"""Events at the sites (events.py): Claude writes one plausible event for the quietest site, validation drops what is not real
(assets, attributes, values out of limits, agents that do not exist or may not talk), the services play it (sensor facts with
ref feed:events, an issue with the event id, calls over the A2A bus, an obligation note, a maintenance request the planner picks
up) and put it right later; the daily call cap, the budget, a missing key, the switch, refusals and API errors fall back to the
templates (with a 60 s backoff after an error); recent titles go into the prompt; nothing ever reaches a person.

The Anthropic client is a fake injected into the director (constructing a real one fails the test), and every outbound provider
path raises: no real API call and no outbound message anywhere."""
import json
import random
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.events import EVENT_KINDS, FALLBACK_BETA, KIND, SENSOR_REF, SYSTEM, TEMPLATES, Context, limits_for
from src.main import create_app

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
TZ = {MY: "Australia/Melbourne", BR: "Europe/London", TM: "Asia/Tokyo"}


@pytest.fixture(autouse=True)
def no_real_anthropic(monkeypatch):
    import anthropic

    def refuse(*args, **kwargs):
        raise AssertionError("a real Anthropic client was created")
    monkeypatch.setattr(anthropic, "Anthropic", refuse)


@pytest.fixture(autouse=True)
def nothing_leaves(monkeypatch):
    """Every path to a person or an outside provider is recorded and raises; after each test none was taken (recorded, because
    the A2A bus catches a provider's exception and falls back to local delivery)."""
    from src import a2a, people, providers, reality
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
    monkeypatch.setattr(people.PeopleService, "send_notice", guard("PeopleService.send_notice"))
    monkeypatch.setattr(people.PeopleService, "send_document", guard("PeopleService.send_document"))
    monkeypatch.setattr(reality.RealityService, "dispatch", guard("RealityService.dispatch"))
    monkeypatch.setattr(reality.RealityService, "send", guard("RealityService.send"))
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


def director(client, fake=None, seed=7):
    events = svc(client).events
    events.client = fake
    events.rng = random.Random(seed)
    return events


def response(payload=None, stop="end_turn", text=None, model="claude-opus-5-5", input_tokens=4000, output_tokens=900):
    body = text if text is not None else json.dumps(payload)
    return SimpleNamespace(model=model, stop_reason=stop, stop_details=None,
                           content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0))


class FakeClaude:
    """Stands in for anthropic.Anthropic(): `.beta.messages.create(**kwargs)` records the request and answers from `script`."""

    def __init__(self, script):
        self.script = script  # callable(request) -> event dict | response object | exception
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        out = self.script(kwargs)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, SimpleNamespace) else response(out)


def bearing_event():
    return dict(
        title="P-101 drive-end bearing running rough", kind="equipment_fault", assetTag="P-101", severity="medium",
        narrative="The night round heard a growl from the P-101 drive-end bearing; vibration is climbing.",
        effects=[
            dict(type="reading", assetTag="P-101", attribute="vibration_mms", values=[2.2, 2.9, 3.8, 4.7, 5.4], minutesApart=2),
            dict(type="issue", kind="bearing_noise", severity="medium", summary="P-101 drive-end bearing growling; vibration 5.4 mm/s and rising."),
            {"type": "conversation", "from": "myer-engineer", "to": "myer-manager", "topic": "P-101 bearing",
             "turns": [dict(speaker="myer-engineer", text="P-101 is at 5.4 mm/s and growling. I want P-103 on duty while we look at it."),
                       dict(speaker="myer-manager", text="Do it. Book the bearing change for the first slot and send me the readings.")]},
            {"type": "conversation", "from": "myer-manager", "to": "bristol-manager", "topic": "Spare bearing for P-101",
             "turns": [dict(speaker="myer-manager", text="Do you still hold a spare drive-end bearing from your P-103 job?"),
                       dict(speaker="bristol-manager", text="One on the shelf. I'll have it sent over today.")]},
            dict(type="obligation_note", obligationId="ob-my-tk201-scheme", note="Pump changeover this week; check the TK-201 pre-charge afterwards."),
            dict(type="maintenance_request", assetTag="P-101", reason="P-101: replace the drive-end bearing and check the coupling alignment."),
        ],
        resolvesAfterMinutes=25)


def facts_of(service, site, tag, attribute):
    return [f for f in service.store.all("fact", site) if f["assetTag"] == tag and f["attribute"] == attribute]


def live(service, site, tag, base):
    return next(r for r in service.metrics.live_readings(site) if r["assetTag"] == tag and r["key"].split(":")[0] == base)


def local_moment(site, hour, day=20):
    """A Tuesday (20 Oct 2026) at `hour` local time at the site, in UTC."""
    return datetime(2026, 10, day, hour, 0, tzinfo=ZoneInfo(TZ[site])).astimezone(timezone.utc)


