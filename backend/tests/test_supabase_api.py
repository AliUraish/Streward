"""HTTP surface of the Supabase features: usage, viewer heartbeats, the authority check, the ledger and signed frames."""
import base64
import io
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.main import create_app
from src.mirror import Mirror
from src.supa_authority import AGENT_IDS
from src.supa_services import SupaServices


def fake_jwt(claims: dict) -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{part({'alg': 'ES256'})}.{part(claims)}.c2ln"


class FakeProject:
    def __init__(self):
        self.calls = []
        self.ledger_hash = "h" * 64
        self.probe = dict(attempted=True, allowed=False, sqlstate="42501", rolledBack=True,
                          message='new row violates row-level security policy for table "attestations"')

    def __call__(self, request: httpx.Request):
        path = request.url.path
        body = json.loads(request.content) if request.content and request.headers.get("content-type", "").startswith("application/json") else None
        self.calls.append((request.method, path, dict(request.headers), body, dict(request.url.params)))
        if path == "/auth/v1/token":
            agent = body["email"].split("+", 1)[1].split("@", 1)[0]
            claims = dict(sub="u-" + agent, role="authenticated", agent_id=agent, agent_level=5, site_id="myer-plant", agent_role="technician")
            return httpx.Response(200, json=dict(access_token=fake_jwt(claims), refresh_token="r", expires_in=3600, expires_at=time.time() + 3600))
        if path == "/rest/v1/rpc/steward_authority_probe":
            return httpx.Response(200, json=self.probe)
        if path == "/rest/v1/rpc/verify_ledger":
            start = body["p_from_seq"]
            head = dict(chainSeq=start + 1, rowHash=self.ledger_hash, id="att-x")
            return httpx.Response(200, json=dict(ok=True, checked=2, fromSeq=start, head=head, signatures=dict(checked=2, method="pgsodium")))
        if path == "/rest/v1/attestations":
            return httpx.Response(200, json=[dict(chain_seq=int(request.url.params["chain_seq"][3:]), row_hash=self.ledger_hash)])
        if path.startswith("/storage/v1/object/sign/"):
            return httpx.Response(200, json={"signedURL": "/object/sign/" + path.removeprefix("/storage/v1/object/sign/") + "?token=t"})
        if path.startswith("/storage/v1/object/"):
            return httpx.Response(200, json={"Key": path})
        return httpx.Response(201)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def connect(client, monkeypatch, agents=True):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_test")
    if agents:
        monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_test")
        for agent in AGENT_IDS:
            monkeypatch.setenv("STEWARD_AGENT_PASSWORD_" + agent.upper().replace("-", "_"), "pw")
    fake = FakeProject()
    reality = client.app.state.service.reality
    reality.mirror.close()
    reality.mirror = Mirror(reality.store, transport=httpx.MockTransport(fake))
    services = SupaServices(reality.mirror, client.app.state.service, app=None, start_threads=False)
    reality.mirror.services = services
    return fake, services


def test_usage_reports_counters_without_configuration(client):
    body = client.get("/api/supabase/usage").json()
    assert body["configured"] is False and body["plan"] == "free" and body["services"] is None
    keys = {c["key"] for c in body["budget"]["counters"]}
    assert {"realtime_msgs_day", "realtime_msgs_month", "storage_mb", "upload_mb", "edge_calls_day", "db_mb", "egress_mb_day"} <= keys
    assert all("cap" in c and "freeLimit" in c for c in body["budget"]["counters"])
    assert body["mau"]["agents"] == 14  # 2 + 4 agents per site at myer-plant, bristol-pumps and tomioka-mill


def test_viewer_heartbeats_gate_realtime(client, monkeypatch):
    off = client.post("/api/supabase/viewers", json={"siteId": "myer-plant", "viewerId": "viewer-123456"}).json()
    assert off["realtime"] is False
    assert client.post("/api/supabase/viewers", json={"siteId": "nowhere", "viewerId": "viewer-123456"}).status_code == 404
    fake, services = connect(client, monkeypatch, agents=False)
    on = client.post("/api/supabase/viewers", json={"siteId": "myer-plant", "viewerId": "viewer-123456"}).json()
    assert on["realtime"] is True and on["channel"] == "site:myer-plant:hud" and on["viewers"] == 1
    assert client.post("/api/supabase/viewers", json={"siteId": "myer-plant", "viewerId": "viewer-123456", "leave": True}).json()["viewers"] == 0
    usage = client.get("/api/supabase/usage").json()
    assert next(c for c in usage["budget"]["counters"] if c["key"] == "realtime_msgs_day")["used"] == 2  # presence join: 2 + 0


