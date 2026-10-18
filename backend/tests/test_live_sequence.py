"""The owner's two-minute live sequence (demo_sequence.py): the contractor call first, the site chats and the telemetry excursion
while it runs, then (paced, in this order) the owner email with the compliance file and the pictures, the employee's text with the
A2A report the manager records, the telemetry email and the contractor confirmation. Inkbox is stubbed at the provider, Claude is
off (the chats are the templates), nothing leaves the process."""
import hashlib
import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.agents import all_agent_ids, env_suffix
from src.main import create_app
from src.providers import InkboxAdapter
from src.store import now

MY, BR = "myer-plant", "bristol-pumps"
OWNER_EMAIL, CONTRACTOR_EMAIL, PHONE = "owner@example.com", "contractor@example.com", "+15550000001"


def jpeg_bytes() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (60, 70, 80)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = jpeg_bytes()


def live_env(monkeypatch):
    monkeypatch.setenv("INKBOX_API_KEY", "fixture-key")
    for agent in all_agent_ids():
        suffix = env_suffix(agent)
        if suffix:
            monkeypatch.setenv(f"INKBOX_IDENTITY_{suffix}", f"steward-{agent}")
            monkeypatch.setenv(f"INKBOX_AGENT_KEY_{suffix}", f"key-{agent}")
    monkeypatch.setenv("INKBOX_IDENTITY_DISPATCH", "steward-dispatch")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")
    monkeypatch.setenv("STEWARD_ALLOW_AGENT_EMAIL", "true")
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("INKBOX_OWNER_PHONE", PHONE)
    monkeypatch.setenv("INKBOX_CONTRACTOR_EMAIL", CONTRACTOR_EMAIL)
    monkeypatch.setenv("INKBOX_CONTRACTOR_PHONE", PHONE)
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", f"{OWNER_EMAIL},{CONTRACTOR_EMAIL},{PHONE}")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    monkeypatch.setenv("STEWARD_CHAT_CLAUDE", "false")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


@pytest.fixture
def line(monkeypatch):
    """The Inkbox side: calls, transcripts, emails and texts, each through the real gate."""
    calls, placed, sent = {}, [], []

    def place_hosted_call(self, to, reason, voicemail=None, role="owner", authority="contact_scoped"):
        InkboxAdapter._person_gate(to, "call", role)
        call_id = f"call-{len(placed) + 1}"
        calls[call_id] = dict(status="initiated", hangupReason=None, startedAt=None, endedAt=None, actionItems=[], transcript=[])
        placed.append(dict(id=call_id, to=to, reason=reason, role=role, authority=authority))
        sent.append(dict(channel="call", to=to, role=role))
        return {"id": call_id, "status": "initiated", "raw": {}}

    def call_status(self, call_id):
        call = calls[call_id]
        return dict(id=call_id, status=call["status"], hangupReason=call["hangupReason"], startedAt=call["startedAt"], endedAt=call["endedAt"],
                    actionItems=list(call["actionItems"]))

    def call_transcripts(self, call_id):
        return [dict(seq=n, tsMs=1792322147000 + n * 1000, party=party, text=text) for n, (party, text) in enumerate(calls[call_id]["transcript"])]

    def hangup(self, call_id):
        return {"id": call_id, "status": "answered"}

    def send_email(self, property_id, to, subject, body, reference, in_reply_to=None, html=None, attachments=None, sender_handle=None,
                   api_key=None, idempotency_key=None, owner_channel=False, cc=None, person_role=None, internal=False):
        if internal:
            InkboxAdapter._internal_gate(to)
        elif owner_channel:
            InkboxAdapter._owner_gate(to, "email")
        else:
            InkboxAdapter._person_gate(to, "email", person_role or "owner")
        sent.append(dict(channel="internal_email" if internal else "email", to=to, subject=subject, cc=InkboxAdapter._cc_gate(cc or []),
                         sender=sender_handle, attachments=[a.get("filename") for a in attachments or []]))
        return {"id": f"msg-{len(sent)}", "threadId": None, "messageId": None, "raw": {}}

    def send_sms(self, property_id, to, body, conversation_id=None, idempotency_key=None, person_role=None):
        InkboxAdapter._person_gate(to, "sms", person_role or "owner")
        sent.append(dict(channel="sms", to=to, text=body, role=person_role))
        return {"id": f"sms-{len(sent)}", "conversationId": None, "raw": {}}

    for name, fn in (("place_hosted_call", place_hosted_call), ("call_status", call_status), ("call_transcripts", call_transcripts),
                     ("hangup", hangup), ("send_email", send_email), ("send_sms", send_sms)):
        monkeypatch.setattr(InkboxAdapter, name, fn)

    class Line:
        pass

    fake = Line()
    fake.calls, fake.placed, fake.sent = calls, placed, sent

    def talk(call_id, *lines):
        calls[call_id].update(status="answered", startedAt=datetime.now(timezone.utc).isoformat())
        calls[call_id]["transcript"] += list(lines)

    def end(call_id, *items):
        calls[call_id].update(status="completed", hangupReason="remote", endedAt=datetime.now(timezone.utc).isoformat(),
                              actionItems=[dict(seq=n + 1, action=text, details=None) for n, text in enumerate(items)])

    fake.talk, fake.end = talk, end
    return fake


