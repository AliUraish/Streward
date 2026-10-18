"""Reality layer: resolve/attest/check, verification checks, dispatch, inbound routing, callbacks, mirror."""
import io
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.mirror import Mirror, row_for
from src.signing import verify
from src.verify import iso


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    for key in ("STEWARD_API_TOKEN", "INKBOX_API_KEY", "INKBOX_IDENTITY", "INKBOX_IDENTITY_MYER_TECHNICIAN", "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
                "STEWARD_INBOUND_SECRET", "INKBOX_WEBHOOK_SIGNING_KEY"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def reality(client):
    return client.app.state.service.reality


def resolve(client, tag, attribute, **extra):
    response = client.post("/api/properties/myer-plant/resolve", json={"assetTag": tag, "attribute": attribute, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_resolve_known_unknown_stale_and_conflict(client):
    known = resolve(client, "P-101", "commissioning_certificate")
    assert known["status"] == "known" and known["attestationId"].startswith("att-")
    assert client.get(f"/api/attestations/{known['attestationId']}").json()["valid"] is True
    assert resolve(client, "V-501", "position")["status"] == "known"
    unknown = resolve(client, "P-101", "pressure_bar")
    assert unknown["status"] == "unknown" and "budget > 0" in unknown["nextStep"] and "workItemId" not in unknown
    # maxAgeHours tighter than the age makes a known reading stale without a budget.
    stale = resolve(client, "V-501", "position", maxAgeHours=0.1)
    assert stale["status"] == "stale" and stale["value"] == "open" and "workItemId" not in stale
    # Conflicting accepted facts inside the TTL open a clarification work item.
    service = reality(client)
    valve = service.component_by_tag("myer-plant", "V-501")
    service.write_fact("myer-plant", valve, "position", "reading", "closed", None, iso(datetime.now(timezone.utc) - timedelta(minutes=10)),
                       {"kind": "agent", "ref": "test"}, [], ["0" * 64])
    conflict = resolve(client, "V-501", "position")
    assert conflict["status"] == "conflict" and len(conflict["conflicts"]) == 2 and conflict["workState"] == "needs_clarification"
    assert resolve(client, "V-501", "position")["workItemId"] == conflict["workItemId"]
    # A stale reading with a budget dispatches once; a second call returns the same open item.
    gauge = service.component_by_tag("myer-plant", "PG-601")
    service.write_fact("myer-plant", gauge, "pressure_bar", "reading", 2.0, "bar", iso(datetime.now(timezone.utc) - timedelta(hours=3)),
                       {"kind": "human", "ref": "test"}, [], ["1" * 64])
    first = resolve(client, "PG-601", "pressure_bar", budget=1)
    assert first["status"] == "stale" and first["value"] == 2.0 and first["workState"] == "waiting" and first["dispatchedVia"] == "local"
    assert resolve(client, "PG-601", "pressure_bar", budget=1)["workItemId"] == first["workItemId"]
    assert resolve(client, "PG-601", "pressure_bar")["reference"] == first["reference"]


def test_unsupported_attribute_and_unknown_asset_return_typed_errors(client):
    bad = client.post("/api/properties/myer-plant/resolve", json={"assetTag": "P-101", "attribute": "colour"})
    assert bad.status_code == 400
    assert bad.json()["code"] == "UNSUPPORTED_ATTRIBUTE" and "pressure_bar" in bad.json()["detail"] and bad.json()["recovery"]
    missing = client.post("/api/properties/myer-plant/resolve", json={"assetTag": "ZZ-999", "attribute": "serial"})
    assert missing.status_code == 404 and missing.json()["code"] == "UNKNOWN_ASSET"
    specs = client.get("/api/properties/myer-plant/specs").json()
    assert specs["kinds"]["pump"]["pressure_bar"]["max"] == 3.5 and specs["ttlSecondsByClass"]["identity"] is None
    assert client.get("/api/work-items/wi-nope").json()["code"] == "NOT_FOUND"


def test_dispatch_builds_task_card_with_reference_and_neighbours(client):
    result = resolve(client, "P-101", "pressure_bar", budget=5, requester="restart-agent")
    assert result["status"] == "unknown" and result["reference"] == "MY-P101-PRESSURE_BAR-0001"
    item = client.get(f"/api/work-items/{result['workItemId']}").json()
    assert item["state"] == "waiting" and item["requester"] == "restart-agent" and item["budget"] == 5
    card = item["dispatches"][0]["body"]
    assert "Myer Plant Room" in card and "north wall" in card and "P-101" in card and "1.5 to 3.5 bar" in card and item["reference"] in card
    assert "P-102" in card and "PG-601" in card
    assert item["dispatches"][0]["providerRef"] is None and item["dispatches"][0]["channel"] == "local"
    assert "_threadRef" not in json.dumps(item)


def test_attest_wrong_tag_is_rejected_with_direction(client):
    result = resolve(client, "P-101", "pressure_bar", budget=5)
    response = client.post("/api/properties/myer-plant/attest", json={
        "assetTag": "P-101", "attribute": "pressure_bar", "value": 2.4, "statedTag": "P-102",
        "source": {"kind": "human", "ref": "sms:1"}, "workItemId": result["workItemId"]})
    assert response.status_code == 200
    verdict = response.json()
    assert verdict["verdict"] == "rejected"
    identity = next(c for c in verdict["checks"] if c["name"] == "identity")
    assert identity["passed"] is False
    assert identity["reason"] == "tag plate reads P-102, expected P-101, P-101 is 1.9 m west of P-102"
    assert "factId" not in verdict
    item = client.get(f"/api/work-items/{result['workItemId']}").json()
    assert item["state"] == "waiting" and item["verdicts"][0]["verdict"] == "rejected"
    assert client.get("/api/properties/myer-plant/facts?assetTag=P-101&attribute=pressure_bar").json() == []


def test_plausibility_and_enum_checks(client):
    high = client.post("/api/properties/myer-plant/attest", json={"assetTag": "P-101", "attribute": "pressure_bar", "value": 9.8, "statedTag": "P-101",
                                                              "source": {"kind": "human", "ref": "t"}}).json()
    assert high["verdict"] == "needs_clarification"
    assert "9.8 bar exceeds 3.5 bar spec; confirm with a second reading" in high["reasons"]
    bad_enum = client.post("/api/properties/myer-plant/attest", json={"assetTag": "V-502", "attribute": "position", "value": "ajar", "statedTag": "V-502",
                                                                  "source": {"kind": "human", "ref": "t"}}).json()
    assert bad_enum["verdict"] == "rejected" and any("ajar" in r for r in bad_enum["reasons"])
    no_tag = client.post("/api/properties/myer-plant/attest", json={"assetTag": "V-502", "attribute": "position", "value": "open",
                                                                "source": {"kind": "human", "ref": "t"}}).json()
    assert no_tag["verdict"] == "needs_clarification" and any("tag plate" in r for r in no_tag["reasons"])
    good = client.post("/api/properties/myer-plant/attest", json={"assetTag": "V-502", "attribute": "position", "value": "Open", "statedTag": "V-502",
                                                              "source": {"kind": "agent", "ref": "planner"}}).json()
    assert good["verdict"] == "accepted" and good["factId"]
    fact = client.get("/api/properties/myer-plant/facts?assetTag=V-502&attribute=position").json()[0]
    assert fact["value"] == "open" and fact["status"] == "known" and fact["ttlSeconds"] == 3600 and fact["source"]["kind"] == "agent"


def test_integrity_reuse_across_work_items_is_rejected(client):
    first = resolve(client, "P-101", "pressure_bar", budget=5)
    photo = b"\x89PNG\r\n\x1a\nfake-gauge-photo"
    accepted = client.post("/api/properties/myer-plant/attest", data={"assetTag": "P-101", "attribute": "pressure_bar", "value": "2.4", "statedTag": "P-101",
                                                                  "workItemId": first["workItemId"], "source": json.dumps({"kind": "human", "ref": "mms:1"})},
                           files={"file": ("P-101.png", photo, "image/png")}).json()
    assert accepted["verdict"] == "accepted", accepted
    assert client.get(f"/api/work-items/{first['workItemId']}").json()["state"] == "resolved"
    second = resolve(client, "P-102", "pressure_bar", budget=5)
    reused = client.post("/api/properties/myer-plant/attest", data={"assetTag": "P-102", "attribute": "pressure_bar", "value": "2.2", "statedTag": "P-102",
                                                                "workItemId": second["workItemId"], "source": json.dumps({"kind": "human", "ref": "mms:2"})},
                         files={"file": ("P-102.png", photo, "image/png")}).json()
    assert reused["verdict"] == "rejected"
    assert any(r.startswith("evidence reused from " + first["workItemId"]) for r in reused["reasons"])


def test_exif_timestamp_is_used_when_present(client):
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (4, 4), (10, 20, 30))
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = "2020:01:01 10:00:00"
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif.tobytes())
    old = client.post("/api/properties/myer-plant/attest", data={"assetTag": "P-101", "attribute": "pressure_bar", "value": "2.4", "statedTag": "P-101",
                                                             "source": json.dumps({"kind": "human", "ref": "t"})},
                      files={"file": ("P-101.jpg", buffer.getvalue(), "image/jpeg")}).json()
    time_check = next(c for c in old["checks"] if c["name"] == "time")
    assert old["verdict"] == "rejected" and time_check["passed"] is False and "EXIF DateTimeOriginal" in time_check["reason"] and "2020-01-01T10:00:00Z" in time_check["reason"]


def test_attestation_signature_verifies_and_tampering_fails(client):
    public_key = client.get("/api/attestations/public-key").json()
    assert public_key["algorithm"] == "ed25519" and public_key["verifierVersion"] == "steward-verify/1"
    accepted = client.post("/api/properties/myer-plant/attest", json={"assetTag": "P-101", "attribute": "pressure_bar", "value": 2.4, "statedTag": "P-101",
                                                                  "source": {"kind": "human", "ref": "t"}}).json()
    record = client.get(f"/api/attestations/{accepted['attestationId']}").json()
    assert record["valid"] is True and record["publicKey"] == public_key["publicKey"] and record["verdict"] == "accepted"
    assert [c["name"] for c in record["checks"]] == ["scope", "identity", "geometry", "plausibility", "time", "integrity"]
    payload = {k: v for k, v in record.items() if k not in ("signature", "valid")}
    assert verify(payload, record["signature"], record["publicKey"]) is True
    assert verify({**payload, "value": 9.9}, record["signature"], record["publicKey"]) is False
    tampered = dict(record)
    tampered["value"] = 9.9
    client.app.state.service.store.put("attestation", {k: v for k, v in tampered.items() if k != "valid"}, "myer-plant")
    assert client.get(f"/api/attestations/{accepted['attestationId']}").json()["valid"] is False
    key_path = client.app.state.service.store.directory / "signing.key"
    assert key_path.exists() and (key_path.stat().st_mode & 0o777) == 0o600


def test_local_inbound_routes_by_reference_then_sender(client):
    result = resolve(client, "P-101", "pressure_bar", budget=5)
    wrong = client.post("/api/inbound/local", json={"reference": result["reference"], "body": "Here is the gauge on P-102, it reads 2.4 bar", "sender": "tech-1"}).json()
    assert wrong == {**wrong, "routed": True, "workItemId": result["workItemId"], "verdict": "rejected"}
    item = client.get(f"/api/work-items/{result['workItemId']}").json()
    assert item["dispatches"][-1]["body"].startswith("Rejected: tag plate reads P-102")
    # Reference inside the body, stated tag in the filename, value as multipart field.
    right = client.post("/api/inbound/local", data={"body": f"Re: {result['reference']} gauge photo attached", "value": "2.4", "sender": "tech-1"},
                        files={"file": ("IMG_P-101_gauge.jpg", b"\xff\xd8\xff\xe0not-really-a-jpeg", "image/jpeg")}).json()
    assert right["verdict"] == "accepted" and right["factId"]
    item = client.get(f"/api/work-items/{result['workItemId']}").json()
    assert item["state"] == "resolved" and item["receipt"]["tokensWhileWaiting"] == 0 and item["receipt"]["dispatches"] >= 2
    assert item["receipt"]["estimatedPollingTokens"] % 350 == 0 and item["receipt"]["currency"] == "USD"
    resolved = resolve(client, "P-101", "pressure_bar")
    assert resolved["status"] == "known" and resolved["value"] == 2.4 and resolved["attestationId"] == item["attestationId"]
    # Routing by sender alone for a new item; an unknown message is stored as unrouted with a Change.
    another = resolve(client, "P-103", "pressure_bar", budget=5)
    by_sender = client.post("/api/inbound/local", json={"body": "P-103 shows 2.0 bar", "sender": ""}).json()
    assert by_sender["routed"] is False and by_sender["unroutedId"].startswith("inb-")
    by_reference = client.post("/api/inbound/local", json={"reference": another["reference"], "body": "P-103 shows 2.0 bar", "statedTag": "P-103"}).json()
    assert by_reference["routed"] is True and by_reference["verdict"] == "accepted"
    changes = client.get("/api/properties/myer-plant/changes?since=0&limit=1000").json()
    assert any(c["summary"].startswith("Unrouted inbound") for c in changes["changes"])
    assert changes["version"] == max(c["version"] for c in changes["changes"]) and changes["waiting"] == []


def test_changes_are_monotonic_and_waiting_lists_open_items(client):
    before = client.get("/api/properties/myer-plant/changes").json()
    result = resolve(client, "P-101", "pressure_bar", budget=5)
    after = client.get(f"/api/properties/myer-plant/changes?since={before['version']}").json()
    assert after["version"] > before["version"]
    assert [c["version"] for c in after["changes"]] == sorted(c["version"] for c in after["changes"])
    assert {c["type"] for c in after["changes"]} >= {"work_item", "dispatch"}
    assert after["waiting"][0]["id"] == result["workItemId"]


class _Collector(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        _Collector.received.append(json.loads(self.rfile.read(length)))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_subscription_callback_is_delivered_to_local_server(client):
    _Collector.received = []
    server = HTTPServer(("127.0.0.1", 0), _Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/callback"
        assert client.post("/api/properties/myer-plant/subscriptions", json={"callbackUrl": "ftp://example.com/x"}).json()["code"] == "INVALID_CALLBACK"
        subscription = client.post("/api/properties/myer-plant/subscriptions", json={"callbackUrl": url, "requester": "planner"}).json()
        assert subscription["id"].startswith("sub-") and subscription["propertyId"] == "myer-plant"
        result = resolve(client, "P-101", "pressure_bar", budget=5)
        client.post("/api/inbound/local", json={"reference": result["reference"], "body": "P-101 reads 2.4 bar"})
        deadline = time.time() + 10
        while time.time() < deadline and not any(e.get("workItem", {}).get("state") == "resolved" for e in _Collector.received):
            time.sleep(0.05)
        assert all(e["event"] == "steward.change" and e["change"]["propertyId"] == "myer-plant" for e in _Collector.received)
        assert any(e["change"]["type"] == "fact" for e in _Collector.received)
        assert any(e.get("workItem", {}).get("state") == "resolved" for e in _Collector.received)
        events = client.get("/api/properties/myer-plant/events").json()
        assert any(e["type"] == "subscription.delivered" for e in events)
    finally:
        server.shutdown()


def test_patrol_writes_identity_and_simulated_sensor_facts(client):
    response = client.post("/api/properties/myer-plant/patrol", json={"scope": "all"})
    assert response.status_code == 202
    job = response.json()
    assert job["kind"] == "inspection" and job["patrolFacts"] >= 23
    facts = client.get("/api/properties/myer-plant/facts").json()
    serials = [f for f in facts if f["attribute"] == "serial"]
    assert len(serials) == 21 and all(f["source"] == {"kind": "patrol", "ref": job["id"]} for f in serials)
    assert all(f["ttlSeconds"] is None and f["expiresAt"] is None and f["status"] == "known" for f in serials)
    sensors = [f for f in facts if f["attribute"] == "temperature_c"]
    assert {f["source"]["ref"] for f in sensors} == {"sim:TS-801", "sim:TS-802"} and all(f["source"]["kind"] == "sensor" for f in sensors)
    assert all(18 <= f["value"] <= 24 and f["unit"] == "°C" for f in sensors)
    changes = client.get("/api/properties/myer-plant/changes?limit=1000").json()["changes"]
    assert sum(c["type"] == "fact" and c["refId"] in {f["id"] for f in facts} for c in changes) >= 23
    assert client.post("/api/properties/myer-plant/patrol", json={"scope": "nothing-here"}).json()["code"] == "UNKNOWN_SCOPE"
    # Scoped patrol still reuses the running inspection job.
    scoped = client.post("/api/properties/myer-plant/patrol", json={"scope": "sensor-01"}).json()
    assert scoped["id"] == job["id"] and scoped["patrolFacts"] == 2


def test_context_min_fits_the_token_budget(client):
    resolve(client, "P-101", "pressure_bar", budget=5)
    context = client.get("/api/properties/myer-plant/context.min").json()
    assert context["propertyId"] == "myer-plant" and context["assets"] == 24 and context["facts"]["known"] >= 25
    assert context["blockers"][0]["reference"].startswith("MY-P101-PRESSURE_BAR-") and context["blockers"][0]["state"] == "waiting"
    assert {s["assetTag"] for s in context["sensors"]} == {"TS-801", "TS-802"}
    assert len(json.dumps(context, separators=(",", ":"))) <= 1600


def test_escalation_ladder_scheduler_and_expiry(client, monkeypatch):
    result = resolve(client, "P-101", "pressure_bar", budget=5)
    escalated = client.post(f"/api/work-items/{result['workItemId']}/escalate", json={"level": 3, "note": "urgent"}).json()
    assert escalated["state"] == "escalated" and escalated["escalationLevel"] == 3
    call = escalated["dispatches"][-1]
    assert call["channel"] == "call" and call["providerRef"] is None and call["body"].startswith("[not sent:")
    assert client.post(f"/api/work-items/{result['workItemId']}/escalate", json={"level": 7}).status_code == 422
    service = reality(client)
    item = service.work_item(result["workItemId"])
    created = datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))
    deadline = datetime.fromisoformat(item["deadlineAt"].replace("Z", "+00:00"))
    span = deadline - created
    assert service.tick(created + span * 0.6) == {"expired": 0, "escalated": 0}  # level 1 already covered by level 3
    assert service.tick(created + span * 0.96) == {"expired": 0, "escalated": 1}
    assert service.work_item(result["workItemId"])["escalationLevel"] == 4
    assert service.tick(deadline + timedelta(seconds=1)) == {"expired": 1, "escalated": 0}
    expired = client.get(f"/api/work-items/{result['workItemId']}").json()
    assert expired["state"] == "expired"
    assert client.post(f"/api/work-items/{result['workItemId']}/escalate", json={"level": 1}).json()["code"] == "WORK_ITEM_CLOSED"
    # A reply after expiry is recorded but not verified.
    late = client.post("/api/inbound/local", json={"reference": result["reference"], "body": "P-101 reads 2.4 bar"}).json()
    assert late["routed"] is True and late["verdict"] is None
    # A fresh resolve opens a new work item with the next sequence number.
    again = resolve(client, "P-101", "pressure_bar", budget=5)
    assert again["reference"] == "MY-P101-PRESSURE_BAR-0002"


def test_owner_decision_resolves_with_an_owner_fact(client):
    result = resolve(client, "P-101", "pressure_bar", budget=5)
    decided = client.post("/api/properties/myer-plant/owner-decision", json={"workItemId": result["workItemId"], "decision": "hold", "note": "await reading"}).json()
    assert decided["state"] == "resolved" and decided["factId"]
    fact = client.get("/api/properties/myer-plant/facts?assetTag=P-101&attribute=owner_decision").json()[0]
    assert fact["source"]["kind"] == "owner" and fact["value"] == "hold" and fact["attributeClass"] == "condition"
    changes = client.get("/api/properties/myer-plant/changes?limit=1000").json()["changes"]
    assert any(c["type"] == "owner_decision" and c["refId"] == result["workItemId"] for c in changes)
    assert client.post("/api/properties/bristol-pumps/owner-decision", json={"workItemId": result["workItemId"], "decision": "hold"}).json()["code"] == "SCOPE"


def test_clearance_corridor_reports_first_blocking_footprint(client):
    blocked = client.post("/api/properties/myer-plant/clearance", json={"from": [-5, -0.6], "to": [3, -0.6], "widthM": 0.8}).json()
    assert blocked["clear"] is False and blocked["blockingAssetTag"] == "TS-801" and blocked["path"] == [[-5, -0.6], [3, -0.6]]
    clear = client.post("/api/properties/myer-plant/clearance", json={"from": [-5, 2.5], "to": [5, 2.5], "widthM": 0.8}).json()
    assert clear["clear"] is True and clear["blockingAssetTag"] is None and clear["widthM"] == 0.8
    assert client.post("/api/properties/myer-plant/clearance", json={"from": [0, 0], "to": [1, 1], "widthM": 0}).status_code == 422


def test_inkbox_inbound_requires_secret_and_parses_webhook(client, monkeypatch):
    stamp = iso(datetime.now(timezone.utc))
    payload = {"id": "evt_1", "event_type": "text.received", "timestamp": stamp, "data": {
        "text_message": {"id": "txt_1", "direction": "inbound", "local_phone_number": "+15550000009", "remote_phone_number": "+15550000000",
                         "text": "", "type": "sms", "media": None, "is_read": False, "conversation_id": "conv_1", "created_at": stamp},
        "contacts": [], "agent_identities": [{"id": "x", "agent_handle": "steward-myer-technician", "display_name": None}], "recipient_phone_number": "+15550000009"}}
    assert client.post("/api/inbound/inkbox", json=payload).status_code == 401
    monkeypatch.setenv("STEWARD_INBOUND_SECRET", "s3cret")
    assert client.post("/api/inbound/inkbox", json=payload, headers={"X-Steward-Inbound-Secret": "wrong"}).status_code == 401
    monkeypatch.setenv("INKBOX_IDENTITY_MYER_TECHNICIAN", "steward-myer-technician")
    result = resolve(client, "P-101", "pressure_bar", budget=5)
    payload["data"]["text_message"]["text"] = f"{result['reference']} P-101 reads 2.4 bar"
    routed = client.post("/api/inbound/inkbox", json=payload, headers={"X-Steward-Inbound-Secret": "s3cret"}).json()
    assert routed["routed"] is True and routed["verdict"] == "accepted" and routed["workItemId"] == result["workItemId"]
    duplicate = client.post("/api/inbound/inkbox", json=payload, headers={"Authorization": "Bearer s3cret"}).json()
    assert duplicate == {"routed": False, "duplicate": True}
    lifecycle = client.post("/api/inbound/inkbox", json={"id": "evt_2", "event_type": "text.delivered", "data": {}}, headers={"X-Steward-Inbound-Secret": "s3cret"}).json()
    assert lifecycle["ignored"] is True
    # Sender-only routing scoped to the receiving identity's site.
    another = resolve(client, "P-102", "pressure_bar", budget=5)
    item = reality(client).work_item(another["workItemId"])
    item["dispatches"][0]["to"] = "+15550000000"
    reality(client).save_work_item(item)
    payload.update(id="evt_3")
    payload["data"]["text_message"].update(id="txt_3", conversation_id="conv_9", text="P-102 reads 2.6 bar")
    by_sender = client.post("/api/inbound/inkbox", json=payload, headers={"X-Steward-Inbound-Secret": "s3cret"}).json()
    assert by_sender["workItemId"] == another["workItemId"] and by_sender["verdict"] == "accepted"
    # Without INKBOX_API_KEY the integration stays not_configured even after a webhook; no fabricated connection.
    assert next(i for i in client.get("/api/integrations").json() if i["id"] == "inkbox")["status"] == "not_configured"


def test_outbound_sends_stay_gated_without_configuration(client, monkeypatch):
    from src.providers import InkboxAdapter, ProviderNotConfigured
    adapter = InkboxAdapter()
    with pytest.raises(ProviderNotConfigured):
        adapter.send_sms("myer-plant", "+15550000000", "hi")
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "someone@example.com")
    with pytest.raises(ValueError):
        adapter.place_call("myer-plant", "+15550000000", "script")
    assert adapter.identity_handle("myer-plant") == ""
    monkeypatch.setenv("INKBOX_IDENTITY", "shared")
    monkeypatch.setenv("INKBOX_IDENTITY_MYER_TECHNICIAN", "steward-myer-technician")
    # Contract 4: the site identity that emails task cards is its Field Technician; the shared identity is the fallback.
    assert adapter.identity_handle("myer-plant") == "steward-myer-technician" and adapter.identity_handle("bristol-pumps") == "shared"
    assert adapter.phone_identity_handle("bristol-pumps") == "shared"
    monkeypatch.setenv("INKBOX_PHONE_IDENTITY", "steward-legacy-phone")
    assert adapter.phone_identity_handle("myer-plant") == "steward-legacy-phone"
    # The shared dispatch line owns the only number and wins over the legacy name.
    monkeypatch.setenv("INKBOX_IDENTITY_DISPATCH", "steward-runner")
    assert adapter.phone_identity_handle("myer-plant") == "steward-runner" and adapter.phone_identity_handle("bristol-pumps") == "steward-runner"
    monkeypatch.setenv("INKBOX_IDENTITY_BRISTOL_COMPLIANCE", "steward-bristol-compliance")
    assert adapter.site_for_handle("steward-myer-technician@inkboxmail.com") == "myer-plant" and adapter.site_for_handle("nobody") is None
    assert adapter.site_for_handle("steward-bristol-compliance") == "bristol-pumps"
    # Retired identities are never read for routing.
    monkeypatch.setenv("INKBOX_IDENTITY_WARDEN_MYER_PLANT", "steward-warden-myer")
    assert adapter.site_for_handle("steward-warden-myer") is None


