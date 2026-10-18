"""Agent identities in Supabase Auth: one user per agent, an access token per agent for RLS-checked writes.

Users are `agent+<id>@steward.invalid` (the .invalid TLD can never receive mail), created once by
backend/scripts/supabase_agents.py with the secret key; their random passwords live only in the root .env as
STEWARD_AGENT_PASSWORD_<SUFFIX> (OPERATOR, DIRECTOR, MYER_MANAGER, ...). The backend signs each agent in with the
password grant, caches the access token until a minute before it expires, refreshes it with the refresh token, and backs
off after a failure, so monthly active users stay at the number of agents (14) and the Auth rate limits are never approached.
The custom access token hook (0003) adds agent_id, agent_level, site_id and agent_role to every token.
"""
from __future__ import annotations

import base64
import json
import threading
import time

from .supa_authority import AGENT_IDS
from .providers import clean_env
from .supa_client import Supa, SupabaseError

BACKOFF_SECONDS = 60
SKEW_SECONDS = 60


def agent_email(agent_id: str) -> str:
    return f"agent+{agent_id}@steward.invalid"


def password_env(agent_id: str) -> str:
    return "STEWARD_AGENT_PASSWORD_" + agent_id.upper().replace("-", "_")


def agent_password(agent_id: str) -> str:
    return clean_env(password_env(agent_id))


def decode_claims(token: str) -> dict:
    """The JWT payload, unverified (display and tests only; Postgres and Auth verify tokens)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


class AgentTokens:
    def __init__(self, supa: Supa, clock=time.time, on_event=None):
        self.supa = supa
        self.clock = clock
        self.on_event = on_event or (lambda title, detail: None)
        self.lock = threading.Lock()
        self.agent_locks = {agent: threading.Lock() for agent in AGENT_IDS}
        self.cache: dict[str, dict] = {}
        self.failed_until: dict[str, float] = {}
        self.logins = 0
        self.refreshes = 0

    @property
    def enabled(self) -> bool:
        """Agent tokens are used when the publishable key and at least one agent password are configured."""
        return bool(self.supa.configured and self.supa.anon and any(agent_password(a) for a in AGENT_IDS))

    def token(self, agent_id: str) -> str | None:
        """A valid access token for `agent_id`, or None (not configured, or a recent failure is backing off)."""
        password = agent_password(agent_id)
        if not password or not self.supa.configured:
            return None
        now = self.clock()
        with self.agent_locks.get(agent_id) or self.lock:
            cached = self.cache.get(agent_id)
            if cached and cached["expires_at"] - SKEW_SECONDS > now:
                return cached["access_token"]
            if self.failed_until.get(agent_id, 0) > now:
                return None
            try:
                if cached and cached.get("refresh_token"):
                    try:
                        session = self.supa.refresh_grant(cached["refresh_token"])
                        self.refreshes += 1
                    except SupabaseError:
                        session = self.supa.password_grant(agent_email(agent_id), password)
                        self.logins += 1
                else:
                    session = self.supa.password_grant(agent_email(agent_id), password)
                    self.logins += 1
            except Exception as error:
                self.failed_until[agent_id] = now + BACKOFF_SECONDS
                self.on_event(f"Supabase sign-in failed for {agent_id}", f"{type(error).__name__}: {str(error)[:200]}; retrying in {BACKOFF_SECONDS} s.")
                return None
            expires_at = float(session.get("expires_at") or (now + float(session.get("expires_in") or 3600)))
            self.cache[agent_id] = dict(access_token=session["access_token"], refresh_token=session.get("refresh_token"), expires_at=expires_at)
            self.failed_until.pop(agent_id, None)
            return session["access_token"]

    def claims(self, agent_id: str) -> dict:
        token = self.token(agent_id)
        return decode_claims(token) if token else {}

    def status(self) -> dict:
        now = self.clock()
        with self.lock:
            cached = {agent: max(0, int(entry["expires_at"] - now)) for agent, entry in self.cache.items()}
            backing_off = sorted(agent for agent, until in self.failed_until.items() if until > now)
        return dict(enabled=self.enabled, configured=sorted(a for a in AGENT_IDS if agent_password(a)), cachedSecondsLeft=cached,
                    backingOff=backing_off, logins=self.logins, refreshes=self.refreshes)
