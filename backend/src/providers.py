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
from .sites import SITE_IDS, site_env_suffix

# Contract 4 team identities per site (INKBOX_IDENTITY_<PREFIX>_<ROLE>); agents.py holds the full roster.
TEAM_ENV_PREFIX = {"myer-plant": "MYER", "bristol-pumps": "BRISTOL", "tomioka-mill": "TOMIOKA"}
TEAM_ROLES = ("MANAGER", "ENGINEER", "COMPLIANCE", "TECHNICIAN")


def team_identity_env(property_id: str, role: str = "TECHNICIAN") -> str:
    return f"INKBOX_IDENTITY_{TEAM_ENV_PREFIX.get(property_id, site_env_suffix(property_id))}_{role}"


class ProviderNotConfigured(ValueError):
    pass


PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_env(name: str, default: str = "") -> str:
    """Environment value with surrounding whitespace, quotes and inline `# comments` removed. Template files
    sometimes leave a comment as the value; a value that is only a comment counts as unset."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    if not value or value.startswith("#"):
        return default
    value = re.split(r"\s+#", value, maxsplit=1)[0].strip().strip('"').strip("'").strip()
    return value or default


def inkbox_base_url() -> str:
    value = clean_env("INKBOX_BASE_URL")
    return value if value.startswith(("https://", "http://localhost", "http://127.0.0.1")) else "https://inkbox.ai"


def external_messages_allowed() -> bool:
    """The single send-time gate for every outbound message to a person (SMS, email, iMessage, calls, owner questions,
    notices, document email). Read from the environment on every call, never cached, so flipping
    STEWARD_ALLOW_EXTERNAL_MESSAGES takes effect without a restart."""
    return clean_env("STEWARD_ALLOW_EXTERNAL_MESSAGES", "false").strip().lower() == "true"


def allowed_recipients() -> set[str]:
    return {item.strip().casefold() for item in clean_env("INKBOX_ALLOWED_RECIPIENTS").split(",") if item.strip()}


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
        """The site identity that sends work-item task cards by email is the site's Field Technician
        (INKBOX_IDENTITY_<MYER|BRISTOL|TOMIOKA>_TECHNICIAN; every agent emails from its own identity), with the shared
        INKBOX_IDENTITY as the fallback. The retired Warden identities are never read."""
        return clean_env(team_identity_env(property_id)) or clean_env("INKBOX_IDENTITY")

    @staticmethod
    def client():
        key = clean_env("INKBOX_API_KEY")
        if not key:
            raise ProviderNotConfigured("Inkbox is not configured. Add INKBOX_API_KEY and a property identity handle.")
        try:
            from inkbox import Inkbox
        except ImportError:
            raise ProviderNotConfigured("Inkbox SDK is missing. Install backend requirements before enabling this integration.")
        # base_url is passed explicitly: the SDK would otherwise read INKBOX_BASE_URL raw, and a template comment there breaks it.
        return Inkbox(api_key=key, base_url=inkbox_base_url())

    def resolve_identity(self, client, property_id):
        handle = self.identity_handle(property_id)
        if not handle:
            raise ProviderNotConfigured(f"Set {team_identity_env(property_id)} to an existing identity handle.")
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
        if not external_messages_allowed():
            raise ProviderNotConfigured("External messages are disabled. Enable STEWARD_ALLOW_EXTERNAL_MESSAGES and configure INKBOX_ALLOWED_RECIPIENTS before sending.")
        allowlist = allowed_recipients()
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

    # ---- Reality-layer comms surface (SMS, email, iMessage, voice, inbound webhooks) --------------------
    # Every outbound send is gated by STEWARD_ALLOW_EXTERNAL_MESSAGES=true and an exact entry in
    # INKBOX_ALLOWED_RECIPIENTS (emails and E.164 phone numbers, comma separated). Nothing is sent otherwise.

    def configured(self, property_id: str) -> bool:
        return bool(clean_env("INKBOX_API_KEY")) and bool(self.identity_handle(property_id))

    @staticmethod
    def contractor_phone():
        r"""E.164-ish phone (^\+?[0-9]{7,15}$) or empty; placeholders and comments never become a recipient."""
        value = clean_env("INKBOX_CONTRACTOR_PHONE")
        return value if PHONE_RE.match(value) else ""

    @staticmethod
    def contractor_email():
        value = clean_env("INKBOX_CONTRACTOR_EMAIL")
        return value if EMAIL_RE.match(value) else ""

    @staticmethod
    def owner_phone():
        value = clean_env("INKBOX_OWNER_PHONE")
        return value if PHONE_RE.match(value) else ""

    @staticmethod
    def owner_email():
        """The owner's address for compliance alerts (contract 7 §2), validated like the contractor's; empty when unset."""
        value = clean_env("INKBOX_OWNER_EMAIL")
        return value if EMAIL_RE.match(value) else ""

    def dispatch_target(self, property_id: str) -> tuple[str, str, str]:
        """(channel, recipient, reason). `local` unless the API key, the site identity, the external-messages gate and a
        validated, allowlisted recipient all exist; the reason says which condition failed."""
        if not clean_env("INKBOX_API_KEY"):
            return "local", "", "INKBOX_API_KEY is not set"
        if not self.identity_handle(property_id):
            return "local", "", f"no Inkbox identity handle for {property_id} ({team_identity_env(property_id)})"
        if not external_messages_allowed():
            return "local", "", "STEWARD_ALLOW_EXTERNAL_MESSAGES is not true"
        allowlist = allowed_recipients()
        phone, email = self.contractor_phone(), self.contractor_email()
        if phone and phone.casefold() in allowlist:
            return "sms", phone, "sms to the allowlisted contractor phone"
        if email and email.casefold() in allowlist:
            return "email", email, "email to the allowlisted contractor address"
        raw_phone, raw_email = clean_env("INKBOX_CONTRACTOR_PHONE"), clean_env("INKBOX_CONTRACTOR_EMAIL")
        if raw_phone and not phone:
            return "local", "", "INKBOX_CONTRACTOR_PHONE is not a valid phone number (^+?[0-9]{7,15}$)"
        if raw_email and not email:
            return "local", "", "INKBOX_CONTRACTOR_EMAIL is not a valid email address"
        if phone or email:
            return "local", "", "the contractor recipient is not in INKBOX_ALLOWED_RECIPIENTS"
        return "local", "", "no INKBOX_CONTRACTOR_PHONE or INKBOX_CONTRACTOR_EMAIL configured"

    @staticmethod
    def phone_identity_handle(property_id: str) -> str:
        """Identity that owns the phone number: the shared Steward Dispatch Line (INKBOX_IDENTITY_DISPATCH, contract 4),
        then the legacy INKBOX_PHONE_IDENTITY. Both field technicians send SMS and place calls through it; the task
        card names the site. The site identity is the last fallback (it has no number, so the send fails honestly)."""
        return clean_env("INKBOX_IDENTITY_DISPATCH") or clean_env("INKBOX_PHONE_IDENTITY") or InkboxAdapter.identity_handle(property_id)

    @staticmethod
    def site_for_handle(handle: str | None, sites=None) -> str | None:
        """Map an Inkbox identity handle (or mailbox address / phone number) to the site that owns it."""
        if not handle:
            return None
        needle = handle.strip().casefold()
        for site in sites or SITE_IDS:
            for role in TEAM_ROLES:
                own = clean_env(team_identity_env(site, role)).casefold()
                if own and (needle == own or needle.startswith(own + "@")):
                    return site
        return None

    def resolve_phone_identity(self, client, property_id):
        handle = self.phone_identity_handle(property_id)
        if not handle:
            raise ProviderNotConfigured("Set INKBOX_IDENTITY_DISPATCH to the identity that owns the dispatch line's phone number.")
        return client.get_identity(handle)

    @staticmethod
    def _gate(recipient: str):
        if not external_messages_allowed():
            raise ProviderNotConfigured("External messages are disabled. Enable STEWARD_ALLOW_EXTERNAL_MESSAGES and configure INKBOX_ALLOWED_RECIPIENTS before sending.")
        allowlist = allowed_recipients()
        if not recipient or recipient.strip().casefold() not in allowlist:
            raise ValueError("Every recipient must be explicitly listed in INKBOX_ALLOWED_RECIPIENTS.")
        if not (PHONE_RE.match(recipient.strip()) or EMAIL_RE.match(recipient.strip())):
            raise ValueError("Recipient must be a phone number (^+?[0-9]{7,15}$) or an email address.")

    def send_sms(self, property_id: str, to: str, body: str, conversation_id: str | None = None, idempotency_key: str | None = None) -> dict:
        """Send an SMS from the property identity's provisioned number. Returns {id, conversationId, raw}."""
        self._gate(to)
        with self.client() as client:
            identity = self.resolve_phone_identity(client, property_id)
            if identity.phone_number is None:
                raise ProviderNotConfigured(f"Inkbox identity {identity.agent_handle} has no provisioned phone number; SMS is unavailable. Set INKBOX_PHONE_IDENTITY to the handle that owns the number.")
            kwargs = dict(text=body[:1600], idempotency_key=idempotency_key)
            if conversation_id:
                kwargs["conversation_id"] = conversation_id
            else:
                kwargs["to"] = to
            message = identity.send_text(**kwargs)
            raw = self.serialize(message)
            return {"id": str(message.id), "conversationId": str(message.conversation_id) if message.conversation_id else None, "raw": raw}

    @staticmethod
    def client_with(api_key: str):
        """An SDK client for an identity-scoped key: an agent emails from its own identity with its own key."""
        try:
            from inkbox import Inkbox
        except ImportError:
            raise ProviderNotConfigured("Inkbox SDK is missing. Install backend requirements before enabling this integration.")
        return Inkbox(api_key=api_key, base_url=inkbox_base_url())

    @staticmethod
    def attachment(item: dict) -> dict:
        """One SDK attachment: {filename, content_type, content_base64, content_id?}. A content_id renders the (image)
        attachment inline in the HTML body as cid:<content_id>; other keys (sizes kept for the record) are dropped."""
        if not item.get("filename") or not item.get("content_type") or not item.get("content_base64"):
            raise ValueError("Each attachment needs filename, content_type and content_base64.")
        out = {"filename": str(item["filename"])[:180], "content_type": str(item["content_type"]), "content_base64": item["content_base64"]}
        if item.get("content_id"):
            out["content_id"] = str(item["content_id"])[:120]
        return out

    def send_email(self, property_id: str, to: str, subject: str, body: str, reference: str, in_reply_to: str | None = None,
                   html: str | None = None, attachments: list[dict] | None = None, sender_handle: str | None = None,
                   api_key: str | None = None, idempotency_key: str | None = None) -> dict:
        """Send an email with the work-item reference in the subject. Returns {id, threadId, messageId, raw}.

        `html` goes out as `body_html` (the plain `body` stays the text part) and `attachments` as Inkbox attachments
        (`attachment()` shape). `sender_handle` sends from that agent identity (with its identity-scoped `api_key` when
        given) instead of the site's Field Technician, the way agent document email picks its sender."""
        self._gate(to)
        if reference and reference not in subject:
            subject = f"[{reference}] {subject}"
        with (self.client_with(api_key) if api_key else self.client()) as client:
            identity = client.get_identity(sender_handle) if sender_handle else self.resolve_identity(client, property_id)
            if identity.email_address is None:
                raise ProviderNotConfigured(f"Inkbox identity {identity.agent_handle} has no mailbox; email is unavailable.")
            kwargs = dict(to=[to], subject=subject[:300], body_text=body, in_reply_to_message_id=in_reply_to)
            if html:
                kwargs["body_html"] = html
            if attachments:
                kwargs["attachments"] = [self.attachment(item) for item in attachments]
            if idempotency_key:
                kwargs["idempotency_key"] = idempotency_key
            message = identity.send_email(**kwargs)
            return {"id": str(message.id), "threadId": str(message.thread_id) if message.thread_id else None,
                    "messageId": message.message_id, "raw": self.serialize(message)}

    def send_imessage(self, property_id: str, to: str, body: str, conversation_id: str | None = None) -> dict:
        self._gate(to)
        with self.client() as client:
            identity = self.resolve_phone_identity(client, property_id)
            if not identity.imessage_enabled:
                raise ProviderNotConfigured(f"Inkbox identity {identity.agent_handle} does not have iMessage enabled.")
            kwargs = dict(text=body[:1600])
            if conversation_id:
                kwargs["conversation_id"] = conversation_id
            else:
                kwargs["to"] = [to]
            message = identity.send_imessage(**kwargs)
            raw = self.serialize(message)
            return {"id": str(getattr(message, "id", raw.get("id", ""))), "conversationId": str(getattr(message, "conversation_id", "") or "") or None, "raw": raw}

    def place_call(self, property_id: str, to: str, script: str) -> dict:
        """Place a hosted-agent voice call (Inkbox Voice AI reads `script` as its task brief)."""
        self._gate(to)
        with self.client() as client:
            identity = self.resolve_phone_identity(client, property_id)
            if identity.phone_number is None:
                raise ProviderNotConfigured(f"Inkbox identity {identity.agent_handle} has no provisioned phone number; voice calls need a dedicated number. Set INKBOX_PHONE_IDENTITY to the handle that owns it.")
            call = identity.place_call(to_number=to, mode="hosted_agent", reason=script[:2000], on_voicemail="leave_message",
                                       voicemail_message=script[:1000])
            return {"id": str(call.id), "status": call.status, "raw": self.serialize(call)}

    def ensure_webhook(self, property_id: str, public_base_url: str, inbound_secret: str) -> dict:
        """Create (or reuse) the webhook subscription that delivers inbound texts, emails and iMessages to /api/inbound/inkbox."""
        if not public_base_url.startswith("https://"):
            raise ValueError("STEWARD_PUBLIC_BASE_URL must be an https:// tunnel URL for Inkbox webhooks.")
        url = public_base_url.rstrip("/") + "/api/inbound/inkbox"
        events = ["text.received", "message.received", "imessage.received", "call.ended",
                  "a2a.task.created", "a2a.task.message", "a2a.task.canceled", "a2a.sent_task.updated"]
        with self.client() as client:
            identity = self.resolve_identity(client, property_id)
            for existing in client.webhooks.subscriptions.list(agent_identity_id=identity.id):
                if getattr(existing, "url", None) == url:
                    return {"id": str(existing.id), "url": url, "created": False, "signingKey": None}
            created = client.webhooks.subscriptions.create(url=url, event_types=events, agent_identity_id=identity.id, auth_token=inbound_secret)
            return {"id": str(created.id), "url": url, "created": True, "signingKey": getattr(created, "signing_key", None)}

    @staticmethod
    def verify_signature(raw: bytes, headers) -> bool | None:
        """True/False when INKBOX_WEBHOOK_SIGNING_KEY is set; None when no signing key is configured."""
        # One signing key per Inkbox identity: try the shared key and every per-agent key (INKBOX_WEBHOOK_SIGNING_KEY_<AGENT>).
        secrets_ = [v for k, v in os.environ.items()
                    if (k == "INKBOX_WEBHOOK_SIGNING_KEY" or k.startswith("INKBOX_WEBHOOK_SIGNING_KEY_")) and v and not v.startswith("#")]
        if not secrets_:
            return None
        from inkbox.signing_keys import verify_webhook
        plain = dict(headers)
        for secret in dict.fromkeys(secrets_):
            try:
                if verify_webhook(payload=raw, headers=plain, secret=secret):
                    return True
            except Exception:  # noqa: BLE001 - a malformed header for one key must not hide a match on another
                continue
        return False

    @staticmethod
    def parse_webhook(payload: dict) -> dict | None:
        """Normalise an Inkbox webhook (text.received / message.received / imessage.received) to the inbound shape.

        Returns None for lifecycle events (sent/delivered/failed) that carry no inbound content.
        """
        event_type = str(payload.get("event_type", ""))
        data = payload.get("data") or {}
        event_id = str(payload.get("id") or "")
        # Receiving identity handles (per-site identities) plus the local number / mailbox, so the inbound
        # router can scope "sender + open items" to the site that owns the identity.
        handles = [item.get("agent_handle") for item in (data.get("agent_identities") or []) if isinstance(item, dict) and item.get("agent_handle")]
        if event_type == "text.received":
            message = data.get("text_message") or {}
            media = [dict(url=m.get("url"), contentType=m.get("content_type")) for m in (message.get("media") or []) if m.get("url")]
            return dict(provider="inkbox", eventId=event_id, channel="sms", providerMessageId=str(message.get("id") or ""),
                        threadRef=str(message.get("conversation_id") or "") or None, sender=message.get("remote_phone_number") or "",
                        subject="", body=message.get("text") or "", media=media, receivedAt=message.get("created_at") or payload.get("timestamp"),
                        identityHandles=handles, localAddress=message.get("local_phone_number") or data.get("recipient_phone_number"))
        if event_type == "message.received":
            message = data.get("message") or {}
            to_handles = [item.get("agent_handle") for item in (data.get("agent_identities") or [])
                          if isinstance(item, dict) and item.get("bucket") in ("to", "cc") and item.get("agent_handle")]
            return dict(provider="inkbox", eventId=event_id, channel="email", providerMessageId=str(message.get("id") or ""),
                        threadRef=str(message.get("thread_id") or "") or None, sender=message.get("from_address") or "",
                        subject=message.get("subject") or "", body=message.get("body") or message.get("snippet") or "", media=[],
                        receivedAt=message.get("created_at") or payload.get("timestamp"), rfcMessageId=message.get("message_id"),
                        hasAttachments=bool(message.get("has_attachments")), mailbox=message.get("email_address"),
                        identityHandles=to_handles or handles, localAddress=message.get("email_address") or (message.get("to_addresses") or [None])[0])
        if event_type == "call.ended":
            call = data.get("call") or {}
            transcript = data.get("transcript") or {}
            lines = []
            for entry in transcript.get("entries") or []:
                if isinstance(entry, dict) and "marker" not in entry:
                    speaker = entry.get("party") or entry.get("speaker") or "speaker"
                    lines.append(f"{speaker}: {entry.get('text') or entry.get('content') or ''}")
            outcome = data.get("outcome")
            body = (f"Call outcome: {outcome}. " if outcome else "") + "\n".join(lines)
            return dict(provider="inkbox", eventId=event_id, channel="call", providerMessageId=str(call.get("id") or ""),
                        threadRef=str(call.get("id") or "") or None, sender=call.get("remote_phone_number") or "",
                        subject=f"call {outcome or call.get('status') or 'ended'}", body=body, media=[],
                        receivedAt=call.get("ended_at") or payload.get("timestamp"), identityHandles=handles,
                        localAddress=call.get("local_phone_number"), callOutcome=outcome, transcriptUrl=data.get("transcript_url"),
                        recordingUrl=call.get("recording_url") or data.get("recording_url"),
                        transcriptEntries=[e for e in (transcript.get("entries") or []) if isinstance(e, dict)],
                        actionItems=[item.get("action") for item in (data.get("post_call_action_items") or []) if isinstance(item, dict)])
        if event_type == "imessage.received":
            message = data.get("message") or {}
            media = [dict(url=m.get("url"), contentType=m.get("content_type")) for m in (message.get("media") or []) if isinstance(m, dict) and m.get("url")]
            return dict(provider="inkbox", eventId=event_id, channel="imessage", providerMessageId=str(message.get("id") or ""),
                        threadRef=str(message.get("conversation_id") or "") or None, sender=message.get("sender_number") or message.get("remote_number") or "",
                        subject="", body=message.get("content") or "", media=media, receivedAt=message.get("created_at") or payload.get("timestamp"),
                        identityHandles=handles, localAddress=None)
        return None

    def fetch_media(self, url: str, limit: int = 10 * 1024 * 1024) -> bytes | None:
        """Best-effort download of MMS/iMessage media referenced by a webhook. Returns None on any failure."""
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                response = client.get(url, headers={"X-API-Key": clean_env("INKBOX_API_KEY")})
                if response.status_code != 200 or len(response.content) > limit:
                    return None
                return response.content
        except Exception:
            return None


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
