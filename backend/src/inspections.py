"""The inspection chain (contract 8 §6): the Site Inspector inspects a site with the agent eye, reports to the Compliance
Officer, the evidence goes to the manager, the manager emails the owner with Compliance Counsel copied, counsel briefs the
contractor, and the manager calls the contractor to book the work.

The Site Inspector (`site-inspector`) inspects one site at a time: first `STEWARD_INSPECTION_FIRST_DELAY_MINUTES` (8) after the
backend starts, then every `STEWARD_INSPECTION_EVERY_MINUTES` (60), rotating Bristol, Myer, Tomioka (the rotation is kept in the
store, so a restart carries on where it left off). `STEWARD_INSPECTIONS=false` turns the loop off. An inspection drives the agent
eye to up to five assets (overdue and blocked obligations first, then open compliance issues, out-of-band readings and obligations
falling due); an eye failure leaves the stop without a frame and never fails the inspection. Findings come from the records with
the latest walkthrough label's observation for the asset; the most important one is the primary, the rest are "also noted".

Chain (record `inspection`, change type `inspection` `{inspectionId, step, status}`):
1. `report`: a long chat (chat_writer) between the Site Inspector and the site's Compliance Officer.
2. `evidence_to_manager`: an internal email (outbox) from the Compliance Officer to the site manager with the frames, and a chat
   between them that decides to tell the owner with Compliance Counsel copied and to book the contractor.
3. `owner_email`: the manager emails role `owner`, CC `compliance-counsel` (outbox), with the frames inline and attached, the
   regulation PDF when its licence allows (England OGL, Japan PDL1.0; Victorian texts are link-only) and the evidence file.
4. `counsel_to_contractor`: Compliance Counsel emails role `contractor`, CC the manager: what the law requires for the job.
5. `contractor_call`: the manager calls the contractor (voice_calls, purpose `contractor_schedule`) to agree one of three slots:
   the planner's window for the obligation when there is one ("currently booked") and the next working-hours slots for that
   kind of work.
6. `booking` (the call's handler): the agreed slot is booked, or the planner's window is moved to it (approved, origin
   `contractor_call`); without an agreed slot the first slot is kept or booked and the confirmation asks the contractor to reply.
   The team hears over A2A and the contractor gets a confirmation email (CC the owner and Compliance Counsel).

One inspection per site runs at a time; when the backend's workers run the chain plays on its own thread (chats in real time),
inline otherwise (tests). An inspection whose contractor call never reports back is closed with the fallback booking after
`STEWARD_INSPECTION_CALL_TIMEOUT_MINUTES` (90). Text is written from the records by templates; the chats are Claude's when the
chat writer can, with these templates as the fallback.
"""
from __future__ import annotations

import base64
import html as html_lib
import re
import threading
from datetime import datetime, timedelta, timezone

from .agents import COUNSEL, INSPECTOR, OPERATOR, compliance_id, display_name, email_for, engineer_id, manager_id, technician_id
from .compliance_alerts import (BAD_STATUSES, MAX_ATTACHMENT_BYTES, MAX_FRAMES, categorize, cite_short, first_sentence, local, lower_first,
                                overdue_days, partner_site, place_of, plural, primary_regulation, query, sentence, short_site, state_phrase)
from .env import env
from .errors import RealityError
from .maintenance_planner import LEAD_HOURS, OPEN, WORK_KINDS, city, is_working_day, obligation_kind, slot_on, tz_for
from .patrol import COMPLIANCE_ISSUE_KINDS, reading_words
from .sites import SITE_IDS
from .frame_labels import labelled_bytes
from .store import now, uid
from .verify import iso, parse_time

STEPS = ("report", "evidence_to_manager", "owner_email", "counsel_to_contractor", "contractor_call", "booking")
ROTATION = ("bristol-pumps", "myer-plant", "tomioka-mill")
MAX_STOPS = 5
SLOT_COUNT = 3
TICK_SECONDS = 30.0
DEFAULT_FIRST_DELAY_MINUTES = 8.0
DEFAULT_EVERY_MINUTES = 60.0
DEFAULT_CALL_TIMEOUT_MINUTES = 90.0
DEFAULT_STEP_SECONDS = 4.0
NEXT_META = "inspections:next-at"
ROTATION_META = "inspections:rotation"
NOT_CALLED = ("dry_run", "capped", "canceled", "failed")
# Who the manager calls, by site and kind of work (maintenance_planner.WORK_KINDS); the contractor is the owner on their phone.
CONTRACTORS = {
    "myer-plant": {"drainage": "Delta Valve Services", "pressure": "Delta Valve Services", "general": "Delta Valve Services",
                   "fire": "Southbank Fire & Emergency Lighting", "electrical": "Yarra Electrical Testing", "visitor_route": "Delta Valve Services",
                   "heritage": "Delta Valve Services"},
    "bristol-pumps": {"drainage": "Avon Pump & Valve Ltd", "pressure": "Northgate Engineering Inspection", "general": "Avon Pump & Valve Ltd",
                      "fire": "Severn Fire Safety Ltd", "electrical": "Clifton Electrical Testing", "visitor_route": "Harbourside Access Ltd",
                      "heritage": "Bristol Heritage Engineering"},
    "tomioka-mill": {"fire": "Kanto Fire Protection", "heritage": "Gunma Heritage Carpentry", "general": "Gunma Heritage Carpentry",
                     "electrical": "Joshu Electrical Services", "drainage": "Gunma Pump Services", "pressure": "Kanto Boiler Inspection",
                     "visitor_route": "Gunma Heritage Carpentry"},
}
# What the law asks the contractor to deliver, by kind of finding (compliance_alerts.categorize); Compliance Counsel's email.
REQUIREMENTS = {
    "pressure": ["The examination is done by the competent person under the written scheme of examination.",
                 "The competent person's written report, with the date of the next examination, comes to us within 28 days; any imminent danger is reported at once.",
                 "Nothing returns to service past its examination date until the report says it may."],
    "maintenance": ["The work puts the equipment back in efficient working order and good repair.",
                    "A short method statement and risk assessment reach the site manager before the visit.",
                    "The repair is recorded in the plant record: what was done, parts used, the test after the work, and who did it."],
    "lighting": ["The full-duration discharge test is run and every luminaire in the circuit is checked.",
                 "Results go into the emergency lighting logbook the same day, signed by the person who ran the test.",
                 "Any failed luminaire is replaced or repaired and retested before you leave site."],
    "drill": ["The evacuation drill follows the site's fire defence plan, with the exits and guide lights checked the same morning.",
              "The drill record (date, people taking part, time to clear, problems found) is signed and filed.",
              "Anything that failed on the route is put right and noted before the next opening."],
    "fire": ["Each unit is inspected by a qualified person and tagged with the date and result.",
             "The inspection record goes into the asset record, and the report is filed with the authority where the law asks for it.",
             "Any unit that fails is replaced on the day."],
    "structure": ["No work alters the protected fabric until the permission is granted in writing.",
                  "The survey is recorded with photographs and a written condition report.",
                  "Any temporary support fixes nothing permanently into the historic structure."],
    "heritage": ["Nothing alters the protected fabric without the written permission.",
                 "The method statement shows how the work avoids drilling, welding or adhesive on historic members.",
                 "Every step is photographed and logged for the conservation record."],
    "humidity": ["The conservator's check of the trusses and machinery is recorded with photographs.",
                 "Any mould or corrosion found is logged with its location and treatment."],
    "route": ["The route is checked end to end before opening: handrails, toe boards, lighting and trip hazards.",
              "The check is signed, timed and filed; the route stays closed until it is."],
    "hotwork": ["A signed hot-work permit is in place before work starts, with a fire watch for an hour afterwards.",
                "The permit is closed in the log when the job ends."],
    "report": ["The service report is filed within five working days of the visit.",
               "It names the work done, the results and who did it."],
    "electrical": ["The periodic inspection and RCD tests are done by a qualified electrician.",
                   "The certificate and test results come to us within five working days."],
    "generic": ["The work is done by a competent person and recorded in the asset record.",
                "The record says what was done, when, and who did it."],
}
SITE_RULES = ("Report to the {manager_role_l} on arrival; the permit to work and the isolation are issued on site.",
              "Send your method statement and risk assessment to the {manager_role_l} before the visit.")


def flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def number(name: str, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(float(env(name, str(default)) or default), high))
    except ValueError:
        return default


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def esc(text) -> str:
    return html_lib.escape(str(text or ""))


def slot_label(site: str, start: datetime) -> str:
    moment = start.astimezone(tz_for(site))
    return f"{moment:%A} {moment.day} {moment:%B}, {moment:%H:%M} {city(site)} time"


def candidate_slots(site: str, kind: str, moment: datetime | None = None, existing: dict | None = None, count: int = SLOT_COUNT) -> list[dict]:
    """Up to `count` slots `{id, startAt, endAt, label, current}`: the existing window first ("currently booked") when it is still ahead,
    then the next working-hours slots for this kind of work at least LEAD_HOURS ahead, one per working day."""
    moment = moment or utcnow()
    kind = kind if kind in WORK_KINDS else "general"
    out, taken = [], set()
    start = parse_time((existing or {}).get("startAt"))
    if existing and start and start > moment:
        end = parse_time(existing.get("endAt")) or start + timedelta(hours=WORK_KINDS[kind]["hours"])
        out.append(dict(id="slot-1", startAt=iso(start), endAt=iso(end), label=f"{slot_label(site, start)} (currently booked)", current=True,
                        windowId=existing["id"]))
        taken.add(start.astimezone(tz_for(site)).date())
    earliest = moment + timedelta(hours=LEAD_HOURS)
    day = earliest.astimezone(tz_for(site)).date()
    for offset in range(60):
        if len(out) >= count:
            break
        candidate = day + timedelta(days=offset)
        if candidate in taken or not is_working_day(site, candidate):
            continue
        begin, end = slot_on(site, candidate, kind)
        if begin < earliest:
            continue
        out.append(dict(id=f"slot-{len(out) + 1}", startAt=iso(begin), endAt=iso(end), label=slot_label(site, begin), current=False, windowId=None))
    return out


def contractor_for(site: str, kind: str) -> str:
    table = CONTRACTORS.get(site) or {}
    return table.get(kind) or table.get("general") or "the maintenance contractor"


def finding_score(obligation: dict) -> int:
    """Blocked work and long-overdue work first: days past due, plus 5 for a block."""
    return (overdue_days(obligation) or 0) + (5 if obligation.get("status") == "blocked" else 0) + 1


