"""Walkthroughs (contract 7 §1, §3): the site's Engineer walks the scan with the agent eye and labels every asset green
"Looks good" or blue "Looks bad" from its obligations, open issues and live readings; route selection, latest label per
asset, patrol Changes, the summary message to the Site Manager, authority, and the autoplayer (which plays scenarios only
now: the sites are walked continuously by walks.py, tested in test_walks_claude.py). The eye is stubbed (no renderer, no
Chrome); nothing leaves the process."""
import hashlib
import io
import math
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agents import display_name
from src.errors import RealityError
from src.main import create_app
from src.store import now
from src.verify import iso

MY, BR, TM = "myer-plant", "bristol-pumps", "tomioka-mill"


def jpeg_bytes() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (80, 80, 80)).save(buffer, format="JPEG")
    return buffer.getvalue()


JPEG = jpeg_bytes()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY", "STEWARD_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


@pytest.fixture
def eye(client, monkeypatch):
    """A stub eye: every go_to stores a real JPEG frame record and returns it, as a renderer would."""
    service = svc(client)
    calls = []

    def act_sync(site_id, action, params, actor, timeout=None):
        calls.append(dict(site=site_id, action=action, assetTag=params.get("assetTag"), actor=actor))
        frame_id = f"eyf-{uuid4().hex[:16]}"
        (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
        frame = dict(id=frame_id, seq=len(calls), siteId=site_id, commandId=f"eyc-test-{len(calls)}", action=action, params=params, actor=actor,
                     actorName=display_name(actor), camera=None, visiblePins=[], index=0, rendererId="test", size=len(JPEG),
                     sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now())
        service.store.put("eye_frame", frame, site_id)
        return dict(frameId=frame_id, frameUrl=frame["url"], actor=actor, action=action)

    monkeypatch.setattr(service.eye, "act_sync", act_sync)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])
    return calls


def overdue(service, obligation_id, days=6):
    record = service.store.get("obligation", obligation_id)
    record.update(dueAt=iso(datetime.now(timezone.utc) - timedelta(days=days, hours=2)), status="overdue", blockedBy=None, blockedReason=None)
    service.store.put("obligation", record, record["siteId"])
    return record


def walk(client, site, route=None, actor="operator", **extra):
    body = dict(siteId=site, **extra)
    if route is not None:
        body["route"] = route
    response = client.post("/api/patrols", json=body, headers={"X-Steward-Actor": actor})
    assert response.status_code == 202, response.text
    return response.json()


def labels_by_tag(client, site):
    response = client.get(f"/api/properties/{site}/labels")
    assert response.status_code == 200
    return {label["assetTag"]: label for label in response.json()}


