"""The Supabase side services the app starts next to the mirror: Storage uploads, the live HUD, the inbox drainer and
the usage poller. Started by supa_routes.install() from the app lifespan only when workers run and Supabase is
configured; tests that build the app without workers get none of these threads.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .sites import DEMO_SITE
from .store import now
from .supa_authority import SITES
from .supa_inbox import InboxDrainer
from .supa_realtime import Hud
from .supa_storage import ObjectStore

USAGE_POLL_SECONDS = 600


class SupaServices:
    def __init__(self, mirror, service, app=None, start_threads: bool = True):
        self.mirror = mirror
        self.service = service
        self.store = service.store
        self.budget = mirror.budget
        self.supa = mirror.supa
        self.frames_dir = self.store.directory / "eye" / "frames"
        self.files_dir = self.store.directory / "files"
        self.storage = ObjectStore(self.supa, self.budget, self.store, on_event=self.event)
        self.hud = Hud(self.supa, self.budget, SITES, redact=mirror.redact_text, on_event=self.event)
        self.inbox = InboxDrainer(self.supa, app, self.budget, on_event=self.event) if app is not None else None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="steward-supabase-storage")
        self._stop = threading.Event()
        self._poller = None
        self.last_poll: dict | None = None
        self.start_threads = start_threads
        if start_threads:
            self.hud.start()
            if self.inbox is not None:
                self.inbox.start()
            self._poller = threading.Thread(target=self._poll_loop, name="steward-supabase-usage", daemon=True)
            self._poller.start()

    def close(self):
        self._stop.set()
        self.hud.stop()
        if self.inbox is not None:
            self.inbox.stop()
        if self._poller and self._poller.is_alive():
            self._poller.join(timeout=2)
        self.executor.shutdown(wait=True)

    def event(self, title: str, detail: str):
        try:
            key = f"supa:event:{title}:{now()[:13]}"  # at most one event per title per hour
            if self.store.mark_once(key):
                self.store.event(DEMO_SITE, "director", "supabase.service", title, detail[:500])
        except Exception:
            pass

    # ---- taps from the mirror -----------------------------------------------------------------------------------

    def tap(self, kind: str, body: dict):
        try:
            if kind == "eye_frame":
                self.executor.submit(self._frame, dict(body))
            elif kind == "attestation" and body.get("evidenceHashes"):
                self.executor.submit(self.storage.upload_evidence, dict(body), self.files_dir)
            elif kind == "telemetry":
                self.hud.telemetry(body)
            elif kind == "conversation":
                self.hud.conversation(body)
            elif kind == "issue":
                self.hud.issue(body)
        except RuntimeError:
            pass  # executor already shut down
        except Exception as error:
            self.event("Supabase tap failed", f"{kind}: {type(error).__name__}")

    def _frame(self, frame: dict):
        uploaded = self.storage.upload_frame(frame, self.frames_dir)
        site = frame.get("siteId")
        viewers = self.hud.viewer_count(site) if site else 0
        if not viewers:
            return
        url = self.storage.frame_url(frame["id"], copies=viewers) if uploaded else None
        thumb = self.storage.thumb_url(frame["id"], site, self.frames_dir, copies=viewers) if uploaded else None
        self.hud.eye_frame(frame, url, thumb)

    # ---- usage poller ---------------------------------------------------------------------------------------------

    def poll_usage(self) -> dict:
        result: dict = dict(at=now())
        try:
            size = self.supa.rpc("steward_db_size")
            if isinstance(size, (int, float)):
                self.budget.set_db_bytes(int(size))
                result["dbBytes"] = int(size)
        except Exception as error:
            result["dbError"] = type(error).__name__
        try:
            usage = self.supa.rpc("steward_storage_usage")
            if isinstance(usage, dict):
                total = sum(int((bucket or {}).get("bytes") or 0) for bucket in usage.values())
                self.budget.set_storage_bytes(total)
                result["storage"] = usage
        except Exception as error:
            result["storageError"] = type(error).__name__
        if self.inbox is not None:
            try:
                result["inbox"] = self.inbox.refresh_stats(force=True)
            except Exception as error:
                result["inboxError"] = type(error).__name__
        self.last_poll = result
        self.store.meta("supa:usage:last_poll", json.dumps(result, default=str))
        return result

    def push_settings(self) -> None:
        """Tell the database the effective Edge Function cap and the backend's signing key (both idempotent)."""
        try:
            self.supa.rpc("steward_put_setting", {"p_key": "edge_calls_day_cap", "p_value": str(self.budget.cap("edge_calls_day"))})
        except Exception as error:
            self.event("Supabase settings push failed", type(error).__name__)
        try:
            signer = self.service.reality.signer
            self.supa.rpc("steward_trust_signing_key", {"p_public_key": signer.public_key_b64, "p_label": "steward backend"})
        except Exception as error:
            self.event("Supabase signing key push failed", type(error).__name__)

    def _poll_loop(self):
        self.push_settings()
        while True:
            try:
                self.poll_usage()
            except Exception:
                pass
            if self._stop.wait(USAGE_POLL_SECONDS):
                return

    def status(self) -> dict:
        return dict(storage=self.storage.stats(), hud=self.hud.status(), inbox=self.inbox.status() if self.inbox else None,
                    lastPoll=self.last_poll or json.loads(self.store.meta("supa:usage:last_poll") or "null"))
