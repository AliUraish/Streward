"""Compliance alerts (contract 7 §2): one workflow per bad compliance finding of a walkthrough (`patrol.py`).

Six paced steps (`STEWARD_ALERT_STEP_SECONDS`, default 4 s apart while the backend runs its workers; inline with no
sleeping otherwise), each a Change of type `compliance_alert` with extras `{alertId, step, status}`:

1. `issue`: raise or reuse the stored issue for the obligation (`compliance_overdue` / `compliance_blocked`) with
   `obligationId`, `regulationIds` and the label's evidence frame; high when overdue by more than 7 days, else medium.
2. `teammate_call`: the walker (the site's Engineer) calls the site's Compliance Officer (A2A call conversation).
3. `cross_site_call`: that Compliance Officer calls another site's Compliance Officer about the same kind of obligation
   (Myer and Bristol for pressure and fire equipment, Bristol and Tomioka for heritage and visitor-route work, Myer and
   Tomioka for fire equipment; else the next site).
4. `manager_decision`: the Compliance Officer calls the Site Manager, who approves telling the owner and assigns the
   crew owner.
5. `owner_email`: from the Compliance Officer's Inkbox identity to `INKBOX_OWNER_EMAIL`: HTML with the regulation
   citation and its official link, the evidence frames inline (`content_id`) and attached as JPEG, the official
   regulation PDF when its licence allows redistribution (England OGL, Japan PDL1.0 with the 出典 line in the body;
   Victorian PDFs are link-only and never attached) and `evidence-<alertId>.txt`.
6. `owner_call`: the Steward Dispatch Line calls `INKBOX_OWNER_PHONE` through the hosted voice agent with a brief
   under 1000 characters, so a voicemail leaves the same message.

A real email or call needs every gate, read from the environment at send time: Inkbox configured, the alert started by
hand (an autoplayed walkthrough also needs `STEWARD_SCENARIO_AUTOPLAY_LIVE=true`), `STEWARD_ALLOW_EXTERNAL_MESSAGES=true`,
`STEWARD_ALLOW_OWNER_ALERTS=true` and the recipient in `INKBOX_ALLOWED_RECIPIENTS` (`InkboxAdapter._gate` checks the last
two again); then fewer than `STEWARD_OWNER_ALERTS_PER_DAY` (default 3) live alerts in the last 24 h and none for the
same obligation. Otherwise the email and the call are recorded `dry_run` (or `capped`) with their full content (subject,
HTML and text, attachment names and sizes, the call brief), so the dashboard shows exactly what would go out. Owner
addresses are stored masked. Text is written from the records by templates; no model is called.
"""
from __future__ import annotations

import base64
import html as html_lib
import re
import threading
from datetime import date as date_cls, datetime, timedelta, timezone

from .agents import (SHORT_SITE, agent_key, compliance_id, display_name, email_for, handle_env_names, handle_for, manager_id)
from .env import env
from .errors import RealityError
from .providers import InkboxAdapter, allowed_recipients, clean_env, external_messages_allowed
from .sites import SITE_BY_ID, SITE_IDS
from .store import now, uid
from .verify import parse_time

STEPS = ("issue", "teammate_call", "cross_site_call", "manager_decision", "owner_email", "owner_call")
STEP_SECONDS = 4.0
BAD_STATUSES = ("overdue", "blocked")
DEDUPE_HOURS = 24
MAX_FRAMES = 3
MAX_PDF_BYTES = 6 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_BRIEF_CHARS = 1000
ATTACHABLE_JURISDICTIONS = ("ENG-UK", "JP")  # OGL v3.0 and PDL1.0 allow redistribution; Victorian legislation does not
PLACE = {"myer-plant": "the plant room", "bristol-pumps": "the pump house", "tomioka-mill": "the Silk Reeling Mill"}
SITE_ZONES = {"myer-plant": ("Australia/Melbourne", 11), "bristol-pumps": ("Europe/London", 1), "tomioka-mill": ("Asia/Tokyo", 9)}
INSTRUMENT_SHORT = (
    ("Pressure Systems Safety Regulations 2000", "PSSR 2000"),
    ("Workplace (Health, Safety and Welfare) Regulations 1992", "Workplace Regulations 1992"),
    ("Health and Safety at Work etc. Act 1974", "HSWA 1974"),
    ("Occupational Health and Safety Regulations 2017 (Vic)", "OHS Regulations 2017 (Vic)"),
    ("Building Regulations 2018 (Vic)", "Building Regulations 2018 (Vic)"),
    ("Building Practice Note ESM-02", "VBA Practice Note ESM-02"),
    ("Act on Protection of Cultural Properties", "Cultural Properties Act"),
    ("Enforcement Order of the Fire Service Act", "Fire Service Act Enforcement Order"),
    ("Enforcement Regulation of the Fire Service Act", "Fire Service Act Enforcement Regulation"),
    ("Fire Service Act", "Fire Service Act"),
)
SPOKEN = ((r"\bregs\.? ", "regulations "), (r"\breg\. ", "regulation "), (r"\barts\. ", "articles "), (r"\bart\. ", "article "),
          (r"\bss\. ", "sections "), (r"\bs\. ", "section "), (r"\bSch\. ", "Schedule "), (r"\bPt ", "Part "), (r"\bpp\. ", "pages "))
# Cross-site partners by kind of obligation (contract 7 §2, step 3); anything else goes to the next site.
PAIRS = {"pressure": (("myer-plant", "bristol-pumps"),),
         "fire": (("myer-plant", "bristol-pumps"), ("myer-plant", "tomioka-mill")),
         "hotwork": (("myer-plant", "bristol-pumps"), ("myer-plant", "tomioka-mill")),
         "heritage": (("bristol-pumps", "tomioka-mill"),),
         "humidity": (("bristol-pumps", "tomioka-mill"),),
         "route": (("bristol-pumps", "tomioka-mill"),)}
