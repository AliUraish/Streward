"""The owner's notifications page, the compliance snapshot PDF, the digest and the agents' play reports (owner, Oct 18
2026: "Have a notifications page to show what things last happened, send me mail too sometimes with a PDF of a compliance
snapshot and stuff. And that page should have agent mode too, so an agent can see what last things I got." and "Make these
all in a report and an agent mails me alerts reports ... I want them to use their email identities to mail me regarding their
play.").

**Feed** (`GET /api/owner/notifications?limit=&since=&siteId=&kind=&format=json|md`): newest first, everything sent or
prepared for the owner and the main things that happened. Items `{id, at, kind, channel: email|call|sms|dashboard, mode:
sent|dry_run|capped|failed|event, title, summary, siteId, siteName, links: {issueId, conversationId, alertId, windowId,
patrolId, digestId, reportId, obligationId, decisionRequestId}, attachments: [{filename, contentType, size, url}], to, from,
fromAddress, reason, severity}`. Kinds: `owner_alert` (the compliance alert's email and call, `compliance_alerts.py`),
`owner_digest` (the Operations Director's snapshot email), `agent_report` (an agent's play report), `decision_request` (the
owner's SMS copy of a decision request), `notice` (texts to the duty engineer, whose contact is the owner), and the events
`issue` (high-severity issue opened or resolved), `compliance_gap` (raised or closed), `maintenance` (a window booked, or
lined up with another site) and `walkthrough` (a walk that found something bad; a repeat of the same findings at the same
site within 6 h is not news). Seed records and machine chatter never appear (`real_only.py` rules: the seeded gaps' own
raise is hidden, their closing is shown); the owner's address and phone appear only masked; nothing is labelled synthetic.
`kind=` takes kinds, or `messages` / `events`. `format=md` is the same feed as compact Markdown for agents.

**Snapshot** (`GET /api/compliance/snapshot[.pdf]?siteId=`, all three sites by default): per site the compliance percent,
overdue, blocked (what blocks it) and due-within-14-days obligations with due dates, owners and regulation citations (titles
and links from the regulations service; Victorian legislation by title and link only), open compliance issues, upcoming
maintenance and cross-site coordination, and the agent activity (each agent's task and why, the site's latest calls and
messages, its latest real changes, the latest walkthrough's bad labels), plus what needs a decision and what changed since
the last snapshot. A black-and-white reportlab PDF with the OGL and PDL1.0 (出典) attribution lines for the titles it quotes.
Deterministic templates; no model is called.

**Owner channel** (`providers.owner_channel_blockers`, `InkboxAdapter._owner_gate`): a real email needs the sender's Inkbox
identity (`INKBOX_AGENT_KEY_<AGENT>` or `INKBOX_API_KEY`, and `INKBOX_IDENTITY_<AGENT>`), `STEWARD_ALLOW_OWNER_ALERTS=true` and
the owner's own address (`INKBOX_OWNER_EMAIL`) in `INKBOX_ALLOWED_RECIPIENTS`; it never needs `STEWARD_ALLOW_EXTERNAL_MESSAGES`
and never goes to anyone else. Otherwise the message is recorded `dry_run` with its full content.

**Digest** (Operations Director, `owner_digest` records, PDF on disk under `<data>/owner-mail/`): with the workers on, every
`STEWARD_OWNER_DIGEST_EVERY_HOURS` (4) when something changed since the last one, and on an important change (a new
compliance gap, a high-severity issue) at least `STEWARD_OWNER_DIGEST_MIN_GAP_MINUTES` (60) after the last; at most
`STEWARD_OWNER_DIGESTS_PER_DAY` (3) real digests in a rolling 24 h (beyond that `capped`); `POST /api/owner/digest`
(operator or director) prepares one now. Subject `Steward compliance snapshot · 18 Oct 2026 · Myer 83 %, Bristol 71 %,
Tomioka 71 %`, a short HTML body and the PDF attached.

**Play reports** (`agent_report` records): every site agent emails the owner from its own Inkbox identity about its own
work, only when something is new since its last report: the Site Engineer its walk findings (bad labels' frames inline and
attached), the Compliance Officer the compliance changes and alerts (its site's snapshot PDF attached), the Site or Plant
Manager the maintenance it booked, the cross-site coordination and its decisions, the Field Technician its work items,
dispatches and dispatch-line messages. At most `STEWARD_AGENT_REPORTS_PER_AGENT_PER_DAY` (1) per agent and
`STEWARD_AGENT_REPORTS_PER_DAY` (8) in all per rolling 24 h, and `STEWARD_AGENT_REPORT_MIN_GAP_MINUTES` (45) between any two
reports (the digest included); a report the caps hold back waits and later carries everything new. Real and dry-run
reports are paced and counted separately, so switching the owner channel on starts real reports at once.

**Outbox** (contract 8 §7): a real digest or report is queued in the outbox (`outbox.py`), which paces every person-facing email
(one every 2 minutes, nothing in the first 3 minutes after a restart) and writes the settled state back into the record's
`email` (with its `outboxId`); the feed reads the item's live state, so a queued email shows `queued` until it goes out. The feed
also lists the outbox's other emails and texts to the owner, the contractor and the employee (kinds `email`, `sms`) and the phone
calls with their outcome (kind `call`); digests, reports and alerts keep their own kinds and are not listed twice.
"""
from __future__ import annotations

import base64
import hashlib
import html as html_lib
import io
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agents import (DIRECTOR, OPERATOR, SHORT_SITE, agent_infos, agent_key, display_name, email_for, handle_env_names, handle_for, kind_of,
                     site_of, team_id)
from .compliance_alerts import CATEGORIES, categorize, cite_short, mask_email, mask_phone, plan_day, plural, query, state_phrase, without_japanese
from .env import env
from .errors import RealityError
from .providers import EMAIL_RE, PHONE_RE, clean_env, owner_channel_blockers
from .real_only import hidden_origins, notification_origin
from .sites import SITE_BY_ID, SITE_IDS
from .frame_labels import labelled_bytes
from .store import now, uid
from .verify import parse_time

MESSAGE_KINDS = ("owner_alert", "owner_digest", "agent_report", "decision_request", "notice", "email", "sms", "call")
EVENT_KINDS = ("issue", "compliance_gap", "maintenance", "walkthrough")
FEED_KINDS = MESSAGE_KINDS + EVENT_KINDS
KIND_GROUPS = {"messages": MESSAGE_KINDS, "events": EVENT_KINDS, "all": FEED_KINDS}
LINK_KEYS = ("issueId", "conversationId", "alertId", "windowId", "patrolId", "digestId", "reportId", "obligationId", "decisionRequestId",
             "phoneCallId", "outboxId", "inspectionId", "caseId")
MODES = ("sent", "dry_run", "capped", "failed", "queued")
OUTBOX_MODE = {"queued": "queued", "sending": "queued", "sent": "sent", "dry_run": "dry_run", "capped": "capped", "failed": "failed", "canceled": "failed"}
OWN_KIND_REFS = ("digestId", "reportId", "alertId")  # outbox items listed under their producer's own kind
ROLE_LABEL = {"owner": "you", "contractor": "you (contractor)", "employee": "you (employee)"}
CALL_MODE = {"queued": "queued", "dialing": "sent", "live": "sent", "ended": "sent", "voicemail": "sent", "no_answer": "sent", "failed": "failed",
             "dry_run": "dry_run", "capped": "capped", "canceled": "failed"}
COMPLIANCE_ISSUE_KINDS = {"inspection_overdue", "certificate_expired", "walkway_closure", "permit_blocked", "alteration_permit", "visitor_route",
                          "compliance_overdue", "compliance_blocked"}
GAP_STATUSES = ("overdue", "blocked")
REPORT_ROLES = ("compliance", "engineer", "manager", "technician")  # report priority when several agents have news
SITE_CITY = {"myer-plant": "Melbourne", "bristol-pumps": "London", "tomioka-mill": "Tokyo"}
SITE_ZONE = {"myer-plant": "Australia/Melbourne", "bristol-pumps": "Europe/London", "tomioka-mill": "Asia/Tokyo"}
WALK_REPEAT_HOURS = 6
TICK_SECONDS = 60
START_DELAY_SECONDS = 60
KEEP_DIGESTS = 300
KEEP_REPORTS = 600
WALK_CURSOR_META = "owner-feed:walk-cursor"
WALK_LAST_META = "owner-feed:walk-last:"
SEED_GAPS_META = "owner-feed:seed-gap-raises"
NOISE_CHANGE_TYPES = ("scenario", "attestation", "pin", "eye", "viewer", "a2a", "wait", "reply", "conversation")  # calls and messages are listed apart
LABEL_RE = re.compile(r"scenario|simulat|synthetic|fixture", re.I)
CJK_FONT = "HeiseiKakuGo-W5"

_LABEL_GROUP = re.compile(r"\s*[\(\[][^()\[\]]*\b(?:synthetic|simulat\w*|demo|demonstration|scenario\w*|fixture|DEMO-RP\S*)\b[^()\[\]]*[\)\]]", re.I)
_SCENARIO_PREFIX = re.compile(r"\b[Ss]cenario\s+[a-z0-9][\w-]*:\s*")
_LABEL_WORDS = re.compile(r"\b(?:synthetic|simulated|simulation|demo)\b[ ]?", re.I)
_SIM_REF = re.compile(r"\b(sensor|source):sim:", re.I)
_PDF_SAFE = re.compile(r"[^\x00-\xff–—‘’“”•…€]+")


# ---- settings ------------------------------------------------------------------------------------------------------------

def _flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def _number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(clean_env(name, str(default)) or default)
    except ValueError:
        return default
    return min(max(value, low), high)


def every_hours() -> float:
    return _number("STEWARD_OWNER_DIGEST_EVERY_HOURS", 4, 0.25, 168)


def digests_per_day() -> int:
    return int(_number("STEWARD_OWNER_DIGESTS_PER_DAY", 3, 0, 50))


def digest_min_gap_minutes() -> float:
    return _number("STEWARD_OWNER_DIGEST_MIN_GAP_MINUTES", 60, 0, 24 * 60)


def reports_per_agent() -> int:
    return int(_number("STEWARD_AGENT_REPORTS_PER_AGENT_PER_DAY", 1, 0, 24))


def reports_per_day() -> int:
    return int(_number("STEWARD_AGENT_REPORTS_PER_DAY", 8, 0, 200))


def report_min_gap_minutes() -> float:
    return _number("STEWARD_AGENT_REPORT_MIN_GAP_MINUTES", 45, 0, 24 * 60)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def zone(name: str):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def owner_zone():
    return zone(clean_env("STEWARD_OWNER_TIMEZONE", "UTC") or "UTC")


def stamp(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def when(moment: datetime | None, with_year: bool = True) -> str:
    """'18 Oct 2026, 17:05 UTC' in the owner's time zone (STEWARD_OWNER_TIMEZONE, default UTC)."""
    if moment is None:
        return "unknown time"
    local = moment.astimezone(owner_zone())
    label = local.tzname() or "UTC"
    return f"{local.day} {local:%b}" + (f" {local:%Y}" if with_year else "") + f", {local:%H:%M} {label}"


def site_local(site: str, moment: datetime | None) -> datetime | None:
    return moment.astimezone(zone(SITE_ZONE.get(site, "UTC"))) if moment else None


def site_day(site: str, value) -> str | None:
    """'21 Oct 2026' at the site."""
    local = site_local(site, parse_time(value) if isinstance(value, str) else value)
    return f"{local.day} {local:%b %Y}" if local else None


def short_site(site: str | None) -> str:
    return SHORT_SITE.get(site or "") or (SITE_BY_ID.get(site or "") or {}).get("name") or (site or "all sites")


def site_name(site: str | None) -> str | None:
    return (SITE_BY_ID.get(site or "") or {}).get("name") if site else None


def pct_label(value) -> str:
    return "n/a" if value is None else f"{int(round(float(value)))} %"


# ---- text ------------------------------------------------------------------------------------------------------------------

def clean(text) -> str:
    """Owner-facing text without internal labels (synthetic, demo, scenario ids, the simulator's sensor refs)."""
    value = str(text or "")
    value = _SCENARIO_PREFIX.sub("", value)
    value = _SIM_REF.sub(r"\1:", value)
    value = re.sub(r"\bdry_run\b", "prepared only", value)
    for _ in range(2):
        value = _LABEL_GROUP.sub("", value)
    value = _LABEL_WORDS.sub("", value)
    value = re.sub(r"\s{2,}", " ", value).replace(" .", ".").replace(" ,", ",")
    return value.strip(" ,;")


def sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "?", "!")) else text + "."


def first_words(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def humanize(reason: str | None, channel: str = "email") -> str:
    """Why something was not sent, in the owner's words (the technical reason stays in `reason`)."""
    text = reason or ""
    if "STEWARD_ALLOW_OWNER_ALERTS" in text:
        return "owner messaging is switched off"
    if "INKBOX_OWNER_EMAIL is not set" in text:
        return "your email address is not set"
    if "INKBOX_OWNER_PHONE" in text and "not set" in text or "no valid INKBOX_OWNER_PHONE" in text:
        return "your phone number is not set"
    if "INKBOX_ALLOWED_RECIPIENTS" in text:
        return "your address is not on the allowlist"
    if "no Inkbox identity" in text or "Inkbox is not configured" in text or "dispatch line identity" in text:
        return "the sender's mailbox is not configured" if channel == "email" else "the dispatch line is not configured"
    if "STEWARD_ALLOW_EXTERNAL_MESSAGES" in text or "STEWARD_ALLOW_NOTICE_SMS" in text:
        return "live texting is switched off"
    if "no contact details" in text or "no owner on the crew table" in text:
        return "no phone or email is set for you"
    if "AUTOPLAY_LIVE" in text:
        return "automatic sending was held"
    return "live sending is off"


def mode_note(mode: str, reason: str | None, channel: str = "email") -> str:
    if mode == "sent":
        return "Sent."
    if mode == "queued":
        return "Queued: it goes out with the next free slot (one message every 2 minutes)."
    if mode == "capped":
        return "Held: today's limit for these messages was reached."
    if mode == "failed":
        return "The send failed; nothing was delivered."
    return f"Prepared, not sent: {humanize(reason, channel)}."


def rich(text) -> str:
    """Escaped Paragraph markup; runs the standard fonts cannot draw (Japanese, arrows) use the CID font."""
    escaped = html_lib.escape("" if text is None else str(text), quote=False)
    if not _CJK_READY:
        return _PDF_SAFE.sub("", escaped)
    return _PDF_SAFE.sub(lambda match: f'<font name="{CJK_FONT}">{match.group(0)}</font>', escaped)


def _register_cjk() -> bool:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))
        return True
    except Exception:
        return False


