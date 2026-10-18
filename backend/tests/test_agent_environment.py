"""The agent environment: one read-only view of a site as an agent sees it (the walk, the latest eye frames with what the agents
marked in them, labels, readings, obligations, open issues, the latest inspection and tours, the recent log and the tools), as
JSON and as markdown for the MCP. The eye is stubbed; nothing leaves the process."""
import hashlib
import io
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.agent_environment import QUIET_TYPES
from src.agents import display_name
from src.main import create_app
from src.store import now

BR = "bristol-pumps"
KEYS = {"siteId", "siteName", "at", "summary", "walk", "eye", "labels", "readings", "obligations", "issues", "inspection", "tours", "logs", "tools", "markdown"}


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

    def act_sync(site_id, action, params, actor, timeout=None):
        frame_id = f"eyf-{uuid4().hex[:16]}"
        (service.eye.frames_dir / f"{frame_id}.jpg").write_bytes(JPEG)
        service.store.put("eye_frame", dict(id=frame_id, seq=1, siteId=site_id, commandId="eyc-test", action=action, params=params, actor=actor,
                                            actorName=display_name(actor), camera=None, visiblePins=[], index=0, rendererId="test", size=len(JPEG),
                                            sha256=hashlib.sha256(JPEG).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now()), site_id)
        return dict(frameId=frame_id, frameUrl=f"/api/eye/frames/{frame_id}.jpg")

    monkeypatch.setattr(service.eye, "act_sync", act_sync)
    monkeypatch.setattr(service.eye, "fresh", lambda site_id, headless=None: [{"rendererId": "test"}])


def test_the_view_has_every_part_and_reads_like_the_site(client, eye):
    service = svc(client)
    tour = client.post("/api/site-tours", json={"siteId": BR, "maxStops": 2}).json()
    frame_id = tour["stops"][-1]["frameId"]
    service.store.put("patrol_label", dict(id="lbl-test", patrolId="ptl-test", siteId=BR, assetTag=tour["stops"][-1]["assetTag"], assetName="Test asset",
                                            verdict="bad", color="blue", title="Looks bad", reasons=["Pipework examination overdue by 6 days"],
                                            mark=dict(x=0.42, y=0.55, note="seized spindle", frameId=frame_id), regulationIds=["eng-pssr-2000-reg-9-6"],
                                            frameId=frame_id, frameUrl=f"/api/eye/frames/{frame_id}.jpg", at=now(), assessedBy="claude"), BR)
    service.store.put("patrol", dict(id="ptl-walking", siteId=BR, agentId="bristol-engineer", agentName="Site Engineer · Bristol", state="running",
                                     route=["PG-602", "V-504", "P-103"], stopIndex=1, currentAssetTag="V-504", startedAt=now()), BR)
    response = client.get(f"/api/agent-environment/{BR}")
    assert response.status_code == 200
    view = response.json()
    assert set(view) == KEYS and view["siteId"] == BR and view["siteName"] == "Bristol Dock Pump House"
    assert set(view["summary"]) == {"compliancePercent", "openIssues", "overdue", "blocked", "employeesCheckedIn", "crewOnShift"}
    assert 0 < view["summary"]["compliancePercent"] < 100 and view["summary"]["overdue"] + view["summary"]["blocked"] >= 1
    walk = view["walk"]
    assert walk == dict(state="running", agentId="bristol-engineer", agentName="Site Engineer · Bristol", stopIndex=2, stops=3, assetTag="V-504",
                        assetName=walk["assetName"], moving=True, startedAt=walk["startedAt"]) and walk["assetName"]
    frames = view["eye"]["frames"]
    assert 1 <= len(frames) <= 3 and frames[0]["url"].startswith("/api/eye/frames/") and frames[0]["actorName"] == "Site Inspector"
    marked = next(f for f in frames if f["id"] == frame_id)
    assert marked["labels"] == [dict(assetTag=tour["stops"][-1]["assetTag"], verdict="bad", color="blue", title="Looks bad",
                                     reasons=["Pipework examination overdue by 6 days"], mark=dict(x=0.42, y=0.55, note="seized spindle"))]
    assert any(l["assetTag"] == tour["stops"][-1]["assetTag"] and l["regulationIds"] == ["eng-pssr-2000-reg-9-6"] for l in view["labels"])
    assert view["readings"] and set(view["readings"][0]) == {"key", "label", "assetTag", "unit", "value", "previous", "delta", "trend", "state", "spec"}
    assert view["obligations"] and view["obligations"][0]["status"] == "blocked" and all(o["status"] in ("blocked", "overdue", "due_soon") for o in view["obligations"])
    assert view["issues"] and all(set(i) == {"id", "kind", "severity", "assetTag", "summary", "at"} for i in view["issues"])
    assert view["tours"][0]["id"] == tour["id"] and view["tours"][0]["stops"] == 2
    assert all(l["type"] not in QUIET_TYPES for l in view["logs"]) and len(view["logs"]) <= 20
    assert {"get_environment", "request_site_tour", "get_site_tour", "eye_go_to"} <= {t["name"] for t in view["tools"]}
    raw = json.dumps(view)
    assert not any(word in raw.lower() for word in ("synthetic", "simulat", "\"demo\"")) and "@" not in raw
    md = view["markdown"]
    assert md.startswith("# Bristol Dock Pump House (bristol-pumps): what the agents see") and "## What the eye sees" in md and "## Tools" in md
    assert "Walking: Site Engineer · Bristol, stop 2 of 3 at V-504" in md and "marked at x 0.42, y 0.55: seized spindle" in md


def test_markdown_format_and_unknown_sites(client):
    text = client.get(f"/api/agent-environment/{BR}?format=md")
    assert text.status_code == 200 and text.headers["content-type"].startswith("text/markdown") and text.text.startswith("# Bristol Dock Pump House")
    assert "No frames yet" in text.text  # no eye frame has been rendered in this fresh store
    assert client.get("/api/agent-environment/nowhere").status_code == 404
    assert client.get(f"/api/agent-environment/{BR}?format=xml").status_code == 422