def frame_for(service, site, tag):
    """A stored eye frame of the asset (what the walks leave behind), so the run has a picture without moving the eye."""
    frame_id = f"eyf-{hashlib.sha256(tag.encode()).hexdigest()[:16]}"
    (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
    service.store.put("eye_frame", dict(id=frame_id, seq=1, siteId=site, commandId="eyc-test", action="go_to", params=dict(assetTag=tag), actor="bristol-engineer",
                                        actorName="Site Engineer · Bristol", camera=None, visiblePins=[], index=0, rendererId="test", size=len(JPEG),
                                        sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now()), site)
    return frame_id


def step_names(run):
    return [s["name"] for s in run["steps"]]


def test_the_call_goes_first_then_the_paced_items_in_order(client, monkeypatch, line):
    live_env(monkeypatch)
    service = svc(client)
    frame_for(service, BR, "V-504")
    run = service.sequence.start_now(contractor_site="bristol-pumps", employee_site="bristol-pumps", telemetry_site="myer-plant")
    assert run["state"] == "running" and service.sequence.active()
    assert step_names(run)[:2] == ["finding", "contractor_call"]
    assert line.placed and line.placed[0]["role"] == "contractor" and line.sent[0]["channel"] == "call"  # nothing person-facing before the call
    call = service.voice_calls.list(purpose="contractor_schedule")[0]
    assert call["context"]["liveSequenceRunId"] == run["id"] and call["context"]["noRetry"] is True and call["priority"] == 1
    assert {"site_chats", "telemetry"} <= set(step_names(run))  # the chats and the excursion ran while the call is on
    person = [s for s in line.sent if s["channel"] in ("email", "sms")]
    assert person == []  # still waiting for the call to end
    high = next(r for r in service.metrics.live_readings(MY) if r["assetTag"] == "PG-602" and r["key"].startswith("pressure_bar"))
    assert high["state"] == "high"
    chats = service.conversations.list(limit=50)
    cross = next(c for c in chats if {"myer-manager", "bristol-manager"} <= set(c["participants"]))
    assert len(cross["transcript"]) >= 4

    provider = service.voice_calls.get(call["id"])["providerCallId"]
    line.talk(provider, ("local", "Hello, this is the Plant Manager at Bristol Dock Pump House; this call is transcribed."), ("remote", "Tuesday works."))
    line.end(provider, f"BOOK {call['options'][1]['id']}", "EMAIL cc=counsel the job pack")
    service.voice_calls.tick()
    run = service.sequence.get(run["id"])
    assert run["state"] == "completed", run
    names = step_names(run)
    assert names.index("call_ended") < names.index("owner_email") < names.index("employee_text") < names.index("lateness_recorded") \
        < names.index("telemetry_email") < names.index("confirmation")
    person = [s for s in line.sent if s["channel"] in ("email", "sms")]
    assert [p["channel"] for p in person] == ["email", "sms", "email", "email"]
    owner, text, telemetry, confirmation = person
    assert owner["to"] == OWNER_EMAIL and "steward-compliance-counsel@inkboxmail.com" in owner["cc"]
    assert any(a.endswith(".jpg") for a in owner["attachments"]) and any(a.startswith("evidence-") and a.endswith(".txt") for a in owner["attachments"])
    assert text["role"] == "employee" and "People Officer" in text["text"] and "41 minutes" in text["text"]
    assert telemetry["to"] == OWNER_EMAIL and telemetry["sender"] == "steward-myer-manager" and "PG-602" in telemetry["subject"]
    assert confirmation["to"] == CONTRACTOR_EMAIL and OWNER_EMAIL in confirmation["cc"] and "steward-compliance-counsel@inkboxmail.com" in confirmation["cc"]
    assert any(a.startswith("job-pack-") for a in confirmation["attachments"])  # asked for on the call
    items = [i for i in service.outbox.list(limit=50) if i["channel"] in ("email", "sms", "call")]
    assert all(i.get("pace") == run["id"] for i in items)
    report = next(c for c in service.conversations.list(limit=80, include="all") if c["participants"][:2] == ["people-officer", "bristol-manager"])
    assert "minutes late" in report["transcript"][0]["text"] and "Recorded" in report["transcript"][-1]["text"]
    entry = next(e for e in service.store.all("attendance_entry", BR) if e.get("recordedBy") == "bristol-manager")
    assert entry["status"] == "late" and entry["lateMinutes"] == 41
    inspection = service.inspections.get(run["inspectionId"])
    assert inspection["booking"]["agreed"] is True and inspection["booking"]["confirmationOutboxId"]
    assert not service.sequence.active()


def test_with_the_person_channel_off_everything_is_prepared_not_sent(client):
    service = svc(client)
    run = service.sequence.start_now(contractor_site="bristol-pumps", employee_site="bristol-pumps", telemetry_site="myer-plant")
    assert run["state"] == "completed", run
    items = [i for i in service.outbox.list(limit=50) if i["channel"] in ("email", "sms", "call")]
    assert {i["channel"] for i in items} == {"email", "sms", "call"}
    assert all(i["status"] == "dry_run" for i in items)
    assert step_names(run)[:2] == ["finding", "contractor_call"]
    assert {"owner_email", "employee_text", "lateness_recorded", "telemetry_email", "confirmation"} <= set(step_names(run))


def test_sequence_items_skip_the_gaps_and_everything_else_waits(client, monkeypatch, line):
    live_env(monkeypatch)
    monkeypatch.setenv("STEWARD_OUTBOX_PACE_INLINE", "true")
    service = svc(client)
    service.sequence.active_id = "lsr-test"  # a run is on
    regular = service.outbox.email(sender="director", to_role="owner", subject="Digest", text="x", purpose="digest")
    with service.outbox.paced_as("lsr-test"):
        paced = service.outbox.email(sender="bristol-manager", to_role="owner", subject="Compliance file", text="y", purpose="inspection_owner")
    assert paced["pace"] == "lsr-test" and regular.get("pace") is None
    service.outbox.tick()
    assert service.outbox.get(paced["id"])["status"] == "sent"  # inside the boot grace, still out
    assert service.outbox.get(regular["id"])["status"] == "queued"  # held while the run is on
    service.sequence.active_id = None
    assert service.sequence.gap() == 30.0
    monkeypatch.setenv("STEWARD_LIVE_SEQUENCE_GAP_SECONDS", "45")
    assert service.sequence.gap() == 45.0


def test_the_route_is_for_the_owners_agent(client):
    denied = client.post("/api/live-sequence", json={}, headers={"X-Steward-Actor": "bristol-manager"})
    assert denied.status_code == 403
    started = client.post("/api/live-sequence", json={}, headers={"X-Steward-Actor": "operator"})
    assert started.status_code == 202 and started.json()["id"].startswith("lsr-")
    status = client.get("/api/live-sequence").json()
    assert status["mode"] == "off" and status["gapSeconds"] == 30.0 and status["runs"][0]["id"] == started.json()["id"]


def test_the_realtime_run_plays_on_its_threads(client, monkeypatch, line):
    """The threaded path the live backend uses, with the gaps shortened."""
    import time as _time
    live_env(monkeypatch)
    for name in ("STEWARD_LIVE_SEQUENCE_GAP_SECONDS", "STEWARD_LIVE_SEQUENCE_CALL_AT_SECONDS", "STEWARD_LIVE_SEQUENCE_TELEMETRY_AT_SECONDS",
                 "STEWARD_LIVE_SEQUENCE_TURN_SECONDS"):
        monkeypatch.setenv(name, "0.2")
    service = svc(client)
    run = service.sequence.start_now(contractor_site="bristol-pumps", employee_site="bristol-pumps", telemetry_site="myer-plant", realtime=True)
    deadline = _time.monotonic() + 20
    while _time.monotonic() < deadline and not line.placed:
        _time.sleep(0.1)
    assert line.placed, "the call was not placed"
    call = service.voice_calls.list(purpose="contractor_schedule")[0]
    provider = service.voice_calls.get(call["id"])["providerCallId"]
    line.talk(provider, ("local", "Hello."), ("remote", "The first slot works."))
    line.end(provider, f"BOOK {call['options'][0]['id']}")
    service.voice_calls.tick()
    while _time.monotonic() < deadline and service.sequence.get(run["id"])["state"] == "running":
        _time.sleep(0.2)
    run = service.sequence.get(run["id"])
    assert run["state"] == "completed", run
    assert [s["channel"] for s in line.sent if s["channel"] in ("email", "sms")] == ["email", "sms", "email", "email"]
    assert "telemetry_settled" in step_names(run)
