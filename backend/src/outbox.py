"""The outbox (contract 8 §2): one paced queue for everything that reaches a person (the owner, the contractor, an employee),
emails, texts and phone calls, plus capped agent-to-agent mail.

Every real person-facing email, text and call in the backend goes through here. The producer enqueues; the outbox decides
when it goes out and sends it with the provider's own gates:

- one person email every `STEWARD_OUTBOX_EMAIL_GAP_SECONDS` (120), one text every `STEWARD_OUTBOX_SMS_GAP_SECONDS` (120), one
  call every `STEWARD_OUTBOX_CALL_GAP_SECONDS` (120) counted from the end of the previous call, never two calls at once (the
  line is busy until the phone call record is terminal);
- nothing person-facing in the first `STEWARD_OUTBOX_BOOT_GRACE_SECONDS` (180) after the backend starts;
- at most `STEWARD_OUTBOX_EMAILS_PER_DAY` (20), `STEWARD_OUTBOX_CALLS_PER_DAY` (8) and `STEWARD_OUTBOX_SMS_PER_DAY` (10) real
  sends in a rolling 24 h; beyond that an item is `capped` with the reason and never sent later;
- agent-to-agent mail (`internal_email`) is not paced, at most `STEWARD_OUTBOX_INTERNAL_EMAILS_PER_HOUR` (20) an hour.

Order: priority (lower first), then enqueue time; `not_before` delays one item; `dedupe_key` within 24 h returns the existing
item. When a gate fails (the switch is off, the address is not allowlisted, no Inkbox identity) the item is `dry_run` at once
with its full content, not paced. Pacing is persisted in the store, so a restart keeps it; items left `sending` go back to
`queued` at startup. With the workers off (tests, one-off scripts) the outbox sends at enqueue, unpaced, unless
`STEWARD_OUTBOX_PACE_INLINE=true`; `tick(moment)` is the worker's pass.

Live sequence (demo_sequence.py): items enqueued inside `with outbox.paced_as(run_id)` carry `pace: run_id`. The run spaces them
itself (STEWARD_LIVE_SEQUENCE_GAP_SECONDS), so here they skip the boot grace and the lane gaps (a call still waits for a free line;
the daily caps still apply), and while a run is active every other person-facing item waits so nothing interleaves.

Records: `outbox_item` (the public record; addresses only masked) and `outbox_payload` (the body, HTML and attachments needed to
send later). A producer can ask for its own record to follow the item (`refs.record = {kind, id, propertyId, field}`): when the
item settles, the outbox writes `{mode, providerRef, reason, outboxId, at}` into that record (into `field` when given).
"""
from __future__ import annotations

import base64
import binascii
import contextvars
import json
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .agents import DISPATCH, OPERATOR, OWNER, agent_key, display_name, email_for, handle_for, is_known
from .env import env
from .errors import RealityError
from .providers import (EMAIL_RE, PERSON_ROLES, ProviderNotConfigured, allowed_recipients, clean_env, external_messages_allowed,
                        person_address, person_channel_blockers)
from .sites import SITE_BY_ID, SITE_IDS
from .store import now, uid
from .verify import parse_time

CHANNELS = ("email", "sms", "call", "internal_email")
STATUSES = ("queued", "sending", "sent", "dry_run", "capped", "failed", "canceled")
TERMINAL = ("sent", "dry_run", "capped", "failed", "canceled")
PACED_LANES = ("email", "sms", "call")
ITEM_KIND, PAYLOAD_KIND = "outbox_item", "outbox_payload"
TICK_SECONDS = 5.0
DEDUPE_HOURS = 24
META_LAST = "outbox:last:"  # + lane: when the last real email / text went out
META_CALL_ACTIVE = "outbox:call:active"  # the phone call holding the line
META_CALL_END = "outbox:call:last_end"  # when the last call ended
VOICE_TERMINAL = ("ended", "voicemail", "no_answer", "failed", "dry_run", "capped", "canceled")
MODE_OF = {"queued": "queued", "sending": "queued", "sent": "sent", "dry_run": "dry_run", "capped": "capped", "failed": "failed",
           "canceled": "failed"}
ROLE_WORDS = {"owner": "the owner", "contractor": "the contractor", "employee": "the employee"}
ROLE_NAMES = {"owner": "Owner", "contractor": "Contractor", "employee": "Employee"}
STATUS_WORDS = {"queued": "queued", "sending": "sending", "sent": "sent", "dry_run": "prepared, not sent", "capped": "held by the daily limit",
                "failed": "failed", "canceled": "canceled"}
SETTINGS = {  # name: (env, default, low, high)
    "email_gap": ("STEWARD_OUTBOX_EMAIL_GAP_SECONDS", 120.0, 0.0, 86400.0),
    "sms_gap": ("STEWARD_OUTBOX_SMS_GAP_SECONDS", 120.0, 0.0, 86400.0),
    "call_gap": ("STEWARD_OUTBOX_CALL_GAP_SECONDS", 120.0, 0.0, 86400.0),
    "boot_grace": ("STEWARD_OUTBOX_BOOT_GRACE_SECONDS", 180.0, 0.0, 86400.0),
    "email_day": ("STEWARD_OUTBOX_EMAILS_PER_DAY", 20.0, 0.0, 10000.0),
    "sms_day": ("STEWARD_OUTBOX_SMS_PER_DAY", 10.0, 0.0, 10000.0),
    "call_day": ("STEWARD_OUTBOX_CALLS_PER_DAY", 8.0, 0.0, 10000.0),
    "internal_hour": ("STEWARD_OUTBOX_INTERNAL_EMAILS_PER_HOUR", 20.0, 0.0, 10000.0),
}
MAX_TEXT = 60000
MAX_SMS = 1500
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024


