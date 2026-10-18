"""Site tours: any agent, or an MCP client acting as the owner's agent, asks the Site Inspector to walk a site with the agent eye; the
inspector looks at each stop, judges it from the records (bad obligations, open issues, out-of-band readings), keeps the pictures
of what is wrong, emits site_tour Changes, and tells a Steward agent that asked over A2A. The eye is stubbed; nothing leaves the
process."""
import hashlib
import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agents import INSPECTOR, display_name
from src.errors import RealityError
from src.main import create_app
from src.store import now

BR = "bristol-pumps"


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
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def svc(client):
    return client.app.state.service


@pytest.fixture
def eye(client, monkeypatch):
    service = svc(client)
    looks = []

    def act_sync(site_id, action, params, actor, timeout=None):
        looks.append((site_id, action, params.get("assetTag"), actor))
        frame_id = f"eyf-{uuid4().hex[:16]}"
        (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
        service.store.put("eye_frame", dict(id=frame_id, seq=1, siteId=site_id, commandId="eyc-test", action=action, params=params, actor=actor,
                                            actorName=display_name(actor), camera=None, visiblePins=[], index=0, rendererId="test", size=len(JPEG),
                                            sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now()), site_id)
        return dict(frameId=frame_id, frameUrl=f"/api/eye/frames/{frame_id}.jpg")

    monkeypatch.setattr(service.eye, "act_sync", act_sync)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])
    return looks


def bad_tags(service, site):
    obligations = service.people.obligations(site)
    return {o["assetTag"] for o in obligations if o.get("assetTag") and o.get("status") in ("overdue", "blocked")}


def test_a_tour_walks_the_worst_first_and_keeps_the_pictures_of_what_is_wrong(client, eye):
    service = svc(client)
    response = client.post("/api/site-tours", json={"siteId": BR, "maxStops": 3, "requester": "mcp:Claude Desktop"})
    assert response.status_code == 202
    tour = response.json()
    assert tour["state"] == "completed" and tour["guide"] == INSPECTOR and tour["guideName"] == "Site Inspector"
    assert tour["requester"] == "mcp:Claude Desktop" and tour["requesterName"] == "Claude Desktop over MCP" and tour["actor"] == "operator"
    assert len(tour["stops"]) == 3 and [s["n"] for s in tour["stops"]] == [1, 2, 3]
    assert {look[3] for look in eye} == {INSPECTOR} and {look[1] for look in eye} == {"go_to"} and [look[2] for look in eye] == [s["assetTag"] for s in tour["stops"]]
    worst = bad_tags(service, BR)
    assert worst and tour["stops"][0]["assetTag"] in worst  # blocked and overdue obligations come first
    stop = tour["stops"][0]
    assert stop["verdict"] == "bad" and stop["color"] == "blue" and stop["title"] == "Looks bad" and stop["reasons"]
    assert stop["frameId"] and stop["frameUrl"] == f"/api/eye/frames/{stop['frameId']}.jpg"
    assert tour["findings"] == [s for s in tour["stops"] if s["verdict"] == "bad"]
    assert "look bad" in tour["summary"] and "picture" in tour["summary"] and tour["finishedAt"]
    for good in [s for s in tour["stops"] if s["verdict"] == "good"]:
        assert good["color"] == "green" and good["title"] == "Looks good"
    changes = [c for c in service.store.all("change", BR) if c["type"] == "site_tour" and c["refId"] == tour["id"]]
    assert [c["status"] for c in changes] == ["started", "stop", "stop", "stop", "completed"]
    assert client.get(f"/api/site-tours/{tour['id']}").json()["id"] == tour["id"]
    listed = client.get(f"/api/site-tours?siteId={BR}").json()
    assert [t["id"] for t in listed] == [tour["id"]]
    assert client.get("/api/site-tours/tour-missing").status_code == 404


def test_focus_assets_come_first_and_bad_input_is_refused(client, eye):
    service = svc(client)
    worst = bad_tags(service, BR)
    calm = next(c["tag"] for c in service.reality.components(BR) if c["tag"] not in worst)
    tour = client.post("/api/site-tours", json={"siteId": BR, "focus": [calm], "maxStops": 2}).json()
    assert tour["stops"][0]["assetTag"] == calm and len(tour["stops"]) == 2
    unknown = client.post("/api/site-tours", json={"siteId": BR, "focus": ["ZZ-999"]})
    assert unknown.status_code == 404 and unknown.json()["code"] == "UNKNOWN_ASSET"
    assert client.post("/api/site-tours", json={"siteId": BR, "maxStops": 9}).status_code == 422
    assert client.post("/api/site-tours", json={"siteId": "nowhere"}).status_code == 404
    stranger = client.post("/api/site-tours", json={"siteId": BR}, headers={"X-Steward-Actor": "nobody"})
    assert stranger.status_code == 403 and stranger.json()["code"] == "AUTHORITY_DENIED"


def test_one_tour_per_site_at_a_time(client, eye):
    service = svc(client)
    running = dict(id="tour-running", siteId=BR, siteName="Bristol Dock Pump House", requester="operator", requesterName="Owner's agent", actor="operator",
                   guide=INSPECTOR, guideName="Site Inspector", state="running", focus=[], maxStops=5, route=["V-504"], stops=[], findings=[], summary=None,
                   error=None, startedAt=now(), finishedAt=None)
    service.store.put("site_tour", running, BR)
    again = client.post("/api/site-tours", json={"siteId": BR}).json()
    assert again["id"] == "tour-running" and not eye


def test_an_eye_failure_never_fails_the_tour(client, monkeypatch):
    service = svc(client)

    def broken(site_id, action, params, actor, timeout=None):
        raise RealityError("No renderer answered.", "EYE_TIMEOUT", "Retry.", 504)

    monkeypatch.setattr(service.eye, "act_sync", broken)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])
    tour = client.post("/api/site-tours", json={"siteId": BR, "maxStops": 2}).json()
    assert tour["state"] == "completed" and len(tour["stops"]) == 2
    assert all(s["frameId"] is None and s["frameUrl"] is None and "eye unavailable" in s["eyeNote"] for s in tour["stops"])
    assert "No pictures" in tour["summary"] or "all look good" in tour["summary"]


def test_a_steward_agent_that_asked_gets_the_findings_over_a2a(client, eye):
    service = svc(client)
    tour = client.post("/api/site-tours", json={"siteId": BR, "maxStops": 2}, headers={"X-Steward-Actor": "director"}).json()
    assert tour["requesterName"] == "Operations Director" and tour.get("conversationId")
    conversation = service.conversations.get(tour["conversationId"])
    assert set(conversation["participants"]) == {INSPECTOR, "director"} and conversation["transcript"][0]["text"] == tour["summary"]
    task = service.bus.task(conversation["a2aTaskIds"][0])
    data = task["messages"][0]["parts"][-1]["data"]["steward"]
    assert data["tourId"] == tour["id"] and data["findings"] == len(tour["findings"])
    assert [f["frameUrl"] for f in data["frames"]] == [s["frameUrl"] for s in tour["findings"] if s["frameUrl"]]
    # The owner's agent (an MCP client) gets the pictures in its tool result, not a message.
    mine = client.post("/api/site-tours", json={"siteId": "myer-plant", "maxStops": 1}).json()
    assert not mine.get("conversationId")
