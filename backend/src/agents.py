"""The agent roster (contract 4 §1): the owner's agent, an operations director and one four-agent team per factory,
plus the authority table enforced on every mutating endpoint and on agent-to-agent messages.

| level | id | display name | scope |
| 1 | operator | Owner's agent | the customer's own agent over MCP, all sites |
| 2 | director | Operations Director | both factories |
| 3 | <site>-manager | Plant Manager · <Site> | own site |
| 4 | <site>-engineer | Site Engineer · <Site> | own site |
| 4 | <site>-compliance | Compliance Officer · <Site> | own site |
| 5 | <site>-technician | Field Technician · <Site> | own site |

`<site>` is `myer` (myer-plant) or `bristol` (bristol-pumps). Identities and identity-scoped keys come from
`INKBOX_IDENTITY_<SUFFIX>` / `INKBOX_AGENT_KEY_<SUFFIX>` (suffix `DIRECTOR`, `MYER_MANAGER`, ...). The single phone
number is the shared "Steward Dispatch Line" (`INKBOX_IDENTITY_DISPATCH`, `STEWARD_DISPATCH_PHONE_NUMBER`): both
field technicians reach people by SMS or call through it, and every agent emails from its own identity.

Cross-site messages are allowed only manager to manager, compliance to compliance, and anyone to or from the
director (`message_allowed`). `authorize()` is the single gate for actions; it raises `AUTHORITY_DENIED` naming who
may perform the action.
"""
from __future__ import annotations

from .errors import RealityError
from .providers import clean_env
from .sites import SITE_BY_ID, SITE_IDS