def setting(name: str) -> float:
    key, default, low, high = SETTINGS[name]
    try:
        value = float(env(key, str(default)) or default)
    except (TypeError, ValueError):
        return default
    return min(max(value, low), high)


def _flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    name, domain = value.split("@", 1)
    return f"{name[:1]}•••@{domain}"


def mask_phone(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return f"••• ••• {digits[-4:]}" if len(digits) >= 7 else None


def query(store, kind: str, where: str = "", params: tuple = (), order: str = "", limit: int | None = None) -> list[dict]:
    sql, args = "SELECT body FROM records WHERE kind=?", [kind]
    if where:
        sql, args = sql + f" AND ({where})", args + list(params)
    if order:
        sql += f" ORDER BY {order}"
    if limit:
        sql, args = sql + " LIMIT ?", args + [int(limit)]
    with store.connect() as db:
        return [json.loads(row["body"]) for row in db.execute(sql, args).fetchall()]


def count(store, where: str, params: tuple) -> int:
    with store.connect() as db:
        return int(db.execute(f"SELECT COUNT(*) FROM records WHERE kind=? AND ({where})", (ITEM_KIND, *params)).fetchone()[0])


def lane_of(item: dict) -> str:
    return item.get("channel") or "email"


_PACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("steward_outbox_pace", default=None)


class Outbox:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self.tick_lock = threading.RLock()  # reentrant: a settled call can run a handler that enqueues while a pass runs
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.booted_at = utcnow()
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self._recover()

    @property
    def comms(self):
        return self.service.reality.comms

    # ---- lifecycle ----------------------------------------------------------------------------------------------------

    def paced(self) -> bool:
        return bool(self.service.start_workers) or _flag("STEWARD_OUTBOX_PACE_INLINE")

    def start(self) -> None:
        if not self.service.start_workers or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._loop, name="steward-outbox", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as error:  # the loop must never die
                self.last_error = f"{type(error).__name__}: {str(error)[:200]}"
                self.store.event(SITE_IDS[0], "director", "outbox.failed", "Outbox pass failed", self.last_error)
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    def _recover(self) -> None:
        """Items a stopped process left `sending` go back to `queued` (the provider's idempotency key makes a resend safe). A call
        that was already placed is `sent`."""
        for item in query(self.store, ITEM_KIND, "json_extract(body, '$.status') = 'sending'"):
            call = self._voice_record(item.get("phoneCallId")) if item.get("channel") == "call" else None
            if call and call.get("providerCallId"):
                item.update(status="sent", providerRef=call["providerCallId"], sentAt=item.get("sentAt") or now())
            else:
                item.update(status="queued", reason="back in the queue after a restart")
            self.store.put(ITEM_KIND, item, "")

    # ---- enqueue ------------------------------------------------------------------------------------------------------

    @contextmanager
    def paced_as(self, run_id: str):
        """Items enqueued inside this block belong to the live sequence run `run_id` (see the module docstring)."""
        token = _PACE.set(run_id)
        try:
            yield
        finally:
            _PACE.reset(token)

    def _sequence_active(self) -> bool:
        sequence = getattr(self.service, "sequence", None)
        try:
            return bool(sequence is not None and sequence.active())
        except Exception:  # the outbox never depends on the sequence working
            return False

    def email(self, *, sender: str, to_role: str, subject: str, text: str, html: str | None = None,
              attachments: list[dict] | None = None, cc: list[str] | None = None, site_id: str | None = None,
              purpose: str, refs: dict | None = None, dedupe_key: str | None = None, priority: int = 5,
              not_before: str | None = None, idempotency_key: str | None = None) -> dict:
        """Queue an email from `sender`'s own identity to a person role. Returns the outbox item."""
        self._check_agent(sender, "sender")
        role = self._check_role(to_role)
        subject, text = self._text(subject, 300, "subject"), self._text(text, MAX_TEXT, "text")
        files = self._attachments(attachments)
        copies = self._cc(cc, exclude=role)
        site = self._site(site_id)
        existing = self._existing(dedupe_key)
        if existing:
            return existing
        blockers = self._sender_blockers(sender) + person_channel_blockers(role, "email")
        item = self._new("email", purpose, sender, site, refs, priority, dedupe_key, not_before, idempotency_key, toRole=role,
                         to=mask_email(person_address(role, "email")) or ROLE_WORDS[role], cc=copies, subject=subject,
                         preview=self._preview(text), attachments=[self._file_meta(f) for f in files])
        payload = dict(id=item["id"], text=text, html=html or None, attachments=files, cc=[c["id"] for c in copies])
        return self._enqueue(item, payload, blockers)

    def sms(self, *, sender: str, to_role: str, text: str, site_id: str | None = None, purpose: str, refs: dict | None = None,
            dedupe_key: str | None = None, priority: int = 5, not_before: str | None = None, gate: str = "person",
            idempotency_key: str | None = None) -> dict:
        """Queue a text from the dispatch line to a person role. `gate`: `person` (the person channel, STEWARD_ALLOW_OWNER_ALERTS)
        or `external` (the general switch STEWARD_ALLOW_EXTERNAL_MESSAGES, for the duty engineer's notices and decision texts)."""
        self._check_agent(sender, "sender", allow_dispatch=True)
        role = self._check_role(to_role)
        if gate not in ("person", "external"):
            raise ValueError("gate is person or external.")
        text = self._text(text, MAX_SMS, "text")
        site = self._site(site_id)
        existing = self._existing(dedupe_key)
        if existing:
            return existing
        # The old external path (notices, decision texts) keeps its own checks: the provider refuses when the line is not set up.
        blockers = (self._line_blockers() if gate == "person" else []) + self._sms_blockers(role, gate)
        item = self._new("sms", purpose, sender, site, refs, priority, dedupe_key, not_before, idempotency_key, toRole=role,
                         to=mask_phone(person_address(role, "phone")) or ROLE_WORDS[role], cc=[], subject=None, preview=self._preview(text),
                         attachments=[], gate=gate)
        return self._enqueue(item, dict(id=item["id"], text=text), blockers)

    def call(self, *, phone_call_id: str, site_id: str | None, purpose: str, priority: int = 5,
             not_before: str | None = None, dedupe_key: str | None = None) -> dict:
        """Queue a phone call prepared by VoiceCalls (the record holds the brief); the outbox decides when the line is free and
        calls `voice_calls.place()`."""
        call = self._voice_record(phone_call_id)
        if not call:
            raise RealityError("Phone call not found.", "NOT_FOUND", "Prepare the call with voice_calls.request().", 404)
        role = self._check_role(call.get("calleeRole") or "")
        site = self._site(site_id or call.get("siteId"))
        existing = self._existing(dedupe_key)
        if existing:
            return existing
        blockers = self._line_blockers() + person_channel_blockers(role, "call")
        item = self._new("call", purpose, call.get("caller") or DISPATCH, site, dict(phoneCallId=phone_call_id), priority, dedupe_key, not_before,
                         None, toRole=role, to=mask_phone(person_address(role, "phone")) or ROLE_WORDS[role], cc=[], subject=None,
                         preview=self._preview(call.get("goal") or ""), attachments=[], phoneCallId=phone_call_id)
        return self._enqueue(item, dict(id=item["id"]), blockers)

    def internal_email(self, *, sender: str, to_agent: str, subject: str, text: str, html: str | None = None,
                       attachments: list[dict] | None = None, cc: list[str] | None = None, site_id: str | None = None,
                       purpose: str, refs: dict | None = None, dedupe_key: str | None = None) -> dict:
        """Queue agent-to-agent mail between Steward identity mailboxes: not paced, capped per hour, never to a person."""
        self._check_agent(sender, "sender")
        self._check_agent(to_agent, "to_agent")
        if to_agent == sender:
            raise ValueError("An agent cannot email itself.")
        subject, text = self._text(subject, 300, "subject"), self._text(text, MAX_TEXT, "text")
        files = self._attachments(attachments)
        copies = [c for c in self._cc(cc, exclude=None) if c["kind"] == "agent" and c["id"] not in (sender, to_agent)]
        if any((entry or "").strip() in PERSON_ROLES for entry in cc or []):
            raise ValueError("Internal mail copies Steward agents only.")
        site = self._site(site_id)
        existing = self._existing(dedupe_key)
        if existing:
            return existing
        blockers = self._sender_blockers(sender) + self._internal_blockers(to_agent)
        item = self._new("internal_email", purpose, sender, site, refs, 5, dedupe_key, None, None, toAgent=to_agent, toName=display_name(to_agent),
                         to=email_for(to_agent), cc=copies, subject=subject, preview=self._preview(text),
                         attachments=[self._file_meta(f) for f in files])
        payload = dict(id=item["id"], text=text, html=html or None, attachments=files, cc=[c["id"] for c in copies])
        return self._enqueue(item, payload, blockers)

    # ---- reading ------------------------------------------------------------------------------------------------------

    @staticmethod
    def public(item: dict) -> dict:
        return {key: value for key, value in item.items() if not key.startswith("_")}

    def get(self, item_id: str) -> dict:
        item = self.store.get(ITEM_KIND, item_id, "")
        if not item:
            raise RealityError("Outbox item not found.", "NOT_FOUND", "List them with GET /api/outbox.", 404)
        return self.public(item)

    def list(self, *, status: str | None = None, channel: str | None = None, site_id: str | None = None, limit: int = 50) -> list[dict]:
        clauses, params = [], []
        if status:
            wanted = [s.strip() for s in str(status).split(",") if s.strip()]
            unknown = [s for s in wanted if s not in STATUSES]
            if unknown:
                raise RealityError(f"Unknown status '{unknown[0][:30]}'.", "INVALID_REQUEST", "Statuses: " + ", ".join(STATUSES) + ".")
            clauses.append("json_extract(body, '$.status') IN (" + ",".join("?" for _ in wanted) + ")")
            params += wanted
        if channel:
            if channel not in CHANNELS:
                raise RealityError(f"Unknown channel '{channel[:30]}'.", "INVALID_REQUEST", "Channels: " + ", ".join(CHANNELS) + ".")
            clauses.append("json_extract(body, '$.channel') = ?")
            params.append(channel)
        if site_id:
            clauses.append("json_extract(body, '$.siteId') = ?")
            params.append(site_id)
        limit = max(1, min(int(limit or 50), 500))
        rows = query(self.store, ITEM_KIND, " AND ".join(clauses), tuple(params), order="json_extract(body, '$.enqueuedAt') DESC, rowid DESC",
                     limit=limit)
        return [self.public(item) for item in rows]

    def status(self, moment: datetime | None = None) -> dict:
        moment = moment or utcnow()
        paced = self.paced()
        queued = query(self.store, ITEM_KIND, "json_extract(body, '$.status') IN ('queued', 'sending')")
        grace_end = self.booted_at + timedelta(seconds=setting("boot_grace")) if paced else None
        lanes = {}
        for lane, gap, per_day in (("email", "email_gap", "email_day"), ("sms", "sms_gap", "sms_day"), ("call", "call_gap", "call_day")):
            waiting = sorted((i for i in queued if lane_of(i) == lane), key=lambda i: (i.get("priority", 5), i.get("enqueuedAt") or ""))
            info = dict(gapSeconds=setting(gap), perDay=int(setting(per_day)), sentLast24h=self._sent(lane, moment, hours=24),
                        queued=len(waiting), nextItemId=waiting[0]["id"] if waiting else None)
            if lane == "call":
                busy, last_end = self._line(moment)
                info.update(activeCallId=self.store.meta(META_CALL_ACTIVE) or None, lineBusy=busy, lastEndedAt=stamp(last_end))
                nxt = last_end + timedelta(seconds=setting(gap)) if last_end else None
            else:
                last = parse_time(self.store.meta(META_LAST + lane) or "")
                info["lastSentAt"] = stamp(last)
                nxt = last + timedelta(seconds=setting(gap)) if last else None
            if paced and grace_end and (nxt is None or nxt < grace_end) and grace_end > moment:
                nxt = grace_end
            info["nextAt"] = stamp(nxt) if waiting and nxt and nxt > moment else (stamp(moment) if waiting else None)
            lanes[lane] = info
        lanes["internal_email"] = dict(perHour=int(setting("internal_hour")), sentLastHour=self._sent("internal_email", moment, hours=1),
                                       queued=len([i for i in queued if lane_of(i) == "internal_email"]))
        roles = {role: dict(email=not person_channel_blockers(role, "email"), phone=not person_channel_blockers(role, "call"),
                            emailTo=mask_email(person_address(role, "email")), phoneTo=mask_phone(person_address(role, "phone")))
                 for role in PERSON_ROLES}
        return dict(at=stamp(moment), state="on" if self.service.start_workers else "inline", paced=paced, tickSeconds=TICK_SECONDS,
                    bootedAt=stamp(self.booted_at), bootGraceSeconds=setting("boot_grace"),
                    bootGraceUntil=stamp(grace_end) if grace_end and grace_end > moment else None,
                    nextEmailAt=lanes["email"]["nextAt"], nextCallAt=lanes["call"]["nextAt"], nextSmsAt=lanes["sms"]["nextAt"],
                    lineBusy=lanes["call"]["lineBusy"], activeCallId=lanes["call"]["activeCallId"],
                    queued=dict(emails=lanes["email"]["queued"], calls=lanes["call"]["queued"], sms=lanes["sms"]["queued"]),
                    sentToday=dict(emails=lanes["email"]["sentLast24h"], calls=lanes["call"]["sentLast24h"], sms=lanes["sms"]["sentLast24h"]),
                    caps=dict(emailsPerDay=lanes["email"]["perDay"], callsPerDay=lanes["call"]["perDay"], smsPerDay=lanes["sms"]["perDay"],
                              emailGapSeconds=lanes["email"]["gapSeconds"], callGapSeconds=lanes["call"]["gapSeconds"],
                              smsGapSeconds=lanes["sms"]["gapSeconds"], internalEmailsPerHour=lanes["internal_email"]["perHour"]),
                    lanes=lanes, roles=roles, personChannelLive=not person_channel_blockers("owner", "email"),
                    lastTickAt=self.last_tick_at, lastError=self.last_error)

    def cancel(self, item_id: str, reason: str) -> dict:
        with self.lock:
            item = self.store.get(ITEM_KIND, item_id, "")
            if not item:
                raise RealityError("Outbox item not found.", "NOT_FOUND", "List them with GET /api/outbox.", 404)
            if item["status"] != "queued":
                raise RealityError(f"Only queued items can be canceled; this one is {item['status']}.", "INVALID_REQUEST", "Pick a queued item.", 409)
            return self._settle(item, "canceled", reason=(reason or "canceled")[:300])

    # ---- the pass -----------------------------------------------------------------------------------------------------

    def tick(self, moment: datetime | None = None) -> list[dict]:
        """One pass: in each lane, the next due item goes out (paced: at most one per lane per pass; unpaced: every due item)."""
        moment = moment or utcnow()
        changed: list[dict] = []
        with self.tick_lock:
            self.last_tick_at = stamp(moment)
            paced = self.paced()
            lanes: dict[str, list[dict]] = {}
            for item in query(self.store, ITEM_KIND, "json_extract(body, '$.status') = 'queued'"):
                lanes.setdefault(lane_of(item), []).append(item)
            for lane, items in lanes.items():
                items.sort(key=lambda i: (i.get("priority", 5), i.get("enqueuedAt") or "", i["id"]))
                for item in items:
                    until, lane_wide = self._wait(item, lane, moment, paced)
                    if until is not None:
                        if item.get("earliestAt") != stamp(until):
                            fresh = self.store.get(ITEM_KIND, item["id"], "")
                            if fresh and fresh["status"] == "queued":
                                fresh["earliestAt"] = stamp(until)
                                self.store.put(ITEM_KIND, fresh, "")
                        if lane_wide:
                            break
                        continue
                    result = self._dispatch(item, lane, moment)
                    if result:
                        changed.append(result)
                    if paced and lane in PACED_LANES and result and result.get("status") in ("sent", "failed"):
                        break  # one real attempt per lane per pass
        return changed

    def _wait(self, item: dict, lane: str, moment: datetime, paced: bool) -> tuple[datetime | None, bool]:
        """(when it may go, whether the whole lane waits) or (None, False) when it is due now."""
        not_before = parse_time(item.get("notBefore") or "")
        if not_before and not_before > moment:
            return not_before, False
        if not paced or lane not in PACED_LANES:
            return None, False
        if item.get("pace"):  # a live sequence item: the run spaces it; only a busy line holds a call
            if lane == "call" and self._line(moment)[0]:
                return moment + timedelta(seconds=TICK_SECONDS), True
            return None, False
        if self._sequence_active():  # everything else waits while a live sequence runs
            return moment + timedelta(seconds=TICK_SECONDS), False
        grace_end = self.booted_at + timedelta(seconds=setting("boot_grace"))
        if moment < grace_end:
            return grace_end, True
        if lane == "call":
            busy, last_end = self._line(moment)
            if busy:
                return moment + timedelta(seconds=TICK_SECONDS), True
            gap_end = last_end + timedelta(seconds=setting("call_gap")) if last_end else None
        else:
            last = parse_time(self.store.meta(META_LAST + lane) or "")
            gap_end = last + timedelta(seconds=setting(f"{lane}_gap")) if last else None
        if gap_end and moment < gap_end:
            return gap_end, True
        return None, False

    def _line(self, moment: datetime) -> tuple[bool, datetime | None]:
        """(the line is busy, when the last call ended). The line is busy while the call that holds it is not terminal."""
        active = self.store.meta(META_CALL_ACTIVE) or ""
        if active:
            call = self._voice_record(active)
            if call and call.get("status") not in VOICE_TERMINAL:
                return True, None
            end = parse_time((call or {}).get("endedAt") or "") or moment
            with self.lock:
                if (self.store.meta(META_CALL_ACTIVE) or "") == active:
                    self.store.meta(META_CALL_END, stamp(end))
                    self.store.meta(META_CALL_ACTIVE, "")
        return False, parse_time(self.store.meta(META_CALL_END) or "")

    def _dispatch(self, item: dict, lane: str, moment: datetime) -> dict | None:
        blockers = self._item_blockers(item)
        if blockers:
            return self._settle(item, "dry_run", reason="; ".join(blockers), moment=moment)
        cap = self._cap_reason(lane, moment)
        if cap:
            return self._settle(item, "capped", reason=cap, moment=moment)
        with self.lock:
            fresh = self.store.get(ITEM_KIND, item["id"], "")
            if not fresh or fresh["status"] != "queued":
                return None
            fresh.update(status="sending", attempts=int(fresh.get("attempts") or 0) + 1, earliestAt=None)
            self.store.put(ITEM_KIND, fresh, "")
        payload = self.store.get(PAYLOAD_KIND, fresh["id"], "") or {}
        note = None
        try:
            if lane == "call":
                result = self.service.voice_calls.place(fresh["phoneCallId"]) or {}
                if not result.get("ok"):
                    return self._settle(fresh, "failed", reason=str(result.get("reason") or "the call could not be placed")[:300], moment=moment,
                                        notify_voice=False)
                provider_ref = result.get("providerCallId")
                with self.lock:
                    self.store.meta(META_CALL_ACTIVE, fresh["phoneCallId"])
            elif lane == "sms":
                provider_ref = self._send_sms(fresh, payload)
            else:
                provider_ref, note = self._send_email(fresh, payload, internal=lane == "internal_email")
        except (ProviderNotConfigured, ValueError) as error:
            return self._settle(fresh, "failed", reason=str(error)[:300], moment=moment)
        except Exception as error:  # nothing is reported as delivered
            return self._settle(fresh, "failed", reason=f"Inkbox send failed ({type(error).__name__}); nothing reported as delivered.", moment=moment)
        if lane in ("email", "sms"):
            self.store.meta(META_LAST + lane, stamp(moment))
        return self._settle(fresh, "sent", reason=note, provider_ref=provider_ref, moment=moment)

    def _send_email(self, item: dict, payload: dict, internal: bool = False) -> tuple[str | None, str | None]:
        sender = item["sender"]
        if internal:
            to, role = email_for(item["toAgent"]), None
        else:
            role = item["toRole"]
            to = person_address(role, "email")
        copies, dropped = self._resolve_cc(payload.get("cc") or [], role, internal)
        files = [{k: a[k] for k in ("filename", "content_type", "content_base64", "content_id") if a.get(k)} for a in payload.get("attachments") or []]
        kwargs = dict(html=payload.get("html"), attachments=files or None, sender_handle=handle_for(sender), api_key=agent_key(sender) or None,
                      idempotency_key=item.get("idempotencyKey") or f"steward-{item['id']}")
        if internal:
            kwargs["internal"] = True
        elif role == "owner":
            kwargs["owner_channel"] = True
        else:
            kwargs["person_role"] = role
        if copies:
            kwargs["cc"] = copies
        result = self.comms.send_email(item.get("siteId") or SITE_IDS[0], to, item["subject"], payload.get("text") or item.get("preview") or "", "", **kwargs)
        note = ("Copy not sent to " + ", ".join(dropped) + ".") if dropped else None
        return (result or {}).get("id"), note

    def _send_sms(self, item: dict, payload: dict) -> str | None:
        role = item["toRole"]
        to = person_address(role, "phone")
        key = item.get("idempotencyKey") or f"steward-{item['id']}"
        if item.get("gate") == "external":
            result = self.comms.send_sms(item.get("siteId") or SITE_IDS[0], to, payload.get("text") or "", idempotency_key=key)
        else:
            result = self.comms.send_sms(item.get("siteId") or SITE_IDS[0], to, payload.get("text") or "", idempotency_key=key, person_role=role)
        return (result or {}).get("id")

    def _settle(self, item: dict, status: str, reason: str | None = None, provider_ref: str | None = None, moment: datetime | None = None,
                notify_voice: bool = True) -> dict:
        moment = moment or utcnow()
        with self.lock:
            fresh = self.store.get(ITEM_KIND, item["id"], "") or item
            fresh.update(status=status, reason=reason, earliestAt=None, settledAt=stamp(moment))
            if provider_ref:
                fresh["providerRef"] = str(provider_ref)
            if status == "sent":
                fresh["sentAt"] = stamp(moment)
            self.store.put(ITEM_KIND, fresh, "")
        self._change(fresh)
        self._sync(fresh)
        if fresh.get("channel") == "call" and status in ("dry_run", "capped", "failed", "canceled") and notify_voice:
            try:
                self.service.voice_calls.not_placed(fresh["phoneCallId"], status, reason or STATUS_WORDS[status])
            except Exception as error:  # the call record must still settle; never break the pass
                self.store.event(fresh.get("siteId") or SITE_IDS[0], "director", "outbox.voice_failed", "Could not settle a phone call",
                                 f"{type(error).__name__}: {str(error)[:200]}")
        return self.public(fresh)

    # ---- gates and caps -----------------------------------------------------------------------------------------------

    @staticmethod
    def _sender_blockers(sender: str) -> list[str]:
        reasons = []
        if not (agent_key(sender) or clean_env("INKBOX_API_KEY")):
            reasons.append("Inkbox is not configured (INKBOX_API_KEY)")
        if not handle_for(sender):
            reasons.append(f"no Inkbox identity for {display_name(sender)}")
        return reasons

    @staticmethod
    def _line_blockers() -> list[str]:
        reasons = []
        if not clean_env("INKBOX_API_KEY"):
            reasons.append("Inkbox is not configured (INKBOX_API_KEY)")
        if not (clean_env("INKBOX_IDENTITY_DISPATCH") or clean_env("INKBOX_PHONE_IDENTITY")):
            reasons.append("no dispatch line identity (INKBOX_IDENTITY_DISPATCH)")
        return reasons

    @staticmethod
    def _sms_blockers(role: str, gate: str) -> list[str]:
        if gate == "person":
            return person_channel_blockers(role, "sms")
        reasons = []
        if not external_messages_allowed():
            reasons.append("STEWARD_ALLOW_EXTERNAL_MESSAGES is not true")
        phone = person_address(role, "phone")
        if not phone:
            reasons.append(f"no valid phone number for {ROLE_WORDS[role]}")
        elif phone.casefold() not in allowed_recipients():
            reasons.append(f"{ROLE_WORDS[role]}'s phone is not in INKBOX_ALLOWED_RECIPIENTS")
        return reasons

    @staticmethod
    def _internal_blockers(to_agent: str) -> list[str]:
        reasons = []
        if not _flag("STEWARD_ALLOW_AGENT_EMAIL"):
            reasons.append("STEWARD_ALLOW_AGENT_EMAIL is not true")
        if not handle_for(to_agent):
            reasons.append(f"no Inkbox identity for {display_name(to_agent)}")
        return reasons

    def _item_blockers(self, item: dict) -> list[str]:
        """The gates again at send time: a switch turned off while the item waited makes it a dry run."""
        lane = lane_of(item)
        if lane == "email":
            return self._sender_blockers(item["sender"]) + person_channel_blockers(item["toRole"], "email")
        if lane == "sms":
            gate = item.get("gate") or "person"
            return (self._line_blockers() if gate == "person" else []) + self._sms_blockers(item["toRole"], gate)
        if lane == "call":
            return self._line_blockers() + person_channel_blockers(item["toRole"], "call")
        return self._sender_blockers(item["sender"]) + self._internal_blockers(item["toAgent"])

    def _sent(self, lane: str, moment: datetime, hours: float) -> int:
        cutoff = stamp(moment - timedelta(hours=hours))
        return count(self.store, "json_extract(body, '$.channel') = ? AND json_extract(body, '$.status') = 'sent' AND json_extract(body, '$.sentAt') > ?",
                     (lane, cutoff))

    def _cap_reason(self, lane: str, moment: datetime) -> str | None:
        if lane == "internal_email":
            cap, used = int(setting("internal_hour")), self._sent(lane, moment, hours=1)
            return (f"{used} agent emails in the last hour; the cap is STEWARD_OUTBOX_INTERNAL_EMAILS_PER_HOUR={cap}" if used >= cap else None)
        name = {"email": ("email_day", "STEWARD_OUTBOX_EMAILS_PER_DAY", "emails"), "sms": ("sms_day", "STEWARD_OUTBOX_SMS_PER_DAY", "texts"),
                "call": ("call_day", "STEWARD_OUTBOX_CALLS_PER_DAY", "calls")}[lane]
        cap, used = int(setting(name[0])), self._sent(lane, moment, hours=24)
        return f"{used} {name[2]} sent in the last 24 h; the cap is {name[1]}={cap}" if used >= cap else None

    # ---- helpers ------------------------------------------------------------------------------------------------------

    @staticmethod
    def _check_agent(agent: str, field: str, allow_dispatch: bool = False) -> None:
        if not isinstance(agent, str) or not (is_known(agent) or (allow_dispatch and agent == DISPATCH)) or agent in (OPERATOR, OWNER):
            raise ValueError(f"{field} must be a Steward agent with an identity, not {str(agent)[:40]!r}.")

    @staticmethod
    def _check_role(role: str) -> str:
        if role not in PERSON_ROLES:
            raise ValueError(f"to_role must be one of {', '.join(PERSON_ROLES)}, not {str(role)[:40]!r}.")
        return role

    @staticmethod
    def _text(value, limit: int, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required.")
        return text[:limit]

    @staticmethod
    def _preview(text: str) -> str:
        return " ".join(str(text or "").split())[:300]

    def _site(self, site_id: str | None) -> str | None:
        if not site_id:
            return None
        if site_id not in SITE_BY_ID and not self.store.get("property", site_id):
            raise ValueError(f"Unknown site {str(site_id)[:40]!r}.")
        return site_id

    @staticmethod
    def _attachments(attachments: list[dict] | None) -> list[dict]:
        files, total = [], 0
        for item in attachments or []:
            if not isinstance(item, dict) or not item.get("filename") or not item.get("content_type") or not item.get("content_base64"):
                raise ValueError("Each attachment needs filename, content_type and content_base64.")
            try:
                size = int(item.get("size") or len(base64.b64decode(item["content_base64"], validate=False)))
            except (binascii.Error, ValueError, TypeError):
                raise ValueError(f"Attachment {str(item['filename'])[:60]} is not valid base64.")
            total += size
            entry = dict(filename=str(item["filename"])[:180], content_type=str(item["content_type"]), content_base64=item["content_base64"], size=size)
            if item.get("content_id"):
                entry["content_id"] = str(item["content_id"])[:120]
            files.append(entry)
        if total > MAX_ATTACHMENT_BYTES:
            raise ValueError(f"Attachments are {total} bytes; the limit is {MAX_ATTACHMENT_BYTES}.")
        return files

    @staticmethod
    def _file_meta(item: dict) -> dict:
        return dict(filename=item["filename"], contentType=item["content_type"], size=item.get("size"), inline=bool(item.get("content_id")))

    @staticmethod
    def _cc(entries: list[str] | None, exclude: str | None) -> list[dict]:
        """CC entries: Steward agents (their identity mailboxes, internal) or the person roles (gated like `to`)."""
        out, seen = [], set()
        for entry in entries or []:
            value = str(entry or "").strip()
            if not value or value == "none" or value in seen:
                continue
            if value in PERSON_ROLES:
                if value != exclude:
                    out.append(dict(id=value, kind="person", name=ROLE_NAMES[value], address=mask_email(person_address(value, "email"))))
            elif is_known(value) and value not in (OPERATOR, OWNER, DISPATCH):
                out.append(dict(id=value, kind="agent", name=display_name(value), address=email_for(value)))
            else:
                raise ValueError(f"CC may name Steward agents or the owner, contractor or employee; not {value[:60]!r}.")
            seen.add(value)
        return out

    @staticmethod
    def _resolve_cc(ids: list[str], role: str | None, internal: bool) -> tuple[list[str], list[str]]:
        """Addresses for the CC entries at send time, and the names of copies that could not be sent."""
        addresses, dropped = [], []
        for entry in ids:
            if entry in PERSON_ROLES:
                if internal or entry == role:
                    continue
                if person_channel_blockers(entry, "email"):
                    dropped.append(ROLE_WORDS[entry])
                    continue
                addresses.append(person_address(entry, "email"))
            else:
                address = email_for(entry)
                if address:
                    addresses.append(address)
                else:
                    dropped.append(display_name(entry))
        return [a for a in dict.fromkeys(addresses) if a and EMAIL_RE.match(a)], dropped

    def _existing(self, dedupe_key: str | None) -> dict | None:
        if not dedupe_key:
            return None
        cutoff = stamp(utcnow() - timedelta(hours=DEDUPE_HOURS))
        rows = query(self.store, ITEM_KIND, "json_extract(body, '$.dedupeKey') = ? AND json_extract(body, '$.enqueuedAt') > ?", (dedupe_key, cutoff),
                     order="json_extract(body, '$.enqueuedAt') DESC", limit=1)
        return self.public(rows[0]) if rows else None

    def _new(self, channel: str, purpose: str, sender: str, site: str | None, refs: dict | None, priority: int, dedupe_key: str | None,
             not_before: str | None, idempotency_key: str | None, **fields) -> dict:
        if not purpose or not isinstance(purpose, str):
            raise ValueError("purpose is required.")
        if not_before is not None and parse_time(not_before) is None:
            raise ValueError("not_before must be an ISO 8601 time.")
        clean_refs = json.loads(json.dumps(refs or {}, default=str))
        return dict(id=uid("obx"), channel=channel, purpose=purpose[:60], sender=sender, senderName=display_name(sender),
                    fromAddress=email_for(sender) if channel in ("email", "internal_email") else None, siteId=site, refs=clean_refs,
                    priority=max(0, min(int(priority if priority is not None else 5), 9)), dedupeKey=dedupe_key, idempotencyKey=idempotency_key,
                    status="queued", reason=None, enqueuedAt=now(), notBefore=not_before, earliestAt=None, sentAt=None, settledAt=None,
                    providerRef=None, attempts=0, pace=_PACE.get(), **fields)

    def _enqueue(self, item: dict, payload: dict, blockers: list[str]) -> dict:
        self.store.put(PAYLOAD_KIND, payload, "")
        if blockers:
            self.store.put(ITEM_KIND, item, "")
            return self._settle(item, "dry_run", reason="; ".join(blockers))
        self.store.put(ITEM_KIND, item, "")
        self._change(item)
        if not self.paced():
            self.tick()  # workers off: send now, unpaced
        elif item.get("pace"):
            self._wake.set()  # a live sequence item goes on the next pass, not up to TICK_SECONDS later
        return self.get(item["id"])

    def _voice_record(self, call_id: str | None) -> dict | None:
        return self.store.get("phone_call", call_id, "") if call_id else None

    def _sync(self, item: dict) -> None:
        """Write the item's settled state into the producer's own record (`refs.record`)."""
        spec = (item.get("refs") or {}).get("record")
        if not isinstance(spec, dict) or not spec.get("kind") or not spec.get("id"):
            return
        prop = spec.get("propertyId") or ""
        try:
            with self.store.lock:
                record = self.store.get(str(spec["kind"]), str(spec["id"]), prop)
                if not record:
                    return
                patch = dict(mode=MODE_OF.get(item["status"], item["status"]), providerRef=item.get("providerRef"),
                             reason=item.get("reason") if item["status"] != "sent" else None, outboxId=item["id"])
                field = spec.get("field")
                if field:
                    current = record.get(field) if isinstance(record.get(field), dict) else {}
                    if item["status"] == "sent":
                        patch["at"] = item.get("sentAt")
                    record[field] = {**current, **patch}
                else:
                    record.update(patch)
                self.store.put(str(spec["kind"]), record, prop)
        except Exception as error:  # a producer's record must never break the outbox
            self.store.event(item.get("siteId") or SITE_IDS[0], "director", "outbox.sync_failed", "Could not update the producer record",
                             f"{type(error).__name__}: {str(error)[:200]}")

    def _change(self, item: dict) -> None:
        status = item["status"]
        if item["channel"] == "internal_email":
            what = f"Email from {item['senderName']} to {item.get('toName') or item.get('toAgent')}"
        elif item["channel"] == "call":
            what = f"Call from {item['senderName']} to {ROLE_WORDS.get(item.get('toRole'), 'a person')}"
        else:
            word = "Email" if item["channel"] == "email" else "Text"
            what = f"{word} from {item['senderName']} to {ROLE_WORDS.get(item.get('toRole'), 'a person')}"
        detail = f": {item['subject']}" if item.get("subject") else (f": {item['preview'][:120]}" if item.get("preview") else "")
        words = STATUS_WORDS.get(status, status)
        if status == "queued" and item.get("earliestAt"):
            words = f"queued, goes out at {item['earliestAt'][11:16]} UTC"
        summary = f"{what} {words}{detail}"[:480]
        extra = dict(itemId=item["id"], channel=item["channel"], status=status, purpose=item.get("purpose"))
        for site in ([item["siteId"]] if item.get("siteId") else list(SITE_IDS)):
            try:
                self.service.reality.emit_change(site, "outbox", item["id"], summary, extra=extra, fields=extra)
            except Exception:  # an unknown site must never break a send
                continue
