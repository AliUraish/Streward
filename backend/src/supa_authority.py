"""Who writes each mirrored row to Supabase: an agent with its own access token (so RLS applies), or the system.

MATRIX mirrors `steward.authority` in supabase/migrations/0003_authority.sql row for row (a test parses the migration
and compares), so the backend never asks Postgres for a write its policies would refuse unless the two genuinely
disagree, which is then recorded as a refusal, not hidden.

Authorship (author_for) is decided from the row itself, refined by the request's acting agent when that agent may make
the write:
- rows that name their author: telemetry/memories (agent_id), eye_frames (actor), viewer_commands (issued_by),
  notifications (sender), conversations (convener), maintenance_windows (approved_by, else proposed_by), issues (the
  last history entry's `by`), findings (inspectedBy), work_items (requester), subscriptions (requester);
- attestations and facts from people's evidence are the site engineer's (the verifier attests on the engineer's
  behalf); machine readings (sensor feed, patrols, scans) and seeds are system rows;
- obligations are the site compliance officer's; dispatches the site technician's;
- changes, crew members and the roster are system rows (service key).
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager

from .agents import DIRECTOR, OPERATOR, ROLES, TEAM_PREFIX
from .agents import display_name as _display_name
from .sites import SITE_IDS

# Mirrors steward.authority (0003_authority.sql). site_kind: one | many | none.
MATRIX: dict[str, dict] = {
    "facts":               dict(site_col="property_id", site_kind="one",  writers=("operator", "engineer"), bind=None, append_only=False),
    "attestations":        dict(site_col="property_id", site_kind="one",  writers=("operator", "engineer"), bind=None, append_only=True),
    "work_items":          dict(site_col="property_id", site_kind="one",  writers=("operator", "director", "manager", "engineer", "technician"), bind=None, append_only=False),
    "dispatches":          dict(site_col="property_id", site_kind="one",  writers=("operator", "engineer", "technician"), bind=None, append_only=False),
    "changes":             dict(site_col="property_id", site_kind="one",  writers=(), bind=None, append_only=False),
    "subscriptions":       dict(site_col="property_id", site_kind="one",  writers=("operator", "engineer"), bind=None, append_only=False),
    "crew_members":        dict(site_col="site_id",     site_kind="one",  writers=("operator", "manager"), bind=None, append_only=False),
    "obligations":         dict(site_col="site_id",     site_kind="one",  writers=("compliance",), bind=None, append_only=False),
    "issues":              dict(site_col="site_id",     site_kind="one",  writers=("operator", "director", "manager", "engineer", "compliance"), bind=None, append_only=False),
    "conversations":       dict(site_col="site_ids",    site_kind="many", writers=("operator", "director", "manager", "engineer", "compliance", "technician"), bind="convener", append_only=False),
    "viewer_commands":     dict(site_col="site_id",     site_kind="one",  writers=("operator", "director", "manager", "engineer", "compliance"), bind="issued_by", append_only=False),
    "memories":            dict(site_col="site_id",     site_kind="one",  writers=("operator", "director", "manager", "engineer", "compliance", "technician"), bind="agent_id", append_only=False),
    "telemetry":           dict(site_col="site_id",     site_kind="one",  writers=("operator", "director", "manager", "engineer", "compliance", "technician"), bind="agent_id", append_only=False),
    "findings":            dict(site_col="site_id",     site_kind="one",  writers=("operator", "director", "manager", "engineer"), bind=None, append_only=False),
    "notifications":       dict(site_col="site_id",     site_kind="one",  writers=("operator", "director", "manager", "engineer", "compliance", "technician"), bind="sender", append_only=False),
    "maintenance_windows": dict(site_col="site_ids",    site_kind="many", writers=("operator", "director", "manager"), bind=None, append_only=False),
    "eye_frames":          dict(site_col="site_id",     site_kind="one",  writers=("operator", "director", "manager", "engineer"), bind="actor", append_only=False),
    "agents":              dict(site_col=None,          site_kind="none", writers=(), bind=None, append_only=False),
}
# Extra integrity rules every agent write must pass (0003 extra_check): the backend satisfies them before sending.
EXTRA_CHECKS = {"attestations": "signed_payload is not null", "facts": "cited attestation already in the ledger"}
NULLABLE_SITE = {"telemetry", "memories"}
MACHINE_SOURCES = {"sensor", "patrol", "scan"}
GLOBAL_ROLES = {"operator", "director"}
# The sites and teams the Supabase layer serves: the backend registry plus contract-5's tomioka-mill, which Supabase must
# know (Auth users, public.agents, HUD channels) before the backend stream adds it. Policies stay site-agnostic: they
# read the caller's site from public.agents, never from a list.
TEAM_PREFIXES: dict[str, str] = {"myer-plant": "myer", "bristol-pumps": "bristol", "tomioka-mill": "tomioka", **TEAM_PREFIX}
PREFIX_SITES = {prefix: site for site, prefix in TEAM_PREFIXES.items()}
SITES: tuple[str, ...] = tuple(dict.fromkeys([*SITE_IDS, *TEAM_PREFIXES]))
AGENT_IDS: tuple[str, ...] = (OPERATOR, DIRECTOR, *(f"{prefix}-{role}" for prefix in dict.fromkeys(TEAM_PREFIXES.values()) for role in ROLES))
LEVELS = {OPERATOR: 1, DIRECTOR: 2, "manager": 3, "engineer": 4, "compliance": 4, "technician": 5}
TITLES = {"myer": {"manager": "Plant Manager", "engineer": "Site Engineer"}, "bristol": {"manager": "Plant Manager", "engineer": "Site Engineer"},
          "tomioka": {"manager": "Site Manager", "engineer": "Conservation Engineer"}}
DEFAULT_TITLES = {"manager": "Plant Manager", "engineer": "Site Engineer", "compliance": "Compliance Officer", "technician": "Field Technician"}

current_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar("steward_supabase_actor", default=None)


@contextmanager
def acting_as(agent_id: str | None):
    token = current_actor.set(agent_id if agent_id in AGENT_IDS else None)
    try:
        yield
    finally:
        current_actor.reset(token)


def _parse(agent_id: str | None) -> tuple[str | None, str | None]:
    """(role, site) for a Supabase agent id; site is None for the operator and the director."""
    if agent_id in (OPERATOR, DIRECTOR):
        return agent_id, None
    prefix, _, role = (agent_id or "").partition("-")
    site = PREFIX_SITES.get(prefix)
    if site and role in ROLES:
        return role, site
    return None, None


def role_of(agent_id: str | None) -> str | None:
    return _parse(agent_id)[0]


def agent_site(agent_id: str | None) -> str | None:
    return _parse(agent_id)[1]


def level_of(agent_id: str) -> int | None:
    role = role_of(agent_id)
    return LEVELS.get(role) if role else None


def display_name(agent_id: str) -> str:
    """The backend's display name, or the contract's for a site the backend does not know yet."""
    name = _display_name(agent_id)
    if name != agent_id:
        return name
    role, site = _parse(agent_id)
    if not role or not site:
        return agent_id
    prefix = TEAM_PREFIXES[site]
    title = TITLES.get(prefix, {}).get(role) or DEFAULT_TITLES[role]
    return f"{title} · {prefix.capitalize()}"


def team(site: str | None, role: str) -> str | None:
    prefix = TEAM_PREFIXES.get(site or "")
    return f"{prefix}-{role}" if prefix and role in ROLES else None


def site_ok(agent_id: str, table: str, row: dict) -> bool:
    spec = MATRIX[table]
    if role_of(agent_id) in GLOBAL_ROLES:
        return True
    mine = agent_site(agent_id)
    if spec["site_kind"] == "none":
        return True
    value = row.get(spec["site_col"])
    if spec["site_kind"] == "many":
        return bool(mine) and isinstance(value, list) and mine in value
    if value is None and table in NULLABLE_SITE:
        return True
    return bool(mine) and value == mine


def permitted(agent_id: str | None, table: str, row: dict) -> bool:
    """True when Postgres's policies (0003) would accept `row` from `agent_id` (writers, site scope, author binding)."""
    spec = MATRIX.get(table)
    role = role_of(agent_id)
    if not spec or not role or role not in spec["writers"]:
        return False
    if spec["bind"] and row.get(spec["bind"]) != agent_id:
        return False
    if table == "attestations" and not row.get("signed_payload"):
        return False
    return site_ok(agent_id, table, row)