def test_supabase_mirror_upserts_in_background_and_reports_status(client, monkeypatch):
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.url.path, dict(request.headers), json.loads(request.content)))
        return httpx.Response(201)

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    service = reality(client)
    service.mirror.close()
    service.mirror = Mirror(service.store, transport=httpx.MockTransport(handler))
    result = resolve(client, "P-101", "pressure_bar", budget=5)
    service.mirror.executor.shutdown(wait=True)
    tables = {path for path, _, _ in calls}
    assert tables >= {"/rest/v1/work_items", "/rest/v1/dispatches", "/rest/v1/changes"}
    headers = calls[0][1]
    assert headers["apikey"] == "service-key" and headers["authorization"] == "Bearer service-key" and "merge-duplicates" in headers["prefer"]
    work_item_row = next(rows[0] for path, _, rows in calls if path == "/rest/v1/work_items")
    assert work_item_row["id"] == result["workItemId"] and work_item_row["property_id"] == "myer-plant" and "asset_tag" in work_item_row
    assert "_threadRef" not in json.dumps(work_item_row) and isinstance(work_item_row["dispatches"], list)
    assert {i["id"]: i["status"] for i in client.get("/api/integrations").json()}["supabase"] == "connected"
    service.mirror = Mirror(service.store, transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    service.emit_change("myer-plant", "fact", "x", "failing mirror")
    service.mirror.executor.shutdown(wait=True)
    assert {i["id"]: i["status"] for i in client.get("/api/integrations").json()}["supabase"] == "error"
    assert any(e["type"] == "mirror.failed" for e in client.get("/api/properties/myer-plant/events").json())
    assert row_for("fact", {"attestationId": "a", "_secret": 1, "source": {"kind": "x"}}) == {"attestation_id": "a", "source": {"kind": "x"}}


def test_seed_is_idempotent_across_restart(tmp_path, monkeypatch):
    from src.service import PropertyService
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    first = PropertyService(tmp_path / "d", start_workers=False)
    count = len(first.store.all("fact", "myer-plant"))
    version = first.reality.version("myer-plant")
    key = first.reality.signer.public_key_b64
    first.close()
    second = PropertyService(tmp_path / "d", start_workers=False)
    assert len(second.store.all("fact", "myer-plant")) == count and second.reality.version("myer-plant") == version
    assert second.reality.signer.public_key_b64 == key
    assert {f["attribute"] for f in second.store.all("fact", "bristol-pumps")} == {"serial"}
    assert {(f["assetTag"], f["attribute"]) for f in second.store.all("fact", "myer-plant") if f["attribute"] != "serial"} == {
        ("P-101", "commissioning_certificate"), ("V-501", "position"), ("TS-801", "temperature_c"), ("TS-802", "temperature_c"),
        ("DB-401", "status"), ("FE-1001", "pressure_ok"), ("D-1101", "closed")}
    second.close()
