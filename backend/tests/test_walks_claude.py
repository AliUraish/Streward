"""Continuous walks with Claude at every stop (walks.py): the request Claude gets (frame and records), the verdict and
observation on the label, the records overriding a "good" answer, the eye's mark at Claude's point and the picked world
point on the label, the per-asset reuse of answers, the daily call cap and budget, the API-error backoff, the continuous
loop that walks every site on its own, the walk reports to the Site Manager, the autoplayer playing scenarios only, and
GET /api/walks/status. The Anthropic client is a fake injected into the judge (constructing a real one fails the test) and
the eye is stubbed: nothing leaves the process."""
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agents import display_name
from src.main import create_app
from src.store import now
from src.verify import iso
from src.walks import FALLBACK_BETA, SCHEMA

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"
READINGS = {BR: [dict(key="pressure_bar:PG-602", label="Steam header pressure (PG-602)", assetTag="PG-602", unit="bar", value=1.09, previous=1.07,
                      delta=0.02, trend="up", state="normal", spec=dict(min=0.5, max=2.5))]}


def jpeg_bytes() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (90, 90, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = jpeg_bytes()


@pytest.fixture(autouse=True)
def no_real_anthropic(monkeypatch):
    import anthropic

    def refuse(*args, **kwargs):
        raise AssertionError("a real Anthropic client was created")
    monkeypatch.setattr(anthropic, "Anthropic", refuse)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY", "STEWARD_API_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        service = client.app.state.service
        monkeypatch.setattr(service.metrics, "live_readings", lambda site_id, moment=None: list(READINGS.get(site_id, [])))
        yield client


def svc(client):
    return client.app.state.service


class StubEye:
    """A renderer stand-in: go_to stores a JPEG frame with the asset's tag point in view; mark returns the picked world point."""

    def __init__(self, service):
        self.service = service
        self.calls = []
        self.world = dict(x=1.25, y=0.5, z=-2.0)
        self.hit = True
        self.pin_visible = True

    def act_sync(self, site_id, action, params, actor, timeout=None):
        self.calls.append(dict(site=site_id, action=action, params=dict(params), actor=actor))
        frame_id = f"eyf-{uuid4().hex[:16]}"
        (self.service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
        pins = [dict(assetTag=params.get("assetTag"), x=0.5, y=0.45, distance=2.0, occluded=False)] if action == "go_to" and self.pin_visible else []
        frame = dict(id=frame_id, seq=len(self.calls), siteId=site_id, commandId=f"eyc-test-{len(self.calls)}", action=action, params=params, actor=actor,
                     actorName=display_name(actor), camera=None, visiblePins=pins, index=0, rendererId="test", size=len(JPEG),
                     sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now())
        self.service.store.put("eye_frame", frame, site_id)
        out = dict(frameId=frame_id, frameUrl=frame["url"], actor=actor, action=action)
        if action == "mark":
            out.update(world=dict(self.world) if self.world else None, hit=self.hit)
        return out

    def marks(self):
        return [c for c in self.calls if c["action"] == "mark"]


@pytest.fixture
def eye(client, monkeypatch):
    service = svc(client)
    stub = StubEye(service)
    monkeypatch.setattr(service.eye, "act_sync", stub.act_sync)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])
    return stub


def records_of(request: dict) -> dict:
    text = request["messages"][0]["content"][2]["text"]
    return json.loads(text.split("\n", 1)[1].rsplit("\nAnswer with the JSON object only.", 1)[0])


def response(payload=None, stop="end_turn", text=None, model="claude-opus-5-5", input_tokens=1200, output_tokens=300):
    body = text if text is not None else json.dumps(payload)
    return SimpleNamespace(model=model, stop_reason=stop, stop_details=None,
                           content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
                           usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0))


