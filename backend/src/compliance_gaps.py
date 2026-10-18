"""Compliance is never 100 % (contract 7 §6): real gaps at every site, and a slow drift that brings one back after the agents
have closed them all.

Gaps are seed records of the `obligations` family that carry `gap: overdue | blocked` (backend/seed/synthetic/obligations.json
and its hand-seed twin): Myer has one overdue obligation, Bristol and Tomioka one overdue and one blocked, each on a real
asset with an owner from the site's crew, citations from the site's own regulation pack (VIC-AU, ENG-UK, JP; never the
comparison records) and a due date in the past; a blocked one names its blocker (`blockedBy`, `blockedReason`). A fresh
database loads them with the other obligations (the people loader keeps the blocker). `migrate()` is the versioned seed
migration (meta `steward_compliance_gaps_version`, once per version, insert-if-missing, like the reality seed): it adds the
gap obligations to databases created before them, with dates relative to the migration, and raises an open stored issue for
every gap: kind `compliance_overdue` or `compliance_blocked`, `obligationId`, `regulationIds` (binding records only), the
owner, severity high when more than 7 days past due, else medium.

Drift (`tick`, every 60 s with workers on; `tick(moment)` inline for tests, the moment drives the pacing): when a site has
no overdue or blocked obligation, its next obligation by due date falls due (dueAt one hour ago) with a recorded reason
("the contractor's visit slipped", "the inspection report is late", ...) and the issue is raised; at most once per site per
two hours (meta `compliance-drift:last:<site>`). Each pass also resolves the gap issues whose obligation has been closed.
Records stay labelled synthetic internally.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from .agents import compliance_id
from .env import env
from .people import PeopleService
from .sites import DEMO_SITE
from .store import now
from .synthetic import load_family
from .verify import iso, parse_time

GAPS_VERSION = "1"
GAPS_META = "steward_compliance_gaps_version"
DRIFT_META = "compliance-drift:last:"
DRIFT_LOG_META = "compliance-drift:log"
TICK_SECONDS = 60
DRIFT_SECONDS = 2 * 3600
HIGH_AFTER_DAYS = 7
GAP_KINDS = {"overdue": "compliance_overdue", "blocked": "compliance_blocked"}
GAP_STATUSES = ("overdue", "blocked")
CLOSED = ("ok", "due_soon")
DRIFT_REASONS = {"pressure": "the examiner's visit slipped", "fire": "the contractor's visit slipped", "drainage": "the contractor's visit slipped",
                 "heritage": "the conservation survey report is late", "electrical": "the electrician's test report is late",
                 "visitor_route": "the route check sheet was not signed off"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def drift_reason(service, obligation: dict) -> str:
    """Why an obligation fell due, from its frequency and kind of work (deterministic)."""
    from .maintenance_planner import obligation_kind
    frequency = str(obligation.get("frequency") or "").strip().lower()
    if frequency in ("daily", "weekly", "monthly"):
        return f"the {frequency} check sheet was not signed off"
    if frequency == "per job":
        return "the permit renewal was not filed in time"
    if frequency == "per event":
        return "the event permit paperwork is late"
    if frequency == "per visit":
        return "the contractor's service report is late"
    return DRIFT_REASONS.get(obligation_kind(service, obligation), "the inspection report is late")


class ComplianceGaps:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick_at: str | None = None
        self.migration = self.migrate()

    # ---- seed migration -----------------------------------------------------------------------------------------

    @staticmethod
    def gap_records() -> list[dict]:
        return [r for r in load_family("obligations") if r.get("gap") in GAP_KINDS]

    @staticmethod
    def from_seed(record: dict, moment: datetime) -> dict:
        """The obligation the people loader would have written for this seed record at `moment`."""
        obligation = dict(id=record["id"], siteId=record["siteId"], assetTag=record.get("assetTag"), title=record["title"], ruleRef=record["ruleRef"],
                          frequency=record.get("frequency", ""), lastDoneAt=iso(moment - timedelta(days=int(record.get("lastDoneDaysAgo", 0)))),
                          dueAt=iso(moment + timedelta(days=int(record.get("dueInDays", 30)))), status="ok", documentId=record.get("documentId"),
                          ownerId=record.get("ownerId"), blockedBy=record.get("blockedBy"), blockedReason=record.get("blockedReason"),
                          regulationIds=list(record.get("regulationIds") or []), note=record.get("note"), synthetic=True,
                          generator=record.get("generator", "hand-seed"), updatedAt=now())
        obligation["status"] = PeopleService.status_of(obligation)
        return obligation

    def migrate(self) -> dict:
        """Once per GAPS_VERSION: insert the missing gap obligations and raise their compliance issues."""
        if self.store.meta(GAPS_META) == GAPS_VERSION:
            return {}
        with self.lock:
            if self.store.meta(GAPS_META) == GAPS_VERSION:
                return {}
            moment = utcnow()
            sites = {p["id"] for p in self.store.all("property")}
            added, raised = [], []
            for record in self.gap_records():
                site = record["siteId"]
                if site not in sites:
                    continue
                obligation = self.store.get("obligation", record["id"], site)
                if obligation is None:
                    obligation = self.from_seed(record, moment)
                    self.service.people._put("obligation", obligation)
                    added.append(obligation["id"])
                    self.service.reality.emit_change(site, "obligation", obligation["id"],
                                                     f"Obligation {obligation['title']} is {obligation['status']}"
                                                     + (f" ({obligation['blockedReason']})" if obligation["status"] == "blocked" else f", due {obligation['dueAt'][:10]}") + ".",
                                                     obligation.get("assetTag"), extra=dict(obligationId=obligation["id"], status=obligation["status"], gap=record["gap"]))
                elif record["gap"] == "blocked" and not obligation.get("blockedBy") and obligation.get("lastDoneAt") and not obligation.get("scenarioId"):
                    # Loaded by a people loader that dropped the blocker: put it back once.
                    obligation.update(blockedBy=record.get("blockedBy"), blockedReason=record.get("blockedReason"), updatedAt=now())
                    obligation["status"] = PeopleService.status_of(obligation)
                    self.service.people._put("obligation", obligation)
                if PeopleService.status_of(obligation) in GAP_STATUSES:
                    raised.append(self.raise_gap(obligation, "seed")["id"])
            self.store.meta(GAPS_META, GAPS_VERSION)
            return dict(added=added, issues=raised)

    # ---- issues ---------------------------------------------------------------------------------------------------

    def raise_gap(self, obligation: dict, origin: str, reason: str | None = None, moment: datetime | None = None) -> dict:
        """Raise (or update, same id) the open compliance issue for an overdue or blocked obligation."""
        from .maintenance_planner import citation, days_overdue, overdue_phrase, person
        site = obligation["siteId"]
        status = PeopleService.status_of(obligation)
        gap = "blocked" if status == "blocked" else "overdue"
        days = days_overdue(obligation.get("dueAt"))
        regulation_ids = self.service.regulations.for_obligation(obligation)
        cite = citation(self.service, regulation_ids)
        owner = self.store.get("crew_member", obligation.get("ownerId") or "", site)
        due = parse_time(obligation.get("dueAt"))
        due_label = f"{due.day} {due:%b}" if due else "unknown"
        title = obligation["title"].rstrip(".")
        if gap == "blocked":
            summary = f"{title} is blocked: {str(obligation.get('blockedReason') or obligation.get('blockedBy') or 'waiting for its blocker').rstrip('.')}."
            summary += f" It was due {due_label} ({overdue_phrase(days)})." if days else f" Due {due_label}."
        elif reason:
            summary = f"{title} fell due: {reason}."
        else:
            summary = f"{title} is {overdue_phrase(days)} (due {due_label})."
        if cite:
            summary += f" {cite}."
        if owner:
            summary += f" Owner: {person(owner)}."
        tag = obligation.get("assetTag")
        if tag and not any(c["tag"] == tag for c in self.store.all("component", site)):
            tag = None
        # `kind` too: a reopened issue (same id) follows the obligation from blocked to overdue and back.
        extra = dict(kind=GAP_KINDS[gap], regulationIds=regulation_ids, ownerId=obligation.get("ownerId"), dueAt=obligation.get("dueAt"), overdueDays=days,
                     obligationTitle=obligation["title"],
                     complianceGap=dict(origin=origin, gap=gap, reason=reason, at=iso(moment or utcnow())))
        if gap == "blocked":
            extra.update(blockedBy=obligation.get("blockedBy"), blockedReason=obligation.get("blockedReason"))
        # One issue per obligation, the id the compliance alert workflow (compliance_alerts.py) uses too, so a walkthrough reuses it.
        existing = next((i for i in self.store.all("issue", site) if i.get("status") == "open" and i.get("obligationId") == obligation["id"]
                         and i.get("kind") in GAP_KINDS.values()), None)
        issue_id = existing["id"] if existing else f"iss-{site[:2]}-compliance-{obligation['id']}"
        return self.service.issues.raise_issue(site, GAP_KINDS[gap], "high" if days > HIGH_AFTER_DAYS else "medium", summary, asset_tag=tag,
                                               issue_id=issue_id, source="agent", obligation_id=obligation["id"],
                                               document_id=obligation.get("documentId"), synthetic=True, actor=compliance_id(site), extra=extra)

    def sync_issues(self) -> list[str]:
        """Resolve the gap issues whose obligation is no longer overdue or blocked."""
        resolved = []
        for prop in self.store.all("property"):
            site = prop["id"]
            for issue in self.store.all("issue", site):
                if issue.get("status") != "open" or issue.get("kind") not in GAP_KINDS.values() or not issue.get("complianceGap"):
                    continue
                obligation = self.store.get("obligation", issue.get("obligationId") or "", site)
                if obligation is None or PeopleService.status_of(obligation) in GAP_STATUSES:
                    continue
                self.service.issues.resolve_issue(issue["id"], f"{obligation['title'][:200]} closed; next due {str(obligation.get('dueAt'))[:10]}.",
                                                  compliance_id(site))
                resolved.append(issue["id"])
        return resolved

    # ---- drift ------------------------------------------------------------------------------------------------------

    def enabled(self) -> bool:
        return self.service.start_workers and _flag("STEWARD_COMPLIANCE_DRIFT", "true")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="steward-compliance-drift", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            if not self.enabled():
                continue
            try:
                self.tick()
            except Exception as error:  # never let the loop die
                self.store.event(DEMO_SITE, "director", "compliance.drift_failed", "Compliance drift pass failed", f"{type(error).__name__}: {str(error)[:200]}")

    def tick(self, moment: datetime | None = None) -> list[dict]:
        """One pass: resolve closed gaps, then let one obligation fall due at each site that has no gap (paced)."""
        moment = moment or utcnow()
        with self.lock:
            self.last_tick_at = iso(moment)
            self.sync_issues()
            drifted = []
            for prop in self.store.all("property"):
                site = prop["id"]
                obligations = self.service.people.obligations(site)
                if not obligations or any(o["status"] in GAP_STATUSES for o in obligations):
                    continue
                last = parse_time(self.store.meta(DRIFT_META + site))
                if last and (moment - last).total_seconds() < DRIFT_SECONDS:
                    continue
                upcoming = sorted((o for o in obligations if o["status"] in CLOSED), key=lambda o: o.get("dueAt") or "")
                if not upcoming:
                    continue
                drifted.append(self.fall_due(site, upcoming[0]["id"], moment))
                self.store.meta(DRIFT_META + site, iso(moment))
            return drifted

    def fall_due(self, site: str, obligation_id: str, moment: datetime | None = None) -> dict:
        moment = moment or utcnow()
        record = self.store.get("obligation", obligation_id, site)
        reason = drift_reason(self.service, record)
        previous = record.get("dueAt")
        record.update(dueAt=iso(utcnow() - timedelta(hours=1)), note=f"Fell due: {reason}."[:300], driftReason=reason, driftedAt=iso(moment),
                      previousDueAt=previous, updatedAt=now())
        record["status"] = PeopleService.status_of(record)
        self.service.people._put("obligation", record)
        self.service.reality.emit_change(site, "obligation", record["id"], f"Obligation {record['title']} fell due: {reason}.", record.get("assetTag"),
                                         extra=dict(obligationId=record["id"], status=record["status"], drift=True, reason=reason))
        issue = self.raise_gap(record, "drift", reason, moment)
        self.service.ops.note(compliance_id(site), f"Raised {issue['kind'].replace('_', ' ')} on {record.get('assetTag') or 'the site'}",
                              why=f"{record['title'][:120]}: {reason}")
        entry = dict(siteId=site, obligationId=record["id"], title=record["title"], reason=reason, previousDueAt=previous, dueAt=record["dueAt"],
                     issueId=issue["id"], at=iso(moment))
        with self.store.lock:
            log = json.loads(self.store.meta(DRIFT_LOG_META) or "[]")
            self.store.meta(DRIFT_LOG_META, json.dumps((log + [entry])[-30:]))
        return entry

    # ---- status -----------------------------------------------------------------------------------------------------

    def status(self) -> dict:
        sites = []
        for prop in self.store.all("property"):
            site = prop["id"]
            obligations = self.service.people.obligations(site)
            compliant = sum(1 for o in obligations if o["status"] in CLOSED)
            last = parse_time(self.store.meta(DRIFT_META + site))
            gaps = [dict(obligationId=o["id"], title=o["title"], status=o["status"], dueAt=o.get("dueAt"), assetTag=o.get("assetTag"),
                         ownerId=o.get("ownerId"), blockedBy=o.get("blockedBy"), blockedReason=o.get("blockedReason"), regulationIds=o.get("regulationIds"))
                    for o in obligations if o["status"] in GAP_STATUSES]
            sites.append(dict(siteId=site, obligations=len(obligations), compliant=compliant,
                              compliancePct=round(100.0 * compliant / len(obligations), 1) if obligations else None, gaps=gaps,
                              lastDriftAt=iso(last) if last else None, nextDriftAfter=iso(last + timedelta(seconds=DRIFT_SECONDS)) if last else None))
        return dict(version=self.store.meta(GAPS_META), enabled=self.enabled(), tickSeconds=TICK_SECONDS, driftSeconds=DRIFT_SECONDS,
                    lastTickAt=self.last_tick_at, sites=sites, recent=list(reversed(json.loads(self.store.meta(DRIFT_LOG_META) or "[]")))[:10],
                    synthetic=True)
