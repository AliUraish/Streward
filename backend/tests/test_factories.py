"""Contracts 3 and 4: two scanned factories, per-site registers and 3D pins, the viewer stream, the agent roster and
runtime settings, crew/obligations/documents, scenarios, conversations, waits, vision ingest, overview and activity,
memory, eval findings and metrics, synthetic data, the Supabase mirror, the agent eye, metrics, regulations, the fix
workflow and cross-factory maintenance. Every external transport is mocked; nothing leaves the machine."""
import asyncio
import base64
import io
import json
import sqlite3
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.service import PropertyService

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def jpeg_bytes(color=(90, 90, 90)) -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def start_scenario(client, scenario_id, **body):
    response = client.post(f"/api/scenarios/{scenario_id}/start", json={"speed": 0, **body})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["state"] == "completed", run
    return run


def snapshot(service, kinds=("fact", "attestation", "requirement", "obligation", "component", "evidence")):
    return {kind: sorted(json.dumps(r, sort_keys=True) for r in service.store.all(kind)) for kind in kinds}


# ---- 1. two sites, retirement, registers, 3D pins ------------------------------------------------------------------

def test_harbor_works_is_retired_with_a_backup_once(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "retire"
    first = PropertyService(directory, start_workers=False)
    harbor = dict(first.store.get("property", MY), id="harbor-works", name="Harbor Works")
    first.store.put("property", harbor)
    first.store.put("component", dict(first.store.all("component", MY)[0]), "harbor-works")
    first.store.put("work_item", dict(id="wi-harbor", propertyId="harbor-works", state="waiting", assetTag="P-101"), "harbor-works")
    first.store.put("agent", dict(id="agent-harbor-works", name="Warden · Harbor Works"))
    first.store.event("harbor-works", "agent-harbor-works", "x", "old", "old event")
    first.store.meta("reality:version:harbor-works", "42")
    first.close()
    with sqlite3.connect(directory / "steward.sqlite3") as db:
        db.execute("DELETE FROM meta WHERE key='steward_retired_sites_version'")
    upgraded = PropertyService(directory, start_workers=False)
    store = upgraded.store
    assert [p["id"] for p in store.all("property")] == [MY, BR, TM]
    assert store.get("work_item", "wi-harbor") is None and store.get("agent", "agent-harbor-works") is None
    with store.connect() as db:
        archived = db.execute("SELECT COUNT(*) FROM records WHERE kind LIKE 'archived:%' AND property_id='archived:harbor-works'").fetchone()[0]
        assert archived == 4  # property, component, work item, legacy agent
        assert db.execute("SELECT COUNT(*) FROM events WHERE property_id='harbor-works'").fetchone()[0] == 0
    assert store.meta("reality:version:harbor-works") is None and store.meta("archived:reality:version:harbor-works") == "42"
    assert any(p.name.startswith("pre-two-sites-") for p in (directory / ".migration-backups").iterdir())
    upgraded.close()
    again = PropertyService(directory, start_workers=False)
    assert len([p for p in (directory / ".migration-backups").iterdir() if p.name.startswith("pre-two-sites-")]) == 1
    assert [p["id"] for p in again.store.all("property")] == [MY, BR, TM]
    again.close()


def test_old_register_is_synced_to_the_per_site_registers(tmp_path, monkeypatch):
    """A database seeded with the old shared register gets Bristol's pump-house register; Myer keeps its tags."""
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "registers"
    first = PropertyService(directory, start_workers=False)
    myer_component = first.store.get("component", "pump-01", MY)
    old_bristol = dict(myer_component, pin={"x": 0.4, "y": 0.6}, pinSource=None)  # an old 2-D pin, the old shared register
    first.store.put("component", old_bristol, BR)
    first.store.put("requirement", dict(id="bristol-pumps-pump-01-cond", componentId="pump-01", status="pending", sourceId="bristol-pumps-spec"), BR)
    fact = dict(first.store.all("fact", MY)[0], id="fact-old", assetTag="P-101", propertyId=BR)
    first.store.put("fact", fact, BR)
    myer_pump = first.store.get("component", "pump-01", MY)
    myer_pump["pin"] = {"x": 1.0, "y": 0.5, "z": -0.25}
    myer_pump["pinSource"] = "placed"
    first.store.put("component", myer_pump, MY)
    first.close()
    with sqlite3.connect(directory / "steward.sqlite3") as db:
        db.execute("DELETE FROM meta WHERE key='steward_register_version'")
    synced = PropertyService(directory, start_workers=False)
    bristol = {c["id"]: c for c in synced.store.all("component", BR)}
    assert len(bristol) == 24 and "pump-01" not in bristol and bristol["sump-01"]["tag"] == "SU-201"
    assert synced.store.get("requirement", "bristol-pumps-pump-01-cond", BR) is None and synced.store.get("fact", "fact-old", BR) is None
    assert all(c["pinSource"] == "estimated" and "z" in c["pin"] for c in bristol.values())
    assert synced.store.get("component", "pump-01", MY)["pin"] == {"x": 1.0, "y": 0.5, "z": -0.25}  # a placed pin survives
    assert "SU-201" in synced.store.get("document", "bristol-pumps-register", BR)["extractedText"]
    synced.close()


def test_pins_can_be_placed_and_reset_by_the_owners_agent_only(client):
    component = client.get(f"/api/properties/{MY}/components/valve-01").json()
    assert component["pinSource"] == "estimated" and {"x", "y", "z"} <= set(component["pin"])
    placed = client.put(f"/api/properties/{MY}/assets/V-501/pin", json={"x": 1.25, "y": -0.4, "z": 2.5, "source": "placed"})
    assert placed.status_code == 200 and placed.json()["pin"] == {"x": 1.25, "y": -0.4, "z": 2.5} and placed.json()["pinSource"] == "placed"
    assert any(c["type"] == "pin" and c["assetTag"] == "V-501" for c in client.get(f"/api/properties/{MY}/changes?limit=1000").json()["changes"])
    scene = client.get(f"/api/properties/{MY}/scene").json()
    assert scene["sogMetaUrl"].endswith("/66b655d3/v1/meta.json") and "azha007" in scene["credit"] and scene["cameraPresets"][0]["fov"] == 75
    assert next(a for a in scene["assets"] if a["assetTag"] == "V-501")["pinSource"] == "placed" and scene["estimatedPins"] == 23
    assert client.put(f"/api/properties/{MY}/assets/V-501/pin", json={"x": 1e9, "y": 0, "z": 0}).json()["code"] == "INVALID_REQUEST"
    denied = client.put(f"/api/properties/{MY}/assets/V-501/pin", json={"x": 0, "y": 0, "z": 0}, headers={"X-Steward-Actor": "myer-engineer"})
    assert denied.status_code == 403
    reset = client.put(f"/api/properties/{MY}/assets/V-501/pin", json={"source": "estimated"}).json()
    assert reset["pinSource"] == "estimated" and reset["pin"] == component["pin"]
    assert client.put(f"/api/properties/{MY}/assets/ZZ-999/pin", json={"x": 0, "y": 0, "z": 0}).status_code == 404


# ---- 2. viewer command stream ----------------------------------------------------------------------------------------

def test_viewer_command_stream(client):
    first = client.post(f"/api/properties/{BR}/viewer", json={"action": "focus", "assetTag": "SU-201"}, headers={"X-Steward-Actor": "bristol-engineer"})
    assert first.status_code == 201 and first.json()["seq"] == 1 and first.json()["pin"] and first.json()["issuedByName"] == "Site Engineer · Bristol"
    client.post(f"/api/properties/{BR}/viewer", json={"action": "reset"})
    listing = client.get(f"/api/properties/{BR}/viewer?since=1").json()
    assert listing["latest"] == 2 and [c["action"] for c in listing["commands"]] == ["reset"]
    assert client.post(f"/api/properties/{BR}/viewer", json={"action": "orbit"}).json()["code"] == "INVALID_REQUEST"
    assert client.post(f"/api/properties/{BR}/viewer", json={"action": "spin", "assetTag": "SU-201"}).json()["code"] == "INVALID_REQUEST"
    assert client.get(f"/api/properties/{MY}/viewer").json()["commands"] == []


# ---- 3. agents: roster, identities, runtime settings -----------------------------------------------------------------

def test_agent_identities_settings_and_reconfigure(client, monkeypatch):
    from src.agents import email_for, handle_for, key_env_name
    monkeypatch.setenv("INKBOX_IDENTITY_MYER_COMPLIANCE", "steward-myer-compliance")
    monkeypatch.setenv("INKBOX_IDENTITY_DIRECTOR", "steward-ops-director")
    monkeypatch.setenv("INKBOX_IDENTITY_COUNSEL", "steward-counsel")  # retired identity, never read
    monkeypatch.setenv("INKBOX_IDENTITY_DISPATCH", "steward-runner")
    monkeypatch.setenv("STEWARD_DISPATCH_PHONE_NUMBER", "+15550001111")
    assert handle_for("myer-compliance") == "steward-myer-compliance" and email_for("director") == "steward-ops-director@inkboxmail.com"
    assert key_env_name("bristol-technician") == "INKBOX_AGENT_KEY_BRISTOL_TECHNICIAN" and handle_for("bristol-compliance") is None
    agents = {a["id"]: a for a in client.get("/api/agents").json()}
    assert agents["dispatch"]["phone"] == "+15550001111" and agents["dispatch"]["handle"] == "steward-runner"
    assert all(a["phone"] is None for k, a in agents.items() if k != "dispatch")
    config = client.get("/api/agents/bristol-compliance/config").json()
    assert config["version"] == 0 and config["settings"]["documentCache"] is False and config["settings"]["pollStrategy"] == "poll"
    assert client.get("/api/agents/myer-engineer/config").json()["settings"]["pollStrategy"] == "subscribe"
    denied = client.post("/api/agents/bristol-compliance/reconfigure", json={"change": {"documentCache": True}}, headers={"X-Steward-Actor": "bristol-manager"})
    assert denied.status_code == 403
    assert client.post("/api/agents/bristol-compliance/reconfigure", json={"change": {"documentCache": True}}).status_code == 403  # owner's agent: not reconfigure
    bad = client.post("/api/agents/bristol-compliance/reconfigure", json={"change": {"warpDrive": True}}, headers={"X-Steward-Actor": "director"})
    assert bad.json()["code"] == "INVALID_REQUEST"
    done = client.post("/api/agents/bristol-compliance/reconfigure", json={"change": {"documentCache": True, "pollStrategy": "subscribe"}, "reason": "tokens"},
                       headers={"X-Steward-Actor": "director"}).json()
    assert done["version"] == 1 and done["settings"]["documentCache"] is True and done["history"][-1]["by"] == "director"
    via_config = client.post("/api/agents/myer-technician/config", json={"pollIntervalSeconds": 300, "reason": "quiet night"}).json()
    assert via_config["settings"]["pollIntervalSeconds"] == 300 and via_config["history"][-1]["via"] == "config"
    assert any(e["kind"] == "decision" for e in client.get("/api/agents/director/transcript").json())
    assert any(m["kind"] == "reconfigure" for m in client.get("/api/agents/bristol-compliance/memory").json()["local"])


def test_old_agent_ids_are_migrated_once_with_a_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    directory = tmp_path / "agent-ids"
    first = PropertyService(directory, start_workers=False)
    store = first.store
    store.put("a2a_task", dict(id="a2a-old", contextId="ctx-1", caller="atlas", target="warden:bristol-pumps", state="completed", siteId=BR,
                               steward={"siteId": BR, "from": "atlas", "to": "warden:bristol-pumps"}, transport="local", createdAt="2026-10-17T00:00:00Z",
                               updatedAt="2026-10-17T00:00:01Z",
                               messages=[dict(role="caller", at="2026-10-17T00:00:00Z", parts=[{"text": "hi"}, {"data": {"steward": {"from": "atlas", "to": "warden:bristol-pumps"}}}])]), BR)
    store.put("agent_activity", dict(id="runner", currentTask="old"), "")
    store.put("agent_config", dict(id="counsel", agentId="counsel", settings={"documentCache": False}, version=1, history=[dict(by="atlas")]), "")
    store.put("work_item", dict(id="wi-old", propertyId=MY, requester="runner/mission:msn-1", state="resolved", assetTag="P-101"), MY)
    store.put("mission", dict(id="msn-old", siteId=MY, state="completed", steps=[dict(id="s", agentId="counsel", summary="x")]), MY)
    store.put("agent_memory", dict(id="amem-old", agentId="warden:myer-plant", container="steward-warden:myer-plant", content="x", siteId=MY), "")
    store.event(MY, "atlas", "a2a", "old", "old event")
    first.close()
    with sqlite3.connect(directory / "steward.sqlite3") as db:
        db.execute("DELETE FROM meta WHERE key='steward_agent_ids_version'")
    upgraded = PropertyService(directory, start_workers=False)
    store = upgraded.store
    task = store.get("a2a_task", "a2a-old", BR)
    assert (task["caller"], task["target"]) == ("director", "bristol-engineer") and task["steward"]["to"] == "bristol-engineer"
    assert task["messages"][0]["parts"][1]["data"]["steward"]["from"] == "director"
    assert store.get("agent_activity", "myer-technician", "") and store.get("agent_activity", "runner", "") is None
    config = store.get("agent_config", "bristol-compliance", "")
    assert config["agentId"] == "bristol-compliance" and config["history"][0]["by"] == "director"
    assert store.get("work_item", "wi-old", MY)["requester"] == "myer-technician/mission:msn-1"
    assert store.get("mission", "msn-old", MY)["steps"][0]["agentId"] == "myer-compliance"
    memory = store.get("agent_memory", "amem-old", "")
    assert memory["agentId"] == "myer-engineer" and memory["container"] == "steward-myer-engineer"
    assert any(e["agentId"] == "director" and e["title"] == "old" for e in store.events(MY))
    assert any(p.name.startswith("pre-agent-ids-") for p in (directory / ".migration-backups").iterdir())
    upgraded.close()
    again = PropertyService(directory, start_workers=False)
    assert len([p for p in (directory / ".migration-backups").iterdir() if p.name.startswith("pre-agent-ids-")]) == 1
    again.close()


# ---- 4. people and compliance ------------------------------------------------------------------------------------------

def test_crew_obligations_documents_and_responsibility(client, monkeypatch):
    monkeypatch.setenv("INKBOX_CONTRACTOR_PHONE", "+15557654321")
    monkeypatch.setenv("INKBOX_CONTRACTOR_EMAIL", "duty.engineer@example.com")
    crew = client.get(f"/api/properties/{BR}/crew").json()
    duty = next(c for c in crew if c["id"] == "crew-br-duty-engineer")
    assert duty["contactable"] is True and duty["phone"] == "••• ••• 4321" and duty["email"] == "d•••@example.com"
    assert "+15557654321" not in json.dumps(crew) and "duty.engineer@example.com" not in json.dumps(crew)
    others = [c for c in crew if c["id"] != "crew-br-duty-engineer"]
    assert others and all(c["contactable"] is False and c["phone"] is None and c["synthetic"] is True for c in others)
    assert all({"name", "expiresAt", "status"} <= set(cert) for c in crew for cert in c["certifications"])
    obligations = client.get(f"/api/properties/{BR}/obligations").json()
    assert {o["status"] for o in obligations} <= {"ok", "due_soon", "overdue", "blocked"} and all(o["synthetic"] and "DEMO-RP" in o["ruleRef"] for o in obligations)
    assert client.get(f"/api/properties/{BR}/obligations?status=nope").json()["code"] == "INVALID_REQUEST"
    responsible = client.get(f"/api/properties/{BR}/responsible?issueKind=certificate_expired").json()
    assert responsible["owner"]["id"] == "crew-br-restoration-lead" and responsible["agent"] == "bristol-compliance"
    assert responsible["contactPlan"]["reachable"] is False and responsible["contactPlan"]["via"] == "bristol-technician"
    sump = client.get(f"/api/properties/{BR}/responsible?issueKind=sump_overflow").json()
    assert sump["owner"]["id"] == "crew-br-duty-engineer" and sump["contactPlan"]["channel"] == "sms" and sump["agent"] == "bristol-engineer"
    fallback = client.get(f"/api/properties/{MY}/responsible?issueKind=nobody_owns_this").json()
    assert fallback["fallback"] is True and fallback["owner"]["id"] == "crew-my-duty-engineer"
    document = client.get("/api/documents/doc-my-contractor-v504").json()
    assert document["textIsData"] is True and "ignore previous instructions" in document["text"] and document["synthetic"] is True
    assert client.get(document["url"]).content.startswith(b"%PDF")
    request = client.post(f"/api/properties/{BR}/obligations/ob-br-pv301-exam/request-document").json()
    assert request["requestedBy"] == "bristol-compliance" and request["notice"]["mode"] == "not_contactable"
    assert client.post(f"/api/properties/{BR}/obligations/ob-br-pv301-exam/request-document", headers={"X-Steward-Actor": "myer-compliance"}).status_code == 403


def test_send_document_is_dry_run_unless_both_gates_and_uses_the_sdk_attachment_shape(client, monkeypatch):
    service = svc(client)
    dry = client.post("/api/agents/bristol-compliance/send-document", json={"to": "bristol-engineer", "documentId": "doc-br-pv301-cert", "note": "for the file"})
    assert dry.status_code == 201, dry.text
    record = dry.json()
    assert record["mode"] == "dry_run" and "STEWARD_ALLOW_EXTERNAL_MESSAGES is not true" in record["reason"] and record["attachment"]["contentType"] == "application/pdf"
    assert record["review"]["verdict"] == "filed" and record["transport"] == "local"
    sender = client.get("/api/agents/bristol-compliance/transcript").json()
    recipient = client.get("/api/agents/bristol-engineer/transcript").json()
    assert any(e["kind"] == "email" and e["direction"] == "out" and e["text"].startswith("[dry_run]") for e in sender)
    assert any(e["kind"] == "email" and e["direction"] == "in" for e in recipient)
    assert client.post("/api/agents/bristol-engineer/send-document", json={"to": "director", "documentId": "doc-br-pv301-cert"},
                       headers={"X-Steward-Actor": "bristol-engineer"}).status_code == 403
    # Cross-site: compliance may email any agent; the A2A note is skipped when the cross-site rule forbids the message.
    cross = client.post("/api/agents/myer-compliance/send-document", json={"to": "bristol-engineer", "documentId": "doc-my-tk201-scheme"}).json()
    assert cross["a2aTaskId"] is None and "across sites" in cross["a2aSkipped"]
    peer = client.post("/api/agents/myer-compliance/send-document", json={"to": "bristol-compliance", "documentId": "doc-my-tk201-scheme"}).json()
    assert peer["a2aTaskId"] and peer["a2aSkipped"] is None
    # Live path with a fake SDK client: both gates on, both identities and keys present.
    sent = []

    class Message:
        id = "msg-1"

    class Identity:
        def __init__(self, handle):
            self.email_address = f"{handle}@inkboxmail.com"

        def send_email(self, **kwargs):
            sent.append(kwargs)
            return Message()

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_identity(self, handle):
            return Identity(handle)

    for name, value in {"STEWARD_ALLOW_EXTERNAL_MESSAGES": "true", "STEWARD_ALLOW_AGENT_EMAIL": "true", "INKBOX_API_KEY": "key",
                        "INKBOX_IDENTITY_BRISTOL_COMPLIANCE": "steward-bristol-compliance", "INKBOX_IDENTITY_BRISTOL_ENGINEER": "steward-bristol-engineer",
                        "INKBOX_AGENT_KEY_BRISTOL_COMPLIANCE": "agent-key"}.items():
        monkeypatch.setenv(name, value)
    service.people.inkbox_factory = lambda key: FakeClient()
    service.bus.transport_for = lambda *args: "local"  # keep A2A in-process in this test
    live = client.post("/api/agents/bristol-compliance/send-document", json={"to": "bristol-engineer", "documentId": "doc-br-pv301-cert"}).json()
    assert live["mode"] == "sent" and live["providerMessageId"] == "msg-1"
    attachment = sent[0]["attachments"][0]
    assert sent[0]["to"] == ["steward-bristol-engineer@inkboxmail.com"] and attachment["content_type"] == "application/pdf"
    assert base64.b64decode(attachment["content_base64"]).startswith(b"%PDF") and attachment["filename"] == "doc-br-pv301-cert.pdf"


# ---- 5. scenarios, conversations, injection ----------------------------------------------------------------------------

def test_scenarios_list_and_site_scenarios_produce_facts_issues_and_meetings(client):
    scenarios = client.get("/api/scenarios").json()
    assert [s["id"] for s in scenarios] == ["my-overpressure", "my-extinguisher", "br-sump", "br-vessel-cert", "ops-counsel-tokens", "ops-injection", "x-maintenance",
                                            "tm-humidity", "tm-alteration-permit", "x-heritage"]
    assert all(s["synthetic"] is True and s["generator"] == "hand-seed" and s["lastRun"] is None for s in scenarios)
    # Nothing fires until a scenario starts; only the seeded compliance gap is open (contract 7 §6).
    assert [i["kind"] for i in client.get("/api/properties/myer-plant/issues").json()] == ["compliance_overdue"]
    assert client.post("/api/scenarios/br-sump/start", json={"speed": 0}, headers={"X-Steward-Actor": "director"}).status_code == 403
    run = start_scenario(client, "br-sump")
    assert run["log"] and run["siteIds"] == [BR]
    sump = client.get(f"/api/properties/{BR}/facts?assetTag=SU-201&attribute=level_pct").json()[0]
    assert sump["value"] == 96.0 and sump["synthetic"] is True and sump["source"] == {"kind": "sensor", "ref": "scenario:br-sump"}
    issues = [i for i in client.get(f"/api/properties/{BR}/issues").json() if i.get("scenarioId") == "br-sump"]
    assert len(issues) == 1 and issues[0]["kind"] == "sump_overflow" and issues[0]["severity"] == "high" and issues[0]["assetTag"] == "SU-201"
    assert issues[0]["synthetic"] is True and "25 min" in issues[0]["summary"] and issues[0]["ownerId"] == "crew-br-duty-engineer"
    assert not any(i["kind"] == "out_of_range" and i["assetTag"] == "SU-201" for i in client.get(f"/api/properties/{BR}/issues").json())
    meetings = client.get(f"/api/board-meetings?siteId={BR}").json()
    assert len(meetings) == 1 and meetings[0]["kind"] == "meeting" and meetings[0]["convener"] == "bristol-manager"
    meeting = client.get(f"/api/board-meetings/{meetings[0]['id']}").json()
    assert [line["speaker"] for line in meeting["transcript"]][:4] == ["bristol-manager", "bristol-engineer", "bristol-compliance", "bristol-technician"]
    assert meeting["contact"]["crewMemberId"] == "crew-br-duty-engineer" and "Duty engineer" in meeting["resolution"] and meeting["status"] == "resolved"
    assert meeting["summary"]["headline"].startswith("SU-201 at 96") and meeting["summaryBy"] == "hand-seed"
    assert client.get(f"/api/board-meetings?issueId={issues[0]['id']}").json()[0]["id"] == meeting["id"]
    notices = client.get(f"/api/properties/{BR}/notices").json()
    assert {n["noticeKind"] for n in notices} == {"contact", "compliance"} and all(n["mode"] in ("dry_run", "not_contactable") for n in notices)
    assert any(c["action"] == "orbit" and c["assetTag"] == "SU-201" for c in client.get(f"/api/properties/{BR}/viewer").json()["commands"])
    runs = client.get("/api/scenarios").json()
    assert next(s for s in runs if s["id"] == "br-sump")["lastRun"]["state"] == "completed"
    assert any(m["kind"] == "scenario_outcome" for m in client.get("/api/agents/director/memory").json()["local"])


def test_compliance_scenarios_change_obligations_and_send_documents(client):
    start_scenario(client, "my-extinguisher")
    obligations = {o["id"]: o for o in client.get(f"/api/properties/{MY}/obligations").json()}
    assert obligations["ob-my-fe1001-monthly"]["status"] == "overdue" and obligations["ob-my-hotwork-permit"]["status"] == "blocked"
    start_scenario(client, "br-vessel-cert")
    bristol = {o["id"]: o for o in client.get(f"/api/properties/{BR}/obligations").json()}
    assert bristol["ob-br-pv301-exam"]["status"] == "overdue" and bristol["ob-br-steam-demo"]["status"] == "blocked"
    emails = client.get(f"/api/document-emails?siteId={BR}").json()
    assert emails and emails[0]["sender"] == "bristol-compliance" and emails[0]["recipient"] == "bristol-engineer" and emails[0]["mode"] == "dry_run"
    cert = client.get("/api/documents/doc-br-pv301-cert").json()
    assert cert["expiresAt"] < time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def test_injected_document_sentence_never_changes_any_state(client):
    service = svc(client)
    before = snapshot(service)
    issues_before = {i["id"] for i in client.get(f"/api/properties/{MY}/issues?status=all").json()}
    run = start_scenario(client, "ops-injection")
    review = next(line for line in run["log"] if line["type"] == "review_document")
    assert "rejected" in review["summary"] and "treated as data" in review["summary"]
    assert snapshot(service) == before  # no fact, attestation, check, obligation, component or evidence changed
    document = client.get("/api/documents/doc-my-contractor-v504").json()
    assert document["flagged"] is True and document["flags"][0]["kind"] == "instruction_injection" and document["flags"][0]["detectedBy"] == "myer-engineer"
    new = [i for i in client.get(f"/api/properties/{MY}/issues?status=all").json() if i["id"] not in issues_before]
    assert [(i["kind"], i["severity"], i["assetTag"]) for i in new] == [("document_injection", "high", "V-504")]
    reviews = service.store.all("document_review", MY)
    assert reviews[-1]["verdict"] == "rejected" and reviews[-1]["statesChanged"] == ["document.flags", "issue"]
    assert next(c for c in reviews[-1]["checks"] if c["name"] == "instruction")["passed"] is False
    # Re-reviewing the same document does not stack issues or flags.
    service.people.review_document("doc-my-contractor-v504", "myer-engineer")
    assert len(service.store.get("document", "doc-my-contractor-v504", MY)["flags"]) == 1
    assert len([i for i in service.store.all("issue", MY) if i["kind"] == "document_injection"]) == 1


def test_ops_tokens_scenario_measures_reconfigures_and_reruns_the_efficiency_eval(client):
    run = start_scenario(client, "ops-counsel-tokens")
    context = run["context"]
    assert context["before"] > context["after"] * 3 and context["ratio"] >= 5 and context["verdict"] == "passed"
    config = client.get("/api/agents/bristol-compliance/config").json()["settings"]
    assert config == {**config, "documentCache": True, "pollStrategy": "subscribe", "maxTokensPerMission": 8000}
    efficiency = [r for r in client.get("/api/evals").json() if r["suite"] == "efficiency"]
    assert efficiency and efficiency[0]["failed"] == 0 and efficiency[0]["runner"] == "local-telemetry"
    assert efficiency[0]["source"] == "Steward telemetry, also delivered to Armature"
    call = next(c for c in client.get("/api/conversations?agentId=bristol-compliance").json() if c["kind"] == "call")
    assert call["participants"] == ["director", "bristol-compliance"] and call["transport"] == "local" and len(call["a2aTaskIds"]) == 1
    task = client.get(f"/api/a2a/tasks/{call['a2aTaskIds'][0]}").json()
    assert task["state"] == "completed" and len(task["messages"]) == 5  # 4 turns + the closing (end of call)
    findings_step = next(line for line in run["log"] if line["type"] == "findings")
    assert "x the median of its peers" in findings_step["summary"] and findings_step["agentId"] == "director"
    findings = client.get("/api/evals/findings").json()
    assert findings["source"].startswith("Steward telemetry")
    # After the reconfigure its average sits just under the 5x bar; a fresh heavy mission is flagged at once.
    assert not any(f["agentId"] == "bristol-compliance" and f["severity"] == "high" for f in findings["flags"])
    svc(client).telemetry.record("myer-compliance", "document_read", "get_document", tokens=60000, mission_id="heavy-1", site_id=MY)
    flagged = next(f for f in client.get("/api/evals/findings").json()["flags"] if f["agentId"] == "myer-compliance")
    assert flagged["severity"] == "high" and "median" in flagged["finding"]
    assert findings["armature"]["live"] is False and "ARMATURE_API_KEY is unset" in findings["armature"]["detail"]
    activity = client.get("/api/agents/bristol-compliance/activity").json()
    assert activity["tokensThisHour"] > 5000 and activity["settings"]["documentCache"] is True and activity["lastActions"]



def test_ops_tokens_scenario_replays_from_the_shipped_settings(client):
    first = start_scenario(client, "ops-counsel-tokens")
    second = start_scenario(client, "ops-counsel-tokens", restart=True)
    for run in (first, second):
        assert run["context"]["verdict"] == "passed" and run["context"]["before"] > run["context"]["after"] * 3, run["context"]
    assert abs(second["context"]["before"] - first["context"]["before"]) <= first["context"]["before"] * 0.2  # same shipped behaviour measured again
    efficiency = [r for r in client.get("/api/evals").json() if r["suite"] == "efficiency"]
    assert len(efficiency) == 2 and all(r["failed"] == 0 for r in efficiency)
    history = client.get("/api/agents/bristol-compliance/config").json()["history"]
    assert [h["via"] for h in history] == ["reconfigure", "scenario_baseline", "reconfigure"]
    reset = history[1]
    assert reset["by"] == "scenario" and reset["change"]["documentCache"] is False and reset["before"]["documentCache"] is True
    sweep = next(line for line in second["log"] if line["type"] == "compliance_sweep")
    assert "Shipped settings restored" in sweep["summary"]

# ---- 6. waits ---------------------------------------------------------------------------------------------------------

def test_waits_fire_on_matching_changes_and_time_out_cleanly(client):
    service = svc(client)
    created = client.post("/api/waits", json={"event": "issue.changed", "siteId": BR, "filter": {"assetTag": "SU-201"}})
    assert created.status_code == 201
    wait_id = created.json()["id"]
    still = client.get(f"/api/waits/{wait_id}?timeout=0.2").json()
    assert still["status"] == "still_waiting" and still["waitId"] == wait_id
    assert client.get(f"/api/waits/{wait_id}?timeout=301").status_code == 422
    assert client.post("/api/waits", json={"event": "nope"}).json()["code"] == "INVALID_REQUEST"
    other = client.post("/api/waits", json={"event": "issue.changed", "siteId": MY}).json()["id"]

    def later():
        time.sleep(0.3)
        service.issues.raise_issue(BR, "sump_overflow", "medium", "test", asset_tag="SU-201")

    thread = threading.Thread(target=later)
    started = time.monotonic()
    thread.start()
    fired = client.get(f"/api/waits/{wait_id}?timeout=10").json()
    thread.join()
    assert fired["status"] == "fired" and fired["event"]["name"] == "issue.changed" and fired["event"]["change"]["assetTag"] == "SU-201"
    assert time.monotonic() - started < 5  # woke on the Change, not at the timeout
    assert client.get(f"/api/waits/{other}?timeout=0").json()["status"] == "still_waiting"  # other site: no match
    assert client.get(f"/api/waits/{wait_id}?timeout=0").json()["status"] == "fired"  # a fired wait stays fired
    resolved = client.post("/api/waits", json={"event": "work_item.resolved", "siteId": MY}).json()["id"]
    result = client.post(f"/api/properties/{MY}/resolve", json={"assetTag": "P-101", "attribute": "pressure_bar", "budget": 5}).json()
    client.post("/api/inbound/local", json={"reference": result["reference"], "body": "P-101 reads 2.4 bar"})
    assert client.get(f"/api/waits/{resolved}?timeout=0").json()["event"]["change"]["refId"] == result["workItemId"]
    reply = client.post("/api/waits", json={"event": "reply.received"}).json()["id"]
    again = client.post(f"/api/properties/{MY}/resolve", json={"assetTag": "P-102", "attribute": "pressure_bar", "budget": 5}).json()
    client.post("/api/inbound/local", json={"reference": again["reference"], "body": "P-102 reads 2.2 bar"})
    assert client.get(f"/api/waits/{reply}?timeout=0").json()["event"]["name"] == "reply.received"
    assert client.get("/api/waits/wait-missing").status_code == 404


# ---- 7. vision ingest ---------------------------------------------------------------------------------------------------

def test_vision_results_become_findings_and_issues(client):
    results = {"siteId": MY, "model": {"id": "facebook/vjepa2-vitl-fpc64-256"}, "runId": "vrun-test", "mode": "peer", "valves": [
        {"assetTag": "V-501", "status": "fixed", "score": 0.08, "threshold": 0.2, "defect": "none", "frames": ["vision/frames/myer-plant/V-501/f00.jpg"]},
        {"assetTag": "V-504", "status": "not_fixed", "score": 0.41, "threshold": 0.2, "defect": "missing-handwheel", "mode": "baseline",
         "pinWarning": "orbit shows a filter cabinet",
         "explanation": {"finding": "handwheel missing", "evidence": "frames 3-7", "confidence": 0.7, "recommendedAction": "refit"}},
        {"assetTag": "V-503", "status": "uncertain", "score": 0.19, "threshold": 0.2}]}
    ingested = client.post(f"/api/properties/{MY}/inspections/vision", json=results)
    assert ingested.status_code == 201, ingested.text
    body = ingested.json()
    assert body["ingested"] == 3 and body["issuesRaised"] == 2 and "not a trained defect classifier" in body["scoreNote"]
    assert body["unlocated"] == 3  # every pin is still estimated
    listing = client.get(f"/api/properties/{MY}/inspections/vision").json()
    assert listing["counts"] == {"fixed": 1, "not_fixed": 1, "uncertain": 1}
    v504 = next(f for f in listing["findings"] if f["assetTag"] == "V-504")
    assert v504["synthetic"] is True and v504["explanation"]["finding"] == "handwheel missing" and v504["issueId"]
    assert v504["mode"] == "baseline" and v504["pinWarning"] == "orbit shows a filter cabinet" and v504["located"] is False and v504["pinSource"] == "estimated"
    v501 = next(f for f in listing["findings"] if f["assetTag"] == "V-501")
    assert v501["synthetic"] is False and v501["defect"] is None  # defect "none" is not a synthetic defect
    kinds = {i["kind"]: i for i in client.get(f"/api/properties/{MY}/issues").json()}
    assert kinds["valve_not_fixed"]["severity"] == "high" and kinds["valve_uncertain"]["severity"] == "medium"
    assert kinds["valve_not_fixed"]["summary"].startswith("Location unconfirmed (estimated pin): ") and "this valve's own clean baseline" in kinds["valve_not_fixed"]["summary"]
    assert kinds["valve_not_fixed"]["pinSource"] == "estimated" and kinds["valve_not_fixed"]["located"] is False
    results["valves"][1]["status"] = "fixed"
    again = client.post(f"/api/properties/{MY}/inspections/vision", json=results).json()
    assert again["issuesResolved"] == 1 and len(client.get(f"/api/properties/{MY}/inspections/vision").json()["findings"]) == 3
    assert client.post(f"/api/properties/{MY}/inspections/vision", json={"siteId": BR, "valves": []}).status_code == 409
    assert client.post(f"/api/properties/{MY}/inspections/vision", json=[{"assetTag": "V-501", "status": "broken"}]).json()["code"] == "INVALID_REQUEST"
    assert client.post(f"/api/properties/{MY}/inspections/vision", json=[{"assetTag": "V-501", "status": "fixed"}], headers={"X-Steward-Actor": "myer-compliance"}).status_code == 403
    cross = client.post(f"/api/properties/{MY}/inspections/vision", json=[{"assetTag": "V-501", "status": "fixed"}], headers={"X-Steward-Actor": "bristol-engineer"})
    assert cross.status_code == 403 and "own site" in cross.json()["detail"]
    for actor in ("myer-engineer", "myer-manager", "director"):
        assert client.post(f"/api/properties/{MY}/inspections/vision", json=[{"assetTag": "V-501", "status": "fixed"}], headers={"X-Steward-Actor": actor}).status_code == 201


# ---- 8. overview and activity -------------------------------------------------------------------------------------------

def test_overview_is_compact_and_activity_reports_telemetry(client):
    start_scenario(client, "my-overpressure")
    overview = client.get("/api/overview").json()
    assert [s["id"] for s in overview["sites"]] == [MY, BR, TM] and overview["sites"][0]["issues"]["high"] >= 1
    assert {"ok", "due_soon", "overdue", "blocked"} == set(overview["sites"][0]["compliance"]) and overview["sites"][0]["crewOnShift"] == 3
    assert len(overview["agents"]) == 14 and len(overview["lastChanges"]) == 10
    assert not any(c["type"] == "scenario" for c in overview["lastChanges"]), "scenario step rows never reach the overview"
    assert len(json.dumps(overview, separators=(",", ":"))) <= 2400  # ≤ 600 tokens at 4 characters a token
    activity = client.get("/api/agents/myer-manager/activity").json()
    assert activity["tokensThisHour"] > 0 and activity["callsThisHour"] > 0 and activity["telemetrySource"].startswith("Steward telemetry")
    assert activity["memoryHighlights"] and activity["lastActions"][0]["tool"]
    logged = client.post("/api/telemetry", json={"agentId": "myer-engineer", "tool": "get_scene", "tokens": 321, "ms": 12, "siteId": MY})
    assert logged.status_code == 201 and logged.json()["tokens"] == 321
    client.get(f"/api/properties/{MY}/scene", headers={"X-Steward-Tool": "get_scene", "X-Steward-Actor": "myer-engineer"})
    rows = svc(client).telemetry.rows("myer-engineer", limit=5)
    assert rows[0]["kind"] == "mcp" and rows[0]["tool"] == "get_scene" and isinstance(rows[0]["ms"], int)


# ---- 9. memory ------------------------------------------------------------------------------------------------------------

def test_memory_local_mirror_and_supermemory_adapter(client, monkeypatch):
    service = svc(client)
    start_scenario(client, "my-extinguisher")
    recall = client.get("/api/agents/myer-compliance/memory?query=FE-1001").json()
    assert recall["container"] == "steward-myer-compliance" and recall["local"] and all("FE-1001" in m["content"] for m in recall["local"][:1])
    assert recall["supermemory"]["live"] is False
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, str(request.url), json.loads(request.content), request.headers.get("authorization")))
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"id": "r1", "memory": "FE-1001 overdue"}], "searchTime": 12})
        return httpx.Response(200, json={"id": "doc-1", "status": "queued"})

    from src.memory_store import SupermemoryClient
    monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm-key")
    monkeypatch.setenv("STEWARD_SUPERMEMORY_LIVE", "true")
    service.memory.client = SupermemoryClient(transport=httpx.MockTransport(handler))
    written = service.memory.write("myer-engineer", "Decision: isolate at V-501", "decision", {"issueId": "iss-1"}, MY)
    assert written["providerStatus"] == "queued" and written["providerId"] == "doc-1"
    method, url, body, auth = calls[0]
    assert url == "https://api.supermemory.ai/ns/steward-myer-engineer/document" and body["id"] == written["id"] and auth == "Bearer sm-key"
    assert body["metadata"]["agentId"] == "myer-engineer" and "content" in body
    live = client.get("/api/agents/myer-engineer/memory?query=V-501").json()
    assert live["supermemory"]["results"][0]["id"] == "r1" and calls[-1][2] == {"query": "V-501", "searchMode": "hybrid", "limit": 10}
    assert client.get("/api/agents/nobody/memory").status_code == 404


