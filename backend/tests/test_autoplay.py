"""Scenario autoplay: scenarios start on their own in rotation with a gap, never while another run or fix workflow
plays, never right after someone started one by hand, never while a live switch could make an auto run reach a person
or spend (agent-to-agent messages over Inkbox and the owner-alert channel are not live switches), and at most a capped
number a day. Runs a dead process left `running` are marked interrupted."""
import pytest
from fastapi.testclient import TestClient

from src.autoplay import live_switches
from src.main import create_app
from src.store import now

LIVE = ("STEWARD_ALLOW_EXTERNAL_MESSAGES", "STEWARD_ALLOW_NOTICE_SMS", "STEWARD_SUPERMEMORY_LIVE")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    for name in LIVE:
        monkeypatch.setenv(name, "false")
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY", "STEWARD_API_TOKEN", "STEWARD_SCENARIO_AUTOPLAY_LIVE",
                "STEWARD_SCENARIO_AUTOPLAY_PLAYLIST", "STEWARD_SCENARIO_AUTOPLAY_MAX_PER_DAY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_DELAY", "0")
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_GAP", "0")
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_COOLDOWN", "0")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def autoplay(client):
    player = client.app.state.service.autoplay
    player.set_enabled(True)  # workers are off in tests, so it is off by default
    return player


def test_autoplay_plays_the_playlist_in_rotation(client):
    player = autoplay(client)
    first = player.tick()
    assert first["scenarioId"] == player.playlist()[0] == "my-overpressure"
    assert first["origin"] == "autoplay" and first["startedBy"] == "autoplay" and first["synthetic"] is True
    second = player.tick()  # the first finished inline; gap 0
    assert second["scenarioId"] == "br-sump"
    status = client.get("/api/scenario-autoplay").json()
    assert status["playedToday"] == 2 and status["next"] == "tm-humidity" and status["enabled"] is True
    assert set(status["playlist"]) == {s["id"] for s in client.get("/api/scenarios").json()}


def test_autoplay_waits_for_the_gap_and_for_runs_started_by_hand(client, monkeypatch):
    player = autoplay(client)
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_GAP", "600")
    assert player.tick()["scenarioId"] == "my-overpressure"
    assert player.tick() is None and player.state == "waiting" and "Next scenario in" in player.reason
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_GAP", "0")
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_COOLDOWN", "600")
    assert client.post("/api/scenarios/my-extinguisher/start", json={"speed": 0}).status_code == 202
    assert player.tick() is None and player.state == "waiting" and "started by hand" in player.reason
    manual = client.get("/api/scenarios").json()
    assert next(s for s in manual if s["id"] == "my-extinguisher")["lastRun"]["state"] == "completed"


def test_autoplay_never_runs_beside_another_active_run(client):
    player = autoplay(client)
    store = client.app.state.service.store
    store.put("scenario_run", dict(id="srun-busy", scenarioId="br-sump", siteId="bristol-pumps", siteIds=["bristol-pumps"], title="Busy run",
                                   state="running", speed=30, startedAt=now(), startedBy="operator", origin="manual", stepIndex=0, stepCount=3,
                                   log=[], synthetic=True), "")
    assert player.tick() is None and player.state == "waiting" and "Busy run is running (started by hand)" in player.reason


def test_autoplay_pauses_while_live_switches_are_on(client, monkeypatch):
    player = autoplay(client)
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "inkbox")  # A2A over Inkbox only connects Steward's own identities
    monkeypatch.setenv("STEWARD_ALLOW_OWNER_ALERTS", "true")  # the owner channel is capped on its own
    monkeypatch.setenv("STEWARD_ALLOW_AGENT_EMAIL", "true")  # contract 8: agent mail only reaches Steward's own mailboxes
    assert live_switches() == [] and player.tick()["origin"] == "autoplay"  # none of them pauses autoplay
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    assert player.tick() is None and player.state == "paused"
    assert "STEWARD_ALLOW_EXTERNAL_MESSAGES" in player.reason and "STEWARD_A2A_TRANSPORT" not in player.reason and "OWNER_ALERTS" not in player.reason
    assert client.get("/api/scenario-autoplay").json()["liveSwitches"] == ["STEWARD_ALLOW_EXTERNAL_MESSAGES"]
    for name in ("STEWARD_ALLOW_NOTICE_SMS", "STEWARD_ALLOW_AGENT_EMAIL", "STEWARD_SUPERMEMORY_LIVE"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "eve")
    assert live_switches() == ["STEWARD_ALLOW_EXTERNAL_MESSAGES", "STEWARD_ALLOW_NOTICE_SMS",
                               "STEWARD_SUPERMEMORY_LIVE", "STEWARD_MODEL_PROVIDER=eve"]  # still live switches
    for name in ("STEWARD_ALLOW_NOTICE_SMS", "STEWARD_ALLOW_AGENT_EMAIL", "STEWARD_SUPERMEMORY_LIVE"):
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_LIVE", "true")  # a deliberate override
    assert player.tick()["origin"] == "autoplay"


def test_autoplay_daily_cap_and_toggle(client, monkeypatch):
    player = autoplay(client)
    monkeypatch.setenv("STEWARD_SCENARIO_AUTOPLAY_MAX_PER_DAY", "1")
    assert player.tick() is not None
    assert player.tick() is None and player.state == "paused" and "daily maximum" in player.reason
    off = client.post("/api/scenario-autoplay", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert player.tick() is None and player.state == "off"
    assert client.post("/api/scenario-autoplay", json={"enabled": "maybe"}).status_code == 422


def test_runs_left_running_by_a_dead_process_are_marked_interrupted(client):
    service = client.app.state.service
    service.store.put("scenario_run", dict(id="srun-zombie", scenarioId="br-sump", siteId="bristol-pumps", siteIds=["bristol-pumps"], title="Zombie",
                                           state="running", speed=30, startedAt=now(), startedBy="operator", stepIndex=1, stepCount=3, log=[]), "")
    service.store.put("fix_workflow", dict(id="fix-zombie", siteId="bristol-pumps", issueId="iss-x", assetTag="SU-201", state="running", steps=[]),
                      "bristol-pumps")
    assert service.scenarios.recover() == 1 and service.fixes.recover() == 1
    run = service.store.get("scenario_run", "srun-zombie", "")
    assert run["state"] == "canceled" and run["outcome"] == "interrupted by a backend restart"
    fix = service.store.get("fix_workflow", "fix-zombie", "bristol-pumps")
    assert fix["state"] == "failed" and "Interrupted by a backend restart" in fix["error"]
