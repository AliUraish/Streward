"""The inspection chain (contract 8 §6): the Site Inspector inspects a site with the agent eye, reports to the Compliance
Officer in a long chat, the evidence goes to the manager, the manager emails the owner with Compliance Counsel copied, counsel
briefs the contractor, the manager calls the contractor to agree a slot, and the call's handler books or moves exactly one
window. The outbox, the phone calls and the chat writer are the contract-8 fakes; the eye is stubbed; nothing leaves the
process."""
import base64
import hashlib
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agents import display_name
from src.errors import RealityError
from src.inspections import STEPS, candidate_slots
from src.main import create_app
from src.store import now
from src.verify import iso, parse_time

from contract8_fakes import install_fakes

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"


def jpeg_bytes() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (60, 70, 80)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = jpeg_bytes()

def same_picture(data: bytes) -> bool:
    """The attached frame is the labelled copy of the frame (labels are drawn on a copy): a JPEG of the same size."""
    from PIL import Image
    return data[:2] == b"\xff\xd8" and Image.open(io.BytesIO(data)).size == Image.open(io.BytesIO(JPEG)).size



@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY", "STEWARD_API_TOKEN", "STEWARD_WALK_OWNER_ALERTS"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


@pytest.fixture
def fakes(client):
    return install_fakes(svc(client))


@pytest.fixture
def eye(client, monkeypatch):
    service = svc(client)
    looks = []

    def act_sync(site_id, action, params, actor, timeout=None):
        looks.append((site_id, action, params.get("assetTag"), actor))
        frame_id = f"eyf-{uuid4().hex[:16]}"
        (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
        service.store.put("eye_frame", dict(id=frame_id, seq=1, siteId=site_id, commandId="eyc-test", action=action, params=params, actor=actor,
                                            actorName=display_name(actor), camera=None, visiblePins=[], index=0, rendererId="test", size=len(JPEG),
                                            sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now()), site_id)
        return dict(frameId=frame_id, frameUrl=f"/api/eye/frames/{frame_id}.jpg")

    monkeypatch.setattr(service.eye, "act_sync", act_sync)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])
    return looks


def emails(fakes, channel="email"):
    return [item for item in fakes.outbox.items if item["channel"] == channel]


def windows_for(service, obligation_id):
    return [w for w in service.store.all("maintenance_window", "") if w.get("obligationId") == obligation_id]


def test_route_primary_finding_and_stops(client, eye, fakes):
    service = svc(client)
    inspection = service.inspections.run(BR)
    tags = [stop["assetTag"] for stop in inspection["stops"]]
    assert tags[:2] == ["V-504", "SP-102"] and len(tags) <= 5  # blocked and long overdue first
    assert [look[2] for look in eye] == tags and {look[3] for look in eye} == {"site-inspector"} and {look[1] for look in eye} == {"go_to"}
    assert all(stop["frameId"] for stop in inspection["stops"])
    primary = inspection["primary"]
    assert primary["kind"] == "obligation" and primary["obligationId"] == "ob-br-v504-gland" and primary["status"] == "blocked"
    assert any(text.startswith("SP-102:") for text in inspection["alsoNoted"])
    assert inspection["workKind"] == "drainage" and inspection["contractor"] == "Avon Pump & Valve Ltd"
    assert inspection["issueId"] == "iss-br-compliance-ob-br-v504-gland"
    issue = service.store.get("issue", inspection["issueId"], BR)
    v504 = next(s for s in inspection["stops"] if s["assetTag"] == "V-504")
    assert v504["frameId"] in issue["evidenceFrameIds"] and issue["inspectionId"] == inspection["id"]


def test_an_eye_failure_never_fails_the_inspection(client, fakes, monkeypatch):
    service = svc(client)

    def broken(site_id, action, params, actor, timeout=None):
        raise RealityError("renderer gone", "EYE_TIMEOUT", "retry")

    monkeypatch.setattr(service.eye, "act_sync", broken)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])
    inspection = service.inspections.run(BR)
    assert inspection["state"] == "running" and inspection["primary"]["obligationId"] == "ob-br-v504-gland"
    assert all(stop["frameId"] is None and "eye unavailable" in stop["eyeNote"] for stop in inspection["stops"])
    owner = emails(fakes)[0]
    names = [a["filename"] for a in owner["attachments"]]
    assert not [n for n in names if n.endswith(".jpg")] and f"evidence-{inspection['id']}.txt" in names
    assert "The agent eye had no frame at this stop" in owner["html"]