# ---- 10. eval findings and the Armature MCP adapter ------------------------------------------------------------------------

def test_armature_adapter_speaks_streamable_http_json_rpc(monkeypatch):
    from src.armature import ArmatureMCP, ArmatureError
    seen = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((body.get("method"), request.headers.get("authorization"), request.headers.get("mcp-session-id")))
        if body.get("method") == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "sess-1", "content-type": "application/json"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18"}})
        if body.get("method") == "notifications/initialized":
            return httpx.Response(202)
        payload = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": json.dumps({"sessions": [{"id": "s1"}]})}]}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="event: message\ndata: " + json.dumps(payload) + "\n\n")

    adapter = ArmatureMCP(transport=httpx.MockTransport(handler))
    with pytest.raises(ArmatureError):
        adapter.call("list_sessions")  # off by default
    monkeypatch.setenv("ARMATURE_API_KEY", "arm-key")
    assert adapter.findings_section()["live"] is False
    monkeypatch.setenv("STEWARD_ARMATURE_LIVE", "true")
    assert adapter.call("list_sessions", {"limit": 5}) == {"sessions": [{"id": "s1"}]}
    assert seen[0] == ("initialize", "Bearer arm-key", None) and seen[2] == ("tools/call", "Bearer arm-key", "sess-1")
    with pytest.raises(ArmatureError):
        adapter.call("delete_everything")
    section = adapter.findings_section()
    assert section["live"] is True and section["sessions"] == {"sessions": [{"id": "s1"}]}


