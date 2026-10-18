"""Scenarios (contract 3 §5): six seeded scripts that play on a compressed timer when the operator starts one.

Scripts live in the synthetic family `scenarios` (steps with `t` in scenario minutes); nothing fires until
`POST /api/scenarios/{id}/start` (actor operator) or MCP `start_scenario`. The runner compresses time by `speed`
(`STEWARD_SCENARIO_SPEED`, default 30: one scenario minute = 2 s) and, with workers off or `speed: 0`, plays every
step inline. Each step writes real records through the same services the agents use: sensor facts (source
`sensor`, ref `scenario:<id>`), issues with `assetTag`, `severity`, `scenarioId`, `synthetic: true`, board meetings,
notices and contact plans (dry-run), obligation and document changes, viewer commands, agent-to-agent document
email, telemetry and memories. Every step emits a Change of type `scenario` (wait event `scenario.step`).

`ops-counsel-tokens` measures, it does not assert: Counsel's sweep cost is computed from the real compliance
documents and its current `agent_config` (every poll re-reads every PDF unless `documentCache` is on; `subscribe`
replaces polls with one held wait), Atlas reads the resulting findings from Steward telemetry, reconfigures Counsel
and reruns a local efficiency eval whose before/after numbers come from the same table.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import threading
from datetime import datetime, timezone

from .agents import ATLAS, COUNSEL, RUNNER, authorize, display_name
from .boards import fill
from .env import env
from .errors import RealityError
from .sites import DEMO_SITE
from .specs import spec_for
from .store import now, uid
from .synthetic import by_id, load_family
from .telemetry import SOURCE_LABEL, estimate_tokens
from .verify import iso

DEFAULT_SPEED = 30.0
EFFICIENCY_BUDGET = 8000


class CounselHandler:
    """Counsel on the A2A bus: acknowledges efficiency reviews and document requests; board statements are replied by
    the meeting runner."""

    def __init__(self, service):
        self.service = service

    def on_task(self, task: dict) -> None:
        kind = (task.get("steward") or {}).get("kind")
        bus = self.service.bus
        if kind in ("board_meeting", "document_delivery"):
            return
        if kind == "efficiency_review":
            bus.reply(COUNSEL, task["id"], "complete", "Understood. I will cache documents by content hash and subscribe to obligation and document "
                                                      "changes instead of re-reading every PDF on each poll.", dict(kind="efficiency_ack"))
            return
        if kind == "document_request":
            bus.reply(COUNSEL, task["id"], "complete", "Document request recorded; I will notify the obligation owner through Runner.", dict(kind="document_ack"))
            return
        bus.reply(COUNSEL, task["id"], "fail", "Counsel handles efficiency reviews, document requests and board meetings.", dict(status="unsupported"))


class ScenarioEngine:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self.threads: dict[str, threading.Thread] = {}
        self.scripts = {script["id"]: self.expand(script) for script in load_family("scenarios")}
        service.bus.register("counsel", CounselHandler(service))

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
            out.append(dict(id=script["id"], siteId=script["siteId"], scope=script.get("scope", "site"), title=script["title"], summary=script["summary"],
                            headline=bool(script.get("headline")), owners=script.get("owners", []), issueKind=script.get("issueKind"),
                            steps=len(script["steps"]), durationMinutes=script["durationMinutes"], synthetic=True, generator=script.get("generator"),
                            lastRun=dict(id=last["id"], state=last["state"], startedAt=last["startedAt"], stepIndex=last["stepIndex"]) if last else None))
        return out

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
        self.service.reality.emit_change(run["siteId"], "scenario", run["id"], summary[:480],
                                         extra=dict(scenarioId=run["scenarioId"], runId=run["id"], **(extra or {})))

    # ---- lifecycle ----------------------------------------------------------------------------------------

    def start(self, scenario_id: str, actor: str, speed: float | None = None, restart: bool = False) -> dict:
        authorize(actor, "start_scenario")
        script = self.script(scenario_id)
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
            run = dict(id=uid("srun"), scenarioId=scenario_id, siteId=script["siteId"], title=script["title"], state="running", speed=speed,
                       startedAt=now(), startedBy=actor, finishedAt=None, stepIndex=0, stepCount=len(script["steps"]), log=[], issueIds={},
                       meetingIds=[], context={}, outcome=None, error=None, synthetic=True, generator=script.get("generator"))
            self._save(run)
        self._change(run, f"Scenario started: {script['title']} (synthetic, speed {speed:g}x).", dict(status="started", step=0))
        self.service.ops.note(ATLAS, f"Scenario {script['title']} started", why=script["summary"][:180])
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
        outcome = (f"{script['title']}: {len(run['log'])} steps, {len(issues)} issue(s), {len(run['meetingIds'])} board meeting(s)"
                   + (f", efficiency eval {run['context'].get('verdict')}" if run["context"].get("verdict") else "") + ".")
        run.update(state="completed", finishedAt=now(), outcome=outcome)
        self._save(run)
        self.service.memory.write(ATLAS, f"Scenario outcome (synthetic): {outcome}", "scenario_outcome", dict(scenarioId=run["scenarioId"], runId=run["id"]),
                                  run["siteId"], synthetic=True)
        self.service.ops.note(ATLAS, None)
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
        spec = spec_for(component["kind"], step["attribute"])
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
        return owners[0] if owners else ATLAS

    def step_resolve_issue(self, run, step):
        issue_id = run["issueIds"][step["key"]]
        self.service.issues.resolve_issue(issue_id, fill(step.get("summary", "resolved by the scenario"), self._ctx(run)), self._owner_agent(run))
        return f"Issue {issue_id} resolved"

    def step_viewer(self, run, step):
        issue_id = run["issueIds"].get(step.get("issueKey") or "")
        command = self.service.viewer.post(run["siteId"], step["action"], step.get("assetTag"), issue_id, step.get("agentId") or ATLAS)
        return f"Viewer {command['action']} {command['assetTag'] or ''} by {command['issuedByName']}".strip()

    def step_board_meeting(self, run, step):
        dialogue = by_id("board_meetings")[step["meetingId"]]
        meeting = self.service.boards.convene(run["siteId"], dialogue["topic"], dialogue["participants"], dialogue["statements"], dialogue["resolution"],
                                              issue_kind=step.get("issueKind"), issue_id=run["issueIds"].get(step.get("issueKey") or ""),
                                              scenario_id=run["scenarioId"], run_id=run["id"], context=self._ctx(run))
        run["meetingIds"].append(meeting["id"])
        if meeting.get("contact"):
            run["context"].update(contactName=meeting["contact"]["name"], contactRole=meeting["contact"]["role"])
        return f"Board resolved: {meeting['resolution']}"

    def step_contact(self, run, step):
        notice = self.service.people.send_notice(run["siteId"], step.get("agentId") or RUNNER, fill(step["text"], self._ctx(run)), issue_kind=step["issueKind"],
                                                 issue_id=next(iter(run["issueIds"].values()), None), notice_kind="contact",
                                                 scenario_id=run["scenarioId"], run_id=run["id"])
        self.service.ops.note(RUNNER, f"Contacting {notice['toName']} ({notice['mode']})", why=f"Board decision in {run['title']}",
                              waiting_on=f"reply from {notice['toName']}" if notice["mode"] == "sent" else None)
        return f"Runner contact to {notice['toName']} via {notice['channel'] or 'no channel'} ({notice['mode']})"

    def step_notice(self, run, step):
        notice = self.service.people.send_notice(run["siteId"], step["from"], fill(step["text"], self._ctx(run)), issue_kind=step.get("issueKind"),
                                                 obligation_id=step.get("obligationId"), issue_id=next(iter(run["issueIds"].values()), None),
                                                 scenario_id=run["scenarioId"], run_id=run["id"])
        return f"Notice from {display_name(step['from'])} to {notice['toName'] or 'nobody'} ({notice['mode']})"

    def step_obligation(self, run, step):
        record = self.service.people.update_obligation(step["obligationId"], COUNSEL, last_done_days_ago=step.get("lastDoneDaysAgo"),
                                                       due_in_days=step.get("dueInDays"), status=step.get("status"), blocked_by=step.get("blockedBy"),
                                                       blocked_reason=step.get("blockedReason"), scenario_id=run["scenarioId"])
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

    def step_counsel_sweep(self, run, step):
        settings = self.service.ops.settings(COUNSEL)
        telemetry = self.service.telemetry
        mission_id = f"counsel-sweep-{step['phase']}-{run['id'][-8:]}"
        documents = self.service.people.compliance_documents()
        cache = json.loads(self.store.meta("counsel:document_cache") or "{}")
        obligations = [o for s in (p["id"] for p in self.store.all("property")) for o in self.service.people.obligations(s)]
        listing = json.dumps([dict(id=o["id"], status=o["status"], dueAt=o["dueAt"]) for o in obligations], separators=(",", ":"))
        reads = 0
        for poll in range(int(step.get("polls", 8))):
            active = settings["pollStrategy"] == "poll" or poll == 0
            if active:
                telemetry.record(COUNSEL, "poll", "list_obligations", text=listing, mission_id=mission_id, scenario_id=run["scenarioId"], run_id=run["id"],
                                 synthetic=True)
                for document in documents:
                    digest = hashlib.sha256((document.get("extractedText") or "").encode()).hexdigest()
                    if settings["documentCache"] and cache.get(document["id"]) == digest:
                        continue
                    telemetry.record(COUNSEL, "document_read", "get_document", text=document.get("extractedText"), mission_id=mission_id,
                                     scenario_id=run["scenarioId"], run_id=run["id"], synthetic=True, detail=f"re-read {document['id']}")
                    reads += 1
                    if settings["documentCache"]:
                        cache[document["id"]] = digest
            elif poll == 1:
                telemetry.record(COUNSEL, "wait", "wait_for", tokens=40, mission_id=mission_id, scenario_id=run["scenarioId"], run_id=run["id"], synthetic=True,
                                 detail="held wait on obligation/document changes; no tokens while waiting")
        if settings["documentCache"]:
            self.store.meta("counsel:document_cache", json.dumps(cache))
        tokens = telemetry.per_mission(COUNSEL, mission_prefix=mission_id).get(mission_id, {}).get("tokens", 0)
        run["context"][step["phase"]] = tokens
        self.service.ops.note(COUNSEL, f"Compliance sweep ({step['phase']}): {reads} document read(s), {tokens} tokens",
                              why="certificate and permit expiry tracking", waiting_on="obligation changes" if settings["pollStrategy"] == "subscribe" else None)
        return (f"Counsel sweep {step['phase']} ({settings['pollStrategy']}, cache {'on' if settings['documentCache'] else 'off'}): "
                f"{reads} PDF read(s), {tokens} estimated tokens")

    def _peer_median(self, run) -> int | None:
        missions = self.service.telemetry.per_mission(since=None)
        suffix = run["id"][-8:]
        peers = [m["tokens"] for key, m in missions.items() if key.startswith("baseline-") and key.endswith(suffix)]
        return round(statistics.median(peers)) if peers else None

    def step_findings(self, run, step):
        findings = self.service.ops.findings(since=run["startedAt"])
        counsel = next((a for a in findings["agents"] if a["agentId"] == COUNSEL), {})
        ratio = counsel.get("ratioToPeers")
        median = self._peer_median(run)
        if run["context"].get("before") and median:
            ratio = round(run["context"]["before"] / median, 1)
        run["context"].update(ratio=ratio, peerMedian=median)
        text = (f"{SOURCE_LABEL}: Counsel used {run['context'].get('before')} tokens on its last sweep, {ratio}x the median of its peers ({median}); "
                f"{counsel.get('polls', 0)} polls.")
        self.service.telemetry.record(ATLAS, "tool", "get_eval_findings", text=text, scenario_id=run["scenarioId"], run_id=run["id"], synthetic=True)
        self.service.ops.note(ATLAS, "Reviewing agent efficiency findings", why=text[:180])
        return text

    def step_call_agent(self, run, step):
        bus = self.service.bus
        text = fill(step["text"], self._ctx(run))
        task = bus.send(step["from"], step["to"], text, dict(kind=step["kind"], scenarioId=run["scenarioId"], runId=run["id"]), run["siteId"], deliver=True)
        return f"{display_name(step['from'])} called {display_name(step['to'])} over A2A ({task['transport']}): {task['state']}"

    def step_reconfigure(self, run, step):
        record = self.service.ops.set_config(step["agentId"], step["change"], fill(step.get("reason", ""), self._ctx(run)), step.get("by", ATLAS),
                                             via="reconfigure", scenario_id=run["scenarioId"], run_id=run["id"])
        return f"{display_name(step.get('by', ATLAS))} reconfigured {display_name(step['agentId'])} (v{record['version']}): " + \
            ", ".join(f"{k}={v}" for k, v in step["change"].items())

    def step_efficiency_eval(self, run, step):
        context = run["context"]
        before, after = context.get("before"), context.get("after")
        median = context.get("peerMedian") or self._peer_median(run)
        budget = self.service.ops.settings(COUNSEL).get("maxTokensPerMission") or EFFICIENCY_BUDGET
        rows = [
            dict(name="counsel_before_measured", target="telemetry", result="PASS" if before else "FAIL", ms=0,
                 detail=f"before: {before} tokens per sweep ({round(before / median, 1) if before and median else '?'}x peer median {median})"),
            dict(name="counsel_after_under_budget", target="telemetry", result="PASS" if after is not None and after <= budget else "FAIL", ms=0,
                 detail=f"after: {after} tokens per sweep, budget {budget}"),
            dict(name="counsel_improved", target="telemetry", result="PASS" if before and after is not None and after * 3 <= before else "FAIL", ms=0,
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
        self.service.reality.emit_change(DEMO_SITE, "eval", record["id"], f"Efficiency eval {verdict}: Counsel {before} -> {after} tokens per sweep (budget {budget}).")
        return f"Efficiency eval {verdict}: Counsel {before} -> {after} tokens per sweep, budget {budget}"
