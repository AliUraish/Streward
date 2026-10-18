import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

import httpx
import pytest

from src.integrations import ModelAdapter, SupermemoryAdapter, integration_status
from src.providers import InkboxAdapter, InsForgeAdapter, ProviderNotConfigured, StripeSandbox


def test_stripe_sandbox_refuses_live_keys_and_builds_idempotent_test_session(monkeypatch):
    purchase = dict(id="proposal-1", description="Gasket", amount=24.50, currency="USD")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_should_never_be_used")
    with pytest.raises(ProviderNotConfigured):
        StripeSandbox().checkout("myer-plant", purchase)
    calls = []

    def transport(request):
        calls.append(request)
        payload = parse_qs(request.content.decode())
        assert payload["line_items[0][price_data][unit_amount]"] == ["2450"]
        assert payload["metadata[propertyId]"] == ["myer-plant"]
        assert payload["metadata[purchaseId]"] == ["proposal-1"]
        assert request.headers["Idempotency-Key"] == "steward-test-checkout-proposal-1"
        return httpx.Response(200, json={"id": "cs_test_123", "livemode": False, "url": "https://checkout.stripe.com/c/test"})

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    result = StripeSandbox(httpx.MockTransport(transport)).checkout("myer-plant", purchase)
    assert result["mode"] == "test"
    assert len(calls) == 1