OPERATOR, DIRECTOR, OWNER, DISPATCH = "operator", "director", "owner", "dispatch"
ROLES = ("manager", "engineer", "compliance", "technician")
TEAM_PREFIX = {"myer-plant": "myer", "bristol-pumps": "bristol"}
PREFIX_SITE = {prefix: site for site, prefix in TEAM_PREFIX.items()}
SHORT_SITE = {"myer-plant": "Myer", "bristol-pumps": "Bristol"}
LEVELS = {OPERATOR: 1, DIRECTOR: 2, "manager": 3, "engineer": 4, "compliance": 4, "technician": 5, DISPATCH: 5}
ROLE_TITLES = {"manager": "Plant Manager", "engineer": "Site Engineer", "compliance": "Compliance Officer", "technician": "Field Technician"}
ROLE_LINES = {
    OPERATOR: "the customer's own agent over MCP, all sites",
    DIRECTOR: "both factories: delegates to managers, reads eval metrics and telemetry, reconfigures agents, approves cross-site maintenance, escalates to the owner",
    "manager": "own site: convenes calls, assigns crew, approves work orders within budget, schedules maintenance, talks to the other site's manager",
    "engineer": "own site: drives the agent eye, runs valve inspections, resolves, attests and verifies, opens issues",
    "compliance": "own site: obligations, regulations, documents, notices; emails documents to any agent; talks to the other site's compliance officer",
    "technician": "own site: contacts people through the dispatch line and email, collects evidence; cannot attest or write facts",
    DISPATCH: "the shared phone number both field technicians use for SMS and calls",
}
SCOPED_KINDS = ROLES
# The Owner's agent keeps the direct reality verbs (resolve/attest/escalate/owner-decision) for the single-agent path
# the MCP tools and the demo eval use; see DEVIATIONS.md.
AUTHORITY: dict[str, list[str]] = {
    OPERATOR: ["read", "start_mission", "set_budget", "resolve", "dispatch", "attest", "escalate", "owner_decision", "decide", "subscribe",
               "simulation", "evals", "start_scenario", "start_fix", "assign_issue", "place_pin", "viewer", "eye", "configure_agent",
               "ingest_vision", "wait"],
    DIRECTOR: ["read", "resolve", "delegate", "cross_site_check", "declare_readiness", "ask_owner", "read_metrics", "reconfigure",
               "configure_agent", "approve_maintenance", "approve_cross_site_maintenance", "convene_call", "call_agent", "eye", "viewer", "wait"],
    "manager": ["read", "resolve", "delegate", "convene_call", "call_agent", "assign_issue", "approve_work_order", "schedule_maintenance",
                "approve_maintenance", "eye", "viewer", "wait"],
    "engineer": ["read", "resolve", "attest", "verify", "escalate", "delegate_field", "subscribe", "review_document", "raise_issue", "eye",
                 "ingest_vision", "viewer", "wait"],
    "compliance": ["read", "write_compliance", "send_document", "request_document", "raise_issue", "viewer", "wait"],
    "technician": ["read", "resolve", "dispatch", "escalate", "collect_evidence", "contact_people", "wait"],
    OWNER: ["read", "owner_decision"],
}
ACTION_LABEL = {
    "read": "read", "start_mission": "start a mission", "set_budget": "set a budget", "resolve": "resolve a fact",
    "dispatch": "dispatch people (resolve with a budget)", "attest": "attest evidence and sign facts", "escalate": "escalate a work item",
    "owner_decision": "record an owner decision", "decide": "decide", "subscribe": "subscribe to changes", "simulation": "toggle the simulation",
    "evals": "run evals", "delegate": "delegate work", "cross_site_check": "run cross-site checks", "declare_readiness": "declare restart readiness",
    "ask_owner": "escalate to the owner", "delegate_field": "delegate field work", "collect_evidence": "collect evidence",
    "start_scenario": "start a scenario", "start_fix": "start a fix workflow", "assign_issue": "assign crew to an issue", "place_pin": "place asset pins",
    "viewer": "move the 3D viewer", "eye": "drive the agent eye", "configure_agent": "change an agent's runtime settings",
    "reconfigure": "reconfigure an agent", "call_agent": "call another agent", "convene_call": "convene a call or meeting",
    "ingest_vision": "run valve inspections", "wait": "wait for events", "write_compliance": "write compliance records",
    "send_document": "email documents", "request_document": "request documents", "review_document": "review documents",
    "raise_issue": "open an issue", "contact_people": "contact people through the dispatch line", "verify": "verify evidence",
    "read_metrics": "read eval metrics and telemetry", "approve_work_order": "approve work orders", "schedule_maintenance": "schedule maintenance",
    "approve_maintenance": "approve maintenance", "approve_cross_site_maintenance": "approve cross-site maintenance",
}
SKILLS = {
    DIRECTOR: [("run-both-factories", "Run both factories", "Delegate to the plant managers, read agent metrics, approve cross-site maintenance."),
               ("clear-site-for-restart", "Clear a site for restart", "Resolve a site's restart set through its team and declare readiness.")],
    "manager": [("convene-call", "Convene a call", "Bring the site team together, decide, and assign crew."),
                ("approve-work-order", "Approve a work order", "Approve field work within the site budget and schedule maintenance.")],
    "engineer": [("resolve-fact", "Resolve a fact", "Answer a fact for this site from signed attestations or dispatch for it."),
                 ("drive-agent-eye", "Drive the agent eye", "Move the 3D scan camera, capture frames and mark observations.")],
    "compliance": [("track-obligations", "Track obligations", "Keep certificates, permits and inspection obligations current against the regulations."),
                   ("send-document", "Send a document", "Email a compliance document (PDF attached) to another Steward agent.")],
    "technician": [("dispatch-technician", "Dispatch a technician", "Reach an employee or contractor through the dispatch line or email."),
                   ("collect-evidence", "Collect evidence", "Receive the reply and hand the evidence to the site engineer.")],
}
# Contract 4 id migration: old id -> new id, or a role resolved by the record's site.
OLD_AGENT_IDS = {"atlas": DIRECTOR, "warden:myer-plant": "myer-engineer", "warden:bristol-pumps": "bristol-engineer",
                 "counsel": "compliance", "runner": "technician"}
RETIRED_HANDLES = ("steward-atlas", "steward-warden-myer", "steward-warden-bristol", "steward-counsel", "steward-warden-harbor")


def team_id(site_id: str, role: str) -> str:
    prefix = TEAM_PREFIX.get(site_id)
    if not prefix or role not in ROLES:
        raise RealityError(f"No {role} for site {site_id}.", "NOT_FOUND", "Sites: " + ", ".join(SITE_IDS) + ".", 404)
    return f"{prefix}-{role}"


def manager_id(site_id: str) -> str:
    return team_id(site_id, "manager")


def engineer_id(site_id: str) -> str:
    return team_id(site_id, "engineer")