_CJK_READY = _register_cjk()


def without_trailing_group(text: str) -> str:
    """'Pressure vessel examination overdue by 6 days' from '... (PSSR 2000 reg. 9(6)-(7))': the last balanced group goes."""
    text = (text or "").rstrip()
    if not text.endswith(")"):
        return text
    depth = 0
    for index in range(len(text) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(text[index], 0)
        if depth == 0:
            return text[:index].rstrip(" ,;:")
    return text


def lower_first(text: str) -> str:
    """Lower-case the first letter unless the first word is a tag or an acronym."""
    word = (text or "").split(" ", 1)[0]
    if not word or any(ch.isdigit() for ch in word) or (len(word) > 1 and word[1].isupper()):
        return text
    return text[:1].lower() + text[1:]


def crew_label(crew: dict | None) -> str:
    if not crew:
        return "unassigned"
    name, role = str(crew.get("name") or "").strip(), str(crew.get("role") or "").strip()
    if role and name.casefold().startswith(role.casefold()):
        return name
    return f"{name} ({role})" if role else name


def role_title(agent: str) -> str:
    return display_name(agent).split(" · ")[0]


class OwnerNotifications:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.directory = self.store.directory / "owner-mail"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.last_tick_at: str | None = None
        self.last_result: dict | None = None
        self.memo_seed_gaps()

    @property
    def comms(self):
        return self.service.reality.comms

    # ---- lifecycle ----------------------------------------------------------------------------------------------------

    def enabled(self) -> bool:
        return bool(self.service.start_workers) and _flag("STEWARD_OWNER_MAIL", "true")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="steward-owner-mail", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        if self._stop.wait(START_DELAY_SECONDS):
            return
        while True:
            if self.enabled():
                try:
                    self.tick()
                except Exception as error:  # the loop must never die
                    self.store.event(SITE_IDS[0], DIRECTOR, "owner_mail.failed", "Owner mail pass failed", f"{type(error).__name__}: {str(error)[:200]}")
            if self._stop.wait(TICK_SECONDS):
                return

    def tick(self, moment: datetime | None = None) -> dict | None:
        """One pass: the digest when it is due, otherwise at most one agent's play report. Returns what was prepared."""
        moment = moment or utcnow()
        self.last_tick_at = stamp(moment)
        self.sync_walks(moment)
        digest = self.digest_tick(moment)
        if digest:
            self.last_result = dict(kind="owner_digest", id=digest["id"], mode=(digest.get("email") or {}).get("mode"), at=digest["at"])
            return self.last_result
        if _flag("STEWARD_AGENT_REPORTS", "true"):
            report = self.report_tick(moment)
            if report:
                self.last_result = dict(kind="agent_report", id=report["id"], agentId=report["agentId"], mode=(report.get("email") or {}).get("mode"),
                                        at=report["at"])
                return self.last_result
        return None

    # ---- privacy ------------------------------------------------------------------------------------------------------

    def _private(self) -> list[tuple[str, str]]:
        """(plain, masked) for the owner's and the duty engineer's addresses and phones, read from the environment."""
        pairs = []
        for name in ("INKBOX_OWNER_EMAIL", "INKBOX_CONTRACTOR_EMAIL"):
            value = clean_env(name)
            if value and EMAIL_RE.match(value):
                pairs.append((value, mask_email(value) or "•••"))
        for name in ("INKBOX_OWNER_PHONE", "INKBOX_CONTRACTOR_PHONE"):
            value = clean_env(name)
            if value and PHONE_RE.match(value):
                masked = mask_phone(value) or "•••"
                pairs.append((value, masked))
                digits = re.sub(r"\D", "", value)
                if digits and digits != value:
                    pairs.append((digits, masked))
        return pairs

    def scrub(self, text, pairs: list[tuple[str, str]] | None = None) -> str | None:
        if text is None:
            return None
        value = str(text)
        for plain, masked in (pairs if pairs is not None else self._private()):
            value = re.sub(re.escape(plain), masked, value, flags=re.I)
        return value

    # ---- items --------------------------------------------------------------------------------------------------------

    def _item(self, item_id: str, at, kind: str, channel: str, mode: str, title: str, summary: str, site: str | None, links: dict | None = None,
              attachments: list[dict] | None = None, sites: list[str] | None = None, to: str | None = None, sender: str | None = None,
              sender_address: str | None = None, reason: str | None = None, severity: str | None = None, event: str | None = None,
              earliest_at: str | None = None) -> dict:
        moment = parse_time(at) if isinstance(at, str) else at
        out_links = {key: None for key in LINK_KEYS}
        for key, value in (links or {}).items():
            if key in out_links and value:
                out_links[key] = value
        files = [dict(filename=str(a.get("filename") or "file"), contentType=a.get("contentType"), size=a.get("size"), url=a.get("url"))
                 for a in attachments or [] if isinstance(a, dict)]
        return {"id": item_id, "at": stamp(moment), "kind": kind, "channel": channel, "mode": mode, "title": first_words(clean(title), 300),
                "summary": first_words(clean(summary), 700), "siteId": site, "siteName": site_name(site), "links": out_links, "attachments": files,
                "to": to, "from": sender, "fromAddress": sender_address, "reason": reason, "severity": severity,
                "earliestAt": earliest_at if mode == "queued" else None, "_dt": moment, "_event": event,
                "_sites": list(sites if sites is not None else ([site] if site else []))}

    @staticmethod
    def _mode(value) -> str:
        return value if value in MODES else "dry_run"

    def _alert_attachments(self, alert: dict, email: dict) -> list[dict]:
        regulations = {r.get("attached"): r.get("id") for r in email.get("references") or [] if isinstance(r, dict) and r.get("attached")}
        frames = list(alert.get("frameIds") or [])
        out = []
        for item in email.get("attachments") or []:
            if not isinstance(item, dict):
                continue
            name, url = str(item.get("filename") or ""), None
            if item.get("kind") == "frame":
                match = re.search(r"-(\d+)\.jpg$", name)
                index = int(match.group(1)) - 1 if match else -1
                if 0 <= index < len(frames):
                    url = f"/api/eye/frames/{frames[index]}.jpg"
            elif item.get("kind") == "regulation" and regulations.get(name):
                url = f"/api/regulations/{regulations[name]}/file"
            out.append(dict(filename=name, contentType=item.get("contentType"), size=item.get("size"), url=url))
        return out

    def _alert_items(self) -> list[dict]:
        out = []
        for alert in query(self.store, "owner_alert"):
            site = alert.get("siteId")
            steps = {step.get("name"): step for step in alert.get("steps") or [] if isinstance(step, dict)}
            decided = ((steps.get("manager_decision") or {}).get("refs") or {}).get("conversationId")
            links = dict(alertId=alert.get("id"), issueId=alert.get("issueId"), patrolId=alert.get("patrolId"), obligationId=alert.get("obligationId"),
                         conversationId=decided or (alert.get("conversationIds") or [None])[-1])
            ask = (alert.get("decision") or {}).get("ask")
            title = alert.get("title") or alert.get("obligationTitle") or "compliance alert"
            email = alert.get("email") if isinstance(alert.get("email"), dict) else None
            if email:
                mode = self._mode(email.get("mode"))
                files = self._alert_attachments(alert, email)
                summary = (f"{email.get('fromName') or 'The compliance officer'} emailed you the file and the evidence for {title} "
                           f"({plural(len(files), 'attachment')}).") + (f" Decision asked: {ask}" if ask else "") + " " + mode_note(mode, email.get("reason"))
                out.append(self._item(f"alert:{alert['id']}:email", email.get("at") or alert.get("at"), "owner_alert", "email", mode,
                                      email.get("subject") or f"Compliance: {title}", summary, site, links, files, to=email.get("to"),
                                      sender=email.get("fromName"), sender_address=email.get("fromAddress"), reason=email.get("reason"),
                                      severity=alert.get("severity")))
            call = alert.get("call") if isinstance(alert.get("call"), dict) else None
            if call:
                mode = self._mode(call.get("mode"))
                summary = (f"The Steward Dispatch Line called you about {title}" + (f" to ask: {ask}" if ask else ".") + " " + mode_note(mode, call.get("reason"), "call"))
                out.append(self._item(f"alert:{alert['id']}:call", call.get("at") or alert.get("at"), "owner_alert", "call", mode, f"Call: {title}",
                                      summary, site, links, [], to=call.get("to"), sender="Steward Dispatch Line", reason=call.get("reason"),
                                      severity=alert.get("severity")))
        return out

    def _live(self, email) -> dict:
        """An email record with the live state of its outbox item (contract 8 §7), when it has one."""
        email = email if isinstance(email, dict) else {}
        item = self.store.get("outbox_item", email["outboxId"], "") if email.get("outboxId") else None
        if not item:
            return email
        mode = OUTBOX_MODE.get(item.get("status"), email.get("mode") or "dry_run")
        return dict(email, mode=mode, providerRef=item.get("providerRef") or email.get("providerRef"), reason=None if mode == "sent" else item.get("reason") or email.get("reason"),
                    at=item.get("sentAt") or email.get("at"), earliestAt=item.get("earliestAt"))

    def _digest_items(self) -> list[dict]:
        out = []
        for digest in query(self.store, "owner_digest"):
            email = self._live(digest.get("email"))
            mode = self._mode(email.get("mode"))
            sites = list(digest.get("siteIds") or [])
            pdf = digest.get("pdf") or {}
            files = [dict(filename=pdf.get("filename"), contentType="application/pdf", size=pdf.get("size"), url=f"/api/owner/digests/{digest['id']}.pdf")] if pdf else []
            changes, decisions = len(digest.get("changes") or []), len(digest.get("decisions") or [])
            summary = (f"The Operations Director's compliance snapshot: {digest.get('complianceLine') or ''}. "
                       + (f"{plural(changes, 'change')} since the last snapshot" if changes else "No change since the last snapshot")
                       + (f", {plural(decisions, 'decision')} waiting for you" if decisions else "") + f". The PDF is attached. {mode_note(mode, email.get('reason'))}")
            out.append(self._item(f"digest:{digest['id']}", email.get("at") or digest.get("at"), "owner_digest", "email", mode,
                                  digest.get("subject") or "Steward compliance snapshot", summary, sites[0] if len(sites) == 1 else None,
                                  dict(digestId=digest["id"], outboxId=email.get("outboxId")), files, sites=sites, to=email.get("to"),
                                  sender=email.get("fromName") or display_name(DIRECTOR), sender_address=email.get("fromAddress"), reason=email.get("reason"),
                                  earliest_at=email.get("earliestAt")))
        return out

    def _report_items(self) -> list[dict]:
        out = []
        for report in query(self.store, "agent_report"):
            email = self._live(report.get("email"))
            mode = self._mode(email.get("mode"))
            found = (report.get("sections") or {}).get("found") or []
            summary = (f"{report.get('agentName')} reported on its work: {report.get('headline')}." + (f" {found[0]}" if found else "")
                       + f" {mode_note(mode, email.get('reason'))}")
            links = dict(report.get("links") or {}, reportId=report["id"], outboxId=email.get("outboxId"))
            out.append(self._item(f"report:{report['id']}", email.get("at") or report.get("at"), "agent_report", "email", mode,
                                  report.get("subject") or report.get("headline") or "Agent report", summary, report.get("siteId"), links,
                                  report.get("attachments") or [], to=email.get("to"), sender=report.get("agentName"),
                                  sender_address=email.get("fromAddress"), reason=email.get("reason"), earliest_at=email.get("earliestAt")))
        return out

    def _decision_items(self) -> list[dict]:
        out = []
        hide = hidden_origins(None)
        for note in query(self.store, "notification", "json_extract(body, '$.toKind') = 'owner'"):
            if notification_origin(note) in hide or note.get("generator"):
                continue
            site = note.get("siteId")
            request = self.store.get("decision_request", note.get("decisionRequestId") or "") if note.get("decisionRequestId") else None
            issue = self.store.get("issue", note.get("issueId") or "") if note.get("issueId") else None
            subject = (issue or {}).get("assetTag") or note.get("issueId") or "an issue"
            mode = note.get("mode") if note.get("mode") in ("sent", "failed", "queued") else "dry_run"
            status = ""
            if request:
                status = (f" Answered: {request['answer']} ({display_name(request.get('answeredBy') or OPERATOR)})." if request.get("answer")
                          else " Awaiting your answer.")
            channel = note.get("channel") if note.get("channel") in ("sms", "email") else "sms"
            out.append(self._item(f"sms:{note['id']}", note.get("at"), "decision_request", channel, mode, f"Text to you: decision needed on {subject}",
                                  f"{note.get('text') or ''}{status} {mode_note(mode, note.get('reason'), 'sms')}", site,
                                  dict(issueId=note.get("issueId"), decisionRequestId=note.get("decisionRequestId"),
                                       conversationId=(request or {}).get("conversationId")),
                                  to=note.get("toMasked"), sender=display_name(note.get("sender") or DIRECTOR), reason=note.get("reason"),
                                  severity=(issue or {}).get("severity")))
        return out

    def _notice_items(self) -> list[dict]:
        users = {c["id"]: c for c in self.store.all("crew_member") if c.get("contact") == "user"}
        if not users:
            return []
        out = []
        people = self.service.people
        for notice in self.store.all("notice"):
            crew = users.get(notice.get("toCrewId") or "")
            if not crew or notice.get("generator"):
                continue
            site = notice.get("siteId")
            channel = notice.get("channel") if notice.get("channel") in ("sms", "email") else "sms"
            mode = notice.get("mode") if notice.get("mode") in ("sent", "failed", "queued") else "dry_run"
            words = str(notice.get("noticeKind") or "notice").replace("_", " ")
            public = people.crew_public(crew)
            to = public.get("phone") if channel == "sms" else public.get("email")
            out.append(self._item(f"notice:{notice['id']}", notice.get("at"), "notice", channel, mode,
                                  f"{'Text' if channel == 'sms' else 'Email'} to you (duty engineer, {short_site(site)}): {words} notice",
                                  f"{notice.get('text') or ''} {mode_note(mode, notice.get('reason'), channel)}", site,
                                  dict(issueId=notice.get("issueId"), obligationId=notice.get("obligationId")), to=to,
                                  sender=display_name(notice.get("via") or notice.get("sender") or DIRECTOR), reason=notice.get("reason")))
        return out

    def _outbox_items(self) -> list[dict]:
        """The outbox's emails and texts to a person (contract 8): everything except what a digest, report or alert lists itself."""
        out = []
        for item in query(self.store, "outbox_item", "json_extract(body, '$.channel') IN ('email', 'sms')"):
            refs = item.get("refs") or {}
            if item.get("purpose") in ("digest", "agent_report") or any(refs.get(key) for key in OWN_KIND_REFS):
                continue
            mode = OUTBOX_MODE.get(item.get("status"), "dry_run")
            channel = item["channel"]
            to = ROLE_LABEL.get(item.get("toRole"), "you")
            files = [dict(filename=a.get("filename"), contentType=a.get("contentType"), size=a.get("size"), url=None) for a in item.get("attachments") or []]
            copies = [c.get("name") for c in item.get("cc") or [] if c.get("name")]
            if channel == "email":
                title = item.get("subject") or "Email"
                summary = (f"{item.get('senderName')} emailed {to}" + (f", copying {', '.join(copies)}" if copies else "") + f": {item.get('preview') or ''} "
                           + mode_note(mode, item.get("reason")))
            else:
                title = f"Text to {to}: {first_words(item.get('preview') or '', 80)}"
                summary = f"{item.get('preview') or ''} {mode_note(mode, item.get('reason'), 'sms')}"
            links = dict(outboxId=item["id"], phoneCallId=refs.get("phoneCallId"), issueId=refs.get("issueId"), windowId=refs.get("windowId"),
                         inspectionId=refs.get("inspectionId"), caseId=refs.get("caseId"), obligationId=refs.get("obligationId"),
                         conversationId=refs.get("conversationId"))
            out.append(self._item(f"outbox:{item['id']}", item.get("sentAt") or item.get("settledAt") or item.get("enqueuedAt"), channel, channel, mode,
                                  title, summary, item.get("siteId"), links, files, sites=[item["siteId"]] if item.get("siteId") else list(SITE_IDS),
                                  to=item.get("to"), sender=item.get("senderName"), sender_address=item.get("fromAddress"), reason=item.get("reason"),
                                  earliest_at=item.get("earliestAt")))
        return out

    def _call_items(self) -> list[dict]:
        """Phone calls to a person (contract 8 §3) with their outcome; an alert's own call is listed with the alert."""
        out = []
        for call in query(self.store, "phone_call"):
            refs = call.get("refs") or {}
            if any(refs.get(key) for key in OWN_KIND_REFS):
                continue
            status = call.get("status") or "queued"
            mode = CALL_MODE.get(status, "dry_run")
            outcome = call.get("outcome") or {}
            to = ROLE_LABEL.get(call.get("calleeRole"), "you")
            what = {"queued": "will call", "dialing": "is calling", "live": "is on the phone with", "voicemail": "left a voicemail for",
                    "no_answer": "could not reach"}.get(status, "called")
            summary = f"{call.get('callerName')} {what} {to} about {call.get('goal') or 'a site matter'}."
            if outcome.get("decision") and status not in ("queued", "dialing", "live"):
                summary += f" {outcome['decision']}."
            done = [f.get("type", "").replace("_", " ") for f in outcome.get("followUps") or [] if f.get("status") in ("done", "queued")]
            if done:
                summary += f" Then: {', '.join(done)}."
            if mode in ("dry_run", "capped", "failed"):
                summary += " " + mode_note(mode, call.get("reason"), "call")
            links = dict(phoneCallId=call["id"], outboxId=call.get("outboxId"), issueId=refs.get("issueId"), windowId=refs.get("windowId"),
                         inspectionId=refs.get("inspectionId"), caseId=refs.get("caseId"), obligationId=refs.get("obligationId"),
                         conversationId=refs.get("conversationId"))
            queued_item = self.store.get("outbox_item", call["outboxId"], "") if mode == "queued" and call.get("outboxId") else None
            out.append(self._item(f"call:{call['id']}", call.get("endedAt") or call.get("startedAt") or call.get("placedAt") or call.get("queuedAt"), "call",
                                  "call", mode, f"Call: {call.get('callerName')} to {to}", summary, call.get("siteId"), links, [],
                                  to=call.get("calleeName"), sender=call.get("callerName"), reason=call.get("reason"),
                                  earliest_at=(queued_item or {}).get("earliestAt") or call.get("notBefore")))
        return out

    # ---- events -------------------------------------------------------------------------------------------------------

    def memo_seed_gaps(self) -> None:
        """Remember the seeded gaps' own raise (complianceGap.origin "seed"): a later re-raise overwrites the origin, and the
        seeded raise never happened in this running system."""
        try:
            memo = json.loads(self.store.meta(SEED_GAPS_META) or "{}")
        except ValueError:
            memo = {}
        changed = False
        for issue in self.store.all("issue"):
            if (issue.get("complianceGap") or {}).get("origin") == "seed" and issue["id"] not in memo:
                memo[issue["id"]] = issue.get("at")
                changed = True
        if changed:
            self.store.meta(SEED_GAPS_META, json.dumps(memo))

    def _seed_gaps(self) -> dict:
        try:
            memo = json.loads(self.store.meta(SEED_GAPS_META) or "{}")
        except ValueError:
            memo = {}
        return memo

    @staticmethod
    def _cycles(issue: dict) -> list[dict]:
        """The issue's open and resolve cycles from its history: [{event: opened|resolved|reopened, at, severity, text}]."""
        history = sorted((h for h in issue.get("history") or [] if isinstance(h, dict) and parse_time(h.get("at"))), key=lambda h: parse_time(h["at"]))
        opened = parse_time(issue.get("at")) or (parse_time(history[0]["at"]) if history else None)
        first = next((h for h in history if not str(h.get("summary") or "").startswith(("resolved:", "assigned to"))), None)
        cycles = [dict(event="opened", at=opened, severity=(first or {}).get("severity") or issue.get("severity"), text=(first or {}).get("summary") or issue.get("summary"),
                       highAt=None)]
        state = "open"
        for entry in history:
            text = str(entry.get("summary") or "")
            moment = parse_time(entry["at"])
            if text.startswith("resolved:"):
                if state == "open":
                    cycles.append(dict(event="resolved", at=moment, severity=entry.get("severity"), text=text[len("resolved:"):].strip()))
                    state = "resolved"
            elif text.startswith("assigned to"):
                continue
            elif state == "resolved" and opened and moment and moment > opened + timedelta(seconds=2):
                cycles.append(dict(event="reopened", at=moment, severity=entry.get("severity"), text=text, highAt=None))
                state = "open"
            if state == "open" and entry.get("severity") == "high":
                current = next(c for c in reversed(cycles) if c["event"] in ("opened", "reopened"))
                if current.get("highAt") is None:
                    current["highAt"] = moment
        if issue.get("status") == "resolved" and state == "open":
            cycles.append(dict(event="resolved", at=parse_time(issue.get("resolvedAt")) or parse_time(issue.get("updatedAt")), severity=issue.get("severity"), text=""))
        return cycles

    def _issue_items(self) -> list[dict]:
        out = []
        seeded = self._seed_gaps()
        for issue in self.store.all("issue"):
            if issue.get("generator"):
                continue
            site = issue.get("siteId")
            kind_words = str(issue.get("kind") or "issue").replace("_", " ")
            obligation = self.store.get("obligation", issue.get("obligationId") or "", site or "") if issue.get("obligationId") else None
            tag = issue.get("assetTag") or (obligation or {}).get("assetTag")
            title_source = issue.get("obligationTitle") or (obligation or {}).get("title")
            subject = categorize(dict(title=title_source))[1].lower() if title_source and issue.get("kind") in COMPLIANCE_ISSUE_KINDS else kind_words
            label = f"{tag}: {subject}" if tag else subject
            links = dict(issueId=issue["id"], obligationId=issue.get("obligationId"), alertId=issue.get("alertId"), patrolId=issue.get("patrolId"),
                         windowId=issue.get("maintenanceWindowId"))
            gap = issue.get("kind") in COMPLIANCE_ISSUE_KINDS
            cycles = self._cycles(issue)
            counts: dict[str, int] = {}
            was_high = False
            for index, cycle in enumerate(cycles):
                event = cycle["event"]
                stem = ("closed" if event == "resolved" else "raised") if gap else ("resolved" if event == "resolved" else "opened")
                counts[stem] = counts.get(stem, 0) + 1
                suffix = "" if counts[stem] == 1 else f".{counts[stem]}"
                if event in ("opened", "reopened"):
                    was_high = gap or bool(cycle.get("highAt")) or cycle.get("severity") == "high"
                if gap:
                    if index == 0 and issue["id"] in seeded:
                        continue  # the seeded raise
                    name = {"opened": "raised", "reopened": "raised again", "resolved": "closed"}[event]
                    title = f"Compliance gap {name}: {label}"
                    item_id = f"gap:{issue['id']}:{stem}{suffix}"
                    kind = "compliance_gap"
                else:
                    if not was_high:
                        continue
                    name = {"opened": "opened", "reopened": "reopened", "resolved": "resolved"}[event]
                    title = f"High-severity issue {name}: {label}"
                    item_id = f"issue:{issue['id']}:{stem}{suffix}"
                    kind = "issue"
                moment = cycle["at"] if event == "resolved" or gap else (cycle.get("highAt") or cycle["at"])
                text = cycle.get("text") or issue.get("summary") or ""
                summary = (f"{issue.get('summary') or text}" if event != "resolved" else sentence(f"Closed: {text or 'the obligation is current again'}"))
                out.append(self._item(item_id, moment, kind, "dashboard", "event", title, summary, site, links, severity=cycle.get("severity") or issue.get("severity"),
                                      event=name))
        return out

    def _maintenance_items(self) -> list[dict]:
        out = []
        for window in self.store.all("maintenance_window", ""):
            if window.get("generator") and window.get("generator") != "planner":
                continue  # seeded windows were not booked in this running system
            sites = list(window.get("siteIds") or [])
            site = sites[0] if sites else None
            booked = window.get("status") in ("approved", "done") or window.get("origin") == "planner"
            verb = "booked" if booked else "proposed"
            when_text = window.get("localStart") or window.get("date") or ""
            city = SITE_CITY.get(site or "", "")
            coordination = window.get("coordination") if isinstance(window.get("coordination"), dict) else None
            others = [s for s in sites[1:]]
            partner = (coordination or {}).get("siteId") or (others[0] if others else None)
            scope = clean(window.get("scope") or "maintenance")
            title = f"Maintenance {verb} at {short_site(site)}: {first_words(scope, 90)}" + (f", lined up with {short_site(partner)}" if partner else "")
            who = display_name(window.get("proposedBy")) if window.get("proposedBy") else "The site manager"
            summary = (f"{who} {verb} {first_words(scope, 160)} for {when_text}" + (f" {city} time" if window.get("localStart") and city else "")
                       + (f" with {clean(window.get('examiner'))}" if window.get("examiner") else "") + ".")
            if coordination:
                summary += f" Lined up with {short_site(partner)}'s window after a call between the managers: {clean(coordination.get('note') or coordination.get('relation') or '')}"
            elif len(sites) > 1:
                summary += " A shared visit across " + ", ".join(short_site(s) for s in sites) + "."
            links = dict(windowId=window["id"], conversationId=(coordination or {}).get("conversationId") or window.get("conversationId"),
                         issueId=window.get("issueId"), obligationId=window.get("obligationId"))
            out.append(self._item(f"maintenance:{window['id']}", window.get("createdAt") or window.get("approvedAt") or window.get("updatedAt"), "maintenance",
                                  "dashboard", "event", title, summary, site, links, sites=sites, event=verb))
        return out

    # ---- walkthrough events (synced from the walks; a repeat of the same findings within 6 h is not news) ---------------

    def sync_walks(self, moment: datetime | None = None, limit: int = 2000) -> int:
        """Turn finished walkthroughs into walkthrough events, incrementally: a walk with bad labels becomes an event when its
        set of bad assets differs from the last event's at the site, or 6 h after it. Returns the events written."""
        moment = moment or utcnow()
        written = 0
        with self.lock:
            cursor = self.store.meta(WALK_CURSOR_META) or stamp(moment - timedelta(hours=24))
            walks = query(self.store, "patrol", "json_extract(body, '$.state') IN ('completed', 'canceled') AND json_extract(body, '$.finishedAt') > ?",
                          (cursor,), order="json_extract(body, '$.finishedAt') ASC", limit=limit)
            last_seen = cursor
            for walk in walks:
                finished = walk.get("finishedAt") or ""
                last_seen = max(last_seen, finished)
                site = walk.get("siteId")
                bad = [s for s in walk.get("stops") or [] if isinstance(s, dict) and s.get("verdict") == "bad"]
                key = WALK_LAST_META + str(site)
                try:
                    previous = json.loads(self.store.meta(key) or "{}")
                except ValueError:
                    previous = {}
                signature = ",".join(sorted({str(s.get("assetTag")) for s in bad}))
                if not bad:
                    if previous.get("signature"):
                        self.store.meta(key, json.dumps(dict(signature="", at=finished, patrolId=walk["id"])))
                    continue
                at = parse_time(finished)
                last_at = parse_time(previous.get("at"))
                if previous.get("signature") == signature and last_at and at and at - last_at < timedelta(hours=WALK_REPEAT_HOURS):
                    continue
                self.store.put("owner_walk_event", dict(id=f"wev-{walk['id']}", patrolId=walk["id"], siteId=site, at=finished, agentId=walk.get("agentId"),
                                                        agentName=walk.get("agentName"), place=walk.get("place"), checked=len(walk.get("stops") or []),
                                                        bad=[dict(assetTag=s.get("assetTag"), reason=s.get("reason"), frameId=s.get("frameId"),
                                                                  labelId=s.get("labelId")) for s in bad[:8]],
                                                        summary=walk.get("summary"), alertIds=list(walk.get("alertIds") or []),
                                                        conversationId=walk.get("conversationId"), state=walk.get("state")), site or "")
                self.store.meta(key, json.dumps(dict(signature=signature, at=finished, patrolId=walk["id"])))
                written += 1
            if last_seen != cursor:
                self.store.meta(WALK_CURSOR_META, last_seen)
        return written

    def _frame_attachment(self, frame_id: str | None, name: str) -> dict | None:
        if not frame_id:
            return None
        frame = self.store.get("eye_frame", frame_id) or {}
        return dict(filename=name, contentType="image/jpeg", size=frame.get("size"), url=f"/api/eye/frames/{frame_id}.jpg")

    def _walk_items(self) -> list[dict]:
        out = []
        for event in query(self.store, "owner_walk_event"):
            site = event.get("siteId")
            bad = event.get("bad") or []
            checked = event.get("checked") or 0
            title = f"Walkthrough at {short_site(site)}: {len(bad)} of {checked} look bad"
            reasons = "; ".join(f"{b.get('assetTag')}: {clean(b.get('reason') or 'looks bad')}" for b in bad[:4])
            summary = f"{event.get('agentName') or 'The site engineer'} walked {event.get('place') or 'the site'} and labelled {reasons}."
            files = [f for f in (self._frame_attachment(b.get("frameId"), f"{str(b.get('assetTag') or 'asset').lower()}.jpg") for b in bad[:3]) if f]
            labels = [self.store.get("patrol_label", b.get("labelId") or "", site or "") for b in bad[:1] if b.get("labelId")]
            links = dict(patrolId=event.get("patrolId"), conversationId=event.get("conversationId"), alertId=(event.get("alertIds") or [None])[0],
                         issueId=next((l.get("issueId") for l in labels if l and l.get("issueId")), None))
            out.append(self._item(f"walkthrough:{event.get('patrolId')}", event.get("at"), "walkthrough", "dashboard", "event", title, summary, site, links, files,
                                  event="found"))
        return out

    # ---- feed ---------------------------------------------------------------------------------------------------------

    def items(self, kinds: set | None = None) -> list[dict]:
        self.sync_walks()
        sources = (("owner_alert", self._alert_items), ("owner_digest", self._digest_items), ("agent_report", self._report_items),
                   ("decision_request", self._decision_items), ("notice", self._notice_items), (("email", "sms"), self._outbox_items),
                   ("call", self._call_items), (("issue", "compliance_gap"), self._issue_items),
                   ("maintenance", self._maintenance_items), ("walkthrough", self._walk_items))
        out: list[dict] = []
        for kind, build in sources:
            names = kind if isinstance(kind, tuple) else (kind,)
            if kinds and not set(names) & kinds:
                continue
            out += build()
        pairs = self._private()
        for item in out:
            for key in ("title", "summary", "to", "reason"):
                item[key] = self.scrub(item[key], pairs)
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        out.sort(key=lambda item: (item["_dt"] or epoch, item["id"]), reverse=True)
        return out

    @staticmethod
    def kinds(value: str | None) -> set | None:
        if not value:
            return None
        wanted = set()
        for part in str(value).split(","):
            name = part.strip()
            if not name:
                continue
            if name in KIND_GROUPS:
                wanted |= set(KIND_GROUPS[name])
            elif name in FEED_KINDS:
                wanted.add(name)
            else:
                raise RealityError(f"Unknown kind '{name[:40]}'.", "INVALID_REQUEST", "Kinds: " + ", ".join(FEED_KINDS) + ", or messages / events.")
        return wanted or None

    @staticmethod
    def public_item(item: dict) -> dict:
        return {key: value for key, value in item.items() if not key.startswith("_")}

    def feed(self, limit: int = 50, since: str | None = None, site_id: str | None = None, kind: str | None = None) -> dict:
        if site_id:
            self.service.require_property(site_id)
        kinds = self.kinds(kind)
        since_at = None
        if since:
            since_at = parse_time(since)
            if since_at is None:
                raise RealityError("since must be an ISO 8601 time.", "INVALID_REQUEST", "Pass the `at` of the newest item you have, e.g. 2026-10-18T17:05:00Z.")
        # `since` compares at the precision the items carry (`at`, milliseconds), so passing the newest `at` returns nothing new.
        rows = [item for item in self.items(kinds) if (not kinds or item["kind"] in kinds) and (not since_at or (item["at"] and parse_time(item["at"]) > since_at))
                and (not site_id or site_id in item["_sites"])]
        limit = max(1, min(int(limit), 500))
        return dict(at=now(), items=[self.public_item(item) for item in rows[:limit]], total=len(rows), limit=limit, since=since, siteId=site_id,
                    kinds=sorted(kinds) if kinds else None, latestAt=rows[0]["at"] if rows else None, schedule=self.schedule())

    def item(self, item_id: str) -> dict:
        for item in self.items():
            if item["id"] == item_id:
                return self.public_item(item)
        raise RealityError("Owner notification not found.", "NOT_FOUND", "List them with GET /api/owner/notifications.", 404)

    def markdown(self, feed: dict) -> str:
        """The feed as compact Markdown for agents: one block per item, newest first."""
        schedule = feed.get("schedule") or {}
        filters = ", ".join(f"{k}={v}" for k, v in (("siteId", feed.get("siteId")), ("kind", ",".join(feed.get("kinds") or []) or None),
                                                    ("since", feed.get("since"))) if v)
        lines = ["# Owner notifications", "",
                 f"As of {when(parse_time(feed.get('at')))} · {len(feed['items'])} of {feed['total']} items, newest first" + (f" · {filters}" if filters else ""),
                 f"Owner email: {'live' if schedule.get('live') else 'prepared only (' + humanize('; '.join(schedule.get('blockers') or [])) + ')'} · "
                 f"digests every {float(schedule.get('digest', {}).get('everyHours') or 0):g} h, at most {schedule.get('digest', {}).get('perDay')} a day · "
                 f"agent reports at most {schedule.get('reports', {}).get('perDay')} a day", ""]
        status = {"sent": "sent", "dry_run": "prepared, not sent", "capped": "held by the daily limit", "failed": "failed", "event": "event",
                  "queued": "queued"}
        for item in feed["items"]:
            head = (f"- **{when(parse_time(item['at']), with_year=False)}** · {item['kind']} · {item['channel']} · {status.get(item['mode'], item['mode'])} · "
                    f"{item.get('siteName') or 'all sites'}")
            lines.append(head)
            lines.append(f"  {item['title']}")
            lines.append(f"  {item['summary']}")
            refs = [f"id `{item['id']}`"]
            if item.get("from"):
                refs.append("from " + item["from"] + (f" <{item['fromAddress']}>" if item.get("fromAddress") else ""))
            if item.get("to"):
                refs.append(f"to {item['to']}")
            refs += [f"{key} {value}" for key, value in item["links"].items() if value]
            refs += [f"{a['filename']}" + (f" ({a['url']})" if a.get("url") else "") for a in item["attachments"][:4]]
            lines.append("  " + " · ".join(refs))
        if not feed["items"]:
            lines.append("Nothing yet.")
        return "\n".join(lines) + "\n"

    # ---- snapshot -----------------------------------------------------------------------------------------------------

    def sites(self, value=None) -> list[str]:
        """Site ids from a list or a comma-separated string, in the registry order; all sites when empty."""
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        known = [p["id"] for p in self.store.all("property")]
        order = [s for s in SITE_IDS if s in known] + [s for s in known if s not in SITE_IDS]
        if not value:
            return order
        for site in value:
            self.service.require_property(site)
        return [s for s in order if s in set(value)]

    def _regulation(self, record: dict) -> dict:
        jurisdiction = record.get("jurisdiction")
        return dict(id=record["id"], jurisdiction=jurisdiction, cite=cite_short(record), title=record.get("title"),
                    titleEnglish=without_japanese(record.get("title") or ""), url=record.get("officialUrl") or record.get("pdfUrl"),
                    linkOnly=jurisdiction == "VIC-AU" or record.get("servePdf") is not True)

    def _obligation(self, site: str, obligation: dict, known: dict, moment: datetime) -> dict:
        crew = self.store.get("crew_member", obligation.get("ownerId") or "", site) if obligation.get("ownerId") else None
        due = parse_time(obligation.get("dueAt"))
        status = obligation.get("status")
        blocker = None
        if status == "blocked" and obligation.get("blockedBy"):
            other = self.store.get("obligation", obligation["blockedBy"], site)
            blocker = clean((other or {}).get("title") or obligation["blockedBy"])
        _, noun = categorize(obligation)
        return dict(obligationId=obligation["id"], title=clean(obligation.get("title")), noun=noun, assetTag=obligation.get("assetTag"), status=status,
                    dueAt=obligation.get("dueAt"), dueDate=site_day(site, due) if due else None,
                    daysOverdue=int((moment - due).total_seconds() // 86400) if due and due < moment else None,
                    dueInDays=max(0, -int(-(due - moment).total_seconds() // 86400)) if due and due >= moment else None,
                    state=state_phrase(obligation), blockedBy=obligation.get("blockedBy"), blockedByTitle=blocker,
                    blockedReason=clean(obligation.get("blockedReason")) or None,
                    owner=dict(crewMemberId=crew["id"], name=crew.get("name"), role=crew.get("role"), label=crew_label(crew)) if crew else None,
                    regulations=[self._regulation(known[rid]) for rid in obligation.get("regulationIds") or [] if rid in known])

    def _walkthrough(self, site: str) -> dict | None:
        rows = query(self.store, "patrol", "json_extract(body, '$.state') IN ('completed', 'canceled')", order="json_extract(body, '$.finishedAt') DESC",
                     limit=1, property_id=site)
        if not rows:
            return None
        walk = rows[0]
        stops = [s for s in walk.get("stops") or [] if isinstance(s, dict)]
        bad = []
        for stop in stops:
            if stop.get("verdict") != "bad":
                continue
            label = self.store.get("patrol_label", stop.get("labelId") or "", site) if stop.get("labelId") else None
            reasons = [clean(r) for r in ((label or {}).get("reasons") or [stop.get("reason")]) if r and not str(r).startswith("No eye frame")]
            bad.append(dict(assetTag=stop.get("assetTag"), assetName=(label or {}).get("assetName"), reasons=reasons[:3], labelId=stop.get("labelId"),
                            frameId=stop.get("frameId"), frameUrl=f"/api/eye/frames/{stop['frameId']}.jpg" if stop.get("frameId") else None))
        return dict(patrolId=walk["id"], finishedAt=walk.get("finishedAt"), agentId=walk.get("agentId"), agentName=walk.get("agentName"),
                    place=walk.get("place"), checked=len(stops), good=len(stops) - len(bad), bad=bad, summary=clean(walk.get("summary")))

    def _maintenance(self, site: str, moment: datetime) -> list[dict]:
        today = site_local(site, moment).date().isoformat()
        out = []
        for window in self.service.maintenance.list(site):
            if window.get("status") not in ("proposed", "approved") or str(window.get("date") or "") < today:
                continue
            coordination = window.get("coordination") if isinstance(window.get("coordination"), dict) else None
            shared = [s for s in window.get("siteIds") or [] if s != site]
            linked = [self.store.get("maintenance_window", wid, "") for wid in window.get("linkedWindowIds") or []]
            linked_sites = sorted({s for w in linked if w for s in w.get("siteIds") or [] if s != site})
            out.append(dict(windowId=window["id"], date=window.get("date"), localStart=window.get("localStart"), city=SITE_CITY.get(site),
                            scope=clean(window.get("scope")), examiner=clean(window.get("examiner")) or None, status=window.get("status"),
                            assetTags=list(window.get("assetTags") or []), obligationId=window.get("obligationId"),
                            coordination=dict(siteId=coordination.get("siteId"), siteName=site_name(coordination.get("siteId")), windowId=coordination.get("windowId"),
                                              relation=coordination.get("relation"), note=clean(coordination.get("note")),
                                              conversationId=coordination.get("conversationId")) if coordination else None,
                            sharedWith=shared, linkedSites=linked_sites))
            if len(out) >= 4:
                break
        return out

    def _agents(self, site: str) -> list[dict]:
        infos = {info["id"]: info for info in agent_infos(self.service)}
        out = []
        for role in ("manager", "engineer", "compliance", "technician"):
            agent = team_id(site, role)
            info = infos.get(agent) or {}
            out.append(dict(agentId=agent, name=display_name(agent), status=info.get("status") or "idle", currentTask=clean(info.get("currentTask")) or None,
                            why=clean(info.get("why")) or None, waitingOn=clean(info.get("waitingOn")) or None, lastActivityAt=info.get("lastActivityAt"),
                            address=email_for(agent)))
        return out

    def _conversations(self, site: str, limit: int = 3) -> list[dict]:
        out = []
        try:
            rows = self.service.conversations.list(site, limit=12)
        except Exception:
            rows = []
        for row in rows:
            summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
            headline = clean(summary.get("headline") or row.get("topic") or "")
            if not headline or LABEL_RE.search(headline):
                continue
            participants = [display_name(p) if not str(p).startswith("crew-") else "a crew member" for p in row.get("participants") or []]
            out.append(dict(id=row.get("id"), kind=row.get("kind"), headline=first_words(headline, 140), participants=participants[:4],
                            at=row.get("startedAt") or row.get("at")))
            if len(out) >= limit:
                break
        return out

    def _changes(self, site: str, limit: int = 4) -> list[dict]:
        """The site's latest real changes: never scenario rows (as reality.changes(include_scenario=False)), nor the sensor feed's
        own readings and attestations, the eye's frames or the walkthroughs' per-stop rows."""
        marks = ",".join("?" for _ in NOISE_CHANGE_TYPES)
        rows = query(self.store, "change", f"json_extract(body, '$.type') NOT IN ({marks}) AND COALESCE(json_extract(body, '$.simulated'), 0) = 0",
                     NOISE_CHANGE_TYPES, order="json_extract(body, '$.version') DESC", limit=60, property_id=site)
        out = []
        for row in rows:
            if row.get("type") in ("patrol", "compliance_alert") and row.get("status") not in ("completed", "canceled", "failed"):
                continue
            text = clean(row.get("summary")).replace("dry_run", "prepared only")
            if not text or LABEL_RE.search(text):
                continue
            out.append(dict(at=row.get("at"), type=row.get("type"), summary=first_words(text, 160), version=row.get("version")))
            if len(out) >= limit:
                break
        return out

    def _issues(self, site: str) -> list[dict]:
        rows = [i for i in self.store.all("issue", site) if i.get("status") == "open" and i.get("kind") in COMPLIANCE_ISSUE_KINDS]
        order = {"high": 0, "medium": 1, "low": 2}
        rows.sort(key=lambda i: (order.get(i.get("severity"), 3), i.get("at") or ""))
        return [dict(issueId=i["id"], kind=i.get("kind"), severity=i.get("severity"), assetTag=i.get("assetTag"), obligationId=i.get("obligationId"),
                     summary=first_words(clean(i.get("summary")), 220), at=i.get("at")) for i in rows[:5]]

    def _decisions(self, site_ids: list[str], obligations: dict[str, list[dict]]) -> list[dict]:
        """What needs the owner's decision: open decision requests, then each gap with the alert's question or the next step."""
        out = []
        for request in query(self.store, "decision_request", "json_extract(body, '$.status') = 'awaiting_answer'"):
            if request.get("siteId") in site_ids:
                options = " / ".join(request.get("options") or [])
                out.append(dict(siteId=request["siteId"], source="decision_request", id=request["id"], issueId=request.get("issueId"),
                                text=f"{short_site(request['siteId'])}: {clean(request.get('question'))}" + (f" ({options})" if options else "")))
        alerts = {}
        for alert in query(self.store, "owner_alert", order="json_extract(body, '$.at') ASC"):
            if alert.get("state") != "failed" and (alert.get("decision") or {}).get("ask"):
                alerts[alert.get("obligationId")] = alert
        booked = self.booked_obligations()
        for site in site_ids:
            for item in obligations.get(site) or []:
                if item["status"] not in GAP_STATUSES or (item["status"] == "overdue" and item["obligationId"] in booked):
                    continue  # a booked visit needs no decision
                alert = alerts.get(item["obligationId"])
                if alert:
                    ask = alert["decision"]["ask"]
                else:
                    category, _ = categorize(dict(title=item["title"]))
                    owner = (item.get("owner") or {}).get("label") or "the owner on the crew table"
                    step = CATEGORIES.get(category, CATEGORIES["generic"])["step"]
                    ask = "Shall we " + step.format(tag=item.get("assetTag") or "the site", day=plan_day(site).strftime("%A"), owner=owner) + "?"
                tag = item.get("assetTag") or item["obligationId"]
                state = item["state"] if item["status"] != "blocked" else "blocked" + (f" ({item['blockedReason'].rstrip('.')})" if item.get("blockedReason") else "")
                out.append(dict(siteId=site, source="obligation", id=item["obligationId"], alertId=(alert or {}).get("id"),
                                text=f"{short_site(site)} {tag}: {item['noun']} {state}. {ask}"))
        return out[:8]

    def booked_obligations(self) -> set:
        """Obligations with an open (proposed or approved) maintenance window: their visit is already booked."""
        return {w.get("obligationId") for w in self.store.all("maintenance_window", "") if w.get("status") in ("proposed", "approved") and w.get("obligationId")}

    def baseline(self, track: str | None = None, sent_only: bool = False) -> dict | None:
        """The last digest (of a track: live or dry; any when None; `sent_only`: one that really went out)."""
        clauses, params = [], []
        if track:
            clauses, params = ["json_extract(body, '$.track') = ?"], [track]
        if sent_only:
            clauses.append("json_extract(body, '$.liveAt') IS NOT NULL")
        rows = query(self.store, "owner_digest", " AND ".join(clauses), tuple(params), order="json_extract(body, '$.at') DESC", limit=1)
        return rows[0] if rows else None

    def _change_lines(self, site_ids: list[str], sites: list[dict], since: datetime, previous: dict | None, moment: datetime) -> list[str]:
        lines = []
        state = (previous or {}).get("state") or {}
        for site in sites:
            before = (state.get(site["siteId"]) or {}).get("compliancePct")
            if before is not None and site["compliancePct"] is not None and round(before) != round(site["compliancePct"]):
                lines.append(f"{site['short']}: compliance {pct_label(before)} → {pct_label(site['compliancePct'])}.")
        events = [i for i in self.items(set(EVENT_KINDS)) if i["_dt"] and since < i["_dt"] <= moment and set(i["_sites"]) & set(site_ids)]
        events.sort(key=lambda i: i["_dt"])
        shown = events[-8:]
        for item in shown:
            prefix = "" if short_site(item["siteId"]) in item["title"] else f"{short_site(item['siteId'])}: "
            lines.append(f"{prefix}{item['title']} ({when(item['_dt'], with_year=False)}).")
        if len(events) > len(shown):
            lines.insert(len(lines) - len(shown), f"{len(events) - len(shown)} earlier events since {when(since, with_year=False)} are in the notifications feed.")
        messages = [i for i in self.items({"owner_alert"}) if i["_dt"] and since < i["_dt"] <= moment and set(i["_sites"]) & set(site_ids)]
        if messages:
            sent = sum(1 for i in messages if i["mode"] == "sent")
            lines.append(f"Owner alerts since then: {len(messages)} {'message' if len(messages) == 1 else 'messages'} (emails and calls), "
                         + (f"{sent} sent." if sent else "none sent."))
        return lines

    def snapshot(self, site_ids=None, moment: datetime | None = None, previous: dict | None = None, use_baseline: bool = True) -> dict:
        moment = moment or utcnow()
        site_ids = self.sites(site_ids)
        known = self.service.regulations.by_id()
        sites, obligations_by_site, cited = [], {}, {}
        for site in site_ids:
            prop = self.service.require_property(site)
            obligations = self.service.people.obligations(site)
            total = len(obligations)
            compliant = sum(1 for o in obligations if o["status"] in ("ok", "due_soon"))
            items = [self._obligation(site, o, known, moment) for o in obligations if o["status"] in ("overdue", "blocked", "due_soon")]
            obligations_by_site[site] = items
            for item in items:
                for regulation in item["regulations"]:
                    cited[regulation["id"]] = known[regulation["id"]]
            entry = dict(siteId=site, siteName=prop["name"], short=short_site(site), jurisdiction=prop.get("jurisdiction"), timeZone=SITE_ZONE.get(site),
                         compliancePct=round(100.0 * compliant / total, 1) if total else None,
                         counts=dict(total=total, compliant=compliant, overdue=sum(1 for o in obligations if o["status"] == "overdue"),
                                     blocked=sum(1 for o in obligations if o["status"] == "blocked"), dueSoon=sum(1 for o in obligations if o["status"] == "due_soon")),
                         overdue=[i for i in items if i["status"] == "overdue"], blocked=[i for i in items if i["status"] == "blocked"],
                         dueSoon=[i for i in items if i["status"] == "due_soon"], openComplianceIssues=self._issues(site),
                         maintenance=self._maintenance(site, moment), walkthrough=self._walkthrough(site), agents=self._agents(site),
                         conversations=self._conversations(site), changes=self._changes(site))
            entry["counts"]["openComplianceIssues"] = len(entry["openComplianceIssues"])
            sites.append(entry)
        if previous is None and use_baseline:
            previous = self.baseline()
        since = parse_time((previous or {}).get("at")) or moment - timedelta(hours=24)
        attributions = []
        for record in cited.values():
            if record.get("jurisdiction") in ("ENG-UK", "JP"):
                line = self.service.regulations.attribution(record)
                if line and line not in attributions:
                    attributions.append(line)
        if any(r.get("jurisdiction") == "JP" for r in cited.values()):
            attributions.append("Japanese headings are quoted from e-Gov with their English reference translation; this snapshot selects and arranges "
                                "them (edited by Steward).")
        if any(r.get("jurisdiction") == "VIC-AU" for r in cited.values()):
            attributions.append("Victorian legislation is cited by title with a link to the official text at legislation.vic.gov.au; none of its text "
                                "is reproduced.")
        line = ", ".join(f"{s['short']} {pct_label(s['compliancePct'])}" for s in sites)
        query_site = ",".join(site_ids) if len(site_ids) < len(self.sites()) else ""
        return dict(title="Steward compliance snapshot", at=stamp(moment), timeZone=clean_env("STEWARD_OWNER_TIMEZONE", "UTC") or "UTC",
                    siteIds=site_ids, complianceLine=line, sites=sites, decisions=self._decisions(site_ids, obligations_by_site),
                    changes=dict(since=stamp(since), baselineDigestId=(previous or {}).get("id"), lines=self._change_lines(site_ids, sites, since, previous, moment)),
                    attributions=attributions,
                    disclaimer="Regulation headings and links come from the official sources; summaries are plain-language notes, not legal advice.",
                    pdfUrl="/api/compliance/snapshot.pdf" + (f"?siteId={query_site}" if query_site else ""))

    @staticmethod
    def state_of(snapshot: dict) -> dict:
        return {s["siteId"]: dict(compliancePct=s["compliancePct"], gaps=[o["obligationId"] for o in s["overdue"] + s["blocked"]]) for s in snapshot["sites"]}

    def snapshot_file(self, site_ids=None) -> tuple[bytes, str]:
        snap = self.snapshot(site_ids)
        moment = parse_time(snap["at"])
        return self.snapshot_pdf(snap), f"steward-compliance-snapshot-{moment:%Y-%m-%d-%H%M}.pdf"

    # ---- PDF ----------------------------------------------------------------------------------------------------------

    def snapshot_pdf(self, snap: dict) -> bytes:
        """A clean black-and-white A4 report (reportlab platypus), a few pages."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        black, grey, light = colors.black, colors.Color(0.35, 0.35, 0.35), colors.Color(0.9, 0.9, 0.9)
        title_style = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=black, spaceAfter=2)
        meta_style = ParagraphStyle("m", fontName="Helvetica", fontSize=8.5, leading=11, textColor=grey, spaceAfter=6)
        h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=black, spaceBefore=9, spaceAfter=3)
        h3 = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=8.8, leading=11, textColor=black, spaceBefore=5, spaceAfter=1.5)
        body = ParagraphStyle("b", fontName="Helvetica", fontSize=8, leading=10, textColor=black)
        small = ParagraphStyle("s", fontName="Helvetica", fontSize=7, leading=8.6, textColor=grey)
        cell = ParagraphStyle("c", fontName="Helvetica", fontSize=7.4, leading=9, textColor=black)
        head = ParagraphStyle("hc", fontName="Helvetica-Bold", fontSize=7.4, leading=9, textColor=black)
        generated = when(parse_time(snap["at"]))
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=13 * mm, bottomMargin=14 * mm,
                                title=snap["title"], author="Steward", subject=f"Compliance snapshot, {generated}")
        width = A4[0] - 30 * mm

        def para(text, style=body):
            return Paragraph(rich(text), style)

        def bullet(text, style=body):
            return Paragraph("•&nbsp;" + rich(text), ParagraphStyle("bl", parent=style, leftIndent=8, firstLineIndent=-6))

        def grid(rows, widths, header=True):
            table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
            style = [("GRID", (0, 0), (-1, -1), 0.35, grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                     ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
            if header:
                style.append(("BACKGROUND", (0, 0), (-1, 0), light))
            table.setStyle(TableStyle(style))
            return table

        def link(regulation, full=True):
            label = f"{regulation['cite']}: {regulation['title'] or ''}".strip(": ") if full else regulation["cite"]
            url = html_lib.escape(regulation.get("url") or "", quote=True)
            return f'<a href="{url}" color="#000000">{rich(first_words(label, 80))}</a>' if url else rich(first_words(label, 80))

        def day(window):
            if window.get("localStart"):
                return f"{window['localStart']}" + (f" {window['city']} time" if window.get("city") else "")
            try:
                moment = datetime.fromisoformat(str(window.get("date"))[:10])
                return f"{moment:%a} {moment.day} {moment:%b}"
            except ValueError:
                return str(window.get("date") or "")

        def footer(canvas, document):
            canvas.saveState()
            canvas.setFont("Helvetica", 6.8)
            canvas.setFillColor(grey)
            canvas.drawString(15 * mm, 8 * mm, f"Steward compliance snapshot · {generated} · page {document.page}")
            canvas.restoreState()

        story = [Paragraph(rich(snap["title"]), title_style),
                 para(f"{generated} · " + " · ".join(f"{s['siteName']} {pct_label(s['compliancePct'])}" for s in snap["sites"]), meta_style)]
        rows = [[Paragraph(t, head) for t in ("Site", "Compliance", "Overdue", "Blocked", "Due in 14 days", "Open compliance issues", "Latest walkthrough")]]
        for site in snap["sites"]:
            walk = site.get("walkthrough")
            rows.append([para(site["siteName"], cell), para(f"{pct_label(site['compliancePct'])} ({site['counts']['compliant']} of {site['counts']['total']})", cell),
                         para(site["counts"]["overdue"], cell), para(site["counts"]["blocked"], cell), para(site["counts"]["dueSoon"], cell),
                         para(site["counts"]["openComplianceIssues"], cell),
                         para(f"{len(walk['bad'])} of {walk['checked']} look bad" if walk else "none yet", cell)])
        story.append(grid(rows, [44 * mm, 24 * mm, 15 * mm, 15 * mm, 22 * mm, 28 * mm, width - 148 * mm]))
        story.append(Paragraph("Needs your decision", h2))
        for item in snap["decisions"][:6] or [dict(text="Nothing is waiting for your decision.")]:
            story.append(bullet(item["text"]))
        story.append(Paragraph(rich(f"What changed since the last snapshot ({when(parse_time(snap['changes']['since']), with_year=False)})"), h2))
        for line in snap["changes"]["lines"] or ["No change since the last snapshot."]:
            story.append(bullet(line))
        for site in snap["sites"]:
            block = [Paragraph(rich(f"{site['siteName']} · {pct_label(site['compliancePct'])} compliant ({site['counts']['compliant']} of "
                                    f"{site['counts']['total']} obligations)"), h2)]
            attention = site["overdue"] + site["blocked"] + site["dueSoon"]
            block.append(Paragraph("Obligations needing attention", h3))
            if attention:
                table = [[Paragraph(t, head) for t in ("Status", "Obligation", "Due", "Owner", "Regulation")]]
                for item in attention[:6]:
                    if item["status"] == "overdue":
                        status = f"Overdue {item['daysOverdue']} d" if item.get("daysOverdue") else "Overdue"
                    elif item["status"] == "blocked":
                        status = "Blocked"
                    else:
                        status = f"Due in {item['dueInDays']} d" if item.get("dueInDays") is not None else "Due soon"
                    what = item["title"]
                    if item["status"] == "blocked":
                        what += f". Blocked by: {item.get('blockedByTitle') or item.get('blockedReason') or 'its blocker'}"
                        if item.get("blockedByTitle") and item.get("blockedReason"):
                            what += f" ({item['blockedReason'].rstrip('.')})"
                    regs = "; ".join([link(r) for r in item["regulations"][:1]] + [link(r, full=False) for r in item["regulations"][1:3]]) or rich("site rule pack")
                    table.append([para(status, cell), para(first_words(what, 230), cell), para(item.get("dueDate") or "", cell),
                                  para((item.get("owner") or {}).get("label") or "unassigned", cell), Paragraph(regs, cell)])
                block.append(grid(table, [19 * mm, 62 * mm, 19 * mm, 30 * mm, width - 130 * mm]))
            else:
                block.append(para("Every obligation is current."))
            story.append(KeepTogether(block[:3]))
            story += block[3:]
            if site["openComplianceIssues"]:
                shown = {item["obligationId"] for item in attention}
                tracked = [i for i in site["openComplianceIssues"] if i.get("obligationId") in shown]
                story.append(Paragraph("Open compliance issues", h3))
                if tracked:
                    story.append(para(f"{plural(len(tracked), 'open issue')} track the obligations above: " + ", ".join(
                        f"{i['issueId']} ({i['severity']})" for i in tracked) + ".", small))
                for issue in [i for i in site["openComplianceIssues"] if i not in tracked]:
                    story.append(bullet(f"{issue['severity']} · {issue['assetTag'] or 'site'} · {issue['summary']} ({issue['issueId']})"))
            story.append(Paragraph("Upcoming maintenance", h3))
            for window in site["maintenance"] or []:
                text = day(window)
                text += f" · {first_words(window['scope'], 120)}" + (f" · {window['examiner']}" if window.get("examiner") else "") + f" · {window['status']}"
                if window.get("coordination"):
                    text += f" · lined up with {window['coordination']['siteName'] or window['coordination']['siteId']} ({window['coordination']['windowId']})"
                elif window.get("sharedWith"):
                    text += " · shared with " + ", ".join(short_site(s) for s in window["sharedWith"])
                elif window.get("linkedSites"):
                    text += " · linked with " + ", ".join(short_site(s) for s in window["linkedSites"])
                story.append(bullet(text))
            if not site["maintenance"]:
                story.append(para("No maintenance window is booked."))
            agents = [[Paragraph(t, head) for t in ("Agent", "Status", "Working on", "Why")]]
            for agent in site["agents"]:
                task = agent.get("currentTask") or "No current task"
                if agent.get("waitingOn"):
                    task += f" (waiting on {agent['waitingOn']})"
                if agent.get("lastActivityAt"):
                    task += f" · {when(parse_time(agent['lastActivityAt']), with_year=False)}"
                agents.append([para(agent["name"], cell), para(agent["status"], cell), para(task, cell), para(agent.get("why") or "", cell)])
            story.append(KeepTogether([Paragraph("Agent activity", h3), grid(agents, [36 * mm, 15 * mm, 66 * mm, width - 117 * mm])]))
            walk = site.get("walkthrough")
            if walk:
                story.append(para(f"Latest walkthrough: {walk['agentName'] or 'the site engineer'}, {when(parse_time(walk['finishedAt']), with_year=False)}: "
                                  f"{walk['checked']} checked, {len(walk['bad'])} look bad.", body))
                for label in walk["bad"][:4]:
                    story.append(bullet(f"{label['assetTag']}" + (f" ({label['assetName']})" if label.get("assetName") else "") + ": "
                                        + ("; ".join(label["reasons"][:2]) or "looks bad"), body))
            else:
                story.append(para("No walkthrough has finished yet."))
            if site["conversations"]:
                story.append(para("Latest calls and messages:", body))
                for row in site["conversations"]:
                    story.append(bullet(f"{when(parse_time(row['at']), with_year=False)} · {row['kind']} · {row['headline']} · " + ", ".join(row["participants"]), small))
            if site["changes"]:
                story.append(para("Latest changes:", body))
                for row in site["changes"]:
                    story.append(bullet(f"{when(parse_time(row['at']), with_year=False)} · {row['type'].replace('_', ' ')} · {row['summary']}", small))
        story.append(Spacer(1, 6))
        story.append(Paragraph("Sources and licences", h3))
        for line in snap["attributions"]:
            story.append(para(line, small))
        story.append(para(snap["disclaimer"], small))
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return buffer.getvalue()

    # ---- the owner channel ----------------------------------------------------------------------------------------------

    @staticmethod
    def sender_blockers(agent: str) -> list[str]:
        """Why `agent` cannot email the owner for real now (empty when it can): its Inkbox identity, then the owner channel."""
        reasons = []
        if not (agent_key(agent) or clean_env("INKBOX_API_KEY")):
            reasons.append("Inkbox is not configured (INKBOX_API_KEY)")
        if not handle_for(agent):
            reasons.append(f"no Inkbox identity for {display_name(agent)} ({(handle_env_names(agent) or ['identity'])[0]})")
        return reasons + owner_channel_blockers("email")

    def _send(self, agent: str, site: str | None, record: dict, attachments: list[dict], kind: str = "owner_digest",
              property_id: str = "") -> tuple[str, str | None, str | None, str | None]:
        """Queue on the owner channel through the outbox (contract 8 §7), which paces it and writes the settled state back into the
        record's `email`. Returns (mode, providerRef, reason, outboxId); with the workers off the outbox sends at once."""
        link = "digestId" if kind == "owner_digest" else "reportId"
        files = [{k: a[k] for k in ("filename", "content_type", "content_base64", "content_id", "size") if a.get(k)} for a in attachments
                 if a.get("content_base64")]
        try:
            item = self.service.outbox.email(sender=agent, to_role="owner", subject=record["subject"], text=record["text"], html=record["html"],
                                             attachments=files, site_id=site, purpose="digest" if kind == "owner_digest" else "agent_report",
                                             refs={link: record["id"], "record": dict(kind=kind, id=record["id"], propertyId=property_id, field="email")},
                                             dedupe_key=f"{kind}:{record['id']}", priority=6 if kind == "owner_digest" else 7,
                                             idempotency_key=f"steward-{record['id']}-email")
        except Exception as error:  # nothing is reported as delivered
            return "failed", None, f"Inkbox send failed ({type(error).__name__}); nothing reported as delivered.", None
        mode = OUTBOX_MODE.get(item.get("status"), "failed")
        return mode, item.get("providerRef"), None if mode == "sent" else item.get("reason"), item.get("id")

    def _email_record(self, agent: str, mode: str, record: dict, attachments: list[dict], provider_ref: str | None, reason: str | None,
                      outbox_id: str | None = None) -> dict:
        return dict(mode=mode, to=mask_email(self.comms.owner_email()), fromAgent=agent, fromName=display_name(agent), fromAddress=email_for(agent),
                    subject=record["subject"], attachments=[dict(filename=a["filename"], contentType=a["content_type"], size=a.get("size"),
                                                                 inline=bool(a.get("content_id"))) for a in attachments],
                    providerRef=provider_ref, reason=reason, at=now(), outboxId=outbox_id)

    def _recent(self, kind: str, hours: float, moment: datetime, where: str = "", params: tuple = ()) -> list[dict]:
        cutoff = stamp(moment - timedelta(hours=hours))
        clause = "json_extract(body, '$.at') > ?" + (f" AND ({where})" if where else "")
        return query(self.store, kind, clause, (cutoff,) + tuple(params), order="json_extract(body, '$.at') DESC")

    def last_report_at(self, track: str) -> datetime | None:
        """The last owner report of a track (the digest or an agent report): the 45-minute gap counts from it."""
        times = []
        for kind in ("owner_digest", "agent_report"):
            rows = query(self.store, kind, "json_extract(body, '$.track') = ?", (track,), order="json_extract(body, '$.at') DESC", limit=1)
            if rows and parse_time(rows[0].get("at")):
                times.append(parse_time(rows[0]["at"]))
        return max(times) if times else None

    # ---- the digest (Operations Director) -----------------------------------------------------------------------------

    def digest_subject(self, snap: dict, moment: datetime) -> str:
        local = moment.astimezone(owner_zone())
        return f"Steward compliance snapshot · {local.day} {local:%b %Y} · {snap['complianceLine']}"

    def digest_body(self, snap: dict) -> tuple[str, str]:
        esc = html_lib.escape
        changes = snap["changes"]["lines"][:5]
        decisions = [d["text"] for d in snap["decisions"][:5]]
        generated = when(parse_time(snap["at"]))
        sites_html = " · ".join(f"<b>{esc(s['siteName'])}</b> {esc(pct_label(s['compliancePct']))}" for s in snap["sites"])
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#111;max-width:640px\">"
                f"<p style=\"font-size:12px;color:#555;margin:0 0 6px\">Steward · {esc(display_name(DIRECTOR))}</p>"
                f"<h2 style=\"font-size:18px;margin:0 0 12px\">Compliance snapshot, {esc(generated)}</h2>"
                f"<p>{sites_html}</p>"
                "<p><b>What changed.</b></p><ul style=\"padding-left:18px\">"
                + "".join(f"<li>{esc(line)}</li>" for line in (changes or ["No change since the last snapshot."])) + "</ul>"
                "<p><b>What needs your decision.</b></p><ul style=\"padding-left:18px\">"
                + "".join(f"<li>{esc(line)}</li>" for line in (decisions or ["Nothing is waiting for your decision."])) + "</ul>"
                "<p>The attached PDF lists every overdue, blocked and due-soon obligation with its owner and regulation, the open compliance "
                "issues, upcoming maintenance, the latest walkthrough and what each agent is doing.</p>"
                "<p style=\"font-size:12px;color:#555\">Regulation summaries are plain-language notes with links to the official text, not legal "
                "advice.</p></div>")
        text = "\n".join([f"Compliance snapshot, {generated}", "", " · ".join(f"{s['siteName']} {pct_label(s['compliancePct'])}" for s in snap["sites"]), "",
                          "What changed:", *[f"  - {line}" for line in (changes or ["No change since the last snapshot."])], "",
                          "What needs your decision:", *[f"  - {line}" for line in (decisions or ["Nothing is waiting for your decision."])], "",
                          "The attached PDF has the full snapshot.", "", "Regulation summaries are plain-language notes with links to the official text, "
                          "not legal advice.", "", f"{display_name(DIRECTOR)}, Steward"])
        return html, text

    def _important(self, since: datetime, moment: datetime) -> str | None:
        """The first important change since `since`: a compliance gap raised, or a high-severity issue opened."""
        for item in sorted(self.items({"compliance_gap", "issue"}), key=lambda i: i["_dt"] or moment):
            if item["_dt"] and since < item["_dt"] <= moment and item.get("_event") in ("raised", "raised again", "opened", "reopened"):
                return item["title"]
        return None

    def _nothing_new(self, previous: dict, moment: datetime) -> bool:
        since = parse_time(previous.get("at"))
        if since is None:
            return False
        if any(i["_dt"] and since < i["_dt"] <= moment for i in self.items(set(EVENT_KINDS) | {"owner_alert"})):
            return False
        current = {s: round(o["compliancePct"]) if o.get("compliancePct") is not None else None for s, o in self._pcts().items()}
        before = {s: round(v["compliancePct"]) if v.get("compliancePct") is not None else None for s, v in (previous.get("state") or {}).items()}
        return all(before.get(s) == value for s, value in current.items())

    def _pcts(self) -> dict:
        out = {}
        for site in self.sites():
            obligations = self.service.people.obligations(site)
            compliant = sum(1 for o in obligations if o["status"] in ("ok", "due_soon"))
            out[site] = dict(compliancePct=round(100.0 * compliant / len(obligations), 1) if obligations else None)
        return out

    def digest_tick(self, moment: datetime) -> dict | None:
        if not _flag("STEWARD_OWNER_DIGEST", "true"):
            return None
        track = "dry" if self.sender_blockers(DIRECTOR) else "live"
        last_report = self.last_report_at(track)
        if last_report and moment - last_report < timedelta(minutes=report_min_gap_minutes()):
            return None
        previous = self.baseline(track)
        if previous is None:
            return self.prepare_digest("scheduled", "The first snapshot", moment=moment)
        since = parse_time(previous.get("at")) or moment
        if moment - since >= timedelta(hours=every_hours()):
            if self._nothing_new(previous, moment):
                return None
            return self.prepare_digest("scheduled", f"Every {every_hours():g} h", moment=moment)
        if moment - since < timedelta(minutes=digest_min_gap_minutes()):
            return None
        important = self._important(since, moment)
        if important:
            return self.prepare_digest("change", important, moment=moment)
        return None

    def prepare_digest(self, trigger: str = "manual", reason: str | None = None, actor: str = "scheduler", site_ids=None,
                       moment: datetime | None = None) -> dict:
        """Build the snapshot and its PDF, record the digest and email it from the Operations Director's identity when the
        owner channel allows (else dry_run, or capped over STEWARD_OWNER_DIGESTS_PER_DAY)."""
        moment = moment or utcnow()
        sites = self.sites(site_ids)
        with self.lock:
            blockers = self.sender_blockers(DIRECTOR)
            track = "dry" if blockers else "live"
            previous = self.baseline(track, sent_only=track == "live")  # "since the last snapshot" the owner actually received
            snap = self.snapshot(sites, moment=moment, previous=previous, use_baseline=False)
            pdf = self.snapshot_pdf(snap)
            digest_id = uid("odg")
            filename = f"steward-compliance-snapshot-{moment.astimezone(owner_zone()):%Y-%m-%d-%H%M}.pdf"
            path = self.directory / f"{digest_id}.pdf"
            path.write_bytes(pdf)
            html, text = self.digest_body(snap)
            record = dict(id=digest_id, siteIds=sites, at=stamp(moment), trigger=trigger, reason=(reason or "")[:300] or None, requestedBy=actor, track=track,
                          subject=self.digest_subject(snap, moment)[:300], html=html, text=text, complianceLine=snap["complianceLine"],
                          compliance=[dict(siteId=s["siteId"], siteName=s["siteName"], compliancePct=s["compliancePct"]) for s in snap["sites"]],
                          changes=snap["changes"]["lines"], decisions=[d["text"] for d in snap["decisions"]], state=self.state_of(snap),
                          baselineDigestId=(previous or {}).get("id"), since=snap["changes"]["since"],
                          pdf=dict(filename=filename, size=len(pdf), sha256=hashlib.sha256(pdf).hexdigest(), url=f"/api/owner/digests/{digest_id}.pdf"),
                          _path=path.name, email=None, liveAt=None, synthetic=True)
            mode, why = "dry_run", "; ".join(blockers) or None
            if not blockers:
                sent = [d for d in self._recent("owner_digest", 24, moment, "json_extract(body, '$.liveAt') IS NOT NULL")]
                cap = digests_per_day()
                if len(sent) >= cap:
                    mode, why = "capped", f"{plural(len(sent), 'digest')} sent in the last 24 h; the cap is STEWARD_OWNER_DIGESTS_PER_DAY={cap}"
                else:
                    mode, record["liveAt"] = "send", now()
            self.store.put("owner_digest", record, "")
        attachment = dict(filename=filename, content_type="application/pdf", content_base64=base64.b64encode(pdf).decode("ascii"), size=len(pdf))
        provider_ref = outbox_id = None
        if mode == "send":
            self.service.ops.note(DIRECTOR, "Emailing the owner the compliance snapshot", why=reason or "The owner's digest")
            mode, provider_ref, why, outbox_id = self._send(DIRECTOR, sites[0] if len(sites) == 1 else None, record, [attachment])
            self.service.ops.note(DIRECTOR, None)
        with self.lock:
            record = self.store.get("owner_digest", digest_id, "") or record
            record["email"] = self._live(self._email_record(DIRECTOR, mode, record, [attachment], provider_ref, why, outbox_id))
            self.store.put("owner_digest", record, "")
            self._prune("owner_digest", KEEP_DIGESTS)
        return record

    def digest_pdf(self, digest_id: str) -> tuple[Path, str]:
        record = self.store.get("owner_digest", digest_id, "")
        path = self.directory / str((record or {}).get("_path") or "")
        if not record or not path.is_file():
            raise RealityError("Digest PDF not found.", "NOT_FOUND", "List digests with GET /api/owner/notifications?kind=owner_digest.", 404)
        return path, (record.get("pdf") or {}).get("filename") or f"{digest_id}.pdf"

    def report_pdf(self, report_id: str) -> tuple[Path, str]:
        record = self.store.get("agent_report", report_id)
        path = self.directory / str((record or {}).get("_path") or "")
        if not record or not record.get("_path") or not path.is_file():
            raise RealityError("Report PDF not found.", "NOT_FOUND", "List reports with GET /api/owner/notifications?kind=agent_report.", 404)
        return path, (record.get("pdf") or {}).get("filename") or f"{report_id}.pdf"

    def _prune(self, kind: str, keep: int) -> int:
        rows = query(self.store, kind, order="json_extract(body, '$.at') DESC")
        drop = rows[keep:]
        for record in drop:
            if record.get("_path"):
                try:
                    (self.directory / record["_path"]).unlink(missing_ok=True)
                except OSError:
                    pass
        if drop:
            with self.store.lock, self.store.connect() as db:
                db.executemany("DELETE FROM records WHERE kind=? AND id=?", [(kind, record["id"]) for record in drop])
        return len(drop)

    # ---- agent play reports -------------------------------------------------------------------------------------------

    def report_agents(self) -> list[str]:
        return [team_id(site, role) for role in REPORT_ROLES for site in self.sites()]

    def last_report(self, agent: str, track: str | None = None) -> dict | None:
        where = "json_extract(body, '$.agentId') = ?" + (" AND json_extract(body, '$.track') = ?" if track else "")
        rows = query(self.store, "agent_report", where, (agent, track) if track else (agent,), order="json_extract(body, '$.at') DESC", limit=1)
        return rows[0] if rows else None

    def report_tick(self, moment: datetime) -> dict | None:
        """At most one play report per pass: the agent (with something new, inside the caps of its track) that reported least
        recently, compliance before engineer before manager before technician."""
        gap = timedelta(minutes=report_min_gap_minutes())
        order = self.report_agents()
        tracks: dict[str, tuple] = {}
        candidates = []
        for agent in order:
            track = "dry" if self.sender_blockers(agent) else "live"
            if track not in tracks:
                tracks[track] = (self.last_report_at(track), self._recent("agent_report", 24, moment, "json_extract(body, '$.track') = ?", (track,)))
            last_any, day = tracks[track]
            if last_any and moment - last_any < gap:
                continue
            if len(day) >= reports_per_day() or sum(1 for r in day if r.get("agentId") == agent) >= reports_per_agent():
                continue
            previous = self.last_report(agent, track)
            since = parse_time((previous or {}).get("at")) or moment - timedelta(hours=24)
            if not self.report_content(agent, since, moment, files=False):
                continue
            last_seen = parse_time((self.last_report(agent) or {}).get("at"))
            candidates.append((last_seen or datetime.min.replace(tzinfo=timezone.utc), REPORT_ROLES.index(kind_of(agent)), order.index(agent), agent, since))
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[:3])
        *_, agent, since = candidates[0]
        return self.prepare_report(agent, since, moment)

    def report_content(self, agent: str, since: datetime, moment: datetime, files: bool = True) -> dict | None:
        """What the agent has to report since `since` (None when nothing is new). `files=False` skips the attachments (the
        snapshot PDF, the frames), for choosing who reports."""
        role, site = kind_of(agent), site_of(agent)
        if role not in REPORT_ROLES or not site:
            return None
        return getattr(self, f"_report_{role}")(agent, site, since, moment, files)

    def _gap_lines(self, site: str, moment: datetime) -> list[dict]:
        known = self.service.regulations.by_id()
        windows = {w.get("obligationId"): w for w in self.service.maintenance.list(site) if w.get("status") in ("proposed", "approved") and w.get("obligationId")}
        out = []
        for obligation in self.service.people.obligations(site):
            if obligation["status"] not in GAP_STATUSES:
                continue
            item = self._obligation(site, obligation, known, moment)
            window = windows.get(obligation["id"])
            cite = item["regulations"][0]["cite"] if item["regulations"] else None
            state = (f"{item['daysOverdue']} days overdue" if item.get("daysOverdue") else "overdue since today") if item["status"] == "overdue" else "blocked"
            booked = None
            if window:
                who = clean(window.get("examiner")) or "the contractor"
                booked = f"{who.split(' (')[0]} booked {window.get('localStart') or window.get('date')}"
            out.append(dict(item=item, state=state, cite=cite, window=window, booked=booked,
                            headline=f"{item.get('assetTag') or item['obligationId']} {item['noun'].lower()} {state}" + (f", {booked}" if booked else "")))
        return out

    def _report_compliance(self, agent: str, site: str, since: datetime, moment: datetime, build: bool = True) -> dict | None:
        gaps = [i for i in self.items({"compliance_gap"}) if i["_dt"] and since < i["_dt"] <= moment and site in i["_sites"]]
        alerts = [a for a in query(self.store, "owner_alert", property_id=site) if (parse_time(a.get("at")) or moment) > since and a.get("state") != "failed"]
        if not gaps and not alerts:
            return None
        raised = sum(1 for i in gaps if i["_event"] in ("raised", "raised again"))
        closed = sum(1 for i in gaps if i["_event"] == "closed")
        focus = [a.get("obligationId") for a in sorted(alerts, key=lambda a: a.get("at") or "", reverse=True)] + [i["links"].get("obligationId") for i in reversed(gaps)]
        lines = self._gap_lines(site, moment)
        lines.sort(key=lambda g: focus.index(g["item"]["obligationId"]) if g["item"]["obligationId"] in focus else len(focus))  # this period's news first
        did = []
        if raised or closed:
            did.append(f"Raised {plural(raised, 'compliance gap')} and closed {closed}" if raised else f"Closed {plural(closed, 'compliance gap')}")
        if alerts:
            did.append(f"Prepared {plural(len(alerts), 'owner alert')} with the file and the evidence (" + ", ".join(sorted({a.get('assetTag') or a['obligationId'] for a in alerts})) + ")")
        found = [sentence(f"{g['item'].get('assetTag') or g['item']['obligationId']}: {g['item']['noun']} {g['state']}"
                          + (f" ({g['item']['blockedReason'].rstrip('.')})" if g["item"]["status"] == "blocked" and g["item"].get("blockedReason") else "")
                          + (f", under {g['cite']}" if g["cite"] else "")) for g in lines[:4]] or ["Every obligation at the site is current again."]
        found += [sentence(f"Closed: {i['title'].split(': ', 1)[-1]}") for i in gaps if i["_event"] == "closed"][:2]
        booked = [g for g in lines if g["booked"]]
        nxt = ([sentence(f"{g['item'].get('assetTag')}: {g['booked']} ({SITE_CITY.get(site, '')} time)") for g in booked[:3]]
               or ["I chase the contractors for dates and close each obligation when its record is in."])
        booked_ids = self.booked_obligations()
        asks = [a["decision"]["ask"] for a in alerts if (a.get("decision") or {}).get("ask") and a.get("obligationId") not in booked_ids]
        need = (asks[:2] or [d["text"] for d in self._decisions([site], {site: [g["item"] for g in lines]})[:2]]
                or (["Nothing from you: the visits are booked; tell me if a date does not suit you."] if booked else ["Nothing from you right now."]))
        headline = lines[0]["headline"] if lines else (gaps[-1]["title"] if gaps else "compliance update")
        files = []
        if build:
            snap = self.snapshot([site], moment=moment, use_baseline=False, previous=dict(at=stamp(since)))
            pdf = self.snapshot_pdf(snap)
            name = f"{site}-compliance-snapshot-{moment.astimezone(owner_zone()):%Y-%m-%d-%H%M}.pdf"
            files = [dict(filename=name, content_type="application/pdf", content_base64=base64.b64encode(pdf).decode("ascii"), size=len(pdf), kind="snapshot",
                          bytes=pdf)]
        links = dict(alertId=alerts[-1]["id"] if alerts else None, issueId=(gaps[-1]["links"].get("issueId") if gaps else None) or (alerts[-1].get("issueId") if alerts else None),
                     obligationId=lines[0]["item"]["obligationId"] if lines else None)
        return dict(headline=headline, did=did, found=found, next=nxt, need=need, files=files, links=links,
                    counts=dict(gapsRaised=raised, gapsClosed=closed, alerts=len(alerts)))

    def _report_engineer(self, agent: str, site: str, since: datetime, moment: datetime, build: bool = True) -> dict | None:
        walks = query(self.store, "patrol", "json_extract(body, '$.agentId') = ? AND json_extract(body, '$.state') IN ('completed', 'canceled') "
                                            "AND json_extract(body, '$.finishedAt') > ?", (agent, stamp(since)),
                      order="json_extract(body, '$.finishedAt') DESC", limit=500, property_id=site)
        walks = [w for w in walks if (parse_time(w.get("finishedAt")) or moment) <= moment]
        if not walks:
            return None
        latest = walks[0]
        stops = [s for s in latest.get("stops") or [] if isinstance(s, dict)]
        bad = [s for s in stops if s.get("verdict") == "bad"]
        place = latest.get("place") or "the site"
        times = {1: "once", 2: "twice"}.get(len(walks), f"{len(walks)} times")
        did = [f"Walked {place} {times} since my last report, labelling every asset I looked at"]
        found = []
        for stop in bad[:4]:
            label = self.store.get("patrol_label", stop.get("labelId") or "", site) if stop.get("labelId") else None
            reasons = [clean(r) for r in ((label or {}).get("reasons") or [stop.get("reason")]) if r and not str(r).startswith("No eye frame")]
            found.append(sentence(f"{stop.get('assetTag')}: " + ("; ".join(reasons[:2]) or "looks bad")))
        if not found:
            found = [f"All {len(stops)} assets on my last walk look good."]
        alerts = [self.store.get("owner_alert", aid) for aid in latest.get("alertIds") or []]
        alerts = [a for a in alerts if a]
        booked_ids = self.booked_obligations()
        asks = [a["decision"]["ask"] for a in alerts if (a.get("decision") or {}).get("ask") and a.get("obligationId") not in booked_ids]
        tags = sorted({a.get("assetTag") for a in alerts if a.get("assetTag")})
        nxt = [f"I keep walking {place}; the compliance officer is taking {', '.join(tags)} to you." if tags else f"I keep walking {place} and label every asset I look at."]
        files = []
        for index, stop in enumerate([s for s in bad if s.get("frameId")][:3] if build else [], 1):
            try:
                data = labelled_bytes(self.service, stop["frameId"])
            except (RealityError, OSError):
                continue
            files.append(dict(filename=f"{str(stop.get('assetTag') or 'asset').lower()}-{index}.jpg", content_type="image/jpeg",
                              content_base64=base64.b64encode(data).decode("ascii"), content_id=f"frame-{index}-{latest['id'][-8:]}", size=len(data), kind="frame",
                              url=f"/api/eye/frames/{stop['frameId']}.jpg", caption=f"{stop.get('assetTag')}, {when(parse_time(stop.get('at')), with_year=False)}"))
        need = asks[:2] or (["Nothing from you; the frames of what looks bad are attached."] if files else ["Nothing from you right now."])
        if bad:
            first = without_trailing_group(clean(bad[0].get("reason") or "looks bad")) or "looks bad"
            headline = f"walked {place}: {len(bad)} of {len(stops)} look bad ({bad[0].get('assetTag')}: {first_words(lower_first(first), 70)})"
        else:
            headline = f"walked {place}: all {len(stops)} look good"
        return dict(headline=headline, did=did, found=found, next=nxt, need=need, files=files,
                    links=dict(patrolId=latest["id"], conversationId=latest.get("conversationId"), alertId=(latest.get("alertIds") or [None])[0]),
                    counts=dict(walks=len(walks), bad=len(bad), checked=len(stops)))

    def _report_manager(self, agent: str, site: str, since: datetime, moment: datetime, build: bool = True) -> dict | None:
        windows = []
        for window in self.store.all("maintenance_window", ""):
            if window.get("generator") and window.get("generator") != "planner":
                continue
            created = parse_time(window.get("createdAt")) or parse_time(window.get("approvedAt"))
            if not created or not since < created <= moment or site not in (window.get("siteIds") or []):
                continue
            if agent in (window.get("proposedBy"), window.get("approvedBy")) or (window.get("origin") == "planner" and (window.get("siteIds") or [None])[0] == site):
                windows.append(window)
        linked = [w for w in self.store.all("maintenance_window", "") if site not in (w.get("siteIds") or []) and (w.get("coordination") or {}).get("siteId") == site
                  and since < (parse_time(w.get("createdAt")) or since) <= moment]
        decisions = [a for a in query(self.store, "owner_alert", property_id=site) if (a.get("decision") or {}).get("by") == agent
                     and since < (parse_time((a.get("decision") or {}).get("at")) or since) <= moment]
        requests = [r for r in query(self.store, "decision_request", "json_extract(body, '$.manager') = ?", (agent,)) if since < (parse_time(r.get("at")) or since) <= moment]
        if not (windows or linked or decisions or requests):
            return None
        city = SITE_CITY.get(site, "")
        did = []
        if windows:
            coordinated = [w for w in windows if w.get("coordination")]
            did.append(f"Booked {plural(len(windows), 'maintenance visit')}" + (f", lining {len(coordinated)} up with another site after a call with its manager" if coordinated else ""))
        if linked:
            did.append("Lined our visits up with " + ", ".join(sorted({short_site(w['siteIds'][0]) for w in linked if w.get('siteIds')})) + " on their managers' calls")
        if decisions:
            did.append("Approved telling you about " + ", ".join(sorted({a.get("assetTag") or a["obligationId"] for a in decisions})) + " and assigned the crew owners")
        found = []
        for window in windows[:4]:
            text = f"{window.get('localStart') or window.get('date')}" + (f" {city} time" if window.get("localStart") else "") + f": {first_words(clean(window.get('scope')), 110)}"
            if window.get("examiner"):
                text += f" with {clean(window['examiner'])}"
            if window.get("coordination"):
                text += f"; lined up with {short_site(window['coordination'].get('siteId'))}'s window ({clean(window['coordination'].get('relation') or 'agreed on a call')})"
            found.append(sentence(text))
        for alert in decisions[:2]:
            found.append(sentence(f"{alert.get('assetTag') or alert['obligationId']}: next step {clean(alert['decision'].get('nextStep') or 'agreed')}"))
        if not found:
            found = [sentence(f"{len(linked)} of the other sites' visits now run alongside ours")]
        waiting = [r for r in query(self.store, "decision_request", "json_extract(body, '$.manager') = ? AND json_extract(body, '$.status') = 'awaiting_answer'", (agent,))]
        need = [sentence(f"Your answer on {clean(r.get('question'))}") for r in waiting[:2]] or ["Nothing; these bookings are within my authority."]
        nxt = ["The team is briefed: compliance files the record, the engineer prepares the asset and the technician confirms the contractor the day before."]
        if windows:
            first = windows[0]
            headline = (f"booked {first_words(clean(first.get('scope')), 60)} for {first.get('localStart') or first.get('date')}"
                        + (f", lined up with {short_site(first['coordination'].get('siteId'))}" if first.get("coordination") else ""))
        elif decisions:
            headline = f"approved telling you about {decisions[0].get('assetTag') or decisions[0]['obligationId']}"
        else:
            headline = "lined our maintenance up with the other sites"
        return dict(headline=headline, did=did, found=found, next=nxt, need=need, files=[],
                    links=dict(windowId=windows[0]["id"] if windows else None, conversationId=((windows[0].get("coordination") or {}).get("conversationId") if windows else None),
                               alertId=decisions[0]["id"] if decisions else None, decisionRequestId=requests[0]["id"] if requests else None),
                    counts=dict(windows=len(windows), linked=len(linked), decisions=len(decisions), requests=len(requests)))

    def _report_technician(self, agent: str, site: str, since: datetime, moment: datetime, build: bool = True) -> dict | None:
        def fresh(record: dict, *keys: str) -> bool:
            moment_of = next((parse_time(record.get(k)) for k in keys if parse_time(record.get(k))), None)
            return bool(moment_of and since < moment_of <= moment)

        notices = [n for n in self.store.all("notice", site) if n.get("via") == agent and not n.get("generator") and fresh(n, "at")]
        items = [w for w in self.store.all("work_item", site) if not w.get("simulated") and w.get("requester") != "simulation" and fresh(w, "updatedAt", "createdAt")]
        dispatches = [d for d in self.store.all("dispatch") if (d.get("propertyId") or d.get("_propertyId")) == site and not d.get("simulated")
                      and fresh(d, "sentAt")]
        if not (notices or items or dispatches):
            return None
        sent = sum(1 for n in notices if n.get("mode") == "sent") + sum(1 for d in dispatches if d.get("providerRef"))
        prepared = len(notices) + len(dispatches) - sent
        did = []
        if notices or dispatches:
            did.append(f"Handled {plural(len(notices) + len(dispatches), 'message')} through the Steward Dispatch Line"
                       + (f" ({sent} sent, {prepared} prepared only)" if prepared and sent else " (prepared only; live texting is off)" if prepared else ""))
        if items:
            did.append(f"Worked {plural(len(items), 'work item')}")
        found = []
        for item in sorted(items, key=lambda w: w.get("updatedAt") or "", reverse=True)[:3]:
            found.append(sentence(f"{item.get('reference') or item['id']}: {item.get('assetTag')} {str(item.get('attribute') or '').replace('_', ' ')} is {item.get('state')}"))
        for notice in notices[:3]:
            who = "you" if str(notice.get("toName") or "").endswith("(you)") else (notice.get("toName") or "the crew")
            found.append(sentence(f"{str(notice.get('noticeKind') or 'notice').replace('_', ' ').capitalize()} notice to {who}: {first_words(clean(notice.get('text')), 120)}"))
        open_items = [w for w in items if w.get("state") not in ("resolved", "rejected", "expired")]
        nxt = [f"I follow up on {plural(len(open_items), 'open work item')} when the replies come in."] if open_items else ["Nothing is waiting on a reply."]
        to_you = [n for n in notices if str(n.get("toName") or "").endswith("(you)") and not n.get("acknowledgedAt")]
        need = ["A reply to the dispatch line when you can: " + first_words(clean(to_you[0].get("text")), 120)] if to_you else ["Nothing from you right now."]
        parts = ([f"{plural(len(notices) + len(dispatches), 'message')} through the dispatch line"] if notices or dispatches else []) + (
            [plural(len(items), "work item")] if items else [])
        headline = ", ".join(parts)
        return dict(headline=headline, did=did, found=found or ["No reply has come in yet."], next=nxt, need=need, files=[],
                    links=dict(issueId=next((n.get("issueId") for n in notices if n.get("issueId")), None)),
                    counts=dict(notices=len(notices), workItems=len(items), dispatches=len(dispatches)))

    def report_body(self, agent: str, site: str, content: dict) -> tuple[str, str]:
        esc = html_lib.escape
        name = display_name(agent)
        address = email_for(agent)
        frames = [f for f in content["files"] if f.get("content_id")]
        html = ("<div style=\"font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#111;max-width:640px\">"
                f"<p style=\"font-size:12px;color:#555;margin:0 0 6px\">Steward · {esc(site_name(site) or site)} · {esc(name)}</p>"
                f"<h2 style=\"font-size:18px;margin:0 0 12px\">{esc(sentence(content['headline']))}</h2>"
                f"<p><b>What I did.</b> {esc(' '.join(sentence(d) for d in content['did']))}</p>"
                "<p><b>What I found.</b></p><ul style=\"padding-left:18px\">" + "".join(f"<li>{esc(line)}</li>" for line in content["found"]) + "</ul>"
                + "".join(f"<div style=\"margin:8px 0\"><img src=\"cid:{esc(f['content_id'])}\" alt=\"{esc(f.get('caption') or f['filename'])}\" width=\"560\" "
                          f"style=\"max-width:100%;border:1px solid #ccc\"><div style=\"font-size:12px;color:#555\">{esc(f.get('caption') or f['filename'])}</div></div>"
                          for f in frames)
                + f"<p><b>What's next.</b> {esc(' '.join(sentence(n) for n in content['next']))}</p>"
                f"<p><b>What I need from you.</b> {esc(' '.join(sentence(n) for n in content['need']))}</p>"
                + (f"<p style=\"font-size:12px;color:#555\">Attached: {esc(', '.join(f['filename'] for f in content['files']))}.</p>" if content["files"] else "")
                + f"<p style=\"font-size:12px;color:#555\">{esc(name)}" + (f" ({esc(address)})" if address else "") + ", Steward. I report at most once a day, "
                "and only when I have something new.</p></div>")
        text = "\n".join([sentence(content["headline"]), "", "What I did: " + " ".join(sentence(d) for d in content["did"]), "", "What I found:",
                          *[f"  - {line}" for line in content["found"]], "", "What's next: " + " ".join(sentence(n) for n in content["next"]), "",
                          "What I need from you: " + " ".join(sentence(n) for n in content["need"]), "",
                          *(["Attached: " + ", ".join(f["filename"] for f in content["files"]), ""] if content["files"] else []),
                          f"{name}" + (f" ({address})" if address else "") + ", Steward"])
        return html, text

    def prepare_report(self, agent: str, since: datetime, moment: datetime, content: dict | None = None) -> dict | None:
        """Record one play report and email it from the agent's own identity when the owner channel allows (else dry_run)."""
        site = site_of(agent)
        content = content or self.report_content(agent, since, moment)
        if not content:
            return None
        with self.lock:
            blockers = self.sender_blockers(agent)
            track = "dry" if blockers else "live"
            report_id = uid("arp")
            html, text = self.report_body(agent, site, content)
            subject = f"[{site_name(site) or site}] {role_title(agent)}: {content['headline']}"
            files_meta, path_name, pdf_meta = [], None, None
            for item in content["files"]:
                url = item.get("url")
                if item.get("kind") == "snapshot":
                    path_name = f"{report_id}.pdf"
                    (self.directory / path_name).write_bytes(item["bytes"])
                    url = f"/api/owner/reports/{report_id}.pdf"
                    pdf_meta = dict(filename=item["filename"], size=item["size"], url=url)
                files_meta.append(dict(filename=item["filename"], contentType=item["content_type"], size=item.get("size"), url=url))
            record = dict(id=report_id, agentId=agent, agentName=display_name(agent), role=role_title(agent), siteId=site, siteName=site_name(site),
                          at=stamp(moment), since=stamp(since), track=track, headline=clean(content["headline"]), subject=clean(subject)[:300], html=html,
                          text=text, sections=dict(did=content["did"], found=content["found"], next=content["next"], need=content["need"]),
                          counts=content.get("counts") or {}, links={k: v for k, v in (content.get("links") or {}).items() if v}, attachments=files_meta,
                          pdf=pdf_meta, _path=path_name, email=None, liveAt=None if blockers else now(), synthetic=True)
            self.store.put("agent_report", record, site)
        attachments = [{k: v for k, v in item.items() if k != "bytes"} for item in content["files"]]
        mode, provider_ref, why, outbox_id = "dry_run", None, "; ".join(blockers) or None, None
        if not blockers:
            mode, provider_ref, why, outbox_id = self._send(agent, site, record, attachments, kind="agent_report", property_id=site)
        with self.lock:
            record = self.store.get("agent_report", report_id, site) or record
            record["email"] = self._live(self._email_record(agent, mode, record, attachments, provider_ref, why, outbox_id))
            self.store.put("agent_report", record, site)
            self._prune("agent_report", KEEP_REPORTS)
        return record

    # ---- status ---------------------------------------------------------------------------------------------------------

    def schedule(self, moment: datetime | None = None) -> dict:
        moment = moment or utcnow()
        blockers = self.sender_blockers(DIRECTOR)
        track = "dry" if blockers else "live"
        last = self.baseline(track)
        last_at = parse_time((last or {}).get("at"))
        sent = self._recent("owner_digest", 24, moment, "json_extract(body, '$.liveAt') IS NOT NULL")
        reports = self._recent("agent_report", 24, moment, "json_extract(body, '$.liveAt') IS NOT NULL")
        return dict(enabled=self.enabled(), live=not blockers, blockers=blockers, ownerTo=mask_email(self.comms.owner_email()), timeZone=clean_env("STEWARD_OWNER_TIMEZONE", "UTC") or "UTC",
                    digest=dict(everyHours=every_hours(), perDay=digests_per_day(), minGapMinutes=digest_min_gap_minutes(), sentLast24h=len(sent),
                                lastAt=stamp(last_at), nextScheduledAt=stamp(last_at + timedelta(hours=every_hours())) if last_at else None,
                                fromAddress=email_for(DIRECTOR)),
                    reports=dict(perAgentPerDay=reports_per_agent(), perDay=reports_per_day(), minGapMinutes=report_min_gap_minutes(), sentLast24h=len(reports)),
                    lastTickAt=self.last_tick_at)

    def digests_view(self, limit: int = 20) -> dict:
        limit = max(1, min(int(limit), 100))
        digests = query(self.store, "owner_digest", order="json_extract(body, '$.at') DESC", limit=limit)
        reports = query(self.store, "agent_report", order="json_extract(body, '$.at') DESC", limit=limit)
        return dict(schedule=self.schedule(), digests=digests, reports=reports)