def test_walkthrough_labels_green_and_blue_with_reasons(client, eye):
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=6)
    patrol = walk(client, BR)
    assert patrol["state"] == "completed" and patrol["origin"] == "manual" and patrol["synthetic"] is True
    assert patrol["agentId"] == "bristol-engineer" and patrol["agentName"] == "Site Engineer · Bristol"
    assert "PV-301" in patrol["route"] and len(patrol["route"]) <= 10
    assert patrol["stopIndex"] == len(patrol["route"]) == len(patrol["stops"])
    assert [c["assetTag"] for c in eye] == patrol["route"] and {c["action"] for c in eye} == {"go_to"} and {c["actor"] for c in eye} == {"bristol-engineer"}
    assert patrol["summary"].startswith(f"Walked the pump house: {len(patrol['route'])} checked, ")
    assert "PV-301: Pressure vessel examination overdue by 6 days (PSSR 2000 reg. 9(6)-(7))" in patrol["summary"]

    labels = labels_by_tag(client, BR)
    assert set(labels) == set(patrol["route"])
    bad = labels["PV-301"]
    assert (bad["verdict"], bad["color"], bad["title"]) == ("bad", "blue", "Looks bad")
    assert bad["reasons"][0] == "Pressure vessel examination overdue by 6 days (PSSR 2000 reg. 9(6)-(7))"
    assert bad["compliance"] is True and bad["obligationId"] == "ob-br-pv301-exam" and "eng-pssr-2000-reg-9-6" in bad["regulationIds"]
    assert bad["frameId"].startswith("eyf-") and bad["frameUrl"] == f"/api/eye/frames/{bad['frameId']}.jpg"
    assert set(bad["world"]) == {"x", "y", "z"} and bad["patrolId"] == patrol["id"] and bad["agentName"] == "Site Engineer · Bristol"
    assert bad["assetName"] == "Steam receiver pressure vessel"

    good = [l for l in labels.values() if l["verdict"] == "good"]
    assert good and all((l["color"], l["title"], l["compliance"]) == ("green", "Looks good", False) for l in good)
    current = [l for l in good if any(re.fullmatch(r".+ current, next due in \d+ days?", reason) for reason in l["reasons"])]
    assert current and all("No open issues" in l["reasons"] for l in current)  # e.g. "Safety valve lift test current, next due in 24 days"
    gauge = labels["PG-602"]
    assert gauge["verdict"] == "good" and gauge["reasons"][0].startswith("Pressure ") and gauge["reasons"][0].endswith(", inside 0.5 to 2.5 bar")
    assert all(label["frameId"] for label in labels.values())
    bad_count = sum(l["verdict"] == "bad" for l in labels.values())  # PV-301 plus any gap seeded at the site
    assert [s["verdict"] for s in patrol["stops"]].count("bad") == bad_count and patrol["counts"] == dict(good=len(patrol["route"]) - bad_count, bad=bad_count)


def test_readings_out_of_band_and_open_issues_look_bad(client, eye, monkeypatch):
    service = svc(client)
    readings = [r for r in service.metrics.live_readings(MY) if r["assetTag"] != "PG-601"]
    readings.append(dict(key="pressure_bar:PG-601", label="Primary circuit pressure (PG-601)", assetTag="PG-601", unit="bar", value=4.1, previous=3.9,
                         delta=0.2, trend="up", state="high", spec=dict(min=1.5, max=3.5)))
    monkeypatch.setattr(service.metrics, "live_readings", lambda site_id, moment=None: readings if site_id == MY else [])
    service.issues.raise_issue(MY, "eye_observation", "low", "Weeping gland on the P-101 pump seal.", asset_tag="P-101", source="agent", actor="myer-engineer")
    patrol = walk(client, MY, route=["PG-601", "P-101", "TS-801"])
    assert patrol["route"] == ["PG-601", "P-101", "TS-801"]  # an explicit route keeps its order
    labels = labels_by_tag(client, MY)
    assert labels["PG-601"]["verdict"] == "bad" and labels["PG-601"]["reasons"] == ["PG-601 4.1 bar, above the 3.5 bar limit"]
    assert labels["PG-601"]["compliance"] is False
    assert labels["P-101"]["verdict"] == "bad" and labels["P-101"]["reasons"] == ["Open issue: Weeping gland on the P-101 pump seal."]
    assert labels["P-101"]["issueId"] and labels["P-101"]["compliance"] is False
    assert labels["TS-801"]["verdict"] == "good" and labels["TS-801"]["reasons"][0].endswith("inside 5 to 40 °C")
    assert patrol["alertIds"] == []  # nothing for the owner: no compliance gap