class FakeClaude:
    """Stands in for anthropic.Anthropic(): `.beta.messages.create(**kwargs)` records the request and answers from `script`."""

    def __init__(self, script):
        self.script = script  # callable(tag, records, request) -> answer dict | response object | exception
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        records = records_of(kwargs)
        outcome = self.script(records["tag"], records, kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome if isinstance(outcome, SimpleNamespace) else response(outcome)

    def tags(self):
        return [records_of(r)["tag"] for r in self.requests]


def answer(verdict="good", title=None, observation="The asset is in clear view, dry and intact.", reasons=None, mark=(0.52, 0.48, "Asset body"),
           confidence="high"):
    return dict(verdict=verdict, title=title or ("Looks good" if verdict == "good" else "Looks bad"), observation=observation,
                reasons=reasons if reasons is not None else ["No leaks or damage visible"],
                mark=dict(x=mark[0], y=mark[1], note=mark[2]) if mark else None, confidence=confidence)


def claude(client, script) -> FakeClaude:
    fake = FakeClaude(script)
    svc(client).walks.judge.client = fake
    return fake


def walk(client, site, route, actor="operator", **extra):
    response = client.post("/api/patrols", json=dict(siteId=site, route=route, **extra), headers={"X-Steward-Actor": actor})
    assert response.status_code == 202, response.text
    return response.json()


def labels(client, site):
    return {label["assetTag"]: label for label in client.get(f"/api/properties/{site}/labels").json()}


def overdue(service, obligation_id, days=6):
    record = service.store.get("obligation", obligation_id)
    record.update(dueAt=iso(datetime.now(timezone.utc) - timedelta(days=days, hours=2)), status="overdue", blockedBy=None, blockedReason=None)
    service.store.put("obligation", record, record["siteId"])
    return record


# ---- Claude at every stop ------------------------------------------------------------------------------------------


def test_claude_looks_at_every_stop_and_the_label_keeps_its_answer(client, eye):
    service = svc(client)
    fake = claude(client, lambda tag, records, request: answer(
        observation=f"{tag} is in clear view, dry and intact. No leaks or loose parts.",
        reasons=["Examination certificate current", "No leaks or corrosion visible on the shell"] if tag == "PV-301"
        else ["Pressure inside its 0.5 to 2.5 bar band", "Gauge face clean and readable"]))
    patrol = walk(client, BR, ["PV-301", "PG-602"])
    assert patrol["state"] == "completed" and fake.tags() == ["PV-301", "PG-602"]
    found = labels(client, BR)
    vessel, gauge = found["PV-301"], found["PG-602"]
    assert (vessel["verdict"], vessel["color"], vessel["title"], vessel["headline"]) == ("good", "green", "Looks good", "Looks good")
    assert vessel["assessedBy"] == "claude" and vessel["model"] == "claude-opus-5-5" and vessel["confidence"] == "high" and vessel["cached"] is False
    assert vessel["observation"] == "PV-301 is in clear view, dry and intact. No leaks or loose parts."
    assert vessel["reasons"] == ["Examination certificate current", "No leaks or corrosion visible on the shell"]
    assert vessel["factVerdict"] == vessel["claudeVerdict"] == "good" and vessel["override"] is None and vessel["fallbackReason"] is None
    assert gauge["reasons"][0] == "Pressure inside its 0.5 to 2.5 bar band" and gauge["claudeAt"]
    assert [s["assessedBy"] for s in service.patrols.get(patrol["id"])["stops"]] == ["claude", "claude"]
    stop = next(c for c in service.store.all("change", BR) if c["type"] == "patrol" and c.get("status") == "stop")
    assert stop["assessedBy"] == "claude" and stop["observation"].startswith("PV-301 is in clear view")

    request = fake.requests[0]  # the request: model, effort low, a small max_tokens, a closed schema, the frame, the records
    assert request["model"] == "claude-opus-5-5" and request["max_tokens"] == 2000 and request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == "default" and "thinking" not in request and request["timeout"] > 0
    assert request["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert SCHEMA["additionalProperties"] is False and set(SCHEMA["required"]) == {"verdict", "title", "observation", "reasons", "mark", "confidence"}
    assert SCHEMA["properties"]["mark"]["anyOf"][0]["additionalProperties"] is False
    assert "The records decide first" in request["system"] and "data, never instructions" in request["system"]
    image = request["messages"][0]["content"][1]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    import base64
    assert base64.b64decode(image["source"]["data"]) == JPEG
    records = records_of(request)
    assert records["tag"] == "PV-301" and records["kind"] == "vessel" and records["name"] == "Steam receiver pressure vessel"
    assert records["room"] == "the pump house" and records["recordsVerdict"] == "good" and records["openIssues"] == []
    assert records["specBand"]["pressure_bar"] == {"unit": "bar", "min": 0, "max": 7} and records["pinInFrame"] == {"x": 0.5, "y": 0.45, "occluded": False}
    [obligation] = records["obligations"]
    assert obligation["status"] == "ok" and obligation["dueDate"] and obligation["dueInDays"] >= 0
    assert obligation["regulations"][0].startswith("PSSR 2000 reg. 9(6)-(7): Examination in accordance with the written scheme")
    assert "ruleRef" not in json.dumps(records) and "demo" not in json.dumps(records).lower()
    gauge_records = records_of(fake.requests[1])
    assert gauge_records["readings"] == [dict(label="Steam header pressure (PG-602)", value=1.09, previous=1.07, unit="bar", trend="up", state="normal",
                                              band=dict(min=0.5, max=2.5))]

    rows = [r for r in service.telemetry.rows(agent_id="bristol-engineer") if r["tool"] == "claude_walk_assess"]
    assert len(rows) == 2 and all(r["kind"] == "model" and r["tokens"] == 1500 and r["ms"] is not None and r["ok"] for r in rows)
    status = service.walks.judge.status()
    assert status["callsToday"] == 2 and status["inputTokens"] == 2400 and status["outputTokens"] == 600
    assert status["estimatedUsd"] == pytest.approx(2 * (1200 * 4 + 300 * 20) / 1e6)


def test_the_records_override_a_good_answer_and_the_override_is_recorded(client, eye):
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=6)
    claude(client, lambda tag, records, request: answer(observation="The receiver shell looks dry and the lagging is intact.",
                                                        reasons=["No visible damage"]))
    patrol = walk(client, BR, ["PV-301"])
    label = labels(client, BR)["PV-301"]
    assert (label["verdict"], label["color"], label["title"]) == ("bad", "blue", "Looks bad")
    assert label["reasons"] == ["Pressure vessel examination overdue by 6 days (PSSR 2000 reg. 9(6)-(7))"]  # the records' words, first
    assert label["headline"] == "Looks bad: pressure vessel examination overdue by 6 days"
    assert label["claudeVerdict"] == "good" and label["factVerdict"] == "bad" and label["confidence"] == "high"
    assert label["override"]["by"] == "records" and label["override"]["claudeVerdict"] == "good" and "overdue by 6 days" in label["override"]["note"]
    assert label["observation"] == "The receiver shell looks dry and the lagging is intact."  # what was seen still stands
    assert label["compliance"] is True and label["obligationId"] == "ob-br-pv301-exam" and patrol["alertIds"]  # and the alert workflow starts


def test_a_bad_answer_keeps_the_records_first_and_drops_what_the_records_do_not_support(client, eye):
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=6)
    claude(client, lambda tag, records, request: answer(
        "bad", title="Looks bad: overdue exam and rust", confidence="medium",
        observation="Rust streaks run below the inlet flange. The simulated scan is soft here.",
        reasons=["Examination overdue by 6 days (PSSR 2000 reg. 9(6)-(7))", "Shell pressure 4.7 bar", "Rust streaks below the inlet flange",
                 "Rendering artefact on the left"],
        mark=(0.31, 0.62, "Rust below the flange")))
    walk(client, BR, ["PV-301"])
    label = labels(client, BR)["PV-301"]
    assert label["reasons"] == ["Pressure vessel examination overdue by 6 days (PSSR 2000 reg. 9(6)-(7))", "Rust streaks below the inlet flange"]
    assert label["observation"] == "Rust streaks run below the inlet flange."  # the sentence naming the source is dropped
    assert label["headline"] == "Looks bad: overdue exam and rust" and label["override"] is None and label["claudeVerdict"] == "bad"
    assert label["mark"]["note"] == "Rust below the flange"