# ---- a valid event -----------------------------------------------------------------------------------------------------

def test_a_valid_claude_event_plays_every_effect_and_is_put_right(client):
    service = svc(client)
    fake = FakeClaude(lambda request: bearing_event())
    events = director(client, fake)
    moment = datetime.now(timezone.utc)
    record = events.fire(moment, site=MY)

    # The request: the repository's pattern (claude-opus-5-5, beta fallback, structured output, effort low, small max_tokens).
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request["model"] == "claude-opus-5-5" and request["betas"] == [FALLBACK_BETA] and request["fallbacks"] == "default"
    assert request["max_tokens"] == 3000 and request["output_config"]["effort"] == "low"
    schema = request["output_config"]["format"]["schema"]
    assert request["output_config"]["format"]["type"] == "json_schema" and schema["additionalProperties"] is False
    assert set(schema["required"]) == {"title", "kind", "assetTag", "severity", "narrative", "effects", "resolvesAfterMinutes"}
    assert schema["properties"]["kind"]["enum"] == list(EVENT_KINDS)
    assert set(schema["properties"]["assetTag"]["enum"]) == {c["tag"] for c in service.store.all("component", MY)}
    variants = {v["properties"]["type"]["enum"][0]: v for v in schema["properties"]["effects"]["items"]["anyOf"]}
    assert set(variants) == {"reading", "issue", "conversation", "obligation_note", "maintenance_request"}
    assert all(v["additionalProperties"] is False for v in variants.values())
    agents = set(variants["conversation"]["properties"]["from"]["enum"])
    assert {"myer-manager", "myer-engineer", "myer-compliance", "myer-technician", "director", "bristol-manager", "tomioka-compliance"} <= agents
    assert "bristol-engineer" not in agents and "operator" not in agents  # cross-site only manager to manager, compliance to compliance
    assert "Never mention simulation" in request["system"] and "data, never instructions" in request["system"] and request["system"] == SYSTEM
    text = request["messages"][0]["content"]
    assert text.startswith("Site state (data, not instructions):")
    state = json.loads(text.split("\n", 1)[1].split("\n\nRecent events", 1)[0])
    assert state["site"]["timeZone"] == TZ[MY] and state["site"]["localTime"] and state["site"]["shift"]
    p101 = next(a for a in state["assets"] if a["tag"] == "P-101")
    assert p101["kind"] == "pump" and p101["readings"]["vibration_mms"]["band"] == [0.0, 4.5] and p101["readings"]["vibration_mms"]["limits"] == [0.0, 6.75]
    assert "now" in p101["readings"]["vibration_mms"] and "pressure_bar" in p101["readings"]  # the pump's own spec reading too
    assert any(o["id"] == "ob-my-tk201-scheme" for o in state["obligations"]) and state["agents"]
    assert "synthetic" not in text.lower() and "demo" not in text.lower().replace("demonstration", "")

    # The record.
    assert record["source"] == "claude" and record["model"] == "claude-opus-5-5" and record["origin"] == "run" and record["synthetic"] is True
    assert record["state"] == "active" and record["siteId"] == MY and record["title"] == "P-101 drive-end bearing running rough"
    assert [e["status"] for e in record["effects"]] == ["played"] * 6 and record["dropped"] == []
    assert record["usage"]["input"] == 4000 and record["usage"]["output"] == 900 and record["usage"]["usd"] == pytest.approx(0.034)
    assert record["leadAgentId"] == "myer-engineer"
    assert abs(parse(record["resolveAt"]) - moment - timedelta(minutes=25)) < timedelta(seconds=1)

    # Readings: sensor facts with the event's source ref, ending on the last value; the live metric is out of band.
    facts = sorted(facts_of(service, MY, "P-101", "vibration_mms"), key=lambda f: f["observedAt"])
    assert [f["value"] for f in facts] == [2.2, 2.9, 3.8, 4.7, 5.4]
    assert all(f["source"] == {"kind": "sensor", "ref": SENSOR_REF} and f.get("synthetic") is True for f in facts)
    assert all(service.store.get("attestation", f["attestationId"]) for f in facts)
    reading = live(service, MY, "P-101", "vibration_mms")
    assert reading["value"] == 5.4 and reading["state"] == "high"

    # The issue, with the event id, on the event's asset.
    issue = service.store.get("issue", record["issueIds"][0], MY)
    assert issue["status"] == "open" and issue["eventId"] == record["id"] and issue["origin"] == "run" and issue["assetTag"] == "P-101"
    assert issue["kind"] == "bearing_noise" and issue["severity"] == "medium" and issue["id"].startswith("iss-ev-")

    # Calls over the A2A bus, one of them cross-site.
    calls = [service.store.get("conversation", cid, "") for cid in record["conversationIds"]]
    assert [c["participants"] for c in calls] == [["myer-engineer", "myer-manager"], ["myer-manager", "bristol-manager"]]
    assert all(c["origin"] == "run" and c["eventId"] == record["id"] and c["kind"] == "call" and c["status"] == "ended" for c in calls)
    assert all(len(c["transcript"]) == 2 and all(line.get("taskId") for line in c["transcript"]) for c in calls)
    assert BR in calls[1]["siteIds"] and calls[0]["issueId"] == issue["id"]
    listed = client.get(f"/api/conversations?siteId={MY}").json()
    assert {c["id"] for c in calls} <= {c["id"] for c in listed}  # origin run: shown by default

    # The note and the maintenance request.
    obligation = service.store.get("obligation", "ob-my-tk201-scheme", MY)
    assert obligation["note"] == "Pump changeover this week; check the TK-201 pre-charge afterwards."
    assert obligation["notes"][-1]["eventId"] == record["id"]
    window = service.store.get("maintenance_window", record["windowIds"][0], "")
    assert window["status"] == "proposed" and window["proposedBy"] == "myer-manager" and window["assetTags"] == ["P-101"]
    assert window["requestedBy"] == "myer-engineer" and window["eventId"] == record["id"] and window["origin"] == "run" and window["workKind"]
    assert parse(window["startAt"]) - datetime.now(timezone.utc) >= timedelta(hours=11, minutes=59) and window["localStart"]

    # Changes the dashboard already shows.
    changes = client.get(f"/api/properties/{MY}/changes?latest=true&limit=1000").json()["changes"]
    types = {c["type"] for c in changes if c.get("refId") in [record["id"], issue["id"], window["id"], *record["conversationIds"], obligation["id"]]}
    assert {"event", "issue", "conversation", "maintenance", "obligation"} <= types
    started = next(c for c in changes if c["type"] == "event" and c["refId"] == record["id"])
    assert started["status"] == "started" and started["eventId"] == record["id"] and started["assetTag"] == "P-101"
    assert started["summary"].startswith("P-101 drive-end bearing running rough:")

    # The planner picks the request up: the Manager approves it and tells the team.
    service.maintenance_planner.tick(moment)
    window = service.store.get("maintenance_window", window["id"], "")
    assert window["status"] == "approved" and window["approvedBy"] == "myer-manager" and window["pickedUpAt"]
    team = [service.store.get("conversation", cid, "") for cid in window["teamConversationIds"]]
    assert [c["participants"] for c in team] == [["myer-manager", "myer-engineer"], ["myer-manager", "myer-technician"]]
    assert all(c["status"] == "ended" and len(c["transcript"]) == 2 for c in team)
    assert service.maintenance_planner.pick_up_requests(parse(window["endAt"]) - timedelta(minutes=1)) == []
    assert service.store.get("maintenance_window", window["id"], "")["status"] == "approved"
    service.maintenance_planner.pick_up_requests(parse(window["endAt"]) + timedelta(minutes=1))  # the visit's slot has passed
    assert service.store.get("maintenance_window", window["id"], "")["status"] == "done"

    # Put right after resolvesAfterMinutes: the reading back in band, the issue resolved, a Change and the Manager's memory.
    assert events.resolve_due(moment + timedelta(minutes=24)) == []
    resolved = events.resolve_due(moment + timedelta(minutes=26))
    assert [r["id"] for r in resolved] == [record["id"]]
    record = events.get(record["id"])
    assert record["state"] == "resolved" and record["resolution"]["issueIds"] == [issue["id"]]
    back = record["effects"][0]["resolvedValue"]
    assert 0 <= back <= 4.5 and live(service, MY, "P-101", "vibration_mms")["state"] == "normal"
    assert service.store.get("issue", issue["id"], MY)["status"] == "resolved"
    changes = client.get(f"/api/properties/{MY}/changes?latest=true&limit=1000").json()["changes"]
    assert any(c["type"] == "event" and c["refId"] == record["id"] and c["status"] == "resolved" and c["summary"].startswith("Resolved:") for c in changes)
    memories = [m for m in service.store.all("agent_memory", "") if (m.get("refs") or {}).get("eventId") == record["id"]]
    assert memories and memories[0]["agentId"] == "myer-manager" and memories[0]["origin"] == "run"
    assert events.resolve_due(moment + timedelta(hours=2)) == []  # once


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---- validation --------------------------------------------------------------------------------------------------------