def test_default_route_puts_placed_pins_first_keeps_gaps_and_walks_a_path(client):
    service = svc(client)
    placed = ["P-101", "P-102", "P-103", "TK-202", "HX-301", "HX-302", "CP-402", "V-501", "V-502", "V-503", "V-505", "L-901"]
    for component in service.store.all("component", MY):
        if component["tag"] in placed:
            component["pinSource"] = "placed"
        if component["tag"] == "TK-201":
            component["viewPose"] = dict(position=[1.0, 0.0, 1.0], target=[1.4, -0.9, -1.2], fov=60)
        service.store.put("component", component, MY)
    overdue(service, "ob-my-fe1001-monthly", days=3)  # FE-1001 is not placed, but its gap must be walked
    gaps = {o["assetTag"] for o in service.people.obligations(MY) if o["status"] in ("overdue", "blocked")}
    route = service.patrols.default_route(MY)
    assert len(route) == 10
    assert "FE-1001" in route and gaps <= set(route) and "TK-201" in route  # the gaps, and the placed asset with an obligation (viewPose)
    assert "DB-401" not in route  # an unplaced asset with an obligation comes after the placed pins
    assert set(route) - gaps - {"TK-201"} <= set(placed)
    components = {c["tag"]: c for c in service.store.all("component", MY)}

    def point(tag):
        pin = components[tag]["pin"]
        return pin["x"], pin["y"], pin["z"]

    for index in range(1, len(route) - 1):  # every next stop is the nearest one not yet walked
        remaining = route[index:]
        assert route[index] == min(remaining, key=lambda tag: math.dist(point(route[index - 1]), point(tag)))
    mill = service.patrols.default_route(TM)  # no placed pins at the mill: gaps, then obligations, then monitored assets
    mill_gaps = {o["assetTag"] for o in service.people.obligations(TM) if o["status"] in ("overdue", "blocked")}
    assert mill_gaps <= set(mill) and {"HS-301", "BW-251"} <= set(mill) and len(mill) == 10


def test_latest_label_per_asset(client, eye):
    service = svc(client)
    overdue(service, "ob-br-pv301-exam", days=2)
    first = walk(client, BR, route=["PV-301", "V-505"])
    assert labels_by_tag(client, BR)["PV-301"]["verdict"] == "bad"
    service.people.complete_obligation("ob-br-pv301-exam", "bristol-compliance", note="Examined by the competent person.")
    issue_id = svc(client).store.get("owner_alert", first["alertIds"][0])["issueId"]
    service.issues.resolve_issue(issue_id, "Examination certificate on file.", "bristol-engineer")
    second = walk(client, BR, route=["PV-301"])
    labels = client.get(f"/api/properties/{BR}/labels").json()
    assert [l["assetTag"] for l in labels].count("PV-301") == 1 and len(labels) == 2
    latest = next(l for l in labels if l["assetTag"] == "PV-301")
    assert latest["verdict"] == "good" and latest["patrolId"] == second["id"] and latest["reasons"][0].startswith("Pressure vessel examination current")
    assert len(service.store.all("patrol_label", BR)) == 3  # history kept; the endpoint shows the latest per asset


def test_patrol_changes_wait_and_summary_message(client, eye):
    service = svc(client)
    overdue(service, "ob-br-v505-lift", days=1)
    waited = client.post("/api/waits", json={"siteId": BR, "event": "any", "filter": {"type": "patrol", "status": "completed"}})
    assert waited.status_code == 201
    patrol = walk(client, BR, route=["V-505", "PG-602"])
    changes = [c for c in client.get(f"/api/properties/{BR}/changes?since=0&limit=1000").json()["changes"] if c["type"] == "patrol"]
    assert [c["status"] for c in changes] == ["started", "stop", "stop", "completed"] and {c["refId"] for c in changes} == {patrol["id"]}
    stop = changes[1]
    assert stop["patrolId"] == patrol["id"] and stop["assetTag"] == "V-505" and stop["verdict"] == "bad" and stop["stop"] == 1 and stop["stops"] == 2
    assert stop["labelId"] == labels_by_tag(client, BR)["V-505"]["id"] and "Looks bad" in stop["summary"]
    fired = client.get(f"/api/waits/{waited.json()['id']}?timeout=0").json()
    assert fired["status"] == "fired" and fired["event"]["change"]["refId"] == patrol["id"]
    replay = client.post("/api/waits", json={"siteId": BR, "event": "any", "filter": {"type": "patrol", "patrolId": patrol["id"], "status": "completed"}}).json()
    assert replay["status"] == "fired"  # a wait created after the walk ended still fires (replay by patrolId)
    message = service.conversations.get(patrol["conversationId"])
    assert message["kind"] == "message" and message["participants"] == ["bristol-engineer", "bristol-manager"] and message["siteIds"] == [BR]
    assert message["transcript"][0]["text"].startswith("Walked the pump house: 2 checked, 1 look good, 1 look bad: V-505: Safety valve lift test overdue by 1 day")
    # contract 8: the walk's alert stays in-house; the Site Inspector's inspection takes it to the owner
    assert "Compliance has V-505 in hand for the inspection." in message["transcript"][0]["text"] and message["status"] == "ended"
    assert message["transcript"][1]["speaker"] == "bristol-manager"