def test_the_frame_turns_a_good_asset_bad_only_with_concrete_evidence(client, eye):
    service = svc(client)
    answers = {"PG-602": answer("bad", title="Looks bad: gland weeping", confidence="medium", reasons=["Gland weeping at the gauge isolation valve"],
                                observation="A wet patch runs down from the gauge isolation valve gland."),
               "V-505": answer("bad", title="Looks bad: maybe corrosion", confidence="low", reasons=["Possible corrosion"],
                               observation="The valve body looks dark on one side.")}
    claude(client, lambda tag, records, request: answers[tag])
    patrol = walk(client, BR, ["PG-602", "V-505"])
    found = labels(client, BR)
    assert found["PG-602"]["verdict"] == "bad" and found["PG-602"]["headline"] == "Looks bad: gland weeping"
    assert found["PG-602"]["reasons"] == ["Gland weeping at the gauge isolation valve"] and found["PG-602"]["compliance"] is False
    assert found["V-505"]["verdict"] == "good" and found["V-505"]["override"]["claudeVerdict"] == "bad"  # low confidence is not evidence
    assert patrol["alertIds"] == []  # a visual finding is not a compliance gap: nothing for the owner


def test_claudes_point_goes_to_the_eye_mark_and_the_label_takes_the_picked_world_point(client, eye):
    service = svc(client)
    claude(client, lambda tag, records, request: answer(mark=(0.31, 0.62, "Gland weeping") if tag == "PV-301" else (0.7, 0.2, "Gauge face")))
    eye.world = dict(x=1.2, y=0.4, z=-2.5)
    walk(client, BR, ["PV-301"])
    [mark] = eye.marks()
    assert mark["params"] == dict(x=0.31, y=0.62, note="Gland weeping") and mark["actor"] == "bristol-engineer" and mark["site"] == BR
    label = labels(client, BR)["PV-301"]
    assert label["mark"]["x"] == 0.31 and label["mark"]["y"] == 0.62 and label["mark"]["note"] == "Gland weeping" and label["mark"]["source"] == "claude"
    assert label["mark"]["world"] == dict(x=1.2, y=0.4, z=-2.5) and label["mark"]["hit"] is True and label["mark"]["frameId"].startswith("eyf-")
    assert label["world"] == dict(x=1.2, y=0.4, z=-2.5)
    eye.hit = False  # a pick that missed the scan: the label stays on the pin
    walk(client, BR, ["PG-602"])
    pin = service.reality.component_by_tag(BR, "PG-602")["pin"]
    gauge = labels(client, BR)["PG-602"]
    assert gauge["mark"]["hit"] is False and gauge["world"] == dict(x=pin["x"], y=pin["y"], z=pin["z"])


