"""Inkbox live setup for Steward's four agents. Never prints secrets.

Usage (from repo root, with backend venv):
  backend/.venv/bin/python -I scripts/inkbox_setup.py status
  backend/.venv/bin/python -I scripts/inkbox_setup.py create [--phone-on runner]
  backend/.venv/bin/python -I scripts/inkbox_setup.py keys      # mint identity-scoped A2A keys, write to .env
  backend/.venv/bin/python -I scripts/inkbox_setup.py skills    # enable A2A and advertise skills
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

AGENTS = {
    "INKBOX_IDENTITY_ATLAS": ("steward-atlas", "Atlas, Steward portfolio coordinator (AI)", [
        ("clear-site-for-restart", "Clear a site for restart", "Delegates fact resolution to the site agent, checks every attestation, asks the owner on out-of-range readings."),
        ("cross-site-check", "Cross-site check", "Asks other site agents to verify a serial or reading after an anomaly."),
    ]),
    "INKBOX_IDENTITY_WARDEN_HARBOR_WORKS": ("steward-warden-harbor", "Warden, Steward site agent for Harbor Works (AI)", [
        ("resolve-fact", "Resolve a fact", "Returns a fresh signed fact for an asset attribute or opens a work item."),
        ("attest-evidence", "Attest evidence", "Verifies submitted evidence against tag, place, spec, time and hash, then signs."),
    ]),
    "INKBOX_IDENTITY_RUNNER": ("steward-runner", "Runner, Steward field agent (AI)", [
        ("dispatch-technician", "Dispatch a technician", "Sends a task card to a contractor by SMS, email or call."),
        ("collect-evidence", "Collect evidence", "Receives photos and readings and hands them to the site agent."),
    ]),
}


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v[:1] in "\"'" and v[-1:] == v[:1]:
            v = v[1:-1]
        v = v.split(" #", 1)[0].strip()
        if v.startswith("#"):
            v = ""
        values[k] = v
    return values


def set_env(key: str, value: str) -> None:
    lines = ENV.read_text().splitlines()
    done = False
    for i, line in enumerate(lines):
        if re.match(rf"^\s*(export\s+)?{re.escape(key)}\s*=", line):
            lines[i] = f"{key}={value}"
            done = True
    if not done:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")


def client(env: dict[str, str]):
    from inkbox import Inkbox
    key = env.get("INKBOX_API_KEY", "")
    if not key or key.startswith("<") or "..." in key:
        sys.exit("INKBOX_API_KEY is missing or a placeholder in .env")
    kwargs = {"api_key": key}
    if env.get("INKBOX_BASE_URL", "").startswith("https://"):
        kwargs["base_url"] = env["INKBOX_BASE_URL"]
    return Inkbox(**kwargs)


def cmd_status(env):
    with client(env) as ib:
        ids = ib.list_identities()
        print(f"key ok: {len(ids)} identit{'y' if len(ids)==1 else 'ies'} in org")
        for s in ids:
            handle = getattr(s, "agent_handle", None) or getattr(s, "handle", None)
            email = getattr(s, "email_address", None)
            print(f"  - {handle}  {email or ''}")
        for var, (handle, _, _) in AGENTS.items():
            print(f"{var} = {env.get(var) or '(empty)'}")


def cmd_create(env, phone_on: str | None):
    with client(env) as ib:
        existing = {}
        for s in ib.list_identities():
            h = getattr(s, "agent_handle", None) or getattr(s, "handle", None)
            existing[h] = s
        for var, (default_handle, display, _) in AGENTS.items():
            handle = env.get(var) or default_handle
            if handle in existing:
                print(f"{var}: {handle} exists")
            else:
                kwargs = {"display_name": display}
                if phone_on and var.endswith(phone_on.upper()):
                    from inkbox.identities.types import IdentityPhoneNumberCreateOptions
                    kwargs["phone_number"] = IdentityPhoneNumberCreateOptions(type="local", state="CA")
                try:
                    ident = ib.create_identity(handle, **kwargs)
                    print(f"{var}: created {ident.agent_handle} ({ident.email_address})" + (" with phone" if "phone_number" in kwargs else ""))
                except Exception as e:  # noqa: BLE001
                    print(f"{var}: create failed for {handle}: {type(e).__name__}: {str(e)[:200]}")
                    continue
            set_env(var, handle)
        print("handles written to .env")


def cmd_skills(env):
    from inkbox.a2a.types import A2ASkill
    with client(env) as ib:
        for var, (default_handle, _, skills) in AGENTS.items():
            handle = env.get(var) or default_handle
            try:
                ident = ib.get_identity(handle)
                ident.a2a_enable()
                ident.a2a_set_skills([A2ASkill(id=i, name=n, description=d, tags=["steward"]) for i, n, d in skills])
                st = ident.a2a_settings()
                print(f"{handle}: a2a enabled={st.enabled} card={st.card_url} skills={len(st.skills or [])}")
            except Exception as e:  # noqa: BLE001
                print(f"{handle}: skills failed: {type(e).__name__}: {str(e)[:200]}")


def cmd_keys(env):
    with client(env) as ib:
        res = ib.api_keys
        create = getattr(res, "create", None)
        if create is None:
            sys.exit("SDK api_keys resource has no create(); mint identity-scoped keys in the Inkbox console instead")
        for var, (default_handle, _, _) in AGENTS.items():
            key_var = var.replace("INKBOX_IDENTITY_", "INKBOX_AGENT_KEY_")
            if env.get(key_var):
                print(f"{key_var}: already set")
                continue
            handle = env.get(var) or default_handle
            try:
                ident = ib.get_identity(handle)
                created = create(label=f"steward-a2a-{handle}", description="Steward A2A identity-scoped key", scoped_identity_id=ident.id)
                secret = getattr(created, "secret", None) or getattr(created, "key", None) or getattr(created, "api_key", None)
                if not secret:
                    print(f"{key_var}: created but no secret field returned; fields: {list(vars(created))}")
                    continue
                set_env(key_var, secret)
                print(f"{key_var}: minted and written to .env")
            except Exception as e:  # noqa: BLE001
                print(f"{key_var}: failed: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    env = load_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        cmd_status(env)
    elif cmd == "create":
        phone = None
        if "--phone-on" in sys.argv:
            phone = sys.argv[sys.argv.index("--phone-on") + 1]
        cmd_create(env, phone)
    elif cmd == "skills":
        cmd_skills(env)
    elif cmd == "keys":
        cmd_keys(env)
    else:
        sys.exit(__doc__)
