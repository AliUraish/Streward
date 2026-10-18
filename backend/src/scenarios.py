"""Scenarios (contract 3 §5, contract 4 §7): seeded scripts that play on a compressed timer when the operator starts one.

Scripts live in the synthetic family `scenarios` (steps with `t` in scenario minutes); nothing fires until
`POST /api/scenarios/{id}/start` (actor operator) or MCP `start_scenario`, or the autoplayer (`autoplay.py`) starts it on
its own in rotation while nothing else runs. The runner compresses time by `speed`
(`STEWARD_SCENARIO_SPEED`, default 30: one scenario minute = 2 s) and, with workers off or `speed: 0`, plays every
step inline. Each step writes real records through the same services the agents use: sensor facts (source
`sensor`, ref `scenario:<id>`), issues with `assetTag`, `severity`, `scenarioId`, `synthetic: true`, board meetings,
notices and contact plans (dry-run), obligation and document changes, viewer commands, agent-to-agent document
email, scripted calls and meetings (conversations over the A2A bus), maintenance windows, telemetry and memories.
Every step emits a Change of type `scenario` on each site the scenario touches (wait event `scenario.step`).

`ops-counsel-tokens` measures, it does not assert: Bristol's Compliance Officer's sweep cost is computed from the
real compliance documents and its current `agent_config` (every poll re-reads every PDF unless `documentCache` is on;
`subscribe` replaces polls with one held wait); the Operations Director reads the findings from Steward telemetry,
calls the officer, reconfigures it and reruns a local efficiency eval whose before/after numbers come from the same table.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import threading
import time
from datetime import datetime, timezone

from datetime import date as date_cls, timedelta

from .agents import DIRECTOR, authorize, display_name, site_of, technician_id
from .conversations import fill
from .env import env
from .errors import RealityError
from .sites import DEMO_SITE
from .specs import spec_for, spec_kind, specs_of
from .store import now, uid
from .synthetic import by_id, load_family
from .telemetry import SOURCE_LABEL, estimate_tokens
from .verify import iso

DEFAULT_SPEED = 30.0
EFFICIENCY_BUDGET = 8000


class ComplianceHandler:
    """A Compliance Officer on the A2A bus: acknowledges efficiency reviews and document requests; call and meeting
    turns are replied by the conversation runner."""

    def __init__(self, service):
        self.service = service

    def on_task(self, task: dict) -> None:
        kind = (task.get("steward") or {}).get("kind")
        bus = self.service.bus
        me = task["target"]
        if kind in ("board_meeting", "call", "document_delivery", "notification"):
            return
        if kind == "efficiency_review":
            bus.reply(me, task["id"], "complete", "Understood. I will cache documents by content hash and subscribe to obligation and document "
                                                      "changes instead of re-reading every PDF on each poll.", dict(kind="efficiency_ack"))
            return
        if kind == "document_request":
            bus.reply(me, task["id"], "complete", "Document request recorded; the field technician notifies the obligation owner.", dict(kind="document_ack"))
            return
        bus.reply(me, task["id"], "fail", f"{display_name(me)} handles efficiency reviews, document requests, calls and meetings.", dict(status="unsupported"))


class ScenarioEngine:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self.threads: dict[str, threading.Thread] = {}
        self.last_manual_start: float | None = None  # monotonic time of the last start not made by the autoplayer
        self.scripts = {script["id"]: self.expand(script) for script in load_family("scenarios")}
        service.bus.register("compliance", ComplianceHandler(service))
        if service.start_workers:
            self.recover()

    def recover(self) -> int:
        """A run left `running` by an earlier backend process has no thread any more: mark it interrupted so a new start
        (and the autoplayer) does not wait on it forever."""
        count = 0
        for run in self.store.all("scenario_run", ""):
            if run["state"] == "running":
                run.update(state="canceled", finishedAt=now(), outcome="interrupted by a backend restart")
                self._save(run)
                count += 1
        return count

    def close(self):
        self._stop.set()
        for thread in list(self.threads.values()):
            if thread.is_alive():
                thread.join(timeout=2)

    # ---- scripts -----------------------------------------------------------------------------------------

    @staticmethod
    def expand(script: dict) -> dict:
        series = by_id("sensor_history")
        steps = []
        for step in script["steps"]:
            if step["type"] == "sensor_series":
                data = series[step["seriesId"]]
                for point in data["points"]:
                    steps.append(dict(t=step["t"] + point["t"], type="sensor", assetTag=data["assetTag"], attribute=data["attribute"], value=point["value"],
                                      unit=data["unit"], seriesId=data["id"], overflowAt=data.get("overflowAt"), ratedLimit=data.get("ratedLimit")))
            else:
                steps.append(dict(step))
        steps = [s for _, s in sorted(enumerate(steps), key=lambda pair: (pair[1]["t"], pair[0]))]
        return {**script, "steps": steps, "durationMinutes": max((s["t"] for s in steps), default=0)}

    def script(self, scenario_id: str) -> dict:
        script = self.scripts.get(scenario_id)
        if not script:
            raise RealityError(f"Unknown scenario '{scenario_id[:40]}'.", "NOT_FOUND", "List scenarios with GET /api/scenarios.", 404)
        return script

    def list(self) -> list[dict]:
        runs = self.runs()
        out = []
        for script in self.scripts.values():
            last = next((r for r in runs if r["scenarioId"] == script["id"]), None)
            out.append(dict(id=script["id"], siteId=script["siteId"], siteIds=self.sites_of(script), scope=script.get("scope", "site"), title=script["title"], summary=script["summary"],
                            headline=bool(script.get("headline")), owners=script.get("owners", []), issueKind=script.get("issueKind"),
                            steps=len(script["steps"]), durationMinutes=script["durationMinutes"], synthetic=True, generator=script.get("generator"),
                            lastRun=dict(id=last["id"], state=last["state"], startedAt=last["startedAt"], stepIndex=last["stepIndex"]) if last else None))
        return out

    @staticmethod
    def sites_of(script: dict) -> list[str]:
        return list(dict.fromkeys(script.get("siteIds") or [script["siteId"]]))

    def runs(self, scenario_id: str | None = None) -> list[dict]:
        records = sorted(self.store.all("scenario_run", ""), key=lambda r: r["startedAt"], reverse=True)
        return [r for r in records if not scenario_id or r["scenarioId"] == scenario_id]

    def run_record(self, run_id: str) -> dict:
        record = self.store.get("scenario_run", run_id, "")
        if not record:
            raise RealityError("Scenario run not found.", "NOT_FOUND", "List runs with GET /api/scenarios.", 404)
        return record

    def active(self) -> dict | None:
        return next((r for r in self.runs() if r["state"] == "running"), None)

    def _save(self, run: dict) -> dict:
        run["updatedAt"] = now()
        self.store.put("scenario_run", run, "")
        return run

    def _change(self, run: dict, summary: str, extra: dict | None = None) -> None:
        for site in run.get("siteIds") or [run["siteId"]]:
            self.service.reality.emit_change(site, "scenario", run["id"], summary[:480],
                                             extra=dict(scenarioId=run["scenarioId"], runId=run["id"], **(extra or {})))

    # ---- lifecycle ----------------------------------------------------------------------------------------

    def start(self, scenario_id: str, actor: str, speed: float | None = None, restart: bool = False, origin: str = "manual") -> dict:
        authorize(actor, "start_scenario")
        script = self.script(scenario_id)
        if origin != "autoplay":
            self.last_manual_start = time.monotonic()  # the autoplayer stays out of the way of people and evals
        with self.lock:
            running = [r for r in self.runs(scenario_id) if r["state"] == "running"]
            if running and not restart:
                return running[0]
            for run in running:
                run.update(state="canceled", finishedAt=now(), outcome="restarted")
                self._save(run)
            speed = float(env("STEWARD_SCENARIO_SPEED", str(DEFAULT_SPEED))) if speed is None else float(speed)
            if speed < 0 or speed > 100000:
                raise RealityError("speed must be between 0 and 100000.", "INVALID_REQUEST", "0 plays every step at once; 30 is the demo default.")
            run = dict(id=uid("srun"), scenarioId=scenario_id, siteId=script["siteId"], siteIds=self.sites_of(script), title=script["title"], state="running",
                       speed=speed, startedAt=now(), startedBy="autoplay" if origin == "autoplay" else actor, origin=origin, finishedAt=None, stepIndex=0, stepCount=len(script["steps"]), log=[], issueIds={},
                       meetingIds=[], conversationIds={}, maintenanceIds={}, context={}, outcome=None, error=None, synthetic=True,
                       generator=script.get("generator"))
            self._save(run)
        self._change(run, f"Scenario started: {script['title']} (synthetic, speed {speed:g}x).", dict(status="started", step=0))
        self.service.ops.note(DIRECTOR, f"Scenario {script['title']} started", why=script["summary"][:180])
        if self.service.start_workers and speed > 0:
            thread = threading.Thread(target=self._play_guarded, args=(run["id"], True), name=f"steward-scenario-{run['id']}", daemon=True)
            self.threads[run["id"]] = thread
            thread.start()
        else:
            self.play(run["id"], realtime=False)
        return self.run_record(run["id"])

    def cancel(self, run_id: str, actor: str) -> dict:
        authorize(actor, "start_scenario")
        run = self.run_record(run_id)
        if run["state"] == "running":
            run.update(state="canceled", finishedAt=now(), outcome="canceled by " + actor)
            self._save(run)
            self._change(run, f"Scenario canceled: {run['title']}.", dict(status="canceled"))
        return run

    def _play_guarded(self, run_id: str, realtime: bool):
        try:
            self.play(run_id, realtime)
        except Exception as error:  # never leave a run dangling
            run = self.store.get("scenario_run", run_id, "")
            if run and run["state"] == "running":
                run.update(state="failed", error=f"{type(error).__name__}: {str(error)[:200]}", finishedAt=now())
                self._save(run)

    def play(self, run_id: str, realtime: bool = False) -> dict:
        run = self.run_record(run_id)
        script = self.script(run["scenarioId"])
        last_t = 0.0
        for index, step in enumerate(script["steps"]):
            if index < run["stepIndex"]:
                last_t = step["t"]
                continue
            if realtime:
                delay = max(0.0, (step["t"] - last_t) * 60.0 / max(run["speed"], 1e-6))
                if self._stop.wait(delay):
                    return self.run_record(run_id)
            last_t = step["t"]
            with self.lock:
                run = self.run_record(run_id)
                if run["state"] != "running":
                    return run
                try:
                    summary = self.execute(run, step)
                except Exception as error:
                    run.update(state="failed", error=f"step {index} ({step['type']}): {type(error).__name__}: {str(error)[:200]}", finishedAt=now())
                    self._save(run)
                    self._change(run, f"Scenario {run['title']} failed at step {index + 1}: {run['error']}", dict(status="failed", step=index))
                    return run
                run["stepIndex"] = index + 1
                run["log"].append(dict(index=index, t=step["t"], type=step["type"], at=now(), agentId=step.get("agentId") or step.get("from"),
                                       summary=summary[:400]))
                self._save(run)
            self._change(run, f"{run['title']} t+{step['t']:g} min: {summary}", dict(step=index, stepType=step["type"], status="step"))
        return self.finish(run_id)

    def finish(self, run_id: str) -> dict:
        run = self.run_record(run_id)
        script = self.script(run["scenarioId"])
        issues = list(run["issueIds"].values())
        outcome = (f"{script['title']}: {len(run['log'])} steps, {len(issues)} issue(s), {len(run.get('conversationIds') or {})} conversation(s)"
                   + (f", efficiency eval {run['context'].get('verdict')}" if run["context"].get("verdict") else "") + ".")
        run.update(state="completed", finishedAt=now(), outcome=outcome)
        self._save(run)
        self.service.memory.write(DIRECTOR, f"Scenario outcome (synthetic): {outcome}", "scenario_outcome", dict(scenarioId=run["scenarioId"], runId=run["id"]),
                                  run["siteId"], synthetic=True)
        self.service.ops.note(DIRECTOR, None)
        self._change(run, f"Scenario completed: {outcome}", dict(status="completed"))
        return run

    # ---- steps ----------------------------------------------------------------------------------------------

    def execute(self, run: dict, step: dict) -> str:
        handler = getattr(self, f"step_{step['type']}", None)
        if handler is None:
            raise RealityError(f"Unknown step type {step['type']}.", "INVALID_REQUEST", "Fix the scenario script.")
        return handler(run, step)

    def _ctx(self, run: dict) -> dict:
        return dict(run.get("context") or {})

    def step_narrate(self, run, step):
        text = fill(step["text"], self._ctx(run))
        self.service.telemetry.record(step["agentId"], "tool", "narrate", text=text, site_id=run["siteId"], scenario_id=run["scenarioId"], run_id=run["id"])
        self.service.ops.note(step["agentId"], text[:180], why=f"Scenario {run['title']}")
        return f"{display_name(step['agentId'])}: {text}"

    def step_sensor(self, run, step):
        site = run["siteId"]
        reality = self.service.reality
        component = reality.component_by_tag(site, step["assetTag"])
        spec = spec_for(spec_kind(component), step["attribute"])
        value = step["value"]
        moment = iso(datetime.now(timezone.utc))
        digest = hashlib.sha256(f"scenario:{run['id']}:{step['assetTag']}:{step['t']}:{value}".encode()).hexdigest()
        checks = [dict(name="scope", passed=True, reason=f"Synthetic scenario reading for {component['tag']} ({run['scenarioId']}); not a physical instrument."),
                  dict(name="integrity", passed=True, reason=f"SHA-256 of the scenario sample: {digest}.")]
        reality.write_fact(site, component, step["attribute"], spec["attributeClass"], value, step.get("unit") or spec.get("unit"), moment,
                           dict(kind="sensor", ref=f"scenario:{run['scenarioId']}"), checks, [digest],
                           summary=f"Scenario {run['scenarioId']}: {component['tag']}.{step['attribute']} = {value} {step.get('unit') or ''}".strip(),
                           extra=dict(synthetic=True, scenarioId=run["scenarioId"]))
        context = run["context"]
        previous = context.get("value")
        context.update(value=value, assetTag=component["tag"], minute=step["t"])
        if step.get("overflowAt") is not None and previous is not None and step["t"] > context.get("previousMinute", 0):
            rate = (value - previous) / max(step["t"] - context.get("previousMinute", 0), 1e-6)
            context["rate"] = round(rate, 3)
            context["minutes"] = round((step["overflowAt"] - value) / rate) if rate > 0 else None
        context["previousMinute"] = step["t"]
        return f"{component['tag']}.{step['attribute']} = {value} {step.get('unit') or ''}".strip()

    def step_issue(self, run, step):
        spec = step["issue"]
        context = self._ctx(run)
        issue = self.service.issues.raise_issue(
            run["siteId"], spec["kind"], spec["severity"], fill(spec["summary"], context), asset_tag=spec.get("assetTag"),
            issue_id=f"iss-{run['id'][-8:]}-{spec['key']}", source="scenario", scenario_id=run["scenarioId"], run_id=run["id"],
            obligation_id=spec.get("obligationId"), document_id=spec.get("documentId"), synthetic=True, actor=self._owner_agent(run))
        run["issueIds"][spec["key"]] = issue["id"]
        return f"Issue {issue['kind']} ({issue['severity']}): {issue['summary']}"

    def _owner_agent(self, run) -> str:
        owners = [o for o in self.script(run["scenarioId"]).get("owners", []) if not o.startswith("crew-")]
        return owners[0] if owners else DIRECTOR

    def step_resolve_issue(self, run, step):
        issue_id = run["issueIds"][step["key"]]
        self.service.issues.resolve_issue(issue_id, fill(step.get("summary", "resolved by the scenario"), self._ctx(run)), self._owner_agent(run))
        return f"Issue {issue_id} resolved"

    def step_viewer(self, run, step):
        issue_id = run["issueIds"].get(step.get("issueKey") or "")
        command = self.service.viewer.post(step.get("siteId") or run["siteId"], step["action"], step.get("assetTag"), issue_id, step.get("agentId") or DIRECTOR)
        return f"Viewer {command['action']} {command['assetTag'] or ''} by {command['issuedByName']}".strip()

    def step_conversation(self, run, step):
        script = by_id("conversations")[step["conversationId"]]
        conversations = self.service.conversations
        context = self._ctx(run)
        issue_id = run["issueIds"].get(step.get("issueKey") or "")
        sites = [s for s in (run.get("siteIds") or [run["siteId"]]) if s in {site_of(p) for p in script["participants"]} or not site_of(script["convener"])]
        if script["kind"] == "meeting":
            conversation = conversations.meeting(script["convener"], script["topic"], script["participants"], script["turns"], script.get("resolution"),
                                                 site_ids=sites or [run["siteId"]], issue_kind=script.get("issueKind"), issue_id=issue_id,
                                                 scenario_id=run["scenarioId"], run_id=run["id"], context=context, summary=script.get("summary"),
                                                 contact_site=run["siteId"])
            run["meetingIds"].append(conversation["id"])
            if conversation.get("contact"):
                run["context"].update(contactName=conversation["contact"]["name"], contactRole=conversation["contact"]["role"])
            text = f"Meeting resolved: {conversation.get('resolution') or conversation['topic']}"
        else:
            conversation = conversations.call(script["convener"], script["callee"], fill(script["topic"], context), script["turns"],
                                              participants=script["participants"], site_ids=sites or [run["siteId"]], issue_id=issue_id,
                                              scenario_id=run["scenarioId"], run_id=run["id"], context=context, summary=script.get("summary"))
            text = f"Call: {conversation['topic']} ({len(conversation['transcript'])} turns, {conversation['transport']})"
        run.setdefault("conversationIds", {})[step["conversationId"]] = conversation["id"]
        return text

    def step_prepare(self, run, step):
        today = date_cls.today()
        if step.get("windowInDays") is not None:
            run["context"]["windowDate"] = (today + timedelta(days=int(step["windowInDays"]))).isoformat()
        if step.get("myerExamMaintenanceId"):
            window = self.store.get("maintenance_window", step["myerExamMaintenanceId"], "")
            run["context"]["myerExamDate"] = window["date"] if window else (today + timedelta(days=9)).isoformat()
        return "Prepared: " + ", ".join(f"{k}={v}" for k, v in run["context"].items() if k in ("windowDate", "myerExamDate"))

    def step_maintenance(self, run, step):
        window = self.service.maintenance.propose(step["siteIds"], run["context"].get("windowDate") or date_cls.today().isoformat(), fill(step["scope"], self._ctx(run)),
                                                  step.get("examiner"), step["proposedBy"], conversation_id=(run.get("conversationIds") or {}).get(step.get("conversationRef") or ""),
                                                  scenario_id=run["scenarioId"])
        run.setdefault("maintenanceIds", {})[step["key"]] = window["id"]
        return f"{display_name(step['proposedBy'])} proposed a {'cross-site ' if len(window['siteIds']) > 1 else ''}maintenance window on {window['date']}"

    def step_approve_maintenance(self, run, step):
        window = self.service.maintenance.approve(run["maintenanceIds"][step["key"]], step["by"],
                                                  conversation_id=(run.get("conversationIds") or {}).get(step.get("conversationRef") or ""))
        return f"{display_name(step['by'])} approved the maintenance window on {window['date']}"

    def step_contact(self, run, step):
        """The field technician contacts a person: the issue kind's owner from the crew table, or `crewMemberId` when the
        script names who is sent (Tomioka's conservator). Synthetic crew are recorded, never contacted."""
        technician = step.get("agentId") or technician_id(run["siteId"])
        notice = self.service.people.send_notice(run["siteId"], technician, fill(step["text"], self._ctx(run)), issue_kind=step["issueKind"],
                                                 crew_member_id=step.get("crewMemberId"),
                                                 issue_id=next(iter(run["issueIds"].values()), None), notice_kind="contact",
                                                 scenario_id=run["scenarioId"], run_id=run["id"])
        self.service.ops.note(technician, f"Contacting {notice['toName']} ({notice['mode']})", why=f"Decision in {run['title']}",
                              waiting_on=f"reply from {notice['toName']}" if notice["mode"] == "sent" else None)
        return f"Runner contact to {notice['toName']} via {notice['channel'] or 'no channel'} ({notice['mode']})"

    def step_notice(self, run, step):
        notice = self.service.people.send_notice(run["siteId"], step["from"], fill(step["text"], self._ctx(run)), issue_kind=step.get("issueKind"),
                                                 obligation_id=step.get("obligationId"), issue_id=next(iter(run["issueIds"].values()), None),
                                                 scenario_id=run["scenarioId"], run_id=run["id"])
        return f"Notice from {display_name(step['from'])} to {notice['toName'] or 'nobody'} ({notice['mode']})"

    def step_obligation(self, run, step):
        record = self.service.people.update_obligation(step["obligationId"], None, last_done_days_ago=step.get("lastDoneDaysAgo"),
                                                       due_in_days=step.get("dueInDays"), status=step.get("status"), blocked_by=step.get("blockedBy"),
                                                       blocked_reason=step.get("blockedReason"), scenario_id=run["scenarioId"],
                                                       note=fill(step["note"], self._ctx(run)) if step.get("note") else None)
        return f"Obligation {record['title']}: {record['status']}"

    def step_regenerate_document(self, run, step):
        document = self.service.people.regenerate_document(step["documentId"])
        return f"Document {document['title']} re-rendered (valid until {(document.get('expiresAt') or '')[:10]})"

    def step_send_document(self, run, step):
        result = self.service.people.send_document(step["from"], step["to"], step["documentId"], fill(step.get("note", ""), self._ctx(run)), actor=step["from"],
                                                   scenario_id=run["scenarioId"], run_id=run["id"], review=step.get("review", True))
        return f"{display_name(step['from'])} emailed {step['documentId']} to {display_name(step['to'])} ({result['mode']}, A2A {result['transport']})"

    def step_review_document(self, run, step):
        review = self.service.people.review_document(step["documentId"], step["agentId"], scenario_id=run["scenarioId"], run_id=run["id"])
        if review.get("issueId"):
            run["issueIds"]["document"] = review["issueId"]
        run["context"]["verdict"] = review["verdict"]
        return f"{display_name(step['agentId'])} reviewed {step['documentId']}: {review['verdict']}" + (" (instruction treated as data, flagged)" if review["injection"] else "")

    def step_fix(self, run, step):
        """Run the contract-4 fix workflow for one of the scenario's issues (evidence, call, contact, fix, verify, inform):
        tm-humidity ends with the verified, signed reading. Inline when workers are off; otherwise the workflow plays on
        its own timer after this step."""
        issue_id = run["issueIds"][step["issueKey"]]
        workflow = self.service.fixes.start(issue_id, "operator", speed=step.get("speed"))
        run.setdefault("context", {})["fixWorkflowId"] = workflow["id"]
        run.setdefault("fixWorkflowIds", {})[step["issueKey"]] = workflow["id"]
        return f"Fix workflow {workflow['id']} {workflow['state']} for {workflow.get('assetTag') or issue_id}"

    def step_memory(self, run, step):
        record = self.service.memory.write(step["agentId"], fill(step["text"], self._ctx(run)), "scenario_outcome",
                                           dict(scenarioId=run["scenarioId"], runId=run["id"]), run["siteId"], synthetic=True)
        return f"{display_name(step['agentId'])} remembered: {record['content'][:160]}"

    # ---- agent-ops steps -----------------------------------------------------------------------------------

    def step_replay_traces(self, run, step):
        telemetry = self.service.telemetry
        count = 0
        for trace in load_family("armature_traces"):
            for call in trace["calls"]:
                telemetry.record(trace["agentId"], "tool", call["tool"], tokens=int(call["tokens"]), mission_id=f"{trace['missionId']}:{run['id'][-8:]}",
                                 scenario_id=run["scenarioId"], run_id=run["id"], source=f"armature-trace:{trace['generator']}", synthetic=True)
                count += 1
        return f"Replayed {count} baseline tool calls from Armature-style traces into Steward telemetry"

    def step_compliance_sweep(self, run, step):
        agent = step.get("agentId") or "bristol-compliance"
        site = site_of(agent)
        baseline = ""
        if step["phase"] == "before":
            # A replay measures the shipped behaviour again: an earlier run's reconfiguration and document cache would
            # otherwise make "before" as cheap as "after" (1.0x). The reset is recorded in the agent's config history.
            restored = self.service.ops.restore_defaults(agent, "Scenario replay: measure the shipped settings again before the Director's fix.",
                                                         scenario_id=run["scenarioId"], run_id=run["id"])
            self.store.meta(f"sweep-cache:{agent}", "{}")
            baseline = " Shipped settings restored for this replay." if restored else ""
        settings = self.service.ops.settings(agent)
        telemetry = self.service.telemetry
        mission_id = f"sweep-{agent}-{step['phase']}-{run['id'][-8:]}"
        documents = self.service.people.compliance_documents(site)
        cache = json.loads(self.store.meta(f"sweep-cache:{agent}") or "{}")
        obligations = self.service.people.obligations(site)
        listing = json.dumps([dict(id=o["id"], status=o["status"], dueAt=o["dueAt"]) for o in obligations], separators=(",", ":"))
        reads = 0
        for poll in range(int(step.get("polls", 8))):
            active = settings["pollStrategy"] == "poll" or poll == 0
            if active:
                telemetry.record(agent, "poll", "list_obligations", text=listing, site_id=site, mission_id=mission_id, scenario_id=run["scenarioId"], run_id=run["id"],
                                 synthetic=True)
                for document in documents:
                    digest = hashlib.sha256((document.get("extractedText") or "").encode()).hexdigest()
                    if settings["documentCache"] and cache.get(document["id"]) == digest:
                        continue
                    telemetry.record(agent, "document_read", "get_document", text=document.get("extractedText"), site_id=site, mission_id=mission_id,
                                     scenario_id=run["scenarioId"], run_id=run["id"], synthetic=True, detail=f"re-read {document['id']}")
                    reads += 1
                    if settings["documentCache"]:
                        cache[document["id"]] = digest
            elif poll == 1:
                telemetry.record(agent, "wait", "wait_for", tokens=40, site_id=site, mission_id=mission_id, scenario_id=run["scenarioId"], run_id=run["id"], synthetic=True,
                                 detail="held wait on obligation/document changes; no tokens while waiting")
        if settings["documentCache"]:
            self.store.meta(f"sweep-cache:{agent}", json.dumps(cache))
        tokens = telemetry.per_mission(agent, mission_prefix=mission_id).get(mission_id, {}).get("tokens", 0)
        run["context"][step["phase"]] = tokens
        self.service.ops.note(agent, f"Compliance sweep ({step['phase']}): {reads} document read(s), {tokens} tokens",
                              why="certificate and permit expiry tracking", waiting_on="obligation changes" if settings["pollStrategy"] == "subscribe" else None)
        return (f"{display_name(agent)} sweep {step['phase']} ({settings['pollStrategy']}, cache {'on' if settings['documentCache'] else 'off'}): "
                f"{reads} PDF read(s), {tokens} estimated tokens.{baseline}")

    def _peer_median(self, run) -> int | None:
        missions = self.service.telemetry.per_mission(since=None)
        suffix = run["id"][-8:]
        peers = [m["tokens"] for key, m in missions.items() if key.startswith("baseline-") and key.endswith(suffix)]
        return round(statistics.median(peers)) if peers else None

    def step_findings(self, run, step):
        findings = self.service.ops.findings(since=run["startedAt"])
        subject = step.get("subject") or "bristol-compliance"
        counsel = next((a for a in findings["agents"] if a["agentId"] == subject), {})
        ratio = counsel.get("ratioToPeers")
        median = self._peer_median(run)
        if run["context"].get("before") and median:
            ratio = round(run["context"]["before"] / median, 1)
        run["context"].update(ratio=ratio, peerMedian=median)
        text = (f"{SOURCE_LABEL}: {display_name(subject)} used {run['context'].get('before')} tokens on its last sweep, {ratio}x the median of its peers ({median}); "
                f"{counsel.get('polls', 0)} polls.")
        self.service.telemetry.record(DIRECTOR, "tool", "get_eval_findings", text=text, scenario_id=run["scenarioId"], run_id=run["id"], synthetic=True)
        self.service.ops.note(DIRECTOR, "Reviewing agent efficiency findings", why=text[:180])
        return text

    def step_call_agent(self, run, step):
        bus = self.service.bus
        text = fill(step["text"], self._ctx(run))
        task = bus.send(step["from"], step["to"], text, dict(kind=step["kind"], scenarioId=run["scenarioId"], runId=run["id"]), run["siteId"], deliver=True)
        return f"{display_name(step['from'])} called {display_name(step['to'])} over A2A ({task['transport']}): {task['state']}"

    def step_reconfigure(self, run, step):
        record = self.service.ops.set_config(step["agentId"], step["change"], fill(step.get("reason", ""), self._ctx(run)), step.get("by", DIRECTOR),
                                             via="reconfigure", scenario_id=run["scenarioId"], run_id=run["id"])
        return f"{display_name(step.get('by', DIRECTOR))} reconfigured {display_name(step['agentId'])} (v{record['version']}): " + \
            ", ".join(f"{k}={v}" for k, v in step["change"].items())

    def step_efficiency_eval(self, run, step):
        context = run["context"]
        before, after = context.get("before"), context.get("after")
        median = context.get("peerMedian") or self._peer_median(run)
        subject = step.get("agentId") or "bristol-compliance"
        budget = self.service.ops.settings(subject).get("maxTokensPerMission") or EFFICIENCY_BUDGET
        rows = [
            dict(name="compliance_before_measured", target="telemetry", result="PASS" if before else "FAIL", ms=0,
                 detail=f"{subject} before: {before} tokens per sweep ({round(before / median, 1) if before and median else '?'}x peer median {median})"),
            dict(name="compliance_after_under_budget", target="telemetry", result="PASS" if after is not None and after <= budget else "FAIL", ms=0,
                 detail=f"after: {after} tokens per sweep, budget {budget}"),
            dict(name="compliance_improved", target="telemetry", result="PASS" if before and after is not None and after * 3 <= before else "FAIL", ms=0,
                 detail=f"improvement: {round(before / after, 1) if before and after else '?'}x fewer tokens"),
        ]
        passed = sum(r["result"] == "PASS" for r in rows)
        record = dict(id=uid("eval"), suite="efficiency", runner="local-telemetry", source=SOURCE_LABEL, startedAt=now(), finishedAt=now(), passed=passed,
                      failed=len(rows) - passed, steps=rows, state="finished", error=None, before=before, after=after, peerMedian=median, budget=budget,
                      scenarioRunId=run["id"], synthetic=True,
                      note="Local efficiency check from Steward telemetry; the full evals/efficiency.json suite runs through POST /api/evals/run.")
        self.store.put("eval_run", record, "")
        verdict = "passed" if record["failed"] == 0 else "failed"
        context.update(verdict=verdict, improvement=round(before / after, 1) if before and after else None)
        self.service.reality.emit_change(DEMO_SITE, "eval", record["id"], f"Efficiency eval {verdict}: {display_name(subject)} {before} -> {after} tokens per sweep (budget {budget}).")
        return f"Efficiency eval {verdict}: {display_name(subject)} {before} -> {after} tokens per sweep, budget {budget}"