# ---- 11. synthetic data and the generators -------------------------------------------------------------------------------

def test_every_seed_record_is_labelled_and_generators_default_to_dry_run():
    import importlib.util
    from pathlib import Path
    from src.synthetic import FAMILIES, load_family
    for family in FAMILIES:
        records = load_family(family)
        # Families are either the hand seed or regenerated once by scripts/synth/generate.py --live (Claude Opus 5.5).
        assert records and all(r["synthetic"] is True and r["generator"] in ("hand-seed", "claude-opus-5-5") for r in records), family
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("synth_generate", root / "scripts" / "synth" / "generate.py")
    generate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generate)
    body = generate.request_body("crews")
    assert body["model"] == "claude-opus-5-5" and body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default" and body["betas"] == ["server-side-fallback-2026-07-01"]
    record_schema = body["output_config"]["format"]["schema"]["properties"]["records"]["items"]
    assert record_schema["additionalProperties"] is False and {"id", "siteId", "owns", "certifications"} <= set(record_schema["required"])
    spec = importlib.util.spec_from_file_location("synth_summarise", root / "scripts" / "synth" / "summarise.py")
    summarise = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summarise)
    request = summarise.request_body({"id": "c1", "kind": "call", "topic": "t", "siteIds": [MY], "transcript": [{"name": "A", "text": "hello"}]})
    assert request["output_config"]["format"]["schema"]["required"] == ["headline", "points", "decisions", "actions"] and "hello" in request["messages"][0]["content"]


