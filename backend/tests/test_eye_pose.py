"""Agent-eye fixes found by the PINS stream: a mark's picked world point posted under `mark` (or `annotation`) reaches the
annotation and the act response; a per-asset `viewPose` set through the pin route makes go_to and orbit start from the
same pose every time; survey acts (`params.purpose == "survey"`) tag their frames so the dashboard can hide them."""
import base64
import io
import threading

import pytest
from fastapi.testclient import TestClient

from src.main import create_app

MY = "myer-plant"
POSE = {"position": [-3.9, -0.4, -4.2], "target": [-4.75, -0.95, -6.43], "fov": 70}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def jpeg() -> str:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (70, 70, 70)).save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode()


class Renderer(threading.Thread):
    def __init__(self, client, key="mark"):
        super().__init__(daemon=True)
        self.client, self.key = client, key
        self.stop = threading.Event()
        self.since = 0
        self.frame = jpeg()
        self.commands = []

    def run(self):
        while not self.stop.is_set():
            listing = self.client.get(f"/api/eye/{MY}/commands", params={"rendererId": "pose-test", "since": self.since, "timeout": 1}).json()
            for command in listing.get("commands", []):
                self.since = max(self.since, command["seq"])
                self.commands.append(command)
                for index in range(command["expectedFrames"]):
                    payload = {"commandId": command["id"], "jpegBase64": self.frame, "rendererId": "pose-test", "index": index,
                               "camera": {"position": POSE["position"], "target": POSE["target"], "fov": 70},
                               "visiblePins": [{"assetTag": "P-101", "x": 0.5, "y": 0.5, "distance": 2.0, "occluded": False}],
                               "startPose": "viewPose" if (command["params"] or {}).get("viewPose") else "approach"}
                    if command["action"] == "mark":
                        payload[self.key] = {"x": 0.5, "y": 0.5, "world": [-4.75, -0.95, -6.43], "hit": True, "note": "casing"}
                    self.client.post(f"/api/eye/{MY}/frames", json=payload)


def test_view_pose_is_stored_and_sent_with_go_to_and_orbit(client, monkeypatch):
    monkeypatch.setenv("STEWARD_EYE_ACT_TIMEOUT", "1")
    pin = {"x": -4.75, "y": -0.95, "z": -6.43, "source": "placed"}
    placed = client.put(f"/api/properties/{MY}/assets/P-101/pin", json={**pin, "viewPose": POSE})
    assert placed.status_code == 200, placed.text
    stored = placed.json()["viewPose"]
    assert stored["position"] == POSE["position"] and stored["target"] == POSE["target"] and stored["fov"] == 70 and stored["setBy"] == "operator"
    bad = client.put(f"/api/properties/{MY}/assets/P-101/pin", json={"viewPose": {"position": [0, 0, 0], "target": [0, 0, 0]}})
    assert bad.status_code == 400 and bad.json()["code"] == "INVALID_REQUEST"
    # A pose-only update keeps the placed pin.
    moved = client.put(f"/api/properties/{MY}/assets/P-101/pin", json={"viewPose": {**POSE, "position": {"x": -3.8, "y": -0.4, "z": -4.0}}}).json()
    assert moved["pin"] == {"x": -4.75, "y": -0.95, "z": -6.43} and moved["pinSource"] == "placed" and moved["viewPose"]["position"] == [-3.8, -0.4, -4.0]
    assert next(a for a in client.get(f"/api/properties/{MY}/scene").json()["assets"] if a["assetTag"] == "P-101")["viewPose"]["fov"] == 70
    client.post(f"/api/eye/{MY}/renderers", json={"rendererId": "pose-test"})
    renderer = Renderer(client)
    renderer.start()
    try:
        first = client.post(f"/api/eye/{MY}/act", json={"action": "go_to", "params": {"assetTag": "P-101"}}, headers={"X-Steward-Actor": "myer-engineer"}).json()
        again = client.post(f"/api/eye/{MY}/act", json={"action": "go_to", "params": {"assetTag": "P-101"}}, headers={"X-Steward-Actor": "myer-engineer"}).json()
        orbit = client.post(f"/api/eye/{MY}/act", json={"action": "orbit", "params": {"assetTag": "P-101", "frames": 4}},
                            headers={"X-Steward-Actor": "myer-engineer"}).json()
        explicit = client.post(f"/api/eye/{MY}/act", json={"action": "go_to", "params": {"assetTag": "P-101", "viewPose": POSE}},
                               headers={"X-Steward-Actor": "myer-engineer"}).json()
    finally:
        renderer.stop.set()
        renderer.join(timeout=5)
    assert first["params"]["viewPose"] == again["params"]["viewPose"] == orbit["params"]["viewPose"]  # the same start pose every time
    assert first["params"]["viewPose"]["position"] == [-3.8, -0.4, -4.0] and first["params"]["viewPoseSource"] == "asset"
    assert explicit["params"]["viewPoseSource"] == "request" and explicit["params"]["viewPose"]["position"] == POSE["position"]
    assert all(c["params"].get("viewPose") for c in renderer.commands)
    reset = client.put(f"/api/properties/{MY}/assets/P-101/pin", json={"source": "estimated"}).json()
    assert reset["pinSource"] == "estimated" and reset["viewPose"] is None
    no_pose = client.post(f"/api/eye/{MY}/act", json={"action": "go_to", "params": {"assetTag": "P-102"}}, headers={"X-Steward-Actor": "myer-engineer"})
    assert no_pose.status_code == 504  # no renderer now; the command itself carried no pose
    assert "viewPose" not in client.app.state.service.store.all("eye_command", MY)[-1]["params"]


@pytest.mark.parametrize("key", ["mark", "annotation"])
def test_mark_world_point_from_either_key_and_survey_frames_are_tagged(client, key):
    client.post(f"/api/eye/{MY}/renderers", json={"rendererId": "pose-test"})
    renderer = Renderer(client, key)
    renderer.start()
    try:
        mark = client.post(f"/api/eye/{MY}/act", json={"action": "mark", "params": {"x": 0.5, "y": 0.5, "note": "casing", "purpose": "survey"}},
                           headers={"X-Steward-Actor": "myer-engineer"}).json()
        plain = client.post(f"/api/eye/{MY}/act", json={"action": "look"}, headers={"X-Steward-Actor": "myer-engineer"}).json()
    finally:
        renderer.stop.set()
        renderer.join(timeout=5)
    assert mark["world"] == {"x": -4.75, "y": -0.95, "z": -6.43} and mark["hit"] is True and mark["survey"] is True
    assert mark["annotation"]["world"] == mark["world"] and mark["annotation"]["survey"] is True and mark["annotation"]["nearestAssetTag"] == "P-101"
    annotations = client.get(f"/api/eye/{MY}/annotations").json()
    assert annotations[0]["world"] == {"x": -4.75, "y": -0.95, "z": -6.43}
    feed = client.get(f"/api/eye/{MY}/feed").json()["frames"]
    assert [f["survey"] for f in feed] == [True, False] and feed[0]["purpose"] == "survey" and feed[0]["annotation"]["world"]["z"] == -6.43
    hidden = client.get(f"/api/eye/{MY}/feed?excludeSurvey=true").json()["frames"]
    assert [f["id"] for f in hidden] == [plain["frameId"]]
    assert client.post(f"/api/eye/{MY}/act", json={"action": "look", "params": {"purpose": ""}}).json()["code"] == "INVALID_REQUEST"
