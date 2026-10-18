"""Contract 8 end to end with the real outbox, phone calls and chat writer (Claude off, so the chats are the templates; Inkbox
stubbed at the provider; the eye stubbed): the People Officer's employee call and the Site Inspector's chain, from the trigger
to the last email. Nothing leaves the process."""
import hashlib
import io
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agents import all_agent_ids, display_name, env_suffix
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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    monkeypatch.setenv("STEWARD_CHAT_CLAUDE", "false")
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
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


@pytest.fixture
def line(monkeypatch):
    """The Inkbox side: placed calls, their states and transcripts, and every email with its gate checked as the real one would."""
    calls, placed, emails = {}, [], []

    def place_hosted_call(self, to, reason, voicemail=None, role="owner", authority="contact_scoped"):
        InkboxAdapter._person_gate(to, "call", role)
        call_id = f"call-{len(placed) + 1}"
        calls[call_id] = dict(status="initiated", hangupReason=None, startedAt=None, endedAt=None, actionItems=[], transcript=[])
        placed.append(dict(id=call_id, to=to, reason=reason, voicemail=voicemail, role=role, authority=authority))
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
        emails.append(dict(to=to, subject=subject, body=body, cc=InkboxAdapter._cc_gate(cc or []), sender=sender_handle, internal=internal,
                           attachments=[a.get("filename") for a in attachments or []]))
        return {"id": f"msg-{len(emails)}", "threadId": None, "messageId": None, "raw": {}}

    for name, fn in (("place_hosted_call", place_hosted_call), ("call_status", call_status), ("call_transcripts", call_transcripts),
                     ("hangup", hangup), ("send_email", send_email)):
        monkeypatch.setattr(InkboxAdapter, name, fn)

    def talk(call_id, *lines):
        calls[call_id].update(status="answered", startedAt=datetime.now(timezone.utc).isoformat())
        calls[call_id]["transcript"] += list(lines)

    def end(call_id, *items):
        calls[call_id].update(status="completed", hangupReason="remote", endedAt=datetime.now(timezone.utc).isoformat(),
                              actionItems=[dict(seq=n + 1, action=text, details=None) for n, text in enumerate(items)])

    class Line:
        pass

    fake = Line()
    fake.calls, fake.placed, fake.emails, fake.talk, fake.end = calls, placed, emails, talk, end
    return fake


@pytest.fixture
def eye(client, monkeypatch):
    service = svc(client)

    def act_sync(site_id, action, params, actor, timeout=None):
        frame_id = f"eyf-{uuid4().hex[:16]}"
        (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
        service.store.put("eye_frame", dict(id=frame_id, seq=1, siteId=site_id, commandId="eyc-test", action=action, params=params, actor=actor,
                                            actorName=display_name(actor), camera=None, visiblePins=[], index=0, rendererId="test", size=len(JPEG),
                                            sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now()), site_id)
        return dict(frameId=frame_id, frameUrl=f"/api/eye/frames/{frame_id}.jpg")

    monkeypatch.setattr(service.eye, "act_sync", act_sync)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])


def test_the_people_officer_calls_the_late_employee_and_the_agreement_sticks(client, line):
    service = svc(client)
    service.attendance.check()  # the first check after a start opens the seeded case (Myer's shift technician)
    case = next(c for c in service.attendance.cases(MY) if c["crewId"] == "crew-my-shift-tech")
    call = service.voice_calls.list(purpose="employee_attendance")[0]
    assert call["refs"].get("caseId") == case["id"] and call["calleeRole"] == "employee" and call["caller"] == "people-officer"
    placed = line.placed[0]
    assert placed["role"] == "employee" and placed["authority"] == "contact_scoped" and placed["to"] == PHONE
    brief = placed["reason"]
    assert brief.startswith("You are") and "Goal:" in brief and "AGREED <option id>" in brief and "start-0730" in brief and len(brief) <= 1900
    assert "Hello, this is" not in brief  # a task, never a speech
    provider = service.voice_calls.get(call["id"])["providerCallId"]
    line.talk(provider, ("local", "Hi Tomas, this is the People Officer. Is now a good time?"), ("remote", "Yes, the bus timetable changed."))
    service.voice_calls.tick()
    assert service.voice_calls.get(call["id"])["status"] == "live" and len(service.voice_calls.get(call["id"])["transcript"]) == 2
    line.end(provider, "AGREED start-0730", "NOTE The bus timetable changed on Thursday")
    service.voice_calls.tick()
    done = service.voice_calls.get(call["id"])
    assert done["status"] == "ended" and done["outcome"]["result"] == "agreed" and done["outcome"]["chosenOptionId"] == "start-0730"
    case = service.attendance.case(case["id"])
    assert case["status"] == "resolved"
    recap = [e for e in line.emails if e["sender"] == "steward-people-officer"]
    assert len(recap) == 1 and recap[0]["to"] == OWNER_EMAIL and "steward-myer-manager@inkboxmail.com" in recap[0]["cc"]
    assert not [e for e in line.emails if e["to"] not in (OWNER_EMAIL, CONTRACTOR_EMAIL) and not e["internal"]]


def test_the_inspection_chain_reaches_the_owner_counsel_and_contractor_and_books_the_slot(client, line, eye):
    service = svc(client)
    inspection = service.inspections.run(BR, realtime=False)
    owner = [e for e in line.emails if e["to"] == OWNER_EMAIL]
    assert owner and "steward-compliance-counsel@inkboxmail.com" in owner[0]["cc"] and owner[0]["sender"] == "steward-bristol-manager"
    counsel = [e for e in line.emails if e["sender"] == "steward-compliance-counsel"]
    assert counsel and counsel[0]["to"] == CONTRACTOR_EMAIL
    evidence = [e for e in line.emails if e["internal"]]
    assert evidence and evidence[0]["to"] == "steward-bristol-manager@inkboxmail.com" and any(a.endswith(".jpg") for a in evidence[0]["attachments"])
    call = service.voice_calls.list(purpose="contractor_schedule")[0]
    assert call["calleeRole"] == "contractor" and call["caller"] == "bristol-manager" and len(call["options"]) == 3
    assert line.placed[-1]["role"] == "contractor" and "BOOK <option id>" in line.placed[-1]["reason"]
    chosen = call["options"][1]["id"]
    provider = service.voice_calls.get(call["id"])["providerCallId"]
    line.talk(provider, ("local", "Hello, this is the Bristol plant manager calling about the V-504 repair."), ("remote", "The second slot works."))
    line.end(provider, f"BOOK {chosen}", "EMAIL cc=counsel the job pack and the evidence")
    before = len(line.emails)
    service.voice_calls.tick()
    done = service.voice_calls.get(call["id"])
    assert done["outcome"]["result"] == "agreed" and done["outcome"]["chosenOptionId"] == chosen
    after = line.emails[before:]
    assert any(e["to"] == CONTRACTOR_EMAIL and "steward-compliance-counsel@inkboxmail.com" in e["cc"] for e in after)  # the file, counsel copied
    confirmation = [e for e in after if e["to"] == CONTRACTOR_EMAIL and OWNER_EMAIL in e["cc"]]
    assert confirmation, after
    inspection = service.inspections.get(inspection["id"])
    assert [s["name"] for s in inspection["steps"]][-1] == "booking" and inspection["windowId"]
    window = next(w for w in service.store.all("maintenance_window", "") if w["id"] == inspection["windowId"])
    assert window["origin"] == "contractor_call" and window.get("status") == "approved"
    assert not [e for e in line.emails if e["to"] not in (OWNER_EMAIL, CONTRACTOR_EMAIL) and not e["internal"]]
