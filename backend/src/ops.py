"""Overview, agent activity, agent runtime settings and eval findings (contract 3 §10).

- `agent_config` (one record per agent): `{id, agentId, settings: {documentCache, pollStrategy: poll | subscribe,
  pollIntervalSeconds, maxTokensPerMission, phrasing}, version, updatedAt, updatedBy, history: [{version, at, by,
  change, reason}]}`. The Operations Director may reconfigure any agent (`POST /api/agents/{id}/reconfigure`,
  director only); the Owner's agent may also change settings through `POST /api/agents/{id}/config`.
- `GET /api/overview` is compact (kept under 600 estimated tokens): every site, open issues by severity,
  compliance counts, crew on shift, each agent's current task, the active scenario and the last 10 Changes.
- `GET /api/agents/{id}/activity`: current task, why, waiting on what, last actions and tokens this hour from local
  telemetry, settings and memory highlights.
- `GET /api/evals/findings`: Atlas's view of agent quality from Steward telemetry (also delivered to Armature),
  plus the Armature MCP section when it is live.
"""
from __future__ import annotations

import json

from .agents import DIRECTOR, OPERATOR, OWNER, agent_infos, all_agent_ids, authorize, display_name, is_known, site_of
from .armature import ArmatureMCP
from .errors import RealityError
from .sites import DEMO_SITE
from .store import now

OVERVIEW_BUDGET_CHARS = 2350
DEFAULT_SETTINGS = dict(documentCache=True, pollStrategy="subscribe", pollIntervalSeconds=60, maxTokensPerMission=None, phrasing=False)
# Bristol's Compliance Officer ships with the inefficient defaults the ops-counsel-tokens scenario is about.
SWEEP_AGENT = "bristol-compliance"
AGENT_DEFAULTS = {SWEEP_AGENT: dict(DEFAULT_SETTINGS, documentCache=False, pollStrategy="poll")}


def validate_change(change: dict) -> dict:
    if not isinstance(change, dict) or not change:
        raise RealityError("change must be a non-empty object.", "INVALID_REQUEST", 'Example: {"documentCache": true, "pollStrategy": "subscribe"}.')
    clean = {}
    for key, value in change.items():
        if key in ("documentCache", "phrasing"):
            if not isinstance(value, bool):
                raise RealityError(f"{key} must be true or false.", "INVALID_REQUEST", f"Send {key}: true.")
        elif key == "pollStrategy":
            if value not in ("poll", "subscribe"):
                raise RealityError("pollStrategy must be poll or subscribe.", "INVALID_REQUEST", "Send pollStrategy: subscribe.")
        elif key == "pollIntervalSeconds":
            if not isinstance(value, int) or isinstance(value, bool) or not 5 <= value <= 3600:
                raise RealityError("pollIntervalSeconds must be an integer from 5 to 3600.", "INVALID_REQUEST", "Send pollIntervalSeconds: 300.")
        elif key == "maxTokensPerMission":
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 100 <= value <= 1_000_000):
                raise RealityError("maxTokensPerMission must be null or an integer from 100 to 1000000.", "INVALID_REQUEST", "Send 8000.")
        else:
            raise RealityError(f"Unknown setting {key[:40]}.", "INVALID_REQUEST",
                               "Settings: documentCache, pollStrategy, pollIntervalSeconds, maxTokensPerMission, phrasing.")
        clean[key] = value
    return clean


