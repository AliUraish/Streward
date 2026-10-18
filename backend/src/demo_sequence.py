"""The live sequence (owner, Oct 18 2026): "agent calls me between 15-30 seconds for contract, emails me the files of compliance
and pictures, then messages me as an employee to tell me I am late and reports to the manager through agent2agent that I was late
and the manager records it; and in between, emails for something off in telemetry data, so it asks another site for their limits
and whether they are facing this. The demo is 2 minutes." Pacing (owner): person-facing items 30 s apart, the call first.

One run, everything real: the person-facing items go through the outbox and the person gate (switch off: recorded dry_run).

    T+0        Bristol's worst compliance finding (V-504, the blocked valve repair) from the records and the latest frames (the eye
               is not moved). The Plant Manager · Bristol's call to the contractor is queued at once and placed at
               T + STEWARD_LIVE_SEQUENCE_CALL_AT_SECONDS (12), so the phone rings about 15 to 25 s after the start.
    the call   meanwhile, not person-facing and not waiting: the Site Inspector ↔ Compliance Officer · Bristol chat (6 turns), the
               evidence email to the manager's mailbox, the Compliance Officer ↔ Plant Manager · Bristol chat (4 turns), and from
               T + STEWARD_LIVE_SEQUENCE_TELEMETRY_AT_SECONDS (20) the Myer excursion (PG-602 above its band) with the Plant
               Manager · Myer ↔ Plant Manager · Bristol chat about Bristol's limits.
    call end   the slot is booked (or the first one held) and the team is told; then each STEWARD_LIVE_SEQUENCE_GAP_SECONDS (30)
               after the previous person-facing item: (1) the owner email with the compliance file and the pictures, Compliance
               Counsel copied; (2) the People Officer's text to the employee (late today), then the A2A report to the Plant Manager ·
               Bristol, who records it on the badge log; (3) the Plant Manager · Myer's telemetry email; (4) the contractor
               confirmation, owner and Compliance Counsel copied (with the job pack when it was asked for on the call).

The outbox lets this run's items through without its own gaps and holds everything else while a run is active (outbox.paced_as);
the regular attendance and inspection loops skip meanwhile. Trigger: `POST /api/live-sequence` (the Owner's agent), or
`STEWARD_LIVE_SEQUENCE=auto`: one run `STEWARD_LIVE_SEQUENCE_DELAY_SECONDS` (20) after the backend starts, again every
`STEWARD_LIVE_SEQUENCE_EVERY_MINUTES` (0 = never). One run at a time. Record `live_sequence_run` {id, state, sites, steps: [{name,
at, summary, refs}], startedAt, finishedAt}; the run itself emits no dashboard changes (what people see is the real call, chats,
emails, text and A2A messages).
"""
from __future__ import annotations

import base64
import hashlib
import html as html_lib
import threading
import time
from datetime import datetime, timedelta, timezone

from .agents import COUNSEL, INSPECTOR, OPERATOR, PEOPLE, display_name, manager_id
from .chat_writer import TURN_OVERRIDE
from .compliance_alerts import local, lower_first, place_of, plural, query, short_site
from .env import env
from .errors import RealityError
from .maintenance_planner import city, tz_for
from .inspections import contractor_for
from .sites import SITE_BY_ID
from .frame_labels import labelled_bytes
from .store import now, uid
from .verify import iso, parse_time

KIND = "live_sequence_run"
BR, MY = "bristol-pumps", "myer-plant"
EMPLOYEE_PREFERRED = "crew-br-visitor-lead"  # Ama Owusu works Bristol's open days, Sunday included
LATE_MINUTES = 41
TELEMETRY_TAG, TELEMETRY_BASE = "PG-602", "pressure_bar"
SENSOR_REF = "feed:sensors"
SETTLED = ("sent", "dry_run", "capped", "failed", "canceled")
CALL_WAIT_MINUTES = 15.0  # a call that never reports back: the rest of the run goes ahead after this


def _number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(env(name, str(default)) or default)
    except ValueError:
        value = default
    return max(low, min(value, high))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def esc(text) -> str:
    return html_lib.escape(str(text or ""), quote=True)