def test_invalid_assets_attributes_values_and_speakers_are_dropped(client):
    service = svc(client)
    turns = [dict(speaker="myer-technician", text="PG-602 needle sticks near 3.4 bar again."), dict(speaker="myer-engineer", text="Tap it and log it.")]
    head = dict(title="PG-602 needle sticking near the top of the dial", kind="sensor_drift", assetTag="PG-602", severity="low",
                narrative="The PG-602 needle sticks near the top of the dial; the technician has tapped it free twice this shift.")
    readings = dict(head, resolvesAfterMinutes=500, effects=[
        dict(type="reading", assetTag="XX-999", attribute="pressure_bar", values=[1, 2, 3], minutesApart=2),
        dict(type="reading", assetTag="PG-602", attribute="humidity_pct", values=[50, 55, 60], minutesApart=2),
        dict(type="reading", assetTag="PG-602", attribute="pressure_bar", values=[2.4, 3.9, 9.5], minutesApart=2),
        dict(type="reading", assetTag="PG-602", attribute="pressure_bar", values=[2.4, 2.6], minutesApart=2),
        dict(type="reading", assetTag="PG-602", attribute="pressure_bar", values=[2.4, 2.9, 3.4, "high"], minutesApart=2),
        dict(type="reading", assetTag="PG-602", attribute="pressure_bar", values=[2.4, 2.9, 3.4, 3.8], minutesApart=40),
        dict(type="reading", assetTag="PG-602", attribute="pressure_bar", values=[2.4, 2.5, 2.6], minutesApart=2),
        dict(type="issue", kind="Gauge Sticking!", severity="low", summary="PG-602 needle sticking near the top of the dial."),
        dict(type="issue", kind="compliance_overdue", severity="high", summary="PG-602 needle sticking near the top of the dial."),
        dict(type="issue", kind="gauge_sticking", severity="urgent", summary="PG-602 needle sticking near the top of the dial."),
        dict(type="obligation_note", obligationId="ob-br-pv301-exam", note="Not this site's obligation."),
        dict(type="telemetry", assetTag="PG-602"),
    ])
    talk = dict(head, resolvesAfterMinutes=None, effects=[
        {"type": "conversation", "from": "myer-technician", "to": "harbor-engineer", "topic": "PG-602", "turns": turns},
        {"type": "conversation", "from": "myer-engineer", "to": "bristol-engineer", "topic": "PG-602", "turns": turns},
        {"type": "conversation", "from": "myer-technician", "to": "bristol-manager", "topic": "PG-602 gauge",
         "turns": [dict(speaker="myer-technician", text="Your PG-602 ever stick?"), dict(speaker="bristol-manager", text="No.")]},
        {"type": "conversation", "from": "bristol-manager", "to": "bristol-compliance", "topic": "PG-602 gauge",
         "turns": [dict(speaker="bristol-manager", text="Seen this?"), dict(speaker="bristol-compliance", text="No.")]},
        {"type": "conversation", "from": "myer-technician", "to": "myer-engineer", "topic": "PG-602 gauge",
         "turns": [dict(speaker="myer-technician", text="It sticks."), dict(speaker="myer-manager", text="Log it.")]},
        {"type": "conversation", "from": "myer-technician", "to": "myer-engineer", "topic": "PG-602 gauge",
         "turns": [dict(speaker="myer-engineer", text="Does it stick?"), dict(speaker="myer-technician", text="Yes.")]},
        {"type": "conversation", "from": "myer-technician", "to": "myer-engineer", "topic": "PG-602 gauge",
         "turns": [dict(speaker="myer-technician", text="This simulated alarm again."), dict(speaker="myer-engineer", text="Log it.")]},
        {"type": "conversation", "from": "myer-technician", "to": "myer-engineer", "topic": "PG-602 gauge", "turns": turns[:1]},
        {"type": "conversation", "from": "myer-technician", "to": "myer-engineer", "topic": "PG-602 gauge sticking", "turns": turns},
        dict(type="maintenance_request", assetTag="PV-301", reason="PV-301 belongs to the pump house, not the plant room."),
        dict(type="maintenance_request", assetTag="PG-602", reason="Call 0412 345 678 for the gauge contractor."),
    ])
    answers = iter([readings, talk])
    events = director(client, FakeClaude(lambda request: next(answers)))
    first = events.fire(datetime.now(timezone.utc), site=MY)
    second = events.fire(datetime.now(timezone.utc), site=MY)
    assert first["source"] == second["source"] == "claude"
    for record, expected in ((first, [("reading", "PG-602")]), (second, [("conversation", "myer-technician")])):
        played = [(e["type"], e.get("assetTag") or e.get("from")) for e in record["effects"]]
        assert played == expected, "\n".join(f"{d['index']}: {d['reason']}" for d in record["dropped"])
    reading = first["effects"][0]
    assert reading["values"] == [2.4, 2.9, 3.4, 3.8] and reading["minutesApart"] == 10.0 and reading["limits"] == [0.5, 4.5]
    assert first["resolvesAfterMinutes"] == 120 and second["resolvesAfterMinutes"] is None and second["resolveAt"] is None
    reasons = [d["reason"] for d in first["dropped"] + second["dropped"]]
    assert len(reasons) == 21
    expected = ["'XX-999' is not at this site", "'humidity_pct' is not a reading of PG-602 (gauge)", "value 9.5 is outside its limits 0.5 to 4.5 bar",
                "a ramp needs 3 to 8 values", "a ramp value is not a number", "a second ramp on PG-602.pressure_bar",
                "'harbor-engineer' is not an agent this site can talk to", "'bristol-engineer' is not an agent this site can talk to",
                "may not message", "neither agent works at this site", "turn 2 speaker 'myer-manager' is not on the call", "the caller speaks first",
                "mentions 'simulat'", "a call needs 2 to 4 turns", "is not short snake_case", "belongs to another workflow",
                "issue severity must be low, medium or high", "is not one of this site's", "'PV-301' is not at this site", "carries contact details",
                "unknown effect type 'telemetry'"]
    for snippet in expected:
        assert any(snippet in reason for reason in reasons), (snippet, reasons)
    # Nothing invalid reached the records.
    assert not facts_of(service, MY, "XX-999", "pressure_bar") and not facts_of(service, MY, "PG-602", "humidity_pct")
    assert [f["value"] for f in sorted(facts_of(service, MY, "PG-602", "pressure_bar"), key=lambda f: f["observedAt"])
            if f["source"]["ref"] == SENSOR_REF] == [2.4, 2.9, 3.4, 3.8]
    assert not [i for i in service.store.all("issue", MY) if i.get("eventId") in (first["id"], second["id"])]
    assert not [w for w in service.store.all("maintenance_window", "") if w.get("eventId") in (first["id"], second["id"])]
    call = svc(client).store.get("conversation", second["conversationIds"][0], "")
    assert call["participants"] == ["myer-technician", "myer-engineer"] and call["topic"] == "PG-602 gauge sticking"
    many = dict(head, resolvesAfterMinutes=None, effects=[dict(type="telemetry")] * 13)
    events.client = FakeClaude(lambda request: many)
    capped = events.fire(datetime.now(timezone.utc), site=MY)
    assert capped["source"] == "template" and capped["dropped"][-1]["reason"] == "more than twelve effects listed"