def test_answers_are_reused_while_the_asset_state_holds(client, eye, monkeypatch):
    service = svc(client)
    fake = claude(client, lambda tag, records, request: answer(observation="The receiver is dry and intact.", mark=(0.4, 0.55, "Receiver shell")))
    walk(client, BR, ["PV-301"])
    second = walk(client, BR, ["PV-301"])
    assert len(fake.requests) == 1  # same state, younger than the TTL: no second call
    label = labels(client, BR)["PV-301"]
    assert label["patrolId"] == second["id"] and label["cached"] is True and label["assessedBy"] == "claude"
    assert label["observation"] == "The receiver is dry and intact." and label["mark"]["x"] == 0.4 and label["mark"]["y"] == 0.55
    assert [m["params"] for m in eye.marks()] == [dict(x=0.4, y=0.55, note="Receiver shell")] * 2  # the walk still flies and marks
    assert [c["action"] for c in eye.calls].count("go_to") == 2
    assert service.walks.judge.status()["cacheHitsToday"] == 1 and service.walks.judge.status()["callsToday"] == 1
    overdue(service, "ob-br-pv301-exam", days=2)  # the obligation's status changed: ask again
    walk(client, BR, ["PV-301"])
    assert len(fake.requests) == 2 and labels(client, BR)["PV-301"]["cached"] is False
    monkeypatch.setenv("STEWARD_WALK_CLAUDE_TTL_MINUTES", "0")  # an answer older than the TTL is not reused
    walk(client, BR, ["PV-301"])
    assert len(fake.requests) == 3