def test_every_step_in_order_with_refs_and_changes(client, eye, fakes):
    service = svc(client)
    inspection = service.inspections.run(BR)
    assert [step["name"] for step in inspection["steps"]] == list(STEPS[:5]) and inspection["state"] == "running"
    report, evidence, owner, counsel, call = inspection["steps"]
    assert report["refs"]["conversationId"] and evidence["refs"]["conversationId"] and evidence["refs"]["outboxId"]
    assert owner["refs"]["outboxId"] and counsel["refs"]["outboxId"] and call["refs"]["callId"] == inspection["callId"]
    assert [s["n"] for s in inspection["steps"]] == [1, 2, 3, 4, 5]
    assert len(inspection["conversationIds"]) == 2 and len(inspection["outboxIds"]) == 3
    changes = [c for c in service.store.all("change", BR) if c["type"] == "inspection" and c["refId"] == inspection["id"]]
    assert [c["status"] for c in changes] == ["started", "inspected"] + ["step"] * 5
    assert [c["step"] for c in changes if c["status"] == "step"] == list(STEPS[:5]) and all(c["inspectionId"] == inspection["id"] for c in changes)


def test_the_long_chats_have_the_right_people_and_lengths(client, eye, fakes):
    service = svc(client)
    inspection = service.inspections.run(BR)
    report, decision = fakes.chats.runs
    assert report["convener"] == "site-inspector" and report["participants"] == ["site-inspector", "bristol-compliance"]
    assert (report["minTurns"], report["maxTurns"]) == (10, 14) and report["siteIds"] == [BR] and report["refs"]["inspectionId"] == inspection["id"]
    assert "V-504" in report["shared"] and "Avon Pump & Valve Ltd" in report["shared"]
    assert "Site Inspector" in report["briefs"]["site-inspector"] and "Compliance Officer · Bristol" in report["briefs"]["bristol-compliance"]
    assert decision["convener"] == "bristol-compliance" and decision["participants"] == ["bristol-compliance", "bristol-manager"]
    assert (decision["minTurns"], decision["maxTurns"]) == (6, 10) and "Compliance Counsel" in decision["goal"]
    first, second = (service.conversations.get(cid) for cid in inspection["conversationIds"])
    assert len(first["transcript"]) >= 10 and first["transcript"][0]["speaker"] == "site-inspector"
    assert len(second["transcript"]) >= 8 and {line["speaker"] for line in second["transcript"]} == {"bristol-compliance", "bristol-manager"}
    said = " ".join(line["text"] for line in first["transcript"] + second["transcript"])
    for word in ("synthetic", "simulation", "scenario", "demo"):
        assert word not in said.lower()


def test_the_evidence_goes_to_the_manager_and_the_owner_email_copies_counsel(client, eye, fakes):
    service = svc(client)
    inspection = service.inspections.run(BR)
    [internal] = emails(fakes, "internal_email")
    assert (internal["sender"], internal["toAgent"], internal["purpose"]) == ("bristol-compliance", "bristol-manager", "inspection_evidence")
    assert any(a["filename"].startswith("evidence-v-504") and a["content_type"] == "image/jpeg" for a in internal["attachments"])
    owner, counsel = emails(fakes)
    assert (owner["sender"], owner["toRole"], owner["cc"], owner["purpose"]) == ("bristol-manager", "owner", ["compliance-counsel"], "inspection_owner")
    assert owner["subject"].startswith("[Bristol Dock Pump House] Compliance: Sump suction valve V-504") and owner["subject"].endswith("(blocked)")
    by_name = {a["filename"]: a for a in owner["attachments"]}
    frame = by_name["evidence-v-504-1.jpg"]
    assert frame["content_id"] and f"cid:{frame['content_id']}" in owner["html"] and same_picture(base64.b64decode(frame["content_base64"]))
    assert base64.b64decode(by_name[f"evidence-{inspection['id']}.txt"]["content_base64"]).decode().startswith(f"Steward inspection evidence {inspection['id']}")
    assert not [n for n in by_name if n.lower().startswith(("vic_", "vba_"))]
    assert "Compliance Counsel" in owner["html"] and "Avon Pump & Valve Ltd" in owner["text"] and owner["dedupeKey"] == f"inspection:{inspection['id']}:owner"
    record = service.inspections.get(inspection["id"])
    assert record["ownerEmail"]["mode"] == "queued" and record["ownerEmail"]["cc"] == ["compliance-counsel"]
    assert (counsel["sender"], counsel["toRole"], counsel["cc"], counsel["purpose"]) == ("compliance-counsel", "contractor", ["bristol-manager"], "inspection_counsel")
    assert "what the work must meet" in counsel["subject"] and "What the work must deliver" in counsel["text"] and "not legal advice" in counsel["text"]
    assert f"job-pack-{inspection['id']}.txt" in {a["filename"] for a in counsel["attachments"]}