# What each kind of finding means, what the walker does now, the manager's next step, and what the other site shares.
CATEGORIES = {
    "pressure": dict(
        risk="it must not be run past its examination date until a competent person has examined it",
        hold="keep {tag} isolated and tagged out of use until the examiner signs it off",
        step="book the competent-person examiner for {day} morning",
        question="how do you keep your pressure-equipment examinations from slipping, and who examines for you?",
        help="I'll email you our examination checklist and the scheme template we work to, with the examiner's contact; they quote for single-vessel visits.",
        practice="We book the next examination the day the report arrives, and the examiner works from a one-page checklist we keep with the plant record."),
    "fire": dict(
        risk="fire equipment that has missed its inspection may not work when it is needed",
        hold="put a checked spare beside {tag} and tag the old unit not to be relied on until it is inspected",
        step="book the fire equipment contractor for {day} morning",
        question="how do you run your extinguisher and hydrant inspections so none of them lapse?",
        help="I'll send our inspection checklist and the service firm's contact; they keep a reminder list, so nothing lapses again.",
        practice="Every unit has a signed tag and a monthly visual check, and the service firm does the periodic service and records it."),
    "hotwork": dict(
        risk="hot work without a valid permit and fire watch puts the plant at risk of fire",
        hold="hold the hot work at {tag} and keep a checked extinguisher within reach",
        step="issue a fresh hot-work permit with a fire watch before the job restarts on {day}",
        question="how do you control hot-work permits with contractors?",
        help="I'll send our hot-work permit form and the fire-watch log we use.",
        practice="Every hot-work job needs a signed permit, a fire watch for an hour afterwards and an extinguisher within reach; the permit is closed in the log."),
    "heritage": dict(
        risk="the protected fabric must not be altered without permission, so the work waits until the permission is in place",
        hold="stop any work on {tag} and keep every sensor on non-invasive clamp mounts",
        step="send the permission request for the {tag} work on {day} and hold the work until it is granted",
        question="how do you mount sensors and carry out repairs on protected fabric without altering it?",
        help="I'll email our method statement for clamp mounts, with the photo log template.",
        practice="Padded stainless clamps on existing frame members: no drilling, welding or adhesive, every mount photographed and logged, cables in the existing conduits."),
    "humidity": dict(
        risk="humidity above the limit risks mould on the trusses and the reeling machinery",
        hold="run the dehumidifier, keep the north windows shut and check the trusses for mould",
        step="bring the conservator in on {day} morning to check the trusses and the reeling machines",
        question="how do you keep humidity under control around historic machinery?",
        help="I'll send our hourly humidity log template and the dehumidifier service contact.",
        practice="We log humidity every hour, start the dehumidifier as soon as it passes the limit and check the metalwork for corrosion every week."),
    "route": dict(
        risk="the route must not open to visitors until it has been checked: handrails, toe boards, lighting and trip hazards",
        hold="keep {tag} closed with the barrier and the sign until the check is done",
        step="have {owner} walk and sign the check before opening on {day}",
        question="how do you run your pre-opening check and the route closure?",
        help="I'll email our pre-opening checklist and the route-closure procedure.",
        practice="We close the route at its entrance with the barrier and sign, sweep it, log the time and the reason, and reopen only after the visitor lead walks it."),
    "report": dict(
        risk="without the service report the plant record has a gap",
        hold="flag the gap in the plant record for {tag}",
        step="chase the contractor for the service report by {day}",
        question="how do you make sure contractors file their service reports on time?",
        help="I'll send you the reporting clause we put in every contractor order.",
        practice="We hold the contractor's invoice until the service report is filed, and the report goes straight into the asset record."),
    "electrical": dict(
        risk="the board's protective devices are not proven until the periodic inspection is done",
        hold="keep {tag} closed and avoid adding loads to it",
        step="book the electrical inspector for {day} morning",
        question="who does your periodic electrical inspection and RCD testing?",
        help="I'll send our inspection scope and the electrical contractor's contact.",
        practice="Our electrical contractor does the RCD trip test and a thermal scan on every visit, and the results go into the asset record."),
    "generic": dict(
        risk="the obligation has lapsed, so the asset's compliance record is not current",
        hold="keep {tag} out of use where that is safe until it is put right",
        step="book the contractor for {day} morning",
        question="have you dealt with this kind of obligation before, and who did the work?",
        help="I'll send the method statement and the contractor we use.",
        practice="We track it on the obligation register with a reminder two weeks before it falls due."),
}
# The other site's own practice, in its own words and under its own law, when it has one for this kind of finding.
PRACTICE = {
    ("myer-plant", "pressure"): "TK-201 runs on an annual inspection with a pre-charge check, and every visit goes into the plant record, as regulations 105 "
                                "and 106 of the Victorian OHS Regulations 2017 ask. The inspector books the next visit before leaving site.",
    ("bristol-pumps", "pressure"): "PV-301 is examined under a written scheme our competent person drew up, as PSSR regulation 8 requires, and the report "
                                   "sets the next date. We book the next examination the day the report arrives.",
    ("myer-plant", "fire"): "FE-1001 gets a monthly visual check and a signed tag, and our annual essential safety measures report covers it under the "
                            "Victorian Building Regulations 2018, regulation 223.",
    ("bristol-pumps", "fire"): "Our engine-hall extinguisher gets a monthly visual check and a signed tag, and the service firm does the annual service "
                               "and records it.",
    ("tomioka-mill", "fire"): "FE-501 to FE-503 and the hydrant FH-601 are inspected every six months by a licensed inspector, and the report goes to "
                              "the fire department under the Fire Service Act, article 17-3-3.",
    ("myer-plant", "hotwork"): "Every hot-work job at the plant room needs a signed permit, a fire watch for an hour afterwards and FE-1001 within reach.",
    ("bristol-pumps", "heritage"): "Padded stainless clamps on existing frame members: no drilling, welding or adhesive, every mount photographed and "
                                   "logged, and cables in the existing conduits.",
    ("tomioka-mill", "heritage"): "We need the Commissioner's permission before altering National Treasure fabric under article 43 of the Cultural "
                                  "Properties Act, so every mount is non-invasive and photographed, and anything that could alter the fabric waits.",
    ("bristol-pumps", "route"): "We close W-1201 at its entrance with the barrier and sign, sweep the route, log the time and the reason, and reopen only "
                                "after the visitor lead walks it.",
    ("tomioka-mill", "route"): "W-801 closes with the barrier and sign, the closure has to fit our fire defence plan, and the guide supervisor walks the "
                               "route before it reopens.",
    ("bristol-pumps", "humidity"): "We log the engine-house humidity every hour and run a dehumidifier when it climbs; the restoration lead checks the "
                                   "1907 metalwork for corrosion every week.",
}


def flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def per_day() -> int:
    try:
        return max(0, min(int(float(env("STEWARD_OWNER_ALERTS_PER_DAY", "3") or 3)), 100))
    except ValueError:
        return 3


def step_seconds() -> float:
    try:
        return max(0.0, min(float(env("STEWARD_ALERT_STEP_SECONDS", str(STEP_SECONDS)) or STEP_SECONDS), 60.0))
    except ValueError:
        return STEP_SECONDS


def place_of(site_id: str) -> str:
    return PLACE.get(site_id) or f"the {SITE_BY_ID.get(site_id, {}).get('area') or 'site'}"


def short_site(site_id: str) -> str:
    return SHORT_SITE.get(site_id) or SITE_BY_ID.get(site_id, {}).get("name") or site_id


def local(site_id: str, moment: datetime | None = None) -> datetime:
    moment = moment or utcnow()
    name, hours = SITE_ZONES.get(site_id, ("UTC", 0))
    try:
        from zoneinfo import ZoneInfo
        return moment.astimezone(ZoneInfo(name))
    except Exception:
        return moment.astimezone(timezone(timedelta(hours=hours)))


def day_month(moment: datetime | date_cls) -> str:
    return f"{moment.day} {moment.strftime('%B')}"