def test_the_daily_call_cap_and_budget_fall_back_to_the_rules(client, eye, monkeypatch):
    service = svc(client)
    fake = claude(client, lambda tag, records, request: answer())
    monkeypatch.setenv("STEWARD_WALK_CLAUDE_MAX_CALLS_PER_DAY", "1")
    walk(client, BR, ["PV-301", "PG-602"])
    found = labels(client, BR)
    assert found["PV-301"]["assessedBy"] == "claude" and len(fake.requests) == 1
    assert found["PG-602"]["assessedBy"] == "rules" and "call cap" in found["PG-602"]["fallbackReason"] and found["PG-602"]["observation"] is None
    assert found["PG-602"]["reasons"][0].endswith(", inside 0.5 to 2.5 bar")  # the deterministic rules
    status = client.get("/api/walks/status").json()["claude"]
    assert status["capReached"] is True and status["maxCalls"] == 1 and "call cap" in status["capReason"] and status["rulesToday"] == 1
    monkeypatch.setenv("STEWARD_WALK_CLAUDE_MAX_CALLS_PER_DAY", "300")
    monkeypatch.setenv("STEWARD_WALK_CLAUDE_BUDGET_USD_PER_DAY", "0.01")  # one call cost 0.0108 at 4 / 20 USD per million tokens
    walk(client, BR, ["V-505"])
    assert labels(client, BR)["V-505"]["assessedBy"] == "rules" and "budget" in labels(client, BR)["V-505"]["fallbackReason"]
    assert len(fake.requests) == 1
    status = client.get("/api/walks/status").json()["claude"]
    assert status["capReached"] is True and status["budgetUsd"] == 0.01 and status["estimatedUsd"] == pytest.approx(0.0108)
    monkeypatch.setenv("STEWARD_WALK_MODEL", "claude-unlisted-1")  # no list price: only the call cap applies
    status = client.get("/api/walks/status").json()["claude"]
    assert status["budgetEnforced"] is False and "only the call cap applies" in status["budgetNote"] and status["capReached"] is False


def test_api_errors_fall_back_to_the_rules_and_back_off(client, eye):
    service = svc(client)

    class RateLimited(Exception):
        status_code = 429

    outcomes = [RateLimited("rate limited"), answer()]
    fake = claude(client, lambda tag, records, request: outcomes.pop(0))
    walk(client, BR, ["PV-301", "PG-602"])
    found = labels(client, BR)
    assert found["PV-301"]["assessedBy"] == "rules" and "Claude API error (RateLimited 429" in found["PV-301"]["fallbackReason"]
    assert found["PG-602"]["assessedBy"] == "rules" and found["PG-602"]["fallbackReason"].startswith("backing off after a Claude API error")
    assert len(fake.requests) == 1  # nothing was sent while backing off
    judge = service.walks.judge
    assert judge.status()["errorsToday"] == 1 and judge.status()["backoffSeconds"] > 50 and "RateLimited" in judge.status()["lastError"]
    failed = [r for r in service.telemetry.rows(agent_id="bristol-engineer") if r["tool"] == "claude_walk_assess"]
    assert len(failed) == 1 and failed[0]["ok"] is False and failed[0]["ms"] is not None
    judge.backoff_until = 0.0  # 60 s later
    walk(client, BR, ["PV-301"])
    assert labels(client, BR)["PV-301"]["assessedBy"] == "claude" and len(fake.requests) == 2