# ---- 12. Supabase mirror for the new tables ----------------------------------------------------------------------------------

def test_mirror_emits_only_documented_columns_for_new_tables(client, monkeypatch):
    from src.mirror import COLUMNS, TABLES, Mirror, row_for
    assert {"crew_members", "obligations", "issues", "conversations", "viewer_commands", "memories", "telemetry", "findings",
            "notifications", "maintenance_windows", "eye_frames"} <= set(COLUMNS)
    assert row_for("issue", {"id": "i", "siteId": MY, "history": [1], "_private": 1, "candidate": True}) == {"id": "i", "site_id": MY}
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(201)

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    service = svc(client)
    service.reality.mirror.close()
    service.reality.mirror = Mirror(service.store, transport=httpx.MockTransport(handler))
    start_scenario(client, "br-sump")
    service.telemetry.record("bristol-engineer", "tool", "probe", tokens=10, site_id=BR)
    service.reality.mirror.executor.shutdown(wait=True)
    tables = {path.rsplit("/", 1)[-1] for path, _ in calls}
    assert {"issues", "conversations", "viewer_commands", "memories", "telemetry", "changes", "facts"} <= tables
    for path, rows in calls:
        table = path.rsplit("/", 1)[-1]
        assert set(rows[0]) <= set(COLUMNS[table]), (table, set(rows[0]) - set(COLUMNS[table]))
    assert all(t in TABLES.values() for t in tables)


