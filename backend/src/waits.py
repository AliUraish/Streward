"""Waiting without tokens (contract 3 §7).

`POST /api/waits {siteId?, event, filter?}` registers a wait; `GET /api/waits/{waitId}?timeout=<s>` long-polls (max
300 s) and returns `{status: "fired", event}` the moment a matching Change lands, or `{status: "still_waiting",
waitId}` on timeout. The hub is event driven: `RealityService.emit_change` calls `on_change` for every Change; a
match fires the wait (persisted, so a fired wait survives a reconnect) and wakes the long-poll through an
`asyncio.Event` set with `loop.call_soon_threadsafe`. Nothing polls the database while a request is held.

Event mapping: `work_item.resolved` (Change `work_item` whose item is resolved), `issue.changed` (`issue`),
`reply.received` (`reply`), `board.resolved` (a meeting `conversation` that ended), `scenario.step` (`scenario`),
`conversation.ended`, `fix.step` (fix workflow steps), `eye.frame` (an agent-eye frame landed), `any` (every Change). `filter` keys match the Change fields and the event extras (assetTag, issueId, kind, status,
scenarioId, runId, workItemId, ...), case-sensitively.
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone

from .errors import RealityError
from .store import now, uid
from .verify import iso, parse_time

EVENTS = ("work_item.resolved", "issue.changed", "reply.received", "board.resolved", "scenario.step", "conversation.ended", "fix.step",
          "eye.frame", "any")
MAX_TIMEOUT_SECONDS = 300
WAIT_TTL = timedelta(hours=6)


def events_for(change: dict, work_item: dict | None, extra: dict) -> list[str]:
    names = ["any"]
    kind = change.get("type")
    if kind == "work_item" and (work_item or {}).get("state") == "resolved":
        names.append("work_item.resolved")
    elif kind == "issue":
        names.append("issue.changed")
    elif kind == "reply":
        names.append("reply.received")
    elif kind == "board_meeting" and extra.get("status") == "resolved":
        names.append("board.resolved")
    elif kind == "conversation" and extra.get("status") == "ended":
        names.append("conversation.ended")
        if extra.get("kind") == "meeting":
            names.append("board.resolved")
    elif kind == "scenario":
        names.append("scenario.step")
    elif kind == "fix":
        names.append("fix.step")
    elif kind == "eye" and extra.get("frameId"):
        names.append("eye.frame")
    return names


class WaitHub:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.Lock()
        self.active: dict[str, dict] = {w["id"]: w for w in self.store.all("wait", "") if w["status"] == "waiting"}
        self.waiters: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}

    def create(self, event: str, site_id: str | None = None, filter_: dict | None = None, actor: str = "operator") -> dict:
        if event not in EVENTS:
            raise RealityError(f"event must be one of: {', '.join(EVENTS)}.", "INVALID_REQUEST", "Pick a supported event.")
        if site_id:
            self.service.require_property(site_id)
        clean_filter = {}
        for key, value in (filter_ or {}).items():
            if not isinstance(key, str) or len(key) > 40 or not isinstance(value, (str, int, float, bool)):
                raise RealityError("filter must be a flat object of scalar values.", "INVALID_REQUEST", 'Example: {"assetTag": "PG-601"}.')
            clean_filter[key] = value
        wait = dict(id=uid("wait"), siteId=site_id, event=event, filter=clean_filter, status="waiting", createdBy=actor, createdAt=now(),
                    expiresAt=iso(datetime.now(timezone.utc) + WAIT_TTL), firedAt=None, firedEvent=None)
        with self.lock:
            self.store.put("wait", wait, "")
            self.active[wait["id"]] = wait
        return wait

    def get(self, wait_id: str) -> dict:
        wait = self.store.get("wait", wait_id, "")
        if not wait:
            raise RealityError("Wait not found.", "NOT_FOUND", "Create one with POST /api/waits.", 404)
        return wait

    @staticmethod
    def matches(wait: dict, change: dict, names: list[str], payload: dict) -> bool:
        if wait["event"] not in names:
            return False
        if wait.get("siteId") and change.get("propertyId") != wait["siteId"]:
            return False
        return all(payload.get(key) == value for key, value in (wait.get("filter") or {}).items())

    def on_change(self, change: dict, work_item: dict | None, extra: dict) -> None:
        names = events_for(change, work_item, extra)
        payload = {**change, **{k: v for k, v in extra.items() if v is not None}}
        if work_item:
            payload.setdefault("workItemId", work_item.get("id"))
            payload.setdefault("state", work_item.get("state"))
        moment = datetime.now(timezone.utc)
        fired = []
        with self.lock:
            for wait_id, wait in list(self.active.items()):
                expires = parse_time(wait.get("expiresAt"))
                if expires and expires < moment:
                    wait.update(status="expired")
                    self.store.put("wait", wait, "")
                    self.active.pop(wait_id, None)
                    continue
                if not self.matches(wait, change, names, payload):
                    continue
                event_name = wait["event"] if wait["event"] != "any" else (names[1] if len(names) > 1 else "any")
                wait.update(status="fired", firedAt=now(), firedEvent=dict(name=event_name, change=change,
                                                                           extra={k: v for k, v in extra.items() if v is not None}))
                self.store.put("wait", wait, "")
                self.active.pop(wait_id, None)
                fired.append(wait_id)
            wake = [(loop, event) for wait_id in fired for loop, event in self.waiters.pop(wait_id, [])]
        for loop, event in wake:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass

    @staticmethod
    def result(wait: dict) -> dict:
        if wait["status"] == "fired":
            return dict(status="fired", waitId=wait["id"], event=wait["firedEvent"], firedAt=wait["firedAt"])
        if wait["status"] == "expired":
            return dict(status="expired", waitId=wait["id"], detail="The wait expired; create a new one.")
        return dict(status="still_waiting", waitId=wait["id"], event=wait["event"],
                    instruction="Call again with the same waitId; no tokens are spent while waiting.")

    async def wait(self, wait_id: str, timeout: float) -> dict:
        if not 0 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise RealityError(f"timeout must be between 0 and {MAX_TIMEOUT_SECONDS} seconds.", "INVALID_REQUEST", "Pass ?timeout=60 for example.")
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        with self.lock:
            wait = self.store.get("wait", wait_id, "")
            if not wait:
                raise RealityError("Wait not found.", "NOT_FOUND", "Create one with POST /api/waits.", 404)
            if wait["status"] != "waiting":
                return self.result(wait)
            self.waiters.setdefault(wait_id, []).append((loop, event))
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            with self.lock:
                remaining = [(l, e) for l, e in self.waiters.get(wait_id, []) if e is not event]
                if remaining:
                    self.waiters[wait_id] = remaining
                else:
                    self.waiters.pop(wait_id, None)
        return self.result(self.get(wait_id))
