"""Point Steward's Inkbox webhooks at the Supabase inbox (Edge Function inkbox-inbox) instead of the tunnel. Prints no secrets.

Usage (repo root, backend venv):
  backend/.venv/bin/python -I scripts/inkbox_use_supabase_inbox.py            # dry run: show the plan, change nothing
  backend/.venv/bin/python -I scripts/inkbox_use_supabase_inbox.py --apply    # add the function subscription, then remove the tunnel one
  backend/.venv/bin/python -I scripts/inkbox_use_supabase_inbox.py --apply --keep-tunnel   # add only (both deliver; the queue dedupes)
  backend/.venv/bin/python -I scripts/inkbox_use_supabase_inbox.py --revert --apply   # back to the tunnel: re-add it, then remove the function one

For every identity in AGENTS: the function subscription `{SUPABASE_URL}/functions/v1/inkbox-inbox?agent=<handle>` is created
first (same event types, no auth_token: the function verifies the per-identity HMAC signature), and only after it exists is
the tunnel subscription (`{STEWARD_PUBLIC_BASE_URL}/api/inbound/inkbox...`) deleted, so no identity is ever without a
delivery path. If Inkbox mints a new signing key for an identity it is written to .env and the run reminds you to push the
signing keys to the function again (`supabase secrets set`), because the function must know every key.
Prerequisites: the backend restarted with the Supabase drainer running (it replays the queue every 5 s), migrations
0006 applied and the function deployed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inkbox_setup import client, load_env, set_env  # noqa: E402
from inkbox_webhooks import AGENTS, EVENTS  # noqa: E402

FUNCTION_PATH = "/functions/v1/inkbox-inbox"
TUNNEL_PATH = "/api/inbound/inkbox"


def function_url(supabase_url: str, handle: str) -> str:
    return f"{supabase_url.rstrip('/')}{FUNCTION_PATH}?agent={handle}"


def is_function(url: str, supabase_url: str) -> bool:
    return bool(supabase_url) and url.startswith(supabase_url.rstrip("/") + FUNCTION_PATH)


def is_tunnel(url: str, tunnel_base: str) -> bool:
    return bool(tunnel_base) and url.startswith(tunnel_base.rstrip("/") + TUNNEL_PATH)


def plan(subscriptions: list[dict], handle: str, supabase_url: str, tunnel_base: str, revert: bool = False, keep_tunnel: bool = False) -> dict:
    """What to create and delete for one identity, given its subscriptions [{id, url}] (pure; unit tested)."""
    target = function_url(supabase_url, handle)
    if revert:
        has_tunnel = any(is_tunnel(s["url"], tunnel_base) for s in subscriptions)
        return dict(create=None if has_tunnel else f"{tunnel_base.rstrip('/')}{TUNNEL_PATH}?agent={handle}",
                    delete=[s["id"] for s in subscriptions if is_function(s["url"], supabase_url)])
    has_function = any(is_function(s["url"], supabase_url) for s in subscriptions)
    return dict(create=None if has_function else target,
                delete=[] if keep_tunnel else [s["id"] for s in subscriptions if is_tunnel(s["url"], tunnel_base)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    parser.add_argument("--keep-tunnel", action="store_true", help="add the function subscription but keep the tunnel one")
    parser.add_argument("--revert", action="store_true", help="return to the tunnel subscription")
    args = parser.parse_args()
    env = load_env()
    supabase_url = env.get("SUPABASE_URL", "").rstrip("/")
    tunnel_base = env.get("STEWARD_PUBLIC_BASE_URL", "").rstrip("/")
    if not supabase_url.startswith("https://"):
        sys.exit("SUPABASE_URL must be the project's https URL")
    if args.revert and not tunnel_base.startswith("https://"):
        sys.exit("--revert needs STEWARD_PUBLIC_BASE_URL (the https tunnel)")
    new_keys = 0
    with client(env) as ib:
        # The SDK's agent_identity_id filter on list() returns nothing here, so list once and filter locally.
        all_subs = list(ib.webhooks.subscriptions.list())
        for var in AGENTS:
            handle = env.get(var)
            if not handle:
                print(f"{var}: empty, skipped")
                continue
            identity = ib.get_identity(handle)
            subs = [dict(id=str(s.id), url=str(getattr(s, "url", "") or "")) for s in all_subs
                    if str(getattr(s, "agent_identity_id", "")) == str(identity.id)]
            todo = plan(subs, handle, supabase_url, tunnel_base, revert=args.revert, keep_tunnel=args.keep_tunnel)
            summary = f"{handle}: create {'nothing (already present)' if not todo['create'] else todo['create'].split('?')[0]}; delete {len(todo['delete'])}"
            if not args.apply:
                print("[dry run] " + summary)
                continue
            if todo["create"]:
                try:
                    created = ib.webhooks.subscriptions.create(url=todo["create"], event_types=EVENTS, agent_identity_id=identity.id)
                except Exception as error:  # noqa: BLE001
                    print(f"{handle}: create failed ({type(error).__name__}: {str(error)[:160]}); nothing deleted")
                    continue
                key = getattr(created, "signing_key", None)
                if key:
                    set_env(f"INKBOX_WEBHOOK_SIGNING_KEY_{var.removeprefix('INKBOX_IDENTITY_')}", key)
                    new_keys += 1
            for sub_id in todo["delete"]:
                try:
                    ib.webhooks.subscriptions.delete(sub_id, scope="identity")
                except Exception as error:  # noqa: BLE001
                    print(f"{handle}: delete {sub_id} failed ({type(error).__name__})")
            print(summary + " - done")
    if new_keys:
        print(f"{new_keys} new signing key(s) written to .env. Push them to the function before relying on it:\n"
              "  (write the INKBOX_WEBHOOK_SIGNING_KEY* lines to a temporary env file) && supabase secrets set --env-file <file> --project-ref $SUPABASE_PROJECT_REF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