# ---- 13. the agent eye ------------------------------------------------------------------------------------------------------

class FakeRenderer(threading.Thread):
    """A renderer in eye mode: long-polls commands, posts a JPEG per expected frame with pose and visible pins."""

    def __init__(self, client, site, renderer_id="browser-test"):
        super().__init__(daemon=True)
        self.client, self.site, self.renderer_id = client, site, renderer_id
        self.stop = threading.Event()
        self.since = 0
        self.frame = base64.b64encode(jpeg_bytes()).decode()

    def run(self):
        while not self.stop.is_set():
            listing = self.client.get(f"/api/eye/{self.site}/commands", params={"rendererId": self.renderer_id, "since": self.since, "timeout": 1}).json()
            for command in listing.get("commands", []):
                self.since = max(self.since, command["seq"])
                for index in range(command["expectedFrames"]):
                    payload = {"commandId": command["id"], "jpegBase64": "data:image/jpeg;base64," + self.frame, "rendererId": self.renderer_id, "index": index,
                               "camera": {"position": [0, 1.6, 3], "target": [0, 1, 0], "fov": 60},
                               "visiblePins": [{"assetTag": "PG-601", "x": 0.52, "y": 0.48, "distance": 2.1, "occluded": False},
                                               {"assetTag": "V-501", "x": 0.1, "y": 0.2, "distance": 3.0, "occluded": True}]}
                    if command["action"] == "mark":
                        payload["annotation"] = {"world": {"x": 0.1, "y": 0.9, "z": -0.3}}
                    self.client.post(f"/api/eye/{self.site}/frames", json=payload)


def test_agent_eye_register_command_frames_act_and_feed(client):
    registered = client.post(f"/api/eye/{MY}/renderers", json={"rendererId": "browser-test"}).json()
    assert registered["registered"] is True and registered["staleAfterSeconds"] == 15
    renderer = FakeRenderer(client, MY)
    renderer.start()
    try:
        look = client.post(f"/api/eye/{MY}/act", json={"action": "go_to", "params": {"assetTag": "PG-601"}}, headers={"X-Steward-Actor": "myer-engineer"})
        assert look.status_code == 200, look.text
        frame = look.json()
        assert frame["frameUrl"].startswith("/api/eye/frames/") and frame["camera"]["fov"] == 60 and frame["actor"] == "myer-engineer"
        assert frame["visiblePins"][0]["assetTag"] == "PG-601" and frame["params"]["target"]
        assert client.get(frame["frameUrl"]).content[:3] == b"\xff\xd8\xff"
        orbit = client.post(f"/api/eye/{MY}/act", json={"action": "orbit", "params": {"assetTag": "PG-601", "frames": 4}},
                            headers={"X-Steward-Actor": "myer-manager"}).json()
        assert [f["index"] for f in orbit["frames"]] == [0, 1, 2, 3]
        moved = client.post(f"/api/eye/{MY}/act", json={"action": "move", "params": {"direction": "forward", "meters": 1.5}}).json()
        assert moved["params"] == {"direction": "forward", "meters": 1.5}
        mark = client.post(f"/api/eye/{MY}/act", json={"action": "mark", "params": {"x": 0.5, "y": 0.5, "note": "weep at gland", "issue": True}},
                           headers={"X-Steward-Actor": "director"}).json()
        annotation = mark["annotation"]
        assert annotation["nearestAssetTag"] == "PG-601" and annotation["world"] == {"x": 0.1, "y": 0.9, "z": -0.3} and annotation["issueId"]
        candidate = client.get(f"/api/issues/{annotation['issueId']}").json()
        assert candidate["kind"] == "eye_observation" and candidate["candidate"] is True and candidate["assetTag"] == "PG-601"
    finally:
        renderer.stop.set()
        renderer.join(timeout=5)
    feed = client.get(f"/api/eye/{MY}/feed").json()
    assert len(feed["frames"]) == 7 and feed["operating"]["actor"] == "director" and feed["renderers"][0]["rendererId"] == "browser-test"
    assert {f["action"] for f in feed["frames"]} == {"go_to", "orbit", "move", "mark"}
    changes = [c for c in client.get(f"/api/properties/{MY}/changes?limit=1000").json()["changes"] if c["type"] == "eye"]
    assert len(changes) == 4
    rows = svc(client).telemetry.rows("myer-manager", limit=5)
    assert rows[0]["tool"] == "eye_orbit" and rows[0]["tokens"] >= 4 * 350
    assert client.post(f"/api/eye/{MY}/act", json={"action": "look"}, headers={"X-Steward-Actor": "myer-compliance"}).status_code == 403
    assert client.post(f"/api/eye/{MY}/act", json={"action": "look"}, headers={"X-Steward-Actor": "bristol-engineer"}).status_code == 403
    assert client.post(f"/api/eye/{MY}/act", json={"action": "move", "params": {"direction": "sideways"}}).json()["code"] == "INVALID_REQUEST"
    assert client.post(f"/api/eye/{MY}/act", json={"action": "orbit", "params": {"assetTag": "PG-601", "frames": 40}}).json()["code"] == "INVALID_REQUEST"
    assert client.post(f"/api/eye/{MY}/frames", json={"commandId": "eyc-none", "jpegBase64": "AAAAAAAAAA=="}).status_code == 404


def test_agent_eye_times_out_without_a_renderer_and_manages_the_headless_worker(client, monkeypatch):
    monkeypatch.setenv("STEWARD_EYE_ACT_TIMEOUT", "0.3")
    monkeypatch.setenv("STEWARD_EYE_COLD_START_TIMEOUT", "0.3")  # the fake worker never registers: keep the cold window short
    timeout = client.post(f"/api/eye/{BR}/act", json={"action": "look"})
    assert timeout.status_code == 504 and timeout.json()["code"] == "EYE_TIMEOUT" and "No renderer" in timeout.json()["detail"]
    service = svc(client)
    launched = []

    class FakeProcess:
        def __init__(self, args):
            self.args, self.pid, self.code = args, 40000 + len(launched), None

        def poll(self):
            return self.code

        def terminate(self):
            self.code = -15

    def launcher(args, log_path):
        process = FakeProcess(args)
        launched.append(process)
        return process

    worker = service.eye.worker
    worker.launcher = launcher
    monkeypatch.setenv("STEWARD_EYE_AUTOSTART", "true")
    client.post(f"/api/eye/{BR}/act", json={"action": "look"})
    assert len(launched) == 1 and launched[0].args[-1] == "http://127.0.0.1:3000/eye?site=bristol-pumps&renderer=headless"
    assert "--headless=new" in launched[0].args and any(a.startswith("--use-angle=") for a in launched[0].args)
    assert worker.status()[BR]["pid"] == launched[0].pid and worker.status()[BR]["mode"] == "gpu"
    client.post(f"/api/eye/{BR}/act", json={"action": "look"})
    assert len(launched) == 1  # reused while running
    worker.procs[BR]["started"] -= 60  # the GPU attempt never registered: retry with SwiftShader
    worker.check(service.eye.fresh)
    assert launched[0].code == -15 and len(launched) == 2 and "--use-angle=swiftshader" in launched[1].args and worker.status()[BR]["mode"] == "swiftshader"
    worker.procs[BR]["lastUsed"] -= 400  # idle for more than five minutes: stopped by its own PID
    worker.check(service.eye.fresh)
    assert launched[1].code == -15 and BR not in worker.status()


