"""Explicit, opt-in external service actions. Defaults never send or charge anything."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import asdict, is_dataclass
from decimal import Decimal, ROUND_HALF_UP

import httpx

from .env import env


class ProviderNotConfigured(ValueError):
    pass


class StripeSandbox:
    def __init__(self, transport=None):
        self.transport = transport

    def checkout(self, property_id, purchase):
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if not key.startswith("sk_test_"):
            raise ProviderNotConfigured("Stripe sandbox is not configured. Set STRIPE_SECRET_KEY to a test key (sk_test_...). Live keys are refused.")
        currency = purchase["currency"].lower()
        zero_decimal = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}
        multiplier = 1 if currency in zero_decimal else 100
        minor_amount = int((Decimal(str(purchase["amount"])) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if minor_amount < 1:
            raise ValueError("Amount is below the currency's minimum unit.")
        base_url = env("STEWARD_PUBLIC_APP_URL", "http://localhost:3000").rstrip("/")
        # This is a merchant test collection, not supplier procurement or a wallet debit.
        data = {
            "mode": "payment", "success_url": f"{base_url}/?payment=test_complete&purchase={purchase['id']}",
            "cancel_url": f"{base_url}/?payment=test_cancelled&purchase={purchase['id']}",
            "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": currency,
            "line_items[0][price_data][unit_amount]": str(minor_amount),
            "line_items[0][price_data][product_data][name]": "Steward sandbox proposal: " + purchase["description"][:180],
            "line_items[0][price_data][product_data][description]": "Test merchant payment only. No supplier order, delivery or live purchase.",
            "metadata[propertyId]": property_id, "metadata[purchaseId]": purchase["id"],
            "client_reference_id": purchase["id"],
        }
        with httpx.Client(transport=self.transport, timeout=25) as client:
            response = client.post("https://api.stripe.com/v1/checkout/sessions", auth=(key, ""), data=data,
                                   headers={"Idempotency-Key": f"steward-test-checkout-{purchase['id']}"})
        response.raise_for_status()
        payload = response.json()
        if payload.get("livemode") is not False or not payload.get("id") or not payload.get("url"):
            raise ValueError("Stripe returned an unexpected or live Checkout session; local state was not marked paid.")
        return {"sessionId": payload["id"], "url": payload["url"], "mode": "test", "detail": "Sandbox merchant Checkout; no supplier order is placed."}

    @staticmethod
    def verify_webhook(raw: bytes, signature: str, current_time=None):
        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        if not secret:
            raise ProviderNotConfigured("Stripe webhook is not configured. Set STRIPE_WEBHOOK_SECRET from the local Stripe CLI listener.")
        parts = {}
        for part in signature.split(","):
            key, _, value = part.partition("=")
            parts.setdefault(key, []).append(value)
        try:
            timestamp = int(parts["t"][0])
        except (KeyError, ValueError):
            raise ValueError("Invalid Stripe signature header.")
        if abs((current_time if current_time is not None else time.time()) - timestamp) > 300:
            raise ValueError("Stripe webhook timestamp is outside the permitted window.")
        digest = hmac.new(secret.encode(), str(timestamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(digest, value) for value in parts.get("v1", [])):
            raise ValueError("Stripe webhook signature did not verify.")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("livemode") is not False:
            raise ValueError("Only signed Stripe test events are accepted.")
        return payload


class InkboxAdapter:
    """SDK transport, with operator-configured identities and an exact recipient allowlist."""
    @staticmethod
    def identity_handle(property_id):
        return os.getenv(f"INKBOX_IDENTITY_{property_id.upper()}") or os.getenv("INKBOX_IDENTITY", "")

    @staticmethod
    def client():
        key = os.getenv("INKBOX_API_KEY")
        if not key:
            raise ProviderNotConfigured("Inkbox is not configured. Add INKBOX_API_KEY and a property identity handle.")
        try:
            from inkbox import Inkbox
        except ImportError:
            raise ProviderNotConfigured("Inkbox SDK is missing. Install backend requirements before enabling this integration.")
        return Inkbox(api_key=key)

    def resolve_identity(self, client, property_id):
        handle = self.identity_handle(property_id)
        if not handle:
            raise ProviderNotConfigured(f"Set INKBOX_IDENTITY_{property_id.upper()} to an existing identity handle.")
        return client.get_identity(handle)

    def status(self, property_id):
        with self.client() as client:
            identity = self.resolve_identity(client, property_id)
            return {"handle": identity.agent_handle, "email": identity.email_address}

    def inbox(self, property_id):
        with self.client() as client:
            identity = self.resolve_identity(client, property_id)
            from itertools import islice
            return [self.serialize(item) for item in islice(identity.iter_emails(), 30)]

    def create_identity(self, property_id, handle, display_name):
        if env("STEWARD_ALLOW_IDENTITY_PROVISION", "false").lower() != "true":
            raise ProviderNotConfigured("Identity provisioning is disabled. Set STEWARD_ALLOW_IDENTITY_PROVISION=true only after choosing an account/plan.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,48}", handle):
            raise ValueError("Identity handle must be 3–49 lowercase letters, numbers or hyphens.")
        with self.client() as client:
            identity = client.create_identity(handle, display_name=display_name)
            return {"handle": identity.agent_handle, "email": identity.email_address, "propertyId": property_id}

    def send(self, property_id, to, subject, body_text):
        if env("STEWARD_ALLOW_EXTERNAL_MESSAGES", "false").lower() != "true":
            raise ProviderNotConfigured("External messages are disabled. Enable STEWARD_ALLOW_EXTERNAL_MESSAGES and configure INKBOX_ALLOWED_RECIPIENTS before sending.")
        allowlist = {email.strip().casefold() for email in os.getenv("INKBOX_ALLOWED_RECIPIENTS", "").split(",") if email.strip()}
        if not to or any(address.casefold() not in allowlist for address in to):
            raise ValueError("Every recipient must be explicitly listed in INKBOX_ALLOWED_RECIPIENTS.")
        with self.client() as client:
            identity = self.resolve_identity(client, property_id)
            return self.serialize(identity.send_email(to=to, subject=subject, body_text=body_text))

    @staticmethod
    def serialize(value):
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return value
        if is_dataclass(value):
            return json.loads(json.dumps(asdict(value), default=str))
        return {"detail": str(value)}


class InsForgeAdapter:
    """Read-only connectivity check for an existing InsForge project; never provisions resources."""
    def __init__(self, transport=None):
        self.transport = transport

    def check(self):
        base = os.getenv("INSFORGE_BASE_URL", "").rstrip("/")
        key = os.getenv("INSFORGE_ANON_KEY", "")
        if not base or not key:
            raise ProviderNotConfigured("InsForge is not configured. Add INSFORGE_BASE_URL and INSFORGE_ANON_KEY for an existing project.")
        with httpx.Client(transport=self.transport, timeout=15) as client:
            response = client.get(base + "/api/database/records/steward_properties", headers={"Authorization": "Bearer " + key}, params={"limit": 1})
        if response.status_code == 404:
            return {"status": "needs_schema", "detail": "Project responded, but steward_properties has not been created. Local data remains active."}
        response.raise_for_status()
        return {"status": "reachable", "detail": "Read-only project table request succeeded. The application still uses local SQLite.", "records": response.json()}