def plan_day(site_id: str) -> date_cls:
    """The working day after tomorrow at the site (Saturday and Sunday move to Monday)."""
    day = local(site_id).date() + timedelta(days=2)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def overdue_days(obligation: dict, moment: datetime | None = None) -> int | None:
    due = parse_time(obligation.get("dueAt"))
    moment = moment or utcnow()
    if due is None or due >= moment:
        return None
    return int((moment - due).total_seconds() // 86400)


def due_in_days(obligation: dict, moment: datetime | None = None) -> int | None:
    due = parse_time(obligation.get("dueAt"))
    if due is None:
        return None
    return max(0, -int(-(due - (moment or utcnow())).total_seconds() // 86400))


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def state_phrase(obligation: dict) -> str:
    if obligation.get("status") == "blocked":
        return "blocked"
    days = overdue_days(obligation)
    if days is None:
        return "due"
    return f"overdue by {plural(days, 'day')}" if days >= 1 else "overdue since today"


def categorize(obligation: dict) -> tuple[str, str]:
    """(category, short noun) for an obligation, from its title."""
    title = (obligation.get("title") or "").lower()
    if "hot-work" in title or "hot work" in title:
        return "hotwork", "Hot-work permit"
    if "contractor" in title and "report" in title:
        return "report", "Contractor service report"
    if "safety valve" in title or "lift and reseat" in title:
        return "pressure", "Safety valve lift test"
    if "steam demonstration" in title:
        return "pressure", "Steam demonstration permit"
    if "expansion vessel" in title:
        return "pressure", "Expansion vessel inspection"
    if any(word in title for word in ("pressure", "receiver", "vessel", "written-scheme", "written scheme", "examination")):
        return "pressure", "Pressure vessel examination"
    if "hydrant" in title:
        return "fire", "Fire hydrant inspection"
    if "extinguisher" in title:
        return "fire", "Fire extinguisher inspection"
    if "humidity" in title or "mould" in title:
        return "humidity", "Humidity watch"
    if "mounting" in title:
        return "heritage", "Heritage mounting and route-closure method"
    if any(word in title for word in ("alter", "national treasure", "permission")):
        return "heritage", "Alteration permission"
    if any(word in title for word in ("walkway", "visitor route", "traffic route")):
        return "route", "Walkway pre-opening check"
    if any(word in title for word in ("distribution board", "rcd", "electrical")):
        return "electrical", "Electrical periodic inspection"
    text = (obligation.get("title") or "Obligation").strip()
    return "generic", (text if len(text) <= 60 else text[:57].rsplit(" ", 1)[0] + "...")


def instrument_name(record: dict) -> str:
    """The instrument's English name, without trailing numbering such as (SI 2000/128) or the Japanese title; (Vic) stays."""
    text = (record.get("instrument") or record.get("id") or "").strip()
    while True:
        match = re.search(r"\s*\(([^()]*)\)\s*$", text)
        if not match or not (re.search(r"\d", match.group(1)) or re.search(r"[^\x00-\x7f]", match.group(1))):
            return text
        text = text[:match.start()].strip()


def instrument_short(record: dict) -> str:
    name = (record.get("instrument") or "").strip()
    for prefix, short in INSTRUMENT_SHORT:
        if name.startswith(prefix):
            return short
    return instrument_name(record)


def provision_short(record: dict) -> str:
    text = without_japanese((record.get("provision") or "").split(";")[0])
    head, _, rest = text.partition(", ")
    if rest and head and head in instrument_short(record):  # "Practice Note ESM-02, pp. 2-3" under "VBA Practice Note ESM-02"
        text = rest
    return text if len(text) <= 48 else text[:45].rsplit(" ", 1)[0] + "..."


def spoken(text: str) -> str:
    for pattern, replacement in SPOKEN:
        text = re.sub(pattern, replacement, text)
    return text


def cite_short(record: dict | None) -> str:
    """"PSSR 2000 reg. 9(6)-(7)"."""
    if not record:
        return "the site's rule pack"
    return f"{instrument_short(record)} {provision_short(record)}".strip()


def cite_spoken(record: dict | None) -> str:
    """"the Pressure Systems Safety Regulations 2000, regulation 9(6)-(7)"."""
    if not record:
        return "the site's rule pack"
    return f"the {instrument_name(record)}, {spoken(provision_short(record))}"


def without_japanese(text: str) -> str:
    """Drop every parenthesised group (nesting allowed) that holds Japanese, e.g. "(第43条第1項, art. 43(1))"."""
    text = text or ""
    out, stack = [], []  # stack: start offsets in `out` of the open groups
    for char in text:
        if char in "(（":
            stack.append(len(out))
            out.append(char)
        elif char in ")）" and stack:
            start = stack.pop()
            out.append(char)
            if any(ord(c) > 127 for c in out[start:]):
                del out[start:]
                while out and out[-1] == " ":
                    out.pop()
        else:
            out.append(char)
    return " ".join("".join(out).split()).replace(" ,", ",").replace(" .", ".")


def ascii_only(text: str) -> str:
    """Text for a voice brief: parentheses holding Japanese dropped, other non-ASCII characters removed."""
    return " ".join(without_japanese(text).encode("ascii", "ignore").decode().split())


def first_sentence(text: str, limit: int = 280) -> str:
    """The first sentence; past `limit` it is cut at the last clause break (semicolon, then comma) and closed."""
    text = " ".join((text or "").split())
    match = re.search(r"(?<!\b[A-Z])(?<!\barts)(?<!\bart)(?<!\breg)(?<!\bregs)(?<!\bSch)(?<!\bpp)(?<!\bNo)\.(\s|$)", text)
    sentence = text[:match.start() + 1] if match else text
    if len(sentence) <= limit:
        return sentence
    head = sentence[:limit]
    for mark in ("; ", ", "):
        cut = head.rfind(mark)
        if cut > limit // 3:
            return head[:cut].rstrip(" ,;") + "."
    return head.rsplit(" ", 1)[0] + "..."


def sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "?", "!")) else text + "."


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text and not text[:2].isupper() else text


def role_title(agent_id: str) -> str:
    """"Site Engineer", "Plant Manager", "Conservation Engineer", "Operations Director": the display name without the site."""
    return display_name(agent_id).split(" · ")[0]


def braces(text: str) -> str:
    """Conversation turns go through str.format_map; keep literal braces literal."""
    return text.replace("{", "{{").replace("}", "}}")


def mask_email(value: str) -> str | None:
    if not value or "@" not in value:
        return None
    name, domain = value.split("@", 1)
    return f"{name[:1]}•••@{domain}"


def mask_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return f"••• ••• {digits[-4:]}" if len(digits) >= 7 else None


def partner_site(site_id: str, category: str) -> str:
    for first, second in PAIRS.get(category, ()):
        if site_id == first:
            return second
        if site_id == second:
            return first
    order = [s for s in SITE_IDS if s in PLACE] or list(SITE_IDS)
    return order[(order.index(site_id) + 1) % len(order)] if site_id in order else order[0]


class ComplianceAlertService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()

    @property
    def comms(self) -> InkboxAdapter:
        return self.service.reality.comms

    def recover(self) -> int:
        """An alert left queued or running by an earlier backend process has no thread any more: mark it failed so the
        autoplayer does not wait on it (the next walkthrough after 24 h raises a fresh one)."""
        count = 0
        for alert in self.store.all("owner_alert"):
            if alert.get("state") in ("queued", "running"):
                alert.update(state="failed", finishedAt=now(), error="Interrupted by a backend restart.")
                self._save(alert)
                count += 1
        return count

    def close(self) -> None:
        self._stop.set()

    # ---- records -----------------------------------------------------------------------------------------

    def get(self, alert_id: str) -> dict:
        record = self.store.get("owner_alert", alert_id)
        if not record:
            raise RealityError("Owner alert not found.", "NOT_FOUND", "List alerts with GET /api/owner-alerts?siteId=.", 404)
        return record

    def list(self, site_id: str | None = None, limit: int = 50) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        records = self.store.all("owner_alert", site_id) if site_id else self.store.all("owner_alert")
        return sorted(records, key=lambda r: r["at"], reverse=True)[:max(1, int(limit))]

    def active(self) -> list[dict]:
        return [a for a in self.store.all("owner_alert") if a.get("state") in ("queued", "running")]

    def _save(self, alert: dict) -> dict:
        alert["updatedAt"] = now()
        self.store.put("owner_alert", alert, alert["siteId"])
        return alert

    def _change(self, alert: dict, summary: str, step: str | None, status: str) -> None:
        fields = dict(alertId=alert["id"], step=step, status=status, patrolId=alert.get("patrolId"), obligationId=alert.get("obligationId"))
        fields = {k: v for k, v in fields.items() if v is not None}
        self.service.reality.emit_change(alert["siteId"], "compliance_alert", alert["id"], summary[:480], alert.get("assetTag"), extra=fields, fields=fields)

    def _step(self, alert_id: str, name: str, summary: str, **refs) -> dict:
        with self.lock:
            alert = self.get(alert_id)
            alert["steps"].append(dict(n=len(alert["steps"]) + 1, name=name, at=now(), summary=summary[:400],
                                       refs={k: v for k, v in refs.items() if v}))
            self._save(alert)
        self._change(alert, f"Compliance alert {alert['assetTag'] or alert['obligationId']} step {len(alert['steps'])} ({name}): {summary[:300]}", name, "step")
        return alert

    def recent(self, obligation_id: str, hours: float = DEDUPE_HOURS) -> dict | None:
        """The latest alert for this obligation raised in the last `hours` (later walkthroughs reuse it)."""
        cutoff = utcnow() - timedelta(hours=hours)
        matches = [a for a in self.store.all("owner_alert") if a.get("obligationId") == obligation_id and (parse_time(a.get("at")) or cutoff) > cutoff]
        return max(matches, key=lambda a: a["at"]) if matches else None

    # ---- open --------------------------------------------------------------------------------------------

    def open(self, site_id: str, label: dict, obligation: dict, patrol: dict | None, walker: str, origin: str = "manual",
             reuse: bool = True) -> tuple[dict, bool]:
        """Create the alert for one bad obligation (queued; `run` plays it), or return the one raised for the same obligation in
        the last 24 h. Returns (alert, reused)."""
        with self.lock:
            if reuse:
                existing = self.recent(obligation["id"])
                if existing:
                    return existing, True
            status = "blocked" if obligation.get("status") == "blocked" else "overdue"
            days = overdue_days(obligation)
            category, noun = categorize(obligation)
            state = state_phrase(obligation)
            regulation_ids = list(obligation.get("regulationIds") or [])
            known = self.service.regulations.by_id()
            first = next((known[rid] for rid in regulation_ids if rid in known), None)
            crew = self.store.get("crew_member", obligation.get("ownerId") or "", site_id) if obligation.get("ownerId") else None
            frame_ids = [f for f in [label.get("frameId")] if f]
            alert = dict(id=uid("oal"), siteId=site_id, siteName=self.service.require_property(site_id)["name"], obligationId=obligation["id"],
                         obligationTitle=obligation.get("title"), obligationStatus=status, dueAt=obligation.get("dueAt"), daysOverdue=days,
                         blockedReason=obligation.get("blockedReason"), blockedBy=obligation.get("blockedBy"), assetTag=label.get("assetTag"),
                         assetName=label.get("assetName"), issueId=None, labelId=label.get("id"), patrolId=(patrol or {}).get("id"),
                         title=f"{label.get('assetTag') or obligation['id']}: {noun} {state}", severity="high" if (days or 0) > 7 else "medium",
                         category=category, noun=noun, statePhrase=state, citation=cite_short(first), regulationIds=regulation_ids,
                         ownerCrewId=(crew or {}).get("id"), ownerName=(crew or {}).get("name"), ownerRole=(crew or {}).get("role"),
                         walker=walker, walkerName=display_name(walker), partnerSiteId=partner_site(site_id, category), frameIds=frame_ids,
                         origin=origin if origin in ("manual", "autoplay") else "manual", state="queued", steps=[], conversationIds=[],
                         decision=None, email=None, call=None, liveAt=None, cappedReason=None, error=None, startedAt=None, finishedAt=None,
                         at=now(), synthetic=True)
            self._save(alert)
        self._change(alert, f"Compliance alert queued for {alert['title']}.", None, "queued")
        return alert, False

    # ---- run ---------------------------------------------------------------------------------------------

    def run(self, alert_id: str, realtime: bool = False) -> dict:
        with self.lock:
            alert = self.get(alert_id)
            if alert["state"] != "queued":
                return alert
            alert.update(state="running", startedAt=now())
            self._save(alert)
        compliance = compliance_id(alert["siteId"])
        self._change(alert, f"{display_name(compliance)} started the compliance alert for {alert['title']}.", None, "started")
        self.service.ops.note(compliance, f"Compliance alert: {alert['title']}"[:200], why="A walkthrough found a compliance gap")
        pause = step_seconds()
        for index, name in enumerate(STEPS):
            if realtime and index and pause and self._stop.wait(pause):
                return self.get(alert_id)
            try:
                getattr(self, f"step_{name}")(self.get(alert_id))
            except Exception as error:
                detail = error.detail if isinstance(error, RealityError) else f"{type(error).__name__}: {str(error)[:200]}"
                with self.lock:
                    alert = self.get(alert_id)
                    alert.update(state="failed", error=f"{name}: {detail}"[:300], finishedAt=now())
                    self._save(alert)
                self._step(alert_id, name, f"Stopped: {detail}")
                self._change(alert, f"Compliance alert for {alert['title']} failed at {name}: {detail}", name, "failed")
                self.service.ops.note(compliance, None)
                return self.get(alert_id)
        with self.lock:
            alert = self.get(alert_id)
            alert.update(state="completed", finishedAt=now())
            self._save(alert)
        self._change(alert, f"Compliance alert for {alert['title']} completed: email {alert['email']['mode']}, call {alert['call']['mode']}.", None, "completed")
        self.service.ops.note(compliance, None)
        return alert

    # ---- context -----------------------------------------------------------------------------------------

    def context(self, alert: dict) -> dict:
        site = alert["siteId"]
        known = self.service.regulations.by_id()
        regulations = [known[rid] for rid in alert.get("regulationIds") or [] if rid in known]
        first = regulations[0] if regulations else None
        category = CATEGORIES.get(alert.get("category") or "generic", CATEGORIES["generic"])
        manager, compliance, walker = manager_id(site), compliance_id(site), alert["walker"]
        partner = alert.get("partnerSiteId") or partner_site(site, alert.get("category") or "generic")
        day = plan_day(site)
        owner = alert.get("ownerName") or "the duty engineer"
        role = alert.get("ownerRole") or "duty engineer"
        values = dict(tag=alert.get("assetTag") or "the site", day=day.strftime("%A"), owner=owner)
        frames = [self.store.get("eye_frame", fid, site) for fid in alert.get("frameIds") or []]
        frames = [f for f in frames if f]
        frame_time = local(site, parse_time(frames[0]["at"])).strftime("%H:%M") if frames and parse_time(frames[0]["at"]) else None
        due = parse_time(alert.get("dueAt"))
        blocked = alert.get("obligationStatus") == "blocked"
        reason = (alert.get("blockedReason") or "").rstrip(". ")
        if blocked and not reason and alert.get("blockedBy"):
            blocker = self.store.get("obligation", alert["blockedBy"], site) or {}
            reason = f"waiting on {blocker.get('title') or alert['blockedBy']}"
        status_line = (f"its {lower_first(alert['noun'])} is blocked: {lower_first(reason or 'nothing can proceed until the block is cleared')}" if blocked else
                       f"its {lower_first(alert['noun'])} fell due on {day_month(local(site, due)) if due else 'its due date'}, so it is {alert['statePhrase']}")
        return dict(site=site, site_name=alert.get("siteName") or self.service.require_property(site)["name"], short=short_site(site), place=place_of(site),
                    tag=alert.get("assetTag") or "the site", asset=(alert.get("assetName") or "asset"), noun=alert["noun"], state=alert["statePhrase"],
                    blocked=blocked, block_reason=reason, status_line=status_line, regulations=regulations, first=first,
                    cite=cite_short(first), cite_spoken=cite_spoken(first), rule=without_japanese(first_sentence((first or {}).get("summary") or "")),
                    rule_full=first_sentence((first or {}).get("summary") or ""), reg_title=without_japanese((first or {}).get("title") or ""),
                    reg_title_full=(first or {}).get("title") or "", risk=category["risk"], hold=category["hold"].format(**values),
                    step=category["step"].format(**values), question=category["question"], help=category["help"],
                    practice=PRACTICE.get((partner, alert.get("category"))) or category["practice"], owner=owner, owner_role=role,
                    manager=manager, manager_name=display_name(manager), compliance=compliance, compliance_name=display_name(compliance),
                    walker=walker, walker_name=display_name(walker), partner=partner, partner_short=short_site(partner),
                    walker_role=role_title(walker).lower(), manager_role=role_title(manager), manager_role_l=role_title(manager).lower(),
                    partner_compliance=compliance_id(partner), partner_name=display_name(compliance_id(partner)), day=day,
                    day_name=day.strftime("%A"), frames=frames, frame_time=frame_time, severity=alert.get("severity") or "medium")

    def _obligation(self, alert: dict) -> dict:
        obligation = self.store.get("obligation", alert["obligationId"], alert["siteId"])
        if not obligation:
            raise RealityError(f"Obligation {alert['obligationId']} no longer exists.", "NOT_FOUND", "Walk the site again.", 404)
        return obligation

    # ---- steps -------------------------------------------------------------------------------------------

    def step_issue(self, alert: dict) -> None:
        site = alert["siteId"]
        obligation = self._obligation(alert)
        issues = self.service.issues
        frames = list(alert.get("frameIds") or [])
        existing = next((i for i in self.store.all("issue", site) if i.get("status") == "open" and i.get("obligationId") == alert["obligationId"]), None)
        if existing:
            existing["evidenceFrameIds"] = list(dict.fromkeys((existing.get("evidenceFrameIds") or []) + frames))
            existing["regulationIds"] = list(dict.fromkeys((existing.get("regulationIds") or []) + list(alert.get("regulationIds") or [])))
            existing.update(alertId=alert["id"], labelId=alert.get("labelId"), patrolId=alert.get("patrolId"))
            issue = issues._save(existing, f"Walkthrough evidence attached to {existing['id']}: {alert['title']}.", alert["walker"])
            verb = "reused"
        else:
            kind = "compliance_blocked" if alert["obligationStatus"] == "blocked" else "compliance_overdue"
            reason = f": {alert['blockedReason'].rstrip('.')}" if alert["obligationStatus"] == "blocked" and alert.get("blockedReason") else ""
            summary = (f"{obligation.get('title')} is {alert['statePhrase']}{reason} ({alert['citation']}). Found on the walkthrough of "
                       f"{place_of(site)} by {alert['walkerName']}.")
            issue = issues.raise_issue(site, kind, alert["severity"], summary, asset_tag=alert.get("assetTag"), issue_id=f"iss-{site[:2]}-compliance-{alert['obligationId']}",
                                       source="agent", obligation_id=alert["obligationId"], document_id=obligation.get("documentId"), synthetic=True,
                                       actor=alert["walker"], extra=dict(regulationIds=list(alert.get("regulationIds") or []), evidenceFrameIds=frames,
                                                                         alertId=alert["id"], labelId=alert.get("labelId"), patrolId=alert.get("patrolId"),
                                                                         ownerId=obligation.get("ownerId")))
            verb = "raised"
        with self.lock:
            alert = self.get(alert["id"])
            alert["issueId"] = issue["id"]
            self._save(alert)
        self._step(alert["id"], "issue", f"{alert['walkerName']} {verb} issue {issue['id']} ({issue['kind']}, {issue['severity']}) for {alert['title']} with "
                                         f"{plural(len(frames), 'evidence frame')}.", issueId=issue["id"], frameIds=frames or None)

    def _call(self, alert: dict, step: str, caller: str, callee: str, topic: str, turns: list[tuple[str, str]], summary: dict, sites: list[str]) -> dict:
        conversation = self.service.conversations.call(
            caller, callee, topic, [dict(speaker=speaker, text=braces(text)) for speaker, text in turns], site_ids=sites,
            issue_id=alert.get("issueId"), issue_kind="compliance_blocked" if alert["obligationStatus"] == "blocked" else "compliance_overdue",
            context={}, summary={k: ([braces(item) if isinstance(item, str) else {kk: braces(vv) for kk, vv in item.items()} for item in v]
                                     if isinstance(v, list) else braces(v)) for k, v in summary.items()},
            summary_by="hand-seed", synthetic=True, workflow_id=alert["id"])
        with self.lock:
            fresh = self.get(alert["id"])
            fresh["conversationIds"] = list(dict.fromkeys((fresh.get("conversationIds") or []) + [conversation["id"]]))
            self._save(fresh)
        return conversation

    def step_teammate_call(self, alert: dict) -> None:
        c = self.context(alert)
        evidence = f"the eye frame from {c['frame_time']}" if c["frame_time"] else "my label and the readings (the eye had no frame at this stop)"
        seen = (f"I have it on the agent eye at {c['frame_time']}" if c["frame_time"] else "The eye couldn't give me a frame here, so this is from the records")
        turns = [
            (c["walker"], f"Compliance, {c['walker_role']} here, on the walkthrough of {c['place']}. I'm at {c['tag']}, the {lower_first(c['asset'])}. "
                          f"{seen}, and {c['status_line']}."),
            (c["compliance"], f"That one is {c['cite_spoken']}" + (f", {lower_first(c['reg_title'])}" if c["reg_title"] else "") + "."
                              + (f" {c['rule']}" if c["rule"] else "")),
            (c["walker"], f"{c['owner']}, the {lower_first(c['owner_role'])}, owns it on our crew table. I've attached {evidence} to the issue, with my label."),
            (c["compliance"], f"Thanks. I'm raising it as {c['severity']} and putting the file and your evidence in one pack for the owner. I'll ask "
                              f"{c['partner_short']}'s compliance officer how they handle it, then take it to the {c['manager_role_l']} for a decision."),
            (c["walker"], sentence(f"Good. Meanwhile I'll {c['hold']}")),
        ]
        summary = dict(headline=f"{c['tag']}: {lower_first(c['noun'])} {c['state']}; owner alert being prepared",
                       points=[sentence(f"{c['tag']}: {c['status_line']}"), f"Why it matters: {c['cite']}" + (f" ({c['reg_title']})." if c["reg_title"] else "."),
                               f"Owner on the crew table: {c['owner']} ({c['owner_role']})."],
                       decisions=[f"Raise a {c['severity']} compliance issue and prepare the owner alert."],
                       actions=[dict(owner=c["compliance_name"], task="Put the file and the evidence together for the owner", due="now"),
                                dict(owner=c["walker_name"], task=sentence(c["hold"]).rstrip("."), due="until it is put right")])
        conversation = self._call(alert, "teammate_call", c["walker"], c["compliance"], f"{c['tag']}: {c['noun']} {c['state']}", turns, summary, [c["site"]])
        self._step(alert["id"], "teammate_call", f"{c['walker_name']} called {c['compliance_name']} about {c['tag']} ({len(turns)} turns): {c['cite']}.",
                   conversationId=conversation["id"])

    def step_cross_site_call(self, alert: dict) -> None:
        c = self.context(alert)
        turns = [
            (c["compliance"], f"{c['partner_short']}, it's {c['short']}'s compliance officer. Our {c['tag']} {lower_first(c['noun'])} is {c['state']}. "
                              f"Quick one: {c['question']}"),
            (c["partner_compliance"], c["practice"]),
            (c["compliance"], f"That fits. Ours falls under {c['cite']}, so I'll adapt it to that. Could you send me what you use?"),
            (c["partner_compliance"], c["help"]),
        ]
        summary = dict(headline=f"{c['partner_short']} shares how it handles {lower_first(c['noun'])}s",
                       points=[c["practice"], f"{c['short']} adapts it to {c['cite']}."],
                       decisions=[f"Adapt {c['partner_short']}'s approach for {c['tag']}."],
                       actions=[dict(owner=c["partner_name"], task=sentence(c["help"].replace("I'll ", "")).rstrip("."), due="today")])
        conversation = self._call(alert, "cross_site_call", c["compliance"], c["partner_compliance"], f"{c['noun']}: how {c['partner_short']} handles it",
                                  turns, summary, [c["site"], c["partner"]])
        self._step(alert["id"], "cross_site_call", f"{c['compliance_name']} called {c['partner_name']} ({len(turns)} turns): {c['help']}",
                   conversationId=conversation["id"], partnerSiteId=c["partner"])

    def step_manager_decision(self, alert: dict) -> None:
        c = self.context(alert)
        frames = f"the {c['walker_role']}'s eye frame" if c["frame_time"] else f"the {c['walker_role']}'s label"
        turns = [
            (c["compliance"], f"{c['manager_role']}, I need a decision on {c['tag']}. Its {lower_first(c['noun'])} is {c['state']}"
                              + (f" ({lower_first(c['block_reason'])})" if c["blocked"] and c["block_reason"] else "")
                              + f", and {c['risk']}. It falls under {c['cite']}. I have the file and {frames} ready for the owner."),
            (c["manager"], f"Approved: tell the owner now. {c['owner']} owns it, and I'm assigning it to them. The {c['walker_role']} will {c['hold']}. "
                           f"Next step: {c['step']}."),
            (c["compliance"], f"Understood. I'll email the owner the file and the evidence, then the dispatch line calls to ask: shall we {c['step']}?"),
        ]
        summary = dict(headline=f"{c['manager_name']} approves telling the owner about {c['tag']}",
                       points=[sentence(f"{c['tag']}: {c['noun']} {c['state']}"), f"Applies: {c['cite']}."],
                       decisions=["Tell the owner now.", f"Assign {c['owner']} ({c['owner_role']}).", sentence(f"Next step: {c['step']}")],
                       actions=[dict(owner=c["compliance_name"], task="Email the owner the file and the evidence", due="now"),
                                dict(owner="Steward Dispatch Line", task="Call the owner for the decision", due="after the email"),
                                dict(owner=c["owner"], task=sentence(c["step"]).rstrip("."), due=c["day_name"])])
        conversation = self._call(alert, "manager_decision", c["compliance"], c["manager"], f"Decision: tell the owner about {c['tag']}", turns, summary, [c["site"]])
        assigned = None
        if alert.get("issueId") and alert.get("ownerCrewId"):
            try:
                self.service.issues.assign(alert["issueId"], alert["ownerCrewId"], c["manager"])
                assigned = alert["ownerCrewId"]
            except RealityError:
                assigned = None
        with self.lock:
            fresh = self.get(alert["id"])
            fresh["decision"] = dict(by=c["manager"], byName=c["manager_name"], approved=True, assignedTo=assigned, assignedName=c["owner"] if assigned else None,
                                     nextStep=c["step"], ask=f"Shall we {c['step']}?", at=now())
            self._save(fresh)
        self._step(alert["id"], "manager_decision", f"{c['manager_name']} approved telling the owner"
                   + (f", assigned {c['owner']} ({c['owner_role']})" if assigned else "") + f"; next step: {c['step']}.",
                   conversationId=conversation["id"], crewMemberId=assigned)

    # ---- gates ----------------------------------------------------------------------------------------------

    def gate(self, alert: dict, channel: str) -> list[str]:
        """Why a real send cannot happen now (empty when every gate holds). Read from the environment at send time."""
        site = alert["siteId"]
        reasons = []
        if alert.get("origin") == "autoplay" and not flag("STEWARD_SCENARIO_AUTOPLAY_LIVE"):
            reasons.append("an autoplayed walkthrough sends only with STEWARD_SCENARIO_AUTOPLAY_LIVE=true")
        if channel == "email":
            sender = compliance_id(site)
            if not (agent_key(sender) or clean_env("INKBOX_API_KEY")):
                reasons.append("Inkbox is not configured (INKBOX_API_KEY)")
            if not handle_for(sender):
                reasons.append(f"no Inkbox identity for {display_name(sender)} ({(handle_env_names(sender) or ['identity'])[0]})")
            recipient, name = self.comms.owner_email(), "INKBOX_OWNER_EMAIL"
        else:
            if not clean_env("INKBOX_API_KEY"):
                reasons.append("Inkbox is not configured (INKBOX_API_KEY)")
            if not (clean_env("INKBOX_IDENTITY_DISPATCH") or clean_env("INKBOX_PHONE_IDENTITY")):
                reasons.append("no dispatch line identity (INKBOX_IDENTITY_DISPATCH)")
            recipient, name = self.comms.owner_phone(), "INKBOX_OWNER_PHONE"
        if not external_messages_allowed():
            reasons.append("STEWARD_ALLOW_EXTERNAL_MESSAGES is not true")
        if not flag("STEWARD_ALLOW_OWNER_ALERTS"):
            reasons.append("STEWARD_ALLOW_OWNER_ALERTS is not true")
        if not recipient:
            reasons.append(f"{name} is not set to a valid " + ("address" if channel == "email" else "phone number"))
        elif recipient.strip().casefold() not in allowed_recipients():
            reasons.append(f"{name} is not in INKBOX_ALLOWED_RECIPIENTS")
        return reasons

    def cap_reason(self, alert: dict) -> str | None:
        """The daily cap (live alerts in the last 24 h) and one live alert per obligation per 24 h."""
        cutoff = utcnow() - timedelta(hours=DEDUPE_HOURS)
        live = [a for a in self.store.all("owner_alert") if a["id"] != alert["id"] and a.get("liveAt") and (parse_time(a["liveAt"]) or cutoff) > cutoff]
        if any(a.get("obligationId") == alert["obligationId"] for a in live):
            return "the owner was already alerted about this obligation in the last 24 h (one alert per obligation per 24 h)"
        cap = per_day()
        if len(live) >= cap:
            return f"{plural(len(live), 'live owner alert')} in the last 24 h; the cap is STEWARD_OWNER_ALERTS_PER_DAY={cap}"
        return None

    def decide(self, alert: dict, channel: str) -> tuple[str, str | None]:
        """("send", None), ("dry_run", why) or ("capped", why). A send counts the alert as live (once per alert)."""
        reasons = self.gate(alert, channel)
        if reasons:
            return "dry_run", "; ".join(reasons)
        with self.lock:
            fresh = self.get(alert["id"])
            if fresh.get("liveAt"):
                return "send", None
            if fresh.get("cappedReason"):
                return "capped", fresh["cappedReason"]
            reason = self.cap_reason(fresh)
            if reason:
                fresh["cappedReason"] = reason
                self._save(fresh)
                return "capped", reason
            fresh["liveAt"] = now()
            self._save(fresh)
            return "send", None

    # ---- owner email --------------------------------------------------------------------------------------

    def references(self, c: dict, budget: int) -> tuple[list[dict], list[dict]]:
        """(cited regulations with link and attachment notes, PDF attachments). Victorian records are link-only."""
        regulations = self.service.regulations
        refs, files, seen, total = [], [], {}, 0
        for record in c["regulations"]:
            jurisdiction = record.get("jurisdiction")
            link = record.get("officialUrl") or record.get("pdfUrl")
            attached = None
            if jurisdiction in ATTACHABLE_JURISDICTIONS and record.get("servePdf") is True:
                path = regulations.pdf_file(record)
                if path and not path.name.lower().startswith(("vic_", "vba_")):
                    if path.name in seen:
                        attached = path.name
                    else:
                        size = path.stat().st_size
                        if size <= MAX_PDF_BYTES and total + size <= budget:
                            data = path.read_bytes()
                            files.append(dict(filename=path.name, content_type="application/pdf", content_base64=base64.b64encode(data).decode("ascii"),
                                              size=len(data), kind="regulation", regulationId=record["id"]))
                            seen[path.name] = True
                            total += size
                            attached = path.name
            note = ("official PDF attached" if attached else
                    "link only: the licence does not allow redistribution" if jurisdiction not in ATTACHABLE_JURISDICTIONS else "official text at the link")
            refs.append(dict(id=record["id"], cite=cite_short(record), title=record.get("title"), instrument=record.get("instrument"),
                             provision=record.get("provision"), summary=first_sentence(record.get("summary") or "", 320), url=link, attached=attached,
                             note=note, attribution=regulations.attribution(record) if attached else None, jurisdiction=jurisdiction))
        return refs, files

    def evidence_text(self, alert: dict, c: dict, label: dict | None, refs: list[dict]) -> str:
        site = alert["siteId"]
        obligation = self.store.get("obligation", alert["obligationId"], site) or {}
        attestations = sorted((a for a in self.store.all("attestation", site) if a.get("assetTag") == alert.get("assetTag")),
                              key=lambda a: a.get("signedAt") or a.get("observedAt") or "", reverse=True)[:3]
        lines = [f"Steward compliance evidence {alert['id']}", "",
                 f"Site: {c['site_name']} ({site})",
                 f"Asset: {c['tag']} ({c['asset']})",
                 f"Obligation: {alert['obligationId']}: {obligation.get('title') or alert.get('obligationTitle')}",
                 f"Status: {alert['statePhrase']}; due {(obligation.get('dueAt') or alert.get('dueAt') or '')[:10]}"
                 + (f"; blocked: {alert['blockedReason']}" if alert.get("blockedReason") and alert["obligationStatus"] == "blocked" else ""),
                 f"Owner: {c['owner']} ({c['owner_role']})",
                 f"Issue: {alert.get('issueId') or '-'}",
                 f"Walkthrough: {alert.get('patrolId') or '-'} by {alert['walkerName']}", ""]
        if label:
            lines += [f"Label {label['id']}: {label['title']} ({label['color']}) at {label['at']}"] + [f"  - {reason}" for reason in label.get("reasons") or []] + [""]
        lines.append("Frames:")
        lines += [f"  - {f['id']} at {f['at']} ({f.get('url')}), sha256 {f.get('sha256')}" for f in c["frames"]] or ["  - none (the eye had no frame at this stop)"]
        lines += ["", "Attestations (latest for the asset):"]
        lines += [f"  - {a['id']}: {a.get('attribute')} = {a.get('value')} at {a.get('observedAt')} ({a.get('verdict')})" for a in attestations] or ["  - none on file"]
        lines += ["", "Regulations:"]
        lines += [f"  - {r['cite']}: {r['title']} ({r['url']}); {r['note']}" for r in refs] or ["  - none cited"]
        lines += ["", "Plain-language summaries with links to the official text; not legal advice."]
        return "\n".join(lines) + "\n"

    def compose_email(self, alert: dict) -> dict:
        """Subject, HTML and text bodies and the attachments (with base64 content) of the owner email."""
        c = self.context(alert)
        site = alert["siteId"]
        label = self.store.get("patrol_label", alert.get("labelId") or "", site) if alert.get("labelId") else None
        attachments, total = [], 0
        frames = []
        for index, frame in enumerate(c["frames"][:MAX_FRAMES], 1):
            try:
                data = self.service.eye.frame_path(frame["id"]).read_bytes()
            except (RealityError, OSError):
                continue
            cid = f"evidence-{index}-{alert['id'][-8:]}"
            name = f"evidence-{(alert.get('assetTag') or 'site').lower()}-{index}.jpg"
            attachments.append(dict(filename=name, content_type="image/jpeg", content_base64=base64.b64encode(data).decode("ascii"), content_id=cid,
                                    size=len(data), kind="frame", frameId=frame["id"]))
            frames.append(dict(cid=cid, filename=name, at=local(site, parse_time(frame["at"])).strftime("%d %b %Y %H:%M") if parse_time(frame["at"]) else frame["at"]))
            total += len(data)
        refs, files = self.references(c, MAX_ATTACHMENT_BYTES - total)
        attachments += files
        evidence = self.evidence_text(alert, c, label, refs).encode("utf-8")
        attachments.append(dict(filename=f"evidence-{alert['id']}.txt", content_type="text/plain", content_base64=base64.b64encode(evidence).decode("ascii"),
                                size=len(evidence), kind="evidence"))
        subject = f"[{c['site_name']}] Compliance: {alert.get('obligationTitle') or c['noun']} ({c['state']})"
        decision = (alert.get("decision") or {})
        ask = f"Shall we {c['step']}?"
        extra = [r for r in (label or {}).get("reasons") or [] if not r.startswith(alert["noun"]) and not r.startswith("No eye frame")]
        what = (f"On today's walkthrough of {c['place']}, the {c['walker_role']} stopped at {c['tag']} ({lower_first(c['asset'])}): {c['status_line']}."
                + (" Also: " + "; ".join(extra[:3]) + "." if extra else ""))
        why = f"{c['cite_spoken'][:1].upper() + c['cite_spoken'][1:]}" + (f" ({c['reg_title_full']})" if c["reg_title_full"] else "") + (
            f": {c['rule_full']}" if c["rule_full"] else ".")
        who = (f"{c['owner']} ({c['owner_role']}) owns it on the {c['short']} crew table. The compliance officer is handling it, and the "
               f"{c['manager_role_l']} approved telling you" + (" and assigned it." if decision.get("assignedTo") else "."))
        attribution = [r["attribution"] for r in refs if r.get("attribution")]
        attribution = list(dict.fromkeys(attribution))
        esc = html_lib.escape
        ref_items = "".join(f"<li><a href=\"{esc(r['url'] or '')}\">{esc(r['cite'])}</a>: {esc(r['title'] or '')} <span style=\"color:#666\">({esc(r['note'])})</span></li>"
                            for r in refs)
        frame_html = "".join(f"<div style=\"margin:8px 0\"><img src=\"cid:{esc(f['cid'])}\" alt=\"Agent eye frame of {esc(c['tag'])}\" width=\"560\" "
                             f"style=\"max-width:100%;border-radius:6px;border:1px solid #ddd\"><div style=\"font-size:12px;color:#666\">{esc(c['tag'])}, "
                             f"{esc(f['at'])} site time ({esc(f['filename'])})</div></div>" for f in frames) or (
            "<p style=\"color:#666\">The agent eye had no frame at this stop; the label and the readings are in the evidence file.</p>")
        attached_list = "".join(f"<li>{esc(a['filename'])} ({max(1, round(a['size'] / 1024))} KB)</li>" for a in attachments)
        html = (
            "<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1a1a1a;max-width:640px\">"
            f"<p style=\"font-size:12px;color:#666;margin:0 0 6px\">Steward · {esc(c['site_name'])} · {esc(c['compliance_name'])}</p>"
            f"<h2 style=\"font-size:18px;margin:0 0 14px\">{esc(c['tag'])}: {esc(c['noun'])} {esc(c['state'])}</h2>"
            f"<p><b>What we found.</b> {esc(what)}</p>"
            f"<p><b>Why it matters.</b> {esc(why)} In plain words: {esc(c['risk'])}.</p>"
            f"<ul style=\"padding-left:18px\">{ref_items}</ul>"
            f"<p><b>Who owns it.</b> {esc(who)} Meanwhile the {esc(c['walker_role'])} will {esc(c['hold'])}.</p>"
            f"<p style=\"background:#f3f6fb;border-left:3px solid #2f5fb3;padding:10px 12px\"><b>Decision needed.</b> {esc(ask)} Reply to this email, "
            "or answer the Steward Dispatch Line when it calls.</p>"
            f"<p><b>Evidence.</b></p>{frame_html}"
            f"<p><b>Attached.</b></p><ul style=\"padding-left:18px\">{attached_list}</ul>"
            + "".join(f"<p style=\"font-size:12px;color:#666\">{esc(line)}</p>" for line in attribution)
            + ("<p style=\"font-size:12px;color:#666\">The summaries above are ours; the attached PDFs are the official texts, unedited.</p>" if files else "")
            + "<p style=\"font-size:12px;color:#666\">Regulation summaries are plain-language notes with links to the official text, not legal advice.</p>"
            "</div>")
        text = "\n".join([
            f"{c['tag']}: {c['noun']} {c['state']} ({c['site_name']})", "",
            f"What we found: {what}", "",
            f"Why it matters: {why} In plain words: {c['risk']}.",
            *[f"  - {r['cite']}: {r['title']} ({r['url']}); {r['note']}" for r in refs], "",
            f"Who owns it: {who} Meanwhile the {c['walker_role']} will {c['hold']}.", "",
            f"Decision needed: {ask} Reply to this email, or answer the Steward Dispatch Line when it calls.", "",
            "Evidence: " + (", ".join(f"{f['filename']} ({f['at']} site time)" for f in frames) or "no eye frame at this stop; see the evidence file."), "",
            "Attached: " + ", ".join(a["filename"] for a in attachments), "",
            *attribution,
            *(["The summaries above are ours; the attached PDFs are the official texts, unedited."] if files else []),
            "Regulation summaries are plain-language notes with links to the official text, not legal advice.",
        ])
        return dict(subject=subject[:300], html=html, text=text, attachments=attachments, references=refs)

    def step_owner_email(self, alert: dict) -> None:
        site = alert["siteId"]
        message = self.compose_email(alert)
        recipient = self.comms.owner_email()
        sender = compliance_id(site)
        mode, reason = self.decide(alert, "email")
        provider_ref = None
        if mode == "send":
            try:
                result = self.comms.send_email(site, recipient, message["subject"], message["text"], "", html=message["html"],
                                               attachments=[{k: a[k] for k in ("filename", "content_type", "content_base64", "content_id") if a.get(k)}
                                                            for a in message["attachments"]],
                                               sender_handle=handle_for(sender), api_key=agent_key(sender) or None, idempotency_key=f"steward-{alert['id']}-email")
                mode, provider_ref = "sent", (result or {}).get("id")
            except Exception as error:  # nothing is reported as delivered
                mode, reason = "failed", f"Inkbox send failed ({type(error).__name__}); nothing reported as delivered."
        record = dict(mode=mode, to=mask_email(recipient), fromAgent=sender, fromName=display_name(sender), fromAddress=email_for(sender),
                      subject=message["subject"], html=message["html"], text=message["text"],
                      attachments=[dict(filename=a["filename"], contentType=a["content_type"], size=a["size"], inline=bool(a.get("content_id")),
                                        kind=a.get("kind")) for a in message["attachments"]],
                      references=[{k: r[k] for k in ("id", "cite", "title", "url", "attached", "note", "jurisdiction")} for r in message["references"]],
                      providerRef=provider_ref, reason=reason, at=now())
        with self.lock:
            fresh = self.get(alert["id"])
            fresh["email"] = record
            self._save(fresh)
        names = ", ".join(a["filename"] for a in message["attachments"])
        self._step(alert["id"], "owner_email", f"{display_name(sender)} emailed the owner ({mode}{': ' + reason if reason and mode != 'sent' else ''}): "
                                               f"\"{message['subject']}\" with {names}."[:400], mode=mode)

    # ---- owner call ---------------------------------------------------------------------------------------

    def brief(self, alert: dict) -> str:
        c = self.context(alert)
        rule = ascii_only(c["rule"])
        parts = [f"Hello, this is the Steward Dispatch Line calling for the compliance team at {ascii_only(c['site_name'])}.",
                 sentence(f"The {lower_first(c['noun'])} for {c['tag']}, the {lower_first(ascii_only(c['asset']))}, is {c['state']}"),
                 sentence(f"Under {ascii_only(c['cite_spoken'])}, {lower_first(c['risk'])}"),
                 sentence(f"{ascii_only(c['owner'])}, the {lower_first(c['owner_role'])}, owns it, and the {c['manager_role_l']} has approved telling you"),
                 "The compliance officer has emailed you the file and the evidence from today's walkthrough.",
                 f"Decision needed: shall we {c['step']}? Please say yes or no, or reply to the email."]
        text = " ".join(parts)
        if rule and len(text) + len(rule) + 1 <= MAX_BRIEF_CHARS:
            parts.insert(3, rule)
            text = " ".join(parts)
        return text[:MAX_BRIEF_CHARS]

    def step_owner_call(self, alert: dict) -> None:
        site = alert["siteId"]
        brief = self.brief(alert)
        recipient = self.comms.owner_phone()
        mode, reason = self.decide(alert, "call")
        email_mode = (alert.get("email") or {}).get("mode")
        provider_ref = None
        if mode == "send":
            try:
                result = self.comms.place_call(site, recipient, brief)
                mode, provider_ref = "sent", (result or {}).get("id")
            except Exception as error:
                mode, reason = "failed", f"Inkbox call failed ({type(error).__name__}); nothing reported as delivered."
        record = {"mode": mode, "to": mask_phone(recipient), "from": "Steward Dispatch Line", "brief": brief, "voicemail": brief,
                  "providerRef": provider_ref, "reason": reason, "at": now()}
        with self.lock:
            fresh = self.get(alert["id"])
            fresh["call"] = record
            self._save(fresh)
        self._step(alert["id"], "owner_call", f"Steward Dispatch Line called the owner ({mode}{': ' + reason if reason and mode != 'sent' else ''}); "
                                              f"email was {email_mode or 'not sent'}.", mode=mode)