def test_an_event_with_nothing_valid_left_falls_back_to_a_template(client):
    answer = dict(title="Nothing real here at all", kind="leak", assetTag="P-103", severity="low", narrative="Every effect below is invalid on purpose.",
                  effects=[dict(type="reading", assetTag="XX-1", attribute="level_pct", values=[1, 2, 3], minutesApart=1),
                           dict(type="issue", kind="out_of_range", severity="low", summary="A computed kind no event may raise.")],
                  resolvesAfterMinutes=None)
    events = director(client, FakeClaude(lambda request: answer))
    record = events.fire(datetime.now(timezone.utc), site=BR)
    assert record["source"] == "template" and record["templateId"] in dict(TEMPLATES)
    assert record["fallbackReason"] == "Claude's event did not validate: no valid effect remained"
    assert record["usage"]["input"] == 4000  # the call was made and paid for; its usage stays on the record
    assert len(record["dropped"]) >= 2
    status = client.get("/api/events/status").json()
    assert status["invalidToday"] == 1 and status["callsToday"] == 1 and status["fallbacksToday"] == 1
    bad_kind = dict(bearing_event(), kind="explosion")
    bad_asset = dict(bearing_event(), assetTag="PV-301")
    bad_title = dict(bearing_event(), title="A synthetic test event for the demo")
    for answer in (bad_kind, bad_asset, bad_title):
        events.client = FakeClaude(lambda request, answer=answer: answer)
        assert events.fire(datetime.now(timezone.utc), site=MY)["source"] == "template"