def test_refusals_unreadable_answers_and_missing_frames_use_the_rules_without_backoff(client, eye, monkeypatch):
    service = svc(client)
    outcomes = {"PV-301": response(stop="refusal", text=""), "PG-602": response(text="not json")}
    fake = claude(client, lambda tag, records, request: outcomes[tag])
    walk(client, BR, ["PV-301", "PG-602"])
    found = labels(client, BR)
    assert found["PV-301"]["assessedBy"] == "rules" and found["PV-301"]["fallbackReason"] == "Claude declined to answer"
    assert found["PG-602"]["assessedBy"] == "rules" and found["PG-602"]["fallbackReason"].startswith("unreadable answer")
    assert service.walks.judge.status()["backoffSeconds"] == 0 and service.walks.judge.status()["refusalsToday"] == 1
    assert found["PV-301"]["mark"]["source"] == "pin" and found["PV-301"]["mark"]["x"] == 0.5  # rules still mark the asset's tag point
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [])  # no renderer: no frame, so no call at all
    monkeypatch.setattr(service.eye.worker, "launcher", None)
    monkeypatch.setenv("STEWARD_EYE_AUTOSTART", "false")
    walk(client, TM, ["HS-301"])
    mill = labels(client, TM)["HS-301"]
    assert mill["assessedBy"] == "rules" and mill["fallbackReason"] == "no eye frame at this stop" and mill["mark"] is None and len(fake.requests) == 2


def test_without_the_switch_or_a_key_the_rules_label_and_still_mark(client, eye, monkeypatch):
    service = svc(client)
    walk(client, BR, ["PV-301"])  # no ANTHROPIC_API_KEY and no client
    label = labels(client, BR)["PV-301"]
    assert label["assessedBy"] == "rules" and label["fallbackReason"] == "ANTHROPIC_API_KEY is not set" and label["model"] is None
    assert label["mark"]["source"] == "pin" and eye.marks()[-1]["params"] == dict(x=0.5, y=0.45, note="PV-301: Looks good")
    fake = claude(client, lambda tag, records, request: answer())
    monkeypatch.setenv("STEWARD_WALK_CLAUDE", "false")
    walk(client, BR, ["PV-301"])
    assert labels(client, BR)["PV-301"]["fallbackReason"] == "STEWARD_WALK_CLAUDE=false" and fake.requests == []
    status = client.get("/api/walks/status").json()["claude"]
    assert status["enabled"] is False and status["switchedOn"] is False and status["configured"] is True


# ---- the continuous loop ------------------------------------------------------------------------------------------


def test_the_continuous_loop_walks_every_site_on_its_own(client, monkeypatch):
    service = svc(client)
    walks = service.walks
    assert walks.enabled() is False and walks.tick() == []  # without the backend's workers the loop is off by default
    monkeypatch.setenv("STEWARD_CONTINUOUS_WALKS", "true")
    first = walks.tick()  # without workers each walk plays inline
    assert sorted(p["siteId"] for p in first) == sorted([MY, BR, TM])
    assert all(p["origin"] == "autoplay" and p["startedBy"] == "autoplay" and p["state"] == "completed" for p in first)
    assert {p["siteId"]: p["agentId"] for p in first} == {MY: "myer-engineer", BR: "bristol-engineer", TM: "tomioka-engineer"}
    alerts = [service.patrols.alerts.get(a) for p in first for a in p["alertIds"]]
    assert alerts and all(a["origin"] == "autoplay" for a in alerts)  # autoplay alerts: never a real email or call by default
    assert all((a.get("email") or {}).get("mode") != "sent" and (a.get("call") or {}).get("mode") != "sent" for a in alerts)
    assert walks.tick() == [] and all(note.startswith("Next walk in") for note in walks.notes.values())  # the 20 s gap
    later = datetime.now(timezone.utc) + timedelta(seconds=21)
    assert len(walks.tick(later)) == 3
    service.store.put("patrol", dict(id="ptl-by-hand", siteId=BR, state="running", origin="manual", place="the pump house", route=["V-505"],
                                     stops=[], startedAt=now(), alertIds=[], line="Site Engineer · Bristol is walking the pump house"), BR)
    started = walks.tick(later + timedelta(minutes=5))
    assert sorted(p["siteId"] for p in started) == sorted([MY, TM]) and walks.notes[BR].startswith("Site Engineer · Bristol is walking")
    monkeypatch.setenv("STEWARD_WALK_GAP_SECONDS", "600")
    assert walks.tick(later + timedelta(minutes=6)) == []
    monkeypatch.setenv("STEWARD_CONTINUOUS_WALKS", "false")
    assert walks.tick(later + timedelta(hours=2)) == [] and walks.state == "off"