# ---- 14. metrics -----------------------------------------------------------------------------------------------------------

def test_metric_series_summary_and_eval_metrics(client):
    data = client.get(f"/api/properties/{MY}/metrics?series=pressure_bar,level_pct").json()
    keys = [s["key"] for s in data["series"]]
    assert keys == ["pressure_bar:PG-601", "pressure_bar:PG-602", "pressure_bar:PG-603", "level_pct:TK-201"] and data["synthetic"] is True
    primary = data["series"][0]
    assert primary["unit"] == "bar" and primary["spec"] == {"min": 1.5, "max": 3.5} and 270 <= len(primary["points"]) <= 300
    assert all(1.0 < value < 4.0 for _, value in primary["points"])
    week = client.get(f"/api/properties/{BR}/metrics?series=level_pct&step=3600&from=2000-01-01T00:00:00Z").json()
    assert week["series"][0]["assetTag"] == "SU-201" and 140 <= len(week["series"][0]["points"]) <= 170 and week["step"] == 3600
    again = client.get(f"/api/properties/{MY}/metrics?series=pressure_bar:PG-602").json()
    assert again["series"][0]["points"][:5] == data["series"][1]["points"][:5]  # deterministic
    assert client.get(f"/api/properties/{MY}/metrics?series=nonsense").json()["code"] == "INVALID_REQUEST"
    for base in ("pressure_bar", "flow_m3h", "temperature_c", "level_pct", "vibration_mms", "power_kw"):
        for site in (MY, BR):
            assert client.get(f"/api/properties/{site}/metrics?series={base}").json()["series"], (site, base)
    start_scenario(client, "my-overpressure")
    ramp = client.get(f"/api/properties/{MY}/metrics?series=pressure_bar:PG-601").json()["series"][0]
    assert ramp["overlayPoints"] >= 9 and ramp["points"][-1][1] == 4.1
    summary = client.get("/api/metrics/summary").json()
    assert [s["siteId"] for s in summary["sites"]] == [MY, BR, TM] and summary["sites"][0]["openIssues"] >= 1
    assert {"avgPressureBar", "avgFlowM3h", "uptimePct", "compliancePct", "crewOnShift", "agentActionsToday"} <= set(summary["sites"][0])
    assert summary["sites"][0]["crewOnShift"] == 3 and summary["average"]["crewOnShift"] == round(sum(s["crewOnShift"] for s in summary["sites"]) / 3, 1)
    assert summary["totals"]["agentActionsToday"] > 0
    start_scenario(client, "ops-counsel-tokens")
    wait = client.post("/api/waits", json={"event": "any"}).json()["id"]
    client.get(f"/api/waits/{wait}?timeout=0.2")
    metrics = client.get("/api/evals/metrics").json()
    assert metrics["source"] == "Steward telemetry, also delivered to Armature"
    assert metrics["suites"][0]["suite"] == "efficiency" and metrics["suites"][0]["runPassRate"] == 1.0
    assert metrics["tokensPerAgentPerMission"]["bristol-compliance"] > metrics["tokensPerAgentPerMission"]["myer-engineer"]
    assert metrics["waitFor"]["tokensAvoided"] >= 350 and metrics["estimatedCost"]["usd"] > 0 and metrics["a2aMessagesPerDay"]
    assert set(metrics["latencyMs"]) == {"p50", "p95", "samples"}


# ---- 15. conversations ----------------------------------------------------------------------------------------------------

def test_conversations_list_derive_and_accept_summaries(client):
    start_scenario(client, "x-maintenance")
    both = client.get(f"/api/conversations?siteId={MY}").json()
    calls = [c for c in both if c["kind"] == "call"]
    assert {c["topic"] for c in calls} >= {"Shared pressure-equipment examiner", "Shared examiner visit"}
    assert all(set(c["siteIds"]) == {MY, BR} for c in calls if c["topic"] in ("Shared pressure-equipment examiner", "Shared examiner visit"))
    compliance = next(c for c in calls if c["topic"] == "Shared pressure-equipment examiner")
    assert [line["speaker"] for line in compliance["transcript"]] == ["bristol-compliance", "myer-compliance", "bristol-compliance"]
    assert compliance["summaryBy"] == "hand-seed" and "examiner" in compliance["summary"]["headline"] and compliance["voiceNote"].startswith("Voice is the browser")
    mission = client.post("/api/missions", json={"siteId": MY, "budget": 5, "assetTags": ["P-101"]}).json()
    derived = [c for c in client.get("/api/conversations?agentId=myer-manager").json() if c.get("derived")]
    assert derived and derived[0]["kind"] == "message" and derived[0]["missionId"] == mission["id"] and derived[0]["summary"] is None
    posted = client.post(f"/api/conversations/{derived[0]['id']}/summary", json={"summary": {"headline": "Restart set delegated", "points": ["P-101"],
                                                                                          "decisions": [], "actions": [{"owner": "Field Technician · Myer", "task": "collect", "due": "now"}]},
                                                                              "summaryBy": "claude-opus-5-5"})
    assert posted.status_code == 200 and posted.json()["summaryBy"] == "claude-opus-5-5"
    assert client.get(f"/api/conversations/{derived[0]['id']}").json()["summary"]["headline"] == "Restart set delegated"
    assert client.post(f"/api/conversations/{derived[0]['id']}/summary", json={"summary": {"points": []}}).json()["code"] == "INVALID_REQUEST"
    assert client.get("/api/conversations/conv-missing").status_code == 404


# ---- 16. regulations ---------------------------------------------------------------------------------------------------

def test_regulations_serve_ogl_pdfs_redirect_the_rest_and_back_citations(client, tmp_path, monkeypatch):
    folder = tmp_path / "regs"
    folder.mkdir()
    (folder / "pssr.pdf").write_bytes(b"%PDF-1.4 fixture")
    (folder / "vic.pdf").write_bytes(b"%PDF-1.4 personal use only")
    records = [
        {"id": "eng-pssr-2000-reg-9", "jurisdiction": "ENG-UK", "siteIds": [BR], "instrument": "Pressure Systems Safety Regulations 2000 (SI 2000/128)",
         "provision": "reg. 9(1)-(5)", "title": "Periodic examination", "officialUrl": "https://www.legislation.gov.uk/uksi/2000/128/regulation/9",
         "pdfUrl": "https://www.legislation.gov.uk/uksi/2000/128/data.pdf", "pdfPath": str(folder / "pssr.pdf"), "pageHint": 7, "servePdf": True,
         "licence": "Open Government Licence v3.0", "retrievedAt": "2026-10-18T04:20:18Z", "summary": "Examine the system before the date in its written scheme.",
         "appliesTo": ["br-vessel-cert", "certificate_expired"], "synthetic": False},
        {"id": "vic-br-2018-reg-216", "jurisdiction": "VIC-AU", "siteIds": [MY], "instrument": "Building Regulations 2018 (Vic)", "provision": "reg. 216",
         "title": "Maintenance of essential safety measures", "officialUrl": "https://www.legislation.vic.gov.au/in-force/statutory-rules/building-regulations-2018/031",
         "pdfUrl": "https://content.legislation.vic.gov.au/sites/default/files/2026-09/18-38sra031-authorised.PDF", "pdfPath": str(folder / "vic.pdf"), "pageHint": 218,
         "servePdf": False, "licence": "Personal use only", "retrievedAt": "2026-10-18T04:37:59Z", "summary": "Keep essential safety measures maintained.",
         "appliesTo": ["my-extinguisher", "inspection_overdue"], "synthetic": False},
    ]
    regulations_file = folder / "regulations.json"
    regulations_file.write_text(json.dumps(records))
    (folder / "obligations-suggested.json").write_text(json.dumps({"records": [
        {"id": "obl-x", "siteId": BR, "relatedSeedObligationIds": ["ob-br-pv301-exam"], "trackedBy": "bristol-compliance", "why": "Examination date passed.",
         "evidence": ["New examination report on file"], "closesWhen": "A new report is on file."}]}))
    monkeypatch.setenv("STEWARD_REGULATIONS_FILE", str(regulations_file))
    bristol = client.get(f"/api/regulations?siteId={BR}").json()
    assert [r["id"] for r in bristol] == ["eng-pssr-2000-reg-9"] and bristol[0]["readUrl"] == "/api/regulations/eng-pssr-2000-reg-9/file#page=7"
    myer = client.get(f"/api/regulations?siteId={MY}").json()
    assert myer[0]["servePdf"] is False and myer[0]["readUrl"].startswith("https://content.legislation.vic.gov.au/") and myer[0]["readUrl"].endswith("#page=218")
    pdf = client.get("/api/regulations/eng-pssr-2000-reg-9/file")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["x-steward-attribution"] == "Contains public sector information licensed under the Open Government Licence v3.0."
    redirect = client.get("/api/regulations/vic-br-2018-reg-216/file", follow_redirects=False)
    assert redirect.status_code == 302 and redirect.headers["location"] == records[1]["pdfUrl"] and b"personal use" not in redirect.content
    obligations = {o["id"]: o for o in client.get(f"/api/properties/{BR}/obligations").json()}
    pv301 = obligations["ob-br-pv301-exam"]
    assert pv301["regulationIds"] == ["eng-pssr-2000-reg-9"] and "eng-pssr-2000-reg-8" in pv301["unresolvedRegulationIds"]
    assert pv301["why"] == "Examination date passed." and pv301["closingEvidence"] == ["New examination report on file"] and pv301["trackedBy"] == "bristol-compliance"
    start_scenario(client, "br-vessel-cert")
    issue = next(i for i in client.get(f"/api/properties/{BR}/issues").json() if i["kind"] == "certificate_expired")
    page = client.get(f"/api/issues/{issue['id']}").json()
    assert page["why"][0]["regulationId"] == "eng-pssr-2000-reg-9" and page["why"][0]["readUrl"].endswith("#page=7")
    assert page["responsible"]["owner"]["id"] == "crew-br-restoration-lead" and page["fix"]["available"] is True and "not legal advice" in page["disclaimer"]
    start_scenario(client, "my-extinguisher")
    extinguisher = next(i for i in client.get(f"/api/properties/{MY}/issues").json() if i["kind"] == "inspection_overdue")
    assert client.get(f"/api/issues/{extinguisher['id']}").json()["regulationIds"] == ["vic-br-2018-reg-216"]