def test_limits_are_a_window_twice_the_band_inside_the_physical_range():
    assert limits_for("pressure_bar", "bar", (1.5, 3.5)) == (0.5, 4.5)
    assert limits_for("humidity_pct", "%", (40, 65)) == (27.5, 77.5)
    assert limits_for("level_pct", "%", (10, 95)) == (0.0, 100.0)
    assert limits_for("crack_width_mm", "mm", (0, 0.3)) == (0.0, 0.45)
    assert limits_for("temperature_c", "°C", (5, 40)) == (-12.5, 57.5)


# ---- caps, budget, switch, key, errors -----------------------------------------------------------------------------------

def test_the_daily_call_cap_and_the_budget_fall_back_to_templates(client, monkeypatch):
    fake = FakeClaude(lambda request: bearing_event())
    events = director(client, fake)
    monkeypatch.setenv("STEWARD_EVENTS_MAX_PER_DAY", "1")
    first = events.fire(datetime.now(timezone.utc), site=MY)
    second = events.fire(datetime.now(timezone.utc), site=MY)
    assert first["source"] == "claude" and second["source"] == "template" and len(fake.requests) == 1
    assert second["fallbackReason"] == "the daily Claude call cap is reached (1 of 1 calls today)"
    status = client.get("/api/events/status").json()
    assert status["capReached"] is True and status["callsToday"] == 1 and status["fallbacksToday"] == 1 and status["maxCallsPerDay"] == 1

    monkeypatch.setenv("STEWARD_EVENTS_MAX_PER_DAY", "120")
    monkeypatch.setenv("STEWARD_EVENTS_BUDGET_USD_PER_DAY", "0.05")
    events.client = FakeClaude(lambda request: response(bearing_event(), input_tokens=4000, output_tokens=3000))  # $0.076 at $4 / $20
    third = events.fire(datetime.now(timezone.utc), site=MY)  # spend so far $0.034: under the budget, so Claude is asked
    fourth = events.fire(datetime.now(timezone.utc), site=MY)
    assert third["source"] == "claude"
    assert fourth["source"] == "template" and fourth["fallbackReason"].startswith("the daily Claude budget is spent ($0.11 of $0.05")
    status = client.get("/api/events/status").json()
    assert status["estimatedUsd"] == pytest.approx(0.11) and status["budgetEnforced"] is True and status["capReached"] is True
    assert status["tokens"]["input"] == 8000 and status["tokens"]["output"] == 3900
    assert status["claude"]["pricesPerMillionTokens"]["input"] == 4.0 and status["claude"]["pricesPerMillionTokens"]["output"] == 20.0