class LiveSequence:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state: dict[str, dict] = {}  # run id -> in-memory progress (phase flags, the call, the telemetry result, threads)
        self.active_id: str | None = None
        self.last_error: str | None = None
        for record in query(self.store, KIND, "json_extract(body, '$.state') = 'running'"):  # a restart ends what was running
            record.update(state="failed", finishedAt=now(), error="Interrupted by a backend restart.")
            self.store.put(KIND, record, "")

    # ---- settings -----------------------------------------------------------------------------------------------------

    @staticmethod
    def mode() -> str:
        value = (env("STEWARD_LIVE_SEQUENCE", "off") or "off").strip().lower()
        return value if value in ("off", "auto") else "off"

    @staticmethod
    def gap() -> float:
        return _number("STEWARD_LIVE_SEQUENCE_GAP_SECONDS", 30.0, 0.0, 600.0)

    @staticmethod
    def call_at() -> float:
        return _number("STEWARD_LIVE_SEQUENCE_CALL_AT_SECONDS", 12.0, 0.0, 120.0)

    @staticmethod
    def telemetry_at() -> float:
        return _number("STEWARD_LIVE_SEQUENCE_TELEMETRY_AT_SECONDS", 20.0, 0.0, 600.0)

    @staticmethod
    def turn_seconds() -> float:
        return _number("STEWARD_LIVE_SEQUENCE_TURN_SECONDS", 2.0, 0.0, 30.0)

    @staticmethod
    def delay() -> float:
        return _number("STEWARD_LIVE_SEQUENCE_DELAY_SECONDS", 20.0, 0.0, 3600.0)

    @staticmethod
    def every() -> float:
        return _number("STEWARD_LIVE_SEQUENCE_EVERY_MINUTES", 0.0, 0.0, 1440.0)

    # ---- lifecycle ----------------------------------------------------------------------------------------------------

    def start(self) -> None:
        if not self.service.start_workers or self.mode() != "auto" or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._loop, name="steward-live-sequence", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(self.delay()):
            return
        while not self._stop.is_set():
            try:
                if self.mode() == "auto" and not self.active():
                    self.start_now()
            except Exception as error:  # the loop never dies
                self.last_error = f"{type(error).__name__}: {str(error)[:200]}"
            minutes = self.every()
            if minutes <= 0 or self._stop.wait(minutes * 60):
                return

    def active(self) -> bool:
        return self.active_id is not None

    # ---- records ------------------------------------------------------------------------------------------------------

    def get(self, run_id: str) -> dict:
        record = self.store.get(KIND, run_id, "")
        if not record:
            raise RealityError("Run not found.", "NOT_FOUND", "List runs with GET /api/live-sequence.", 404)
        return record

    def list(self, limit: int = 10) -> list[dict]:
        return query(self.store, KIND, order="json_extract(body, '$.startedAt') DESC", limit=max(1, min(int(limit or 10), 50)))

    def status(self) -> dict:
        return dict(mode=self.mode(), active=self.active(), activeRunId=self.active_id, gapSeconds=self.gap(), callAtSeconds=self.call_at(),
                    telemetryAtSeconds=self.telemetry_at(), turnSeconds=self.turn_seconds(), delaySeconds=self.delay(), everyMinutes=self.every(),
                    lastError=self.last_error, runs=self.list(5))

    def _save(self, record: dict) -> dict:
        self.store.put(KIND, record, "")
        return record

    def _step(self, run_id: str, name: str, summary: str, **refs) -> None:
        with self.lock:
            record = self.store.get(KIND, run_id, "")
            if not record:
                return
            record["steps"].append(dict(n=len(record["steps"]) + 1, name=name, at=now(), summary=summary[:400],
                                        refs={k: v for k, v in refs.items() if v not in (None, "", [], {})}))
            self._save(record)

    def _finish(self, run_id: str, state: str, error: str | None = None) -> None:
        with self.lock:
            record = self.store.get(KIND, run_id, "")
            if record and record.get("state") == "running":
                record.update(state=state, finishedAt=now(), error=error)
                self._save(record)
            if self.active_id == run_id:
                self.active_id = None

    # ---- start --------------------------------------------------------------------------------------------------------

    def start_now(self, actor: str = OPERATOR, contractor_site: str = MY, employee_site: str = BR, telemetry_site: str = BR,
                  realtime: bool | None = None) -> dict:
        """Start a run (or return the running one). With the workers the run plays on its own threads; otherwise inline."""
        for site in (contractor_site, employee_site, telemetry_site):
            self.service.require_property(site)
        if telemetry_site == contractor_site:
            raise RealityError("The telemetry site asks the contractor's site about its limits; pick two different sites.", "INVALID_REQUEST",
                               f"For example contractorSiteId {BR} and telemetrySiteId {MY}.")
        realtime = bool(self.service.start_workers) if realtime is None else realtime
        with self.lock:
            if self.active_id:
                return self.get(self.active_id)
            record = dict(id=uid("lsr"), state="running", actor=actor, sites=dict(contractor=contractor_site, employee=employee_site, telemetry=telemetry_site),
                          inspectionId=None, callId=None, steps=[], gapSeconds=self.gap(), startedAt=now(), finishedAt=None, error=None)
            self._save(record)
            self.active_id = record["id"]
            self.state[record["id"]] = dict(realtime=realtime, t0=time.monotonic(), phase1=False, call=None, phase2=False, telemetry=None,
                                            telemetry_thread=None, chat_thread=None, inspectionId=None, employee=None)
        if realtime:
            threading.Thread(target=self._phase1, args=(record["id"],), name="steward-live-sequence-run", daemon=True).start()
            return record
        self._phase1(record["id"])
        return self.get(record["id"])

    def _phase1(self, run_id: str) -> None:
        state = self.state[run_id]
        realtime = state["realtime"]
        record = self.get(run_id)
        sites = record["sites"]
        try:
            inspection = self._open_inspection(run_id, sites["contractor"])
            state["inspectionId"] = inspection["id"]
            with self.lock:
                fresh = self.get(run_id)
                fresh["inspectionId"] = inspection["id"]
                self._save(fresh)
            self._step(run_id, "finding", f"{display_name(INSPECTOR)}: {inspection['primary']['title']}", inspectionId=inspection["id"])
            not_before = iso(utcnow() + timedelta(seconds=self.call_at())) if realtime else None
            # The step first: a call that cannot be placed settles (and runs its handler) inside the request.
            self._step(run_id, "contractor_call", f"{display_name(manager_id(sites['contractor']))} is calling the contractor"
                                                  + (f", placed at {not_before[11:19]} UTC" if not_before else ""))
            with self.service.outbox.paced_as(run_id):
                self.service.inspections.step_contractor_call(inspection, realtime, priority=1, not_before=not_before,
                                                              extra_context=dict(liveSequenceRunId=run_id, noRetry=True))
            call_id = self.service.inspections.get(inspection["id"]).get("callId")
            with self.lock:
                fresh = self.get(run_id)
                fresh["callId"] = call_id
                for step in fresh["steps"]:
                    if step["name"] == "contractor_call":
                        step["refs"] = dict(step.get("refs") or {}, callId=call_id)
                self._save(fresh)
            if realtime:
                state["chat_thread"] = threading.Thread(target=self._safely, args=(run_id, self._site_chats, inspection["id"]), daemon=True,
                                                        name="steward-live-sequence-chats")
                state["telemetry_thread"] = threading.Thread(target=self._safely, args=(run_id, self._telemetry_later), daemon=True,
                                                             name="steward-live-sequence-telemetry")
                state["chat_thread"].start()
                state["telemetry_thread"].start()
            else:
                self._site_chats(run_id, inspection["id"])
                self._telemetry(run_id)
            with self.lock:
                state["phase1"] = True
                ready = state["call"] is not None
            if ready:
                self._phase2_start(run_id)
            elif realtime:
                threading.Thread(target=self._watch_call, args=(run_id,), daemon=True, name="steward-live-sequence-watch").start()
        except Exception as error:
            self._fail(run_id, error)

    def _safely(self, run_id: str, fn, *args) -> None:
        try:
            fn(run_id, *args)
        except Exception as error:  # a chat or the excursion failing never stops the run; the step says so
            self._step(run_id, "note", f"{fn.__name__.strip('_')} did not finish ({type(error).__name__}: {str(error)[:160]})")

    def _fail(self, run_id: str, error: Exception) -> None:
        detail = error.detail if isinstance(error, RealityError) else f"{type(error).__name__}: {str(error)[:200]}"
        self.last_error = detail
        self._step(run_id, "failed", detail)
        self._finish(run_id, "failed", detail)

    # ---- the finding (no eye moves) -----------------------------------------------------------------------------------

    def _open_inspection(self, run_id: str, site: str) -> dict:
        inspections = self.service.inspections
        inspection = dict(id=uid("insp"), siteId=site, siteName=self.service.require_property(site)["name"], inspectorId=INSPECTOR,
                          inspectorName=display_name(INSPECTOR), state="running", startedBy=OPERATOR, stops=[], findings=[], primary=None, alsoNoted=[],
                          steps=[], conversationIds=[], outboxIds=[], callId=None, callRequestedAt=None, windowId=None, slots=[], workKind=None,
                          contractor=None, issueId=None, summary=None, error=None, startedAt=now(), finishedAt=None, synthetic=True, liveSequenceRunId=run_id)
        inspections._save(inspection)
        inspections._change(inspection, f"{display_name(INSPECTOR)} started an inspection of {place_of(site)} at {short_site(site)}.", None, "started")
        self._inspect_from_records(inspection["id"])
        inspection = inspections.get(inspection["id"])
        if not inspection.get("primary"):
            raise RealityError(f"Nothing outstanding at {short_site(site)} to act on.", "NOT_FOUND", "Pick a site with a compliance finding.", 409)
        inspections.attach_issue(inspection["id"])
        return inspections.get(inspection["id"])

    def _latest_frame(self, site: str, tag: str, label: dict | None) -> dict | None:
        if label and label.get("frameId"):
            frame = self.store.get("eye_frame", label["frameId"], site)
            if frame:
                return frame
        rows = query(self.store, "eye_frame", "json_extract(body, '$.params.assetTag') = ?", (tag,), order="json_extract(body, '$.at') DESC",
                     limit=1, property_id=site)
        return rows[0] if rows else None

    def _inspect_from_records(self, inspection_id: str) -> None:
        """The inspection's stops and findings from the records, with each asset's latest frame (InspectionService.inspect without
        moving the eye)."""
        inspections, patrols = self.service.inspections, self.service.patrols
        record = inspections.get(inspection_id)
        site = record["siteId"]
        obligations = self.service.people.obligations(site)
        issues = patrols.open_issues(site)
        readings = patrols.readings(site)
        labels = {label["assetTag"]: label for label in patrols.labels(site)}
        stops, findings = [], []
        for index, tag in enumerate(inspections.route(site)[:3]):
            component = self.service.reality.component_by_tag(site, tag)
            label = labels.get(tag)
            frame = self._latest_frame(site, tag, label)
            assessment = patrols.assess(site, component, obligations, issues, readings)
            observation = (label or {}).get("observation") if (label or {}).get("assessedBy") not in (None, "rules") else None
            stops.append(dict(n=index + 1, assetTag=tag, assetName=component.get("name"), frameId=(frame or {}).get("id"), frameUrl=(frame or {}).get("url"),
                              eyeNote=None if frame else "no recent frame", verdict=assessment["verdict"], reasons=list(assessment["reasons"])[:4],
                              observation=observation, walkLabelId=(label or {}).get("id"), at=(frame or {}).get("at") or now()))
            findings += inspections.findings_at(site, tag, component, (frame or {}).get("id"), assessment, obligations, issues, readings)
        findings.sort(key=lambda f: f["score"], reverse=True)
        primary = findings[0] if findings else None
        also = [f for f in findings[1:] if not primary or f.get("assetTag") != primary.get("assetTag") or f.get("obligationId") != primary.get("obligationId")]
        kind = inspections.work_kind(site, primary) if primary else None
        inspections._update(inspection_id, stops=stops, findings=findings, primary=primary, alsoNoted=[f["title"] for f in also][:4], workKind=kind,
                            contractor=contractor_for(site, kind) if kind else None)

    # ---- while the call runs (not person-facing) ---------------------------------------------------------------------

    def _site_chats(self, run_id: str, inspection_id: str) -> None:
        """The inspector's report (6 turns), the evidence email to the manager's mailbox, the decision with the manager (4 turns)."""
        state = self.state.get(run_id) or {}
        realtime = bool(state.get("realtime"))
        token = TURN_OVERRIDE.set(self.turn_seconds()) if realtime else None
        inspections = self.service.inspections
        try:
            record = inspections.get(inspection_id)
            c = inspections.context(record)
            site, compliance, manager = c["site"], c["compliance"], c["manager"]
            shared = inspections.shared_facts(c)
            briefs = {INSPECTOR: (f"You are the Site Inspector. You just inspected {c['place']} at {c['site_name']}. Stops: " + " | ".join(c["stops_text"])
                                  + f". Your most important finding is {c['tag']}: {c['status_line']}. Report it with the evidence and agree the severity."),
                      compliance: (f"You are the {c['compliance_name']}. Regulation: {c['cite']}" + (f", {c['reg_title']}" if c["reg_title"] else "")
                                   + f". {inspections.due_text(c)} Owner on the crew table: {c['owner_label']}. After this chat the evidence goes to the "
                                     f"{c['manager_role_l']}; recommend: {c['step']}.")}
            summary = dict(headline=f"{c['tag']}: {lower_first(c['noun'])} {c['state']}; evidence to the {c['manager_role_l']}",
                           points=[f"{c['tag']}: {c['status_line']}.", f"Why it matters: {c['cite']}."],
                           decisions=[f"Treat it as {c['severity']} severity.", f"Send the evidence pack to the {c['manager_role_l']}."],
                           actions=[dict(owner=c["compliance_name"], task=f"Send the evidence pack to the {c['manager_role_l']}", due="now")])
            report = inspections.chat(INSPECTOR, compliance, f"Inspection of {c['place']}: {c['tag']} {lower_first(c['noun'])} {c['state']}", site, briefs,
                                      shared, f"Report {c['tag']} with the evidence and agree its severity and that the evidence goes to the {c['manager_role_l']}.",
                                      inspections.report_turns(c)[:6], summary, 6, 6, record, realtime)
            inspections._update(inspection_id, conversationIds=[report["id"]])
            inspections._step(inspection_id, "report", f"{c['inspector_name']} reported {c['tag']} to {c['compliance_name']} "
                                                       f"({plural(len(report.get('transcript') or []), 'message')}): {c['cite']}.", conversationId=report["id"])
            item = self._evidence_email(record, c)
            window = inspections.covering_window(record)
            window_text = (f"The planner has a window on {window['localStart']} {city(site)} time; I'll offer that first." if window and window.get("localStart")
                           else "The planner has nothing booked for it yet, so I'll offer the next slots.")
            briefs2 = {compliance: f"You are the {c['compliance_name']}. You emailed the evidence pack to the {c['manager_role_l']}. Finding: {c['tag']}: "
                                   f"{c['status_line']}. Recommendation: {c['step']}. The contractor is {c['contractor']}.",
                       manager: f"You are the {c['manager_name']}. You are on the phone with {c['contractor']} about this right now. {window_text} "
                                f"Decide to email the owner with Compliance Counsel copied once the slot is agreed."}
            summary2 = dict(headline=f"{c['manager_name']} books {c['contractor']} for {c['tag']} and tells the owner",
                            points=[f"{c['tag']}: {c['noun']} {c['state']}.", window_text],
                            decisions=["Email the owner with Compliance Counsel copied.", f"Book {c['contractor']} on the call."],
                            actions=[dict(owner=c["manager_name"], task="Email the owner (Compliance Counsel copied)", due="after the call")])
            decision = inspections.chat(compliance, manager, f"Decision: {c['tag']} {lower_first(c['noun'])}", site, briefs2, shared,
                                        f"Agree to book {c['contractor']} and email the owner with Compliance Counsel copied.",
                                        inspections.manager_turns(c, window_text)[:4], summary2, 4, 4, record, realtime)
            inspections._update(inspection_id, conversationIds=[decision["id"]])
            inspections._step(inspection_id, "evidence_to_manager", f"{c['compliance_name']} sent the evidence pack to the {c['manager_role_l']} "
                                                                    f"({item.get('status') or 'queued'}) and they agreed: email the owner, book {c['contractor']}.",
                              outboxId=item.get("id"), conversationId=decision["id"], mode=item.get("status"))
            self._step(run_id, "site_chats", f"Inspector, compliance officer and manager at {short_site(site)}: two chats and the evidence pack",
                       conversationIds=[report["id"], decision["id"]], outboxId=item.get("id"))
        finally:
            if token is not None:
                TURN_OVERRIDE.reset(token)

    def _evidence_email(self, record: dict, c: dict) -> dict:
        inspections = self.service.inspections
        attachments, notes = inspections.frame_attachments(record, c, "pack")
        refs, _ = self.service.patrols.alerts.references(c, 0)
        evidence = inspections.evidence_text(record, c, refs).encode("utf-8")
        attachments.append(dict(filename=f"evidence-{record['id']}.txt", content_type="text/plain", content_base64=base64.b64encode(evidence).decode("ascii"),
                                size=len(evidence), kind="evidence"))
        subject = f"[{c['site_name']}] Inspection evidence: {c['tag']} {lower_first(c['noun'])} ({c['state']})"
        text = "\n".join([f"{c['manager_role']},", "", f"The Site Inspector found {c['tag']} ({lower_first(c['asset'])}): {c['status_line']}.",
                          f"It falls under {c['cite']}.", f"Recommendation: {c['step']}. The work is for {c['contractor']}.", "",
                          "Attached: " + ", ".join(a["filename"] for a in attachments), "", c["compliance_name"]])
        frame_html = "".join(f"<div style=\"margin:8px 0\"><img src=\"cid:{esc(n['cid'])}\" alt=\"Agent eye frame of {esc(n['tag'])}\" width=\"560\" "
                             f"style=\"max-width:100%;border:1px solid #ddd\"><div style=\"font-size:12px;color:#666\">{esc(n['tag'])}, {esc(n['at'])} site time</div></div>"
                             for n in notes)
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px\">"
                f"<p>{esc(c['manager_role'])},</p><p>The Site Inspector found <b>{esc(c['tag'])}</b> ({esc(lower_first(c['asset']))}): {esc(c['status_line'])}. "
                f"It falls under {esc(c['cite'])}.</p><p><b>Recommendation.</b> {esc(c['step'])}. The work is for {esc(c['contractor'])}.</p>"
                f"{frame_html}<p>{esc(c['compliance_name'])}</p></div>")
        try:
            item = self.service.outbox.internal_email(sender=c["compliance"], to_agent=c["manager"], subject=subject[:300], text=text, html=html,
                                                      attachments=inspections.wire(attachments), site_id=c["site"], purpose="inspection_evidence",
                                                      refs=dict(inspectionId=record["id"], issueId=record.get("issueId")))
        except Exception as error:
            item = dict(id=None, status="failed", reason=f"{type(error).__name__}")
        inspections._update(record["id"], outboxIds=[item["id"]] if item.get("id") else [],
                            evidenceEmail=dict(mode=item.get("status"), outboxId=item.get("id"), subject=subject[:300],
                                               attachments=[a["filename"] for a in attachments], reason=item.get("reason"), at=now()))
        return item

    def _telemetry_later(self, run_id: str) -> None:
        state = self.state.get(run_id) or {}
        wait = self.telemetry_at() - (time.monotonic() - state.get("t0", time.monotonic()))
        if wait > 0 and self._stop.wait(wait):
            return
        self._telemetry(run_id)

    def _telemetry(self, run_id: str) -> None:
        """The excursion: a reading above its band at the telemetry site (through the sensor feed, so the live metrics show it high),
        then the cross-site chat with the contractor's site about its limits."""
        state = self.state.get(run_id) or {}
        realtime = bool(state.get("realtime"))
        record = self.get(run_id)
        site, other = record["sites"]["telemetry"], record["sites"]["contractor"]
        metrics, reality = self.service.metrics, self.service.reality
        specs = [s for s in metrics.specs(site) if s["key"].split(":")[0] == TELEMETRY_BASE and (s.get("spec") or {}).get("max") is not None]
        spec = next((s for s in specs if s["assetTag"] == TELEMETRY_TAG), None) or (specs[1] if len(specs) > 1 else specs[0] if specs else None)
        if spec is None:
            raise RealityError(f"No pressure series with a band at {short_site(site)}.", "NOT_FOUND", "Pick another telemetry site.", 409)
        tag, band = spec["assetTag"], spec["spec"]
        value = round(float(band["max"]) + 0.32, 2)
        self._reading(site, tag, value, band, "high")
        others = [s for s in metrics.specs(other) if s["key"].split(":")[0] == TELEMETRY_BASE and s.get("spec")]
        other_spec = next((s for s in others if s["assetTag"] == tag), None) or (others[0] if others else None)
        live = {r["key"]: r for r in metrics.live_readings(other)} if other_spec else {}
        other_reading = live.get(other_spec["key"]) if other_spec else None
        token = TURN_OVERRIDE.set(self.turn_seconds()) if realtime else None
        try:
            mine, theirs = manager_id(site), manager_id(other)
            unit = spec.get("unit") or "bar"
            ob = (other_spec or {}).get("spec") or {}
            other_value = (other_reading or {}).get("value")
            other_state = (other_reading or {}).get("state") or "normal"
            seeing = other_state != "normal"
            their_line = (f"We run {other_spec['assetTag']}, our {lower_first(other_spec['label'].split(' (')[0])}, at {ob.get('min')} to {ob.get('max')} {unit}; "
                          f"it reads {other_value} {unit} now, " + ("outside the band, so yes, we're seeing it too." if seeing else "inside the band. Nothing like that here today.")
                          ) if other_spec else "We don't have a comparable gauge here, so I can't compare limits."
            turns = [dict(speaker=mine, text=f"{short_site(other)}, {tag}, our {lower_first(spec['label'].split(' (')[0])}, just read {value} {unit} against our "
                                             f"{band.get('min')} to {band.get('max')} {unit} band. What limits do you run, and are you seeing anything like this?"),
                     dict(speaker=theirs, text=their_line),
                     dict(speaker=mine, text="Thanks. Ours climbed in the last few minutes; I'll have our Site Engineer check the circuit and the relief valve now."),
                     dict(speaker=theirs, text="Sensible. If it settles back inside the band it's likely the relief valve; I'll send you our checklist."),
                     dict(speaker=mine, text="Please do. I'll tell the owner and book a pressure-system check if it doesn't settle within the hour.")]
            briefs = {mine: (f"You are the {display_name(mine)}. {tag} ({spec['label']}) reads {value} {unit}, above its {band.get('min')} to {band.get('max')} "
                             f"{unit} band, and rose in the last few minutes. Ask the {display_name(theirs)} what limits they run on their comparable gauge and "
                             f"whether they see the same; agree a next step (your Site Engineer checks the circuit and the relief valve)."),
                      theirs: (f"You are the {display_name(theirs)}. " + (f"Your comparable gauge is {other_spec['assetTag']} ({other_spec['label']}); band "
                                                                          f"{ob.get('min')} to {ob.get('max')} {unit}; it reads {other_value} {unit} now ({other_state}). "
                                                                          if other_spec else "You have no comparable gauge. ")
                               + "Answer from these records only and offer your relief-valve checklist.")}
            shared = (f"{site_name(site)}: {tag} {spec['label']} = {value} {unit} (band {band.get('min')} to {band.get('max')} {unit}, high). "
                      + (f"{site_name(other)}: {other_spec['assetTag']} {other_spec['label']} = {other_value} {unit} (band {ob.get('min')} to {ob.get('max')} {unit}, "
                         f"{other_state})." if other_spec else ""))
            summary = dict(headline=f"{tag} high at {short_site(site)}; {short_site(other)} " + ("sees the same" if seeing else "is inside its band"),
                           points=[f"{short_site(site)} {tag}: {value} {unit}, band {band.get('min')} to {band.get('max')} {unit}.",
                                   their_line],
                           decisions=["The Site Engineer checks the circuit and the relief valve now.", "Book a pressure-system check if it does not settle."],
                           actions=[dict(owner=display_name(mine), task="Tell the owner", due="now"),
                                    dict(owner=display_name(theirs), task="Send the relief-valve checklist", due="today")])
            conversation = self.service.chats.run(convener=mine, participants=[mine, theirs], topic=f"{tag} pressure at {short_site(site)}: your limits?",
                                                  site_ids=[site, other], briefs=briefs, shared=shared,
                                                  goal=f"Learn {short_site(other)}'s limits on its comparable gauge and whether it sees the same; agree the next step.",
                                                  min_turns=4, max_turns=6, fallback=turns, fallback_summary=summary, realtime=realtime, origin="workflow",
                                                  source="sequence")
        finally:
            if token is not None:
                TURN_OVERRIDE.reset(token)
        state["telemetry"] = dict(siteId=site, tag=tag, label=spec["label"], unit=unit, value=value, band=band, otherSite=other,
                                  otherTag=(other_spec or {}).get("assetTag"), otherLabel=(other_spec or {}).get("label"), otherBand=ob or None,
                                  otherValue=other_value, otherState=other_state, seeing=seeing, conversationId=conversation["id"], at=now())
        self._step(run_id, "telemetry", f"{tag} at {short_site(site)} read {value} {unit} (band {band.get('min')} to {band.get('max')}); the managers compared "
                                        f"limits with {short_site(other)}", conversationId=conversation["id"])

    def _reading(self, site: str, tag: str, value: float, band: dict, label: str) -> None:
        component = self.service.reality.component_by_tag(site, tag)
        observed = iso(utcnow())
        digest = hashlib.sha256(f"sensors:{site}:{tag}:{TELEMETRY_BASE}:{value}:{observed}".encode()).hexdigest()
        low, high = band.get("min"), band.get("max")
        inside = low is not None and high is not None and low <= value <= high
        checks = [dict(name="scope", passed=True, reason=f"Sensor feed reading for {tag}."),
                  dict(name="band", passed=inside, reason=f"{value} bar against the {low} to {high} bar band."),
                  dict(name="integrity", passed=True, reason=f"SHA-256 of the sample: {digest}.")]
        self.service.reality.write_fact(site, component, TELEMETRY_BASE, "reading", value, "bar", observed, dict(kind="sensor", ref=SENSOR_REF), checks,
                                        [digest], summary=f"{tag}.{TELEMETRY_BASE} = {value} bar (sensor:{SENSOR_REF})", extra=dict(synthetic=True))

    # ---- after the call -----------------------------------------------------------------------------------------------

    def on_contractor_call(self, call: dict, inspection_id: str) -> dict | None:
        """The contractor_schedule handler for this run's call: book (the confirmation comes last, paced), then the rest of the run."""
        run_id = (call.get("context") or {}).get("liveSequenceRunId")
        result = self.service.inspections.finish_booking(inspection_id, call, confirm=False) or {}
        outcome = call.get("outcome") or {}
        handled = list(result.get("handled") or [])
        if any((f or {}).get("type") == "email_file" for f in outcome.get("followUps") or []):
            handled.append("email_file")  # the job pack goes with the confirmation, copies as asked
        state = self.state.get(run_id or "")
        if state is None:
            return dict(result, handled=handled)
        self._step(run_id, "call_ended", f"The call ended ({outcome.get('result') or call.get('status')}): {outcome.get('decision') or 'no decision'}",
                   callId=call.get("id"))
        with self.lock:
            state["call"] = call
            ready = state["phase1"]
        if ready:
            self._phase2_start(run_id)
        return dict(result, handled=handled)

    def _watch_call(self, run_id: str) -> None:
        """A call that never reports back must not stall the run."""
        if self._stop.wait(CALL_WAIT_MINUTES * 60):
            return
        state = self.state.get(run_id) or {}
        with self.lock:
            if state.get("call") is not None or state.get("phase2"):
                return
            state["call"] = dict(id=None, status="failed", outcome=dict(result="failed", decision="The call did not report back.", followUps=[]))
        inspection_id = state.get("inspectionId")
        if inspection_id:
            try:
                self.service.inspections.finish_booking(inspection_id, state["call"], timed_out=True, confirm=False)
            except Exception:
                pass
        self._phase2_start(run_id)

    def _phase2_start(self, run_id: str) -> None:
        state = self.state.get(run_id) or {}
        with self.lock:
            if state.get("phase2"):
                return
            state["phase2"] = True
        if state.get("realtime"):
            threading.Thread(target=self._phase2, args=(run_id,), name="steward-live-sequence-after", daemon=True).start()
        else:
            self._phase2(run_id)

    def _wait_until(self, moment: datetime, realtime: bool) -> None:
        if not realtime:
            return
        seconds = (moment - utcnow()).total_seconds()
        if seconds > 0:
            self._stop.wait(seconds)

    def _settled(self, item_id: str | None, realtime: bool) -> datetime:
        """When the item settled (sent, prepared or held); the next item counts its gap from here."""
        deadline = time.monotonic() + (120 if realtime else 0)
        while item_id:
            try:
                item = self.service.outbox.get(item_id)
            except Exception:
                break
            if item.get("status") in SETTLED:
                return parse_time(item.get("sentAt") or item.get("settledAt") or "") or utcnow()
            if not realtime or time.monotonic() > deadline or self._stop.wait(0.5):
                break
        return utcnow()

    def _phase2(self, run_id: str) -> None:
        state = self.state.get(run_id) or {}
        realtime = bool(state.get("realtime"))
        gap = timedelta(seconds=self.gap() if realtime else 0)
        try:
            call = state.get("call") or {}
            last = parse_time(call.get("endedAt") or "") or utcnow()
            inspection_id = state["inspectionId"]
            inspections = self.service.inspections
            # (1) the owner email: the compliance file and the pictures, Compliance Counsel copied
            self._wait_until(last + gap, realtime)
            with self.service.outbox.paced_as(run_id):
                inspections.step_owner_email(inspections.get(inspection_id), realtime)
            owner = inspections.get(inspection_id).get("ownerEmail") or {}
            last = self._settled(owner.get("outboxId"), realtime)
            self._step(run_id, "owner_email", f"Owner email with the compliance file and the pictures, Compliance Counsel copied ({owner.get('mode')})",
                       outboxId=owner.get("outboxId"))
            # (2) the employee's text, then the A2A report the manager records
            self._wait_until(last + gap, realtime)
            sms, employee, entry = self._employee_text(run_id)
            last = self._settled(sms.get("id"), realtime)
            self._report_lateness(run_id, employee, entry)
            # (3) the telemetry email, after the cross-site chat
            thread = state.get("telemetry_thread")
            if thread is not None:
                thread.join(timeout=120)
            if state.get("telemetry") is None:
                self._telemetry(run_id)
            self._wait_until(last + gap, realtime)
            telemetry = self._telemetry_email(run_id)
            last = self._settled(telemetry.get("id"), realtime)
            # (4) the contractor confirmation, owner and Compliance Counsel copied
            self._wait_until(last + gap, realtime)
            confirmation = self._confirmation(run_id, inspection_id, call)
            self._settled(confirmation, realtime)
            self._restore(run_id)
            self._finish(run_id, "completed")
        except Exception as error:
            self._fail(run_id, error)

    def _employee_today(self, site: str) -> tuple[dict, dict]:
        """The employee whose shift runs today (Ama Owusu at Bristol), with today's badge entry."""
        attendance = self.service.attendance
        employees = attendance.employees(site)
        if not employees:
            raise RealityError(f"Nobody with a shift at {short_site(site)}.", "NOT_FOUND", "Pick another employee site.", 409)
        today = utcnow().astimezone(tz_for(site)).date()
        working = [e for e in employees if today.weekday() in e["days"]]
        employee = next((e for e in working if e["crewId"] == EMPLOYEE_PREFERRED), None) or (working[0] if working else employees[0])
        try:
            attendance.generate(utcnow(), [site])
        except Exception:
            pass
        entry_id = f"att-{employee['crewId']}-{today.isoformat()}"
        entry = self.store.get("attendance_entry", entry_id, site) or dict(id=entry_id, siteId=site, crewId=employee["crewId"], name=employee["name"],
                                                                          role=employee["role"], date=today.isoformat(), shiftStart=employee["start"],
                                                                          shiftEnd=employee["end"], synthetic=True)
        start = attendance._local(site, today, employee["start"])
        check_in = start + timedelta(minutes=LATE_MINUTES)
        entry.update(status="late", lateMinutes=LATE_MINUTES, checkIn=check_in.strftime("%H:%M"), checkInAt=iso(check_in), shiftStart=employee["start"],
                     shiftEnd=employee["end"], onSite=True)
        self.store.put("attendance_entry", entry, site)
        self.service.reality.emit_change(site, "attendance", entry_id, f"{employee['name']} checked in at {entry['checkIn']}, {LATE_MINUTES} minutes late.",
                                         extra=dict(crewId=employee["crewId"], status="late", entryId=entry_id))
        return employee, entry

    def _employee_text(self, run_id: str) -> tuple[dict, dict, dict]:
        site = self.get(run_id)["sites"]["employee"]
        employee, entry = self._employee_today(site)
        first = employee["name"].split()[0]
        text = (f"Hi {first}, it's the People Officer for {site_name(site)}. Your badge shows {entry['checkIn']} today, {LATE_MINUTES} minutes after your "
                f"{employee['start']} start; is everything all right?")
        with self.service.outbox.paced_as(run_id):
            item = self.service.outbox.sms(sender=PEOPLE, to_role="employee", text=text, site_id=site, purpose="attendance_text", gate="person",
                                           refs=dict(crewId=employee["crewId"], entryId=entry["id"]), dedupe_key=f"live:{run_id}:sms", priority=1)
        self._step(run_id, "employee_text", f"People Officer texted {employee['name']} ({item.get('status')}): {text}", outboxId=item.get("id"))
        return item, employee, entry

    def _report_lateness(self, run_id: str, employee: dict, entry: dict) -> None:
        site = entry["siteId"]
        manager = manager_id(site)
        conversations = self.service.conversations
        text = f"{employee['name']} checked in at {entry['checkIn']} today, {LATE_MINUTES} minutes late; I have texted them."
        conversation = conversations.message(PEOPLE, manager, f"Attendance: {employee['name']} late today", text, site_ids=[site],
                                             data=dict(crewId=employee["crewId"], entryId=entry["id"]), synthetic=True)
        answer = f"Recorded on {employee['name'].split()[0]}'s attendance for today: {entry['checkIn']}, {LATE_MINUTES} minutes late. Thanks."
        conversations.answer(conversation["id"], manager, answer)
        fresh = self.store.get("attendance_entry", entry["id"], site) or entry
        fresh.update(recordedBy=manager, recordedByName=display_name(manager), recordedAt=now(), conversationId=conversation["id"],
                     note=f"{LATE_MINUTES} minutes late; the People Officer texted them; recorded by the {display_name(manager)}.")
        self.store.put("attendance_entry", fresh, site)
        self.service.reality.emit_change(site, "attendance", entry["id"], f"{display_name(manager)} recorded {employee['name']}'s late check-in ({entry['checkIn']}).",
                                         extra=dict(crewId=employee["crewId"], status="recorded", entryId=entry["id"]))
        self._step(run_id, "lateness_recorded", f"People Officer reported it to the {display_name(manager)} over A2A; recorded on the badge log",
                   conversationId=conversation["id"], entryId=entry["id"])

    def _telemetry_email(self, run_id: str) -> dict:
        t = (self.state.get(run_id) or {}).get("telemetry")
        if not t:
            raise RealityError("The telemetry excursion did not run.", "INVALID_REQUEST", "Check the run's steps.", 409)
        site, other, unit = t["siteId"], t["otherSite"], t["unit"]
        manager = manager_id(site)
        band, ob = t["band"], t.get("otherBand") or {}
        when = local(site, parse_time(t["at"]) or utcnow()).strftime("%H:%M")
        asked = (f"I asked the {display_name(manager_id(other))} what they run on their comparable gauge: {t['otherTag']} ({t['otherLabel']}) runs "
                 f"{ob.get('min')} to {ob.get('max')} {unit} and reads {t['otherValue']} {unit} now, so they "
                 + ("are seeing the same." if t["seeing"] else "are not seeing this.")) if t.get("otherTag") else \
            f"I asked {short_site(other)}; they have no comparable gauge to compare."
        found = f"{t['tag']} ({t['label']}) read {t['value']} {unit} at {when} {city(site)} time, above its {band.get('min')} to {band.get('max')} {unit} band."
        step = "The Site Engineer is checking the circuit and the relief valve now; if it does not settle within the hour I will book a pressure-system check and tell you."
        subject = f"[{site_name(site)}] {t['tag']} pressure above its limit: {t['value']} {unit}"
        text = "\n".join([found, "", asked, "", f"Next step: {step}", "", display_name(manager)])
        attachments, picture = [], ""
        frame = self._latest_frame(site, t["tag"], None)
        if frame:
            try:
                data = labelled_bytes(self.service, frame["id"], extra=[dict(
                    assetTag=t["tag"], assetName=t.get("label"), bad=True, title=f"Above its limit: {t['value']} {unit}",
                    reason=f"{t['tag']} read {t['value']} {unit}, above its {band.get('min')} to {band.get('max')} {unit} band", agentName=display_name(manager), at=t.get("at"))])
                cid = f"tele-{run_id[-8:]}"
                attachments.append(dict(filename=f"{t['tag'].lower()}-latest.jpg", content_type="image/jpeg", content_base64=base64.b64encode(data).decode("ascii"),
                                        content_id=cid, size=len(data)))
                picture = (f"<div style=\"margin:8px 0\"><img src=\"cid:{cid}\" alt=\"Agent eye frame of {esc(t['tag'])}\" width=\"560\" "
                           f"style=\"max-width:100%;border:1px solid #ddd\"><div style=\"font-size:12px;color:#666\">{esc(t['tag'])}, the agent eye's latest frame</div></div>")
            except (RealityError, OSError):
                pass
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px\">"
                f"<p style=\"font-size:12px;color:#666;margin:0 0 6px\">Steward · {esc(site_name(site))} · {esc(display_name(manager))}</p>"
                f"<h2 style=\"font-size:18px;margin:0 0 14px\">{esc(t['tag'])} pressure above its limit</h2>"
                f"<p><b>What we see.</b> {esc(found)}</p><p><b>{esc(short_site(other))}.</b> {esc(asked)}</p>"
                f"<p style=\"background:#f4f4f4;border-left:3px solid #1a1a1a;padding:10px 12px\"><b>Next step.</b> {esc(step)}</p>{picture}"
                f"<p>{esc(display_name(manager))}</p></div>")
        with self.service.outbox.paced_as(run_id):
            item = self.service.outbox.email(sender=manager, to_role="owner", subject=subject[:300], text=text, html=html, attachments=attachments,
                                             site_id=site, purpose="telemetry_alert", refs=dict(conversationId=t["conversationId"]),
                                             dedupe_key=f"live:{run_id}:telemetry", priority=1)
        self._step(run_id, "telemetry_email", f"{display_name(manager)} emailed the owner about {t['tag']} ({item.get('status')})", outboxId=item.get("id"))
        return item

    def _confirmation(self, run_id: str, inspection_id: str, call: dict) -> str | None:
        inspections = self.service.inspections
        record = inspections.get(inspection_id)
        booking = record.get("booking") or {}
        window = self.store.get("maintenance_window", booking.get("windowId") or record.get("windowId") or "", "")
        if not window:
            self._step(run_id, "confirmation", "No booking to confirm.")
            return None
        c = inspections.context(record)
        slot = next((s for s in record.get("slots") or [] if s["id"] == booking.get("slotId")), None) or dict(id=booking.get("slotId"), label=booking.get("label") or "")
        outcome = (call or {}).get("outcome") or {}
        attachments = []
        if any((f or {}).get("type") == "email_file" for f in outcome.get("followUps") or []):
            pack = inspections.job_pack(record, c).encode("utf-8")
            attachments.append(dict(filename=f"job-pack-{record['id']}.txt", content_type="text/plain", content_base64=base64.b64encode(pack).decode("ascii"),
                                    size=len(pack)))
        with self.service.outbox.paced_as(run_id):
            item_id, mode = inspections.confirm(record, c, window, slot, bool(booking.get("agreed")), booking.get("callResult") or outcome.get("result") or "undecided",
                                                call or {}, attachments=attachments)
        inspections._update(inspection_id, outboxIds=[item_id] if item_id else [], booking=dict(booking, confirmationOutboxId=item_id))
        self._step(run_id, "confirmation", f"Contractor confirmation, owner and Compliance Counsel copied ({mode})", outboxId=item_id, windowId=window["id"])
        return item_id

    def _restore(self, run_id: str) -> None:
        t = (self.state.get(run_id) or {}).get("telemetry")
        if not t or not (self.state.get(run_id) or {}).get("realtime"):
            return  # inline (tests): the excursion stays visible to the caller
        band = t["band"]
        value = round((float(band["min"]) + float(band["max"])) / 2 + 0.25, 2)
        try:
            self._reading(t["siteId"], t["tag"], value, band, "back")
            self._step(run_id, "telemetry_settled", f"{t['tag']} back inside its band: {value} {t['unit']}")
        except Exception:
            pass


def site_name(site_id: str) -> str:
    return SITE_BY_ID.get(site_id, {}).get("name", site_id)