def compliance_id(site_id: str) -> str:
    return team_id(site_id, "compliance")


def technician_id(site_id: str) -> str:
    return team_id(site_id, "technician")


def _split(agent_id: str) -> tuple[str | None, str | None]:
    prefix, _, role = (agent_id or "").partition("-")
    if prefix in PREFIX_SITE and role in ROLES:
        return PREFIX_SITE[prefix], role
    return None, None


def kind_of(agent_id: str) -> str:
    if agent_id in (OPERATOR, DIRECTOR, OWNER, DISPATCH):
        return agent_id
    site, role = _split(agent_id)
    return role if role else agent_id


def site_of(agent_id: str) -> str | None:
    return _split(agent_id)[0]


def is_known(agent_id: str) -> bool:
    if agent_id in (OPERATOR, DIRECTOR, OWNER):
        return True
    site, role = _split(agent_id)
    return bool(role) and site in SITE_BY_ID


def all_agent_ids() -> list[str]:
    return [OPERATOR, DIRECTOR] + [team_id(site, role) for site in SITE_IDS if site in TEAM_PREFIX for role in ROLES]


def site_team(site_id: str) -> list[str]:
    return [team_id(site_id, role) for role in ROLES]


def display_name(agent_id: str) -> str:
    if agent_id == OPERATOR:
        return "Owner's agent"
    if agent_id == DIRECTOR:
        return "Operations Director"
    if agent_id == DISPATCH:
        return "Steward Dispatch Line"
    if agent_id == OWNER:
        return "the owner"
    site, role = _split(agent_id)
    if role:
        return f"{ROLE_TITLES[role]} · {SHORT_SITE.get(site, site)}"
    return agent_id


def env_suffix(agent_id: str) -> str | None:
    if agent_id == DIRECTOR:
        return "DIRECTOR"
    if agent_id == DISPATCH:
        return "DISPATCH"
    site, role = _split(agent_id)
    if role:
        return f"{TEAM_PREFIX[site].upper()}_{role.upper()}"
    return None


def handle_env_names(agent_id: str) -> list[str]:
    suffix = env_suffix(agent_id)
    return [f"INKBOX_IDENTITY_{suffix}"] if suffix else []


def handle_for(agent_id: str) -> str | None:
    for name in handle_env_names(agent_id):
        value = clean_env(name)
        if value and value not in RETIRED_HANDLES:
            return value
    return None


def key_env_name(agent_id: str) -> str | None:
    """Identity-scoped Inkbox API key used for outbound A2A sends and email by this agent."""
    suffix = env_suffix(agent_id)
    return f"INKBOX_AGENT_KEY_{suffix}" if suffix and agent_id != DISPATCH else None


def agent_key(agent_id: str) -> str | None:
    name = key_env_name(agent_id)
    return (clean_env(name) or None) if name else None


def dispatch_handle() -> str | None:
    value = clean_env("INKBOX_IDENTITY_DISPATCH") or clean_env("INKBOX_PHONE_IDENTITY")
    return value or None


def dispatch_phone() -> str | None:
    return clean_env("STEWARD_DISPATCH_PHONE_NUMBER") or clean_env("STEWARD_RUNNER_PHONE_NUMBER") or None


def phone_for(agent_id: str) -> str | None:
    """No agent owns a phone: the plan allows one number and it is the shared dispatch line."""
    return dispatch_phone() if agent_id == DISPATCH else None


def email_for(agent_id: str) -> str | None:
    handle = handle_for(agent_id)
    return f"{handle}@inkboxmail.com" if handle else None


def parse_actor(header_value: str | None) -> str:
    actor = (header_value or OPERATOR).strip().casefold()
    if actor in OLD_AGENT_IDS:
        raise RealityError(f"Agent id '{actor}' was retired in contract 4.", "AUTHORITY_DENIED",
                           "Use operator, director or <myer|bristol>-<manager|engineer|compliance|technician>.", 403)
    if not is_known(actor):
        raise RealityError(f"Unknown actor '{actor[:40]}'.", "AUTHORITY_DENIED",
                           "Send X-Steward-Actor as operator, director or <myer|bristol>-<manager|engineer|compliance|technician>.", 403)
    return actor


