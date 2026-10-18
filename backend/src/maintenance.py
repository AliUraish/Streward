"""Maintenance windows (contract 4 §7): `{id, siteIds, date, scope, examiner, status: proposed | approved | done,
conversationId, assetTags?, obligationId?, proposedBy?, approvedBy?, synthetic}`.

Managers schedule maintenance for their own site; a window that spans more than one site needs the Operations
Director's approval (`approve_cross_site_maintenance`). Seeded windows come from the synthetic `maintenance`
family (relative dates); the `x-maintenance` scenario creates the shared examiner window (Myer and Bristol) and
`x-heritage` the shared heritage-safe sensor installation window (Tomioka and Bristol).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .agents import authorize, display_name
from .errors import RealityError
from .store import now, uid
from .synthetic import load_family

STATUSES = ("proposed", "approved", "done")


class MaintenanceService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.load()

    def load(self) -> None:
        # Version 2 (contract 5): re-run once, insert-if-missing, for the Tomioka windows.
        if self.store.meta("steward_maintenance_version") == "2":
            return
        today = datetime.now(timezone.utc).date()
        for record in load_family("maintenance"):
            if self.store.get("maintenance_window", record["id"], ""):
                continue
            sites = [s for s in record.get("siteIds", []) if self.store.get("property", s)]
            if not sites:
                continue
            self._put(dict(id=record["id"], siteIds=sites, date=(today + timedelta(days=int(record.get("inDays", 7)))).isoformat(), scope=record["scope"],
                           examiner=record.get("examiner"), status=record.get("status", "proposed"), conversationId=None,
                           assetTags=record.get("assetTags", []), obligationId=record.get("obligationId"), proposedBy=None, approvedBy=None,
                           synthetic=True, generator=record["generator"], createdAt=now(), updatedAt=now()))
        self.store.meta("steward_maintenance_version", "2")

    def _put(self, window: dict) -> dict:
        window["updatedAt"] = now()
        self.store.put("maintenance_window", window, "")
        self.service.reality.mirror.put("maintenance_window", window, window["siteIds"][0] if window["siteIds"] else "")
        return window

    def _change(self, window: dict, summary: str) -> None:
        for site in window["siteIds"]:
            self.service.reality.emit_change(site, "maintenance", window["id"], summary[:480],
                                             extra=dict(maintenanceId=window["id"], status=window["status"], crossSite=len(window["siteIds"]) > 1))

    def get(self, window_id: str) -> dict:
        window = self.store.get("maintenance_window", window_id, "")
        if not window:
            raise RealityError("Maintenance window not found.", "NOT_FOUND", "List windows with GET /api/maintenance?siteId=.", 404)
        return window

    def list(self, site_id: str | None = None) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        windows = self.store.all("maintenance_window", "")
        if site_id:
            windows = [w for w in windows if site_id in w["siteIds"]]
        return sorted(windows, key=lambda w: w["date"])

    @staticmethod
    def _authorize_schedule(actor: str, sites: list[str]) -> str:
        """The director may schedule anywhere; a manager schedules for its own site, including a shared window that
        includes its site (the other manager agrees on a call, the director approves)."""
        from .agents import DIRECTOR, site_of
        if actor == DIRECTOR or actor == "operator":
            return authorize(actor, "read")
        own = site_of(actor)
        if own not in sites:
            raise RealityError(f"{display_name(actor)} may only schedule maintenance that includes its own site.", "AUTHORITY_DENIED",
                               "Ask that site's plant manager or the Operations Director.", 403)
        return authorize(actor, "schedule_maintenance", own)

    def propose(self, site_ids: list[str], date: str, scope: str, examiner: str | None, actor: str, conversation_id: str | None = None,
                asset_tags: list[str] | None = None, obligation_id: str | None = None, scenario_id: str | None = None, synthetic: bool = True) -> dict:
        sites = list(dict.fromkeys(site_ids))
        if not sites:
            raise RealityError("siteIds is required.", "INVALID_REQUEST", "Name one or more sites.")
        for site in sites:
            self.service.require_property(site)
        actor = self._authorize_schedule(actor, sites)
        try:
            datetime.fromisoformat(date)
        except ValueError:
            raise RealityError("date must be an ISO date (YYYY-MM-DD).", "INVALID_REQUEST", "Example: 2026-10-24.")
        window = dict(id=uid("mw"), siteIds=sites, date=date[:10], scope=scope[:500], examiner=(examiner or "")[:200] or None, status="proposed",
                      conversationId=conversation_id, assetTags=list(asset_tags or []), obligationId=obligation_id, proposedBy=actor, approvedBy=None,
                      scenarioId=scenario_id, synthetic=bool(synthetic), createdAt=now(), updatedAt=now())
        self._put(window)
        self._change(window, f"{display_name(actor)} proposed maintenance on {window['date']}" + (f" across {len(sites)} sites" if len(sites) > 1 else "") + f": {scope[:200]}")
        return window

    def approve(self, window_id: str, actor: str, conversation_id: str | None = None) -> dict:
        window = self.get(window_id)
        if len(window["siteIds"]) > 1:
            authorize(actor, "approve_cross_site_maintenance")
        else:
            authorize(actor, "approve_maintenance", window["siteIds"][0])
        if window["status"] == "done":
            raise RealityError("Window already done.", "INVALID_REQUEST", "Nothing to approve.", 409)
        window.update(status="approved", approvedBy=actor, approvedAt=now())
        if conversation_id:
            window["approvalConversationId"] = conversation_id
        self._put(window)
        self._change(window, f"{display_name(actor)} approved maintenance on {window['date']}: {window['scope'][:200]}")
        return window

    def complete(self, window_id: str, actor: str) -> dict:
        window = self.get(window_id)
        self._authorize_schedule(actor, window["siteIds"])
        window.update(status="done", doneAt=now())
        self._put(window)
        self._change(window, f"Maintenance on {window['date']} marked done: {window['scope'][:200]}")
        return window