def test_eye_unavailable_still_labels_and_stops_retrying(client, monkeypatch):
    service = svc(client)
    patrol = walk(client, TM, route=["HS-301", "BW-251"])  # no renderer, worker off in tests
    labels = labels_by_tag(client, TM)
    assert all(l["frameId"] is None and l["frameUrl"] is None for l in labels.values())
    assert labels["HS-301"]["reasons"][-1] == "No eye frame: no renderer is open and the headless worker is off"
    assert patrol["state"] == "completed" and all(stop["frameId"] is None for stop in patrol["stops"])
    attempts = []

    def failing(site_id, action, params, actor, timeout=None):
        attempts.append(params["assetTag"])
        raise RealityError("No frame within 20 s for eye go_to.", "EYE_TIMEOUT", "Open /eye.", 504)

    monkeypatch.setattr(service.eye, "act_sync", failing)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "stuck"}])
    walk(client, TM, route=["HS-301", "HS-302", "HS-303", "RM-101"])
    assert attempts == ["HS-301", "HS-302"]  # two failures in a row: the rest of the route is labelled without the eye
    later = labels_by_tag(client, TM)
    assert later["RM-101"]["frameId"] is None and later["RM-101"]["reasons"][-1].startswith("No eye frame: eye unavailable (No frame within 20 s")


def test_patrol_routes_authority_validation_and_cancel(client, eye):
    service = svc(client)
    denied = client.post("/api/patrols", json={"siteId": BR}, headers={"X-Steward-Actor": "bristol-compliance"})
    assert denied.status_code == 403 and denied.json()["code"] == "AUTHORITY_DENIED"
    assert client.post("/api/patrols", json={"siteId": BR}, headers={"X-Steward-Actor": "myer-engineer"}).status_code == 403
    assert walk(client, BR, route=["V-505"], actor="bristol-manager")["state"] == "completed"
    assert walk(client, BR, route=["V-505"], actor="director", agentId="bristol-manager")["agentId"] == "bristol-manager"
    assert client.post("/api/patrols", json={"siteId": "nowhere"}).status_code == 404
    unknown = client.post("/api/patrols", json={"siteId": BR, "route": ["XX-999"]})
    assert unknown.status_code == 404 and unknown.json()["code"] == "UNKNOWN_ASSET"
    assert client.post("/api/patrols", json={"siteId": BR, "paceSeconds": 500}).status_code == 422
    assert client.post("/api/patrols", json={"siteId": BR, "agentId": "bristol-technician"}).status_code == 400
    listed = client.get(f"/api/patrols?siteId={BR}&limit=5").json()
    assert len(listed) == 2 and listed[0]["startedAt"] >= listed[1]["startedAt"]
    assert client.get(f"/api/patrols/{listed[0]['id']}").json()["id"] == listed[0]["id"]
    assert client.get("/api/patrols/ptl-missing").status_code == 404
    assert client.post(f"/api/patrols/{listed[0]['id']}/cancel").json()["state"] == "completed"  # finished walks stay as they are
    running = dict(id="ptl-running", siteId=BR, siteName="Bristol Dock Pump House", agentId="bristol-engineer", agentName="Site Engineer · Bristol",
                   state="running", origin="manual", startedBy="operator", route=["V-505", "PV-301"], stopIndex=1, stops=[], currentAssetTag="PV-301",
                   place="the pump house", line="", paceSeconds=8, counts={}, startedAt=now(), finishedAt=None, summary=None, alertIds=[],
                   conversationId=None, error=None, synthetic=True)
    service.store.put("patrol", running, BR)
    assert walk(client, BR)["id"] == "ptl-running"  # a walk already running at the site is returned, not a second one
    assert client.post("/api/patrols/ptl-running/cancel", headers={"X-Steward-Actor": "myer-manager"}).status_code == 403
    canceled = client.post("/api/patrols/ptl-running/cancel", headers={"X-Steward-Actor": "bristol-engineer"}).json()
    assert canceled["state"] == "canceled" and canceled["finishedAt"] and canceled["summary"] == "Canceled after 1 of 2 stops."
    statuses = [c["status"] for c in service.store.all("change", BR) if c["type"] == "patrol" and c["refId"] == "ptl-running"]
    assert statuses == ["canceled"]