def test_defaults_are_the_owners_numbers(client):
    events = director(client)
    assert events.interval() == (3.0, 7.0) and events.max_calls() == 120 and events.budget_usd() == 10.0
    assert events.model() == "claude-opus-5-5" and events.max_tokens() == 3000


def test_no_key_or_the_switch_off_uses_templates_without_a_call(client, monkeypatch):
    events = director(client)  # no client injected and ANTHROPIC_API_KEY unset
    record = events.fire(datetime.now(timezone.utc), site=TM)
    assert record["source"] == "template" and record["fallbackReason"] == "ANTHROPIC_API_KEY is not set" and record["usage"] is None
    fake = FakeClaude(lambda request: bearing_event())
    events.client = fake
    monkeypatch.setenv("STEWARD_EVENTS_CLAUDE", "false")
    record = events.fire(datetime.now(timezone.utc), site=TM)
    assert record["source"] == "template" and record["fallbackReason"] == "STEWARD_EVENTS_CLAUDE=false" and fake.requests == []
    status = client.get("/api/events/status").json()
    assert status["claude"]["enabled"] is False and status["fallbacksToday"] == 2 and status["callsToday"] == 0


def test_an_api_error_falls_back_and_backs_off_for_60_seconds(client):
    calls = []

    def script(request):
        calls.append(1)
        return RuntimeError("overloaded") if len(calls) == 1 else bearing_event()
    fake = FakeClaude(script)
    events = director(client, fake)
    first = events.fire(datetime.now(timezone.utc), site=MY)
    assert first["source"] == "template" and first["fallbackReason"] == "Claude API error (RuntimeError: overloaded); backing off 60 s"
    status = client.get("/api/events/status").json()
    assert 55 <= status["backoffSeconds"] <= 60 and status["errorsToday"] == 1 and status["lastError"] == "RuntimeError: overloaded"
    second = events.fire(datetime.now(timezone.utc), site=MY)
    assert second["source"] == "template" and second["fallbackReason"].startswith("backing off after a Claude API error") and len(fake.requests) == 1
    events.backoff_until = time.monotonic() - 1  # the 60 s are over
    third = events.fire(datetime.now(timezone.utc), site=MY)
    assert third["source"] == "claude" and len(fake.requests) == 2


def test_a_refusal_or_an_unreadable_answer_falls_back(client):
    events = director(client, FakeClaude(lambda request: response(stop="refusal", text="")))
    record = events.fire(datetime.now(timezone.utc), site=BR)
    assert record["source"] == "template" and record["fallbackReason"] == "Claude declined to answer"
    events.client = FakeClaude(lambda request: response(text="not json", stop="max_tokens"))
    record = events.fire(datetime.now(timezone.utc), site=BR)
    assert record["source"] == "template" and record["fallbackReason"] == "unreadable answer (stop reason max_tokens)"
    status = client.get("/api/events/status").json()
    assert status["refusalsToday"] == 1 and status["callsToday"] == 2


# ---- nothing leaves, every template plays --------------------------------------------------------------------------------

