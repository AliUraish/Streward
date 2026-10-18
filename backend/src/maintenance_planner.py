"""Maintenance planner (owner, Oct 18 2026: "in maintenance don't ask agents to maintenance, it schedules on its own with
communication to other sites when they have scheduled").

Every `TICK_SECONDS` (workers on) the planner walks each site's obligations; `tick(moment)` is the same pass, inline, for
tests (the moment drives the pacing and the slot search). An obligation is booked when it is overdue or due within 14 days
and has no window for its current cycle: no window names it (`obligationId`) since it was last done, and no open window of
the same kind of work covers its asset. It is left alone when it is not a site visit: daily and weekly rounds are the site
staff's own checks, permits and reports (`per job`, `per event`, `per visit`) are paperwork, a blocked obligation waits
for its blocker, and an obligation a running scenario drives is left to that scenario.

Booking (at most one new window per site per 10 minutes, the most overdue first):
- The site's Manager books it in the site's local working hours (Australia/Melbourne, Europe/London, Asia/Tokyo; Monday
  to Friday, public holidays skipped, at least 12 hours ahead): overdue work takes the first slot, work that is due soon
  the last working day at least two days before its due date. The start time comes from the kind of work
  (pressure-system examinations 09:00, fire-safety checks 10:00, visitor routes 08:00 before opening, ...).
- First it looks for another site's open window of the same kind (same contractor type or regulation family) within
  ±7 days. When there is one, the two Managers hold a cross-site A2A call (`ConversationService.call`) and line the visits
  up: the same examining body where the group shares one, the other site's checklist or method statement, and which visit
  goes first. The new window is linked to the other one (`linkedWindowIds`, `coordination`, `conversationId`) and the
  other window gets the back link.
- The window is `approved` (a Manager schedules and approves its own site's work) with `origin: "planner"`, the
  obligation, its asset, owner and regulation ids; the change is emitted on the site (type `maintenance`); the open
  compliance issue of the obligation records the booking.
- The Manager tells the team over A2A (`ConversationService.message` to the Compliance Officer, the Engineer and the
  Field Technician; each answers).
- A planner window is marked `done` once its obligation is closed (the obligation's `lastDoneAt` passes the booking).

Text comes from templates (no model calls) and every record is labelled synthetic internally. While a live path is on
(Inkbox A2A, live Supermemory) the planner pauses, like the scenario autoplayer, unless `STEWARD_SCENARIO_AUTOPLAY_LIVE`
or `STEWARD_MAINTENANCE_PLANNER_LIVE` is true; `STEWARD_MAINTENANCE_PLANNER=false` turns the background loop off.
The propose/approve API in `maintenance.py` is unchanged.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .agents import SHORT_SITE, authorize, compliance_id, display_name, engineer_id, manager_id, technician_id
from .env import env
from .store import now
from .verify import iso, parse_time

TICK_SECONDS = 60
START_DELAY_SECONDS = 15
PACE_SECONDS = 600
LOOKAHEAD_DAYS = 14
COORDINATION_DAYS = 7
LEAD_HOURS = 12
DUE_MARGIN_DAYS = 2
SEARCH_DAYS = 60
OPEN = ("proposed", "approved")
ROUNDS = ("daily", "weekly")
PAPERWORK = ("per job", "per event", "per visit")
IN_HOUSE = ("daily", "weekly", "monthly")
PACE_META = "maintenance-planner:last:"
LOG_META = "maintenance-planner:log"
SITE_TZ = {"myer-plant": "Australia/Melbourne", "bristol-pumps": "Europe/London", "tomioka-mill": "Asia/Tokyo"}
CITY = {"Australia/Melbourne": "Melbourne", "Europe/London": "London", "Asia/Tokyo": "Tokyo"}
# Public holidays (and the mill's year-end closure) through January 2027; no visit is booked on these days.
HOLIDAYS = {
    "myer-plant": {"2026-11-03", "2026-12-25", "2026-12-28", "2027-01-01", "2027-01-26"},
    "bristol-pumps": {"2026-12-25", "2026-12-28", "2027-01-01"},
    "tomioka-mill": {"2026-11-03", "2026-11-23", "2026-12-29", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-11"},
}

# Kinds of work: the contractor type and the regulation family a window belongs to. An obligation or window is classified
# by its regulation ids (3 points per id with a listed prefix), its asset's subsystem (2) and words in its title (1 each).
WORK_KINDS: dict[str, dict] = {
    "pressure": dict(label="pressure-system examination", family="pressure systems", start=(9, 0), hours=4, shared=True,
                     contractor={"*": "Northgate Engineering Inspection (competent person)"},
                     regs=("eng-pssr-", "vic-ohsr-2017-reg-74", "vic-ohsr-2017-reg-105", "vic-ohsr-2017-reg-106"),
                     words=("pressure", "vessel", "receiver", "safety valve", "lift test", "written scheme", "steam supply", "pipework"),
                     subsystems=("Steam plant", "Pressure management"), prep="isolate and depressurise {asset}",
                     share="the written-scheme checklist for vessels, valves and pipework", share_short="checklist"),
    "fire": dict(label="fire-safety check", family="fire safety", start=(10, 0), hours=2, shared=False,
                 contractor={"myer-plant": "the ESM contractor (fire and emergency lighting)", "bristol-pumps": "the fire equipment contractor",
                             "tomioka-mill": "the licensed fire equipment inspector", "*": "the fire equipment contractor"},
                 regs=("vic-br-2018-", "vic-vba-pn-esm", "jp-fsa-", "jp-fso-", "jp-fsr-"),
                 words=("extinguisher", "hydrant", "fire", "emergency", "exit", "evacuation", "luminaire", "guide-light"),
                 subsystems=("Portable equipment", "Indoor hydrant", "Lighting", "Access and egress"), prep="keep the access to {asset} clear",
                 share="one checklist for extinguishers, exit signs and emergency lights", share_short="checklist"),
    "heritage": dict(label="heritage fabric work", family="heritage fabric", start=(9, 30), hours=3, shared=False,
                     contractor={"tomioka-mill": "the conservation architect and a heritage carpenter", "bristol-pumps": "the restoration team",
                                 "*": "the conservation specialist"},
                     regs=("jp-cpa-",), words=("heritage", "national treasure", "truss", "historic", "conservation", "humidity"),
                     subsystems=("National Treasure fabric", "Roof", "Environmental monitoring", "Structural monitoring", "Climate control", "Silk reeling"),
                     prep="protect the fabric around {asset}", share="the method statement for work that fixes nothing into historic fabric",
                     share_short="method statement"),
    "drainage": dict(label="drainage plant service", family="drainage and workplace", start=(8, 30), hours=3, shared=False,
                     contractor={"*": "the pump and valve contractor"}, regs=("eng-whswr-1992-reg-5",),
                     words=("sump", "drainage", "suction", "float", "gland"), subsystems=("Drainage",),
                     prep="put the standby pump on duty and isolate {asset}", share="the float-switch and changeover test sheet", share_short="test sheet"),
    "visitor_route": dict(label="visitor route work", family="visitor routes", start=(8, 0), hours=2, shared=False,
                          contractor={"*": "the visitor operations team"}, regs=("eng-whswr-1992-reg-12",),
                          words=("walkway", "visitor route", "handrail", "barrier"), subsystems=("Visitor route",),
                          prep="close the route at {asset} with barriers and signs", share="the route closure procedure and barrier plan",
                          share_short="procedure"),
    "electrical": dict(label="electrical test", family="electrical installations", start=(13, 0), hours=3, shared=False,
                       contractor={"*": "the electrical contractor"}, regs=(), words=("distribution board", "electrical", "rcd", "thermal scan", "thermographic"),
                       subsystems=("Power distribution", "Controls"), prep="arrange the shutdown for {asset}", share="the test sheet and isolation plan",
                       share_short="test sheet"),
    "general": dict(label="maintenance visit", family="general maintenance", start=(10, 0), hours=2, shared=False,
                    contractor={"*": "the maintenance contractor"}, regs=(), words=(), subsystems=(), prep="prepare access to {asset}",
                    share="the job sheet", share_short="job sheet"),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def tz_for(site: str) -> ZoneInfo:
    return ZoneInfo(SITE_TZ.get(site, "UTC"))


def city(site: str) -> str:
    return CITY.get(SITE_TZ.get(site, ""), "UTC")


def short(site: str) -> str:
    return SHORT_SITE.get(site, site)


def clean(text) -> str:
    """Visible text without internal labels (synthetic, demo, rule-pack codes) or template braces."""
    value = str(text or "")
    value = re.sub(r"\s*\([^()]*\b(?:synthetic|demo|DEMO-RP)\b[^()]*\)", "", value, flags=re.I)
    value = re.sub(r"\b(?:synthetic|demo)\b\s*", "", value, flags=re.I)
    value = value.replace("{", "(").replace("}", ")")
    return re.sub(r"\s{2,}", " ", value).strip(" ,;")


def lower_first(text: str) -> str:
    """Lower-case the first letter unless the first word is a tag, an acronym or 'No.'."""
    text = text.strip()
    word = text.split(" ", 1)[0] if text else ""
    if not word or word == "No." or any(ch.isdigit() for ch in word) or (len(word) > 1 and word[1].isupper()):
        return text
    return text[:1].lower() + text[1:]


def capital(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def person(crew: dict | None) -> str:
    """'Meera Vasquez-Lin (site safety lead)'; 'the duty engineer (you)' when the name is the role."""
    if not crew:
        return "the obligation owner"
    name, role = str(crew.get("name") or ""), str(crew.get("role") or "")
    if role and name.casefold().startswith(role.casefold()):
        return f"the {lower_first(name)}"
    return f"{name} ({lower_first(role)})" if role else name


def strip_parenthetical(text: str) -> str:
    return re.sub(r"\s*\([^()]*\)", "", text or "").strip()


def clean_tree(value):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [clean_tree(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_tree(item) for key, item in value.items()}
    return value


def day_label(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def local_label(moment: datetime, site: str) -> str:
    local = moment.astimezone(tz_for(site))
    return f"{day_label(local.date())} {local:%H:%M}"


def work_kind(regulation_ids, text: str, subsystems) -> str:
    regs = [str(r) for r in (regulation_ids or [])]
    words = (text or "").casefold()
    subs = {s for s in (subsystems or []) if s}
    best, best_score = "general", 0
    for key, spec in WORK_KINDS.items():
        score = 3 * sum(1 for r in regs if any(r.startswith(prefix) for prefix in spec["regs"]))
        score += 2 * len(subs & set(spec["subsystems"]))
        score += sum(1 for word in spec["words"] if word in words)
        if score > best_score:
            best, best_score = key, score
    return best


def subsystem_of(store, site: str, tag: str | None) -> str | None:
    if not tag:
        return None
    component = next((c for c in store.all("component", site) if c["tag"] == tag), None)
    return (component or {}).get("subsystem")


def obligation_kind(service, obligation: dict) -> str:
    return work_kind(obligation.get("regulationIds"), obligation.get("title", ""),
                     [subsystem_of(service.store, obligation.get("siteId"), obligation.get("assetTag"))])


def describe(obligation: dict) -> str:
    """'the <task> for <subject>' from an obligation title such as 'Exit sign L-901: six-monthly discharge test'."""
    title = clean(obligation.get("title")).rstrip(".")
    if ":" in title:
        subject, task = (part.strip() for part in title.split(":", 1))
        text = f"the {lower_first(task)} for {lower_first(subject)}"
    else:
        text = f"the {lower_first(title)}"
    tag = obligation.get("assetTag")
    if tag and tag not in text:
        text += f" ({tag})"
    return text


def short_instrument(name: str) -> str:
    out = str(name or "")
    for group in re.findall(r"\([^()]*\)", out):
        if re.search(r"No\.|\bSI\b|\bc\. ?\d|[^\x00-\x7F]", group):
            out = out.replace(group, "")
    return re.sub(r"\s{2,}", " ", out).strip()


def short_provision(text: str) -> str:
    out = str(text or "").split(";", 1)[0]
    out = re.sub(r"\s*\([^()]*[^\x00-\x7F][^()]*\)", "", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def citation(service, regulation_ids) -> str:
    """'Building Regulations 2018 (Vic) reg. 195' for the first binding regulation, '' when none resolves."""
    regulations = getattr(service, "regulations", None)
    why = regulations.why(list(regulation_ids or [])) if regulations else []
    if not why:
        return ""
    first = why[0]
    return f"{short_instrument(first.get('instrument'))} {short_provision(first.get('provision'))}".strip()


def days_overdue(due_at: str | None, moment: datetime | None = None) -> int:
    due = parse_time(due_at)
    if due is None:
        return 0
    return max(0, int(((moment or utcnow()) - due).total_seconds() // 86400))


def overdue_phrase(days: int) -> str:
    if days <= 0:
        return "overdue since today"
    return "1 day overdue" if days == 1 else f"{days} days overdue"


def relation_phrase(ours: date, theirs: date) -> str:
    delta = (ours - theirs).days
    if delta == 0:
        return "the same day as yours"
    if delta == 1:
        return "the day after yours"
    if delta == -1:
        return "the day before yours"
    if delta == 7:
        return "the following week"
    if delta == -7:
        return "the week before yours"
    return f"{delta} days after yours" if delta > 0 else f"{-delta} days before yours"


def is_working_day(site: str, day: date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in HOLIDAYS.get(site, set())


def slot_on(site: str, day: date, kind: str) -> tuple[datetime, datetime]:
    spec = WORK_KINDS[kind]
    hour, minute = spec["start"]
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz_for(site))
    return start, start + timedelta(hours=spec["hours"])


def choose_slot(site: str, kind: str, moment: datetime, due: datetime | None, overdue: bool) -> tuple[datetime, datetime]:
    """Overdue: the first working-hours slot at least LEAD_HOURS ahead. Due soon: the last working day at least
    DUE_MARGIN_DAYS before the due date (never earlier than the first slot)."""
    earliest = moment + timedelta(hours=LEAD_HOURS)
    day = earliest.astimezone(tz_for(site)).date()
    first = None
    for offset in range(SEARCH_DAYS):
        candidate = day + timedelta(days=offset)
        if not is_working_day(site, candidate):
            continue
        start, end = slot_on(site, candidate, kind)
        if start >= earliest:
            first = (start, end)
            break
    if first is None:
        first = (earliest, earliest + timedelta(hours=WORK_KINDS[kind]["hours"]))
    if overdue or due is None:
        return first
    target = (due.astimezone(tz_for(site)) - timedelta(days=DUE_MARGIN_DAYS)).date()
    best, cursor = first, first[0].astimezone(tz_for(site)).date() + timedelta(days=1)
    while cursor <= target:
        if is_working_day(site, cursor):
            best = slot_on(site, cursor, kind)
        cursor += timedelta(days=1)
    return best


class MaintenancePlanner:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = "off"
        self.reason: str | None = "The planner starts with the backend's workers."
        self.last_tick_at: str | None = None

    # ---- lifecycle -------------------------------------------------------------------------------------------

    def enabled(self) -> bool:
        return self.service.start_workers and _flag("STEWARD_MAINTENANCE_PLANNER", "true")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.state, self.reason = "waiting", "First planning pass shortly after start."
        self._thread = threading.Thread(target=self._loop, name="steward-maintenance-planner", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        if self._stop.wait(START_DELAY_SECONDS):
            return
        while not self._stop.is_set():
            if self.enabled():
                try:
                    self.tick()
                except Exception as error:  # never let the loop die; the status says why
                    self.state, self.reason = "error", f"{type(error).__name__}: {str(error)[:200]}"
            else:
                self.state, self.reason = "off", "STEWARD_MAINTENANCE_PLANNER=false."
            if self._stop.wait(TICK_SECONDS):
                return

    def live_switches(self) -> list[str]:
        """External paths the planner's calls and messages would take now: Inkbox A2A and live Supermemory memories."""
        on = []
        try:
            if self.service.bus.inkbox_available():
                on.append("Inkbox A2A transport")
        except Exception:
            pass
        client = getattr(getattr(self.service, "memory", None), "client", None)
        try:
            if client is not None and client.live:
                on.append("STEWARD_SUPERMEMORY_LIVE")
        except Exception:
            pass
        return on

    # ---- classification and coverage -------------------------------------------------------------------------

    def window_kind(self, window: dict) -> str:
        if window.get("workKind") in WORK_KINDS:
            return window["workKind"]
        if window.get("obligationId"):
            obligation = self.store.get("obligation", window["obligationId"])
            if obligation:
                return obligation_kind(self.service, obligation)
        subsystems = [subsystem_of(self.store, site, tag) for site in window.get("siteIds") or [] for tag in window.get("assetTags") or []]
        return work_kind([], window.get("scope", ""), subsystems)

    def covering(self, obligation: dict, kind: str, windows: list[dict]) -> dict | None:
        """A window for the obligation's current cycle: one that names it since it was last done, or an open window of the
        same kind of work on its asset (a scenario's or a person's booking)."""
        site, since = obligation["siteId"], parse_time(obligation.get("lastDoneAt"))
        for window in windows:
            if site not in (window.get("siteIds") or []):
                continue
            created = parse_time(window.get("createdAt"))
            if since and created and created < since:
                continue
            names = window.get("obligationId") == obligation["id"] or obligation["id"] in (window.get("obligationIds") or [])
            if names and window.get("status") in OPEN + ("done",):
                return window
            tag = obligation.get("assetTag")
            if (not names and tag and window.get("status") in OPEN and (tag in (window.get("assetTags") or []) or tag in (window.get("scope") or ""))
                    and self.window_kind(window) == kind):
                return window
        return None

    def plan(self, site: str) -> list[dict]:
        """What the planner would do with each obligation that is overdue, due within 14 days or blocked."""
        people = self.service.people
        obligations = people.obligations(site)
        windows = self.store.all("maintenance_window", "")
        running = {r.get("scenarioId") for r in self.service.scenarios.runs() if r.get("state") == "running"}
        decisions = []
        for obligation in obligations:
            status = obligation["status"]
            if status not in ("overdue", "due_soon", "blocked"):
                continue
            kind = obligation_kind(self.service, obligation)
            frequency = str(obligation.get("frequency") or "").strip().lower()
            decision = dict(obligationId=obligation["id"], title=obligation["title"], status=status, dueAt=obligation.get("dueAt"),
                            assetTag=obligation.get("assetTag"), kind=kind, windowId=None)
            if status == "blocked":
                decision.update(action="waiting", note=f"Blocked: {obligation.get('blockedReason') or obligation.get('blockedBy') or 'waiting for its blocker'}")
            elif frequency in ROUNDS:
                decision.update(action="round", note="A daily or weekly round done by the site staff; no window needed.")
            elif frequency in PAPERWORK:
                decision.update(action="paperwork", note="Permit or report paperwork, not a site visit.")
            elif obligation.get("scenarioId") and obligation.get("scenarioId") in running:
                decision.update(action="scenario", note="A running scenario is handling it.")
            else:
                window = self.covering(obligation, kind, windows)
                if window:
                    decision.update(action="covered", windowId=window["id"], note=f"Window {window['id']} on {window['date']} ({window['status']}).")
                else:
                    decision.update(action="book", note="Next to book." if status == "overdue" else "Due within 14 days.")
            decisions.append(decision)
        decisions.sort(key=lambda d: (d["action"] != "book", d["status"] != "overdue", d.get("dueAt") or ""))
        return decisions

    # ---- the pass ---------------------------------------------------------------------------------------------

    def tick(self, moment: datetime | None = None) -> list[dict]:
        """One planning pass: close windows whose obligation closed, then book at most one window per site (paced)."""
        moment = moment or utcnow()
        with self.lock:
            self.last_tick_at = iso(moment)
            live = self.live_switches()
            if live and not (_flag("STEWARD_SCENARIO_AUTOPLAY_LIVE") or _flag("STEWARD_MAINTENANCE_PLANNER_LIVE")):
                self.state, self.reason = "paused", ("Live paths are on (" + ", ".join(live) + "), so the planner's calls and messages would leave "
                                                     "the machine on their own. Set STEWARD_MAINTENANCE_PLANNER_LIVE=true to allow it.")
                return []
            self.sync_windows()
            booked = []
            for prop in self.store.all("property"):
                site = prop["id"]
                if site not in SITE_TZ:
                    continue
                last = parse_time(self.store.meta(PACE_META + site))
                if last and (moment - last).total_seconds() < PACE_SECONDS:
                    continue
                todo = [d for d in self.plan(site) if d["action"] == "book"]
                if not todo:
                    continue
                try:
                    window = self.book(site, todo[0]["obligationId"], moment)
                except Exception as error:  # one site's failure never stops the others; retried after the pace
                    window = None
                    self.store.event(site, manager_id(site), "maintenance.planner_failed", "Maintenance planner could not book a window",
                                     f"{todo[0]['obligationId']}: {type(error).__name__}: {str(error)[:200]}")
                self.store.meta(PACE_META + site, iso(moment))
                if window:
                    booked.append(window)
            if booked:
                self.state, self.reason = "booked", "Booked " + ", ".join(f"{w['id']} ({w['localStart']})" for w in booked) + "."
            else:
                self.state, self.reason = "idle", "Every overdue or due obligation has a window, waits for its blocker, or is paced."
            return booked

    def sync_windows(self) -> list[str]:
        """A planner window is done once its obligation has been closed after the booking."""
        closed = []
        for window in self.store.all("maintenance_window", ""):
            if window.get("origin") != "planner" or window.get("status") not in OPEN or not window.get("obligationId"):
                continue
            obligation = self.store.get("obligation", window["obligationId"])
            done_at, created = parse_time((obligation or {}).get("lastDoneAt")), parse_time(window.get("createdAt"))
            if not obligation or not done_at or not created or done_at <= created:
                continue
            window.update(status="done", doneAt=now(), closedReason=f"{obligation['title'][:160]} closed on {obligation['lastDoneAt'][:10]}.")
            self.service.maintenance._put(window)
            site = window["siteIds"][0]
            self.service.reality.emit_change(site, "maintenance", window["id"], f"Maintenance {window['id']} done: {window['scope'][:200]} (obligation closed).",
                                             (window.get("assetTags") or [None])[0],
                                             extra=dict(maintenanceId=window["id"], status="done", crossSite=False, origin="planner", obligationId=obligation["id"]))
            closed.append(window["id"])
        return closed

    # ---- booking ----------------------------------------------------------------------------------------------

    @staticmethod
    def window_id(obligation: dict) -> str:
        cycle = re.sub(r"[^0-9T]", "", str(obligation.get("lastDoneAt") or ""))[:13] or "0"
        return f"mw-plan-{obligation['id'].removeprefix('ob-')}-{cycle}"[:120]

    def contractor(self, site: str, kind: str, obligation: dict, owner: dict | None) -> tuple[str, str]:
        """(label, short name): routine checks are done in-house by the obligation's owner, visits by the kind's contractor."""
        frequency = str(obligation.get("frequency") or "").strip().lower()
        if frequency in IN_HOUSE and owner:
            label = person(owner)
            if label.startswith("the ") or not label.endswith(")"):
                label = f"{label}, in-house"
            else:
                label = f"{label[:-1]}, in-house)"
            return label, (strip_parenthetical(person(owner)) or label)
        table = WORK_KINDS[kind]["contractor"]
        label = table.get(site) or table["*"]
        return label, strip_parenthetical(label) or label

    def window_contractor(self, window: dict, site: str, kind: str) -> str:
        named = clean(window.get("examiner"))
        if named and named[:1].isupper():
            return named
        table = WORK_KINDS[kind]["contractor"]
        return table.get(site) or table["*"]

    def related_window(self, site: str, kind: str, start: datetime) -> dict | None:
        """The nearest open window of the same kind at another site within ±COORDINATION_DAYS of the slot."""
        ours = start.astimezone(tz_for(site)).date()
        best = None
        for window in self.store.all("maintenance_window", ""):
            sites = window.get("siteIds") or []
            if window.get("status") not in OPEN or site in sites or not sites:
                continue
            try:
                theirs = date.fromisoformat(str(window.get("date"))[:10])
            except ValueError:
                continue
            gap = abs((theirs - ours).days)
            if gap > COORDINATION_DAYS or self.window_kind(window) != kind:
                continue
            key = (gap, str(window.get("date")), window["id"])
            if best is None or key < best[0]:
                best = (key, window)
        return best[1] if best else None

    def open_issue(self, obligation: dict) -> dict | None:
        issues = [i for i in self.store.all("issue", obligation["siteId"]) if i.get("status") == "open" and i.get("obligationId") == obligation["id"]]
        issues.sort(key=lambda i: (not str(i.get("kind", "")).startswith("compliance_"), i.get("at") or ""))
        return issues[0] if issues else None

    def book(self, site: str, obligation_id: str, moment: datetime | None = None) -> dict | None:
        moment = moment or utcnow()
        people = self.service.people
        obligation = people.obligation_view(people.obligation(obligation_id))
        window_id = self.window_id(obligation)
        if self.store.get("maintenance_window", window_id, ""):
            return None
        manager = authorize(manager_id(site), "schedule_maintenance", site)
        kind = obligation_kind(self.service, obligation)
        spec = WORK_KINDS[kind]
        status = people.status_of(obligation)
        due = parse_time(obligation.get("dueAt"))
        start, end = choose_slot(site, kind, moment, due, status == "overdue")
        owner = self.store.get("crew_member", obligation.get("ownerId") or "", site)
        contractor, helper = self.contractor(site, kind, obligation, owner)
        tag = obligation.get("assetTag")
        days = days_overdue(obligation.get("dueAt"))
        if status == "overdue":
            due_text = overdue_phrase(days)
        else:
            due_text = f"due {day_label(due.astimezone(tz_for(site)).date())}" if due else "due soon"
        local_start, local_end = local_label(start, site), f"{end.astimezone(tz_for(site)):%H:%M}"
        issue = self.open_issue(obligation)
        window = dict(id=window_id, siteIds=[site], date=start.astimezone(tz_for(site)).date().isoformat(), startAt=iso(start), endAt=iso(end),
                      timeZone=SITE_TZ[site], localStart=local_start, localEnd=local_end, scope=clean(obligation["title"])[:500], examiner=contractor[:200],
                      status="approved", conversationId=None, assetTags=[tag] if tag else [], obligationId=obligation["id"], obligationIds=[obligation["id"]],
                      ownerId=obligation.get("ownerId"), ownerName=(owner or {}).get("name"), regulationIds=list(obligation.get("regulationIds") or []),
                      workKind=kind, workFamily=spec["family"], cycleStart=obligation.get("lastDoneAt"), cycleDueAt=obligation.get("dueAt"),
                      dueStatus=status, bookedReason=due_text, proposedBy=manager, approvedBy=manager, approvedAt=now(), origin="planner",
                      linkedWindowIds=[], coordination=None, teamConversationIds=[], issueId=(issue or {}).get("id"), scenarioId=None,
                      synthetic=True, generator="planner", createdAt=now(), updatedAt=now())
        other = self.related_window(site, kind, start)
        conversation = None
        if other:
            conversation, coordination = self.coordinate(site, obligation, kind, window, other, due_text, contractor, issue)
            window.update(conversationId=conversation["id"], linkedWindowIds=[other["id"]], coordination=coordination)
        self.service.maintenance._put(window)
        if other:
            self._link_back(other, window, conversation, site)
        summary = (f"{display_name(manager)} booked the {spec['label']} for {tag or 'the site'} on {local_start} {city(site)} time ({due_text}) "
                   f"with {contractor}" + (f", linked with {short(window['coordination']['siteId'])}'s window after a call" if other else "") + ".")
        self.service.reality.emit_change(site, "maintenance", window["id"], summary[:480], tag,
                                         extra=dict(maintenanceId=window["id"], status=window["status"], crossSite=False, origin="planner",
                                                    obligationId=obligation["id"], conversationId=window["conversationId"],
                                                    linkedWindowIds=window["linkedWindowIds"], startAt=window["startAt"], workKind=kind))
        window["teamConversationIds"] = self.tell_team(site, window, obligation, kind, owner, contractor, helper, due_text, issue)
        self.service.maintenance._put(window)
        if issue:
            self._note_issue(issue, window, contractor)
        self.service.ops.note(manager, f"Booked the {spec['label']} for {tag or 'the site'}: {local_start}", why=f"{obligation['title'][:120]} ({due_text})")
        self._log(window)
        return window

    def _link_back(self, other: dict, window: dict, conversation: dict, site: str) -> None:
        other["linkedWindowIds"] = list(dict.fromkeys(list(other.get("linkedWindowIds") or []) + [window["id"]]))
        other["lastCoordinationConversationId"] = conversation["id"]
        self.service.maintenance._put(other)
        other_site = next(s for s in other["siteIds"] if s != site)
        self.service.reality.emit_change(other_site, "maintenance", other["id"],
                                         f"{display_name(manager_id(other_site))} linked {other['id']} with {short(site)}'s {WORK_KINDS[window['workKind']]['label']} "
                                         f"on {window['localStart']} {city(site)} time after a call with {display_name(manager_id(site))}."[:480],
                                         (other.get("assetTags") or [None])[0],
                                         extra=dict(maintenanceId=other["id"], status=other.get("status"), crossSite=False, origin="planner",
                                                    conversationId=conversation["id"], linkedWindowIds=other["linkedWindowIds"]))

    def _note_issue(self, issue: dict, window: dict, contractor: str) -> None:
        stored = self.store.get("issue", issue["id"], issue["siteId"])
        if not stored or stored.get("status") != "open":
            return
        stored.update(maintenanceWindowId=window["id"], plannedAt=window["startAt"])
        text = f"Booked for {window['localStart']} {city(window['siteIds'][0])} time with {contractor} ({window['id']})."
        stored["history"] = (stored.get("history") or [])[-19:] + [dict(at=now(), severity=stored["severity"], summary=text[:300], by=window["proposedBy"])]
        self.service.issues._save(stored, f"Issue {stored['kind']} on {stored.get('assetTag') or 'the site'}: {text}"[:480], window["proposedBy"])

    def _log(self, window: dict) -> None:
        with self.store.lock:
            log = json.loads(self.store.meta(LOG_META) or "[]")
            log.append(dict(windowId=window["id"], siteId=window["siteIds"][0], obligationId=window["obligationId"], startAt=window["startAt"],
                            localStart=window["localStart"], conversationId=window.get("conversationId"), at=now()))
            self.store.meta(LOG_META, json.dumps(log[-30:]))

    # ---- conversations ------------------------------------------------------------------------------------------

    def coordinate(self, site: str, obligation: dict, kind: str, window: dict, other: dict, due_text: str, contractor: str,
                   issue: dict | None) -> tuple[dict, dict]:
        """The cross-site call between the two Managers before booking; returns (conversation, coordination)."""
        spec = WORK_KINDS[kind]
        other_site = next(s for s in other["siteIds"] if s != site)
        caller, callee = manager_id(site), manager_id(other_site)
        start = parse_time(window["startAt"])
        ours = start.astimezone(tz_for(site)).date()
        theirs = date.fromisoformat(str(other["date"])[:10])
        their_start = parse_time(other.get("startAt"))
        their_when = f"{local_label(their_start, other_site)} {city(other_site)} time" if their_start else day_label(theirs)
        our_when = f"{window['localStart']} {city(site)} time"
        their_obligation = self.store.get("obligation", other["obligationId"]) if other.get("obligationId") else None
        their_work = describe(their_obligation) if their_obligation else f"the {lower_first(clean(other.get('scope'))[:160])}"
        their_contractor = self.window_contractor(other, other_site, kind)
        same_body = bool(spec.get("shared")) and their_contractor == contractor
        relation = relation_phrase(ours, theirs)
        first = (start < their_start) if their_start else (ours < theirs)
        if ours == theirs and not their_start:
            order = ""
        elif first:
            order = (" It is overdue, so ours goes first and you get our notes before your visit." if window["dueStatus"] == "overdue"
                     else " Ours comes first and you get our notes before your visit.")
        else:
            order = " Your notes from that visit carry over to ours."
        if same_body:
            plan = f"Then we book the same examining body, {contractor}, for {our_when}, {relation}.{order}"
        else:
            plan = (f"Then ours goes in for {our_when} with {contractor}, {relation}, and we work from your {spec['share_short']} "
                    f"so both records read the same.{order}")
        turns = [
            dict(speaker=caller, text=f"{short(site)} here. I'm booking {describe(obligation)}, {due_text}. {short(other_site)} has a {spec['label']} on "
                                      f"{their_when}: {their_work}. Can we line the two up?"),
            dict(speaker=callee, text=f"Yes. {capital(their_contractor)} does ours on {their_when}. We work from {spec['share']}; happy to share it."),
            dict(speaker=caller, text=plan),
            dict(speaker=callee, text=f"Agreed. I'll link the two windows. Our Compliance Officer sends {spec['share']} to yours, and both reports go to "
                                      f"the Operations Director together."),
            dict(speaker=caller, text="Booked and linked. I'm telling my team now."),
        ]
        tag, their_tag = obligation.get("assetTag") or "the site", (other.get("assetTags") or [None])[0] or "its asset"
        topic = f"{capital(spec['label'])}s: {short(site)} {tag} and {short(other_site)} {their_tag}"
        summary = dict(headline=f"{short(site)} booked {tag} for {our_when}, linked with {short(other_site)}'s {their_tag} visit on {day_label(theirs)}",
                       points=[f"{short(site)}: {describe(obligation)}, {due_text}.", f"{short(other_site)}: {their_work} on {their_when}."],
                       decisions=[f"Book {contractor} for {our_when} and link it to {other['id']}."],
                       actions=[dict(owner=display_name(compliance_id(other_site)), task=f"Send {spec['share']} to {display_name(compliance_id(site))}",
                                     due=day_label(ours)),
                                dict(owner=display_name(caller), task=f"Tell the {short(site)} team about the booking", due="today")])
        conversation = self.service.conversations.call(caller, callee, clean(topic), [dict(t, text=clean(t["text"])) for t in turns],
                                                       site_ids=[site, other_site], issue_id=(issue or {}).get("id"),
                                                       issue_kind=(issue or {}).get("kind"), summary=clean_tree(summary), summary_by="hand-seed")
        conversation["maintenanceWindowId"] = window["id"]
        self.service.conversations._save(conversation)
        coordination = dict(mode="linked", siteId=other_site, windowId=other["id"], conversationId=conversation["id"], relation=relation,
                            sharedContractor=same_body, note=plan[:300])
        return conversation, coordination

    def tell_team(self, site: str, window: dict, obligation: dict, kind: str, owner: dict | None, contractor: str, helper: str, due_text: str,
                  issue: dict | None) -> list[str]:
        """The Manager tells the Compliance Officer, the Engineer and the Field Technician; each answers."""
        spec = WORK_KINDS[kind]
        manager = manager_id(site)
        tag = obligation.get("assetTag") or "the site"
        when = f"{window['localStart']} to {window['localEnd']} {city(site)} time"
        cite = citation(self.service, obligation.get("regulationIds"))
        who = person(owner)
        prep = spec["prep"].format(asset=tag)
        linked = ""
        if window.get("coordination"):
            other = window["coordination"]
            linked = f" Linked with {short(other['siteId'])}'s window {other['windowId']} after my call with {display_name(manager_id(other['siteId']))}."
        messages = [
            (compliance_id(site),
             f"Booked for {when}: {describe(obligation)} with {contractor}. It is {due_text}" + (f" under {cite}" if cite else "") + f"; owner {who}."
             + linked + " Please file the record and close the obligation after the visit.",
             "Noted. I'll file the record" + (f" against {cite}" if cite else "") + " and close the obligation when the report is in."),
            (engineer_id(site),
             f"{tag} is booked for the {spec['label']} on {when}. Please {prep} and walk it with {helper}; capture before-and-after frames with the eye.",
             f"Noted. I'll {prep} and walk it with {helper}."),
            (technician_id(site),
             f"Please tell {who} about the {spec['label']} on {when}, and confirm {helper}'s arrival the day before.",
             f"Noted. I'll tell {strip_parenthetical(who)} and confirm {helper} the day before."),
        ]
        topic = clean(f"Maintenance booked: {tag} {spec['label']}, {window['localStart']}")
        ids = []
        conversations = self.service.conversations
        for teammate, text, answer in messages:
            conversation = conversations.message(manager, teammate, topic, clean(text), site_ids=[site], issue_id=(issue or {}).get("id"),
                                                 data=dict(maintenanceWindowId=window["id"], obligationId=obligation["id"]), synthetic=True)
            conversation["maintenanceWindowId"] = window["id"]
            conversations._save(conversation)
            conversations.answer(conversation["id"], teammate, clean(answer))
            ids.append(conversation["id"])
        return ids

    # ---- status -------------------------------------------------------------------------------------------------

    def status(self) -> dict:
        moment = utcnow()
        sites = []
        for prop in self.store.all("property"):
            site = prop["id"]
            if site not in SITE_TZ:
                continue
            last = parse_time(self.store.meta(PACE_META + site))
            windows = [w for w in self.store.all("maintenance_window", "") if w.get("origin") == "planner" and site in (w.get("siteIds") or [])]
            sites.append(dict(siteId=site, timeZone=SITE_TZ[site], localTime=local_label(moment, site), managerId=manager_id(site),
                              managerName=display_name(manager_id(site)), lastBookedAt=iso(last) if last else None,
                              nextBookingAfter=iso(last + timedelta(seconds=PACE_SECONDS)) if last else None,
                              openWindows=sum(1 for w in windows if w.get("status") in OPEN), doneWindows=sum(1 for w in windows if w.get("status") == "done"),
                              queue=self.plan(site)))
        return dict(enabled=self.enabled(), state=self.state, reason=self.reason, lastTickAt=self.last_tick_at, tickSeconds=TICK_SECONDS,
                    paceSeconds=PACE_SECONDS, lookaheadDays=LOOKAHEAD_DAYS, coordinationDays=COORDINATION_DAYS, leadHours=LEAD_HOURS,
                    liveSwitches=self.live_switches(), sites=sites, recent=list(reversed(json.loads(self.store.meta(LOG_META) or "[]")))[:10],
                    synthetic=True)