def test_authority_check_returns_postgres_own_refusal(client, monkeypatch):
    fake, _ = connect(client, monkeypatch)
    response = client.post("/api/supabase/authority-check", json={"agentId": "myer-technician", "table": "attestations", "action": "insert"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["postgres"]["message"] == 'new row violates row-level security policy for table "attestations"'
    assert body["postgres"]["sqlstate"] == "42501" and body["localAuthoritySays"] == "refused" and body["agreement"] is True
    assert body["claims"]["agent_id"] == "myer-technician" and body["claims"]["site_id"] == "myer-plant"
    probe = next(c for c in fake.calls if c[1] == "/rest/v1/rpc/steward_authority_probe")
    assert probe[2]["authorization"].startswith("Bearer ") and probe[2]["apikey"] == "sb_publishable_test"  # as the agent, not the service role
    assert client.post("/api/supabase/authority-check", json={"agentId": "nobody", "table": "attestations"}).status_code == 404


def test_ledger_verifies_incrementally_from_the_local_anchor(client, monkeypatch):
    fake, _ = connect(client, monkeypatch)
    first = client.get("/api/supabase/ledger").json()
    assert first["ok"] is True and first["mode"].startswith("full") and first["ledger"]["head"]["chainSeq"] == 2
    second = client.get("/api/supabase/ledger").json()
    assert second["ok"] is True and second["mode"].startswith("incremental") and second["anchor"]["stillMatches"] is True
    call = [c for c in fake.calls if c[1] == "/rest/v1/rpc/verify_ledger"][-1]
    assert call[3]["p_from_seq"] == 3 and call[3]["p_expected_prev"] == "h" * 64
    fake.ledger_hash = "x" * 64  # someone rewrote the chain under the anchor
    third = client.get("/api/supabase/ledger").json()
    assert third["ok"] is False and third["anchor"]["stillMatches"] is False


def test_frames_redirect_browsers_to_signed_urls_and_serve_agents_bytes(client, monkeypatch):
    fake, services = connect(client, monkeypatch, agents=False)
    store = client.app.state.service.store
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (10, 20, 30)).save(buffer, format="JPEG")
    frame = dict(id="eyf-00000000000000aa", seq=1, siteId="myer-plant", commandId="c1", action="look", params={}, actor="myer-engineer",
                 actorName="Site Engineer · Myer", camera=None, visiblePins=[], index=0, rendererId="r", size=len(buffer.getvalue()), sha256="0",
                 url="/api/eye/frames/eyf-00000000000000aa.jpg", at="2026-10-18T00:00:00Z")
    (services.frames_dir / f"{frame['id']}.jpg").write_bytes(buffer.getvalue())
    store.put("eye_frame", frame, "myer-plant")
    local = client.get(f"/api/eye/frames/{frame['id']}.jpg", follow_redirects=False)
    assert local.status_code == 200  # not uploaded yet: local bytes
    assert services.storage.upload_frame(frame, services.frames_dir)
    browser = client.get(f"/api/eye/frames/{frame['id']}.jpg", follow_redirects=False)
    assert browser.status_code == 307 and browser.headers["location"].startswith("https://example.supabase.co/storage/v1/object/sign/eye-frames/")
    agent = client.get(f"/api/eye/frames/{frame['id']}.jpg", headers={"X-Steward-Actor": "myer-engineer"}, follow_redirects=False)
    assert agent.status_code == 200 and agent.headers["content-type"] == "image/jpeg"  # the MCP eye tools refuse redirects
    assert client.get(f"/api/eye/frames/{frame['id']}.jpg?local=1", follow_redirects=False).status_code == 200
    feed = client.get("/api/eye/myer-plant/feed").json()
    item = next(f for f in feed["frames"] if f["id"] == frame["id"])
    assert item["storage"] == "supabase" and item["url"] == item["signedUrl"] and item["localUrl"] == frame["url"] and item["thumbUrl"]