def who_may(action: str, site: str | None = None) -> list[str]:
    names = []
    for agent_id in all_agent_ids() + [OWNER]:
        kind = kind_of(agent_id)
        if action in AUTHORITY.get(kind, []) and (site is None or kind not in SCOPED_KINDS or site_of(agent_id) == site):
            names.append(display_name(agent_id))
    return names


def authorize(actor: str, action: str, site: str | None = None) -> str:
    """Return the actor when permitted; raise AUTHORITY_DENIED (403) otherwise."""
    actor = parse_actor(actor)
    kind = kind_of(actor)
    allowed = AUTHORITY.get(kind, [])
    permitted = action in allowed and (kind not in SCOPED_KINDS or site is None or site_of(actor) == site)
    if permitted:
        return actor
    label = ACTION_LABEL.get(action, action)
    if kind in SCOPED_KINDS and action in allowed and site and site_of(actor) != site:
        detail = f"{display_name(actor)} may only {label} for its own site ({site_of(actor)}), not {site}."
    else:
        detail = f"{display_name(actor)} may not {label}."
    names = who_may(action, site)
    raise RealityError(detail, "AUTHORITY_DENIED", f"Only {', '.join(names) if names else 'nobody'} may {label}" + (f" at {site}." if site else "."), 403)


def message_allowed(caller: str, target: str) -> tuple[bool, str]:
    """Cross-site messages: manager to manager, compliance to compliance, and anyone to or from the director."""
    if DIRECTOR in (caller, target) or OPERATOR in (caller, target):
        return True, ""
    caller_site, target_site = site_of(caller), site_of(target)
    if not caller_site or not target_site or caller_site == target_site:
        return True, ""
    if kind_of(caller) == kind_of(target) and kind_of(caller) in ("manager", "compliance"):
        return True, ""
    return False, (f"{display_name(caller)} may not message {display_name(target)} across sites; cross-site messages go manager to manager, "
                   "compliance to compliance, or through the Operations Director.")


def require_message_allowed(caller: str, target: str) -> None:
    ok, reason = message_allowed(caller, target)
    if not ok:
        raise RealityError(reason, "AUTHORITY_DENIED", "Route it through the Operations Director or the counterpart role.", 403)


def migrate_agent_id(value: str, site: str | None) -> str:
    """Contract 4: atlas→director, warden:<site>→<site>-engineer, counsel→<site>-compliance (cross-site→bristol-compliance),
    runner→<site>-technician (no site→myer-technician)."""
    if value not in OLD_AGENT_IDS:
        return value
    new = OLD_AGENT_IDS[value]
    if new in ROLES:
        if site in TEAM_PREFIX:
            return team_id(site, new)
        return "bristol-compliance" if new == "compliance" else "myer-technician"
    return new


def agent_infos(service) -> list[dict]:
    """AgentInfo[] with live status from the A2A bus and the activity records, plus the dispatch line."""
    bus = service.bus
    infos = []
    for agent_id in all_agent_ids():
        kind = kind_of(agent_id)
        activity = service.store.get("agent_activity", agent_id, "") or {}
        status, current = bus.status_for(agent_id)
        info = dict(id=agent_id, level=LEVELS[kind], kind=kind, name=display_name(agent_id), role=ROLE_LINES[kind], handle=handle_for(agent_id),
                    status=status, currentTask=current or activity.get("currentTask"), lastActivityAt=activity.get("lastActivityAt"),
                    authority=list(AUTHORITY[kind]), transport=bus.transport_for(agent_id), email=email_for(agent_id), phone=None,
                    siteId=site_of(agent_id), actor=True)
        if activity.get("why"):
            info["why"] = activity["why"]
        if activity.get("waitingOn"):
            info["waitingOn"] = activity["waitingOn"]
        infos.append(info)
    handle = dispatch_handle()
    infos.append(dict(id=DISPATCH, level=LEVELS[DISPATCH], kind=DISPATCH, name=display_name(DISPATCH), role=ROLE_LINES[DISPATCH], handle=handle,
                      status="idle", currentTask=None, lastActivityAt=None, authority=[], transport="inkbox" if handle and clean_env("INKBOX_API_KEY") else "local",
                      email=None, phone=dispatch_phone(), siteId=None, actor=False, usedBy=[technician_id(site) for site in SITE_IDS if site in TEAM_PREFIX]))
    return infos
