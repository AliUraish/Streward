"""Missions: the Operations Director's five-step `clear_for_restart` state machine as a checkpointed, resumable job.

Contract 4 roles (the code keeps the older handler names): Atlas = the Operations Director, the Warden = the site's
Site Engineer, Runner = the site's Field Technician. The director delegates to the site's Plant Manager, who approves
the work order within the site budget (`STEWARD_WORK_ORDER_LIMIT_USD`, default 500) and hands the restart set to the
engineer; the manager relays the engineer's reports back up.

1. Director → Manager → Engineer task "resolve restart set for <site>" (every attribute in the restart set, with the budget).
2. Warden resolves each: known ones are reported with attestation IDs (`progress`); unknown ones become a
   Warden → Runner task "collect <attribute> for <tag>", and Runner dispatches through the existing path.
3. Inbound evidence is verified on the inbound path (same verifier the Warden signs with); Runner hands the
   evidence reference to the Warden on its task (`complete` with the attestation ID, or `progress` with the
   rejection reason and keeps waiting).
4. Atlas `check`s every attestation; an out-of-range reading opens cross-site tasks to the other Wardens, marks
   the mission `input_required` and asks the owner one question through the existing escalation path.
5. Atlas replies to the Operator's mission task with `completed` and a restart checklist, or `failed` with what is
   missing.

Warden and Runner are code-driven participants on the same bus. Their text parts are templated; the optional
model adapter may phrase them when `STEWARD_AGENT_PHRASING=true` and a model is configured.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from .agents import DIRECTOR, OPERATOR, authorize, display_name, engineer_id, manager_id, technician_id

ATLAS = DIRECTOR  # the director keeps Atlas's role in this state machine
warden_id = engineer_id
from .env import env
from .errors import RealityError
from .sites import SITE_BY_ID, SITE_IDS
from .specs import SPECS, spec_for
from .store import now, uid

RESTART_SET: dict[str, list[str]] = {"pump": ["commissioning_certificate", "pressure_bar"], "valve": ["position"], "panel": ["status"],
                                     "fire": ["pressure_ok"], "door": ["closed"]}
TERMINAL_ITEM = ("known", "accepted", "decided")
OPEN_MISSION = ("running", "input_required")


def in_spec(spec: dict, value) -> bool:
    if spec.get("min") is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
        return spec["min"] <= value <= spec["max"]
    if spec.get("enum") and isinstance(value, str):
        return value in spec["enum"] and not (spec["attribute"] == "status" and value in ("tripped", "alarm"))
    return True


class MissionEngine:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.reality = service.reality
        self.bus = service.bus
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="steward-mission")
        self.bus.register("director", AtlasHandler(self))
        self.bus.register("manager", ManagerHandler(self))
        self.bus.register("engineer", WardenHandler(self))
        self.bus.register("technician", RunnerHandler(self))
        self.reality.listeners.append(self.on_reality_event)

    def close(self):
        self.executor.shutdown(wait=True)

    # ---- helpers ---------------------------------------------------------------------------------------

    def phrase(self, agent_id: str, text: str) -> str:
        """Templated text, optionally rephrased by the configured model. The template stays in the data part."""
        if env("STEWARD_AGENT_PHRASING", "false").lower() != "true" or not self.service.model.configured:
            return text
        try:
            phrased = self.service.model.synthesize(
                f"You are {display_name(agent_id)}, an industrial site agent. Rephrase this status line in one plain sentence, keeping every "
                f"identifier, number and unit exactly: {text}", {"property": {"id": "n/a"}, "line": text})
            return (phrased or text).strip()[:600] or text
        except Exception:
            return text

    def mission(self, mission_id: str) -> dict:
        record = self.store.get("mission", mission_id)
        if not record:
            raise RealityError("Mission not found.", "NOT_FOUND", "List missions with GET /api/missions.", 404)
        return self._shape(record)

    def missions(self, site: str | None = None) -> list[dict]:
        records = self.store.all("mission", site) if site else self.store.all("mission")
        return [self._shape(m) for m in sorted(records, key=lambda m: m["createdAt"], reverse=True)]

    @staticmethod
    def _shape(record: dict) -> dict:
        record["checklist"] = record.get("checklist") or []
        record.setdefault("steps", [])
        return record

    def save(self, mission: dict) -> dict:
        mission["updatedAt"] = now()
        self.store.put("mission", mission, mission["siteId"])
        return mission

    def step(self, mission: dict, agent_id: str, summary: str, task_id=None, work_item_id=None, attestation_id=None) -> dict:
        mission.setdefault("steps", []).append(dict(id=uid("step"), at=now(), agentId=agent_id, summary=summary[:400], taskId=task_id,
                                                    workItemId=work_item_id, attestationId=attestation_id))
        telemetry = getattr(self.service, "telemetry", None)
        if telemetry is not None and agent_id != OPERATOR:
            telemetry.record(agent_id, "mission", "mission_step", text=summary, site_id=mission.get("siteId"), mission_id=mission["id"])
        return self.save(mission)

    def remember(self, mission: dict, text: str) -> None:
        memory = getattr(self.service, "memory", None)
        if memory is not None:
            memory.write(ATLAS, text, "decision", dict(missionId=mission["id"]), mission.get("siteId"))

    def item_for(self, mission: dict, asset_tag: str, attribute: str) -> dict | None:
        return next((i for i in mission["items"] if i["assetTag"] == asset_tag and i["attribute"] == attribute), None)

    def mission_for_task(self, task: dict) -> dict | None:
        mission_id = (task.get("steward") or {}).get("missionId")
        return self.store.get("mission", mission_id) if mission_id else None

    def missions_for_work_item(self, work_item_id: str) -> list[tuple[dict, dict | None]]:
        """Every open mission that waits on this work item (several missions may share one open item)."""
        matches = []
        for mission in self.store.all("mission"):
            if mission["state"] not in OPEN_MISSION:
                continue
            item = next((i for i in mission["items"] if i.get("workItemId") == work_item_id), None)
            if item is not None:
                matches.append((mission, item))
            elif mission.get("tasks", {}).get("ownerWorkItemId") == work_item_id:
                matches.append((mission, None))
        return matches

    def restart_set(self, site: str, asset_tags: list[str] | None) -> list[tuple[dict, str]]:
        """Default: one representative asset per restart-set kind (register order). `assetTags` narrows to named assets;
        `["all"]` (or `["*"]`) covers every asset of those kinds."""
        wanted = {tag.strip().upper() for tag in asset_tags or [] if tag and tag.strip()}
        everything = bool(wanted & {"ALL", "*"})
        pairs, seen_kinds = [], set()
        for component in self.reality.components(site):
            if component["kind"] not in RESTART_SET:
                continue
            if wanted and not everything:
                if component["tag"] not in wanted:
                    continue
            elif not everything:
                if component["kind"] in seen_kinds:
                    continue
                seen_kinds.add(component["kind"])
            for attribute in RESTART_SET[component["kind"]]:
                pairs.append((component, attribute))
        return pairs

    # ---- API -------------------------------------------------------------------------------------------

    def start(self, site: str, goal: str, budget: float, requester: str, asset_tags: list[str] | None = None, actor: str = OPERATOR) -> dict:
        authorize(actor, "start_mission")
        self.service.require_property(site)
        if goal != "clear_for_restart":
            raise RealityError("goal must be clear_for_restart.", "INVALID_REQUEST", "Start a mission with goal clear_for_restart.")
        pairs = self.restart_set(site, asset_tags)
        if not pairs:
            raise RealityError("The restart set is empty for the requested assets.", "INVALID_REQUEST",
                               "Pass registered asset tags of kind pump, valve, panel, fire or door, or omit assetTags.")
        mission = dict(id=uid("msn"), siteId=site, goal=goal, budget=float(budget or 0), requester=requester or "operator", state="running",
                       steps=[], contextId=uid("ctx"), checklist=[], scope=dict(assetTags=sorted({c["tag"] for c, _ in pairs})), phase="delegating",
                       items=[dict(assetTag=c["tag"], componentId=c["id"], attribute=a, status="pending", value=None, unit=None, attestationId=None,
                                   workItemId=None, reference=None, runnerTaskId=None, reason=None) for c, a in pairs],
                       tasks=dict(operator=None, manager=None, warden=None, crossSite=[], ownerWorkItemId=None), failure=None, createdAt=now(), updatedAt=now())
        self.save(mission)
        name = SITE_BY_ID[site]["name"]
        task = self.bus.send(OPERATOR, ATLAS, self.phrase(OPERATOR, f"Clear {name} for restart. Budget {mission['budget']:g} USD. Requester {mission['requester']}."),
                             dict(missionId=mission["id"], goal=goal, budget=mission["budget"], kind="mission"), site, context_id=mission["contextId"], deliver=False)
        mission = self.mission(mission["id"])
        mission["tasks"]["operator"] = task["id"]
        self.step(mission, OPERATOR, f"Mission started: clear {name} for restart ({len(pairs)} attribute(s), budget {mission['budget']:g}).", task_id=task["id"])
        if self.service.start_workers:
            self.executor.submit(self._guarded_advance, mission["id"])
        else:
            self.advance(mission["id"])
        return self.mission(mission["id"])

    def recover(self) -> None:
        """Resume interrupted missions from their checkpoint: re-read work items, then advance."""
        for mission in self.missions():
            if mission["state"] not in OPEN_MISSION:
                continue
            for item in mission["items"]:
                if item.get("workItemId") and item["status"] in ("waiting", "rejected"):
                    work_item = self.store.get("work_item", item["workItemId"])
                    if work_item and work_item["state"] == "resolved" and work_item.get("attestationId"):
                        item.update(status="accepted", attestationId=work_item["attestationId"])
                    elif work_item and work_item["state"] == "expired":
                        item.update(status="expired", reason="work item expired before any accepted fact")
            self.step(mission, ATLAS, "Mission resumed from checkpoint after restart.")
            self.executor.submit(self._guarded_advance, mission["id"])

    def _guarded_advance(self, mission_id: str):
        try:
            self.advance(mission_id)
        except Exception as error:
            mission = self.store.get("mission", mission_id)
            if mission and mission["state"] in OPEN_MISSION:
                mission.update(state="failed", failure=f"mission worker failed ({type(error).__name__}: {str(error)[:160]})")
                self.step(mission, ATLAS, mission["failure"])

    # ---- Atlas state machine ---------------------------------------------------------------------------

    def advance(self, mission_id: str) -> dict:
        with self.lock:
            mission = self.mission(mission_id)
            if mission["state"] not in OPEN_MISSION:
                return mission
            site = mission["siteId"]
            if not mission["tasks"].get("manager") and not mission["tasks"].get("warden"):
                attributes = [f"{i['assetTag']}.{i['attribute']}" for i in mission["items"]]
                text = self.phrase(ATLAS, f"Clear {SITE_BY_ID[site]['name']} for restart: resolve {', '.join(attributes)}. Budget {mission['budget']:g} USD per item.")
                mission["phase"] = "resolving"
                self.save(mission)
                task = self.bus.send(ATLAS, manager_id(site), text, dict(missionId=mission_id, kind="delegate_restart_set", budget=mission["budget"],
                                                                       attributes=attributes), site, context_id=mission["contextId"], deliver=False)
                mission = self.mission(mission_id)
                mission["tasks"]["manager"] = task["id"]
                self.step(mission, ATLAS, f"Delegated the restart set ({len(attributes)} attribute(s)) to {display_name(manager_id(site))}.", task_id=task["id"])
                self.bus.handler_for(manager_id(site)).on_task(self.bus.task(task["id"]))
                mission = self.mission(mission_id)
            if mission["state"] not in OPEN_MISSION:
                return mission
            statuses = [i["status"] for i in mission["items"]]
            if any(s in ("expired", "failed") for s in statuses):
                return self.fail(mission, "missing: " + ", ".join(f"{i['assetTag']}.{i['attribute']} ({i['status']})" for i in mission["items"] if i["status"] in ("expired", "failed")))
            if mission["phase"] == "resolving":
                if not all(s in TERMINAL_ITEM for s in statuses):
                    return mission
                mission["phase"] = "checking"
                self.save(mission)
            if mission["phase"] == "checking":
                return self.check(mission)
            if mission["phase"] == "input_required":
                if mission["tasks"].get("ownerWorkItemId") and not any(i.get("ownerDecision") for i in mission["items"]):
                    return mission
                mission["phase"] = "checking"
                self.save(mission)
                return self.check(mission)
            return mission

    def check(self, mission: dict) -> dict:
        """Step 4: verify every attestation signature and spec range; step 5: complete or fail."""
        site = mission["siteId"]
        checklist, out_of_range, missing = [], [], []
        for item in mission["items"]:
            if not item.get("attestationId"):
                missing.append(f"{item['assetTag']}.{item['attribute']}")
                continue
            record = self.reality.check_attestation(item["attestationId"])
            component = self.store.get("component", item["componentId"], site)
            spec = spec_for(component["kind"], item["attribute"])
            valid = bool(record["valid"]) and record["verdict"] == "accepted" and in_spec(spec, record["value"])
            if item.get("ownerDecision"):
                valid = valid or str(item["ownerDecision"]).casefold() == "proceed"
            entry = dict(assetTag=item["assetTag"], attribute=item["attribute"], value=record["value"], attestationId=item["attestationId"], valid=valid)
            if item.get("ownerDecision"):
                entry["ownerDecision"] = item["ownerDecision"]
            checklist.append(entry)
            if record["valid"] and not in_spec(spec, record["value"]) and not item.get("ownerDecision") and not item.get("crossChecked"):
                out_of_range.append((item, record, spec))
        if out_of_range and not mission["tasks"].get("ownerWorkItemId"):
            return self.ask_for_input(mission, out_of_range)
        mission["checklist"] = checklist
        self.save(mission)
        if missing:
            return self.fail(mission, "missing: " + ", ".join(missing))
        valid_count = sum(1 for c in checklist if c["valid"])
        summary = f"{SITE_BY_ID[site]['name']} restart checklist: {valid_count}/{len(checklist)} items verified with signed attestations."
        self.step(mission, ATLAS, "Checked every attestation signature and spec range; declaring readiness.")
        mission = self.mission(mission["id"])
        mission.update(state="completed", phase="done", checklist=checklist)
        self.save(mission)
        if mission["tasks"].get("operator"):
            self.bus.reply(ATLAS, mission["tasks"]["operator"], "complete", self.phrase(ATLAS, summary), dict(checklist=checklist, missionState="completed"), deliver=False)
        self.step(self.mission(mission["id"]), ATLAS, summary, task_id=mission["tasks"].get("operator"))
        self.remember(mission, f"Declared readiness for mission {mission['id']}: {summary}")
        return self.mission(mission["id"])

    def fail(self, mission: dict, reason: str) -> dict:
        mission.update(state="failed", phase="done", failure=reason[:500])
        self.save(mission)
        if mission["tasks"].get("operator"):
            try:
                self.bus.reply(ATLAS, mission["tasks"]["operator"], "fail", self.phrase(ATLAS, f"Cannot clear {SITE_BY_ID[mission['siteId']]['name']} for restart; {reason}"),
                               dict(missionState="failed", failure=reason[:500]), deliver=False)
            except RealityError:
                pass
        self.step(self.mission(mission["id"]), ATLAS, f"Mission failed; {reason}", task_id=mission["tasks"].get("operator"))
        self.remember(mission, f"Mission {mission['id']} failed: {reason[:300]}")
        return self.mission(mission["id"])

    def ask_for_input(self, mission: dict, out_of_range: list) -> dict:
        """Step 4 branch: cross-site tasks to the other Wardens plus one owner question through the escalation path."""
        site = mission["siteId"]
        item, record, spec = out_of_range[0]
        unit = f" {record.get('unit')}" if record.get("unit") else ""
        for other in SITE_IDS:
            if other == site:
                continue
            text = self.phrase(ATLAS, f"Cross-site check: verify your {item['assetTag']} {item['attribute'].replace('_', ' ')} reading or serial; "
                                      f"{SITE_BY_ID[site]['name']} reads {record['value']}{unit} against spec {spec.get('min')}–{spec.get('max')}.")
            task = self.bus.send(ATLAS, warden_id(other), text, dict(missionId=mission["id"], kind="cross_site_check", assetTag=item["assetTag"],
                                                                 attribute=item["attribute"]), other, context_id=mission["contextId"])
            mission = self.mission(mission["id"])
            mission["tasks"]["crossSite"].append(task["id"])
            self.step(mission, ATLAS, f"Opened a cross-site check with {display_name(warden_id(other))} for {item['assetTag']}.{item['attribute']}.", task_id=task["id"])
        for entry in mission["items"]:
            if entry["assetTag"] == item["assetTag"] and entry["attribute"] == item["attribute"]:
                entry["crossChecked"] = True
        component = self.store.get("component", item["componentId"], site)
        work_item = self.reality.open_work_item_for(site, item["assetTag"], item["attribute"]) or \
            self.reality.create_work_item(site, component, item["attribute"], spec, f"atlas/mission:{mission['id']}", mission["budget"], state="needs_clarification")
        try:
            self.reality.escalate(work_item["id"], 4, note=f"Mission {mission['id']}: {item['assetTag']} {item['attribute']} = {record['value']}{unit} is outside spec. PROCEED or HOLD?")
        except RealityError:
            pass
        mission["tasks"]["ownerWorkItemId"] = work_item["id"]
        mission.update(state="input_required", phase="input_required")
        self.step(mission, ATLAS, f"Asked the owner one question on {work_item['reference']}: {item['assetTag']} {item['attribute']} = {record['value']}{unit} is outside spec.",
                  work_item_id=work_item["id"], attestation_id=item["attestationId"])
        return self.mission(mission["id"])

    # ---- reality listener (inbound evidence, expiry, owner decisions) --------------------------------------

    def on_reality_event(self, event: str, work_item: dict | None, extra: dict) -> None:
        if not work_item:
            return
        with self.lock:
            for mission, item in self.missions_for_work_item(work_item["id"]):
                self._on_work_item_event(event, work_item, extra, mission, item)

    def _on_work_item_event(self, event: str, work_item: dict, extra: dict, mission: dict, item: dict | None) -> None:
        with self.lock:
            if event == "owner_decision" and mission["tasks"].get("ownerWorkItemId") == work_item["id"]:
                decision = extra.get("decision") or work_item.get("ownerDecision", {}).get("decision")
                for entry in mission["items"]:
                    if entry["assetTag"] == work_item["assetTag"] and entry["attribute"] == work_item["attribute"]:
                        entry["ownerDecision"] = decision
                if not any(e.get("ownerDecision") for e in mission["items"]) and mission["items"]:
                    mission["items"][0]["ownerDecision"] = decision
                mission["phase"] = "checking"
                mission["state"] = "running"
                self.step(mission, ATLAS, f"Owner decided '{decision}' on {work_item['reference']}; continuing.", work_item_id=work_item["id"])
                self.remember(mission, f"Owner decided '{decision}' on {work_item['reference']} ({work_item['assetTag']}.{work_item['attribute']}).")
                self.advance(mission["id"])
                return
            if item is None or not item.get("runnerTaskId"):
                return
            task = self.store.get("a2a_task", item["runnerTaskId"])
            if not task or task["state"] in ("completed", "failed", "canceled"):
                return
            if event == "verdict":
                result = extra.get("result") or {}
                message = extra.get("message") or {}
                verdict = result.get("verdict")
                via = f"{message.get('channel') or 'local'} from {message.get('sender') or 'the technician'}"
                runner = task["target"]
                if verdict == "accepted":
                    self.bus.reply(runner, task["id"], "complete",
                                   self.phrase(runner, f"Evidence received {via} for {work_item['reference']}: accepted, attestation {result.get('attestationId')}."),
                                   dict(workItemId=work_item["id"], attestationId=result.get("attestationId"), verdict=verdict))
                else:
                    reasons = "; ".join(result.get("reasons") or [])[:300]
                    self.bus.reply(runner, task["id"], "progress",
                                   self.phrase(runner, f"Evidence received {via} for {work_item['reference']}: {verdict}: {reasons}. Still waiting."),
                                   dict(workItemId=work_item["id"], attestationId=result.get("attestationId"), verdict=verdict, reasons=result.get("reasons") or []))
            elif event == "expired":
                self.bus.reply(task["target"], task["id"], "fail", self.phrase(task["target"], f"{work_item['reference']} expired at its deadline with no accepted fact."),
                               dict(workItemId=work_item["id"], verdict="expired"))


class AtlasHandler:
    def __init__(self, engine: MissionEngine):
        self.engine = engine

    def on_task(self, task: dict) -> None:
        """A mission request addressed to Atlas (local operator task or an external A2A caller)."""
        steward = task.get("steward") or {}
        if steward.get("missionId") or steward.get("goal") != "clear_for_restart":
            return
        site = steward.get("siteId") or task.get("siteId")
        mission = self.engine.start(site, "clear_for_restart", float(steward.get("budget") or 0), task["caller"], steward.get("assetTags"))
        self.engine.bus.reply(ATLAS, task["id"], "progress", f"Mission {mission['id']} started for {site}.", dict(missionId=mission["id"]), deliver=False)

    def on_reply(self, task: dict, message: dict, intent: str) -> None:
        engine = self.engine
        with engine.lock:
            mission = engine.mission_for_task(task)
            if not mission or mission["state"] not in OPEN_MISSION:
                return
            kind = (task.get("steward") or {}).get("kind")
            text = " ".join(str(p.get("text")) for p in message["parts"] if p.get("text"))
            if kind == "cross_site_check":
                engine.step(mission, task["target"], text, task_id=task["id"])
                return
            if intent == "progress":
                engine.step(mission, task["target"], text, task_id=task["id"])
                return
            if intent == "fail":
                engine.step(mission, task["target"], text, task_id=task["id"])
                mission = engine.mission(mission["id"])
                missing = ", ".join(f"{i['assetTag']}.{i['attribute']} ({i['status']})" for i in mission["items"] if i["status"] not in TERMINAL_ITEM)
                engine.fail(mission, (f"missing: {missing}; " if missing else "") + text)
                return
            if intent == "complete":
                engine.step(mission, task["target"], text, task_id=task["id"])
                mission = engine.mission(mission["id"])
                mission["phase"] = "checking"
                engine.save(mission)
                engine.advance(mission["id"])


class ManagerHandler:
    """The Plant Manager approves the restart-set work order within the site budget, hands it to the Site Engineer and
    relays the engineer's reports to the director's task."""

    def __init__(self, engine: MissionEngine):
        self.engine = engine

    @staticmethod
    def limit() -> float:
        try:
            return float(env("STEWARD_WORK_ORDER_LIMIT_USD", "500"))
        except ValueError:
            return 500.0

    def on_task(self, task: dict) -> None:
        engine, bus = self.engine, self.engine.bus
        steward = task.get("steward") or {}
        me = task["target"]
        site = task["siteId"]
        if steward.get("kind") in ("board_meeting", "call", "document_delivery", "notification"):
            return  # conversations and broadcasts are replied by their runners
        if steward.get("kind") != "delegate_restart_set":
            bus.reply(me, task["id"], "fail", f"{display_name(me)} takes restart sets, calls and maintenance requests.", dict(status="unsupported"))
            return
        with engine.lock:
            mission = engine.mission_for_task(task)
            if not mission:
                bus.reply(me, task["id"], "fail", "No mission is attached to this task.", {})
                return
            authorize(me, "approve_work_order", site)
            requested = float(steward.get("budget") or 0)
            approved = min(requested, self.limit())
            note = "" if approved == requested else f" (capped at the site work-order limit {self.limit():g} USD)"
            bus.reply(me, task["id"], "progress", engine.phrase(me, f"Work order approved: {approved:g} USD per item{note}. Handing the restart set to "
                                                                  f"{display_name(warden_id(site))}."), dict(status="approved", approvedBudget=approved))
            engine.step(engine.mission(mission["id"]), me, f"Approved the restart-set work order at {approved:g} USD per item{note}.", task_id=task["id"])
            text = engine.phrase(me, f"Resolve the restart set for {SITE_BY_ID[site]['name']}: {', '.join(steward.get('attributes') or [])}. "
                                     f"Approved budget {approved:g} USD per item.")
            warden_task = bus.send(me, warden_id(site), text, dict(missionId=mission["id"], kind="resolve_restart_set", budget=approved,
                                                                  attributes=steward.get("attributes") or []), site, context_id=mission["contextId"], deliver=False)
            mission = engine.mission(mission["id"])
            mission["tasks"]["warden"] = warden_task["id"]
            engine.step(mission, me, f"Delegated the restart set to {display_name(warden_id(site))}.", task_id=warden_task["id"])
        bus.handler_for(warden_id(site)).on_task(bus.task(warden_task["id"]))

    def on_reply(self, task: dict, message: dict, intent: str) -> None:
        engine, bus = self.engine, self.engine.bus
        mission = engine.mission_for_task(task)
        if not mission or mission["state"] not in OPEN_MISSION or (task.get("steward") or {}).get("kind") != "resolve_restart_set":
            return
        up = mission["tasks"].get("manager")
        if not up:
            return
        up_task = bus.task(up)
        if up_task["state"] in ("completed", "failed", "canceled"):
            return
        from .a2a import steward_data
        text = " ".join(str(p.get("text")) for p in message["parts"] if p.get("text"))
        data = {k: v for k, v in steward_data(message["parts"]).items() if k not in ("from", "to", "messageId")}
        bus.reply(task["caller"], up, intent, engine.phrase(task["caller"], f"{display_name(task['target'])} reports: {text}"), data)


class WardenHandler:
    def __init__(self, engine: MissionEngine):
        self.engine = engine

    def on_task(self, task: dict) -> None:
        engine, bus = self.engine, self.engine.bus
        steward = task.get("steward") or {}
        site = task["siteId"]
        me = task["target"]
        if steward.get("kind") in ("board_meeting", "call", "notification"):
            return  # conversation and broadcast runners record this engineer's reply
        if steward.get("kind") == "document_delivery":
            people = getattr(engine.service, "people", None)
            if people is None or not steward.get("documentId"):
                bus.reply(me, task["id"], "fail", "No document attached to this delivery.", dict(status="failed"))
                return
            try:
                review = people.review_document(steward["documentId"], me)
                bus.reply(me, task["id"], "complete", f"Filed {steward['documentId']}; review verdict {review['verdict']}.",
                          dict(documentId=steward["documentId"], verdict=review["verdict"]))
            except RealityError as error:
                bus.reply(me, task["id"], "fail", f"Could not file the document: {error.detail}", dict(status="failed"))
            return
        if steward.get("kind") == "cross_site_check":
            authorize(me, "resolve", site)
            try:
                result = engine.reality.resolve(site, steward["assetTag"], steward["attribute"], budget=0, requester=me)
            except RealityError as error:
                bus.reply(me, task["id"], "complete", engine.phrase(me, f"No comparable fact at {SITE_BY_ID[site]['name']}: {error.detail}"), dict(status="unsupported"))
                return
            if result["status"] in ("known", "stale"):
                unit = f" {result.get('unit')}" if result.get("unit") else ""
                bus.reply(me, task["id"], "complete", engine.phrase(me, f"{SITE_BY_ID[site]['name']} {steward['assetTag']}.{steward['attribute']} = {result['value']}{unit} "
                                                                       f"({result['status']}, attestation {result['attestationId']})."),
                          dict(status=result["status"], value=result.get("value"), attestationId=result.get("attestationId")))
            else:
                bus.reply(me, task["id"], "complete", engine.phrase(me, f"{SITE_BY_ID[site]['name']} has no fact for {steward['assetTag']}.{steward['attribute']}."),
                          dict(status=result["status"]))
            return
        if steward.get("kind") != "resolve_restart_set":
            bus.reply(me, task["id"], "fail", f"{display_name(me)} only handles resolve-fact and cross-site checks.", dict(status="unsupported"))
            return
        with engine.lock:
            mission = engine.mission_for_task(task)
            if not mission:
                bus.reply(me, task["id"], "fail", "No mission is attached to this task.", {})
                return
            budget = min(float(steward.get("budget") or 0), mission["budget"])
            pending = [(i["assetTag"], i["attribute"]) for i in mission["items"] if i["status"] == "pending"]
            for asset_tag, attribute in pending:
                mission = engine.mission(mission["id"])  # re-read after every reply; handlers checkpoint the record
                item = engine.item_for(mission, asset_tag, attribute)
                if item["status"] != "pending":
                    continue
                authorize(me, "resolve", site)
                result = engine.reality.resolve(site, item["assetTag"], item["attribute"], budget=0, requester=me)
                if result["status"] == "known":
                    item.update(status="known", value=result["value"], unit=result.get("unit"), attestationId=result["attestationId"])
                    engine.save(mission)
                    unit = f" {result.get('unit')}" if result.get("unit") else ""
                    bus.reply(me, task["id"], "progress", engine.phrase(me, f"{item['assetTag']}.{item['attribute']} is known: {result['value']}{unit} "
                                                                           f"(attestation {result['attestationId']}, {result['ageSeconds']} s old)."),
                              dict(assetTag=item["assetTag"], attribute=item["attribute"], attestationId=result["attestationId"], status="known"))
                    mission = engine.mission(mission["id"])
                    continue
                if result["status"] == "conflict":
                    item.update(status="waiting", reason="conflicting facts", workItemId=result.get("workItemId"), reference=result.get("reference"))
                authorize(me, "delegate_field", site)
                detail = {"unknown": "no fact on record", "stale": f"last value {result.get('value')} is stale", "conflict": "conflicting facts"}[result["status"]]
                text = engine.phrase(me, f"Collect {item['attribute'].replace('_', ' ')} for {item['assetTag']} at {SITE_BY_ID[site]['name']}: {detail}. Budget {budget:g} USD.")
                engine.save(mission)
                runner = technician_id(site)
                runner_task = bus.send(me, runner, text, dict(missionId=mission["id"], kind="collect", assetTag=item["assetTag"], attribute=item["attribute"],
                                                             budget=budget, wardenTaskId=task["id"]), site, context_id=mission["contextId"], deliver=False)
                mission = engine.mission(mission["id"])
                entry = engine.item_for(mission, item["assetTag"], item["attribute"])
                entry["runnerTaskId"] = runner_task["id"]
                if entry["status"] == "pending":
                    entry["status"] = "waiting"
                engine.step(mission, me, f"Delegated collection of {item['assetTag']}.{item['attribute']} to {display_name(runner)} ({detail}).", task_id=runner_task["id"],
                            work_item_id=entry.get("workItemId"))
                bus.handler_for(runner).on_task(bus.task(runner_task["id"]))  # delivered after the checkpoint so the reply finds the item
                mission = engine.mission(mission["id"])
            self.report(mission, task)

    def report(self, mission: dict, warden_task: dict) -> None:
        """Reply to Atlas with the current tally; `complete` once every item carries an accepted attestation."""
        engine, bus = self.engine, self.engine.bus
        me = warden_task["target"]
        task = bus.task(warden_task["id"])
        if task["state"] in ("completed", "failed", "canceled"):
            return
        known = [i for i in mission["items"] if i["status"] in TERMINAL_ITEM]
        waiting = [i for i in mission["items"] if i["status"] not in TERMINAL_ITEM]
        if not waiting:
            attestations = [i["attestationId"] for i in mission["items"] if i.get("attestationId")]
            bus.reply(me, task["id"], "complete", engine.phrase(me, f"Restart set resolved for {SITE_BY_ID[mission['siteId']]['name']}: {len(known)} attribute(s) with signed attestations."),
                      dict(attestationIds=attestations, status="resolved"))
        else:
            bus.reply(me, task["id"], "progress", engine.phrase(me, f"{len(known)} known, {len(waiting)} waiting for field evidence: "
                                                                   + ", ".join(f"{i['assetTag']}.{i['attribute']}" for i in waiting) + "."),
                      dict(status="waiting", waiting=[f"{i['assetTag']}.{i['attribute']}" for i in waiting]))

    def on_reply(self, task: dict, message: dict, intent: str) -> None:
        """Runner reported on a collect task: dispatch details, a verdict, or expiry."""
        engine = self.engine
        from .a2a import steward_data
        data = steward_data(message["parts"])
        with engine.lock:
            mission = engine.mission_for_task(task)
            if not mission or mission["state"] not in OPEN_MISSION:
                return
            item = next((i for i in mission["items"] if i.get("runnerTaskId") == task["id"]), None)
            if item is None:
                return
            me = task["caller"]
            text = " ".join(str(p.get("text")) for p in message["parts"] if p.get("text"))
            if data.get("workItemId"):
                item["workItemId"] = data["workItemId"]
                item["reference"] = data.get("reference") or item.get("reference")
            verdict = data.get("verdict")
            # The Runner's words are the Runner's step; the Warden's verification verdict is the Warden's step.
            engine.step(mission, task["target"], text, task_id=task["id"], work_item_id=item.get("workItemId"), attestation_id=data.get("attestationId"))
            mission = engine.mission(mission["id"])
            item = next(i for i in mission["items"] if i.get("runnerTaskId") == task["id"])
            if intent == "complete" and data.get("attestationId"):
                record = engine.reality.check_attestation(data["attestationId"])
                item.update(status="accepted", attestationId=data["attestationId"], value=record["value"], unit=record.get("unit"), reason=None)
                engine.step(mission, me, f"Verified {item['reference'] or item['assetTag']}: accepted, signed attestation {data['attestationId']} ({'valid' if record['valid'] else 'INVALID signature'}).",
                            task_id=task["id"], work_item_id=item.get("workItemId"), attestation_id=data["attestationId"])
            elif intent == "fail":
                item.update(status="expired" if verdict == "expired" else "failed", reason=text[:300])
            elif verdict in ("rejected", "needs_clarification"):
                item.update(status="rejected", reason="; ".join(data.get("reasons") or [])[:300], attestationId=None)
                engine.step(mission, me, f"Verification {verdict} for {item['reference'] or item['assetTag']}: {item['reason']}. Keeping the work item open.",
                            task_id=task["id"], work_item_id=item.get("workItemId"), attestation_id=data.get("attestationId"))
            else:
                item["status"] = "waiting" if item["status"] == "pending" else item["status"]
            engine.save(mission)
            warden_task_id = mission["tasks"].get("warden")
            if warden_task_id and (intent != "progress" or verdict):
                self.report(engine.mission(mission["id"]), engine.bus.task(warden_task_id))
            if intent == "fail":
                mission = engine.mission(mission["id"])
                if mission["state"] in OPEN_MISSION:
                    warden_task = engine.bus.task(warden_task_id) if warden_task_id else None
                    if warden_task and warden_task["state"] not in ("completed", "failed", "canceled"):
                        engine.bus.reply(me, warden_task_id, "fail", engine.phrase(me, f"Cannot complete the restart set: {text}"), dict(status="failed"))


class RunnerHandler:
    def __init__(self, engine: MissionEngine):
        self.engine = engine

    def on_task(self, task: dict) -> None:
        engine, bus = self.engine, self.engine.bus
        steward = task.get("steward") or {}
        site = task["siteId"]
        if steward.get("kind") in ("board_meeting", "call", "document_delivery", "notification"):
            return
        if steward.get("kind") != "collect":
            bus.reply(task["target"], task["id"], "fail", "The field technician only handles collect tasks (dispatch-technician, collect-evidence).", dict(status="unsupported"))
            return
        me = task["target"]
        authorize(me, "dispatch", site)
        budget = float(steward.get("budget") or 0)
        result = engine.reality.resolve(site, steward["assetTag"], steward["attribute"], None, budget=budget if budget > 0 else 1,
                                        requester=f"{me}/mission:{steward.get('missionId')}")
        if result["status"] == "known":
            bus.reply(me, task["id"], "complete", engine.phrase(me, f"{steward['assetTag']}.{steward['attribute']} already has a fresh fact (attestation {result['attestationId']})."),
                      dict(attestationId=result["attestationId"], verdict="accepted"))
            return
        if not result.get("workItemId"):
            bus.reply(me, task["id"], "fail", engine.phrase(me, f"Could not open a work item for {steward['assetTag']}.{steward['attribute']}: {result['nextStep']}"), dict(status="failed"))
            return
        item = engine.reality.work_item(result["workItemId"])
        last = item["dispatches"][-1] if item["dispatches"] else None
        how = f"via {last['channel']} to {last['to'] or 'the local task card'}" if last else "without a dispatch"
        delivered = " (provider receipt recorded)" if last and last.get("providerRef") else " (no provider receipt; local card)" if last else ""
        bus.reply(me, task["id"], "progress", engine.phrase(me, f"Dispatched {item['reference']} {how}{delivered}; waiting for the technician's reply."),
                  dict(workItemId=item["id"], reference=item["reference"], state=item["state"], channel=last["channel"] if last else None))

    def on_cancel(self, task: dict) -> None:
        return