def test_the_contractor_call_request(client, eye, fakes):
    service = svc(client)
    inspection = service.inspections.run(BR)
    [call] = fakes.voice_calls.calls
    assert (call["purpose"], call["caller"], call["calleeRole"], call["calleeName"], call["siteId"]) == (
        "contractor_schedule", "bristol-manager", "contractor", "Avon Pump & Valve Ltd", BR)
    assert set(call["canDo"]) == {"book_slot", "email_file", "counsel_call", "note"} and call["refs"]["inspectionId"] == inspection["id"]
    assert call["dedupeKey"] == f"inspection:{inspection['id']}:contractor" and "V-504" in call["goal"]
    assert [o["id"] for o in call["options"]] == ["slot-1", "slot-2", "slot-3"] and all("London time" in o["label"] for o in call["options"])
    assert any("held up because" in fact for fact in call["facts"])  # the blocked repair: an earlier visit unblocks it
    assert call["file"]["subject"].startswith("[Bristol Dock Pump House] Job pack") and call["file"]["cc"] == ["bristol-manager"]
    starts = [parse_time(s["startAt"]) for s in service.inspections.get(inspection["id"])["slots"]]
    assert starts == sorted(starts) and all(s > datetime.now(timezone.utc) + timedelta(hours=11) for s in starts)
    assert all(s.astimezone(__import__("zoneinfo").ZoneInfo("Europe/London")).weekday() < 5 for s in starts)


def test_an_agreed_slot_books_exactly_one_window_and_confirms(client, eye, fakes):
    service = svc(client)
    inspection = service.inspections.run(BR)
    [call] = fakes.voice_calls.calls
    slots = service.inspections.get(inspection["id"])["slots"]
    result = fakes.voice_calls.finish(call["id"], result="agreed", chosen_option_id="slot-2", decision="Tuesday works")
    [window] = windows_for(service, "ob-br-v504-gland")
    assert result["handled"] == ["book_slot"] and result["refs"]["windowId"] == window["id"]
    assert (window["origin"], window["status"], window["examiner"], window["startAt"]) == ("contractor_call", "approved", "Avon Pump & Valve Ltd", slots[1]["startAt"])
    assert window["awaitingContractor"] is False and window["approvedBy"] == "bristol-manager" and window["inspectionId"] == inspection["id"]
    record = service.inspections.get(inspection["id"])
    assert record["state"] == "completed" and [s["name"] for s in record["steps"]] == list(STEPS) and record["windowId"] == window["id"]
    assert record["booking"]["agreed"] is True and record["booking"]["action"] == "booked"
    confirmation = emails(fakes)[-1]
    assert (confirmation["toRole"], confirmation["cc"], confirmation["purpose"]) == ("contractor", ["owner", "compliance-counsel"], "inspection_booking")
    assert confirmation["subject"].startswith("[Bristol Dock Pump House] Booked:")
    team = [service.conversations.get(cid) for cid in record["steps"][-1]["refs"]["conversationIds"]]
    assert {c["participants"][1] for c in team} == {"bristol-compliance", "bristol-engineer", "bristol-technician"}
    assert service.store.get("issue", record["issueId"], BR)["maintenanceWindowId"] == window["id"]
    assert fakes.voice_calls.finish(call["id"], result="agreed", chosen_option_id="slot-3")["notes"] == ["Already booked."]
    assert len(windows_for(service, "ob-br-v504-gland")) == 1
    planner = service.maintenance_planner.plan(BR)
    assert not [d for d in planner if d["obligationId"] == "ob-br-v504-gland" and d["action"] == "book"]