def test_continuous_walks_report_to_the_manager_only_when_something_changed(client, monkeypatch):
    from src.agents import OPERATOR
    service = svc(client)
    patrols = service.patrols
    first = patrols.start(BR, OPERATOR, route=["PV-301", "SP-102"], origin="autoplay")
    assert first["conversationId"]  # the first report
    second = patrols.start(BR, OPERATOR, route=["PV-301", "SP-102"], origin="autoplay")
    assert second["conversationId"] is None and "no message" in second["reportSkipped"]  # same findings, no new alert
    overdue(service, "ob-br-pv301-exam", days=1)
    third = patrols.start(BR, OPERATOR, route=["PV-301", "SP-102"], origin="autoplay")
    assert third["conversationId"]  # PV-301 turned bad (and raised an alert)
    monkeypatch.setenv("STEWARD_WALK_REPORT_MINUTES", "0")
    assert patrols.start(BR, OPERATOR, route=["PV-301", "SP-102"], origin="autoplay")["conversationId"]  # the periodic summary
    monkeypatch.setenv("STEWARD_WALK_REPORT_MINUTES", "60")
    assert patrols.start(BR, OPERATOR, route=["PV-301", "SP-102"])["conversationId"]  # a walk started by hand always reports


def test_autoplay_no_longer_schedules_walks(client, monkeypatch):
    service = svc(client)
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_PATROLS", "true")
    for name in ("STEWARD_SCENARIO_AUTOPLAY_DELAY", "STEWARD_SCENARIO_AUTOPLAY_GAP", "STEWARD_SCENARIO_AUTOPLAY_COOLDOWN"):
        monkeypatch.setenv(name, "0")
    player = service.autoplay
    player.set_enabled(True)
    assert not any(entry.startswith("patrol:") for entry in player.playlist())
    assert all(player.tick()["scenarioId"] in service.scenarios.scripts for _ in range(3)) and service.patrols.list() == []


# ---- status ----------------------------------------------------------------------------------------------------------


def test_walks_status_reports_each_site_and_the_days_claude_spend(client, eye):
    service = svc(client)
    claude(client, lambda tag, records, request: answer(observation="The receiver is dry and intact."))
    walk(client, BR, ["PV-301"])
    service.store.put("patrol", dict(id="ptl-now", siteId=MY, siteName="Myer Plant Room", agentId="myer-engineer", agentName="Site Engineer · Myer",
                                     state="running", origin="autoplay", route=["P-101", "TK-201", "PG-601"], stopIndex=1, stops=[],
                                     currentAssetTag="TK-201", line="Site Engineer · Myer is walking the plant room: stop 2 of 3, TK-201",
                                     startedAt=now(), alertIds=[]), MY)
    status = client.get("/api/walks/status").json()
    sites = {s["siteId"]: s for s in status["sites"]}
    assert set(sites) == {MY, BR, TM} and status["gapSeconds"] == 20 and status["enabled"] is False
    assert sites[MY]["walking"] is True and sites[MY]["patrolId"] == "ptl-now" and (sites[MY]["stop"], sites[MY]["of"]) == (2, 3)
    assert sites[MY]["assetTag"] == "TK-201"
    assert sites[BR]["walking"] is False and sites[BR]["lastObservation"] == "The receiver is dry and intact." and sites[BR]["lastAt"]
    assert sites[BR]["lastAssessedBy"] == "claude" and sites[BR]["stop"] == sites[BR]["of"] == 1 and sites[BR]["assetTag"] is None
    assert sites[TM]["patrolId"] is None and sites[TM]["lastObservation"] is None
    c = status["claude"]
    for key in ("enabled", "model", "callsToday", "cacheHitsToday", "inputTokens", "outputTokens", "estimatedUsd", "capReached", "maxCalls", "budgetUsd"):
        assert key in c
    assert c["enabled"] is True and c["model"] == "claude-opus-5-5" and c["callsToday"] == 1 and c["cacheHitsToday"] == 0
    assert (c["inputTokens"], c["outputTokens"], c["capReached"], c["maxCalls"], c["budgetUsd"]) == (1200, 300, False, 300, 10)
    assert c["estimatedUsd"] == pytest.approx(0.0108) and c["effort"] == "low" and c["ttlMinutes"] == 30