class OpsService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.armature = ArmatureMCP()

    # ---- agent config ------------------------------------------------------------------------------------

    @staticmethod
    def _require_agent(agent_id: str):
        if not is_known(agent_id) or agent_id == OWNER:
            raise RealityError(f"Unknown agent '{agent_id[:40]}'.", "NOT_FOUND", "Use one of: " + ", ".join(all_agent_ids()) + ".", 404)

    def config(self, agent_id: str) -> dict:
        self._require_agent(agent_id)
        record = self.store.get("agent_config", agent_id, "")
        if record:
            return record
        return dict(id=agent_id, agentId=agent_id, settings=dict(AGENT_DEFAULTS.get(agent_id, DEFAULT_SETTINGS)), version=0, updatedAt=None,
                    updatedBy=None, history=[])

    def settings(self, agent_id: str) -> dict:
        return self.config(agent_id)["settings"]

    def set_config(self, agent_id: str, change: dict, reason: str, actor: str, via: str = "config", scenario_id: str | None = None,
                   run_id: str | None = None) -> dict:
        self._require_agent(agent_id)
        if agent_id == OPERATOR:
            raise RealityError("The Operator is the customer's agent; Steward does not configure it.", "INVALID_REQUEST", "Pick a Steward agent.")
        actor = authorize(actor, "reconfigure" if via == "reconfigure" else "configure_agent")
        if via == "reconfigure" and actor != DIRECTOR:
            raise RealityError(f"{display_name(actor)} may not reconfigure agents.", "AUTHORITY_DENIED", "Only the Operations Director may reconfigure an agent.", 403)
        clean = validate_change(change)
        record = self.config(agent_id)
        before = dict(record["settings"])
        record["settings"].update(clean)
        record["version"] = int(record.get("version", 0)) + 1
        record.update(updatedAt=now(), updatedBy=actor)
        record["history"] = (record.get("history") or [])[-19:] + [dict(version=record["version"], at=record["updatedAt"], by=actor, change=clean,
                                                                        before={k: before.get(k) for k in clean}, reason=(reason or "")[:500], via=via)]
        self.store.put("agent_config", record, "")
        site = site_of(agent_id) or DEMO_SITE
        summary = f"{display_name(actor)} reconfigured {display_name(agent_id)}: " + ", ".join(f"{k}={v}" for k, v in clean.items()) + (f" ({reason[:160]})" if reason else "")
        self.service.reality.emit_change(site, "agent_config", agent_id, summary[:480],
                                         extra=dict(agentId=agent_id, version=record["version"], by=actor, scenarioId=scenario_id, runId=run_id))
        self.service.telemetry.record(actor, "decision", "reconfigure_agent", text=summary, site_id=site, scenario_id=scenario_id, run_id=run_id)
        for who in dict.fromkeys([actor, agent_id]):
            if who != OPERATOR:
                self.service.memory.write(who, summary, "reconfigure", dict(agentId=agent_id, version=str(record["version"])), site_id=site)
        return record

    def restore_defaults(self, agent_id: str, reason: str, scenario_id: str | None = None, run_id: str | None = None) -> dict | None:
        """Put an agent back on its shipped settings for a scenario replay (recorded in its config history as
        `via: scenario_baseline`, by `scenario`, so it is never shown as a Director decision). None when already there."""
        self._require_agent(agent_id)
        defaults = dict(AGENT_DEFAULTS.get(agent_id, DEFAULT_SETTINGS))
        record = self.config(agent_id)
        before = dict(record["settings"])
        changed = {k: v for k, v in defaults.items() if before.get(k) != v}
        if not changed:
            return None
        record["settings"] = defaults
        record["version"] = int(record.get("version", 0)) + 1
        record.update(updatedAt=now(), updatedBy="scenario")
        record["history"] = (record.get("history") or [])[-19:] + [dict(version=record["version"], at=record["updatedAt"], by="scenario", change=changed,
                                                                        before={k: before.get(k) for k in changed}, reason=(reason or "")[:500],
                                                                        via="scenario_baseline")]
        self.store.put("agent_config", record, "")
        site = site_of(agent_id) or DEMO_SITE
        summary = f"Scenario replay restored {display_name(agent_id)} to its shipped settings: " + ", ".join(f"{k}={v}" for k, v in changed.items())
        self.service.reality.emit_change(site, "agent_config", agent_id, summary[:480],
                                         extra=dict(agentId=agent_id, version=record["version"], by="scenario", scenarioId=scenario_id, runId=run_id))
        return record

    # ---- activity and overview ------------------------------------------------------------------------------

    def note(self, agent_id: str, task: str | None, why: str | None = None, waiting_on: str | None = None) -> None:
        """Record what an agent is doing now (the dashboard's 'agents now' strip)."""
        if agent_id in (OPERATOR, OWNER):
            return
        self.store.put("agent_activity", dict(id=agent_id, lastActivityAt=now(), currentTask=(task or "")[:200] or None, why=(why or "")[:200] or None,
                                              waitingOn=(waiting_on or "")[:120] or None), "")

    def activity(self, agent_id: str) -> dict:
        self._require_agent(agent_id)
        info = next(a for a in agent_infos(self.service) if a["id"] == agent_id)
        telemetry = self.service.telemetry
        tokens, calls = telemetry.tokens_since(agent_id, telemetry.hour_ago())
        actions = [dict(at=r["at"], kind=r["kind"], tool=r["tool"], tokens=r["tokens"], detail=(r["detail"] or "")[:160], synthetic=r["synthetic"])
                   for r in telemetry.rows(agent_id, limit=10)]
        memories = [dict(at=m["at"], kind=m["kind"], content=m["content"][:200]) for m in self.service.memory.local(agent_id, limit=3)]
        return dict(agentId=agent_id, name=info["name"], level=info["level"], status=info["status"], currentTask=info.get("currentTask"),
                    why=info.get("why"), waitingOn=info.get("waitingOn"), lastActivityAt=info.get("lastActivityAt"), transport=info["transport"],
                    lastActions=actions, tokensThisHour=tokens, callsThisHour=calls, settings=self.settings(agent_id) if agent_id != OPERATOR else None,
                    memoryHighlights=memories, telemetrySource="Steward telemetry, also delivered to Armature")

    def overview(self) -> dict:
        severity = ("high", "medium", "low")
        sites = []
        changes = []
        for prop in self.store.all("property"):
            site_id = prop["id"]
            issues = self.service.issues.list(site_id, "open")
            obligations = self.service.people.obligations(site_id)
            crew = self.store.all("crew_member", site_id)
            sites.append(dict(id=site_id, name=prop["name"], issues={s: sum(1 for i in issues if i["severity"] == s) for s in severity},
                              compliance={s: sum(1 for o in obligations if o["status"] == s) for s in ("ok", "due_soon", "overdue", "blocked")},
                              crewOnShift=sum(1 for c in crew if c.get("onShift"))))
            changes += self.service.reality.changes(site_id, max(0, self.service.reality.version(site_id) - 10), 10)["changes"]
        changes.sort(key=lambda c: c["at"], reverse=True)
        infos = [info for info in agent_infos(self.service) if info.get("actor", True)]
        active = self.service.scenarios.active()
        scenario = dict(id=active["scenarioId"], runId=active["id"], step=active["stepIndex"], of=active["stepCount"]) if active else None

        def build(task_chars: int, summary_chars: int) -> dict:
            agents = []
            for info in infos:
                entry = dict(id=info["id"], status=info["status"])
                if info.get("currentTask"):
                    entry["task"] = info["currentTask"][:task_chars]
                if info.get("waitingOn"):
                    entry["waitingOn"] = info["waitingOn"][:40]
                agents.append(entry)
            return dict(at=now(), sites=sites, agents=agents, activeScenario=scenario,
                        lastChanges=[dict(site=c["propertyId"][:2], type=c["type"], summary=c["summary"][:summary_chars], at=c["at"][11:16])
                                     for c in changes[:10]])

        # Kept under ~600 estimated tokens (2400 characters at 4 a token): with three sites and 14 agents the text
        # fields shrink step by step until it fits.
        for task_chars, summary_chars in ((56, 64), (48, 56), (40, 48), (32, 40), (24, 32)):
            overview = build(task_chars, summary_chars)
            if len(json.dumps(overview, separators=(",", ":"))) <= OVERVIEW_BUDGET_CHARS:
                break
        return overview

    # ---- findings -----------------------------------------------------------------------------------------

    def findings(self, since: str | None = None) -> dict:
        report = self.service.telemetry.findings(since)
        report["armature"] = self.armature.findings_section()
        report["configs"] = {agent: self.settings(agent) for agent in all_agent_ids() if agent != OPERATOR}
        return report
