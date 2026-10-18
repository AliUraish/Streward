"""Drain the Supabase inbox queue (`inkbox_inbound`, pgmq) into the backend's own Inkbox webhook route.

The Edge Function supabase/functions/inkbox-inbox verifies each Inkbox webhook (HMAC-SHA256 over
request_id.timestamp.body), deduplicates on the envelope id and enqueues the exact request: the raw body bytes (base64)
and the X-Inkbox-* signature headers. Every 5 s while the backend runs, this drainer reads up to 10 messages through
the service-only RPC wrappers, replays each one through POST /api/inbound/inkbox in process (so it takes exactly the
path a direct webhook takes, signature check included), and archives it. A message that fails five reads is archived
as poison and announced; 5xx answers are retried after the 60 s visibility timeout.
"""
from __future__ import annotations

import asyncio
import base64
import threading
import time

import httpx

DRAIN_SECONDS = 5
BATCH = 10
VISIBILITY_SECONDS = 60
POISON_READS = 5
STATS_SECONDS = 60
FORWARDED_HEADERS = ("x-inkbox-signature", "x-inkbox-request-id", "x-inkbox-timestamp", "content-type", "user-agent")


class InboxDrainer:
    def __init__(self, supa, app, budget, on_event=None, interval: float = DRAIN_SECONDS):
        self.supa = supa
        self.app = app
        self.budget = budget
        self.on_event = on_event or (lambda title, detail: None)
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.processed = 0
        self.archived = 0
        self.poisoned = 0
        self.failures = 0
        self.last_stats: dict | None = None
        self._stats_at = 0.0
        self.last_error: str | None = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="steward-supabase-inbox", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.drain()
            except Exception as error:  # a broken queue must never take the backend down
                self.failures += 1
                self.last_error = f"{type(error).__name__}: {str(error)[:200]}"
            try:
                self.refresh_stats()
            except Exception:
                pass

    def refresh_stats(self, force: bool = False) -> dict | None:
        if not force and time.monotonic() - self._stats_at < STATS_SECONDS:
            return self.last_stats
        stats = self.supa.rpc("inkbox_inbox_stats")
        self._stats_at = time.monotonic()
        if isinstance(stats, dict):
            self.last_stats = stats
            if stats.get("day") is not None:
                self.budget.set_edge_calls(str(stats["day"]), int(stats.get("callsToday") or 0))
        return self.last_stats

    def replay(self, message: dict) -> httpx.Response:
        raw = base64.b64decode(message.get("rawB64") or "")
        headers = {k: v for k, v in (message.get("headers") or {}).items() if k.lower() in FORWARDED_HEADERS and isinstance(v, str)}
        headers.setdefault("content-type", "application/json")
        headers["x-steward-relay"] = "supabase-inbox"

        async def call():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://steward.internal", timeout=60) as client:
                return await client.post("/api/inbound/inkbox", content=raw, headers=headers)

        return asyncio.run(call())

    def drain(self) -> int:
        rows = self.supa.rpc("inkbox_inbox_read", {"p_qty": BATCH, "p_vt": VISIBILITY_SECONDS}) or []
        done = 0
        for row in rows if isinstance(rows, list) else []:
            msg_id, read_ct, message = row.get("msg_id"), int(row.get("read_ct") or 0), row.get("message") or {}
            try:
                response = self.replay(message)
                status = response.status_code
            except Exception as error:
                status, response = 599, None
                self.last_error = f"replay failed: {type(error).__name__}"
            if status < 500 and status != 401:
                self.supa.rpc("inkbox_inbox_archive", {"p_msg_id": msg_id})
                self.archived += 1
                self.processed += 1
                done += 1
                if status >= 400:
                    self.on_event("Supabase inbox message rejected", f"msg {msg_id} answered {status}; archived.")
            elif read_ct >= POISON_READS:
                self.supa.rpc("inkbox_inbox_archive", {"p_msg_id": msg_id})
                self.poisoned += 1
                self.on_event("Supabase inbox poison message archived",
                              f"msg {msg_id} answered {status} {read_ct} times (401 means the backend's signing keys differ from the function's).")
        return done

    def status(self) -> dict:
        return dict(running=bool(self._thread and self._thread.is_alive()), intervalSeconds=self.interval, processed=self.processed,
                    archived=self.archived, poisoned=self.poisoned, failures=self.failures, lastError=self.last_error, queue=self.last_stats)