def _site(table: str, row: dict) -> str | None:
    spec = MATRIX.get(table) or {}
    value = row.get(spec.get("site_col") or "")
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _machine(row: dict, body: dict) -> bool:
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    return bool(body.get("simulated") or source.get("kind") in MACHINE_SOURCES or source.get("ref") == "seed")


def _known(agent_id) -> str | None:
    return agent_id if agent_id in AGENT_IDS else None


def default_author(table: str, row: dict, body: dict) -> str | None:
    """The row's author from its own content (a known agent id), or None for a system row (service key)."""
    site = _site(table, row)
    if table in ("changes", "crew_members", "agents"):
        return None
    if table in ("telemetry", "memories"):
        return _known(row.get("agent_id"))
    if table == "eye_frames":
        return _known(row.get("actor"))
    if table == "viewer_commands":
        return _known(row.get("issued_by"))
    if table == "notifications":
        return _known(row.get("sender"))
    if table == "conversations":
        return _known(row.get("convener"))
    if table == "maintenance_windows":
        return _known(body.get("approvedBy")) or _known(body.get("proposedBy"))
    if table == "issues":
        history = body.get("history") or []
        by = history[-1].get("by") if history and isinstance(history[-1], dict) else None
        return _known(by) or team(site, "engineer")
    if table == "findings":
        return _known(body.get("inspectedBy")) or team(site, "engineer")
    if table in ("attestations", "facts"):
        return None if _machine(row, body) else team(site, "engineer")
    if table in ("work_items", "subscriptions"):
        return _known(row.get("requester")) or OPERATOR
    if table == "obligations":
        return team(site, "compliance")
    if table == "dispatches":
        return team(site, "technician")
    return None


def author_for(table: str, row: dict, body: dict | None = None, actor: str | None = None) -> str | None:
    """The agent whose own token writes `row`, or None for a system row (service key).

    Machine readings are always system rows. Otherwise the request's acting agent writes the row when Postgres would
    accept it from that agent; else the row's own author does, and if Postgres refuses that author the refusal is
    recorded (never retried with the service key)."""
    body = body or {}
    if table in ("attestations", "facts") and _machine(row, body):
        return None
    actor = actor if actor is not None else current_actor.get()
    if actor and permitted(actor, table, row):
        return actor
    return default_author(table, row, body)