def test_the_planners_window_is_offered_first_and_moved(client, eye, fakes):
    service = svc(client)
    start = datetime.now(timezone.utc) + timedelta(days=9)
    while start.weekday() >= 5:
        start += timedelta(days=1)
    planner_window = dict(id="mw-plan-test-l901", siteIds=[MY], date=start.date().isoformat(), startAt=iso(start), endAt=iso(start + timedelta(hours=2)),
                          timeZone="Australia/Melbourne", localStart="Mon 1 Jan 10:00", localEnd="12:00", scope="Exit sign and emergency luminaire L-901",
                          examiner="the ESM contractor (fire and emergency lighting)", status="approved", obligationId="ob-my-l901-esm",
                          obligationIds=["ob-my-l901-esm"], assetTags=["L-901"], workKind="fire", origin="planner", createdAt=now(), updatedAt=now())
    service.store.put("maintenance_window", planner_window, "")
    inspection = service.inspections.run(MY)
    assert inspection["primary"]["obligationId"] == "ob-my-l901-esm" and inspection["contractor"] == "Southbank Fire & Emergency Lighting"
    [call] = fakes.voice_calls.calls
    slots = service.inspections.get(inspection["id"])["slots"]
    assert slots[0]["current"] is True and slots[0]["label"].endswith("(currently booked)") and slots[0]["startAt"] == iso(start)
    assert all("Melbourne time" in s["label"] for s in slots)
    fakes.voice_calls.finish(call["id"], result="agreed", chosen_option_id="slot-3")
    [window] = windows_for(service, "ob-my-l901-esm")
    assert window["id"] == "mw-plan-test-l901" and window["startAt"] == slots[2]["startAt"] and window["rescheduledFrom"] == iso(start)
    assert (window["origin"], window["previousOrigin"], window["examiner"]) == ("contractor_call", "planner", "Southbank Fire & Emergency Lighting")
    assert service.inspections.get(inspection["id"])["booking"]["action"] == "moved"


@pytest.mark.parametrize("result,attempt", [("declined", 1), ("undecided", 1), ("no_answer", 2), ("failed", 1), ("voicemail", 2)])
def test_without_an_agreed_slot_the_first_slot_is_held_and_the_contractor_asked(client, eye, fakes, result, attempt):
    service = svc(client)
    inspection = service.inspections.run(BR)
    [call] = fakes.voice_calls.calls
    call["attempt"] = attempt
    fakes.voice_calls.finish(call["id"], result=result)
    [window] = windows_for(service, "ob-br-v504-gland")
    slots = service.inspections.get(inspection["id"])["slots"]
    assert window["startAt"] == slots[0]["startAt"] and window["awaitingContractor"] is True and window["origin"] == "contractor_call"
    record = service.inspections.get(inspection["id"])
    assert record["state"] == "completed" and record["booking"]["agreed"] is False and record["booking"]["callResult"] == result
    assert emails(fakes)[-1]["subject"].startswith("[Bristol Dock Pump House] Please confirm:")


def test_a_first_voicemail_waits_for_the_retry(client, eye, fakes):
    service = svc(client)
    inspection = service.inspections.run(BR)
    [call] = fakes.voice_calls.calls
    result = fakes.voice_calls.finish(call["id"], result="voicemail")
    assert result["handled"] == [] and windows_for(service, "ob-br-v504-gland") == []
    assert service.inspections.get(inspection["id"])["state"] == "running"
    retry = fakes.voice_calls.request(purpose="contractor_schedule", caller="bristol-manager", callee_role="contractor", callee_name="Avon Pump & Valve Ltd",
                                      site_id=BR, goal=call["goal"], facts=call["facts"], options=call["options"], can_do=call["canDo"], refs=call["refs"])
    retry["attempt"] = 2
    fakes.voice_calls.finish(retry["id"], result="agreed", chosen_option_id="slot-1")
    [window] = windows_for(service, "ob-br-v504-gland")
    assert window["awaitingContractor"] is False and service.inspections.get(inspection["id"])["state"] == "completed"


