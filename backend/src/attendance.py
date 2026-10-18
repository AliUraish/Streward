"""Employee logs and the People Officer (contract 8 §5; owner, Oct 18 2026: "have employee logs too, so for example an employee
is late for 2 days, a call goes to him. A different agent looks into this matter").

**Roster.** Every `crew_member` with a named shift is on the badge log; the duty engineer (the user), contractors, the
surveyor and volunteers are not. Shift text is parsed: a day range ("Tue-Sat 08:00-16:00"), "days" (Monday to Friday),
"office hours" (Monday to Friday 09:00-17:00), "opening days" / "opening hours" / "open days" (the site's opening week:
Myer Monday to Friday, Bristol Saturday and Sunday, Tomioka Tuesday to Sunday) and "rest day today" (the first working day
the log sees is a rest day); anything else is Monday to Friday 09:00-17:00. Times are local (Australia/Melbourne,
Europe/London, Asia/Tokyo).

**Badge log** (`attendance_entry`, property = site, id `att-<crewId>-<date>`): `{id, siteId, crewId, name, role, date (local),
weekday, shiftStart, shiftEnd, checkIn, checkOut (local HH:MM), checkInAt, checkOutAt (UTC), lateMinutes, status: on_time |
late | absent | rest_day, onSite, caseId, note, timeZone}`, one per local working day. The 14 days before today are written
once, deterministically per employee and date (a hash of the two); today's entry appears once its check-in time has passed
(an absence an hour after the start) and gets its check-out once that has passed. About 4.5 % of days start a late run (12
to 55 minutes) and a late day is followed by another about half the time, so a late-twice case opens every other day or so
across the three sites; 1 % of days are absences; for two weeks after an employee agrees a fix, lateness drops to 2 %.
An agreed change of start time or a swap to the late shift moves the expected start for those days.

**Seeded case.** The first time the log is written, the Myer shift technician's (Tomas Reyes, 07:00) last two working days
before today are late (start + 38 and + 52 minutes), so the rule fires on the first check after startup. With
`STEWARD_ATTENDANCE_SEED_ON_START=always` every start seeds the next employee who has had no case in 7 days (one per start,
no site with a case in progress); the operator's `POST /api/attendance/check {seed: true, crewId?}` does the same on demand.

**Rule.** Late by more than `STEWARD_ATTENDANCE_LATE_MINUTES` (10) on two consecutive working days, the second within the
last 4 local days and on or after the day the log started watching the site (so the backfill itself never opens a case; the
seeded pair does), opens `attendance_case` (property = site) `{id, siteId, crewId, name, role, shift, days: [{date, weekday,
checkIn, lateMinutes, shiftStart}], status: open | calling | resolved | unreachable | held, conversationIds, callId, callIds,
outcome, recapOutboxId, managerConversationId, openedAt, resolvedAt, nextShift}`; one case per employee per 7 days and at
most one case in progress (open or calling) per site. Change type `attendance` `{caseId, crewId, status}`.

**Handling.** The People Officer (1) holds a long chat with the site's manager (`service.chats.run`, 6 to 8 turns, templates
as the fallback), (2) asks `service.voice_calls` for a call to the employee (purpose `employee_attendance`, role `employee`:
the owner's phone; a check-in, never discipline; three options: a start 30 minutes later for two weeks, the late shift this
week, or the usual start with a reminder the evening before), and (3) when the call's outcome is read (`register`ed
handler): records it on the case (resolved with the agreed option, unreachable after voicemail or no answer on the last
attempt, held when the call was a dry run or over the daily call cap), notes it on the two late days, tells the manager over
A2A, and queues one recap email through the outbox (to role `employee`, the manager's mailbox copied) unless the call's
`email_file` follow-up already sent one. A held or failed call still tells the manager and sends the email.

Loop: `STEWARD_ATTENDANCE` (true) with the workers; first check `STEWARD_ATTENDANCE_FIRST_DELAY_SECONDS` (90) after start,
then every `STEWARD_ATTENDANCE_EVERY_MINUTES` (15). Cases are handled in a background thread with the workers on and inline
otherwise (tests). Names are the crew's; no phone number or address is stored here: the employee is reached through the role.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .agents import PEOPLE, display_name, manager_id
from .env import env
from .errors import RealityError
from .sites import SITE_BY_ID, SITE_IDS
from .store import now, uid
from .verify import iso, parse_time

SITE_TZ = {"myer-plant": "Australia/Melbourne", "bristol-pumps": "Europe/London", "tomioka-mill": "Asia/Tokyo"}
SHORT = {"myer-plant": "Myer", "bristol-pumps": "Bristol", "tomioka-mill": "Tomioka"}
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_INDEX = {name.casefold(): index for index, name in enumerate(DAY_NAMES)}
WEEKDAYS = (0, 1, 2, 3, 4)
OPEN_WEEK = {"myer-plant": WEEKDAYS, "bristol-pumps": (5, 6), "tomioka-mill": (1, 2, 3, 4, 5, 6)}
SKIP_NAME = re.compile(r"\((?:you|contractor|competent person|volunteer)\)", re.I)
SKIP_ROLE = re.compile(r"contractor|surveyor|volunteer|duty engineer", re.I)
SKIP_SHIFT = re.compile(r"on call|call-out|call out|by appointment|steam days", re.I)
TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")
DAY_RANGE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*[-–]\s*(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
OPEN_WORDS = re.compile(r"\b(?:opening|open)\s+(?:days|hours)\b", re.I)

BACKFILL_DAYS = 14
RECENT_DAYS = 4
CASE_EVERY_DAYS = 7
BASE_LATE, STREAK_LATE, SETTLED_LATE, ABSENT = 0.045, 0.55, 0.02, 0.01
SETTLED_DAYS = 14
SEED_META = "attendance:seed"
REST_META = "attendance:rest:"
SINCE_META = "attendance:since:"  # + site: the local date the log started watching (older late pairs never open a case)
SEED_CREW = "crew-my-shift-tech"
SEED_SITE = "myer-plant"
SEED_LATE_MINUTES = (38, 52)
IN_PROGRESS = ("open", "calling")
TERMINAL = ("resolved", "unreachable", "held")
PURPOSE = "employee_attendance"
EMAIL_PURPOSE = "attendance_recap"


def _flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def _number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(env(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def late_threshold() -> int:
    return int(_number("STEWARD_ATTENDANCE_LATE_MINUTES", 10, 0, 240))


def call_retries() -> int:
    return int(_number("STEWARD_CALL_RETRIES", 1, 0, 5))


def retry_minutes() -> int:
    return int(_number("STEWARD_CALL_RETRY_MINUTES", 10, 0, 1440))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def tz_for(site_id: str) -> ZoneInfo:
    return ZoneInfo(SITE_TZ.get(site_id, "UTC"))


def hhmm(value: str) -> tuple[int, int]:
    hours, minutes = value.split(":")
    return int(hours), int(minutes)


def plus_minutes(value: str, minutes: int) -> str:
    hours, mins = hhmm(value)
    total = (hours * 60 + mins + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def minutes_between(start: str, end: str) -> int:
    (h1, m1), (h2, m2) = hhmm(start), hhmm(end)
    span = (h2 * 60 + m2) - (h1 * 60 + m1)
    return span if span > 0 else span + 24 * 60


def day_label(value: date | str) -> str:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


def first_name(name: str) -> str:
    return (name or "").split(" ")[0] or name


def days_text(days: tuple[int, ...]) -> str:
    days = tuple(sorted(days))
    if days == WEEKDAYS:
        return "Monday to Friday"
    if len(days) == 7:
        return "every day"
    full = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    if len(days) > 2 and days == tuple(range(days[0], days[-1] + 1)):
        return f"{full[days[0]]} to {full[days[-1]]}"
    return " and ".join(full[d] for d in days)


def parse_shift(text: str, site_id: str) -> dict | None:
    """`{days, start, end, restToday}` for a named shift, or None for people who keep no shift (on call, call-out, by
    appointment, steam days only)."""
    raw = (text or "").strip()
    if not raw or SKIP_SHIFT.search(raw):
        return None
    lower = raw.casefold()
    times = TIME_RANGE.search(raw)
    start, end = ("09:00", "17:00")
    if times:
        start = f"{int(times.group(1)):02d}:{times.group(2)}"
        end = f"{int(times.group(3)):02d}:{times.group(4)}"
    days = WEEKDAYS
    span = DAY_RANGE.search(raw)
    if span:
        first, last = DAY_INDEX[span.group(1).casefold()], DAY_INDEX[span.group(2).casefold()]
        days = tuple(range(first, last + 1)) if first <= last else tuple(list(range(first, 7)) + list(range(0, last + 1)))
    elif "office hours" in lower:
        days = WEEKDAYS
    elif OPEN_WORDS.search(raw):
        days = OPEN_WEEK.get(site_id, WEEKDAYS)
    return dict(days=tuple(sorted(days)), start=start, end=end, restToday="rest day today" in lower)


def employee_of(record: dict) -> dict | None:
    if record.get("contact") == "user" or SKIP_NAME.search(record.get("name") or "") or SKIP_ROLE.search(record.get("role") or ""):
        return None
    shift = parse_shift(record.get("shift") or "", record.get("siteId") or "")
    if not shift:
        return None
    return dict(crewId=record["id"], siteId=record["siteId"], name=record["name"], role=record.get("role") or "", shift=record.get("shift") or "",
                days=shift["days"], start=shift["start"], end=shift["end"], restToday=shift["restToday"])


def _rand(crew_id: str, day: date, salt: str) -> float:
    digest = hashlib.sha256(f"{crew_id}|{day.isoformat()}|{salt}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64


class AttendanceService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handling: set[str] = set()  # site ids with a case being handled in this process
        self.state = "idle"
        self.reason: str | None = None
        self.last_check_at: str | None = None
        self.next_check_at: str | None = None
        self.last_error: str | None = None
        self._register()

    def _register(self) -> None:
        voice = getattr(self.service, "voice_calls", None)
        if voice is not None and hasattr(voice, "register"):
            voice.register(PURPOSE, self.on_call)

    # ---- lifecycle ----------------------------------------------------------------------------------------------------

    def enabled(self) -> bool:
        return bool(self.service.start_workers) and _flag("STEWARD_ATTENDANCE", "true")

    def start(self) -> None:
        # service.voice_calls may have been replaced after construction (tests install fakes); register again on start.
        self._register()
        if not self.service.start_workers:
            self.state, self.reason = "off", "workers are off"
            return
        if not _flag("STEWARD_ATTENDANCE", "true"):
            self.state, self.reason = "off", "STEWARD_ATTENDANCE=false"
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.state, self.reason = "running", None
        self.next_check_at = iso(utcnow() + timedelta(seconds=_number("STEWARD_ATTENDANCE_FIRST_DELAY_SECONDS", 90, 0, 86400)))
        self._thread = threading.Thread(target=self._loop, name="steward-attendance", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.state = "stopped"

    def _loop(self) -> None:
        delay = _number("STEWARD_ATTENDANCE_FIRST_DELAY_SECONDS", 90, 0, 86400)
        if env("STEWARD_ATTENDANCE_SEED_ON_START", "once").strip().lower() == "always":
            self._seed_on_start_pending = True
        while True:
            self.next_check_at = iso(utcnow() + timedelta(seconds=delay))
            if self._stop.wait(delay):
                return
            try:
                if getattr(self, "_seed_on_start_pending", False):
                    self._seed_on_start_pending = False
                    with self.lock:
                        self.generate()
                        self.seed_next()
                self.tick()
            except Exception as error:  # the loop never dies; the failure is an event and the status says why
                self.last_error = f"{type(error).__name__}: {str(error)[:200]}"
                self.store.event(SEED_SITE, PEOPLE, "attendance.error", "Attendance check failed", self.last_error)
            delay = _number("STEWARD_ATTENDANCE_EVERY_MINUTES", 15, 0.05, 1440) * 60

    def status(self) -> dict:
        cases = self.store.all("attendance_case")
        return dict(state=self.state, reason=self.reason, lastCheckAt=self.last_check_at, nextCheckAt=self.next_check_at,
                    lastError=self.last_error, lateMinutes=late_threshold(),
                    inProgress=len([c for c in cases if c["status"] in IN_PROGRESS]), cases=len(cases))

    # ---- roster ---------------------------------------------------------------------------------------------------

    def employees(self, site_id: str) -> list[dict]:
        rows = [employee_of(record) for record in self.store.all("crew_member", site_id)]
        return [row for row in rows if row]

    def roster(self, site_id: str) -> list[dict]:
        self.service.require_property(site_id)
        return [dict(crewId=e["crewId"], siteId=site_id, name=e["name"], role=e["role"], shift=e["shift"], workingDays=[DAY_NAMES[d] for d in e["days"]],
                     workingDaysText=days_text(e["days"]), shiftStart=e["start"], shiftEnd=e["end"], timeZone=SITE_TZ.get(site_id, "UTC"))
                for e in self.employees(site_id)]

    def rest_day(self, employee: dict, today: date) -> str | None:
        """'rest day today' marks the first working day the log sees for that employee (stored, so it does not move)."""
        if not employee["restToday"]:
            return None
        key = REST_META + employee["crewId"]
        stored = self.store.meta(key)
        if stored:
            return stored
        day = today
        while day.weekday() not in employee["days"]:
            day += timedelta(days=1)
        self.store.meta(key, day.isoformat())
        return day.isoformat()

    def employee_cases(self, site_id: str, crew_id: str) -> list[dict]:
        return [c for c in self.store.all("attendance_case", site_id) if c["crewId"] == crew_id]

    def shift_on(self, employee: dict, day: date, cases: list[dict]) -> tuple[str, str]:
        """The expected start and end on `day`: the rostered shift, or an agreed change that covers that day."""
        for case in sorted(cases, key=lambda c: c.get("resolvedAt") or "", reverse=True):
            adjustment = (case.get("outcome") or {}).get("adjustment")
            if adjustment and adjustment["from"] <= day.isoformat() <= adjustment["until"]:
                return adjustment["start"], adjustment["end"]
        return employee["start"], employee["end"]

    @staticmethod
    def settled(cases: list[dict], day: date) -> bool:
        for case in cases:
            outcome = case.get("outcome") or {}
            resolved = parse_time(case.get("resolvedAt"))
            if case["status"] == "resolved" and outcome.get("result") == "agreed" and resolved:
                start = resolved.date()
                if start < day <= start + timedelta(days=SETTLED_DAYS):
                    return True
        return False

    # ---- the badge log ------------------------------------------------------------------------------------------------

    def _local(self, site_id: str, day: date, clock: str) -> datetime:
        hours, minutes = hhmm(clock)
        return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=tz_for(site_id))

    def plan(self, employee: dict, day: date, previous_late: bool, settled: bool, start: str, end: str) -> dict:
        """The day's badge entry, decided by a hash of the employee and the date (the same inputs always give the same day)."""
        site, crew = employee["siteId"], employee["crewId"]
        shift_start, shift_end = self._local(site, day, start), self._local(site, day, start) + timedelta(minutes=minutes_between(start, end))
        chance = SETTLED_LATE if settled else (STREAK_LATE if previous_late else BASE_LATE)
        entry = dict(id=f"att-{crew}-{day.isoformat()}", siteId=site, crewId=crew, name=employee["name"], role=employee["role"], date=day.isoformat(),
                     weekday=DAY_NAMES[day.weekday()], shiftStart=start, shiftEnd=end, timeZone=SITE_TZ.get(site, "UTC"), caseId=None, note=None,
                     synthetic=True, generator="attendance")
        if _rand(crew, day, "absent") < ABSENT:
            entry.update(status="absent", checkIn=None, checkOut=None, checkInAt=None, checkOutAt=None, lateMinutes=None, _dueAt=shift_start + timedelta(hours=1))
            return entry
        if _rand(crew, day, "late") < chance:
            offset = 12 + int(_rand(crew, day, "minutes") * 44)
        else:
            offset = -15 + int(_rand(crew, day, "on-time") * 21)
        check_in = shift_start + timedelta(minutes=offset)
        check_out = shift_end + timedelta(minutes=-5 + int(_rand(crew, day, "out") * 31))
        late = max(0, offset)
        entry.update(status="late" if late > late_threshold() else "on_time", checkIn=check_in.strftime("%H:%M"), checkInAt=iso(check_in),
                     checkOut=check_out.strftime("%H:%M"), checkOutAt=iso(check_out), lateMinutes=late, _dueAt=check_in, _outAt=check_out)
        return entry

    def _store_entry(self, entry: dict, moment: datetime) -> dict:
        due, out = entry.pop("_dueAt", None), entry.pop("_outAt", None)
        if out is not None and moment < out:
            entry.update(checkOut=None, checkOutAt=None, onSite=True)
        else:
            entry["onSite"] = False
        self.store.put("attendance_entry", entry, entry["siteId"])
        return entry

    def entries(self, site_id: str, crew_id: str | None = None) -> list[dict]:
        rows = self.store.all("attendance_entry", site_id)
        if crew_id:
            rows = [r for r in rows if r["crewId"] == crew_id]
        return sorted(rows, key=lambda r: r["date"])

    def generate(self, moment: datetime | None = None, site_ids: list[str] | None = None) -> int:
        """Write every missing or unfinished entry of the last 14 days and today (today's once its check-in has passed)."""
        moment = moment or utcnow()
        written = 0
        with self.lock:
            for site in site_ids or SITE_IDS:
                if not self.store.get("property", site):
                    continue
                local_now = moment.astimezone(tz_for(site))
                today = local_now.date()
                if not self.store.meta(SINCE_META + site):
                    self.store.meta(SINCE_META + site, today.isoformat())
                for employee in self.employees(site):
                    written += self._generate_employee(employee, today, moment)
            self._seed_once(moment)
        return written

    def _generate_employee(self, employee: dict, today: date, moment: datetime) -> int:
        site, crew = employee["siteId"], employee["crewId"]
        existing = {e["date"]: e for e in self.entries(site, crew)}
        cases = self.employee_cases(site, crew)
        rest = self.rest_day(employee, today)
        previous_late = False
        written = 0
        for back in range(BACKFILL_DAYS, -1, -1):
            day = today - timedelta(days=back)
            key = day.isoformat()
            if day.weekday() not in employee["days"]:
                continue
            current = existing.get(key)
            if key == rest:
                if not current:
                    self.store.put("attendance_entry", dict(id=f"att-{crew}-{key}", siteId=site, crewId=crew, name=employee["name"], role=employee["role"],
                                                            date=key, weekday=DAY_NAMES[day.weekday()], shiftStart=employee["start"], shiftEnd=employee["end"],
                                                            timeZone=SITE_TZ.get(site, "UTC"), status="rest_day", checkIn=None, checkOut=None, checkInAt=None,
                                                            checkOutAt=None, lateMinutes=None, onSite=False, caseId=None, note="Rest day", synthetic=True,
                                                            generator="attendance"), site)
                    written += 1
                continue
            if current and not current.get("onSite"):
                previous_late = current["status"] == "late"
                continue
            start, end = self.shift_on(employee, day, cases)
            entry = self.plan(employee, day, previous_late, self.settled(cases, day), start, end)
            if moment < entry["_dueAt"]:
                break  # today's check-in has not happened yet
            if current:  # today's entry, still on site: keep what is known, add the check-out once it has passed
                entry.update(caseId=current.get("caseId"), note=current.get("note"))
                for field in ("checkIn", "checkInAt", "lateMinutes", "status"):
                    entry[field] = current.get(field)
            self._store_entry(entry, moment)
            if not current or not entry.get("onSite"):
                written += 1
            previous_late = entry["status"] == "late"
        return written

    def _seed_once(self, moment: datetime) -> None:
        if self.store.meta(SEED_META):
            return
        employee = next((e for e in self.employees(SEED_SITE) if e["crewId"] == SEED_CREW), None) or next(iter(self.employees(SEED_SITE)), None)
        if employee is None:
            return
        seeded = self._seed(employee, moment)
        self.store.meta(SEED_META, json.dumps(dict(crewId=employee["crewId"], dates=seeded, at=now(), mode="first start")))

    def _seed(self, employee: dict, moment: datetime) -> list[str]:
        """Make the employee's last two finished working days before today late (start + 38 and + 52 minutes)."""
        site, crew = employee["siteId"], employee["crewId"]
        today = moment.astimezone(tz_for(site)).date()
        past = [e for e in self.entries(site, crew) if e["date"] < today.isoformat() and e["status"] != "rest_day"]
        chosen = past[-2:]
        for entry, minutes in zip(chosen, SEED_LATE_MINUTES):
            day = date.fromisoformat(entry["date"])
            check_in = self._local(site, day, entry["shiftStart"]) + timedelta(minutes=minutes)
            check_out = self._local(site, day, entry["shiftStart"]) + timedelta(minutes=minutes_between(entry["shiftStart"], entry["shiftEnd"]) + minutes - 10)
            entry.update(status="late", lateMinutes=minutes, checkIn=check_in.strftime("%H:%M"), checkInAt=iso(check_in),
                         checkOut=check_out.strftime("%H:%M"), checkOutAt=iso(check_out), onSite=False, seeded=True)
            self.store.put("attendance_entry", entry, site)
        return [e["date"] for e in chosen]

    def seed_next(self, crew_id: str | None = None, moment: datetime | None = None) -> dict | None:
        """Seed a late pair for `crew_id`, or for the next employee with no case in 7 days at a site with nothing in progress."""
        moment = moment or utcnow()
        with self.lock:
            candidates = []
            for site in SITE_IDS:
                if any(c["status"] in IN_PROGRESS for c in self.store.all("attendance_case", site)) or site in self._handling:
                    continue
                for employee in self.employees(site):
                    if crew_id and employee["crewId"] != crew_id:
                        continue
                    recent = [c for c in self.employee_cases(site, employee["crewId"]) if (parse_time(c["openedAt"]) or moment) > moment - timedelta(days=CASE_EVERY_DAYS)]
                    if not recent:
                        candidates.append(employee)
            if crew_id and not candidates:
                raise RealityError(f"No employee {crew_id[:60]} can be seeded now.", "INVALID_REQUEST",
                                   "Use a crewId from GET /api/attendance with no case in the last 7 days, at a site with no case in progress.")
            if not candidates:
                return None
            employee = candidates[0]
            dates = self._seed(employee, moment)
            if len(dates) < 2:
                return None
            self.store.meta(SEED_META, json.dumps(dict(crewId=employee["crewId"], dates=dates, at=now(), mode="seed")))
            return dict(crewId=employee["crewId"], name=employee["name"], siteId=employee["siteId"], dates=dates)

    def log(self, site_id: str, days: int = 14, moment: datetime | None = None) -> dict:
        self.service.require_property(site_id)
        days = max(1, min(int(days), 31))
        today = (moment or utcnow()).astimezone(tz_for(site_id)).date()
        window = [(today - timedelta(days=back)).isoformat() for back in range(days - 1, -1, -1)]
        cases = self.cases(site_id, limit=200)
        employees = []
        for row in self.roster(site_id):
            mine = [self.view(e) for e in self.entries(site_id, row["crewId"]) if e["date"] in window]
            late = [e for e in mine if e["status"] == "late"]
            today_entry = next((e for e in mine if e["date"] == today.isoformat()), None)
            flags = []
            if today_entry and today_entry["status"] == "late":
                flags.append(f"Late today by {today_entry['lateMinutes']} min")
            if today_entry and today_entry["status"] == "absent":
                flags.append("Absent today")
            open_case = next((c for c in cases if c["crewId"] == row["crewId"] and c["status"] in IN_PROGRESS), None)
            if open_case:
                flags.append("Late two working days running: the People Officer is following up")
            employees.append(dict(row, entries=mine, lateDays=len(late), absentDays=len([e for e in mine if e["status"] == "absent"]),
                                  onSite=bool(today_entry and today_entry.get("onSite")), flags=flags,
                                  latestCase=next((c for c in cases if c["crewId"] == row["crewId"]), None)))
        return dict(siteId=site_id, siteName=SITE_BY_ID.get(site_id, {}).get("name", site_id), timeZone=SITE_TZ.get(site_id, "UTC"),
                    today=today.isoformat(), days=window, lateMinutes=late_threshold(), employees=employees, cases=cases,
                    summary=dict(employees=len(employees), onSiteNow=len([e for e in employees if e["onSite"]]),
                                 lateToday=len([e for e in employees if any(f.startswith("Late today") for f in e["flags"])]),
                                 absentToday=len([e for e in employees if "Absent today" in e["flags"]]),
                                 openCases=len([c for c in cases if c["status"] in IN_PROGRESS])))

    @staticmethod
    def view(record: dict) -> dict:
        return {k: v for k, v in record.items() if k not in ("synthetic", "generator", "seeded") and not k.startswith("_")}

    # ---- cases --------------------------------------------------------------------------------------------------------

    def cases(self, site_id: str | None = None, limit: int = 50) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        rows = self.store.all("attendance_case", site_id) if site_id else self.store.all("attendance_case")
        rows.sort(key=lambda c: c["openedAt"], reverse=True)
        return [self.view(c) for c in rows[:max(1, min(int(limit), 200))]]

    def case(self, case_id: str) -> dict:
        record = self.store.get("attendance_case", case_id)
        if not record:
            raise RealityError("Attendance case not found.", "NOT_FOUND", "List cases with GET /api/attendance/cases.", 404)
        return self.view(record)

    def _save_case(self, case: dict, summary: str | None = None) -> dict:
        case["updatedAt"] = now()
        self.store.put("attendance_case", case, case["siteId"])
        if summary:
            self.service.reality.emit_change(case["siteId"], "attendance", case["id"], summary,
                                             extra=dict(caseId=case["id"], crewId=case["crewId"], status=case["status"]))
        return case

    def rule(self, moment: datetime | None = None) -> list[dict]:
        """Open a case for every employee late on two consecutive working days (the second within the last 4 local days),
        one per employee per 7 days and at most one in progress per site."""
        moment = moment or utcnow()
        threshold = late_threshold()
        opened = []
        with self.lock:
            for site in SITE_IDS:
                if not self.store.get("property", site):
                    continue
                site_cases = self.store.all("attendance_case", site)
                if any(c["status"] in IN_PROGRESS for c in site_cases):
                    continue
                today = moment.astimezone(tz_for(site)).date()
                for employee in self.employees(site):
                    pair = self.late_pair(employee, today, threshold)
                    if not pair:
                        continue
                    mine = [c for c in site_cases if c["crewId"] == employee["crewId"]]
                    dates = [e["date"] for e in pair]
                    if any(c.get("dayDates") == dates for c in mine):
                        continue
                    if any((parse_time(c["openedAt"]) or moment) > moment - timedelta(days=CASE_EVERY_DAYS) for c in mine):
                        continue
                    opened.append(self._open(employee, pair, today, moment))
                    break  # one case in progress per site
        return opened

    def late_pair(self, employee: dict, today: date, threshold: int) -> list[dict] | None:
        entries = self.entries(employee["siteId"], employee["crewId"])
        since = self.store.meta(SINCE_META + employee["siteId"]) or ""
        rest = {e["date"] for e in entries if e["status"] == "rest_day"}
        rows = [e for e in entries if e["status"] != "rest_day"]
        late = lambda e: e["status"] == "late" and (e.get("lateMinutes") or 0) > threshold  # noqa: E731
        for index in range(len(rows) - 1, 0, -1):
            second, first = rows[index], rows[index - 1]
            if (today - date.fromisoformat(second["date"])).days > RECENT_DAYS:
                break
            watched = second["date"] >= since or (first.get("seeded") and second.get("seeded"))
            if watched and late(first) and late(second) and self.consecutive(employee, first["date"], second["date"], rest):
                return [first, second]
        return None

    @staticmethod
    def consecutive(employee: dict, first: str, second: str, rest: set[str] | None = None) -> bool:
        """No working day of the employee lies between the two dates (a rest day does not count as one)."""
        day = date.fromisoformat(first) + timedelta(days=1)
        end = date.fromisoformat(second)
        while day < end:
            if day.weekday() in employee["days"] and day.isoformat() not in (rest or set()):
                return False
            day += timedelta(days=1)
        return True

    def next_shift(self, employee: dict, moment: datetime) -> dict:
        """Today's shift when it has not started yet, else the next working day's."""
        site = employee["siteId"]
        local_now = moment.astimezone(tz_for(site))
        day = local_now.date()
        cases = self.employee_cases(site, employee["crewId"])
        starts_later_today = day.weekday() in employee["days"] and local_now < self._local(site, day, self.shift_on(employee, day, cases)[0])
        if not starts_later_today:
            day += timedelta(days=1)
            while day.weekday() not in employee["days"]:
                day += timedelta(days=1)
        start, _ = self.shift_on(employee, day, cases)
        return dict(date=day.isoformat(), label=day_label(day), start=start)

    def _open(self, employee: dict, pair: list[dict], today: date, moment: datetime) -> dict:
        site = employee["siteId"]
        days = [dict(date=e["date"], weekday=e["weekday"], label=day_label(e["date"]), checkIn=e["checkIn"], lateMinutes=e["lateMinutes"],
                     shiftStart=e["shiftStart"]) for e in pair]
        case = dict(id=uid("attc"), siteId=site, crewId=employee["crewId"], name=employee["name"], role=employee["role"], shift=employee["shift"],
                    shiftStart=employee["start"], shiftEnd=employee["end"], workingDays=days_text(employee["days"]), days=days,
                    dayDates=[d["date"] for d in days], status="open", conversationIds=[], callId=None, callIds=[], outcome=None, recapOutboxId=None,
                    managerConversationId=None, openedAt=iso(moment), resolvedAt=None, nextShift=self.next_shift(employee, moment), handledBy=PEOPLE,
                    managerId=manager_id(site), synthetic=True, generator="attendance")
        for entry in pair:
            entry.update(caseId=case["id"])
            self.store.put("attendance_entry", entry, site)
        summary = (f"{employee['name']} came in late two working days running ({days[0]['label']} at {days[0]['checkIn']}, {days[1]['label']} at "
                   f"{days[1]['checkIn']}); the People Officer is following up")
        return self._save_case(case, summary)

    # ---- checks -------------------------------------------------------------------------------------------------------

    def tick(self, moment: datetime | None = None) -> dict:
        moment = moment or utcnow()
        sequence = getattr(self.service, "sequence", None)
        if sequence is not None and sequence.active():  # the live sequence has the line and the inbox for now
            return dict(entries=0, opened=[], handling=[], at=now(), skipped="live sequence running")
        written = self.generate(moment)
        opened = self.rule(moment)
        handled = []
        for case in self.store.all("attendance_case"):
            if case["status"] == "open" and case["siteId"] not in self._handling:
                handled.append(case["id"])
                self.dispatch(case["id"])
        self.last_check_at = now()
        return dict(entries=written, opened=[c["id"] for c in opened], handling=handled, at=self.last_check_at)

    def check(self, moment: datetime | None = None, seed: bool = False, crew_id: str | None = None) -> dict:
        """The operator's trigger (`POST /api/attendance/check`): optionally seed a late pair, then run the rule now."""
        moment = moment or utcnow()
        seeded = None
        if seed or crew_id:
            self.generate(moment)
            seeded = self.seed_next(crew_id, moment)
        result = self.tick(moment)
        result["seeded"] = seeded
        return result

    def dispatch(self, case_id: str) -> None:
        case = self.store.get("attendance_case", case_id)
        if not case:
            return
        with self.lock:
            if case["siteId"] in self._handling:
                return
            self._handling.add(case["siteId"])
        if self.service.start_workers:
            threading.Thread(target=self._handle_safely, args=(case_id,), name=f"steward-attendance-{case_id}", daemon=True).start()
        else:
            self._handle_safely(case_id)

    def _handle_safely(self, case_id: str) -> None:
        case = self.store.get("attendance_case", case_id)
        try:
            self.handle(case_id)
        except Exception as error:  # a broken case never takes the loop down; the case says what happened
            self.last_error = f"{type(error).__name__}: {str(error)[:200]}"
            if case:
                self.store.event(case["siteId"], PEOPLE, "attendance.error", "Attendance follow-up failed", self.last_error)
        finally:
            if case:
                with self.lock:
                    self._handling.discard(case["siteId"])

    # ---- the People Officer -----------------------------------------------------------------------------------------

    def context(self, case: dict) -> dict:
        site = case["siteId"]
        employee = next((e for e in self.employees(site) if e["crewId"] == case["crewId"]), None) or dict(
            crewId=case["crewId"], siteId=site, name=case["name"], role=case["role"], shift=case["shift"], days=WEEKDAYS, start=case["shiftStart"],
            end=case["shiftEnd"], restToday=False)
        manager = case.get("managerId") or manager_id(site)
        others = [e for e in self.employees(site) if e["crewId"] != case["crewId"]]
        cover = next((e for e in others if e["start"] == employee["start"]), None) or next(iter(others), None)
        later = plus_minutes(employee["start"], 30)
        late_start = employee["end"]
        late_end = plus_minutes(late_start, minutes_between(employee["start"], employee["end"]))
        window = [e for e in self.entries(site, case["crewId"]) if e["date"] not in case["dayDates"] and e["status"] != "rest_day"][-10:]
        on_time = len([e for e in window if e["status"] == "on_time"])
        first, second = case["days"][0], case["days"][1]
        options = [dict(id=f"start-{later.replace(':', '')}", label=f"Start at {later} for the next two weeks"),
                   dict(id="swap-late", label="Swap to the late shift this week"),
                   dict(id="keep-reminder", label=f"Keep {employee['start']} with a reminder the evening before")]
        return dict(site=site, siteName=SITE_BY_ID.get(site, {}).get("name", site), short=SHORT.get(site, site), employee=employee, manager=manager,
                    managerName=display_name(manager), first=first_name(case["name"]), cover=(cover or {}).get("name"), later=later,
                    lateShift=(late_start, late_end), onTime=on_time, checked=len(window), day1=first, day2=second, options=options,
                    nextShift=case.get("nextShift") or self.next_shift(employee, utcnow()))

    def handle(self, case_id: str) -> dict:
        """The chat with the manager, then the call to the employee; the outcome arrives through `on_call`."""
        case = self.store.get("attendance_case", case_id)
        if not case or case["status"] != "open":
            return case or {}
        c = self.context(case)
        if not case["conversationIds"]:
            conversation = self.chat(case, c)
            if conversation and conversation.get("id"):
                case["conversationIds"].append(conversation["id"])
                self._save_case(case)
        return self.call(case, c)

    def chat(self, case: dict, c: dict) -> dict | None:
        name, first, manager_name = case["name"], c["first"], c["managerName"]
        d1, d2, start, nxt = c["day1"], c["day2"], c["employee"]["start"], c["nextShift"]
        cover = c["cover"]
        late_start, late_end = c["lateShift"]
        log_line = (f"{d1['label']} in at {d1['checkIn']} ({d1['lateMinutes']} minutes late), {d2['label']} in at {d2['checkIn']} "
                    f"({d2['lateMinutes']} minutes late), against a {start} start")
        shared = (f"Badge log, {c['siteName']}: {name}, {case['role'].lower()}, shift {case['shift']} ({case['workingDays']}). {log_line}. "
                  f"On time on {c['onTime']} of the {c['checked']} working days before that. Next shift: {nxt['label']} at {nxt['start']}. "
                  f"Options the People Officer can offer: " + "; ".join(o["label"] for o in c["options"]) + ".")
        briefs = {
            PEOPLE: (f"You look after attendance at all three sites. {name} was late two working days running and you will phone {first} before the "
                     f"next shift on {nxt['label']}. Ask {manager_name} for anything you should know, agree which options to offer, and say you will "
                     "send a short recap with the manager copied. Keep it a supportive check-in: no warnings, no discipline on a first follow-up."),
            c["manager"]: (f"You are {manager_name}. {name} is reliable: on time on {c['onTime']} of the {c['checked']} working days before these two. "
                           + (f"{cover} can cover the {start} handover for two weeks if {first} starts later. " if cover else "")
                           + f"The late shift ({late_start} to {late_end}) has room this week. You know of nothing that explains the late starts; "
                           f"you want {first} supported and the {start} handover covered."),
        }
        fallback = [
            dict(speaker=PEOPLE, text=(f"{name} badged in late two working days running: {d1['checkIn']} on {d1['label']} and {d2['checkIn']} on "
                                       f"{d2['label']}, against the {start} start. On time on {c['onTime']} of the {c['checked']} working days before that. "
                                       f"I'd like to call {first} before {nxt['label']}. Anything I should know?")),
            dict(speaker=c["manager"], text=(f"Nothing on my side; {first} is reliable. " + (f"{cover} covered the {start} handover both days. " if cover else "")
                                             + f"{nxt['label']} starts with the {start} handover again.")),
            dict(speaker=PEOPLE, text=(f"Then I'll keep it a check-in, not a warning: ask if {first} is all right and what changed. I can offer "
                                       + "; ".join(o["label"].lower() for o in c["options"]) + ".")),
            dict(speaker=c["manager"], text=((f"All three work. If {first} takes {c['later']}, {cover} can do the {start} handover for two weeks. " if cover else
                                              f"All three work for me. ") + f"The late shift, {late_start} to {late_end}, has room this week.")),
            dict(speaker=PEOPLE, text=f"Good. I'll call {first}, agree one of those, and send a short recap with you copied."),
            dict(speaker=c["manager"], text=f"Thanks. Tell me what {first} says; I'll check in at the start of the next shift."),
        ]
        fallback_summary = dict(headline=f"The People Officer and {manager_name} agreed how to approach {first}'s two late starts",
                                points=[log_line, f"On time on {c['onTime']} of the {c['checked']} working days before"],
                                decisions=["Keep it a supportive check-in", "Offer: " + "; ".join(o["label"] for o in c["options"])],
                                actions=[dict(owner="People Officer", task=f"Call {name} before the next shift", due=nxt["label"]),
                                         dict(owner=manager_name, task=f"Check in with {first} at the start of the next shift", due=nxt["label"])])
        topic = f"{name}: late two working days running"
        chats = getattr(self.service, "chats", None)
        try:
            return chats.run(convener=PEOPLE, participants=[PEOPLE, c["manager"]], topic=topic, site_ids=[c["site"]], briefs=briefs, shared=shared,
                             goal=f"Agree how the People Officer approaches the call to {first} and which options to offer.", min_turns=6, max_turns=8,
                             refs=dict(caseId=case["id"], crewId=case["crewId"]), fallback=fallback, fallback_summary=fallback_summary,
                             realtime=bool(self.service.start_workers), origin="workflow")
        except Exception as error:  # the writer is unavailable: the template chat keeps the follow-up going
            self.last_error = f"chat: {type(error).__name__}: {str(error)[:160]}"
            return self.service.conversations.call(PEOPLE, c["manager"], topic, fallback, site_ids=[c["site"]], summary=fallback_summary,
                                                   summary_by="hand-seed", origin="workflow")

    def call(self, case: dict, c: dict) -> dict:
        name, first = case["name"], c["first"]
        d1, d2, start, nxt = c["day1"], c["day2"], c["employee"]["start"], c["nextShift"]
        facts = [
            f"{name} is a {case['role'].lower()} at {c['siteName']}; shift {case['shift']} ({case['workingDays']}).",
            f"Badge log: {d1['label']} in at {d1['checkIn']}, {d1['lateMinutes']} minutes after the {start} start; {d2['label']} in at "
            f"{d2['checkIn']}, {d2['lateMinutes']} minutes late.",
            f"On time on {c['onTime']} of the {c['checked']} working days before that.",
            f"Next shift: {nxt['label']} at {nxt['start']}.",
            f"{c['managerName']} knows you are calling and is happy with any of the options.",
            "This is a check-in, not a disciplinary call: if something is wrong, offer support and listen.",
        ]
        recap = self.recap(case, c, result="pending")
        self._register()  # whichever phone-call service is installed now gets the handler
        try:
            record = self.service.voice_calls.request(
                purpose=PURPOSE, caller=PEOPLE, callee_role="employee", callee_name=name, site_id=c["site"],
                goal=(f"Check {first} is all right, learn why they came in late on {d1['label']} and {d2['label']}, and agree one of the options "
                      f"before the next shift on {nxt['label']}."),
                facts=facts, options=c["options"], can_do=["note", "email_file"], file=dict(subject=recap["subject"], text=recap["text"], html=recap["html"],
                                                                                            cc=[c["manager"]]),
                context=dict(caseId=case["id"], crewId=case["crewId"]), refs=dict(caseId=case["id"], crewId=case["crewId"], siteId=c["site"]),
                dedupe_key=f"attendance:{case['id']}")
        except Exception as error:  # the call could not be prepared: tell the manager and the employee another way
            self.last_error = f"call: {type(error).__name__}: {str(error)[:160]}"
            self.store.event(case["siteId"], PEOPLE, "attendance.call", "Attendance call could not be placed", self.last_error)
            case.update(status="held")
            return self.finish(case, c, dict(result="held", reason="the call could not be placed"), None)
        case.update(callId=record.get("id"), callIds=list(dict.fromkeys((case.get("callIds") or []) + [record.get("id")])))
        status = record.get("status")
        if status in ("dry_run", "capped"):
            reason = record.get("reason") or ("Calls to people are switched off" if status == "dry_run" else "The daily call limit is reached")
            return self.finish(case, c, dict(result="held", reason=reason), record)
        if status in ("failed", "canceled"):
            return self.finish(case, c, dict(result="failed", reason=record.get("reason") or f"The call was {status}."), record)
        case["status"] = "calling"
        return self._save_case(case, f"The People Officer is calling {name} about the two late starts")

    # ---- after the call -----------------------------------------------------------------------------------------------

    def case_for_call(self, call: dict) -> dict | None:
        refs = dict(call.get("refs") or {}, **(call.get("context") or {}))
        if refs.get("caseId"):
            found = self.store.get("attendance_case", refs["caseId"])
            if found:
                return found
        wanted = {call.get("id"), call.get("retryOf")} - {None}
        return next((c for c in self.store.all("attendance_case") if wanted & set((c.get("callIds") or []) + [c.get("callId")])), None)

    def on_call(self, call: dict) -> dict | None:
        """The VoiceCalls handler: runs once per call after its outcome is read (also for a voicemail that will be retried)."""
        with self.lock:
            case = self.case_for_call(call)
            if not case or case["status"] in TERMINAL:
                return dict(handled=[], notes=["No open attendance case for this call."], refs=dict(caseId=(case or {}).get("id")))
            if call.get("id"):
                case.update(callId=call["id"], callIds=list(dict.fromkeys((case.get("callIds") or []) + [call["id"]])))
            outcome = call.get("outcome") or {}
            status = call.get("status")
            result = outcome.get("result") or {"voicemail": "voicemail", "no_answer": "no_answer", "failed": "failed", "canceled": "failed",
                                               "dry_run": "held", "capped": "held"}.get(status, "undecided")
            if status in ("dry_run", "capped"):
                result = "held"
            c = self.context(case)
            if result in ("voicemail", "no_answer") and int(call.get("attempt") or 1) <= call_retries():
                case["status"] = "calling"
                case["lastAttempt"] = dict(result=result, at=now(), callId=call.get("id"))
                self._save_case(case, f"No answer from {case['name']}; the People Officer will try again in {retry_minutes()} minutes")
                return dict(handled=[], notes=[f"{result.replace('_', ' ')}; a retry follows"], refs=dict(caseId=case["id"]))
            emailed = next((f for f in outcome.get("followUps") or [] if f.get("type") == "email_file" and f.get("status") == "done" and f.get("ref")), None)
            reason = (call.get("reason") or ("Calls to people are switched off" if status == "dry_run" else "The daily call limit is reached")) if result == "held" else None
            details = dict(result=result, decision=outcome.get("decision") or "", summary=outcome.get("summary") or "",
                           optionId=outcome.get("chosenOptionId"), interpretedBy=outcome.get("interpretedBy"), reason=reason)
            done = self.finish(case, c, details, call, already_emailed=emailed)
            return dict(handled=[] if emailed else ["email_file"], notes=[done.get("outcome", {}).get("headline", "")], refs=dict(caseId=case["id"]))

    def adjustment(self, option_id: str | None, c: dict) -> dict | None:
        if not option_id:
            return None
        start_day = date.fromisoformat(c["nextShift"]["date"])
        employee = c["employee"]
        if option_id.startswith("start-"):
            return dict(kind="later_start", start=c["later"], end=plus_minutes(employee["end"], 30), **{"from": start_day.isoformat()},
                        until=(start_day + timedelta(days=13)).isoformat())
        if option_id == "swap-late":
            week_end = start_day + timedelta(days=6 - start_day.weekday())
            return dict(kind="late_shift", start=c["lateShift"][0], end=c["lateShift"][1], **{"from": start_day.isoformat()}, until=week_end.isoformat())
        return None

    def finish(self, case: dict, c: dict, details: dict, call: dict | None, already_emailed: dict | None = None) -> dict:
        """Record the outcome, note it on the two late days, tell the manager, and queue the recap once."""
        name, first = case["name"], c["first"]
        result = details["result"]
        option = next((o for o in c["options"] if o["id"] == details.get("optionId")), None) if result == "agreed" else None
        if result == "agreed" and not option:
            result = "undecided"
        status = {"agreed": "resolved", "declined": "resolved", "undecided": "resolved", "held": "held"}.get(result, "unreachable")
        headline = {
            "agreed": f"{name} agreed: {option['label'].lower()}" if option else "",
            "declined": f"{name} talked it through; no change agreed",
            "undecided": f"{name} talked it through and is still choosing",
            "held": f"The call to {name} is on hold: {details.get('reason') or 'calls are held'}",
            "voicemail": f"{name} could not be reached (voicemail)",
            "no_answer": f"{name} could not be reached (no answer)",
            "failed": f"The call to {name} did not go through",
        }.get(result) or f"The call to {name} ended"
        outcome = dict(result=result, headline=headline, decision=details.get("decision") or "", summary=details.get("summary") or "",
                       optionId=option["id"] if option else None, optionLabel=option["label"] if option else None,
                       adjustment=self.adjustment(option["id"], c) if option else None, reason=details.get("reason"),
                       interpretedBy=details.get("interpretedBy"), callId=(call or {}).get("id"), at=now())
        case.update(status=status, outcome=outcome, resolvedAt=now())
        note = {"resolved": f"People Officer followed up: {headline}",
                "unreachable": "The People Officer could not reach them; the manager follows up", "held": "Follow-up by email; the call is on hold"}[status]
        for day in case["dayDates"]:
            entry = self.store.get("attendance_entry", f"att-{case['crewId']}-{day}", case["siteId"])
            if entry:
                entry.update(caseId=case["id"], note=note[:200])
                self.store.put("attendance_entry", entry, case["siteId"])
        try:
            case["managerConversationId"] = self.tell_manager(case, c, outcome)
        except Exception as error:  # the A2A note failing must not lose the outcome
            self.last_error = f"manager message: {type(error).__name__}: {str(error)[:160]}"
        if already_emailed:
            case["recapOutboxId"] = already_emailed.get("ref")
        elif not case.get("recapOutboxId"):
            recap = self.recap(case, c, result=result, option=option, outcome=outcome)
            try:
                item = self.service.outbox.email(sender=PEOPLE, to_role="employee", subject=recap["subject"], text=recap["text"], html=recap["html"],
                                                 cc=[c["manager"]], site_id=case["siteId"], purpose=EMAIL_PURPOSE,
                                                 refs=dict(caseId=case["id"], callId=(call or {}).get("id")), dedupe_key=f"attendance-recap:{case['id']}")
                case["recapOutboxId"] = item.get("id")
            except Exception as error:  # the outbox refusing must not lose the outcome
                self.last_error = f"recap: {type(error).__name__}: {str(error)[:160]}"
        return self._save_case(case, headline)

    def tell_manager(self, case: dict, c: dict, outcome: dict) -> str | None:
        first, manager, nxt = c["first"], c["manager"], c["nextShift"]
        result = outcome["result"]
        said = (outcome.get("summary") or "").strip().rstrip(".")
        if result == "agreed":
            text = (f"Spoke to {first}" + (f": {said}" if said else "") + f". Agreed: {outcome['optionLabel'].lower()}. "
                    f"I've sent {first} a recap and copied you.")
            answer = (f"Thanks. I'll make sure {c['cover']} covers the {c['employee']['start']} handover." if outcome["optionId"].startswith("start-") and c["cover"]
                      else f"Thanks. I'll check in with {first} on {nxt['label']}.")
        elif result in ("declined", "undecided"):
            text = (f"Spoke to {first}" + (f": {said}" if said else "") + ". "
                    + ("No change agreed." if result == "declined" else "Still choosing between the options.") + f" Recap sent with you copied.")
            answer = f"Thanks. I'll have a word with {first} at the start of the shift on {nxt['label']}."
        elif result == "held":
            text = f"The call to {first} is on hold ({outcome.get('reason') or 'calls are held'}). I've emailed {first} instead, with you copied."
            answer = f"Understood. I'll have a word with {first} at the start of the shift on {nxt['label']}."
        else:
            text = f"I couldn't reach {first} ({result.replace('_', ' ')}). I've emailed {first} with you copied."
            answer = f"Thanks. I'll have a word with {first} at the start of the shift on {nxt['label']}."
        conversations = self.service.conversations
        conversation = conversations.message(PEOPLE, manager, f"{case['name']}: follow-up on the late starts", text, site_ids=[case["siteId"]],
                                             data=dict(caseId=case["id"], attendanceOutcome=outcome["result"]), synthetic=True)
        conversations.answer(conversation["id"], manager, answer)
        conversations.set_summary(conversation["id"], dict(headline=outcome["headline"][:200], points=[text[:300]], decisions=[answer[:300]], actions=[]),
                                  "hand-seed")
        return conversation["id"]

    def recap(self, case: dict, c: dict, result: str, option: dict | None = None, outcome: dict | None = None) -> dict:
        first, d1, d2, start = c["first"], c["day1"], c["day2"], c["employee"]["start"]
        manager_name, nxt = c["managerName"], c["nextShift"]
        log_line = f"{d1['label']} in at {d1['checkIn']} and {d2['label']} in at {d2['checkIn']}, against your {start} start"
        summary = (outcome or {}).get("summary") or ""
        if result == "agreed" and option:
            subject = "Recap: our call about your start times"
            lines = ["Thanks for talking with me today.", f"What the badge log showed: {log_line}.", f"What we agreed: {option['label']}."]
            if summary:
                lines.append(summary)
        elif result in ("declined", "undecided"):
            subject = "Recap: our call about your start times"
            lines = ["Thanks for talking with me today.", f"What the badge log showed: {log_line}."]
            if summary:
                lines.append(summary)
            lines.append("No change agreed for now." if result == "declined" else
                         "If one of these suits you, reply with it: " + "; ".join(o["label"] for o in c["options"]) + ".")
        elif result == "pending":
            subject = "Recap: our call about your start times"
            lines = [f"What the badge log showed: {log_line}.", "The options we talked about: " + "; ".join(o["label"] for o in c["options"]) + "."]
        elif result == "held":
            subject = "About your start times last week"
            lines = [f"I wanted to call you before your next shift on {nxt['label']}.", f"The badge log shows {log_line}.",
                     "Is everything all right? These could help: " + "; ".join(o["label"] for o in c["options"]) + "."]
        else:
            subject = "I tried to call you about your start times"
            lines = [f"I tried to call you before your next shift on {nxt['label']}.", f"The badge log shows {log_line}.",
                     "Is everything all right? These could help: " + "; ".join(o["label"] for o in c["options"]) + "."]
        closing = f"If anything changes, reply to this email or talk to {manager_name}, who is copied."
        signature = ["People Officer", f"Steward · {c['siteName']}"]
        text = "\n\n".join([f"Hi {first},"] + lines + [closing, "\n".join(signature)])
        body = "".join(f"<p>{html_lib.escape(line)}</p>" for line in [f"Hi {first},"] + lines + [closing])
        html = (f"<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#111\">{body}"
                f"<p>{'<br>'.join(html_lib.escape(s) for s in signature)}</p></div>")
        return dict(subject=subject, text=text, html=html)