def test_the_real_rule_pack_resolves_every_cited_regulation(client):
    """Reads the REGULATIONS stream's files read-only: every obligation id we cite exists, Victorian copies are never streamed."""
    regulations = client.get("/api/regulations").json()
    if not regulations:
        pytest.skip("backend/seed/regulations/regulations.json is not present")
    by_id = {r["id"]: r for r in regulations}
    assert {r["jurisdiction"] for r in regulations} <= {"ENG-UK", "VIC-AU", "JP"} and {"ENG-UK", "VIC-AU"} <= {r["jurisdiction"] for r in regulations}
    assert all(r["servePdf"] is False for r in regulations if r["jurisdiction"] == "VIC-AU")
    expected = {MY: "VIC-AU", BR: "ENG-UK", TM: "JP"}
    for site in (MY, BR, TM):
        for obligation in client.get(f"/api/properties/{site}/obligations").json():
            if site == TM and obligation.get("regulationPending"):
                continue  # contract 5: the JP records may still be arriving from the regulations stream
            assert not obligation.get("unresolvedRegulationIds"), obligation["id"]
            assert all(by_id[rid]["jurisdiction"] == expected[site] for rid in obligation["regulationIds"])
    victorian = next(r for r in regulations if r["jurisdiction"] == "VIC-AU")
    response = client.get(f"/api/regulations/{victorian['id']}/file", follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"].startswith("https://")


# ---- 17. the fix workflow and notifications ------------------------------------------------------------------------------

def test_fix_workflow_evidence_call_contact_fix_verify_inform(client):
    start_scenario(client, "br-sump")
    issue = next(i for i in client.get(f"/api/properties/{BR}/issues").json() if i["kind"] == "sump_overflow")
    assert client.post(f"/api/issues/{issue['id']}/fix", json={"speed": 0}, headers={"X-Steward-Actor": "bristol-manager"}).status_code == 403
    client.post(f"/api/eye/{BR}/renderers", json={"rendererId": "browser-fix"})
    renderer = FakeRenderer(client, BR, "browser-fix")
    renderer.start()
    try:
        response = client.post(f"/api/issues/{issue['id']}/fix", json={"speed": 0})
    finally:
        renderer.stop.set()
        renderer.join(timeout=5)
    assert response.status_code == 202, response.text
    workflow = response.json()
    assert workflow["state"] == "completed", workflow
    assert [s["name"] for s in workflow["steps"]] == ["evidence", "call", "contact", "fix", "verify", "inform"]
    assert len(workflow["evidence"]["frameIds"]) == 5  # go_to + a 4-frame orbit
    assert client.get(f"/api/issues/{issue['id']}").json()["status"] == "resolved"
    assert set(client.get(f"/api/issues/{issue['id']}").json()["evidenceFrameIds"]) == set(workflow["evidence"]["frameIds"])
    call = client.get(f"/api/conversations/{workflow['conversationId']}").json()
    assert call["kind"] == "call" and [line["speaker"] for line in call["transcript"]] == ["bristol-engineer", "bristol-manager", "bristol-compliance", "bristol-manager"]
    assert call["summaryBy"] == "hand-seed" and call["workflowId"] == workflow["id"]
    item = client.get(f"/api/work-items/{workflow['workItemId']}").json()
    assert item["state"] == "resolved" and client.get(f"/api/attestations/{workflow['attestationId']}").json()["valid"] is True
    assert workflow["reply"]["simulated"] is True and workflow["reply"]["body"].startswith("[synthetic reply]")
    fact = client.get(f"/api/properties/{BR}/facts?assetTag=SU-201&attribute=level_pct").json()[0]
    assert fact["value"] == 61
    assert {o["id"]: o for o in client.get(f"/api/properties/{BR}/obligations").json()}["ob-br-walkway-check"]["status"] in ("ok", "due_soon")
    notifications = client.get(f"/api/notifications?siteId={BR}").json()
    crew = [n for n in notifications if n["toKind"] == "crew"]
    agents = [n for n in notifications if n["toKind"] == "agent"]
    assert len(crew) == 5 and all(n["mode"] in ("record_only", "dry_run", "not_contactable") for n in crew)
    assert {n["to"] for n in agents} == {"bristol-engineer", "bristol-compliance", "bristol-technician", "director"}
    assert client.get(f"/api/fix-workflows?issueId={issue['id']}").json()[0]["id"] == workflow["id"]
    fixes = [c for c in client.get(f"/api/properties/{BR}/changes?limit=1000").json()["changes"] if c["type"] == "fix"]
    assert len(fixes) == 8  # started, six steps, completed
    assert client.post(f"/api/issues/{issue['id']}/fix", json={"speed": 0}).json()["code"] == "ISSUE_CLOSED"


def test_fix_workflow_without_a_renderer_records_missing_evidence(client):
    start_scenario(client, "my-overpressure")
    issue = next(i for i in client.get(f"/api/properties/{MY}/issues").json() if i["kind"] == "overpressure")
    workflow = client.post(f"/api/issues/{issue['id']}/fix", json={"speed": 0}).json()
    assert workflow["state"] == "completed" and workflow["evidence"]["frameIds"] == [] and "No renderer" in workflow["evidence"]["detail"]
    assert client.get(f"/api/properties/{MY}/facts?assetTag=PG-601&attribute=pressure_bar").json()[0]["value"] == 3.1
    assert client.get(f"/api/properties/{MY}/metrics?series=pressure_bar:PG-601").json()["series"][0]["points"][-1][1] == 3.1


# ---- 18. cross-factory maintenance -----------------------------------------------------------------------------------------

def test_x_maintenance_agrees_a_shared_window_and_the_director_approves(client):
    seeded = client.get(f"/api/maintenance?siteId={MY}").json()
    assert {w["id"] for w in seeded} >= {"mw-my-tk201-exam", "mw-my-db401-survey"} and all(w["synthetic"] for w in seeded)
    run = start_scenario(client, "x-maintenance")
    shared = [w for w in client.get(f"/api/maintenance?siteId={BR}").json() if len(w["siteIds"]) == 2]
    assert len(shared) == 1 and shared[0]["status"] == "approved" and shared[0]["approvedBy"] == "director" and shared[0]["proposedBy"] == "bristol-manager"
    assert shared[0]["conversationId"] == run["conversationIds"]["cv-x-managers"] and shared[0]["date"] == run["context"]["windowDate"]
    assert shared[0] in client.get(f"/api/maintenance?siteId={MY}").json()
    template = [e for e in client.get(f"/api/document-emails?siteId={MY}").json() if e["documentId"] == "doc-my-tk201-scheme"]
    assert template and template[0]["recipient"] == "bristol-compliance" and template[0]["a2aTaskId"]
    note = {o["id"]: o for o in client.get(f"/api/properties/{BR}/obligations").json()}["ob-br-pv301-exam"]["note"]
    assert run["context"]["windowDate"] in note
    proposal = client.post("/api/maintenance", json={"siteIds": [BR, MY], "date": "2026-11-02", "scope": "Joint drill"}, headers={"X-Steward-Actor": "myer-manager"})
    assert proposal.status_code == 201 and proposal.json()["status"] == "proposed"
    assert client.post(f"/api/maintenance/{proposal.json()['id']}/approve", headers={"X-Steward-Actor": "myer-manager"}).status_code == 403
    assert client.post(f"/api/maintenance/{proposal.json()['id']}/approve", headers={"X-Steward-Actor": "director"}).json()["status"] == "approved"
    assert client.post("/api/maintenance", json={"siteIds": [BR], "date": "2026-11-02", "scope": "Not mine"}, headers={"X-Steward-Actor": "myer-manager"}).status_code == 403
    own = client.post("/api/maintenance", json={"siteIds": [MY], "date": "2026-11-03", "scope": "Pump seals"}, headers={"X-Steward-Actor": "myer-manager"}).json()
    assert client.post(f"/api/maintenance/{own['id']}/approve", headers={"X-Steward-Actor": "myer-manager"}).json()["status"] == "approved"


# ---- 19. the decide fallback and operator telemetry -------------------------------------------------------------------------

def test_decide_routes_to_the_site_manager_and_to_the_owner_only_in_live_mode(client, monkeypatch):
    start_scenario(client, "br-sump")
    issue = next(i for i in client.get(f"/api/properties/{BR}/issues").json() if i["kind"] == "sump_overflow")
    asked = client.post(f"/api/issues/{issue['id']}/decide", json={"question": "Close the walkway for the open day?", "options": ["CLOSE", "KEEP"],
                                                                  "actor": "operator"})
    assert asked.status_code == 201, asked.text
    first = asked.json()
    assert first["routedTo"] == ["bristol-manager"] and first["ownerMode"] == "not_contactable" and first["status"] == "awaiting_answer"
    conversation = client.get(f"/api/conversations/{first['conversationId']}").json()
    assert conversation["kind"] == "message" and conversation["participants"] == ["operator", "bristol-manager"] and conversation["status"] == "awaiting_answer"
    notifications = [n for n in client.get(f"/api/notifications?siteId={BR}").json() if n.get("decisionRequestId") == first["id"]]
    assert {(n["toKind"], n["mode"]) for n in notifications} == {("agent", "sent"), ("owner", "not_contactable")}
    monkeypatch.setenv("INKBOX_OWNER_PHONE", "+15550002222")
    dry = client.post(f"/api/issues/{issue['id']}/decide", json={"question": "Close the walkway?", "options": ["CLOSE", "KEEP"]}).json()
    assert dry["ownerMode"] == "dry_run" and dry["ownerPhone"] == "••• ••• 2222" and "+15550002222" not in json.dumps(dry)
    # Cross-site askers go through the director (the cross-site rule forbids engineer → other site's manager).
    via_director = client.post(f"/api/issues/{issue['id']}/decide", json={"question": "Close?", "actor": "myer-engineer"}).json()
    assert via_director["sender"] == "director" and via_director["askedBy"] == "myer-engineer"
    sent = []
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    monkeypatch.setenv("STEWARD_ALLOW_NOTICE_SMS", "true")
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "+15550002222")
    monkeypatch.setattr(svc(client).reality.comms, "send_sms", lambda site, to, text, **kw: sent.append((site, to, text)) or {"id": "txt-1"})
    live = client.post(f"/api/issues/{issue['id']}/decision-request", json={"question": "Close the walkway?", "options": ["CLOSE", "KEEP"]}).json()
    assert live["ownerMode"] == "sent" and live["routedTo"] == ["bristol-manager", "owner"] and sent[0][1] == "+15550002222" and "CLOSE / KEEP" in sent[0][2]
    assert client.post(f"/api/decision-requests/{live['id']}/answer", json={"answer": "maybe"}).json()["code"] == "INVALID_REQUEST"
    assert client.post(f"/api/decision-requests/{live['id']}/answer", json={"answer": "close"}, headers={"X-Steward-Actor": "myer-manager"}).status_code == 403
    answered = client.post(f"/api/decision-requests/{live['id']}/answer", json={"answer": "close"}, headers={"X-Steward-Actor": "bristol-manager"}).json()
    assert answered["answer"] == "close" and answered["answeredBy"] == "bristol-manager" and answered["status"] == "answered"
    closed = client.get(f"/api/conversations/{live['conversationId']}").json()
    assert closed["status"] == "ended" and closed["transcript"][-1]["speaker"] == "bristol-manager" and "Decision: close" in closed["transcript"][-1]["text"]
    assert client.get(f"/api/a2a/tasks/{closed['a2aTaskIds'][0]}").json()["state"] == "completed"
    assert client.post(f"/api/decision-requests/{live['id']}/answer", json={"answer": "KEEP"}).status_code == 409
    assert client.post("/api/issues/iss-missing/decide", json={"question": "Close?"}).status_code == 404