def test_recover_marks_interrupted_walks_and_alerts_failed(client):
    service = svc(client)
    service.store.put("patrol", dict(id="ptl-zombie", siteId=BR, state="running", route=["V-505"], stops=[], startedAt=now(), place="the pump house"), BR)
    service.store.put("owner_alert", dict(id="oal-zombie", siteId=BR, state="queued", obligationId="ob-br-v505-lift", at=now(), steps=[]), BR)
    assert service.patrols.recover() == 2
    assert service.store.get("patrol", "ptl-zombie")["state"] == "failed" and service.store.get("owner_alert", "oal-zombie")["state"] == "failed"


# ---- autoplay (contract 7 §3, superseded: each site walks on its own, walks.py) -------------------------------------


@pytest.fixture
def player(client, monkeypatch):
    for name in ("STEWARD_ALLOW_EXTERNAL_MESSAGES", "STEWARD_ALLOW_NOTICE_SMS", "STEWARD_ALLOW_AGENT_EMAIL", "STEWARD_SUPERMEMORY_LIVE"):
        monkeypatch.setenv(name, "false")
    for key in ("STEWARD_SCENARIO_AUTOPLAY_LIVE", "STEWARD_SCENARIO_AUTOPLAY_PLAYLIST", "STEWARD_SCENARIO_AUTOPLAY_MAX_PER_DAY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_DELAY", "0")
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_GAP", "0")
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_COOLDOWN", "0")
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_PATROLS", "true")
    autoplay = svc(client).autoplay
    autoplay.set_enabled(True)
    return autoplay


def test_autoplay_plays_scenarios_only_and_never_walks_a_site(client, player, eye):
    service = svc(client)
    playlist = player.playlist()  # STEWARD_SCENARIO_AUTOPLAY_PATROLS=true no longer adds walks
    assert playlist and not any(entry.startswith("patrol:") for entry in playlist)
    assert playlist == list(dict.fromkeys(playlist)) and set(playlist) == set(service.scenarios.scripts)
    for expected in playlist[:3]:
        assert player.tick()["scenarioId"] == expected  # each run finished inline (no workers), so the rotation moves on
    assert service.patrols.list() == []  # the sites are walked by the continuous loop (walks.py), never by the playlist
    status = client.get("/api/scenario-autoplay").json()
    assert status["current"]["kind"] == "scenario" and status["playedToday"] == 3 and status["next"] == playlist[3]
    assert status["patrols"] is False and status["walks"]["status"] == "/api/walks/status" and not any(e.startswith("patrol:") for e in status["playlist"])