def test_stripe_signature_timestamp_and_livemode_are_verified(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_fixture")
    timestamp = 1000000000

    def signature(raw):
        digest = hmac.new(b"whsec_fixture", str(timestamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={digest}"

    raw = json.dumps({"id": "evt_test", "livemode": False}).encode()
    assert StripeSandbox.verify_webhook(raw, signature(raw), timestamp)["id"] == "evt_test"
    with pytest.raises(ValueError):
        StripeSandbox.verify_webhook(raw + b" ", signature(raw), timestamp)
    with pytest.raises(ValueError):
        StripeSandbox.verify_webhook(raw, signature(raw), timestamp + 301)
    live = json.dumps({"id": "evt_live", "livemode": True}).encode()
    with pytest.raises(ValueError):
        StripeSandbox.verify_webhook(live, signature(live), timestamp)


def test_inkbox_never_sends_without_explicit_enable_and_allowlist(monkeypatch):
    adapter = InkboxAdapter()
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "false")
    with pytest.raises(ProviderNotConfigured):
        adapter.send("myer-plant", ["owner@example.com"], "Update", "Fixture")
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "owner@example.com")
    with pytest.raises(ValueError):
        adapter.send("myer-plant", ["owner@example.com", "stranger@example.com"], "Update", "Fixture")

    @dataclass
    class Message:
        id: str
        status: str

    class Identity:
        agent_handle = "myer-plant-bot"
        email_address = "custom@approved.example"

        def send_email(self, **kwargs):
            assert kwargs["to"] == ["owner@example.com"]
            assert kwargs["body_text"] == "Fixture"
            return Message("msg-fixture", "queued")

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_identity(self, handle):
            assert handle == "myer-plant-bot"
            return Identity()

    monkeypatch.setenv("INKBOX_IDENTITY_MYER_TECHNICIAN", "myer-plant-bot")  # contract 4: the site's Field Technician emails
    monkeypatch.setattr(adapter, "client", lambda: FakeClient())
    assert adapter.status("myer-plant")["email"] == "custom@approved.example"  # Trust actual assigned address.
    assert adapter.send("myer-plant", ["owner@example.com"], "Update", "Fixture")["status"] == "queued"


def test_insforge_check_is_read_only_and_does_not_claim_database_migration(monkeypatch):
    monkeypatch.setenv("INSFORGE_BASE_URL", "https://demo.insforge.app")
    monkeypatch.setenv("INSFORGE_ANON_KEY", "public-fixture")

    def transport(request):
        assert request.method == "GET"
        assert request.url.path == "/api/database/records/steward_properties"
        return httpx.Response(404, json={"detail": "missing table"})

    result = InsForgeAdapter(httpx.MockTransport(transport)).check()
    assert result["status"] == "needs_schema"


def test_model_failure_remains_explicit_and_never_reports_external_action(client=None):
    # This test intentionally has no provider credentials and makes no network call.
    adapter = ModelAdapter()
    adapter.provider = "local"
    assert adapter.synthesize("Did you buy it?", {"property": {"id": "myer-plant"}}) is None


def test_supermemory_uses_server_derived_namespace_and_source_linked_async_writes(monkeypatch):
    monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_fixture")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        assert kwargs["headers"]["Authorization"] == "Bearer sm_fixture"
        return httpx.Response(200, json={"id": "memory-123", "status": "queued", "results": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    adapter = SupermemoryAdapter()
    memory = {"id": "memory-123", "content": "Check pump identifier", "source": "job:abc", "createdAt": "2026-10-17T20:00:00Z"}
    assert adapter.save("myer-plant", memory)["status"] == "queued"
    adapter.recall("myer-plant", "pump identity")
    assert calls[0][0] == "https://api.supermemory.ai/ns/steward-local-myer-plant/document"
    assert calls[0][1]["metadata"]["source"] == "job:abc"
    assert "dreaming" not in calls[0][1]  # No surprise paid instant ingestion.
    assert calls[1][0].endswith("/steward-local-myer-plant/search")
    assert calls[1][1]["searchMode"] == "hybrid"


def test_capabilities_reflect_credentials_property_scope_and_explicit_action_gates(monkeypatch):
    keys = ["INKBOX_API_KEY", "INKBOX_IDENTITY", "INKBOX_IDENTITY_MYER_TECHNICIAN", "INKBOX_IDENTITY_BRISTOL_TECHNICIAN", "INKBOX_IDENTITY_WARDEN_MYER_PLANT",
            "INKBOX_ALLOWED_RECIPIENTS", "STEWARD_ALLOW_EXTERNAL_MESSAGES", "STEWARD_ALLOW_IDENTITY_PROVISION", "STRIPE_SECRET_KEY",
            "SUPERMEMORY_API_KEY", "INSFORGE_BASE_URL", "INSFORGE_ANON_KEY"]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    def capabilities(property_id="myer-plant"):
        return {item["id"]: item["capabilities"] for item in integration_status(property_id)}

    assert capabilities()["inkbox"] == {"identity": False, "inbox": False, "sendEmail": False, "createIdentity": False}
    assert capabilities()["stripe"]["testCheckout"] is False
    monkeypatch.setenv("INKBOX_API_KEY", "fixture")
    monkeypatch.setenv("INKBOX_IDENTITY_WARDEN_MYER_PLANT", "steward-warden-myer")  # retired: never read
    assert capabilities()["inkbox"]["identity"] is False
    monkeypatch.setenv("INKBOX_IDENTITY_MYER_TECHNICIAN", "myer-plant-bot")
    assert capabilities()["inkbox"]["identity"] is True
    assert capabilities("bristol-pumps")["inkbox"]["inbox"] is False
    monkeypatch.setenv("STEWARD_ALLOW_EXTERNAL_MESSAGES", "true")
    assert capabilities()["inkbox"]["sendEmail"] is False
    monkeypatch.setenv("INKBOX_ALLOWED_RECIPIENTS", "owner@example.com")
    assert capabilities()["inkbox"]["sendEmail"] is True
    monkeypatch.setenv("STEWARD_ALLOW_IDENTITY_PROVISION", "true")
    assert capabilities()["inkbox"]["createIdentity"] is True
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_fixture")
    assert capabilities()["stripe"]["testCheckout"] is False
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fixture")
    assert capabilities()["stripe"]["testCheckout"] is True
    monkeypatch.setenv("INSFORGE_BASE_URL", "https://fixture.insforge.app")
    assert capabilities()["insforge"]["check"] is False
    monkeypatch.setenv("INSFORGE_ANON_KEY", "fixture")
    assert capabilities()["insforge"]["check"] is True


def test_eve_readiness_can_use_runtime_gateway_key_or_explicit_authenticated_runtime(monkeypatch):
    for key in ("STEWARD_MODEL_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AI_GATEWAY_API_KEY", "STEWARD_EVE_READY"):
        monkeypatch.delenv(key, raising=False)
    adapter = ModelAdapter()
    adapter.provider = "eve"
    assert adapter.configured is False
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fixture-key")
    assert adapter.configured is True
    monkeypatch.delenv("AI_GATEWAY_API_KEY")
    monkeypatch.setenv("STEWARD_EVE_READY", "true")
    assert adapter.configured is True
    # A declared runtime is configured, not verified/connected before an actual successful request.
    monkeypatch.setenv("STEWARD_MODEL_PROVIDER", "eve")
    status = next(item for item in integration_status() if item["id"] == "model")
    assert status["status"] == "local"
    assert status["capabilities"]["synthesize"] is True
    monkeypatch.setenv("STEWARD_EVE_READY", "false")
    assert adapter.configured is False
