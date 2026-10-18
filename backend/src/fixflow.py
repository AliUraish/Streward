"""The fix workflow (contract 4 §6, simulated by default): `POST /api/issues/{id}/fix` (operator) plays six steps
with compressed timing; every step is a Change of type `fix` (wait event `fix.step`).

1. Evidence: the site engineer drives the agent eye to the asset (`go_to`, then `orbit`) and the frames are attached
   to the issue. Without an open renderer (and no headless worker) the step records that no frame was available.
2. Call: the engineer calls the plant manager (a `call` conversation over A2A); the manager decides and assigns the
   responsible person from the crew table; the compliance officer adds the regulation reason.
3. Contact: the field technician opens a work item and contacts that person through the dispatch line. Synthetic
   crew are never contacted (recorded only); the duty engineer (the user) gets a live SMS only in live mode
   (`STEWARD_ALLOW_EXTERNAL_MESSAGES`, `STEWARD_ALLOW_NOTICE_SMS`, an allowlisted number and Inkbox configured).
4. Fix: the person's reply arrives: simulated after a delay with a labelled synthetic photo and reading, or the user's
   real reply in live mode (the workflow waits for the work item to resolve, up to `STEWARD_FIX_LIVE_TIMEOUT_SECONDS`).
5. Verify: the reply went through the six verification checks and was signed; the engineer re-checks the
   attestation (and takes a fresh eye frame when a renderer is open), the compliance officer closes the obligation,
   the issue is resolved.
6. Inform: the manager posts the resolution; a `notification` goes to every person on the site roster (records only
   for synthetic crew) and, over A2A, to the other agents.
"""
from __future__ import annotations

import io
import threading
from datetime import datetime, timezone

from .agents import DIRECTOR, authorize, compliance_id, display_name, engineer_id, manager_id, site_team, technician_id
from .conversations import fill
from .env import env
from .errors import RealityError
from .sites import SITE2
from .specs import SPECS, spec_for, spec_kind, specs_of
from .store import now, uid
from .synthetic import by_id

STEPS = ("evidence", "call", "contact", "fix", "verify", "inform")
DELAYS = (0.0, 4.0, 4.0, 15.0, 4.0, 3.0)  # demo seconds before each step at speed 1
FIX_PLANS = {
    "overpressure": dict(attribute="pressure_bar", value=3.1, reply="{assetTag} reads 3.1 bar after isolating at V-501 and recharging TK-201 to 1.5 bar."),
    "sump_overflow": dict(attribute="level_pct", value=61, reply="{assetTag} down to 61 % with P-104 running; P-103 float switch freed."),
    "inspection_overdue": dict(attribute="inspection_tag_date", value="{today}", reply="{assetTag} inspected and tag signed {today}."),
    "certificate_expired": dict(attribute="inspection_certificate", value="{prefix}-WSE-{tagCompact}-{year}",
                                reply="{assetTag} examined; new certificate {prefix}-WSE-{tagCompact}-{year} issued."),
    "valve_not_fixed": dict(attribute="position", value="open", reply="{assetTag} handwheel refitted; valve reads open."),
    "valve_uncertain": dict(attribute="position", value="open", reply="{assetTag} checked by hand; valve reads open."),
    "document_injection": dict(attribute="position", value="open", reply="Clean service report resubmitted; {assetTag} checked, valve open."),
    # Contract 5 (Tomioka): the conservator's dehumidifier fix, the clamp-mount decision on BW-251, the route-closure drill.
    "humidity_high": dict(attribute="humidity_pct", value=58, reply="{assetTag} reads 58 % RH: the conservator started DH-1101 and closed the north windows; "
                                                                    "trusses and reeling machines checked, no mould."),
    "alteration_permit": dict(attribute="condition", value="sound", reply="{assetTag} checked: no drilling, sensors on non-invasive clamp mounts; "
                                                                          "brick fabric sound, permission request filed for the cable entry."),
    "visitor_route": dict(attribute="clear", value="yes", reply="{assetTag} closure procedure posted and drilled; barrier and signage checked, route clear."),
}