def test_every_template_validates_and_plays_at_every_site_and_nothing_is_sent(client):
    service = svc(client)
    events = director(client, seed=3)
    played = set()
    for site in (MY, BR, TM):
        for hour in (10, 3):  # working hours and the night shift
            moment = local_moment(site, hour)
            for template_id, build in TEMPLATES:
                context = Context(events, site, moment)
                raw = build(context)
                if not raw:
                    continue
                event, dropped, problem = events.validate(site, raw, context)
                assert event is not None, (site, hour, template_id, problem, dropped)
                assert dropped == [], (site, hour, template_id, dropped)
                record = events.create(site, context, event, dict(source="template", templateId=template_id), moment)
                events.play(record["id"], realtime=False)
                record = events.get(record["id"])
                assert all(e["status"] == "played" for e in record["effects"]), (template_id, record["effects"])
                played.add(template_id)
                events.resolve_due(moment + timedelta(hours=3))
    assert played == {template_id for template_id, _ in TEMPLATES}  # each template applies somewhere
    claude = director(client, FakeClaude(lambda request: bearing_event()))
    record = claude.fire(datetime.now(timezone.utc), site=MY)
    claude.resolve_due(datetime.now(timezone.utc) + timedelta(hours=1))
    service.maintenance_planner.tick(datetime.now(timezone.utc))
    assert claude.get(record["id"])["state"] == "resolved"
    for kind in ("notice", "dispatch", "document_email", "owner_alert", "notification"):
        assert service.store.all(kind) == [], kind
    events_listed = client.get("/api/events?limit=200").json()
    assert len(events_listed) >= 12 and all(e["origin"] == "run" for e in events_listed)
    conversations = [c for c in service.store.all("conversation", "") if c.get("eventId")]
    assert conversations and all(c["transport"] == "local" for c in conversations)
    text = json.dumps(events_listed).lower()
    for word in ("synthetic test", "simulated", "scenario", " demo "):
        assert word not in text.replace('"synthetic": true', "")


# ---- variety, the loop, site choice, endpoints ---------------------------------------------------------------------------

def test_recent_titles_go_into_the_prompt_and_templates_vary(client, monkeypatch):
    monkeypatch.setenv("STEWARD_EVENTS_CLAUDE", "false")
    events = director(client, seed=11)
    made = [events.fire(local_moment(BR, 11), site=BR) for _ in range(4)]
    assert len({r["templateId"] for r in made}) == 4  # a template is not used again at a site while it is recent
    assert len({r["title"] for r in made}) == 4
    monkeypatch.delenv("STEWARD_EVENTS_CLAUDE")
    fake = FakeClaude(lambda request: bearing_event())
    events.client = fake
    events.fire(datetime.now(timezone.utc), site=MY)
    text = fake.requests[0]["messages"][0]["content"]
    listed = text.split("Recent events at the sites (do not repeat or rephrase these):\n", 1)[1]
    for record in made:
        assert f"- {record['title']} (Bristol)" in listed
    assert "do not repeat or rephrase any recent event" in fake.requests[0]["system"]
    many = [events.fire(datetime.now(timezone.utc), site=MY) for _ in range(9)]
    assert all(r["source"] == "claude" for r in many)
    last = fake.requests[-1]["messages"][0]["content"].split("(do not repeat or rephrase these):\n", 1)[1]
    assert last.count("\n- ") + 1 == 10  # the last 10 titles


def test_the_loop_toggle_interval_and_resolution(client, monkeypatch):
    events = director(client)
    moment = datetime.now(timezone.utc)
    assert events.tick(moment) is None and events.enabled() is False  # without workers events are off by default
    assert client.get("/api/events/status").json()["enabled"] is False
    monkeypatch.setenv("STEWARD_EVENTS", "true")
    monkeypatch.setenv("STEWARD_EVENTS_CLAUDE", "false")
    first = events.tick(moment)
    assert first is not None and first["source"] == "template"
    gap = (events.next_at - moment).total_seconds() / 60
    assert 3 <= gap <= 7
    assert events.tick(moment + timedelta(minutes=2)) is None or gap < 2
    second = events.tick(events.next_at)
    assert second is not None and second["id"] != first["id"]
    monkeypatch.setenv("STEWARD_EVENTS_MIN_MINUTES", "0.5")
    monkeypatch.setenv("STEWARD_EVENTS_MAX_MINUTES", "0.5")
    at = events.next_at
    events.tick(at)
    assert events.next_at - at == timedelta(seconds=30)
    status = client.get("/api/events/status").json()
    assert status["enabled"] is True and status["nextEventAt"] and status["intervalMinutes"] == {"min": 0.5, "max": 0.5} and status["eventsToday"] >= 3
    # A later pass puts the earlier events right.
    later = at + timedelta(hours=3)
    events.tick(later)
    assert all(events.get(r["id"])["state"] in ("resolved", "done") for r in (first, second))