def test_mcp_telemetry_rows_feed_activity_and_eval_metrics_without_double_counting(client):
    service = svc(client)
    before = len(service.telemetry.rows(limit=10000))
    posted = client.post("/api/telemetry", json={"agentId": "myer-engineer", "tool": "eye_look", "tokens": 512, "ms": 840,
                                                 "detail": {"in": 120, "out": 392}})
    assert posted.status_code == 201 and posted.json()["detail"] == '{"in":120,"out":392}' and posted.json()["tokens"] == 512
    estimated = client.post("/api/telemetry", json={"agentId": "operator", "tool": "get_overview", "ms": 35, "detail": {"in": 40, "out": 600}}).json()
    assert estimated["tokens"] == 640
    # The MCP's own API calls (no X-Steward-Tool) add no second row; only the explicit telemetry posts count.
    client.post(f"/api/properties/{MY}/viewer", json={"action": "focus", "assetTag": "PG-601"})
    client.post("/api/scenarios/my-extinguisher/start", json={"speed": 0})
    rows = [r for r in service.telemetry.rows(limit=10000)][: len(service.telemetry.rows(limit=10000)) - before]
    assert sum(1 for r in rows if r["kind"] == "mcp") == 2
    activity = client.get("/api/agents/myer-engineer/activity").json()
    assert activity["tokensThisHour"] >= 512 and any(a["tool"] == "eye_look" for a in activity["lastActions"])
    latency = client.get("/api/evals/metrics").json()["latencyMs"]
    assert latency["samples"] >= 2 and latency["p50"] in (35, 840) and latency["p95"] == 840
    assert client.post("/api/telemetry", json={"agentId": "atlas", "tool": "x"}).status_code == 403


# ---- 20. safety switches: the send-time gate and the A2A transport mode ------------------------------------------------------

REAL_LOOKING = {
    "INKBOX_API_KEY": "ik_live_looking_key", "INKBOX_IDENTITY_MYER_TECHNICIAN": "steward-myer-technician", "INKBOX_IDENTITY_DISPATCH": "steward-runner",
    "INKBOX_CONTRACTOR_PHONE": "+15551230000", "INKBOX_CONTRACTOR_EMAIL": "duty@example.com", "INKBOX_OWNER_PHONE": "+15551239999",
    "INKBOX_ALLOWED_RECIPIENTS": "+15551230000,duty@example.com,+15551239999", "STEWARD_ALLOW_NOTICE_SMS": "true", "STEWARD_ALLOW_AGENT_EMAIL": "true",
    "INKBOX_IDENTITY_DIRECTOR": "steward-ops-director", "INKBOX_AGENT_KEY_DIRECTOR": "k1", "INKBOX_IDENTITY_MYER_MANAGER": "steward-myer-manager",
    "INKBOX_AGENT_KEY_MYER_MANAGER": "k2", "INKBOX_IDENTITY_MYER_ENGINEER": "steward-myer-engineer", "INKBOX_AGENT_KEY_MYER_ENGINEER": "k3",
    "INKBOX_IDENTITY_MYER_COMPLIANCE": "steward-myer-compliance", "INKBOX_AGENT_KEY_MYER_COMPLIANCE": "k4", "INKBOX_AGENT_KEY_MYER_TECHNICIAN": "k5",
}


def forbid_providers(monkeypatch, service):
    from src.a2a import A2ABus
    from src.providers import InkboxAdapter
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError("a provider client was created")

    monkeypatch.setattr(InkboxAdapter, "client", staticmethod(refuse))
    monkeypatch.setattr(A2ABus, "_client", staticmethod(refuse))
    service.people.inkbox_factory = refuse
    return calls


def test_scheduler_ladder_sends_nothing_when_external_messages_are_off(client, monkeypatch):
    for name, value in REAL_LOOKING.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "false")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    service = svc(client)
    calls = forbid_providers(monkeypatch, service)
    result = client.post(f"/api/properties/{MY}/resolve", json={"assetTag": "P-101", "attribute": "pressure_bar", "budget": 5}).json()
    item = service.reality.work_item(result["workItemId"])
    assert item["dispatches"][0]["channel"] == "local"
    from datetime import datetime, timedelta
    created = datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))
    deadline = datetime.fromisoformat(item["deadlineAt"].replace("Z", "+00:00"))
    for fraction in (0.55, 0.75, 0.9, 0.97):
        service.reality.tick(created + (deadline - created) * fraction)
    service.reality.tick(deadline + timedelta(seconds=1))
    item = service.reality.work_item(result["workItemId"])
    assert item["state"] == "expired" and item["escalationLevel"] == 4
    assert calls == []  # no SDK client was ever created: no SMS, email, call or owner SMS left the machine
    assert all(d["providerRef"] is None for d in item["dispatches"])
    sent = [d for d in item["dispatches"] if d["channel"] in ("sms", "email", "call")]
    assert {d["channel"] for d in sent} == {"sms", "email", "call"} and all(d["body"].startswith("[not sent: dry-run") for d in sent)
    # Notices, the decide SMS fallback and agent document email also stay dry-run with every other gate open.
    notice = service.people.send_notice(MY, "myer-technician", "test", crew_member_id="crew-my-duty-engineer")
    assert notice["mode"] == "dry_run"
    start_scenario(client, "my-overpressure")
    issue = next(i for i in client.get(f"/api/properties/{MY}/issues").json() if i["kind"] == "overpressure")
    assert client.post(f"/api/issues/{issue['id']}/decide", json={"question": "Isolate now?"}).json()["ownerMode"] == "dry_run"
    email = client.post("/api/agents/myer-compliance/send-document", json={"to": "myer-engineer", "documentId": "doc-my-tk201-scheme"}).json()
    assert email["mode"] == "dry_run" and "STEWARD_ALLOW_EXTERNAL_MESSAGES is not true" in email["reason"]
    assert calls == []


def test_a2a_transport_local_never_calls_inkbox_even_with_keys(client, monkeypatch):
    for name, value in REAL_LOOKING.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "false")
    service = svc(client)
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "auto")
    assert service.bus.transport_for("director", "myer-manager") == "inkbox"  # keys present: auto would use Inkbox
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    calls = forbid_providers(monkeypatch, service)
    assert service.bus.transport_for("director", "myer-manager") == "local"
    start_scenario(client, "my-overpressure")
    mission = client.post("/api/missions", json={"siteId": MY, "budget": 5, "assetTags": ["P-101"]}).json()
    service.simulator.tick_event("a2a_status", BR)
    tasks = client.get("/api/a2a/tasks").json()
    assert tasks and all(t["transport"] == "local" for t in tasks)
    assert {a["transport"] for a in client.get("/api/agents").json() if a.get("actor", True)} == {"local"}
    assert mission["state"] == "running" and calls == []
    # An inbound Inkbox task (webhook) is answered locally while the mode is local.
    monkeypatch.setenv("STEWARD_INBOUND_SECRET", "s3cret")
    created = client.post("/api/inbound/inkbox", headers={"X-Steward-Inbound-Secret": "s3cret"}, json={
        "id": "evt-local-1", "event_type": "a2a.task.created", "data": {"task_id": "task-ext-9", "context_id": "c9", "state": "submitted",
        "caller": {"handle": "someone", "identity_id": "i", "organization_id": "o"}, "message_id": "m9",
        "parts": [{"text": "status?"}, {"data": {"steward": {"kind": "status_check", "siteId": MY, "to": "myer-engineer"}}}]}}).json()
    task = client.get(f"/api/a2a/tasks/{created['taskId']}").json()
    assert task["state"] == "failed" and "STEWARD_A2A_TRANSPORT=local" in task["providerError"] and calls == []
    assert service.bus.start() is None and service.bus._thread is None  # no startup recovery call either
