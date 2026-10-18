"""Requests that arrive through the public tunnel (a non-loopback x-forwarded-host) must carry the backend token, because
X-Steward-Actor selects the acting agent. Local calls and the local Next.js proxy (x-forwarded-host 127.0.0.1:3000) stay
open; health and the signed Inkbox webhook stay reachable."""
import pytest
from fastapi.testclient import TestClient

from src.main import create_app

TUNNEL = {"x-forwarded-host": "steward-atlas.inkboxwire.com", "x-forwarded-proto": "https"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "local")
    for key in ("STEWARD_API_TOKEN", "STEWARD_ALLOW_REMOTE_UNAUTHENTICATED", "PHY_API_TOKEN", "PHY_ALLOW_REMOTE_UNAUTHENTICATED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("STEWARD_BACKEND_TOKEN", "test-remote-token")
    with TestClient(create_app(tmp_path / "data", start_workers=False)) as client:
        yield client


def test_local_calls_and_the_local_proxy_stay_open(client):
    assert client.get("/api/properties").status_code == 200
    for host in ("127.0.0.1:3000", "localhost:3000", "[::1]:3000", "steward.localhost"):
        assert client.get("/api/properties", headers={"x-forwarded-host": host}).status_code == 200, host


def test_tunnel_calls_need_the_backend_token(client):
    denied = client.get("/api/properties", headers=TUNNEL)
    assert denied.status_code == 401 and denied.json()["code"] == "AUTH_REQUIRED"
    acted = client.post("/api/eye/myer-plant/act", json={"action": "look"}, headers={**TUNNEL, "X-Steward-Actor": "director"})
    assert acted.status_code == 401  # never reaches the actor header
    assert client.get("/api/properties", headers={**TUNNEL, "Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/properties", headers={**TUNNEL, "Authorization": "Bearer test-remote-token"}).status_code == 200


def test_tunnel_is_closed_when_no_backend_token_is_configured(client, monkeypatch):
    monkeypatch.delenv("STEWARD_BACKEND_TOKEN")
    assert client.get("/api/properties", headers={**TUNNEL, "Authorization": "Bearer "}).status_code == 401


def test_health_and_the_signed_webhook_stay_reachable_through_the_tunnel(client):
    assert client.get("/health", headers=TUNNEL).status_code == 200
    webhook = client.post("/api/inbound/inkbox", json={}, headers=TUNNEL)
    assert webhook.json().get("code") != "AUTH_REQUIRED"  # its own signature check answers, not the tunnel gate


def test_remote_gate_can_be_opened_explicitly(client, monkeypatch):
    monkeypatch.setenv("STEWARD_ALLOW_REMOTE_UNAUTHENTICATED", "true")
    assert client.get("/api/properties", headers=TUNNEL).status_code == 200