def synthetic_photo(lines: list[str]) -> bytes:
    """A small labelled JPEG standing in for the technician's photo (never presented as a real photograph)."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (480, 320), (34, 34, 34))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 479, 36], fill=(140, 40, 24))
    draw.text((12, 10), "SYNTHETIC EVIDENCE - NOT A REAL PHOTOGRAPH", fill=(255, 255, 255))
    for index, line in enumerate(lines[:10]):
        draw.text((12, 56 + index * 24), line[:70], fill=(235, 235, 235))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


class FixWorkflowService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self._stop = threading.Event()
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.RLock()
        if service.start_workers:
            self.recover()

    def recover(self) -> int:
        """A workflow left `running` by an earlier backend process has no thread any more: mark it interrupted, so the issue
        can be fixed again and the scenario autoplayer does not wait on it."""
        count = 0
        for workflow in self.store.all("fix_workflow"):
            if workflow.get("state") == "running":
                workflow.update(state="failed", finishedAt=now(), error="Interrupted by a backend restart; start the fix again.")
                self.store.put("fix_workflow", workflow, workflow["siteId"])
                count += 1
        return count

    def close(self):
        self._stop.set()
        for thread in list(self.threads.values()):
            if thread.is_alive():
                thread.join(timeout=2)

    # ---- records -----------------------------------------------------------------------------------------

    def get(self, workflow_id: str) -> dict:
        record = self.store.get("fix_workflow", workflow_id)
        if not record:
            raise RealityError("Fix workflow not found.", "NOT_FOUND", "Start one with POST /api/issues/{id}/fix.", 404)
        return record

    def list(self, site_id: str | None = None, issue_id: str | None = None) -> list[dict]:
        records = self.store.all("fix_workflow", site_id) if site_id else self.store.all("fix_workflow")
        if issue_id:
            records = [r for r in records if r["issueId"] == issue_id]
        return sorted(records, key=lambda r: r["startedAt"], reverse=True)

    def _save(self, workflow: dict) -> dict:
        workflow["updatedAt"] = now()
        self.store.put("fix_workflow", workflow, workflow["siteId"])
        return workflow

    def _step(self, workflow: dict, name: str, summary: str, **refs) -> dict:
        workflow["steps"].append(dict(n=len(workflow["steps"]) + 1, name=name, at=now(), summary=summary[:400], refs={k: v for k, v in refs.items() if v}))
        self._save(workflow)
        self.service.reality.emit_change(workflow["siteId"], "fix", workflow["id"], f"Fix {workflow['assetTag'] or workflow['issueId']} step {len(workflow['steps'])} "
                                         f"({name}): {summary[:300]}", workflow.get("assetTag"),
                                         extra=dict(workflowId=workflow["id"], issueId=workflow["issueId"], step=len(workflow["steps"]), name=name, status="step"))
        return workflow

    def notifications(self, site_id: str | None = None) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        records = self.store.all("notification", site_id) if site_id else self.store.all("notification")
        return sorted(records, key=lambda r: r["at"], reverse=True)

    # ---- start ---------------------------------------------------------------------------------------------

    def start(self, issue_id: str, actor: str, speed: float | None = None) -> dict:
        actor = authorize(actor, "start_fix")
        issues = self.service.issues
        issue = issues.get(issue_id)
        if issue.get("status") not in (None, "open"):
            raise RealityError(f"Issue {issue_id} is {issue.get('status')}.", "ISSUE_CLOSED", "Only open issues can be fixed.", 409)
        site = issue["siteId"]
        with self.lock:
            running = [w for w in self.list(site, issue_id) if w["state"] == "running"]
            if running:
                return running[0]
            if issue.get("source") == "computed":
                issue = issues.raise_issue(site, issue["kind"], issue["severity"], issue["summary"], asset_tag=issue.get("assetTag"), issue_id=issue["id"],
                                           source="computed", ref_id=issue.get("refId"), synthetic=bool(issue.get("simulated")), actor=engineer_id(site))
            speed = float(env("STEWARD_FIX_SPEED", "1")) if speed is None else float(speed)
            if speed < 0 or speed > 1000:
                raise RealityError("speed must be between 0 and 1000.", "INVALID_REQUEST", "0 plays every step at once.")
            workflow = dict(id=uid("fix"), issueId=issue["id"], siteId=site, assetTag=issue.get("assetTag"), kind=issue["kind"], state="running", speed=speed,
                            startedBy=actor, startedAt=now(), finishedAt=None, steps=[], live=False, evidence=None, conversationId=None, crewMemberId=None,
                            noticeId=None, workItemId=None, attestationId=None, notificationIds=[], regulationIds=[], error=None, synthetic=True)
            self._save(workflow)
        self.service.reality.emit_change(site, "fix", workflow["id"], f"Fix workflow started for {issue.get('assetTag') or issue['id']} ({issue['kind']}).",
                                         issue.get("assetTag"), extra=dict(workflowId=workflow["id"], issueId=issue["id"], step=0, status="started"))
        if self.service.start_workers and speed > 0:
            thread = threading.Thread(target=self._guarded, args=(workflow["id"], True), name=f"steward-fix-{workflow['id']}", daemon=True)
            self.threads[workflow["id"]] = thread
            thread.start()
        else:
            self.run(workflow["id"], realtime=False)
        return self.get(workflow["id"])

    def _guarded(self, workflow_id: str, realtime: bool):
        try:
            self.run(workflow_id, realtime)
        except Exception as error:
            workflow = self.store.get("fix_workflow", workflow_id)
            if workflow and workflow["state"] == "running":
                workflow.update(state="failed", error=f"{type(error).__name__}: {str(error)[:200]}", finishedAt=now())
                self._save(workflow)

    def run(self, workflow_id: str, realtime: bool = False) -> dict:
        for index, name in enumerate(STEPS):
            workflow = self.get(workflow_id)
            if workflow["state"] != "running":
                return workflow
            if realtime and DELAYS[index] and workflow["speed"] > 0 and self._stop.wait(DELAYS[index] / workflow["speed"]):
                return workflow
            try:
                getattr(self, f"step_{name}")(self.get(workflow_id))
            except RealityError as error:
                workflow = self.get(workflow_id)
                workflow.update(state="failed", error=f"{name}: {error.detail}"[:300], finishedAt=now())
                self._save(workflow)
                self._step(workflow, name, f"Stopped: {error.detail}")
                return workflow
            if self.get(workflow_id)["state"] != "running":
                return self.get(workflow_id)
        workflow = self.get(workflow_id)
        workflow.update(state="completed", finishedAt=now())
        self._save(workflow)
        self.service.reality.emit_change(workflow["siteId"], "fix", workflow["id"], f"Fix workflow completed for {workflow['assetTag'] or workflow['issueId']}.",
                                         workflow.get("assetTag"), extra=dict(workflowId=workflow["id"], issueId=workflow["issueId"], step=len(STEPS), status="completed"))
        return workflow

    # ---- steps ---------------------------------------------------------------------------------------------

    def _issue(self, workflow: dict) -> dict:
        return self.service.issues.stored(workflow["issueId"])

    def step_evidence(self, workflow: dict):
        site, tag = workflow["siteId"], workflow.get("assetTag")
        eye = self.service.eye
        engineer = engineer_id(site)
        frames, detail = [], None
        if not tag:
            detail = "No asset on this issue; no eye frame."
        elif not eye.fresh(site) and not eye.worker.enabled:
            detail = "No renderer open and the headless worker is off; evidence frame skipped (open /eye?site=... to watch)."
        else:
            try:
                timeout = float(env("STEWARD_FIX_EYE_TIMEOUT", "20"))
                looked = eye.act_sync(site, "go_to", dict(assetTag=tag), engineer, timeout=timeout)
                frames.append(looked["frameId"])
                orbit = eye.act_sync(site, "orbit", dict(assetTag=tag, frames=4), engineer, timeout=timeout + 6)
                frames += [f["frameId"] for f in orbit.get("frames", [])]
            except RealityError as error:
                detail = f"Eye unavailable: {error.detail[:200]}"
        issue = self._issue(workflow)
        if frames:
            issue["evidenceFrameIds"] = list(dict.fromkeys((issue.get("evidenceFrameIds") or []) + frames))
            self.service.issues._save(issue, f"Eye evidence attached to {issue['id']}: {len(frames)} frame(s) of {tag}.", engineer)
        workflow = self.get(workflow["id"])
        workflow["evidence"] = dict(frameIds=frames, detail=detail, renderedFrom="hosted third-party capture" if frames else None)
        self._save(workflow)
        self._step(workflow, "evidence", (f"{display_name(engineer)} captured {len(frames)} frame(s) of {tag} with the agent eye." if frames
                                          else f"{display_name(engineer)}: {detail}"),
                   frameIds=frames or None)

    def step_call(self, workflow: dict):
        site = workflow["siteId"]
        issue = self._issue(workflow)
        people, regulations = self.service.people, self.service.regulations
        crew = people.responsible_crew(site, issue["kind"])
        if crew is None:
            duty = next((c for c in self.store.all("crew_member", site) if c.get("contact") == "user"), None)
            crew = people.crew_public(duty) if duty else None
        if crew is None:
            raise RealityError("Nobody on the crew table owns this issue.", "NO_OWNER", "Add an owner to the crew table.")
        regulation_ids = regulations.for_issue(issue)
        obligation = self.store.get("obligation", issue.get("obligationId") or "", site) if issue.get("obligationId") else None
        reason = regulations.reason_text(regulation_ids, f"{issue['kind'].replace('_', ' ')} must be put right under the site's duties (demo rule pack).")
        evidence = workflow.get("evidence") or {}
        template = by_id("conversations")["cv-fix-call"]
        roles = dict(engineer=engineer_id(site), manager=manager_id(site), compliance=compliance_id(site), technician=technician_id(site))
        turns = [dict(speaker=roles[t["speakerRole"]], to=roles[t["toRole"]], text=t["text"]) for t in template["turns"]]
        context = dict(assetTag=issue.get("assetTag") or "site", issueSummary=issue["summary"], issueKind=issue["kind"].replace("_", " "),
                       evidence=(f"{len(evidence.get('frameIds') or [])} frame(s) attached" if evidence.get("frameIds") else (evidence.get("detail") or "none")),
                       crewName=crew["name"], crewRole=crew["role"], regulationReason=reason, obligationTitle=(obligation or {}).get("title") or "the issue")
        conversation = self.service.conversations.call(roles["engineer"], roles["manager"], fill(template["topic"], context), turns,
                                                       participants=[roles["compliance"]], site_ids=[site], issue_id=issue["id"], issue_kind=issue["kind"],
                                                       context=context, summary=template["summary"], summary_by="hand-seed", workflow_id=workflow["id"])
        self.service.issues.assign(issue["id"], crew["id"], roles["manager"])
        workflow = self.get(workflow["id"])
        workflow.update(conversationId=conversation["id"], crewMemberId=crew["id"], regulationIds=regulation_ids)
        self._save(workflow)
        self._step(workflow, "call", f"{display_name(roles['engineer'])} called {display_name(roles['manager'])}; assigned {crew['name']} ({crew['role']}); "
                                     f"{display_name(roles['compliance'])}: {reason[:160]}", conversationId=conversation["id"], crewMemberId=crew["id"])

    def _plan(self, workflow: dict) -> tuple[dict, str, object, str]:
        site, tag = workflow["siteId"], workflow.get("assetTag")
        component = self.service.reality.component_by_tag(site, tag)
        today = datetime.now(timezone.utc).date().isoformat()
        context = dict(assetTag=component["tag"], today=today, year=str(datetime.now(timezone.utc).year), tagCompact=component["tag"].replace("-", ""),
                       prefix=SITE2.get(site, site[:2].upper()))
        plan = FIX_PLANS.get(workflow["kind"])
        table = specs_of(component)
        if not plan or plan["attribute"] not in table:
            attribute = next((a for a, s in table.items() if s["attributeClass"] in ("reading", "condition")), None) or next(iter(table), None)
            if not attribute:
                raise RealityError(f"{component['tag']} has no attribute to verify.", "INVALID_REQUEST", "Fix this issue by hand.")
            spec = table[attribute]
            if spec.get("min") is not None:
                value = round((spec["min"] + spec["max"]) / 2, 1)
            elif spec.get("enum"):
                value = next((v for v in ("normal", "yes", "open", "on") if v in spec["enum"]), spec["enum"][0])
            else:
                value = f"{context['prefix']}-{context['tagCompact']}-FIX-{today}"
            plan = dict(attribute=attribute, value=value, reply=f"{{assetTag}} {attribute.replace('_', ' ')} now {value}.")
        value = fill(plan["value"], context) if isinstance(plan["value"], str) else plan["value"]
        return component, plan["attribute"], value, fill(plan["reply"], context)

    def step_contact(self, workflow: dict):
        site = workflow["siteId"]
        issue = self._issue(workflow)
        technician = technician_id(site)
        reality = self.service.reality
        component, attribute, _, _ = self._plan(workflow)
        spec = spec_for(spec_kind(component), attribute)
        item = reality.open_work_item_for(site, component["tag"], attribute) or reality.create_work_item(site, component, attribute, spec,
                                                                                                         f"{technician}/fix:{workflow['id']}", 25)
        card = reality.task_card(item)
        reality.record_dispatch(item, "local", "", card, None, None, f"fix workflow {workflow['id']}: card for the crew member; contact goes through the dispatch line")
        item = reality.work_item(item["id"])
        item["state"] = "waiting"
        reality.save_work_item(item)
        text = (f"Steward fix for {component['tag']} at {self.service.require_property(site)['name']}: {issue['summary'][:200]} "
                f"Please put it right and reply with the {attribute.replace('_', ' ')} and a photo. Reference {item['reference']}.")
        notice = self.service.people.send_notice(site, technician, text, crew_member_id=workflow["crewMemberId"], issue_id=issue["id"], notice_kind="fix_contact")
        workflow = self.get(workflow["id"])
        workflow.update(noticeId=notice["id"], workItemId=item["id"], live=notice["mode"] == "sent", reference=item["reference"])
        self._save(workflow)
        self._step(workflow, "contact", f"{display_name(technician)} contacted {notice['toName']} through the dispatch line ({notice['mode']}); work item "
                                        f"{item['reference']}.", noticeId=notice["id"], workItemId=item["id"])

    def step_fix(self, workflow: dict):
        reality = self.service.reality
        item = reality.work_item(workflow["workItemId"])
        if workflow.get("live"):
            limit = float(env("STEWARD_FIX_LIVE_TIMEOUT_SECONDS", "900"))
            waited = 0.0
            while item["state"] not in ("resolved", "expired", "rejected") and waited < limit:
                if self._stop.wait(2):
                    return
                waited += 2
                item = reality.work_item(item["id"])
            if item["state"] != "resolved":
                raise RealityError(f"No verified reply on {item['reference']} within {limit:g} s.", "FIX_TIMEOUT", "Reply to the SMS with the reading, or rerun.")
            self._step(self.get(workflow["id"]), "fix", f"Live reply verified on {item['reference']}.", workItemId=item["id"], attestationId=item.get("attestationId"))
            return
        component, attribute, value, reply = self._plan(workflow)
        crew = self.store.get("crew_member", workflow["crewMemberId"], workflow["siteId"]) or {}
        photo = synthetic_photo([f"Asset {component['tag']} ({component['name']})", f"{attribute.replace('_', ' ')}: {value}", f"Reference {item['reference']}",
                                 f"Simulated reply from {crew.get('name', 'crew')}", f"Workflow {workflow['id']}"])
        message = dict(provider="local", channel="local", providerMessageId=uid("sim"), reference=item["reference"], body=f"[synthetic reply] {reply}",
                       statedTag=component["tag"], value=value, observedAt=None, sender=f"synthetic:{crew.get('id', 'crew')}", threadRef=None,
                       receivedAt=now(), subject="")
        result = reality.inbound(message, (f"synthetic-{component['tag']}-{workflow['id']}.jpg", photo))
        workflow = self.get(workflow["id"])
        workflow.update(reply=dict(simulated=True, body=message["body"], verdict=result.get("verdict"), attestationId=result.get("attestationId")))
        self._save(workflow)
        if result.get("verdict") != "accepted":
            raise RealityError(f"The simulated reply was {result.get('verdict')}: {'; '.join(result.get('reasons') or [])[:200]}", "FIX_REJECTED",
                               "Check the asset's spec and rerun.")
        self._step(workflow, "fix", f"{crew.get('name', 'Crew')} replied (simulated, synthetic photo): {reply[:200]}", workItemId=item["id"],
                   attestationId=result.get("attestationId"))

    def step_verify(self, workflow: dict):
        site = workflow["siteId"]
        reality = self.service.reality
        engineer, compliance = engineer_id(site), compliance_id(site)
        item = reality.work_item(workflow["workItemId"])
        if not item.get("attestationId"):
            raise RealityError("No accepted attestation to verify.", "FIX_UNVERIFIED", "Wait for a verified reply.")
        attestation = reality.check_attestation(item["attestationId"])
        if not attestation["valid"] or attestation["verdict"] != "accepted":
            raise RealityError("The attestation did not verify.", "FIX_UNVERIFIED", "Collect fresh evidence.")
        eye = self.service.eye
        frame_id = None
        if workflow.get("assetTag") and eye.fresh(site):
            try:
                frame_id = eye.act_sync(site, "go_to", dict(assetTag=workflow["assetTag"]), engineer, timeout=float(env("STEWARD_FIX_EYE_TIMEOUT", "20")))["frameId"]
            except RealityError:
                frame_id = None
        issue = self._issue(workflow)
        closed = None
        if issue.get("obligationId") and self.store.get("obligation", issue["obligationId"], site):
            closed = self.service.people.complete_obligation(issue["obligationId"], compliance, note=f"Closed after verified fix {workflow['id']}.")
            obligation_doc = closed.get("documentId")
            if obligation_doc and self.store.get("document", obligation_doc, site) and (self.store.get("document", obligation_doc, site) or {}).get("_body"):
                self.service.people.regenerate_document(obligation_doc)
        self.service.issues.resolve_issue(issue["id"], f"Fixed and verified: attestation {item['attestationId']} ({attestation['value']}).", engineer)
        workflow = self.get(workflow["id"])
        workflow["attestationId"] = item["attestationId"]
        self._save(workflow)
        self._step(workflow, "verify", f"{display_name(engineer)} verified attestation {item['attestationId']} (signature valid, {attestation['value']})"
                                       + (f"; fresh eye frame {frame_id}" if frame_id else "")
                                       + (f"; {display_name(compliance)} closed '{closed['title']}' (next due {closed['dueAt'][:10]})" if closed else "") + "; issue resolved.",
                   attestationId=item["attestationId"], frameId=frame_id, obligationId=(closed or {}).get("id"))

    def step_inform(self, workflow: dict):
        site = workflow["siteId"]
        manager = manager_id(site)
        issue = self._issue(workflow)
        text = f"Resolved: {issue.get('assetTag') or 'site'} {issue['kind'].replace('_', ' ')}. {issue['summary'][:160]} Verified by attestation {workflow.get('attestationId')}."
        ids = []
        for crew in self.store.all("crew_member", site):
            if crew.get("contact") == "user":
                notice = self.service.people.send_notice(site, manager, text, crew_member_id=crew["id"], issue_id=issue["id"], notice_kind="resolution")
                mode, channel, notice_id = notice["mode"], notice["channel"], notice["id"]
            else:
                mode, channel, notice_id = "record_only", None, None
            record = dict(id=uid("ntf"), siteId=site, workflowId=workflow["id"], issueId=issue["id"], sender=manager, toKind="crew", to=crew["id"],
                          toName=crew["name"], channel=channel, text=text, mode=mode, noticeId=notice_id, synthetic=True, at=now())
            self.store.put("notification", record, site)
            self.service.reality.mirror.put("notification", record, site)
            ids.append(record["id"])
        bus = self.service.bus
        for agent in [a for a in site_team(site) if a != manager] + [DIRECTOR]:
            task = bus.send(manager, agent, text, dict(kind="notification", issueId=issue["id"], workflowId=workflow["id"]), site, deliver=False)
            bus.reply(agent, task["id"], "complete", "Noted.", dict(kind="notification_ack"), deliver=False)
            record = dict(id=uid("ntf"), siteId=site, workflowId=workflow["id"], issueId=issue["id"], sender=manager, toKind="agent", to=agent,
                          toName=display_name(agent), channel="a2a", text=text, mode="sent", a2aTaskId=task["id"], transport=task["transport"],
                          synthetic=True, at=now())
            self.store.put("notification", record, site)
            self.service.reality.mirror.put("notification", record, site)
            ids.append(record["id"])
        self.service.memory.write(manager, f"Fix {workflow['id']} on {issue.get('assetTag')}: {text}", "decision", dict(issueId=issue["id"]), site, synthetic=True)
        workflow = self.get(workflow["id"])
        workflow["notificationIds"] = ids
        self._save(workflow)
        self._step(workflow, "inform", f"{display_name(manager)} posted the resolution: {len(ids)} notification(s) to the roster and the agents.",
                   notifications=len(ids))
