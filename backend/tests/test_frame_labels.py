"""Labelled eye frames (owner, Oct 18: "the image provided to MCP can also be labelled so it's known what the issue is"):
GET /api/eye/frames/{id}/labelled.jpg burns the judgements made on a frame (ring, verdict, reason) and the visible asset tags
into a copy of the picture; the original frame file is never changed."""
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.main import create_app
from src.store import now

BR = "bristol-pumps"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    monkeypatch.setenv("STEWARD_A2A_TRANSPORT", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def frame(service, frame_id="eyf-test0001", pins=None):
    buffer = io.BytesIO()
    Image.new("RGB", (640, 400), (90, 90, 90)).save(buffer, format="JPEG")
    data = buffer.getvalue()
    (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(data)
    service.store.put("eye_frame", dict(id=frame_id, seq=1, siteId=BR, action="go_to", actor="bristol-engineer", actorName="Site Engineer · Bristol",
                                        visiblePins=pins or [dict(assetTag="V-504", x=0.5, y=0.5, distance=2.0, occluded=False),
                                                             dict(assetTag="P-104", x=0.2, y=0.6, distance=3.0, occluded=False)],
                                        url=f"/api/eye/frames/{frame_id}.jpg", size=len(data), sha256=hashlib.sha256(data).hexdigest(), at=now()), BR)
    return data


def test_a_judged_frame_comes_back_labelled_and_the_original_is_untouched(client):
    service = client.app.state.service
    original = frame(service)
    service.store.put("patrol_label", dict(id="lbl-t1", siteId=BR, assetTag="V-504", assetName="Sump suction valve", verdict="bad", color="blue", title="Looks bad",
                                           reasons=["Valve repair blocked (Workplace Regulations 1992 reg. 5)"], mark=dict(x=0.5, y=0.5, note="valve"),
                                           frameId="eyf-test0001", agentName="Site Engineer · Bristol", at=now()), BR)
    response = client.get("/api/eye/frames/eyf-test0001/labelled.jpg")
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg" and response.headers["x-steward-labels"] == "1"
    labelled = Image.open(io.BytesIO(response.content)).convert("RGB")
    assert labelled.size == (640, 400)
    r, g, b = labelled.getpixel((320 - 18, 200))  # on the ring around the mark: the "looks bad" blue
    assert b > 180 and r < 120
    top = labelled.getpixel((300, 10))  # the caption bar darkens the top of the picture
    assert sum(top) < sum((90, 90, 90))
    assert (service.eye.frames_dir / "eyf-test0001.jpg").read_bytes() == original


def test_a_tour_stop_labels_its_frame_and_unjudged_frames_still_carry_their_tags(client):
    service = client.app.state.service
    frame(service, "eyf-test0002")
    service.store.put("site_tour", dict(id="tour-t1", siteId=BR, guideName="Site Inspector", startedAt=now(), stops=[
        dict(n=1, assetTag="P-104", verdict="good", title="Looks good", reasons=["2.6 bar, inside 1.5 to 3.5 bar"], frameId="eyf-test0002", at=now())]), BR)
    response = client.get("/api/eye/frames/eyf-test0002/labelled.jpg")
    assert response.status_code == 200 and response.headers["x-steward-labels"] == "1"
    frame(service, "eyf-test0003")
    plain = client.get("/api/eye/frames/eyf-test0003/labelled.jpg")
    assert plain.status_code == 200 and plain.headers["x-steward-labels"] == "0"
    assert client.get("/api/eye/frames/eyf-missing/labelled.jpg").status_code == 404
