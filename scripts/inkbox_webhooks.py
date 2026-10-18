"""Subscribe Steward's Inkbox identities to deliver webhooks to the tunnel. Prints no secrets.

Usage: backend/.venv/bin/python -I scripts/inkbox_webhooks.py
Uses STEWARD_PUBLIC_BASE_URL (https tunnel) and the three agent identity handles from .env.
Subscriptions are created without auth_token (that path needs an initialized org vault); the backend
verifies the per-identity HMAC signature instead. Inkbox returns one signing key per identity, once;
it is written to .env (INKBOX_WEBHOOK_SIGNING_KEY for the first, INKBOX_WEBHOOK_SIGNING_KEY_<AGENT> for all).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inkbox_setup import client, load_env, set_env  # noqa: E402

EVENTS = ["text.received", "message.received", "imessage.received", "call.ended",
          "a2a.task.created", "a2a.task.message", "a2a.task.canceled", "a2a.sent_task.updated"]
AGENTS = ["INKBOX_IDENTITY_DISPATCH", "INKBOX_IDENTITY_DIRECTOR",
          "INKBOX_IDENTITY_MYER_MANAGER", "INKBOX_IDENTITY_MYER_ENGINEER", "INKBOX_IDENTITY_MYER_COMPLIANCE", "INKBOX_IDENTITY_MYER_TECHNICIAN",
          "INKBOX_IDENTITY_BRISTOL_MANAGER", "INKBOX_IDENTITY_BRISTOL_ENGINEER", "INKBOX_IDENTITY_BRISTOL_COMPLIANCE", "INKBOX_IDENTITY_BRISTOL_TECHNICIAN",
          "INKBOX_IDENTITY_TOMIOKA_MANAGER", "INKBOX_IDENTITY_TOMIOKA_ENGINEER", "INKBOX_IDENTITY_TOMIOKA_COMPLIANCE", "INKBOX_IDENTITY_TOMIOKA_TECHNICIAN"]


def main() -> int:
    env = load_env()
    base = env.get("STEWARD_PUBLIC_BASE_URL", "")
    if not base.startswith("https://"):
        sys.exit("STEWARD_PUBLIC_BASE_URL must be the https tunnel URL (run scripts/inkbox_tunnel.py first)")
    url = base.rstrip("/") + "/api/inbound/inkbox"
    with client(env) as ib:
        for var in AGENTS:
            handle = env.get(var)
            if not handle:
                print(f"{var}: empty, skipped")
                continue
            ident = ib.get_identity(handle)
            # Inkbox allows one subscription per URL and event set across the org, so each identity gets its own URL tag.
            agent_url = f"{url}?agent={handle}"
            subs = list(ib.webhooks.subscriptions.list(agent_identity_id=ident.id))
            if any(getattr(s_, "url", None) in (url, agent_url) for s_ in subs):
                print(f"{handle}: subscription already present")
                continue
            try:
                created = ib.webhooks.subscriptions.create(url=agent_url, event_types=EVENTS, agent_identity_id=ident.id)
            except Exception as e:  # noqa: BLE001
                print(f"{handle}: create failed: {type(e).__name__}: {str(e)[:160]}")
                continue
            key = getattr(created, "signing_key", None)
            print(f"{handle}: subscribed {created.id}" + (" (signing key saved)" if key else " (identity already had a signing key)"))
            if key:
                set_env(f"INKBOX_WEBHOOK_SIGNING_KEY_{var.removeprefix('INKBOX_IDENTITY_')}", key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