def test_autoplay_waits_for_walks_started_by_hand_and_for_alerts_but_not_for_continuous_walks(client, player):
    service = svc(client)
    walk = dict(id="ptl-busy", siteId=BR, state="running", origin="manual", place="the pump house", route=["V-505"], stops=[], startedAt=now(),
                alertIds=[])
    service.store.put("patrol", walk, BR)
    assert player.tick() is None and player.state == "waiting" and "a walkthrough of the pump house is running (started by hand)" in player.reason
    service.store.put("patrol", dict(walk, origin="autoplay"), BR)  # a continuous walk runs beside the scenario rotation
    assert player.tick()["origin"] == "autoplay" and player.state == "playing"
    service.store.put("patrol", dict(walk, state="completed", origin="autoplay", alertIds=["oal-busy"]), BR)
    service.store.put("owner_alert", dict(id="oal-busy", siteId=BR, state="running", assetTag="V-505", obligationId="ob-br-v505-lift", at=now()), BR)
    assert player.tick() is None and player.state == "waiting" and "the compliance alert for V-505 is running" in player.reason
    service.store.put("owner_alert", dict(id="oal-busy", siteId=BR, state="completed", assetTag="V-505", obligationId="ob-br-v505-lift", at=now()), BR)
    assert player.tick() is not None


def test_autoplay_continuous_pace_defaults(client, monkeypatch):
    for key in ("STEWARD_SCENARIO_AUTOPLAY_SPEED", "STEWARD_SCENARIO_AUTOPLAY_GAP", "STEWARD_SCENARIO_SPEED", "STEWARD_SCENARIO_AUTOPLAY_PATROLS"):
        monkeypatch.delenv(key, raising=False)
    player = svc(client).autoplay
    assert player.speed() == 10 and player.gap() == 30
    assert not any(entry.startswith("patrol:") for entry in player.playlist())
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_PATROLS", "true")  # the old switch no longer interleaves walks
    assert not any(entry.startswith("patrol:") for entry in player.playlist())
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_PLAYLIST", "br-sump,patrol:tomioka-mill,patrol:nowhere")
    assert player.playlist() == ["br-sump"]  # walking is the continuous loop's job (walks.py)


def test_threaded_walk_paces_stops_and_can_be_canceled(client, eye, monkeypatch):
    """With the backend's workers the walk runs on its own thread at `paceSeconds` per stop and its alerts follow, paced too."""
    import time
    service = svc(client)
    monkeypatch.setenv("STEWARD_ALERT_STEP_SECONDS", "0.05")
    monkeypatch.setattr(service, "start_workers", True)  # the eye is stubbed, so no renderer or Chrome is involved
    overdue(service, "ob-br-v505-lift", days=2)
    started = time.monotonic()
    patrol = walk(client, BR, route=["V-505", "PG-602"], paceSeconds=0.3)
    assert patrol["state"] == "running" and patrol["paceSeconds"] == 0.3
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and service.patrols.active(service.patrols.get(patrol["id"])):
        time.sleep(0.05)
    done = service.patrols.get(patrol["id"])
    assert done["state"] == "completed" and time.monotonic() - started >= 0.3  # one pause between the two stops
    [alert] = [service.patrols.alerts.get(a) for a in done["alertIds"]]
    assert alert["state"] == "completed" and [s["name"] for s in alert["steps"]][-1] == "owner_call"
    slow = walk(client, BR, route=["V-505", "PG-602", "SU-201"], paceSeconds=2)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and service.patrols.get(slow["id"])["stopIndex"] < 1:
        time.sleep(0.02)
    canceled = client.post(f"/api/patrols/{slow['id']}/cancel").json()
    assert canceled["state"] == "canceled"
    thread = service.patrols.threads.get(slow["id"])
    if thread:
        thread.join(timeout=5)
    final = service.patrols.get(slow["id"])
    assert final["state"] == "canceled" and final["stopIndex"] < 3 and final["alertIds"] == []
