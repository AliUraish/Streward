"""Headless eye worker robustness: a cold act waits for the renderer to start instead of failing at 20 s, gives up early
when the worker exits, and a renderer left behind by an earlier backend run (it still holds the Chrome profile lock, so
every new launch aborts) is stopped, but only when its PID comes from this site's own profile lock and its command line
names that profile."""
import base64
import io
import os
import socket
import subprocess
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.main import create_app

MY = "myer-plant"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


def jpeg() -> str:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (70, 70, 70)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


class FakeProcess:
    def __init__(self, pid, exits=False):
        self.pid, self.code = pid, (1 if exits else None)

    def poll(self):
        return self.code

    def terminate(self):
        self.code = -15


class LateRenderer(threading.Thread):
    """A headless renderer that registers only after `delay` seconds (Chrome launch, page compile, scan load)."""

    def __init__(self, client, delay):
        super().__init__(daemon=True)
        self.client, self.delay = client, delay
        self.stop = threading.Event()
        self.frame = jpeg()

    def run(self):
        if self.stop.wait(self.delay):
            return
        since = 0
        while not self.stop.is_set():
            listing = self.client.get(f"/api/eye/{MY}/commands", params={"rendererId": "headless-test", "since": since, "timeout": 1}).json()
            for command in listing.get("commands", []):
                since = max(since, command["seq"])
                for index in range(command["expectedFrames"]):
                    self.client.post(f"/api/eye/{MY}/frames", json={"commandId": command["id"], "jpegBase64": self.frame, "rendererId": "headless-test",
                                                                    "index": index, "camera": {"position": [0, 1, 3], "target": [0, 1, 0], "fov": 60},
                                                                    "visiblePins": []})


def autostart(client, monkeypatch, exits=False):
    monkeypatch.setenv("STEWARD_EYE_AUTOSTART", "true")
    launched = []

    def launcher(args, log_path):
        process = FakeProcess(41000 + len(launched), exits=exits)
        launched.append(process)
        return process

    svc(client).eye.worker.launcher = launcher
    return launched


def test_cold_act_waits_for_a_renderer_that_is_still_starting(client, monkeypatch):
    monkeypatch.setenv("STEWARD_EYE_ACT_TIMEOUT", "0.5")
    monkeypatch.setenv("STEWARD_EYE_COLD_START_TIMEOUT", "20")
    launched = autostart(client, monkeypatch)
    renderer = LateRenderer(client, delay=2.0)
    renderer.start()
    try:
        started = time.monotonic()
        looked = client.post(f"/api/eye/{MY}/act", json={"action": "go_to", "params": {"assetTag": "PG-601"}}, headers={"X-Steward-Actor": "myer-engineer"})
        assert looked.status_code == 200, looked.text
        assert looked.json()["frameUrl"].startswith("/api/eye/frames/") and len(launched) == 1
        assert 1.5 < time.monotonic() - started < 15  # longer than the warm 0.5 s window, shorter than the cold one
        warm = client.post(f"/api/eye/{MY}/act", json={"action": "look"}, headers={"X-Steward-Actor": "myer-engineer"})
        assert warm.status_code == 200 and len(launched) == 1  # registered now: no second launch
    finally:
        renderer.stop.set()
        renderer.join(timeout=5)


def test_cold_act_gives_up_early_when_the_worker_exits(client, monkeypatch):
    monkeypatch.setenv("STEWARD_EYE_ACT_TIMEOUT", "0.5")
    monkeypatch.setenv("STEWARD_EYE_COLD_START_TIMEOUT", "60")
    autostart(client, monkeypatch, exits=True)
    started = time.monotonic()
    failed = client.post(f"/api/eye/{MY}/act", json={"action": "look"}, headers={"X-Steward-Actor": "myer-engineer"})
    assert failed.status_code == 504 and failed.json()["code"] == "EYE_TIMEOUT"
    assert "exited before it registered" in failed.json()["detail"] and "chrome-myer-plant.log" in failed.json()["detail"]
    assert time.monotonic() - started < 10  # not the 60 s cold window


def test_timeouts_cold_and_warm(monkeypatch):
    from src.eye import EyeService
    for name in ("STEWARD_EYE_ACT_TIMEOUT", "STEWARD_EYE_COLD_START_TIMEOUT", "PHY_EYE_ACT_TIMEOUT", "PHY_EYE_COLD_START_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    command = {"expectedFrames": 1}
    assert EyeService.timeout_for(None, command) == 20
    assert EyeService.timeout_for(None, command, cold=True) == 90
    assert EyeService.timeout_for(None, {"expectedFrames": 16}, cold=True) == 120  # capped


def lock(profile, pid):
    profile.mkdir(parents=True, exist_ok=True)
    target = profile / "SingletonLock"
    if target.is_symlink() or target.exists():
        target.unlink()
    os.symlink(f"{socket.gethostname()}-{pid}", target)


def test_reaper_stops_a_leftover_renderer_that_holds_this_profile(client):
    worker = svc(client).eye.worker
    profile = worker.profile_dir(MY)
    leftover = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--headless=new", f"--user-data-dir={profile}"],
                                start_new_session=True)
    try:
        lock(profile, leftover.pid)
        reaped = worker.reap_orphan(MY)
        assert reaped == {"siteId": MY, "pid": leftover.pid, "reaped": True}
        assert leftover.wait(timeout=5) == -15
        assert not (profile / "SingletonLock").is_symlink()
    finally:
        if leftover.poll() is None:
            leftover.kill()


def test_reaper_never_touches_a_process_that_is_not_this_profiles_renderer(client):
    worker = svc(client).eye.worker
    profile = worker.profile_dir(MY)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--headless=new", "--user-data-dir=/somewhere/else"],
                             start_new_session=True)
    try:
        lock(profile, other.pid)
        assert worker.reap_orphan(MY) is None
        time.sleep(0.3)
        assert other.poll() is None  # still running
    finally:
        other.kill()
        other.wait(timeout=5)


def test_reaper_clears_a_lock_whose_process_is_gone(client):
    worker = svc(client).eye.worker
    profile = worker.profile_dir(MY)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait(timeout=5)
    lock(profile, gone.pid)
    assert worker.reap_orphan(MY) == {"siteId": MY, "pid": gone.pid, "reaped": False}
    assert not (profile / "SingletonLock").is_symlink()


def test_prewarm_starts_listed_sites_and_keeps_them_from_idling_out(client, monkeypatch):
    launched = autostart(client, monkeypatch)
    monkeypatch.setenv("STEWARD_EYE_PREWARM", "myer-plant,nowhere")
    service = svc(client)
    worker = service.eye.worker
    worker.check(service.eye.fresh)
    assert [p.pid for p in launched] == [41000] and set(worker.status()) == {MY}
    worker.procs[MY]["lastUsed"] -= 400
    worker.procs[MY]["seen"] = time.monotonic()  # registered, so the GPU grace rule does not apply
    service.eye.register(MY, "headless-warm")
    worker.check(service.eye.fresh)
    assert MY in worker.status() and launched[0].code is None  # kept warm despite five idle minutes
    monkeypatch.setenv("STEWARD_EYE_PREWARM", "")
    worker.check(service.eye.fresh)
    assert MY not in worker.status() and launched[0].code == -15
