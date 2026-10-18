"""Live HUD over Supabase Realtime Broadcast: private channels `site:<siteId>:hud`, sent only by the backend.

Events: eye_frame (a signed Storage URL, never image bytes), agent_action (telemetry lines), conversation_line and
issue_change. They are coalesced to at most one Broadcast message per second per site, and only while at least one
viewer is present: the frontend module (frontend/src/lib/realtime) posts heartbeats to POST /api/supabase/viewers; no
fresh heartbeat for a site means no broadcasts for it, and events for it are dropped (the dashboard keeps polling).

Cost is counted the way Supabase bills it: a broadcast to N viewers costs 1 + N messages (one sent, one per receiver);
a viewer joining presence costs 2 + N (track, state, diff to everyone), leaving costs N. The budget guard approves every
broadcast first, and the interval stretches as the day's budget is spent (1 s, 2 s past 50 %, 5 s past 75 %; none at 100 %).
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque

from .store import now

HEARTBEAT_SECONDS = 10
STALE_SECONDS = 30
BASE_INTERVAL = 1.0
MAX_PAYLOAD_BYTES = 48 * 1024
MAX_LINES = 16
TEXT_LIMIT = 280
EVENT_TYPES = ("eye_frame", "agent_action", "conversation_line", "issue_change")
VIEWER_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{6,80}$")


def topic_for(site_id: str) -> str:
    return f"site:{site_id}:hud"


def interval_for(fraction: float) -> float | None:
    if fraction >= 1.0:
        return None
    if fraction >= 0.75:
        return BASE_INTERVAL * 5
    if fraction >= 0.5:
        return BASE_INTERVAL * 2
    return BASE_INTERVAL


class Hud:
    def __init__(self, supa, budget, sites, redact=lambda value: value, clock=time.monotonic, on_event=None):
        self.supa = supa
        self.budget = budget
        self.sites = list(sites)
        self.redact = redact
        self.clock = clock
        self.on_event = on_event or (lambda title, detail: None)
        self.lock = threading.Lock()
        self.viewers: dict[str, dict[str, dict]] = {site: {} for site in self.sites}
        self.buffers: dict[str, dict] = {site: self._empty() for site in self.sites}
        self.last_sent: dict[str, float] = {site: 0.0 for site in self.sites}
        self.sent = 0
        self.messages = 0
        self.dropped = 0
        self.failures = 0
        self.conversation_lengths: dict[str, int] = {}
        self._stop = threading.Event()
        self._thread = None

    @staticmethod
    def _empty() -> dict:
        return dict(eye_frame=None, issues={}, lines=deque(maxlen=MAX_LINES))

    # ---- lifecycle --------------------------------------------------------------------------------------------

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="steward-supabase-hud", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _loop(self):
        while not self._stop.wait(0.25):
            try:
                self.tick()
            except Exception as error:  # the HUD must never take the backend down
                self.failures += 1
                self.on_event("Supabase HUD tick failed", type(error).__name__)

    # ---- viewers ----------------------------------------------------------------------------------------------

    def _prune(self, site: str) -> int:
        """Drop stale viewers (charging the presence leave each one caused) and return the fresh count."""
        cutoff = self.clock() - STALE_SECONDS
        entries = self.viewers.setdefault(site, {})
        stale = [vid for vid, entry in entries.items() if entry["seen"] < cutoff]
        for vid in stale:
            entries.pop(vid, None)
            if self.budget is not None:
                self.budget.spend_realtime(len(entries), force=True)
        return len(entries)

    def viewer_count(self, site: str) -> int:
        with self.lock:
            return self._prune(site)

    def heartbeat(self, site: str, viewer_id: str, role: str = "viewer") -> dict:
        """Register or refresh a viewer. Returns whether the browser should hold its Realtime connection open."""
        if site not in self.viewers:
            return dict(realtime=False, reason="unknown site", heartbeatSeconds=HEARTBEAT_SECONDS)
        if not VIEWER_ID_RE.match(viewer_id or ""):
            return dict(realtime=False, reason="viewerId must be 6-80 characters of [A-Za-z0-9_.:-]", heartbeatSeconds=HEARTBEAT_SECONDS)
        role = role if role in ("viewer", "renderer") else "viewer"
        reason = ""
        with self.lock:
            count = self._prune(site)
            entries = self.viewers[site]
            known = viewer_id in entries
            if not self.supa or not self.supa.configured:
                return dict(realtime=False, reason="Supabase is not configured", heartbeatSeconds=HEARTBEAT_SECONDS)
            if not known and self.budget is not None and not self.budget.viewers_ok(count + 1):
                self.budget.refuse("realtime_viewers", f"{count} viewers already on {site}; viewer {viewer_id[:12]} keeps polling.")
                return dict(realtime=False, reason="viewer cap reached; keep polling", heartbeatSeconds=HEARTBEAT_SECONDS)
            if self.budget is not None and not self.budget.realtime_ok((1 if known else 2) + count):  # next broadcast, or the join
                self.budget.refuse("realtime_msgs_day", f"Realtime budget spent; viewer on {site} keeps polling.")
                if known:
                    entries.pop(viewer_id, None)
                return dict(realtime=False, reason="realtime budget spent for today; keep polling", heartbeatSeconds=HEARTBEAT_SECONDS)
            if not known and self.budget is not None:
                self.budget.spend_realtime(2 + count, force=True)  # presence track + state + diff fan-out
            entries[viewer_id] = dict(seen=self.clock(), role=role, since=entries.get(viewer_id, {}).get("since") or now())
            total = sum(len(v) for v in self.viewers.values())
        if self.budget is not None:
            self.budget.note_viewers(total)
        return dict(realtime=True, channel=topic_for(site), event="hud", heartbeatSeconds=HEARTBEAT_SECONDS, staleAfterSeconds=STALE_SECONDS,
                    viewers=len(self.viewers[site]), reason=reason or None)

    def leave(self, site: str, viewer_id: str) -> dict:
        with self.lock:
            entries = self.viewers.get(site, {})
            if entries.pop(viewer_id, None) is not None and self.budget is not None:
                self.budget.spend_realtime(len(entries), force=True)
            return dict(left=True, viewers=len(entries))

    # ---- events -----------------------------------------------------------------------------------------------

    def _text(self, value, limit: int = TEXT_LIMIT):
        if value is None:
            return None
        text = str(self.redact(str(value)))
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def push(self, site: str | None, event: dict) -> bool:
        """Queue an event for a site's next broadcast. Dropped (never queued) while nobody watches that site."""
        if site not in self.buffers or event.get("type") not in EVENT_TYPES:
            return False
        event = {k: (self._text(v, 120 if k == "topic" else TEXT_LIMIT) if k in ("text", "summary", "topic") else v) for k, v in event.items()}
        with self.lock:
            if not self._prune(site):
                self.dropped += 1
                return False
            buffer = self.buffers[site]
            kind = event["type"]
            if kind == "eye_frame":
                buffer["eye_frame"] = event
            elif kind == "issue_change":
                buffer["issues"][event.get("issueId") or "?"] = event
            else:
                buffer["lines"].append(event)
            return True

    def eye_frame(self, frame: dict, url: str | None, thumb_url: str | None):
        pins = [{k: p.get(k) for k in ("assetTag", "x", "y", "distance", "occluded")} for p in (frame.get("visiblePins") or [])[:24] if isinstance(p, dict)]
        self.push(frame.get("siteId"), dict(type="eye_frame", siteId=frame.get("siteId"), frameId=frame.get("id"), seq=frame.get("seq"),
                                             actor=frame.get("actor"), actorName=frame.get("actorName"), action=frame.get("action"),
                                             at=frame.get("at"), url=url or frame.get("url"), thumbUrl=thumb_url, signed=bool(url),
                                             camera=frame.get("camera"), visiblePins=pins))

    def telemetry(self, row: dict):
        detail = row.get("detail") or ""
        text = " ".join(part for part in (row.get("tool") or row.get("kind") or "", str(detail)) if part).strip()
        self.push(row.get("siteId") or row.get("site_id"), dict(type="agent_action", agentId=row.get("agentId") or row.get("agent_id"),
                                                               kind=row.get("kind"), tool=row.get("tool"), text=self._text(text), tokens=row.get("tokens"),
                                                               ok=row.get("ok"), at=row.get("at")))

    def conversation(self, conversation: dict):
        transcript = conversation.get("transcript") or []
        key = conversation.get("id") or ""
        seen = self.conversation_lengths.get(key, 0)
        fresh = transcript[seen:] if len(transcript) >= seen else transcript[-1:]
        self.conversation_lengths[key] = len(transcript)
        if len(self.conversation_lengths) > 500:
            for old in list(self.conversation_lengths)[:100]:
                self.conversation_lengths.pop(old, None)
        for line in fresh[-4:]:
            if not isinstance(line, dict):
                continue
            for site in conversation.get("siteIds") or []:
                self.push(site, dict(type="conversation_line", conversationId=key, kind=conversation.get("kind"), topic=self._text(conversation.get("topic"), 120),
                                     speaker=line.get("speaker") or line.get("name"), text=self._text(line.get("text")), at=line.get("at"),
                                     siteIds=conversation.get("siteIds")))

    def issue(self, issue: dict):
        self.push(issue.get("siteId"), dict(type="issue_change", issueId=issue.get("id"), siteId=issue.get("siteId"), kind=issue.get("kind"),
                                            severity=issue.get("severity"), status=issue.get("status"), summary=self._text(issue.get("summary")),
                                            assetTag=issue.get("assetTag"), at=issue.get("updatedAt") or issue.get("at")))

    # ---- sending ----------------------------------------------------------------------------------------------

    def _take(self, site: str) -> list[dict]:
        buffer = self.buffers[site]
        events = list(buffer["lines"])
        events += list(buffer["issues"].values())
        if buffer["eye_frame"]:
            events.append(buffer["eye_frame"])
        self.buffers[site] = self._empty()
        return events

    def tick(self):
        if not self.supa or not self.supa.configured:
            return
        fraction = self.budget.realtime_fraction() if self.budget is not None else 0.0
        interval = interval_for(fraction)
        for site in self.sites:
            with self.lock:
                viewers = self._prune(site)
                due = interval is not None and self.clock() - self.last_sent[site] >= interval
                buffer = self.buffers[site]
                pending = bool(buffer["lines"] or buffer["issues"] or buffer["eye_frame"])
                if not pending or not due or not viewers:
                    if pending and (not viewers or interval is None):
                        self.buffers[site] = self._empty()
                        self.dropped += 1
                    continue
                events = self._take(site)
                self.last_sent[site] = self.clock()
            self.send(site, events, viewers)

    def send(self, site: str, events: list[dict], viewers: int) -> bool:
        payload = dict(siteId=site, at=now(), events=events)
        body = json.dumps(payload, ensure_ascii=False, default=str)
        while len(body.encode()) > MAX_PAYLOAD_BYTES and len(payload["events"]) > 1:
            payload["events"] = payload["events"][1:]
            body = json.dumps(payload, ensure_ascii=False, default=str)
        cost = 1 + viewers
        if self.budget is not None:
            if not self.budget.spend_realtime(cost):
                self.budget.refuse("realtime_msgs_day" if self.budget.counter("realtime_msgs", "day") + cost > self.budget.cap("realtime_msgs_day")
                                   else "realtime_msgs_month", f"HUD broadcast to {viewers} viewer(s) on {site} skipped; dashboards keep polling.")
                self.dropped += 1
                return False
            if not self.budget.spend_egress(len(body.encode()) * viewers):
                self.budget.refuse("egress_mb_day", f"HUD broadcast on {site} skipped: egress budget spent.")
                self.dropped += 1
                return False
        try:
            self.supa.broadcast([dict(topic=topic_for(site), event="hud", payload=payload, private=True)])
        except Exception as error:
            self.failures += 1
            self.on_event("Supabase HUD broadcast failed", f"{type(error).__name__}: {str(error)[:200]}")
            return False
        self.sent += 1
        self.messages += cost
        return True

    def status(self) -> dict:
        with self.lock:
            viewers = {site: self._prune(site) for site in self.sites}
        return dict(viewers=viewers, broadcasts=self.sent, messagesCounted=self.messages, dropped=self.dropped, failures=self.failures,
                    channelPattern="site:<siteId>:hud", event="hud", private=True)
