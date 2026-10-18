"""Phone calls (contract 8 §3): the brief is a task, the call is placed contact-scoped on the person gate and supervised while
live, the outcome is read by Claude (or by rules over the action items), only offered options, the call's own follow-ups and the
allowed copies survive, voicemail retries once, the hang-up guard holds, a call that cannot be placed still lets its chain finish,
and the routes show the calls with numbers masked. Inkbox and Claude are stubbed; nothing leaves the process."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.agents import COUNSEL, env_suffix
from src.main import create_app
from src.providers import InkboxAdapter
from src.voice_calls import MAX_BRIEF, MAX_VOICEMAIL

BR = "bristol-pumps"
OWNER_EMAIL, CONTRACTOR_EMAIL, PHONE = "owner@example.com", "contractor@example.com", "+15550000001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def channel(monkeypatch, *agents):
    monkeypatch.setenv("INKBOX_API_KEY", "fixture-key")
    for agent in agents:
        suffix = env_suffix(agent)
        monkeypatch.setenv(f"INKBOX_IDENTITY_{suffix}", f"steward-{agent}")
        monkeypatch.setenv(f"INKBOX_AGENT_KEY_{suffix}", f"key-{agent}")
    monkeypatch.setenv("INKBOX_IDENTITY_DISPATCH", "steward-dispatch")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")
    monkeypatch.setenv("INKBOX_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("INKBOX_OWNER_PHONE", PHONE)
    monkeypatch.setenv("INKBOX_CONTRACTOR_EMAIL", CONTRACTOR_EMAIL)
    monkeypatch.setenv("INKBOX_CONTRACTOR_PHONE", PHONE)
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", f"{OWNER_EMAIL},{CONTRACTOR_EMAIL},{PHONE}")


class FakeLine:
    """The Inkbox side of a call: the test moves each call through its states."""

    def __init__(self):
        self.calls, self.placed, self.hangups = {}, [], []

    def place(self, to, reason, voicemail, role, authority):
        call_id = f"call-{len(self.placed) + 1}"
        self.calls[call_id] = dict(status="initiated", hangupReason=None, startedAt=None, endedAt=None, actionItems=[], transcript=[])
        self.placed.append(dict(id=call_id, to=to, reason=reason, voicemail=voicemail, role=role, authority=authority))
        return {"id": call_id, "status": "initiated", "raw": {}}

    def answer(self, call_id, *lines, started=None):
        call = self.calls[call_id]
        call.update(status="answered", startedAt=(started or datetime.now(timezone.utc)).isoformat())
        call["transcript"] += list(lines)

    def end(self, call_id, *items, reason="remote"):
        call = self.calls[call_id]
        call.update(status="completed", hangupReason=reason, endedAt=datetime.now(timezone.utc).isoformat(),
                    actionItems=[dict(seq=n + 1, action=text, details=None) for n, text in enumerate(items)])
        if reason == "voicemail":
            call["startedAt"] = call["startedAt"] or datetime.now(timezone.utc).isoformat()


@pytest.fixture
def line(monkeypatch):
    fake = FakeLine()
    sent = []

    def place_hosted_call(self, to, reason, voicemail=None, role="owner", authority="contact_scoped"):
        InkboxAdapter._person_gate(to, "call", role)
        return fake.place(to, reason, voicemail, role, authority)

    def call_status(self, call_id):
        call = fake.calls[call_id]
        return dict(id=call_id, status=call["status"], hangupReason=call["hangupReason"], startedAt=call["startedAt"], endedAt=call["endedAt"],
                    actionItems=list(call["actionItems"]))

    def call_transcripts(self, call_id):
        return [dict(seq=n, tsMs=1792322147000 + n * 1000, party=party, text=text) for n, (party, text) in enumerate(fake.calls[call_id]["transcript"])]

    def hangup(self, call_id):
        fake.hangups.append(call_id)
        return {"id": call_id, "status": "answered"}

    def send_email(self, property_id, to, subject, body, reference, in_reply_to=None, html=None, attachments=None, sender_handle=None,
                   api_key=None, idempotency_key=None, owner_channel=False, cc=None, person_role=None, internal=False):
        InkboxAdapter._owner_gate(to, "email") if owner_channel else InkboxAdapter._person_gate(to, "email", person_role or "owner")
        sent.append(dict(to=to, subject=subject, body=body, cc=InkboxAdapter._cc_gate(cc or []), sender_handle=sender_handle))
        return {"id": f"msg-{len(sent)}", "threadId": None, "messageId": None, "raw": {}}

    for name, fn in (("place_hosted_call", place_hosted_call), ("call_status", call_status), ("call_transcripts", call_transcripts),
                     ("hangup", hangup), ("send_email", send_email)):
        monkeypatch.setattr(InkboxAdapter, name, fn)
    fake.emails = sent
    return fake


class FakeClaude:
    def __init__(self, answer):
        self.answer, self.requests = answer, []
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(self.answer))], stop_reason="end_turn", model="claude-opus-5-5",
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=180))


OPTIONS = [dict(id="slot-1", label="Tuesday 21 October, 09:00 London time"), dict(id="slot-2", label="Wednesday 22 October, 14:00 London time")]


def schedule(service, **extra):
    fields = dict(purpose="contractor_schedule", caller="bristol-manager", callee_role="contractor", callee_name="Avon Pump & Valve", site_id=BR,
                  goal="Agree a visit slot to repair the V-504 sump suction valve", options=OPTIONS, can_do=["book_slot", "email_file", "counsel_call", "note"],
                  facts=["The V-504 repair is blocked by a missing spare.", "The regulation needs the valve kept in good repair."],
                  file=dict(subject="V-504 job pack", text="The job pack: valve, permit, access."))
    fields.update(extra)
    return service.voice_calls.request(**fields)


# ---- the brief -----------------------------------------------------------------------------------------------------------------

def test_the_brief_is_a_task_with_every_section_and_fits(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    facts = [f"Fact number {n}: " + "the valve record says something long and specific about the repair. " * 2 for n in range(12)]
    call = schedule(service, facts=facts)
    brief = call["brief"]
    assert len(brief) <= MAX_BRIEF and len(call["voicemail"]) <= MAX_VOICEMAIL
    assert brief.startswith("You are the Plant Manager at Bristol Dock Pump House, calling Avon Pump & Valve (the contractor) on the Steward line.")
    for section in ("Goal: Agree a visit slot", "Facts:", "Options you may offer:", "[slot-1] Tuesday 21 October, 09:00 London time", "You can:",
                    "How to run the call:", "Action items:", "BOOK <option id>", "EMAIL cc=<counsel|manager|none> <what>", "COUNSEL_CALL <why>",
                    "NOTE <text>", "Never invent dates, prices, people or rules"):
        assert section in brief, section
    assert "CALLBACK <when>" not in brief, "only the call's own follow-ups"
    assert not brief.lower().startswith("hello") and "Hello, this is" not in brief
    assert call["voicemail"].startswith("Hello Avon Pump & Valve, this is the Plant Manager at Bristol Dock Pump House")
    with pytest.raises(ValueError):
        schedule(service, options=[dict(id="Slot One", label="x")])
    with pytest.raises(ValueError):
        schedule(service, can_do=["book_slot", "wire_money"])
    with pytest.raises(ValueError):
        schedule(service, callee_role="inspector")


# ---- the call ------------------------------------------------------------------------------------------------------------------

def test_a_call_is_placed_contact_scoped_supervised_and_read_by_claude(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager", COUNSEL)
    claude = FakeClaude(dict(result="agreed", decision="Wednesday 14:00 works; send the job pack with counsel copied.",
                             summary="The contractor picked Wednesday afternoon and asked for the job pack with the lawyer copied.",
                             chosenOptionId="slot-2", followUps=[dict(type="email_file", cc=["compliance-counsel"], topic="job pack", details="with counsel")]))
    service.voice_calls.client = claude
    seen = []
    service.voice_calls.register("contractor_schedule", lambda call: seen.append(call) or dict(handled=["book_slot"], notes=["Booked slot-2."],
                                                                                              refs=dict(windowId="mw-1")))
    call = schedule(service)
    assert call["status"] == "dialing" and call["providerCallId"] == "call-1" and call["outboxId"]
    [placed] = line.placed
    assert placed["authority"] == "contact_scoped" and placed["to"] == PHONE and placed["role"] == "contractor" and placed["reason"] == call["brief"]
    line.answer("call-1", ("local", "Hi, this is the Plant Manager at Bristol Dock Pump House. Is now a good time?"),
                ("remote", "Yes. Wednesday afternoon suits me, email me the pack and keep your lawyer in CC."))
    service.voice_calls.tick()
    live = service.voice_calls.get(call["id"])
    assert live["status"] == "live" and [l["party"] for l in live["transcript"]] == ["agent", "person"] and live["transcript"][1]["name"] == "Avon Pump & Valve"
    line.end("call-1", "BOOK slot-2", "EMAIL cc=counsel the job pack")
    service.voice_calls.tick()
    done = service.voice_calls.get(call["id"])
    outcome = done["outcome"]
    assert done["status"] == "ended" and done["actionItems"][0]["action"] == "BOOK slot-2"
    assert outcome["interpretedBy"] == "claude-opus-5-5" and outcome["result"] == "agreed" and outcome["chosenOptionId"] == "slot-2"
    follow = {f["type"]: f for f in outcome["followUps"]}
    assert follow["book_slot"]["status"] == "done" and follow["email_file"]["status"] == "done" and follow["email_file"]["ref"]
    assert seen and seen[0]["outcome"]["chosenOptionId"] == "slot-2" and done["refs"]["windowId"] == "mw-1" and "Booked slot-2." in outcome["notes"]
    [email] = line.emails
    assert email["to"] == CONTRACTOR_EMAIL and email["cc"] == ["steward-compliance-counsel@inkboxmail.com"] and email["subject"] == "V-504 job pack"
    assert email["sender_handle"] == "steward-bristol-manager" and "As agreed on our call" in email["body"]
    schema = claude.requests[0]["output_config"]["format"]["schema"]
    assert schema["properties"]["chosenOptionId"]["anyOf"][0]["enum"] == ["slot-1", "slot-2"] and claude.requests[0]["output_config"]["effort"] == "low"
    kinds = [c["fields"] if "fields" in c else c for c in service.store.all("change", BR) if c["type"] == "phone_call"]
    assert {c.get("status") for c in kinds} >= {"queued", "dialing", "live", "ended"}


def test_rules_read_the_action_items_when_claude_is_off(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    monkeypatch.setenv("STEWARD_CALL_CLAUDE", "false")
    call = schedule(service, can_do=["book_slot", "note"])
    line.answer("call-1", ("remote", "Tuesday morning is fine."))
    line.end("call-1", "BOOK slot-9", "BOOK slot-1", "EMAIL cc=counsel the pack", "NOTE gate code 4411 2233 99")
    service.voice_calls.tick()
    outcome = service.voice_calls.get(call["id"])["outcome"]
    assert outcome["interpretedBy"] == "rules" and outcome["chosenOptionId"] == "slot-1" and outcome["result"] == "agreed"
    assert [f["type"] for f in outcome["followUps"]] == ["book_slot", "note"], "email_file is not this call's follow-up"
    assert "4411" not in json.dumps(outcome) and outcome["decision"].startswith("Agreed: Tuesday 21 October")


def test_claude_answers_are_cleaned_to_the_offered_options_and_follow_ups(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    service.voice_calls.client = FakeClaude(dict(result="agreed", decision="d", summary="s", chosenOptionId="slot-7",
                                                 followUps=[dict(type="counsel_call", cc=[], topic="t", details="x"),
                                                            dict(type="email_file", cc=["someone", "compliance-counsel"], topic="t", details="x")]))
    call = schedule(service, can_do=["book_slot", "email_file", "note"])
    line.answer("call-1", ("remote", "Send me the pack."))
    line.end("call-1")
    service.voice_calls.tick()
    outcome = service.voice_calls.get(call["id"])["outcome"]
    assert outcome["chosenOptionId"] is None and [f["type"] for f in outcome["followUps"]] == ["email_file"]
    assert outcome["followUps"][0]["cc"] == [COUNSEL] and outcome["result"] == "agreed"


def test_voicemail_retries_once_then_the_handler_runs(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    seen = []
    service.voice_calls.register("contractor_schedule", lambda call: seen.append(call) or None)
    first = schedule(service, refs=dict(caseId="case-1"), context=dict(k="v"))
    line.end("call-1", reason="voicemail")
    service.voice_calls.tick()
    first = service.voice_calls.get(first["id"])
    assert first["status"] == "voicemail" and first["outcome"]["result"] == "voicemail" and first["retryId"]
    assert [c["id"] for c in seen] == [first["id"]] and seen[0]["attempt"] == 1, "the handler runs after every attempt; it waits on attempt 1"
    retry = service.voice_calls.get(first["retryId"])
    assert retry["status"] == "queued" and retry["attempt"] == 2 and retry["retryOf"] == first["id"] and len(line.placed) == 1
    assert retry["purpose"] == first["purpose"] and retry["refs"] == first["refs"] == dict(caseId="case-1") and retry["context"] == dict(k="v")
    service.outbox.tick(datetime.now(timezone.utc) + timedelta(minutes=11))
    assert service.voice_calls.get(retry["id"])["status"] == "dialing" and len(line.placed) == 2
    line.end("call-2", reason="voicemail")
    service.voice_calls.tick()
    assert len(seen) == 2 and seen[1]["id"] == retry["id"] and seen[1]["outcome"]["result"] == "voicemail" and seen[1]["retryOf"] == first["id"]
    assert not service.voice_calls.get(retry["id"]).get("retryId"), "one retry only"


def test_the_hang_up_guard_ends_a_call_that_runs_too_long(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    monkeypatch.setenv("STEWARD_CALL_MAX_SECONDS", "60")
    call = schedule(service)
    line.answer("call-1", ("remote", "Hello?"), started=datetime.now(timezone.utc) - timedelta(seconds=120))
    service.voice_calls.tick()
    service.voice_calls.tick()
    assert line.hangups == ["call-1"] and service.voice_calls.get(call["id"])["hangupRequestedAt"]


def test_a_call_that_cannot_be_placed_still_lets_its_chain_finish(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "false")
    seen = []
    service.voice_calls.register("contractor_schedule", lambda call: seen.append(call) or dict(handled=[], notes=["Booked the first slot."]))
    call = schedule(service)
    assert call["status"] == "dry_run" and line.placed == []
    assert call["outcome"]["result"] == "undecided" and call["outcome"]["decision"].startswith("Not placed: STEWARD_ALLOW_OWNER_ALERTS is not true")
    assert len(seen) == 1 and "Booked the first slot." in call["outcome"]["notes"]


def test_one_call_at_a_time_and_the_gap_counts_from_the_end_of_the_call(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    monkeypatch.setenv("STEWARD_OUTBOX_PACE_INLINE", "true")
    monkeypatch.setenv("STEWARD_OUTBOX_BOOT_GRACE_SECONDS", "0")
    monkeypatch.setenv("STEWARD_CALL_CLAUDE", "false")
    first, second = schedule(service), schedule(service, callee_role="owner", callee_name="the owner", purpose="owner_compliance", can_do=["note"], options=[])
    t0 = datetime.now(timezone.utc)
    service.outbox.tick(t0)
    assert len(line.placed) == 1 and service.voice_calls.get(first["id"])["status"] == "dialing"
    service.outbox.tick(t0 + timedelta(seconds=300))
    assert len(line.placed) == 1, "the line is busy while the first call is not over"
    line.answer("call-1", ("remote", "Yes."))
    line.end("call-1", "NOTE fine")
    service.voice_calls.tick()
    ended = datetime.fromisoformat(service.voice_calls.get(first["id"])["endedAt"].replace("Z", "+00:00"))
    service.outbox.tick(ended + timedelta(seconds=60))
    assert len(line.placed) == 1, "two minutes from the end of the previous call"
    service.outbox.tick(ended + timedelta(seconds=121))
    assert len(line.placed) == 2 and service.voice_calls.get(second["id"])["status"] == "dialing"


# ---- routes ------------------------------------------------------------------------------------------------------------------

def test_routes_show_the_calls_with_numbers_masked(client, line, monkeypatch):
    service = svc(client)
    channel(monkeypatch, "bristol-manager")
    monkeypatch.setenv("STEWARD_CALL_CLAUDE", "false")
    call = schedule(service)
    line.answer("call-1", ("remote", "Call me back on 415 555 0199 or mail me at me@example.com."))
    service.voice_calls.tick()
    active = client.get("/api/phone-calls", params=dict(active="true", siteId=BR)).json()
    assert [c["id"] for c in active] == [call["id"]] and "0199" not in json.dumps(active) and "me@example.com" not in json.dumps(active)
    one = client.get(f"/api/phone-calls/{call['id']}").json()
    assert one["transcript"][0]["text"] == "Call me back on ••• or mail me at •••."
    assert client.get("/api/phone-calls/pcall-missing").status_code == 404
    assert client.get("/api/phone-calls", params=dict(purpose="nope")).status_code == 400
    assert PHONE not in client.get("/api/phone-calls").text
