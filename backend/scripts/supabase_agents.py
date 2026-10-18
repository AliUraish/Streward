#!/usr/bin/env python
"""Create one Supabase Auth user per agent and link it to public.agents (run once; safe to re-run).

Usage: backend/.venv/bin/python backend/scripts/supabase_agents.py [--verify] [--data-dir backend/data]

- Users are agent+<id>@steward.invalid, created through the Auth admin API with the secret key (email confirmed, so no
  mail is ever sent). Each random password is written only to the root .env as STEWARD_AGENT_PASSWORD_<SUFFIX>;
  nothing secret is printed. An existing user whose password is missing locally gets a fresh one.
- public.agents.auth_user_id is set for each agent; the backend's Ed25519 public key is registered as the trusted
  ledger key; the Edge Function daily cap is written to steward.settings.
- --verify signs each agent in with the password grant and prints the agent claims the access token hook added.
Requires SUPABASE_URL, SUPABASE_SERVICE_KEY and the publishable key (NEXT_PUBLIC_SUPABASE_ANON_KEY) in the root .env.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env", override=True)

from src.env import env, sanitize_environment  # noqa: E402

sanitize_environment()

from src.supa_authority import AGENT_IDS, agent_site, role_of  # noqa: E402
from src.signing import Signer  # noqa: E402
from src.supa_auth import agent_email, decode_claims, password_env  # noqa: E402
from src.supa_budget import Budget  # noqa: E402
from src.supa_client import Supa, SupabaseError  # noqa: E402
from supabase_env import set_env_values  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="sign each agent in and show its claims")
    parser.add_argument("--data-dir", default=env("STEWARD_DATA_DIR", str(ROOT / "data")))
    args = parser.parse_args()
    supa = Supa()
    if not supa.configured or not supa.anon:
        print("SUPABASE_URL, SUPABASE_SERVICE_KEY and the publishable key are required; nothing done.")
        return 2
    existing = {u.get("email"): u for u in supa.admin_users(per_page=200)}
    new_passwords: dict[str, str] = {}
    created = updated = linked = 0
    for agent in AGENT_IDS:
        email = agent_email(agent)
        password = (os.getenv(password_env(agent)) or "").strip()
        fresh = not password
        if fresh:
            password = secrets.token_urlsafe(32)
            new_passwords[password_env(agent)] = password
        user = existing.get(email)
        meta = {"agent_id": agent, "steward": True}
        if user is None:
            user = supa.admin_create_user(email, password, meta)
            created += 1
            state = "created"
        elif fresh:
            supa.admin_update_user(user["id"], password=password, app_metadata=meta)
            updated += 1
            state = "password reset"
        else:
            state = "exists"
        supa.patch("agents", {"id": agent}, {"auth_user_id": user["id"]})
        linked += 1
        print(f"{agent:20s} {state:15s} {'(new password written to the root .env)' if fresh else '(password already in .env)'}")
    if new_passwords:
        set_env_values(new_passwords)
    extras = []
    try:
        signer = Signer(Path(args.data_dir))
        supa.rpc("steward_trust_signing_key", {"p_public_key": signer.public_key_b64, "p_label": "steward backend"})
        extras.append("trusted signing key registered")
    except SupabaseError as error:
        extras.append(f"signing key not registered yet ({error.status}; apply 0004_ledger.sql and re-run)")
    try:
        supa.rpc("steward_put_setting", {"p_key": "edge_calls_day_cap", "p_value": str(Budget(None).cap("edge_calls_day"))})
        extras.append(f"edge cap {Budget(None).cap('edge_calls_day')} pushed")
    except SupabaseError as error:
        extras.append(f"edge cap not pushed yet ({error.status}; apply 0006_inbox_queue.sql and re-run)")
    print(f"users created {created}, passwords reset {updated}, agents linked {linked}; " + "; ".join(extras) + ".")
    if args.verify:
        for name, value in new_passwords.items():
            os.environ[name] = value
        failures = 0
        for agent in AGENT_IDS:
            try:
                session = supa.password_grant(agent_email(agent), os.environ[password_env(agent)])
            except SupabaseError as error:
                failures += 1
                print(f"{agent:20s} sign-in FAILED: {error.status} {error.message[:120]}")
                continue
            claims = decode_claims(session["access_token"])
            expected = (agent, role_of(agent), agent_site(agent))
            got = (claims.get("agent_id"), claims.get("agent_role"), claims.get("site_id"))
            ok = got == expected
            failures += 0 if ok else 1
            print(f"{agent:20s} claims agent_id={got[0]} agent_role={got[1]} site_id={got[2]} agent_level={claims.get('agent_level')} "
                  f"{'ok' if ok else 'MISMATCH (is the access token hook enabled?)'}")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