def test_the_quietest_site_is_picked_most(client):
    service = svc(client)
    events = director(client, seed=5)
    for site in (MY, BR):
        for n in range(20):
            service.issues.raise_issue(site, "busy_work", "low", f"Busy site issue number {n} for the weighting.", issue_id=f"iss-busy-{site}-{n}")
    moment = datetime.now(timezone.utc)
    assert events.busyness(TM, moment) < events.busyness(MY, moment)
    picks = [events.pick_site(moment) for _ in range(300)]
    assert picks.count(TM) > 0.55 * len(picks) and picks.count(MY) > 0 and picks.count(BR) > 0


def test_an_event_ramp_is_not_overwritten_by_the_sensor_feed(client):
    service = svc(client)
    answer = dict(title="TS-801 supply temperature creeping up", kind="sensor_drift", assetTag="TS-801", severity="low",
                  narrative="TS-801 is creeping up while the room is steady; the probe on the header reads lower.",
                  effects=[dict(type="reading", assetTag="TS-801", attribute="temperature_c", values=[21.0, 26.5, 33.0, 41.5], minutesApart=2)],
                  resolvesAfterMinutes=20)
    events = director(client, FakeClaude(lambda request: answer))
    events.fire(datetime.now(timezone.utc), site=MY)
    service.simulator.tick_sensors()
    latest = service.reality.latest_facts(MY, "TS-801", "temperature_c")[0]
    assert latest["source"]["ref"] == SENSOR_REF and latest["value"] == 41.5
    other = service.reality.latest_facts(MY, "TS-802", "temperature_c")[0]
    assert other["source"]["ref"] == "sim:TS-802"  # the feed still runs for the other sensors


def test_event_endpoints(client):
    events = director(client, FakeClaude(lambda request: bearing_event()))
    record = events.fire(datetime.now(timezone.utc), site=MY)
    director(client).fire(datetime.now(timezone.utc), site=TM)
    everything = client.get("/api/events").json()
    assert [e["siteId"] for e in everything] == [TM, MY]
    mine = client.get(f"/api/events?siteId={MY}&limit=5").json()
    assert [e["id"] for e in mine] == [record["id"]] and "_plan" not in mine[0] and mine[0]["effects"][0]["status"] == "played"
    assert client.get("/api/events?siteId=nowhere").status_code == 404
    assert client.get("/api/events?limit=0").status_code == 422
    status = client.get("/api/events/status").json()
    for key in ("enabled", "nextEventAt", "callsToday", "tokens", "estimatedUsd", "capReached", "capReason", "fallbacksToday", "budgetUsdPerDay",
                "maxCallsPerDay", "active", "lastEvent", "claude"):
        assert key in status, key
    assert status["lastEvent"]["siteId"] == TM and status["eventsToday"] == 2 and status["callsToday"] == 1
    assert {a["id"] for a in status["active"]} >= {record["id"]}
    assert svc(client).store.get(KIND, record["id"])["siteId"] == MY


def test_realtime_playback_runs_on_its_own_thread_and_restarts_skip_what_did_not_play(client):
    service = svc(client)
    events = director(client)
    moment = datetime.now(timezone.utc)

    def made(at_seconds):
        context = Context(events, MY, moment)
        event, dropped, problem = events.validate(MY, bearing_event(), context)
        assert event is not None, problem
        record = events.create(MY, context, event, dict(source="claude", model="claude-opus-5-5"), moment)
        record["_plan"] = [dict(action, at=index * at_seconds) for index, action in enumerate(record["_plan"])]  # the same order, compressed
        events._save(record)
        return record

    quick = made(0.02)
    events.play(quick["id"], realtime=True)
    events.threads[quick["id"]].join(timeout=20)
    quick = events.get(quick["id"])
    assert quick["state"] == "active" and all(e["status"] == "played" for e in quick["effects"]) and quick["finishedAt"]
    stamps = [f["observedAt"] for f in sorted(facts_of(service, MY, "P-101", "vibration_mms"), key=lambda f: f["version"])]
    assert stamps == sorted(stamps)  # written as they happened, in order

    slow = made(30.0)
    events.play(slow["id"], realtime=True)
    resolved = events.resolve_due(moment + timedelta(hours=2))
    assert [r["id"] for r in resolved] == [quick["id"]]  # the slow one is still on its thread: not resolved under it
    assert events.get(slow["id"])["state"] == "playing"
    events._stop.set()
    events.threads[slow["id"]].join(timeout=5)
    resolved = events.resolve_due(moment + timedelta(hours=2))
    slow = events.get(slow["id"])
    assert slow["id"] in [r["id"] for r in resolved] and slow["state"] == "resolved"
    assert any(e["status"] == "skipped" and e.get("reason") == "the playback stopped before every effect played" for e in slow["effects"])

    left = made(30.0)  # an event a crashed process left playing
    assert events.recover() == 1
    left = events.get(left["id"])
    assert left["state"] == "active" and all(e["status"] == "skipped" and e["reason"] == "interrupted by a backend restart" for e in left["effects"])