def test_a_call_that_cannot_be_placed_books_at_once(client, eye, fakes, monkeypatch):
    service = svc(client)
    original = fakes.voice_calls.request

    def dry_run(**kwargs):
        record = original(**kwargs)
        record.update(status="dry_run", reason="STEWARD_ALLOW_OWNER_ALERTS is not true")
        return record

    monkeypatch.setattr(fakes.voice_calls, "request", dry_run)
    inspection = service.inspections.run(TM)
    record = service.inspections.get(inspection["id"])
    assert record["state"] == "completed" and [s["name"] for s in record["steps"]] == list(STEPS)
    assert record["steps"][4]["refs"]["mode"] == "dry_run" and record["booking"]["callResult"] == "dry_run"
    assert record["contractor"] in ("Gunma Heritage Carpentry", "Kanto Fire Protection")
    assert emails(fakes)[-1]["subject"].startswith("[Tomioka Silk Mill] Please confirm:")


def test_one_inspection_per_site_and_routes(client, eye, fakes):
    started = client.post("/api/inspections", json=dict(siteId=BR), headers={"X-Steward-Actor": "operator"})
    assert started.status_code == 202, started.text
    body = started.json()
    again = client.post("/api/inspections", json=dict(siteId=BR), headers={"X-Steward-Actor": "operator"})
    assert again.status_code == 202 and again.json()["id"] == body["id"]  # still waiting for its contractor call
    denied = client.post("/api/inspections", json=dict(siteId=BR), headers={"X-Steward-Actor": "bristol-manager"})
    assert denied.status_code == 403 and denied.json()["code"] == "AUTHORITY_DENIED"
    assert client.post("/api/inspections", json=dict(siteId="nowhere"), headers={"X-Steward-Actor": "operator"}).status_code == 404
    listed = client.get(f"/api/inspections?siteId={BR}&limit=5").json()
    assert [i["id"] for i in listed] == [body["id"]] and client.get("/api/inspections").json()[0]["id"] == body["id"]
    one = client.get(f"/api/inspections/{body['id']}").json()
    assert one["primary"]["assetTag"] == "V-504" and [s["name"] for s in one["steps"]] == list(STEPS[:5])
    assert client.get("/api/inspections/insp-missing").status_code == 404


def test_the_loop_waits_then_rotates_sites(client, eye, fakes, monkeypatch):
    service = svc(client)
    monkeypatch.setenv("STEWARD_INSPECTION_FIRST_DELAY_MINUTES", "8")
    monkeypatch.setenv("STEWARD_INSPECTION_EVERY_MINUTES", "60")
    moment = datetime.now(timezone.utc)
    assert service.inspections.tick(moment) is None  # schedules the first one
    assert service.inspections.tick(moment + timedelta(minutes=5)) is None
    first = service.inspections.tick(moment + timedelta(minutes=9))
    assert first["siteId"] == BR
    assert service.inspections.tick(moment + timedelta(minutes=30)) is None
    second = service.inspections.tick(moment + timedelta(minutes=70))
    assert second["siteId"] == MY
    monkeypatch.setenv("STEWARD_INSPECTIONS", "false")
    assert service.inspections.tick(moment + timedelta(minutes=200)) is None and service.inspections.state == "off"


def test_a_call_that_never_reports_back_is_closed_with_the_fallback(client, eye, fakes, monkeypatch):
    service = svc(client)
    monkeypatch.setenv("STEWARD_INSPECTION_CALL_TIMEOUT_MINUTES", "90")
    inspection = service.inspections.run(BR)
    assert service.inspections.close_stale(datetime.now(timezone.utc) + timedelta(minutes=30)) == []
    assert service.inspections.close_stale(datetime.now(timezone.utc) + timedelta(minutes=95)) == [inspection["id"]]
    record = service.inspections.get(inspection["id"])
    assert record["state"] == "completed" and record["booking"]["callResult"] == "no_answer" and "did not report back" in record["steps"][-1]["summary"]


def test_candidate_slots_skip_weekends_and_keep_the_lead_time():
    moment = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)  # a Friday afternoon in London
    slots = candidate_slots(BR, "pressure", moment)
    assert [s["id"] for s in slots] == ["slot-1", "slot-2", "slot-3"]
    assert slots[0]["label"] == "Monday 19 October, 09:00 London time" and slots[1]["label"].startswith("Tuesday 20 October")
    existing = dict(id="mw-x", startAt=iso(moment + timedelta(days=5)), endAt=iso(moment + timedelta(days=5, hours=4)))
    with_current = candidate_slots(BR, "pressure", moment, existing)
    assert with_current[0]["current"] is True and with_current[0]["windowId"] == "mw-x" and len(with_current) == 3