class InspectionService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.threads: dict[str, threading.Thread] = {}
        self.state = "off"
        self.reason: str | None = "Inspections start with the backend's workers."
        self.last_tick_at: str | None = None
        self.register_handlers()
        if getattr(service, "start_workers", False):
            self.recover()

    # ---- settings -------------------------------------------------------------------------------------------

    @staticmethod
    def switched_on() -> bool:
        return flag("STEWARD_INSPECTIONS", "true")

    def enabled(self) -> bool:
        return bool(getattr(self.service, "start_workers", False)) and self.switched_on()

    @staticmethod
    def first_delay() -> timedelta:
        return timedelta(minutes=number("STEWARD_INSPECTION_FIRST_DELAY_MINUTES", DEFAULT_FIRST_DELAY_MINUTES, 0, 1440))

    @staticmethod
    def every() -> timedelta:
        return timedelta(minutes=number("STEWARD_INSPECTION_EVERY_MINUTES", DEFAULT_EVERY_MINUTES, 1, 10080))

    @staticmethod
    def call_timeout() -> timedelta:
        return timedelta(minutes=number("STEWARD_INSPECTION_CALL_TIMEOUT_MINUTES", DEFAULT_CALL_TIMEOUT_MINUTES, 5, 1440))

    @staticmethod
    def step_seconds() -> float:
        return number("STEWARD_INSPECTION_STEP_SECONDS", DEFAULT_STEP_SECONDS, 0, 60)

    @staticmethod
    def call_retries() -> int:
        return int(number("STEWARD_CALL_RETRIES", 1, 0, 5))

    def register_handlers(self) -> None:
        """The contractor call's handler, on whichever phone-call service the backend has now (tests swap in fakes)."""
        voice = getattr(self.service, "voice_calls", None)
        if voice is not None and hasattr(voice, "register"):
            voice.register("contractor_schedule", self.on_contractor_call)

    # ---- the loop -------------------------------------------------------------------------------------------

    def start(self) -> None:
        if not self.enabled():
            self.state, self.reason = "off", ("STEWARD_INSPECTIONS=false." if not self.switched_on() else "The backend's workers are off.")
            return
        if self._thread and self._thread.is_alive():
            return
        self.register_handlers()
        self.state, self.reason = "idle", "The first inspection starts a few minutes after the backend."
        self.store.meta(NEXT_META, iso(utcnow() + self.first_delay()))
        self._thread = threading.Thread(target=self._loop, name="steward-inspections", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception as error:  # the loop never dies; the next tick tries again
                self.state, self.reason = "error", f"{type(error).__name__}: {str(error)[:200]}"
                self.store.event(ROTATION[0], INSPECTOR, "inspection.loop_failed", "Inspection loop failed", self.reason)

    def tick(self, moment: datetime | None = None) -> dict | None:
        """One pass: close inspections whose contractor call never reported back, then start the next inspection when it is due.
        Returns the inspection started, if any."""
        moment = moment or utcnow()
        self.last_tick_at = iso(moment)
        self.close_stale(moment)
        if not self.switched_on():
            self.state, self.reason = "off", "STEWARD_INSPECTIONS=false."
            return None
        sequence = getattr(self.service, "sequence", None)
        if sequence is not None and sequence.active():  # the live sequence has the line and the inbox for now
            return None
        due = parse_time(self.store.meta(NEXT_META))
        if due is None:
            self.store.meta(NEXT_META, iso(moment + self.first_delay()))
            return None
        if moment < due:
            return None
        rotation = [s for s in ROTATION if self.store.get("property", s)] or [s for s in SITE_IDS]
        try:
            index = int(self.store.meta(ROTATION_META) or 0)
        except ValueError:
            index = 0
        started = None
        for offset in range(len(rotation)):
            site = rotation[(index + offset) % len(rotation)]
            if self.running(site):
                continue
            started = self.start_now(site, OPERATOR, realtime=bool(getattr(self.service, "start_workers", False)))
            self.store.meta(ROTATION_META, str((index + offset + 1) % len(rotation)))
            break
        self.store.meta(NEXT_META, iso(moment + self.every()))
        if started:
            self.state, self.reason = "inspecting", f"Inspecting {short_site(started['siteId'])}."
        else:
            self.state, self.reason = "waiting", "Every site has an inspection in progress."
        return started

    def recover(self) -> int:
        """An inspection left running by an earlier process before its contractor call has no thread any more: mark it failed.
        One that is only waiting for its call keeps waiting (the call's handler is registered again at start)."""
        count = 0
        for inspection in query(self.store, "inspection", "json_extract(body, '$.state') = 'running'"):
            if inspection.get("callId"):
                continue
            inspection.update(state="failed", finishedAt=now(), error="Interrupted by a backend restart.")
            self._save(inspection)
            count += 1
        return count

    def close_stale(self, moment: datetime | None = None) -> list[str]:
        moment = moment or utcnow()
        closed = []
        for inspection in query(self.store, "inspection", "json_extract(body, '$.state') = 'running'"):
            requested = parse_time(inspection.get("callRequestedAt"))
            if not inspection.get("callId") or not requested or moment - requested < self.call_timeout():
                continue
            call = dict(id=inspection["callId"], refs=dict(inspectionId=inspection["id"]), status="no_answer", attempt=99,
                        outcome=dict(result="no_answer", decision="", summary="The contractor call did not report back.", chosenOptionId=None, followUps=[]))
            try:
                self.finish_booking(inspection["id"], call, timed_out=True)
                closed.append(inspection["id"])
            except Exception as error:
                self.store.event(inspection["siteId"], INSPECTOR, "inspection.close_failed", "Inspection could not be closed",
                                 f"{inspection['id']}: {type(error).__name__}: {str(error)[:160]}")
        return closed

    # ---- records --------------------------------------------------------------------------------------------

    def get(self, inspection_id: str) -> dict:
        record = self.store.get("inspection", inspection_id)
        if not record:
            raise RealityError("Inspection not found.", "NOT_FOUND", "List inspections with GET /api/inspections?siteId=.", 404)
        return record

    def list(self, site_id: str | None = None, limit: int = 20) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        return query(self.store, "inspection", order="json_extract(body, '$.startedAt') DESC", limit=max(1, int(limit)), property_id=site_id or None)

    def running(self, site_id: str) -> dict | None:
        rows = query(self.store, "inspection", "json_extract(body, '$.state') = 'running'", property_id=site_id)
        return rows[0] if rows else None

    def _save(self, inspection: dict) -> dict:
        inspection["updatedAt"] = now()
        self.store.put("inspection", inspection, inspection["siteId"])
        return inspection

    def _update(self, inspection_id: str, **fields) -> dict:
        with self.lock:
            record = self.get(inspection_id)
            for key, value in fields.items():
                if key in ("conversationIds", "outboxIds") and isinstance(value, list):
                    record[key] = list(dict.fromkeys((record.get(key) or []) + [v for v in value if v]))
                else:
                    record[key] = value
            return self._save(record)

    def _change(self, inspection: dict, summary: str, step: str | None, status: str) -> None:
        fields = {k: v for k, v in dict(inspectionId=inspection["id"], step=step, status=status, obligationId=(inspection.get("primary") or {}).get("obligationId")).items()
                  if v is not None}
        tag = (inspection.get("primary") or {}).get("assetTag")
        self.service.reality.emit_change(inspection["siteId"], "inspection", inspection["id"], summary[:480], tag, extra=fields, fields=fields)

    def _step(self, inspection_id: str, name: str, summary: str, **refs) -> dict:
        with self.lock:
            record = self.get(inspection_id)
            record["steps"].append(dict(n=len(record["steps"]) + 1, name=name, at=now(), summary=summary[:400],
                                        refs={k: v for k, v in refs.items() if v not in (None, "", [], {})}))
            # The chain's order, whatever finished first (a call that could not be placed books before its own step is written).
            order = {step: index for index, step in enumerate(STEPS)}
            record["steps"].sort(key=lambda s: (order.get(s["name"], len(order)), s["at"]))
            for index, step in enumerate(record["steps"], 1):
                step["n"] = index
            self._save(record)
        self._change(record, f"Inspection of {short_site(record['siteId'])}, step {len(record['steps'])} ({name}): {summary[:300]}", name, "step")
        return record

    # ---- start ----------------------------------------------------------------------------------------------

    def start_now(self, site_id: str, actor: str = OPERATOR, realtime: bool | None = None) -> dict:
        """Start an inspection at the site now, or return the one in progress there. With the backend's workers the inspection
        plays on its own thread (chats in real time); otherwise inline."""
        self.service.require_property(site_id)
        realtime = bool(getattr(self.service, "start_workers", False)) if realtime is None else realtime
        with self.lock:
            existing = self.running(site_id)
            if existing:
                return existing
            inspection = dict(id=uid("insp"), siteId=site_id, siteName=self.service.require_property(site_id)["name"], inspectorId=INSPECTOR,
                              inspectorName=display_name(INSPECTOR), state="running", startedBy=actor, stops=[], findings=[], primary=None, alsoNoted=[],
                              steps=[], conversationIds=[], outboxIds=[], callId=None, callRequestedAt=None, windowId=None, slots=[], workKind=None,
                              contractor=None, issueId=None, summary=None, error=None, startedAt=now(), finishedAt=None, synthetic=True)
            self._save(inspection)
        self._change(inspection, f"{display_name(INSPECTOR)} started an inspection of {place_of(site_id)} at {short_site(site_id)}.", None, "started")
        if realtime:
            thread = threading.Thread(target=self.run_existing, args=(inspection["id"], True), name=f"steward-inspection-{site_id}", daemon=True)
            self.threads[site_id] = thread
            thread.start()
            return inspection
        return self.run_existing(inspection["id"], False)

    def run(self, site_id: str, realtime: bool = False) -> dict:
        """One inspection and its chain, inline (tests) or on a thread (`realtime`)."""
        return self.start_now(site_id, OPERATOR, realtime)

    def run_existing(self, inspection_id: str, realtime: bool = False) -> dict:
        inspection = self.get(inspection_id)
        site = inspection["siteId"]
        try:
            self.service.ops.note(INSPECTOR, f"Inspecting {short_site(site)}", why="The scheduled inspection round")
            self.inspect(inspection_id)
            inspection = self.get(inspection_id)
            if not inspection.get("primary"):
                return self.finish_clean(inspection_id)
            self.attach_issue(inspection_id)
            pause = self.step_seconds() if realtime else 0
            for index, name in enumerate(STEPS[:5]):
                if index and pause and self._stop.wait(pause):
                    return self.get(inspection_id)
                getattr(self, f"step_{name}")(self.get(inspection_id), realtime)
        except Exception as error:
            detail = error.detail if isinstance(error, RealityError) else f"{type(error).__name__}: {str(error)[:200]}"
            record = self._update(inspection_id, state="failed", error=detail[:300], finishedAt=now())
            self._change(record, f"Inspection of {short_site(site)} stopped: {detail}", None, "failed")
            return record
        finally:
            self.service.ops.note(INSPECTOR, None)
        return self.get(inspection_id)

    def finish_clean(self, inspection_id: str) -> dict:
        record = self.get(inspection_id)
        site = record["siteId"]
        text = f"Inspected {place_of(site)}: {plural(len(record['stops']), 'stop')}, nothing outstanding."
        try:
            conversation = self.service.conversations.message(INSPECTOR, compliance_id(site), f"Inspection of {place_of(site)}", text, site_ids=[site],
                                                              data=dict(inspectionId=record["id"]), synthetic=True)
            self.service.conversations.answer(conversation["id"], compliance_id(site), "Thanks. Nothing for the owner from this one.")
            self._update(inspection_id, conversationIds=[conversation["id"]])
        except RealityError:
            pass
        record = self._update(inspection_id, state="completed", summary=text, finishedAt=now())
        self._change(record, text, None, "completed")
        return record

    # ---- the inspection -------------------------------------------------------------------------------------

    def route(self, site: str) -> list[str]:
        """Up to MAX_STOPS asset tags: overdue and blocked obligations (most important first), open compliance issues, out-of-band
        readings, then obligations falling due."""
        people, patrols = self.service.people, self.service.patrols
        obligations = people.obligations(site)
        issues = patrols.open_issues(site)
        readings = patrols.readings(site)
        known = {c["tag"] for c in self.service.reality.components(site)}
        bad = sorted([o for o in obligations if o.get("assetTag") and o.get("status") in BAD_STATUSES], key=finding_score, reverse=True)
        tags = [o["assetTag"] for o in bad]
        tags += [i["assetTag"] for i in issues if i.get("assetTag") and (i.get("obligationId") or i.get("kind") in COMPLIANCE_ISSUE_KINDS)]
        tags += [r["assetTag"] for r in readings if r.get("assetTag") and r.get("state") in ("high", "low")]
        tags += [o["assetTag"] for o in obligations if o.get("assetTag") and o.get("status") == "due_soon"]
        return [t for t in dict.fromkeys(tags) if t in known][:MAX_STOPS]

    def inspect(self, inspection_id: str) -> dict:
        record = self.get(inspection_id)
        site = record["siteId"]
        patrols = self.service.patrols
        obligations = self.service.people.obligations(site)
        issues = patrols.open_issues(site)
        readings = patrols.readings(site)
        walk_labels = {label["assetTag"]: label for label in patrols.labels(site)}
        stops, findings = [], []
        for index, tag in enumerate(self.route(site)):
            component = self.service.reality.component_by_tag(site, tag)
            try:
                frame_id, frame_url, note = patrols.look(site, tag, INSPECTOR)
            except Exception as error:  # the eye never fails the inspection
                frame_id, frame_url, note = None, None, f"eye unavailable ({type(error).__name__})"
            assessment = patrols.assess(site, component, obligations, issues, readings)
            label = walk_labels.get(tag)
            observation = (label or {}).get("observation") if (label or {}).get("assessedBy") not in (None, "rules") else None
            stop = dict(n=index + 1, assetTag=tag, assetName=component.get("name"), frameId=frame_id, frameUrl=frame_url if frame_id else None,
                        eyeNote=note, verdict=assessment["verdict"], reasons=list(assessment["reasons"])[:4], observation=observation,
                        walkLabelId=(label or {}).get("id"), at=now())
            stops.append(stop)
            self.service.telemetry.record(INSPECTOR, "tool", "inspect_asset", tokens=40, site_id=site, synthetic=True,
                                          detail=(f"{tag}: {'findings' if assessment['verdict'] == 'bad' else 'no findings'}"
                                                  + (f": {stop['reasons'][0]}" if stop["reasons"] else ""))[:200])
            findings += self.findings_at(site, tag, component, frame_id, assessment, obligations, issues, readings)
        findings.sort(key=lambda f: f["score"], reverse=True)
        primary = findings[0] if findings else None
        also = [f for f in findings[1:] if not primary or f.get("assetTag") != primary.get("assetTag") or f.get("obligationId") != primary.get("obligationId")]
        kind = self.work_kind(site, primary) if primary else None
        record = self._update(inspection_id, stops=stops, findings=findings, primary=primary, alsoNoted=[f["title"] for f in also][:4], workKind=kind,
                              contractor=contractor_for(site, kind) if kind else None)
        frames = sum(1 for s in stops if s["frameId"])
        self._change(record, f"{display_name(INSPECTOR)} inspected {plural(len(stops), 'asset')} at {short_site(site)} ({plural(frames, 'frame')}): "
                             + (f"{primary['title']}." if primary else "nothing outstanding."), None, "inspected")
        return record

    def findings_at(self, site: str, tag: str, component: dict, frame_id: str | None, assessment: dict, obligations: list[dict],
                    issues: list[dict], readings: list[dict]) -> list[dict]:
        out = []
        known = self.service.regulations.by_id()
        for obligation in obligations:
            if obligation.get("assetTag") != tag or obligation.get("status") not in BAD_STATUSES:
                continue
            _, noun = categorize(obligation)
            state = state_phrase(obligation)
            first = primary_regulation(obligation, known)
            out.append(dict(kind="obligation", assetTag=tag, assetName=component.get("name"), obligationId=obligation["id"], issueId=None,
                            title=f"{tag}: {noun} {state}", noun=noun, statePhrase=state, status=obligation["status"],
                            daysOverdue=overdue_days(obligation), score=finding_score(obligation), citation=cite_short(first) if first else None,
                            regulationIds=list(obligation.get("regulationIds") or []), frameId=frame_id))
        named = {o["id"] for o in obligations if o.get("assetTag") == tag}
        for issue in issues:
            if issue.get("assetTag") != tag or issue.get("obligationId") in named:
                continue
            if not (issue.get("obligationId") or issue.get("kind") in COMPLIANCE_ISSUE_KINDS):
                continue
            summary = first_sentence(" ".join(str(issue.get("summary") or issue["kind"]).split()), 120)
            out.append(dict(kind="issue", assetTag=tag, assetName=component.get("name"), obligationId=None, issueId=issue["id"], title=f"{tag}: {summary}",
                            noun=summary.rstrip("."), statePhrase="open", status="open", daysOverdue=None,
                            score=4 if issue.get("severity") == "high" else 3, citation=None,
                            regulationIds=list(self.service.regulations.for_issue(issue)), frameId=frame_id))
        for reading in readings:
            if reading.get("assetTag") != tag or reading.get("state") not in ("high", "low"):
                continue
            _, words = reading_words(reading)
            out.append(dict(kind="reading", assetTag=tag, assetName=component.get("name"), obligationId=None, issueId=None, title=words,
                            noun=words, statePhrase="out of band", status="reading", daysOverdue=None, score=2, citation=None,
                            regulationIds=[], frameId=frame_id))
        return out

    def work_kind(self, site: str, finding: dict) -> str:
        if finding.get("obligationId"):
            obligation = self.store.get("obligation", finding["obligationId"], site)
            if obligation:
                return obligation_kind(self.service, obligation)
        from .maintenance_planner import subsystem_of, work_kind
        return work_kind(finding.get("regulationIds"), finding.get("title", ""), [subsystem_of(self.store, site, finding.get("assetTag"))])

    def attach_issue(self, inspection_id: str) -> None:
        """The primary finding's open issue carries the inspection's frames (raised when there is none yet)."""
        record = self.get(inspection_id)
        site, primary = record["siteId"], record["primary"]
        frames = [s["frameId"] for s in record["stops"] if s["frameId"] and s["assetTag"] == primary.get("assetTag")]
        issues = self.service.issues
        if primary.get("issueId"):
            existing = self.store.get("issue", primary["issueId"], site)
        else:
            existing = next((i for i in self.store.all("issue", site) if i.get("status") == "open" and primary.get("obligationId")
                             and i.get("obligationId") == primary["obligationId"]), None)
        if existing:
            existing["evidenceFrameIds"] = list(dict.fromkeys((existing.get("evidenceFrameIds") or []) + frames))
            existing["inspectionId"] = record["id"]
            issue = issues._save(existing, f"Inspection evidence attached to {existing['id']}: {primary['title']}.", INSPECTOR)
        elif primary.get("obligationId"):
            obligation = self.store.get("obligation", primary["obligationId"], site) or {}
            kind = "compliance_blocked" if primary.get("status") == "blocked" else "compliance_overdue"
            severity = "high" if (primary.get("daysOverdue") or 0) > 7 else "medium"
            issue = issues.raise_issue(site, kind, severity, f"{obligation.get('title') or primary['title']} is {primary['statePhrase']} "
                                                             f"({primary.get('citation') or 'the site rule pack'}). Found on the inspection of {place_of(site)}.",
                                       asset_tag=primary.get("assetTag"), issue_id=f"iss-{site[:2]}-compliance-{primary['obligationId']}", source="agent",
                                       obligation_id=primary["obligationId"], document_id=obligation.get("documentId"), synthetic=True, actor=INSPECTOR,
                                       extra=dict(regulationIds=list(primary.get("regulationIds") or []), evidenceFrameIds=frames, inspectionId=record["id"],
                                                  ownerId=obligation.get("ownerId")))
        else:
            return
        self._update(inspection_id, issueId=issue["id"])

    # ---- context --------------------------------------------------------------------------------------------

    def alert_like(self, record: dict) -> dict:
        """The primary finding in the shape compliance_alerts.context() reads, with the Site Inspector as the walker."""
        site, primary = record["siteId"], record["primary"]
        frames = [s["frameId"] for s in record["stops"] if s["frameId"] and s["assetTag"] == primary.get("assetTag")]
        base = dict(id=record["id"], siteId=site, siteName=record.get("siteName"), assetTag=primary.get("assetTag"), assetName=primary.get("assetName"),
                    walker=INSPECTOR, frameIds=frames, severity="high" if (primary.get("daysOverdue") or 0) > 7 or primary.get("score", 0) >= 12 else "medium")
        obligation = self.store.get("obligation", primary["obligationId"], site) if primary.get("obligationId") else None
        if obligation:
            category, noun = categorize(obligation)
            known = self.service.regulations.by_id()
            first = primary_regulation(obligation, known)
            regulation_ids = list(self.service.regulations.for_obligation(obligation) or obligation.get("regulationIds") or [])
            if first and first["id"] in regulation_ids:
                regulation_ids = [first["id"]] + [rid for rid in regulation_ids if rid != first["id"]]
            crew = self.store.get("crew_member", obligation.get("ownerId") or "", site) if obligation.get("ownerId") else None
            base.update(obligationId=obligation["id"], obligationTitle=obligation.get("title"),
                        obligationStatus="blocked" if obligation.get("status") == "blocked" else "overdue", dueAt=obligation.get("dueAt"),
                        daysOverdue=overdue_days(obligation), blockedReason=obligation.get("blockedReason"), blockedBy=obligation.get("blockedBy"),
                        category=category, noun=noun, statePhrase=state_phrase(obligation), regulationIds=regulation_ids,
                        ownerCrewId=(crew or {}).get("id"), ownerName=(crew or {}).get("name"), ownerRole=(crew or {}).get("role"),
                        partnerSiteId=partner_site(site, category))
        else:
            base.update(obligationId=None, obligationTitle=primary["title"], obligationStatus="overdue", dueAt=None, daysOverdue=None, blockedReason=None,
                        blockedBy=None, category="generic", noun=primary.get("noun") or primary["title"], statePhrase=primary.get("statePhrase") or "open",
                        regulationIds=list(primary.get("regulationIds") or []), ownerCrewId=None, ownerName=None, ownerRole=None,
                        partnerSiteId=partner_site(site, "generic"))
        return base

    def context(self, record: dict) -> dict:
        alert = self.alert_like(record)
        c = self.service.patrols.alerts.context(alert)
        site = record["siteId"]
        if not alert.get("obligationId"):
            c["status_line"] = sentence(record["primary"]["title"]).rstrip(".")
        manager = manager_id(site)
        contractor = record.get("contractor") or contractor_for(site, record.get("workKind") or "general")
        kind = record.get("workKind") or "general"
        stops = record.get("stops") or []
        primary_stop = next((s for s in stops if s["assetTag"] == record["primary"].get("assetTag")), None)
        frame_at = parse_time((primary_stop or {}).get("at")) if (primary_stop or {}).get("frameId") else None
        c.update(alert=alert, record=record, contractor=contractor, work_label=WORK_KINDS.get(kind, WORK_KINDS["general"])["label"], kind=kind,
                 inspector_name=display_name(INSPECTOR), counsel_name=display_name(COUNSEL), manager_email=email_for(manager),
                 frame_time=local(site, frame_at).strftime("%H:%M") if frame_at else None, also=list(record.get("alsoNoted") or []),
                 requirements=REQUIREMENTS.get(alert.get("category") or "generic", REQUIREMENTS["generic"]),
                 site_rules=[rule.format(manager_role_l=c["manager_role_l"]) for rule in SITE_RULES],
                 inspected_at=local(site, parse_time(record["startedAt"]) or utcnow()).strftime("%H:%M"),
                 stops_text=self.stops_text(record), obligation=self.store.get("obligation", alert["obligationId"], site) if alert.get("obligationId") else None)
        return c

    def stops_text(self, record: dict) -> list[str]:
        site = record["siteId"]
        lines = []
        for stop in record.get("stops") or []:
            at = parse_time(stop.get("at"))
            when = local(site, at).strftime("%H:%M") if at else ""
            seen = f"frame {stop['frameId']} at {when}" if stop.get("frameId") else f"no frame ({stop.get('eyeNote') or 'the eye did not answer'})"
            words = "; ".join(stop.get("reasons") or [])
            line = f"{stop['assetTag']} ({stop.get('assetName') or 'asset'}): {seen}; {'findings' if stop['verdict'] == 'bad' else 'no findings'}: {words}"
            if stop.get("observation"):
                line += f". Walkthrough observation: {stop['observation']}"
            lines.append(line[:400])
        return lines

    @staticmethod
    def short_reason(c: dict) -> str:
        """The block's first clause: "the pump and valve contractor has no free slot for three weeks"."""
        text = lower_first((c.get("block_reason") or "waiting for its blocker").strip().rstrip("."))
        for mark in ("; ", ", and ", ", so "):
            text = text.split(mark, 1)[0]
        return text

    def due_date(self, c: dict) -> str | None:
        due = parse_time((c.get("obligation") or {}).get("dueAt"))
        return f"{local(c['site'], due).day} {local(c['site'], due):%B}" if due else None

    def due_text(self, c: dict) -> str:
        """"It fell due on 7 October and is held up: <first clause>." / "It fell due on 9 October, so it is overdue by 9 days." """
        date = self.due_date(c)
        if c["blocked"]:
            return (f"It fell due on {date} and is held up: " if date else "It is held up: ") + f"{self.short_reason(c)}."
        if date:
            return f"It fell due on {date}, so it is {c['state']}."
        return sentence(f"It is {c['state']}")

    # ---- step 1: the report chat ----------------------------------------------------------------------------

    def chat(self, convener: str, other: str, topic: str, site: str, briefs: dict, shared: str, goal: str, turns: list[dict], summary: dict,
             min_turns: int, max_turns: int, record: dict, realtime: bool) -> dict:
        """A long chat through the chat writer; the template turns play directly if the writer is unavailable."""
        try:
            return self.service.chats.run(convener=convener, participants=[convener, other], topic=topic, site_ids=[site], briefs=briefs, shared=shared,
                                          goal=goal, min_turns=min_turns, max_turns=max_turns, refs=dict(inspectionId=record["id"]),
                                          issue_id=record.get("issueId"), fallback=turns, fallback_summary=summary, realtime=realtime, origin="workflow")
        except Exception:
            return self.service.conversations.call(convener, other, topic, [dict(speaker=t["speaker"], text=t["text"].replace("{", "{{").replace("}", "}}"))
                                                                         for t in turns],
                                                   site_ids=[site], issue_id=record.get("issueId"), summary=summary, summary_by="hand-seed", synthetic=True,
                                                   workflow_id=record["id"], origin="workflow")

    def shared_facts(self, c: dict) -> str:
        lines = [f"Inspection {c['record']['id']} of {c['place']} at {c['site_name']}, {c['inspected_at']} site time, by the Site Inspector.",
                 f"Primary finding: {c['tag']} ({c['asset']}): {c['status_line']}.",
                 f"Regulation: {c['cite']}" + (f" ({c['reg_title']})" if c["reg_title"] else "") + (f". {c['rule']}" if c["rule"] else "."),
                 "Stops: " + " | ".join(c["stops_text"])]
        if c["also"]:
            lines.append("Also noted: " + "; ".join(c["also"]) + ".")
        lines.append(f"Contractor for this work: {c['contractor']}.")
        return "\n".join(lines)

    def report_turns(self, c: dict) -> list[dict]:
        inspector, compliance = INSPECTOR, c["compliance"]
        seen = (f"I have it on the agent eye at {c['frame_time']}" if c["frame_time"] else "The eye couldn't give me a frame at that stop, so this is from the records")
        stop = next((s for s in c["record"]["stops"] if s["assetTag"] == c["tag"]), {}) or {}
        noun = c["noun"].casefold()
        extra = stop.get("observation") or next((r for r in stop.get("reasons") or [] if not r.casefold().startswith(noun) and not r.startswith("No eye frame")), "")
        also = "; ".join(c["also"]) if c["also"] else "nothing else outstanding"
        date = self.due_date(c)
        blocker = (f" It fell due on {date} and has been held up since." if c["blocked"] and date else
                   f" It fell due on {date}." if date else "")
        return [
            dict(speaker=inspector, text=f"Compliance, it's the Site Inspector. I've just inspected {c['place']}: {plural(len(c['record']['stops']), 'stop')}. "
                                         f"The one that matters most is {c['tag']}, the {lower_first(c['asset'])}: {c['status_line']}."),
            dict(speaker=compliance, text=f"Thanks. That one is {c['cite_spoken']}" + (f", {lower_first(c['reg_title'])}" if c["reg_title"] else "") + "."
                                          + (f" {c['rule']}" if c["rule"] else "")),
            dict(speaker=inspector, text=sentence(f"{seen}") + (f" {sentence(extra)}" if extra else " The frame and the readings are in my notes.")),
            dict(speaker=compliance, text="Who owns it on the crew table, and is anything stopping the work?"),
            dict(speaker=inspector, text=sentence(f"{c['owner_intro']} owns it") + (blocker or f" It has been {c['state']}.")),
            dict(speaker=compliance, text=f"Then I'm treating it as {c['severity']} severity. In plain words, {c['risk']}."),
            dict(speaker=inspector, text=sentence(f"Agreed. Until it's put right the team should {c['hold']}")),
            dict(speaker=compliance, text=f"I'll put your frames and the readings in one pack for the {c['manager_role_l']}, with a recommendation: "
                                          f"{c['step']}. {c['contractor']} does this work for us."),
            dict(speaker=inspector, text=f"Also noted on the way round: {also}."),
            dict(speaker=compliance, text=f"Got it. The pack goes to the {c['manager_role_l']} now; the owner will hear from them with Compliance Counsel copied."),
        ]

    def step_report(self, record: dict, realtime: bool) -> None:
        c = self.context(record)
        compliance = c["compliance"]
        briefs = {
            INSPECTOR: (f"You are the Site Inspector, working across all three sites. You inspected {c['place']} at {c['site_name']} at {c['inspected_at']} "
                        f"site time. What you saw at each stop: " + " | ".join(c["stops_text"]) + f". Your most important finding is {c['tag']}: "
                        f"{c['status_line']}. Report it with the evidence (frames, readings), agree the severity with the Compliance Officer, say what "
                        f"must happen and by when, and mention what else you noted."),
            compliance: (f"You are the {c['compliance_name']}. The obligation: {(c.get('obligation') or {}).get('title') or c['noun']}. {self.due_text(c)} "
                         f"Owner on the crew table: {c['owner_label']}. Regulation: {c['cite']}" + (f", {c['reg_title']}" if c["reg_title"] else "")
                         + (f": {c['rule']}" if c["rule"] else "") + (f" Official text: {c['first'].get('officialUrl')}." if (c.get("first") or {}).get("officialUrl") else "")
                         + f" Severity rule: high when more than 7 days overdue. After this chat you send the evidence pack to the {c['manager_role_l']} "
                           f"and recommend: {c['step']}. The contractor for this work is {c['contractor']}."),
        }
        goal = (f"Report the inspection finding at {c['tag']} with the evidence, agree its severity, the hold until it is put right, and that the "
                f"evidence goes to the {c['manager_role_l']}.")
        summary = dict(headline=f"{c['tag']}: {lower_first(c['noun'])} {c['state']}; evidence to the {c['manager_role_l']}",
                       points=[sentence(f"{c['tag']}: {c['status_line']}"), f"Why it matters: {c['cite']}" + (f" ({c['reg_title']})." if c["reg_title"] else "."),
                               f"Also noted: {'; '.join(c['also']) or 'nothing else outstanding'}."],
                       decisions=[f"Treat it as {c['severity']} severity.", f"Send the evidence pack to the {c['manager_role_l']}."],
                       actions=[dict(owner=c["compliance_name"], task=f"Send the evidence pack to the {c['manager_role_l']}", due="now"),
                                dict(owner=c["owner_label"], task=sentence(c["hold"]).rstrip("."), due="until it is put right")])
        conversation = self.chat(INSPECTOR, compliance, f"Inspection of {c['place']}: {c['tag']} {lower_first(c['noun'])} {c['state']}", c["site"], briefs,
                                 self.shared_facts(c), goal, self.report_turns(c), summary, 10, 14, record, realtime)
        self._update(record["id"], conversationIds=[conversation["id"]])
        self.service.ops.note(compliance, f"Inspection finding: {c['tag']}", why="The Site Inspector reported a compliance gap")
        self._step(record["id"], "report", f"{c['inspector_name']} reported {c['tag']} to {c['compliance_name']} "
                                           f"({plural(len(conversation.get('transcript') or []), 'message')}): {c['cite']}.",
                   conversationId=conversation["id"], obligationId=c["alert"].get("obligationId"), issueId=record.get("issueId"))

    # ---- step 2: evidence to the manager --------------------------------------------------------------------

    def frame_attachments(self, record: dict, c: dict, prefix: str) -> tuple[list[dict], list[dict]]:
        """(attachments with base64 content, frame notes) for up to MAX_FRAMES frames, the primary asset's first."""
        site = record["siteId"]
        stops = sorted([s for s in record["stops"] if s.get("frameId")], key=lambda s: s["assetTag"] != c["tag"])
        attachments, notes = [], []
        for index, stop in enumerate(stops[:MAX_FRAMES], 1):
            try:
                data = labelled_bytes(self.service, stop["frameId"])
            except (RealityError, OSError):
                continue
            cid = f"{prefix}-{index}-{record['id'][-8:]}"
            name = f"evidence-{stop['assetTag'].lower()}-{index}.jpg"
            at = parse_time(stop.get("at"))
            attachments.append(dict(filename=name, content_type="image/jpeg", content_base64=base64.b64encode(data).decode("ascii"), content_id=cid,
                                    size=len(data), kind="frame", frameId=stop["frameId"]))
            notes.append(dict(cid=cid, filename=name, tag=stop["assetTag"], at=local(site, at).strftime("%d %b %Y %H:%M") if at else stop.get("at")))
        return attachments, notes

    @staticmethod
    def wire(attachments: list[dict]) -> list[dict]:
        """The outbox's attachment shape: filename, content_type, content_base64, content_id (sizes kept for the record)."""
        return [{k: a[k] for k in ("filename", "content_type", "content_base64", "content_id", "size") if a.get(k) is not None} for a in attachments]

    def evidence_text(self, record: dict, c: dict, refs: list[dict]) -> str:
        site = record["siteId"]
        lines = [f"Steward inspection evidence {record['id']}", "",
                 f"Site: {c['site_name']} ({site})",
                 f"Inspected by: {c['inspector_name']} at {c['inspected_at']} site time",
                 f"Primary finding: {c['tag']} ({c['asset']}): {c['status_line']}"]
        if c["alert"].get("obligationId"):
            lines.append(f"Obligation: {c['alert']['obligationId']}: {(c.get('obligation') or {}).get('title') or c['noun']}")
        lines += [f"Owner: {c['owner_label']}", f"Issue: {record.get('issueId') or '-'}", "", "Stops:"]
        lines += [f"  - {line}" for line in c["stops_text"]] or ["  - none"]
        lines += ["", "Also noted:"] + ([f"  - {item}" for item in c["also"]] or ["  - nothing else outstanding"])
        lines += ["", "Frames:"]
        frames = [self.store.get("eye_frame", s["frameId"], site) for s in record["stops"] if s.get("frameId")]
        lines += [f"  - {f['id']} at {f['at']} ({f.get('url')}), sha256 {f.get('sha256')}" for f in frames if f] or ["  - none"]
        lines += ["", "Regulations:"]
        lines += [f"  - {r['cite']}: {r['title']} ({r['url']}); {r['note']}" for r in refs] or ["  - none cited"]
        lines += ["", "Plain-language summaries with links to the official text; not legal advice."]
        return "\n".join(lines) + "\n"

    def manager_turns(self, c: dict, window_text: str) -> list[dict]:
        compliance, manager = c["compliance"], c["manager"]
        blocker = f" It was blocked because {lower_first(c['block_reason'])}." if c["blocked"] and c["block_reason"] else ""
        return [
            dict(speaker=compliance, text=f"{c['manager_role']}, the Site Inspector found {c['tag']}: {lower_first(c['noun'])} {c['state']}. "
                                          f"The evidence pack is in your inbox. It falls under {c['cite']}."),
            dict(speaker=manager, text="I've got it. What does it take to put right?"),
            dict(speaker=compliance, text=sentence(f"My recommendation: {c['step']}") + f" The work is for {c['contractor']}.{blocker}"),
            dict(speaker=manager, text="Then I'll tell the owner now and copy Compliance Counsel, so the legal side is covered from the start."),
            dict(speaker=compliance, text=f"Good. Counsel will send {c['contractor']} what the law requires for the job, so they arrive knowing what to deliver."),
            dict(speaker=manager, text=f"I'll call {c['contractor']} myself and agree a slot. {window_text}"),
            dict(speaker=compliance, text=sentence(f"Meanwhile the team keeps to the hold: {c['hold']}")),
            dict(speaker=manager, text="Agreed. Owner email first, then the call; I'll confirm the booking to the team when it's done."),
        ]

    def step_evidence_to_manager(self, record: dict, realtime: bool) -> None:
        c = self.context(record)
        site, compliance, manager = c["site"], c["compliance"], c["manager"]
        attachments, notes = self.frame_attachments(record, c, "pack")
        refs, _ = self.service.patrols.alerts.references(c, 0)
        evidence = self.evidence_text(record, c, refs).encode("utf-8")
        attachments.append(dict(filename=f"evidence-{record['id']}.txt", content_type="text/plain", content_base64=base64.b64encode(evidence).decode("ascii"),
                                size=len(evidence), kind="evidence"))
        subject = f"[{c['site_name']}] Inspection evidence: {c['tag']} {lower_first(c['noun'])} ({c['state']})"
        text = "\n".join([f"{c['manager_role']},", "",
                          f"The Site Inspector inspected {c['place']} at {c['inspected_at']} and found {c['tag']} ({lower_first(c['asset'])}): {c['status_line']}.",
                          f"It falls under {c['cite']}" + (f" ({c['reg_title']})." if c["reg_title"] else "."), "",
                          f"Recommendation: {c['step']}. The work is for {c['contractor']}.",
                          f"Hold until then: {c['hold']}.", "",
                          "Stops:", *[f"  - {line}" for line in c["stops_text"]], "",
                          "Attached: " + ", ".join(a["filename"] for a in attachments), "", c["compliance_name"]])
        frame_html = "".join(f"<div style=\"margin:8px 0\"><img src=\"cid:{esc(n['cid'])}\" alt=\"Agent eye frame of {esc(n['tag'])}\" width=\"560\" "
                             f"style=\"max-width:100%;border:1px solid #ddd\"><div style=\"font-size:12px;color:#666\">{esc(n['tag'])}, {esc(n['at'])} site time</div></div>"
                             for n in notes)
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px\">"
                f"<p>{esc(c['manager_role'])},</p><p>The Site Inspector inspected {esc(c['place'])} at {esc(c['inspected_at'])} and found "
                f"<b>{esc(c['tag'])}</b> ({esc(lower_first(c['asset']))}): {esc(c['status_line'])}. It falls under {esc(c['cite'])}.</p>"
                f"<p><b>Recommendation.</b> {esc(c['step'])}. The work is for {esc(c['contractor'])}. Hold until then: {esc(c['hold'])}.</p>"
                f"{frame_html}<p>{esc(c['compliance_name'])}</p></div>")
        mode, item_id, reason = "failed", None, None
        try:
            item = self.service.outbox.internal_email(sender=compliance, to_agent=manager, subject=subject[:300], text=text, html=html,
                                                      attachments=self.wire(attachments), site_id=site, purpose="inspection_evidence",
                                                      refs=dict(inspectionId=record["id"], issueId=record.get("issueId")))
            mode, item_id, reason = item.get("status") or "queued", item.get("id"), item.get("reason")
        except Exception as error:
            reason = f"{type(error).__name__}: {str(error)[:160]}"
        self._update(record["id"], outboxIds=[item_id] if item_id else [], evidenceEmail=dict(mode=mode, outboxId=item_id, subject=subject[:300],
                                                                                              attachments=[a["filename"] for a in attachments], reason=reason, at=now()))
        window = self.covering_window(record)
        window_text = (f"The planner has a window on {window['localStart']} {city(site)} time; I'll offer that first." if window and window.get("localStart")
                       else "The planner has nothing booked for it yet, so I'll offer the next slots.")
        briefs = {
            compliance: (f"You are the {c['compliance_name']}. You have just emailed the evidence pack ({len(notes)} frames and the evidence file) to the "
                         f"{c['manager_role_l']}. The finding: {c['tag']}: {c['status_line']}. Regulation: {c['cite']}. In plain words: {c['risk']}. "
                         f"Recommendation: {c['step']}. Hold until then: {c['hold']}. The contractor for this work is {c['contractor']}."),
            manager: (f"You are the {c['manager_name']}. You approve work orders and schedule maintenance for your site. {window_text} "
                      f"The contractor for this work is {c['contractor']}. Decide to email the owner about it with Compliance Counsel copied, and to call "
                      f"{c['contractor']} yourself to book the visit. Say who does what."),
        }
        goal = f"Decide to email the owner with Compliance Counsel copied and to call {c['contractor']} to book the visit; agree who does what."
        summary = dict(headline=f"{c['manager_name']} tells the owner and books {c['contractor']} for {c['tag']}",
                       points=[sentence(f"{c['tag']}: {c['noun']} {c['state']}"), f"Applies: {c['cite']}.", window_text],
                       decisions=["Email the owner with Compliance Counsel copied.", f"Call {c['contractor']} to book the visit."],
                       actions=[dict(owner=c["manager_name"], task="Email the owner (Compliance Counsel copied)", due="now"),
                                dict(owner=c["counsel_name"], task=f"Send {c['contractor']} the legal requirements for the job", due="today"),
                                dict(owner=c["manager_name"], task=f"Call {c['contractor']} and book the visit", due="today")])
        conversation = self.chat(compliance, manager, f"Decision: {c['tag']} {lower_first(c['noun'])}", site, briefs, self.shared_facts(c), goal,
                                 self.manager_turns(c, window_text), summary, 6, 10, record, realtime)
        self._update(record["id"], conversationIds=[conversation["id"]])
        self.service.ops.note(manager, f"Owner email and contractor call: {c['tag']}", why="The Site Inspector's finding")
        self._step(record["id"], "evidence_to_manager", f"{c['compliance_name']} sent the evidence pack to the {c['manager_role_l']} ({mode}; "
                                                        f"{plural(len(notes), 'frame')}) and they agreed: email the owner, call {c['contractor']}.",
                   outboxId=item_id, conversationId=conversation["id"], mode=mode)

    # ---- step 3: the owner email ----------------------------------------------------------------------------

    def compose_owner_email(self, record: dict, c: dict) -> dict:
        attachments, notes = self.frame_attachments(record, c, "evidence")
        total = sum(a["size"] for a in attachments)
        refs, files = self.service.patrols.alerts.references(c, MAX_ATTACHMENT_BYTES - total)
        attachments += files
        evidence = self.evidence_text(record, c, refs).encode("utf-8")
        attachments.append(dict(filename=f"evidence-{record['id']}.txt", content_type="text/plain", content_base64=base64.b64encode(evidence).decode("ascii"),
                                size=len(evidence), kind="evidence"))
        title = (c.get("obligation") or {}).get("title") or c["noun"]
        subject = f"[{c['site_name']}] Compliance: {title} ({c['state']})"
        what = (f"On today's inspection of {c['place']}, the Site Inspector stopped at {c['tag']} ({lower_first(c['asset'])}): {c['status_line']}."
                + (" Also noted: " + "; ".join(c["also"]) + "." if c["also"] else ""))
        why = f"{c['cite_spoken'][:1].upper() + c['cite_spoken'][1:]}" + (f" ({c['reg_title_full']})" if c["reg_title_full"] else "") + (
            f": {c['rule_full']}" if c["rule_full"] else ".")
        who = sentence(f"{c['owner_label']} owns it on the {c['short']} crew table") + f" The compliance officer has the evidence pack and I have approved the work."
        plan = (f"I'm calling {c['contractor']} now to book the {c['work_label']}, and Compliance Counsel (copied here) is sending them what the law "
                f"requires for the job. You'll get the booking when it's agreed. Until then the team will {c['hold']}.")
        attribution = list(dict.fromkeys(r["attribution"] for r in refs if r.get("attribution")))
        ref_items = "".join(f"<li><a href=\"{esc(r['url'])}\">{esc(r['cite'])}</a>: {esc(r['title'])} <span style=\"color:#666\">({esc(r['note'])})</span></li>"
                            for r in refs)
        frame_html = "".join(f"<div style=\"margin:8px 0\"><img src=\"cid:{esc(n['cid'])}\" alt=\"Agent eye frame of {esc(n['tag'])}\" width=\"560\" "
                             f"style=\"max-width:100%;border-radius:6px;border:1px solid #ddd\"><div style=\"font-size:12px;color:#666\">{esc(n['tag'])}, "
                             f"{esc(n['at'])} site time ({esc(n['filename'])})</div></div>" for n in notes) or (
            "<p style=\"color:#666\">The agent eye had no frame at this stop; the readings and the records are in the evidence file.</p>")
        attached_list = "".join(f"<li>{esc(a['filename'])} ({max(1, round(a['size'] / 1024))} KB)</li>" for a in attachments)
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px\">"
                f"<p style=\"font-size:12px;color:#666;margin:0 0 6px\">Steward · {esc(c['site_name'])} · {esc(c['manager_name'])}</p>"
                f"<h2 style=\"font-size:18px;margin:0 0 14px\">{esc(c['tag'])}: {esc(c['noun'])} {esc(c['state'])}</h2>"
                f"<p><b>What we found.</b> {esc(what)}</p>"
                f"<p><b>Why it matters.</b> {esc(why)} In plain words: {esc(c['risk'])}.</p>"
                f"<ul style=\"padding-left:18px\">{ref_items}</ul>"
                f"<p><b>Who owns it.</b> {esc(who)}</p>"
                f"<p style=\"background:#f4f4f4;border-left:3px solid #1a1a1a;padding:10px 12px\"><b>What happens next.</b> {esc(plan)}</p>"
                f"<p><b>Evidence.</b></p>{frame_html}"
                f"<p><b>Attached.</b></p><ul style=\"padding-left:18px\">{attached_list}</ul>"
                + "".join(f"<p style=\"font-size:12px;color:#666\">{esc(line)}</p>" for line in attribution)
                + ("<p style=\"font-size:12px;color:#666\">The summaries above are ours; the attached PDFs are the official texts, unedited.</p>" if files else "")
                + "<p style=\"font-size:12px;color:#666\">Regulation summaries are plain-language notes with links to the official text, not legal advice.</p>"
                f"<p>{esc(c['manager_name'])}</p></div>")
        text = "\n".join([f"{c['tag']}: {c['noun']} {c['state']} ({c['site_name']})", "",
                          f"What we found: {what}", "",
                          f"Why it matters: {why} In plain words: {c['risk']}.",
                          *[f"  - {r['cite']}: {r['title']} ({r['url']}); {r['note']}" for r in refs], "",
                          f"Who owns it: {who}", "",
                          f"What happens next: {plan}", "",
                          "Evidence: " + (", ".join(f"{n['filename']} ({n['at']} site time)" for n in notes) or "no eye frame; see the evidence file."), "",
                          "Attached: " + ", ".join(a["filename"] for a in attachments), "",
                          *attribution,
                          *(["The summaries above are ours; the attached PDFs are the official texts, unedited."] if files else []),
                          "Regulation summaries are plain-language notes with links to the official text, not legal advice.", "", c["manager_name"]])
        return dict(subject=subject[:300], html=html, text=text, attachments=attachments, references=refs)

    def step_owner_email(self, record: dict, realtime: bool) -> None:
        c = self.context(record)
        message = self.compose_owner_email(record, c)
        mode, item_id, reason = "failed", None, None
        try:
            item = self.service.outbox.email(sender=c["manager"], to_role="owner", subject=message["subject"], text=message["text"], html=message["html"],
                                             attachments=self.wire(message["attachments"]), cc=[COUNSEL], site_id=c["site"], purpose="inspection_owner",
                                             refs=dict(inspectionId=record["id"], issueId=record.get("issueId"), obligationId=c["alert"].get("obligationId")),
                                             dedupe_key=f"inspection:{record['id']}:owner", priority=3)
            mode, item_id, reason = item.get("status") or "queued", item.get("id"), item.get("reason")
        except Exception as error:
            reason = f"{type(error).__name__}: {str(error)[:160]}"
        self._update(record["id"], outboxIds=[item_id] if item_id else [],
                     ownerEmail=dict(mode=mode, outboxId=item_id, fromAgent=c["manager"], fromName=c["manager_name"], toRole="owner", cc=[COUNSEL],
                                     subject=message["subject"], attachments=[dict(filename=a["filename"], contentType=a["content_type"], size=a["size"],
                                                                                   inline=bool(a.get("content_id")), kind=a.get("kind")) for a in message["attachments"]],
                                     references=[{k: r[k] for k in ("id", "cite", "title", "url", "attached", "note", "jurisdiction")} for r in message["references"]],
                                     reason=reason, at=now()))
        names = ", ".join(a["filename"] for a in message["attachments"])
        self._step(record["id"], "owner_email", f"{c['manager_name']} emailed the owner with Compliance Counsel copied ({mode}): \"{message['subject']}\" "
                                                f"with {names}."[:400], outboxId=item_id, mode=mode)

    # ---- step 4: Compliance Counsel to the contractor --------------------------------------------------------

    def job_pack(self, record: dict, c: dict) -> str:
        lines = [f"Job pack {record['id']}: {c['work_label']} at {c['site_name']}", "",
                 f"Asset: {c['tag']} ({c['asset']})",
                 f"What is wrong: {c['status_line']}",
                 f"Regulation: {c['cite']}" + (f" ({c['reg_title']})" if c["reg_title"] else ""),
                 f"Deadline: {self.due_text(c)} As soon as you can attend.",
                 f"Until then: the team will {c['hold']}", "",
                 "What the work must deliver:", *[f"  - {item}" for item in c["requirements"]], "",
                 "On site:", *[f"  - {rule}" for rule in c["site_rules"]], "",
                 f"Site contact: {c['manager_name']} ({c['manager_email'] or 'the site manager'})"]
        return "\n".join(lines) + "\n"

    def step_counsel_to_contractor(self, record: dict, realtime: bool) -> None:
        c = self.context(record)
        refs, files = self.service.patrols.alerts.references(c, MAX_ATTACHMENT_BYTES)
        pack = self.job_pack(record, c).encode("utf-8")
        attachments = files + [dict(filename=f"job-pack-{record['id']}.txt", content_type="text/plain", content_base64=base64.b64encode(pack).decode("ascii"),
                                    size=len(pack), kind="job_pack")]
        subject = f"[{c['site_name']}] {c['tag']} {lower_first(c['noun'])}: what the work must meet"
        attribution = list(dict.fromkeys(r["attribution"] for r in refs if r.get("attribution")))
        intro = (f"I'm Compliance Counsel for {c['site_name']}, copied on the {c['manager_role_l']}'s report about {c['tag']} ({lower_first(c['asset'])}). "
                 f"The {c['manager_role_l']} will call you to book the visit. Before you come, here is what the law asks of this job.")
        law = f"It falls under {c['cite_spoken']}" + (f" ({c['reg_title_full']})" if c["reg_title_full"] else "") + (f": {c['rule_full']}" if c["rule_full"] else ".")
        text = "\n".join([f"Hello {c['contractor']},", "", intro, "", law, "",
                          "What the work must deliver:", *[f"  - {item}" for item in c["requirements"]], "",
                          f"Deadline: {self.due_text(c)} Please attend as soon as you can.", "",
                          "On site:", *[f"  - {rule}" for rule in c["site_rules"]], "",
                          *[f"  - {r['cite']}: {r['title']} ({r['url']}); {r['note']}" for r in refs], "",
                          *attribution,
                          "This is a plain-language summary of the obligations with links to the official text, not legal advice.", "",
                          c["counsel_name"]])
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px\">"
                f"<p>Hello {esc(c['contractor'])},</p><p>{esc(intro)}</p><p>{esc(law)}</p>"
                "<p><b>What the work must deliver.</b></p><ul style=\"padding-left:18px\">" + "".join(f"<li>{esc(item)}</li>" for item in c["requirements"]) + "</ul>"
                f"<p><b>Deadline.</b> {esc(self.due_text(c))} Please attend as soon as you can.</p>"
                "<p><b>On site.</b></p><ul style=\"padding-left:18px\">" + "".join(f"<li>{esc(rule)}</li>" for rule in c["site_rules"]) + "</ul>"
                + ("<ul style=\"padding-left:18px\">" + "".join(f"<li><a href=\"{esc(r['url'])}\">{esc(r['cite'])}</a>: {esc(r['title'])}</li>" for r in refs) + "</ul>"
                   if refs else "")
                + "".join(f"<p style=\"font-size:12px;color:#666\">{esc(line)}</p>" for line in attribution)
                + "<p style=\"font-size:12px;color:#666\">A plain-language summary of the obligations with links to the official text, not legal advice.</p>"
                f"<p>{esc(c['counsel_name'])}</p></div>")
        mode, item_id, reason = "failed", None, None
        try:
            item = self.service.outbox.email(sender=COUNSEL, to_role="contractor", subject=subject[:300], text=text, html=html, attachments=self.wire(attachments),
                                             cc=[c["manager"]], site_id=c["site"], purpose="inspection_counsel",
                                             refs=dict(inspectionId=record["id"], issueId=record.get("issueId"), obligationId=c["alert"].get("obligationId")),
                                             dedupe_key=f"inspection:{record['id']}:counsel", priority=4)
            mode, item_id, reason = item.get("status") or "queued", item.get("id"), item.get("reason")
        except Exception as error:
            reason = f"{type(error).__name__}: {str(error)[:160]}"
        self._update(record["id"], outboxIds=[item_id] if item_id else [],
                     counselEmail=dict(mode=mode, outboxId=item_id, fromAgent=COUNSEL, toRole="contractor", cc=[c["manager"]], subject=subject[:300],
                                       attachments=[a["filename"] for a in attachments], reason=reason, at=now()))
        self._step(record["id"], "counsel_to_contractor", f"{c['counsel_name']} emailed {c['contractor']} what the law requires for the job ({mode}), "
                                                          f"the {c['manager_role_l']} copied.", outboxId=item_id, mode=mode)

    # ---- step 5: the contractor call ------------------------------------------------------------------------

    def covering_window(self, record: dict) -> dict | None:
        """The open window that already covers the primary obligation (the planner's, or this inspection's own)."""
        if record.get("windowId"):
            window = self.store.get("maintenance_window", record["windowId"], "")
            if window and window.get("status") in OPEN:
                return window
        obligation_id = (record.get("primary") or {}).get("obligationId")
        if not obligation_id:
            return None
        obligation = self.store.get("obligation", obligation_id)
        if not obligation:
            return None
        windows = self.store.all("maintenance_window", "")
        planner = getattr(self.service, "maintenance_planner", None)
        if planner is not None:
            window = planner.covering(obligation, record.get("workKind") or obligation_kind(self.service, obligation), windows)
            return window if window and window.get("status") in OPEN else None
        return next((w for w in windows if w.get("obligationId") == obligation_id and w.get("status") in OPEN), None)

    def step_contractor_call(self, record: dict, realtime: bool, priority: int = 3, not_before: str | None = None,
                             extra_context: dict | None = None) -> None:
        """`priority`, `not_before` and `extra_context` let the live sequence (demo_sequence.py) place this call first, on time."""
        c = self.context(record)
        site = c["site"]
        existing = self.covering_window(record)
        slots = candidate_slots(site, record.get("workKind") or "general", utcnow(), existing)
        pack = self.job_pack(record, c)
        attachments, _ = self.frame_attachments(record, c, "pack")
        file = dict(subject=f"[{c['site_name']}] Job pack: {c['work_label']} at {c['tag']}", text=pack,
                    attachments=self.wire(attachments) + [dict(filename=f"job-pack-{record['id']}.txt", content_type="text/plain",
                                                               content_base64=base64.b64encode(pack.encode("utf-8")).decode("ascii"), size=len(pack.encode("utf-8")))],
                    cc=[c["manager"]])
        first = (f"{c['tag']}, the {lower_first(c['asset'])} at {c['site_name']}: the {lower_first(c['noun'])} is {c['state']}" if c["blocked"] else
                 f"{c['tag']}, the {lower_first(c['asset'])} at {c['site_name']}: {c['status_line']}")
        facts = [sentence(first),
                 sentence(f"It falls under {c['cite_spoken']}") + f" In plain words, {c['risk']}.",
                 sentence(f"Until it is fixed the team will {c['hold']}"),
                 f"Compliance Counsel has emailed {c['contractor']} what the law requires for the job; the job pack is ready to email.",
                 c["site_rules"][0]]
        if c["blocked"] and c["block_reason"]:
            unblocks = re.search(r"contractor|slot|tools|availab|visit", c["block_reason"], re.I)
            facts.insert(1, sentence(f"It has been held up because {lower_first(c['block_reason'])}")
                         + (" An earlier visit unblocks it." if unblocks else " Book the visit for what can be done now; anything the block covers waits until it clears."))
        goal = (f"Book {c['contractor']} for the {c['work_label']} at {c['tag']} ({lower_first(c['noun'])}, {c['state']}) at {c['site_name']}: "
                f"agree one of the slots.")
        self._update(record["id"], slots=slots, windowId=(existing or {}).get("id") or record.get("windowId"))
        self.register_handlers()
        try:
            call = self.service.voice_calls.request(purpose="contractor_schedule", caller=c["manager"], callee_role="contractor", callee_name=c["contractor"],
                                                    site_id=site, goal=goal, facts=facts, options=[dict(id=s["id"], label=s["label"]) for s in slots],
                                                    can_do=["book_slot", "email_file", "counsel_call", "note"], file=file,
                                                    context=dict(inspectionId=record["id"], slots=slots, contractor=c["contractor"], **(extra_context or {})),
                                                    refs=dict(inspectionId=record["id"], issueId=record.get("issueId"), obligationId=c["alert"].get("obligationId")),
                                                    priority=priority, dedupe_key=f"inspection:{record['id']}:contractor", not_before=not_before)
        except Exception as error:
            reason = f"{type(error).__name__}: {str(error)[:160]}"
            self._step(record["id"], "contractor_call", f"{c['manager_name']} could not place the call to {c['contractor']} ({reason}).", mode="failed")
            self.finish_booking(record["id"], dict(id=None, status="failed", attempt=99, refs=dict(inspectionId=record["id"]),
                                                   outcome=dict(result="failed", decision="", summary=reason, chosenOptionId=None, followUps=[])))
            return
        self._update(record["id"], callId=call["id"], callRequestedAt=now())
        status = call.get("status") or "queued"
        self._step(record["id"], "contractor_call", f"{c['manager_name']} is calling {c['contractor']} ({status}) to agree a slot: "
                                                    + "; ".join(s["label"] for s in slots) + ".", callId=call["id"], mode=status)
        if status in NOT_CALLED and not (extra_context or {}).get("liveSequenceRunId"):  # the live sequence books through its own handler
            self.finish_booking(record["id"], dict(call, attempt=99, outcome=call.get("outcome") or dict(result=status, decision="", summary=call.get("reason") or "",
                                                                                                         chosenOptionId=None, followUps=[])))

    # ---- step 6: the booking --------------------------------------------------------------------------------

    def on_contractor_call(self, call: dict) -> dict | None:
        """VoiceCalls handler for `contractor_schedule`: book the agreed slot (or the first one) and confirm."""
        inspection_id = (call.get("refs") or {}).get("inspectionId") or (call.get("context") or {}).get("inspectionId")
        if not inspection_id or not self.store.get("inspection", inspection_id):
            return None
        sequence = getattr(self.service, "sequence", None)
        if sequence is not None and (call.get("context") or {}).get("liveSequenceRunId"):
            return sequence.on_contractor_call(call, inspection_id)
        outcome = call.get("outcome") or {}
        result = outcome.get("result") or call.get("status") or "undecided"
        if result in ("voicemail", "no_answer") and int(call.get("attempt") or 1) <= self.call_retries():
            note = f"The call reached {('voicemail' if result == 'voicemail' else 'no answer')}; it will be tried again."
            self._update(inspection_id, lastCallResult=result)
            return dict(handled=[], notes=[note], refs={})
        return self.finish_booking(inspection_id, call)

    def finish_booking(self, inspection_id: str, call: dict, timed_out: bool = False, confirm: bool = True) -> dict | None:
        """Book (or move) the window, tell the team and, unless `confirm` is false (the live sequence sends it later), confirm."""
        with self.lock:
            record = self.get(inspection_id)
            if any(step["name"] == "booking" for step in record["steps"]):
                return dict(handled=["book_slot"], notes=["Already booked."], refs=dict(windowId=record.get("windowId")))
        c = self.context(record)
        site, manager = c["site"], c["manager"]
        outcome = call.get("outcome") or {}
        result = outcome.get("result") or call.get("status") or "undecided"
        slots = record.get("slots") or candidate_slots(site, record.get("workKind") or "general", utcnow(), self.covering_window(record))
        chosen = outcome.get("chosenOptionId") if result == "agreed" else None
        slot = next((s for s in slots if s["id"] == chosen), None)
        agreed = slot is not None
        slot = slot or (slots[0] if slots else None)
        if slot is None:
            raise RealityError("No slot to book.", "INVALID_REQUEST", "The site has no working-hours slot in the next 60 days.")
        window, action = self.book(record, c, slot, agreed, call)
        conversation_ids = self.tell_team(record, c, window, agreed)
        item_id, mode = self.confirm(record, c, window, slot, agreed, result, call) if confirm else (None, "later")
        self._update(inspection_id, windowId=window["id"], conversationIds=conversation_ids, outboxIds=[item_id] if item_id else [],
                     booking=dict(windowId=window["id"], slotId=slot["id"], startAt=window["startAt"], label=slot["label"].replace(" (currently booked)", ""),
                                  agreed=agreed, action=action, callResult=result, callId=call.get("id"), confirmationOutboxId=item_id, at=now()))
        verb = {"booked": "booked", "moved": "moved the booking to", "kept": "kept the booking for"}[action]
        how = ("as agreed on the call" if agreed else
               "after the call did not report back; the confirmation asks them to reply" if timed_out else
               f"without an agreed slot ({result}); the confirmation asks them to reply")
        summary = f"{c['manager_name']} {verb} {window['localStart']} {city(site)} time with {c['contractor']} {how}."
        self._step(inspection_id, "booking", summary, windowId=window["id"], outboxId=item_id, callId=call.get("id"), mode=mode,
                   conversationIds=conversation_ids)
        record = self._update(inspection_id, state="completed", finishedAt=now(), summary=summary)
        self._change(record, f"Inspection of {short_site(site)} completed: {summary}", None, "completed")
        self.service.ops.note(manager, None)
        return dict(handled=["book_slot"], notes=[summary], refs=dict(windowId=window["id"]))

    def book(self, record: dict, c: dict, slot: dict, agreed: bool, call: dict) -> tuple[dict, str]:
        """Book or move exactly one window for the obligation: the planner's (moved), this inspection's own, or a new one."""
        site, manager = c["site"], c["manager"]
        start, end = parse_time(slot["startAt"]), parse_time(slot["endAt"])
        kind = record.get("workKind") or "general"
        spec = WORK_KINDS.get(kind, WORK_KINDS["general"])
        tz = tz_for(site)
        local_start, local_end = slot_label_short(site, start), f"{end.astimezone(tz):%H:%M}"
        existing = self.covering_window(record)
        tag = c["tag"] if c["tag"] != "the site" else None
        fields = dict(date=start.astimezone(tz).date().isoformat(), startAt=iso(start), endAt=iso(end), timeZone=str(tz), localStart=local_start, localEnd=local_end,
                      examiner=c["contractor"][:200], status="approved", approvedBy=manager, approvedAt=now(), origin="contractor_call", inspectionId=record["id"],
                      callId=call.get("id"), awaitingContractor=not agreed, bookedVia="contractor_call")
        if existing:
            previous = existing.get("startAt")
            action = "kept" if previous == fields["startAt"] else "moved"
            if existing.get("origin") and existing.get("origin") != "contractor_call":
                fields["previousOrigin"] = existing["origin"]
            if action == "moved":
                fields["rescheduledFrom"] = previous
            existing.update(fields)
            window = self.service.maintenance._put(existing)
        else:
            obligation = c.get("obligation") or {}
            action = "booked"
            window = dict(id=f"mw-insp-{record['id'].removeprefix('insp-')}"[:120], siteIds=[site], scope=(obligation.get("title") or c["noun"])[:500],
                          conversationId=None, assetTags=[tag] if tag else [], obligationId=obligation.get("id"),
                          obligationIds=[obligation["id"]] if obligation.get("id") else [], ownerId=obligation.get("ownerId"),
                          ownerName=(self.store.get("crew_member", obligation.get("ownerId") or "", site) or {}).get("name") if obligation.get("ownerId") else None,
                          regulationIds=list(c["alert"].get("regulationIds") or []), workKind=kind, workFamily=spec["family"],
                          cycleStart=obligation.get("lastDoneAt"), cycleDueAt=obligation.get("dueAt"), dueStatus=obligation.get("status"),
                          bookedReason=c["state"], proposedBy=manager, linkedWindowIds=[], coordination=None, teamConversationIds=[],
                          issueId=record.get("issueId"), scenarioId=None, synthetic=True, generator="inspection", createdAt=now(), **fields)
            window = self.service.maintenance._put(window)
        verb = {"booked": "booked", "moved": "moved", "kept": "kept"}[action]
        self.service.reality.emit_change(site, "maintenance", window["id"],
                                         f"{c['manager_name']} {verb} the {spec['label']} for {tag or 'the site'} on {local_start} {city(site)} time with "
                                         f"{c['contractor']}" + (" (agreed on the call)." if agreed else " (waiting for the contractor to confirm)."), tag,
                                         extra=dict(maintenanceId=window["id"], status=window["status"], crossSite=False, origin="contractor_call",
                                                    obligationId=window.get("obligationId"), startAt=window["startAt"], workKind=kind, inspectionId=record["id"]))
        issue = self.store.get("issue", record["issueId"], site) if record.get("issueId") else None
        if issue and issue.get("status") == "open":
            issue.update(maintenanceWindowId=window["id"], plannedAt=window["startAt"])
            text = f"Booked for {local_start} {city(site)} time with {c['contractor']} ({window['id']})" + ("." if agreed else ", waiting for them to confirm.")
            issue["history"] = (issue.get("history") or [])[-19:] + [dict(at=now(), severity=issue.get("severity"), summary=text[:300], by=manager)]
            self.service.issues._save(issue, f"Issue {issue['kind']} on {issue.get('assetTag') or 'the site'}: {text}"[:480], manager)
        return window, action

    def tell_team(self, record: dict, c: dict, window: dict, agreed: bool) -> list[str]:
        site, manager = c["site"], c["manager"]
        when = f"{window['localStart']} {city(site)} time"
        state = "agreed on the call" if agreed else "waiting for them to confirm"
        messages = [
            (c["compliance"], f"{c['contractor']} is booked for {when} ({state}) for the {c['work_label']} at {c['tag']}. Counsel has sent them the requirements.",
             "Noted. I'll close the obligation once their report is in."),
            (engineer_id(site), f"{c['contractor']} comes on {when} for {c['tag']} ({state}). Please have it ready: {c['hold']}.",
             f"Noted. I'll have {c['tag']} ready and walk it with them."),
            (technician_id(site), f"Please confirm {c['contractor']}'s visit for {c['tag']} on {when} the day before.", "Noted. I'll confirm the day before."),
        ]
        ids = []
        conversations = self.service.conversations
        for teammate, text, answer in messages:
            try:
                conversation = conversations.message(manager, teammate, f"Booked: {c['tag']} {c['work_label']}, {window['localStart']}", text, site_ids=[site],
                                                     issue_id=record.get("issueId"), data=dict(maintenanceWindowId=window["id"], inspectionId=record["id"]),
                                                     synthetic=True)
                conversations.answer(conversation["id"], teammate, answer)
                ids.append(conversation["id"])
            except RealityError:
                continue
        window["teamConversationIds"] = list(dict.fromkeys((window.get("teamConversationIds") or []) + ids))
        self.service.maintenance._put(window)
        return ids

    def confirm(self, record: dict, c: dict, window: dict, slot: dict, agreed: bool, result: str, call: dict,
                attachments: list[dict] | None = None) -> tuple[str | None, str]:
        site = c["site"]
        when = f"{window['localStart']}–{window['localEnd']} {city(site)} time"
        if agreed:
            subject = f"[{c['site_name']}] Booked: {c['work_label']} at {c['tag']}, {window['localStart']}"
            opening = f"Thanks for agreeing the visit on the phone. You're booked for {when} for the {c['work_label']} at {c['tag']}."
            ask = "If anything changes, reply to this email."
        else:
            subject = f"[{c['site_name']}] Please confirm: {c['work_label']} at {c['tag']}, {window['localStart']}"
            opening = (f"We couldn't agree a time on the phone, so I've held {when} for the {c['work_label']} at {c['tag']}.")
            ask = "Please reply to confirm this slot, or tell me a time that works for you."
        purpose = sentence(f"{c['noun']} at {c['tag']} ({lower_first(c['asset'])}), {c['state']}")
        lines = [f"Hello {c['contractor']},", "", opening, "",
                 f"What it's for: {purpose}",
                 f"Where: {c['site_name']}, {c['place']}. {c['site_rules'][0]}",
                 c["site_rules"][1], "",
                 "What the work must deliver:", *[f"  - {item}" for item in c["requirements"]], "",
                 "Compliance Counsel's email has the legal requirements and the official links.", "", ask, "", c["manager_name"]]
        text = "\n".join(lines)
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px\">"
                f"<p>Hello {esc(c['contractor'])},</p><p>{esc(opening)}</p>"
                f"<p><b>What it's for.</b> {esc(purpose)}</p>"
                f"<p><b>Where.</b> {esc(c['site_name'])}, {esc(c['place'])}. {esc(c['site_rules'][0])} {esc(c['site_rules'][1])}</p>"
                "<p><b>What the work must deliver.</b></p><ul style=\"padding-left:18px\">" + "".join(f"<li>{esc(item)}</li>" for item in c["requirements"]) + "</ul>"
                f"<p>Compliance Counsel's email has the legal requirements and the official links.</p><p>{esc(ask)}</p><p>{esc(c['manager_name'])}</p></div>")
        try:
            item = self.service.outbox.email(sender=c["manager"], to_role="contractor", subject=subject[:300], text=text, html=html,
                                             attachments=list(attachments or []), cc=["owner", COUNSEL], site_id=site, purpose="inspection_booking",
                                             refs=dict(inspectionId=record["id"], windowId=window["id"], callId=call.get("id")),
                                             dedupe_key=f"inspection:{record['id']}:booking", priority=4)
            return item.get("id"), item.get("status") or "queued"
        except Exception as error:
            self.store.event(site, c["manager"], "inspection.confirmation_failed", "Booking confirmation could not be queued", f"{type(error).__name__}")
            return None, "failed"


def slot_label_short(site: str, start: datetime) -> str:
    """'Mon 19 Oct 08:30', the planner's localStart shape."""
    moment = start.astimezone(tz_for(site))
    return f"{moment:%a} {moment.day} {moment:%b} {moment:%H:%M}"
