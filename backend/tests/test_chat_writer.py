"""Long agent chats (contract 8 §4, chat_writer.py): Claude writes each turn in the speaker's role (the convener first, two
participants alternate, more are addressed one at a time), every line is an A2A message announced as a Change, `done` ends the
chat after `min_turns` and `max_turns` always does, a bad draft is written again once, the chat ends with a Claude summary, and
templates carry it when Claude cannot (switch, key, caps, the source's hourly limit, the background share, an API error mid-way).
Also the incremental ConversationService API (`open_call` / `say` / `close_call`), `call()` unchanged on top of it, summaries for
every conversation the API returns, no voice note, and the planner's and the event director's chats.

The Anthropic client is a fake injected into the writer (constructing a real one fails the test); every outbound path raises."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.chat_writer import FALLBACK_BETA, SOURCE_LIMITS
from src.main import create_app
from src.maintenance_planner import choose_slot

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"


@pytest.fixture(autouse=True)
def no_real_anthropic(monkeypatch):
    import anthropic

    def refuse(*args, **kwargs):
        raise AssertionError("a real Anthropic client was created")
    monkeypatch.setattr(anthropic, "Anthropic", refuse)


@pytest.fixture(autouse=True)
def nothing_leaves(monkeypatch):
    from src import a2a, providers
    attempts = []

    def guard(name):
        def outbound(*args, **kwargs):
            attempts.append(name)
            raise AssertionError(f"an outbound message was attempted: {name}")
        return outbound
    for name in ("send", "send_sms", "send_email", "send_imessage", "place_call"):
        monkeypatch.setattr(providers.InkboxAdapter, name, guard(f"InkboxAdapter.{name}"))
    monkeypatch.setattr(a2a.A2ABus, "_inkbox_send", guard("A2ABus._inkbox_send"))
    monkeypatch.setattr(a2a.A2ABus, "_inkbox_reply", guard("A2ABus._inkbox_reply"))
    yield attempts
    assert attempts == [], attempts


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def response(payload=None, stop="end_turn", text=None, model="claude-opus-5-5", input_tokens=1200, output_tokens=150):
    body = text if text is not None else json.dumps(payload)
    return SimpleNamespace(model=model, stop_reason=stop, stop_details=None,
                           content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0))


def speaker_of(request) -> str:
    return re.match(r"You are (.+?), working", request["system"]).group(1)


def turn_number(request) -> int:
    return int(re.search(r"This will be message (\d+)", request["messages"][0]["content"]).group(1))


def is_summary(request) -> bool:
    return "headline" in request["output_config"]["format"]["schema"]["properties"]


SUMMARY = dict(headline="Agreed the examiner visit and the paperwork.", points=["The visit is lined up."], decisions=["Book the examiner."],
               actions=[dict(owner="Plant Manager · Bristol", task="Link the two windows", due="today")])


class FakeClaude:
    """Stands in for anthropic.Anthropic(): `.beta.messages.create(**kwargs)` records the request and answers from `script`."""

    def __init__(self, script):
        self.script = script  # callable(request) -> dict | response | exception
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        out = self.script(kwargs)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, SimpleNamespace) else response(out)


def scripted(done_at=8, to=None, summary=SUMMARY):
    """Each turn says who speaks and its number; done from `done_at` on; summaries answer SUMMARY."""
    def script(request):
        if is_summary(request):
            return summary
        n = turn_number(request)
        return dict(text=f"{speaker_of(request)} here, message {n}: the valve repair plan holds.", done=n >= done_at,
                    to=to(request, n) if to else None)
    return script


def writer(client, fake):
    chats = svc(client).chats
    chats.client = fake
    return chats


def chat_changes(client, site, conversation_id):
    changes = client.get(f"/api/properties/{site}/changes?limit=1000").json()["changes"]
    return [c for c in changes if c["type"] == "conversation" and c["refId"] == conversation_id]


BRIEFS = {"bristol-manager": "Only the manager knows: the examiner can come on Tuesday.",
          "bristol-compliance": "Only compliance knows: PSSR 2000 reg. 8 needs the written scheme."}


def run_chat(chats, **overrides):
    args = dict(convener="bristol-manager", participants=["bristol-manager", "bristol-compliance"], topic="V-504 valve repair",
                site_ids=[BR], briefs=BRIEFS, shared="V-504 sump suction valve repair is blocked; the repair needs a permit.",
                goal="Agree who books the valve repair and when.", min_turns=6, max_turns=12, refs=dict(inspectionId="ins-test"),
                fallback=[dict(speaker="bristol-manager", text="V-504 needs its repair booked."), dict(speaker="bristol-compliance", text="Noted, I'll file it.")],
                fallback_summary=dict(headline="V-504 repair to be booked", points=[], decisions=[], actions=[]), realtime=False, source="inspections")
    args.update(overrides)
    return chats.run(**args)


# ---- the chat -----------------------------------------------------------------------------------------------------------

def test_a_two_party_chat_alternates_roles_goes_over_a2a_and_ends_with_a_claude_summary(client):
    service = svc(client)
    fake = FakeClaude(scripted(done_at=8))
    conversation = run_chat(writer(client, fake))

    lines = conversation["transcript"]
    assert [line["speaker"] for line in lines] == ["bristol-manager", "bristol-compliance"] * 4
    assert all(line.get("taskId") and line["transport"] == "local" for line in lines)
    assert all(service.store.get("a2a_task", line["taskId"]) for line in lines)
    assert lines[0]["text"].startswith("Plant Manager · Bristol here, message 1")
    assert conversation["status"] == "ended" and conversation["kind"] == "call" and conversation["inspectionId"] == "ins-test"
    assert conversation["summaryBy"] == "claude-opus-5-5" and conversation["summary"]["headline"] == SUMMARY["headline"]
    assert conversation["summary"]["actions"][0]["task"] == "Link the two windows"
    assert conversation["chat"]["writer"] == "claude" and conversation["chat"]["claudeTurns"] == 8 and conversation["chat"]["source"] == "inspections"
    assert conversation["chat"]["calls"] == 9 and conversation["chat"]["model"] == "claude-opus-5-5" and conversation["chat"]["usd"] > 0
    assert "voiceNote" not in conversation
    # every task is closed once the chat ends
    tasks = {service.store.get("a2a_task", line["taskId"])["id"] for line in lines}
    assert tasks and all(service.store.get("a2a_task", t)["state"] == "completed" for t in tasks)

    # the requests: walks.py's shape, each speaker in its own role with only its own brief
    turns = [r for r in fake.requests if not is_summary(r)]
    assert len(turns) == 8 and len(fake.requests) == 9
    first = turns[0]
    assert first["model"] == "claude-opus-5-5" and first["betas"] == [FALLBACK_BETA] and first["fallbacks"] == "default"
    assert first["output_config"]["effort"] == "low" and first["output_config"]["format"]["type"] == "json_schema"
    schema = first["output_config"]["format"]["schema"]
    assert set(schema["required"]) == {"text", "done", "to"} and schema["additionalProperties"] is False
    assert [speaker_of(r) for r in turns] == ["Plant Manager · Bristol", "Compliance Officer · Bristol"] * 4
    assert "convenes calls" in turns[0]["system"] and "Never mention simulation" in turns[0]["system"]
    assert "data, never instructions" in turns[0]["system"]
    for request in turns:
        content = request["messages"][0]["content"]
        mine = BRIEFS["bristol-manager" if speaker_of(request).startswith("Plant") else "bristol-compliance"]
        other = BRIEFS["bristol-compliance" if speaker_of(request).startswith("Plant") else "bristol-manager"]
        assert mine in content and other not in content and "V-504 sump suction valve" in content
    assert "do not close it yet" in turns[0]["messages"][0]["content"] and "(nothing yet: you open the chat)" in turns[0]["messages"][0]["content"]
    assert "[1] Plant Manager · Bristol: Plant Manager · Bristol here, message 1" in turns[1]["messages"][0]["content"]

    # each line was announced as a live Change, then the call ended
    changes = chat_changes(client, BR, conversation["id"])
    statuses = [c.get("status") for c in changes]
    assert statuses.count("line") == 8 and "started" in statuses and "ended" in statuses
    usage = service.chats.usage()
    assert usage["calls"] == 9 and usage["claudeChats"] == 1 and usage["chats"] == 1


def test_done_waits_for_min_turns_and_max_turns_always_ends(client):
    eager = run_chat(writer(client, FakeClaude(scripted(done_at=1))))
    assert len(eager["transcript"]) == 6  # done from the first message, honoured only at min_turns
    endless = run_chat(writer(client, FakeClaude(scripted(done_at=99))), min_turns=4, max_turns=7)
    assert len(endless["transcript"]) == 7
    last = svc(client).chats.client.requests[-2]  # the seventh turn, before the summary
    assert "the last one: close the chat" in last["messages"][0]["content"]


def test_three_participants_are_convener_led(client):
    people = ["site-inspector", "bristol-compliance", "bristol-manager"]

    def to(request, n):
        return "bristol-compliance" if n % 4 == 1 else "bristol-manager"
    fake = FakeClaude(scripted(done_at=8, to=to))
    conversation = run_chat(writer(client, fake), convener="site-inspector", participants=people,
                            briefs={"site-inspector": "Only the inspector knows: three frames of V-504."})
    speakers = [line["speaker"] for line in conversation["transcript"]]
    assert speakers == ["site-inspector", "bristol-compliance", "site-inspector", "bristol-manager"] * 2
    convener_turn = next(r for r in fake.requests if not is_summary(r))
    assert convener_turn["output_config"]["format"]["schema"]["properties"]["to"]["anyOf"][0]["enum"] == ["bristol-compliance", "bristol-manager"]
    assert "Address one of" in convener_turn["messages"][0]["content"]
    assert set(conversation["participants"]) == set(people) and conversation["convener"] == "site-inspector"


def test_a_bad_draft_is_written_again_once_then_the_chat_falls_back(client):
    calls = {"n": 0}

    def once_bad(request):
        if is_summary(request):
            return SUMMARY
        calls["n"] += 1
        n = turn_number(request)
        if calls["n"] == 1:
            return dict(text="This simulation says the valve is fine.", done=False, to=None)
        return dict(text=f"Message {n}: the valve stays shut until the repair.", done=n >= 6, to=None)
    fake = FakeClaude(once_bad)
    conversation = run_chat(writer(client, fake))
    assert len(conversation["transcript"]) == 6 and all("simulation" not in line["text"] for line in conversation["transcript"])
    assert "cannot go out because it mentions 'simulat'" in fake.requests[1]["messages"][0]["content"]
    assert svc(client).chats.usage()["rejected"] == 1

    # Two bad drafts on the first turn: Claude never wrote a line, so the templates carry the chat.
    always_bad = FakeClaude(lambda r: SUMMARY if is_summary(r) else dict(text="Call me on +44 7700 900123.", done=False, to=None))
    templated = run_chat(writer(client, always_bad))
    assert [line["text"] for line in templated["transcript"]] == ["V-504 needs its repair booked.", "Noted, I'll file it."]
    assert templated["chat"]["writer"] == "templates" and "contact details" in templated["chat"]["fallbackReason"]
    assert templated["summary"]["headline"] == "V-504 repair to be booked" and templated["summaryBy"] == "hand-seed"


def test_losing_claude_mid_chat_closes_with_a_template_line(client):
    service = svc(client)

    def breaks(request):
        if is_summary(request):
            return SUMMARY
        n = turn_number(request)
        if n == 4:
            return RuntimeError("overloaded")
        return dict(text=f"Message {n}: the repair is on the list.", done=False, to=None)
    conversation = run_chat(writer(client, FakeClaude(breaks)))
    lines = conversation["transcript"]
    assert len(lines) == 4 and lines[-1]["speaker"] == "bristol-compliance"  # turn 4 was compliance's: it closes the chat
    assert lines[-1]["text"] == "Understood. Send me the details in writing and I'll follow up."
    assert conversation["status"] == "ended" and conversation["chat"]["writer"] == "mixed" and conversation["chat"]["claudeTurns"] == 3
    assert "Claude API error" in conversation["chat"]["fallbackReason"]
    # the backoff holds the summary too: written from the record
    assert conversation["summaryBy"] == "hand-seed" and conversation["summary"]["points"]
    assert all(service.store.get("a2a_task", line["taskId"])["state"] == "completed" for line in lines)
    status = client.get("/api/chats/status").json()
    assert status["errorsToday"] == 1 and status["backoffSeconds"] > 0 and "overloaded" in status["lastError"]
    # while backing off, the next chat is templated from the start
    after = run_chat(service.chats)
    assert after["chat"]["writer"] == "templates" and "backing off" in after["chat"]["fallbackReason"]


def test_caps_switch_and_key_fall_back_to_templates(client, monkeypatch):
    chats = writer(client, FakeClaude(scripted()))
    monkeypatch.setenv("STEWARD_CHAT_CLAUDE_MAX_CALLS_PER_DAY", "0")
    capped = run_chat(chats)
    assert capped["chat"]["writer"] == "templates" and "daily Claude call cap" in capped["chat"]["fallbackReason"]
    assert len(capped["transcript"]) == 2 and capped["summary"]["headline"] == "V-504 repair to be booked"
    monkeypatch.delenv("STEWARD_CHAT_CLAUDE_MAX_CALLS_PER_DAY")
    monkeypatch.setenv("STEWARD_CHAT_CLAUDE_BUDGET_USD_PER_DAY", "0")
    assert "budget is spent" in run_chat(chats)["chat"]["fallbackReason"]
    monkeypatch.delenv("STEWARD_CHAT_CLAUDE_BUDGET_USD_PER_DAY")
    monkeypatch.setenv("STEWARD_CHAT_CLAUDE", "false")
    assert run_chat(chats)["chat"]["fallbackReason"] == "STEWARD_CHAT_CLAUDE=false"
    monkeypatch.delenv("STEWARD_CHAT_CLAUDE")
    assert chats.client.requests == []  # none of these called Claude
    chats.client = None  # no key in the test environment: templates, and no real client is ever built
    plain = run_chat(chats, fallback=None, fallback_summary=None)
    assert plain["chat"]["fallbackReason"] == "ANTHROPIC_API_KEY is not set" and len(plain["transcript"]) == 2
    assert plain["summaryBy"] == "hand-seed" and plain["summary"]["headline"] == "V-504 valve repair"


def test_background_sources_have_an_hourly_limit_and_a_budget_share(client, monkeypatch):
    service = svc(client)
    chats = writer(client, FakeClaude(scripted(done_at=2)))
    for _ in range(SOURCE_LIMITS["planner"]):
        assert run_chat(chats, source="planner", min_turns=2, max_turns=2)["chat"]["writer"] == "claude"
    held = run_chat(chats, source="planner", min_turns=2, max_turns=2)
    assert held["chat"]["writer"] == "templates" and "limited to 4 Claude-written chats an hour" in held["chat"]["fallbackReason"]
    assert run_chat(chats, source="inspections", min_turns=2, max_turns=2)["chat"]["writer"] == "claude"  # no hourly limit
    # Half the day's budget spent: background chats are templated, the inspection chain and the People Officer keep Claude.
    used = service.chats.usage()
    monkeypatch.setenv("STEWARD_CHAT_CLAUDE_BUDGET_USD_PER_DAY", str(round(used["usd"] * 1.5, 6)))
    events_chat = run_chat(chats, source="events", min_turns=2, max_turns=2)
    assert events_chat["chat"]["writer"] == "templates" and "of the day's budget is spent" in events_chat["chat"]["fallbackReason"]
    assert run_chat(chats, source="people", min_turns=2, max_turns=2)["chat"]["writer"] == "claude"
    status = client.get("/api/chats/status").json()
    assert status["sources"]["planner"]["claudeChatsLastHour"] == 4 and status["sources"]["planner"]["hourlyLimit"] == 4
    assert status["sources"]["events"]["background"] is True and status["sources"]["events"]["heldBecause"]
    assert status["sources"]["inspections"]["hourlyLimit"] is None and status["active"] == []


def test_realtime_chats_pace_their_lines(client, monkeypatch):
    monkeypatch.setenv("STEWARD_CHAT_TURN_SECONDS", "0.05")
    started = time.monotonic()
    conversation = run_chat(writer(client, FakeClaude(scripted(done_at=4))), realtime=True, min_turns=4, max_turns=4)
    assert len(conversation["transcript"]) == 4 and time.monotonic() - started >= 0.15


def test_the_status_route(client):
    status = client.get("/api/chats/status").json()
    assert status["model"] == "claude-opus-5-5" and status["effort"] == "low" and status["maxCalls"] == 400 and status["budgetUsd"] == 6.0
    assert status["enabled"] is False and status["configured"] is False and status["callsToday"] == 0
    assert set(status["sources"]) >= {"planner", "events", "inspections", "people"} and status["turnSeconds"] == 4.0


# ---- the incremental API, call() and summaries -------------------------------------------------------------------------

def test_open_say_close_carry_lines_over_a2a(client):
    service = svc(client)
    conversations = service.conversations
    opened = conversations.open_call("bristol-manager", "myer-manager", "Shared examiner", site_ids=[BR], inspectionId="ins-1", id="nope")
    assert opened["status"] == "live" and opened["inspectionId"] == "ins-1" and opened["id"].startswith("conv") and opened["siteIds"] == [BR, MY]
    conversations.say(opened["id"], "bristol-manager", "Can your examiner come to us on Tuesday?")
    conversations.say(opened["id"], "myer-manager", "Yes, Northgate can do Tuesday morning.")
    conversations.say(opened["id"], "bristol-manager", "Booked. I'll link the windows.")
    live = conversations._raw(opened["id"])
    task = service.store.get("a2a_task", live["transcript"][0]["taskId"])
    assert {line["taskId"] for line in live["transcript"]} == {task["id"]}  # one task for the pair, as call() does
    assert task["caller"] == "bristol-manager" and task["target"] == "myer-manager" and task["state"] == "working"
    assert [m["role"] for m in task["messages"]] == ["caller", "agent", "caller"]
    closed = conversations.close_call(opened["id"], dict(headline="Examiner lined up", points=[], decisions=[], actions=[]), "hand-seed")
    assert closed["status"] == "ended" and service.store.get("a2a_task", task["id"])["state"] == "completed"
    assert closed["summary"]["headline"] == "Examiner lined up"
    with pytest.raises(Exception):
        conversations.say(opened["id"], "bristol-manager", "One more thing.")
    lines = sorted((c for c in chat_changes(client, BR, opened["id"]) if c.get("status") == "line"), key=lambda c: c["version"])
    assert [(c["seq"], c["speaker"]) for c in lines] == [(1, "bristol-manager"), (2, "myer-manager"), (3, "bristol-manager")]
    assert lines[0]["summary"] == "Plant Manager · Bristol: Can your examiner come to us on Tuesday?" and lines[0]["conversationId"] == opened["id"]


def test_call_is_unchanged_on_top_of_the_incremental_api(client):
    service = svc(client)
    turns = [dict(speaker="myer-engineer", text="P-101 is growling at {level}."), dict(speaker="myer-manager", text="Swap to P-103."),
             dict(speaker="myer-engineer", text="Done.")]
    call = service.conversations.call("myer-engineer", "myer-manager", "P-101 bearing", turns, site_ids=[MY], context=dict(level="5.4 mm/s"),
                                      summary=dict(headline="P-101 swapped", points=[], decisions=[], actions=[]))
    assert [line["speaker"] for line in call["transcript"]] == ["myer-engineer", "myer-manager", "myer-engineer"]
    assert call["transcript"][0]["text"] == "P-101 is growling at 5.4 mm/s." and call["status"] == "ended" and call["summaryBy"] == "hand-seed"
    task = service.store.get("a2a_task", call["transcript"][0]["taskId"])
    assert task["state"] == "completed" and task["messages"][-1]["parts"][0]["text"] == "(end of call)"
    statuses = [c.get("status") for c in chat_changes(client, MY, call["id"])]
    assert "line" not in statuses and statuses.count("started") == 1 and statuses.count("ended") == 1
    shown = client.get(f"/api/conversations/{call['id']}").json()
    assert "voiceNote" not in shown and shown["summary"]["headline"] == "P-101 swapped"


def test_every_conversation_the_api_returns_has_a_summary(client):
    service = svc(client)
    asked = service.conversations.message("myer-manager", "myer-compliance", "Permit for P-101", "Is the hot-work permit signed?", site_ids=[MY])
    service.conversations.answer(asked["id"], "myer-compliance", "Signed this morning.")
    assert service.store.get("conversation", asked["id"], "")["summary"] is None  # written on read, never stored
    shown = client.get(f"/api/conversations/{asked['id']}").json()
    assert shown["summaryBy"] == "record" and shown["summary"]["headline"].startswith("Plant Manager · Myer asked Compliance Officer · Myer")
    assert shown["summary"]["points"] == ["Signed this morning."]
    service.bus.send("myer-technician", "myer-engineer", "Gauge PG-602 reads 2.4 bar against the hand probe.", dict(kind="note"), MY, deliver=False)
    listed = client.get(f"/api/conversations?siteId={MY}").json()
    assert listed and all(c.get("summary") and c["summary"].get("headline") for c in listed)
    assert all("voiceNote" not in c for c in listed)
    derived = next(c for c in listed if c.get("derived") and "PG-602" in c["topic"])
    assert derived["summaryBy"] == "record" and "Field Technician · Myer asked Site Engineer · Myer" in derived["summary"]["headline"]
    # a summary posted later replaces the one written from the record
    posted = client.post(f"/api/conversations/{asked['id']}/summary", json={"summary": {"headline": "Permit signed", "points": [], "decisions": [],
                                                                                          "actions": []}, "summaryBy": "claude-opus-5-5"}).json()
    assert posted["summary"]["headline"] == "Permit signed" and posted["summaryBy"] == "claude-opus-5-5" and "voiceNote" not in posted


# ---- the producers --------------------------------------------------------------------------------------------------------

def test_the_planners_cross_site_coordination_is_a_long_claude_chat(client):
    service = svc(client)
    fake = FakeClaude(scripted(done_at=8))
    writer(client, fake)
    moment = datetime.now(timezone.utc)
    slot, _ = choose_slot(BR, "pressure", moment, None, True)
    exam = service.store.get("maintenance_window", "mw-my-tk201-exam", "")
    exam["date"] = (slot.astimezone(ZoneInfo("Europe/London")).date() + timedelta(days=2)).isoformat()
    service.maintenance._put(exam)
    booked = {w["obligationId"]: w for w in service.maintenance_planner.tick(moment)}
    bristol = booked["ob-br-sp102-pipework"]
    call = client.get(f"/api/conversations/{bristol['conversationId']}").json()
    assert call["participants"] == ["bristol-manager", "myer-manager"] and call["siteIds"] == [BR, MY] and call["maintenanceWindowId"] == bristol["id"]
    assert len(call["transcript"]) == 8 and call["chat"]["source"] == "planner" and call["chat"]["writer"] == "claude"
    assert call["summaryBy"] == "claude-opus-5-5" and bristol["coordination"]["mode"] == "linked"
    first = next(r for r in fake.requests if not is_summary(r) and "SP-102" in r["messages"][0]["content"])
    assert "TK-201" in first["messages"][0]["content"] and "The plan on the table" in first["messages"][0]["content"]
    assert service.chats._source_times("planner")  # counted against the planner's hourly limit


def test_an_events_discussion_is_a_long_chat_with_the_events_turns_as_talking_points(client):
    from src.events import KIND  # noqa: F401  (the module loads with the chat writer wired in)
    service = svc(client)
    chat_fake = FakeClaude(scripted(done_at=6))
    writer(client, chat_fake)
    event = dict(
        title="P-101 drive-end bearing running rough", kind="equipment_fault", assetTag="P-101", severity="medium",
        narrative="The night round heard a growl from the P-101 drive-end bearing; vibration is climbing.",
        effects=[dict(type="reading", assetTag="P-101", attribute="vibration_mms", values=[2.2, 2.9, 3.8, 4.7, 5.4], minutesApart=2),
                 dict(type="issue", kind="bearing_noise", severity="medium", summary="P-101 drive-end bearing growling; vibration 5.4 mm/s and rising."),
                 {"type": "conversation", "from": "myer-engineer", "to": "myer-manager", "topic": "P-101 bearing",
                  "turns": [dict(speaker="myer-engineer", text="P-101 is at 5.4 mm/s and growling. I want P-103 on duty while we look at it."),
                            dict(speaker="myer-manager", text="Do it. Book the bearing change for the first slot and send me the readings.")]}],
        resolvesAfterMinutes=25)
    events = service.events
    events.client = FakeClaude(lambda request: event)
    record = events.fire(datetime.now(timezone.utc), site=MY)
    call = service.store.get("conversation", record["conversationIds"][0], "")
    assert call["eventId"] == record["id"] and call["origin"] == "run" and call["chat"]["source"] == "events"
    assert len(call["transcript"]) == 6 and call["summaryBy"] == "claude-opus-5-5"
    talking = next(r for r in chat_fake.requests if not is_summary(r))
    assert "I want P-103 on duty" in talking["messages"][0]["content"] and "vibration_mms readings: 2.2" in talking["messages"][0]["content"]


def test_an_unexpected_error_mid_chat_returns_a_closed_chat_instead_of_raising(client, monkeypatch):
    service = svc(client)
    chats = writer(client, FakeClaude(scripted(done_at=8)))
    real_say = service.conversations.say
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == fail_on["n"]:
            raise RuntimeError("the bus hiccuped")
        return real_say(*args, **kwargs)
    monkeypatch.setattr(service.conversations, "say", flaky)

    fail_on = {"n": 3}  # two Claude lines went out, the third broke
    broken = run_chat(chats)
    assert broken["status"] == "ended" and len(broken["transcript"]) == 2 and broken["chat"]["writer"] == "mixed"
    assert broken["chat"]["claudeTurns"] == 2 and "stopped on an error (RuntimeError: the bus hiccuped)" in broken["chat"]["fallbackReason"]
    assert broken["summary"] and broken["summaryBy"] == "claude-opus-5-5"
    errors = [e for e in service.store.events(BR, limit=5000) if e["type"] == "chat.error"]
    assert errors and "the bus hiccuped" in errors[-1]["detail"]

    calls["n"], fail_on["n"] = 0, 1  # the very first line broke: the templates carry the chat
    templated = run_chat(chats)
    assert templated["status"] == "ended" and templated["chat"]["writer"] == "templates"
    assert [line["text"] for line in templated["transcript"]] == ["V-504 needs its repair booked.", "Noted, I'll file it."]
