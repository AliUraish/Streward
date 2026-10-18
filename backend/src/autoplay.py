"""Scenario autoplay: the seeded scenarios start on their own, one after another, so the dashboard always shows the agent
teams at work without anyone pressing Start.

Before every start the autoplayer checks, in order:
- It is on: `STEWARD_SCENARIO_AUTOPLAY` (default true when the backend runs its workers) and not paused from the dashboard
  (`POST /api/scenario-autoplay {enabled}`, remembered across restarts).
- No live switch is on: real SMS, calls or email to people (`STEWARD_ALLOW_EXTERNAL_MESSAGES`, `STEWARD_ALLOW_NOTICE_SMS`),
  live Supermemory, or a model provider (`STEWARD_MODEL_PROVIDER` other than local). An
  auto-started run would otherwise send real messages or spend money on its own, again and again.
  `STEWARD_SCENARIO_AUTOPLAY_LIVE=true` overrides this on purpose. Not live switches: agent-to-agent messages over Inkbox
  (`STEWARD_A2A_TRANSPORT=inkbox`) travel only between Steward's own identities, never reach a person and are capped per
  hour by the A2A bus; owner alerts (`STEWARD_ALLOW_OWNER_ALERTS`) go through their own capped owner channel; agent email
  (`STEWARD_ALLOW_AGENT_EMAIL`, contract 8) only lets the outbox mail Steward's own mailboxes (capped per hour), and the
  document email that also reaches a person still needs `STEWARD_ALLOW_EXTERNAL_MESSAGES`.
- The Supabase realtime budget is less than half spent today, so the demo keeps the rest.
- Fewer than `STEWARD_SCENARIO_AUTOPLAY_MAX_PER_DAY` auto runs today (default 120).
- No other scenario run or fix workflow is active, and nobody started a scenario by hand (a presenter, the evals,
  `start_scenario` over MCP) in the last `STEWARD_SCENARIO_AUTOPLAY_COOLDOWN` seconds (default 600). Manual runs win.
- `STEWARD_SCENARIO_AUTOPLAY_GAP` seconds (default 30) passed since the last auto run and its fix workflow ended, and
  `STEWARD_SCENARIO_AUTOPLAY_DELAY` seconds (default 20) since the backend started.

Runs play at `STEWARD_SCENARIO_AUTOPLAY_SPEED` (default 10x, the contract-7 continuous pace) through the playlist
`STEWARD_SCENARIO_AUTOPLAY_PLAYLIST` (default every scenario, sites interleaved), resuming where the rotation left off.
The playlist holds scenarios only: each site's Engineer walks continuously on its own (`walks.py`), so the autoplayer no
longer walks sites (contract 7 §3's `patrol:<siteId>` entries are gone; a custom playlist naming one ignores it). A
walkthrough started by hand makes autoplay wait, and so does a compliance alert still in its steps; the continuous walks
(origin autoplay) do not. Auto runs carry `origin: "autoplay"` and `startedBy: "autoplay"`; everything they write stays
synthetic.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from .agents import OPERATOR
from .env import env

TICK_SECONDS = 5
PLAYLIST_ORDER = ("my-overpressure", "br-sump", "tm-humidity", "my-extinguisher", "br-vessel-cert", "tm-alteration-permit",
                  "x-maintenance", "ops-injection", "x-heritage", "ops-counsel-tokens")
LIVE_FLAGS = ("STEWARD_ALLOW_EXTERNAL_MESSAGES", "STEWARD_ALLOW_NOTICE_SMS", "STEWARD_SUPERMEMORY_LIVE")
DEFAULT_SPEED = 10.0
REALTIME_SHARE_LIMIT = 0.5


def _flag(name: str, default: str = "false") -> bool:
    return (env(name, default) or default).strip().lower() == "true"


def _number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(env(name, str(default)) or default)
    except ValueError:
        return default
    return min(max(value, low), high)


def live_switches() -> list[str]:
    """The settings that make a scenario reach a person or spend money, as they are now. The A2A transport is not one: over
    Inkbox it only connects Steward's own identities (and the bus caps it per hour)."""
    on = [name for name in LIVE_FLAGS if _flag(name)]
    provider = (env("STEWARD_MODEL_PROVIDER", "local") or "local").strip().lower()
    if provider not in ("", "local"):
        on.append(f"STEWARD_MODEL_PROVIDER={provider}")
    return on


class ScenarioAutoplay:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.booted = time.monotonic()
        self.current_run_id: str | None = None
        self.last_finished: float | None = None
        self.state = "off"
        self.reason: str | None = "Autoplay starts with the backend's workers."

    # ---- settings -----------------------------------------------------------------------------------------

    def enabled(self) -> bool:
        override = self.store.meta("autoplay:enabled")
        if override in ("true", "false"):
            return override == "true"
        return self.service.start_workers and _flag("STEWARD_SCENARIO_AUTOPLAY", "true")

    def set_enabled(self, enabled: bool) -> dict:
        self.store.meta("autoplay:enabled", "true" if enabled else "false")
        if enabled:
            self.last_finished = None  # resume promptly; the other checks still apply
        return self.status()

    @staticmethod
    def gap() -> float:
        return _number("STEWARD_SCENARIO_AUTOPLAY_GAP", 30, 0, 86400)

    @staticmethod
    def delay() -> float:
        return _number("STEWARD_SCENARIO_AUTOPLAY_DELAY", 20, 0, 3600)

    @staticmethod
    def cooldown() -> float:
        return _number("STEWARD_SCENARIO_AUTOPLAY_COOLDOWN", 600, 0, 86400)

    @staticmethod
    def max_per_day() -> int:
        return int(_number("STEWARD_SCENARIO_AUTOPLAY_MAX_PER_DAY", 120, 0, 10000))

    def speed(self) -> float:
        return _number("STEWARD_SCENARIO_AUTOPLAY_SPEED", DEFAULT_SPEED, 1, 100000)

    def playlist(self) -> list[str]:
        """Scenarios only (the sites are walked continuously by walks.py; a custom `patrol:<siteId>` entry is ignored)."""
        known = list(self.service.scenarios.scripts)
        raw = (env("STEWARD_SCENARIO_AUTOPLAY_PLAYLIST", "") or "").strip()
        if raw:
            return [s.strip() for s in raw.split(",") if s.strip() in known]
        ordered = [s for s in PLAYLIST_ORDER if s in known]
        return ordered + [s for s in known if s not in ordered]

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def played_today(self) -> int:
        return int(self.store.meta(f"autoplay:played:{self._today()}") or 0)

    # ---- checks -------------------------------------------------------------------------------------------

    def _realtime_share(self) -> float | None:
        budget = getattr(getattr(self.service.reality, "mirror", None), "budget", None)
        try:
            return float(budget.realtime_fraction()) if budget is not None else None
        except Exception:
            return None

    def _busy(self) -> str | None:
        """Another scenario run or fix workflow that is still playing."""
        scenarios = self.service.scenarios
        for run in scenarios.runs():
            if run["state"] == "running":
                return f"{run['title']} is running" + (" (started by hand)" if run.get("origin", "manual") != "autoplay" else "")
        for workflow in self.service.fixes.list():
            if workflow.get("state") == "running":
                return f"a fix workflow for {workflow.get('assetTag') or workflow.get('issueId')} is running"
        patrols = getattr(self.service, "patrols", None)
        return patrols.busy(manual_only=True) if patrols is not None else None  # the continuous walks run beside the rotation

    def blocked(self) -> tuple[str, str] | None:
        if not self.enabled():
            return "off", "Autoplay is off (paused from the dashboard, or STEWARD_SCENARIO_AUTOPLAY=false)."
        live = live_switches()
        if live and not _flag("STEWARD_SCENARIO_AUTOPLAY_LIVE"):
            return "paused", ("Live switches are on (" + ", ".join(live) + "), so an auto-started run would send real messages or spend on its own. "
                              "Start scenarios by hand, or set STEWARD_SCENARIO_AUTOPLAY_LIVE=true.")
        share = self._realtime_share()
        if share is not None and share >= REALTIME_SHARE_LIMIT:
            return "paused", f"The Supabase realtime budget is {round(share * 100)}% spent today; autoplay leaves the rest for the demo."
        if self.played_today() >= self.max_per_day():
            return "paused", f"{self.played_today()} auto runs today, the daily maximum (STEWARD_SCENARIO_AUTOPLAY_MAX_PER_DAY)."
        busy = self._busy()
        if busy:
            return "waiting", f"Waiting: {busy}."
        manual = self.service.scenarios.last_manual_start
        if manual is not None and time.monotonic() - manual < self.cooldown():
            left = int(self.cooldown() - (time.monotonic() - manual))
            return "waiting", f"A scenario was started by hand; autoplay resumes in {left} s."
        since_boot = time.monotonic() - self.booted
        if since_boot < self.delay():
            return "waiting", f"First scenario in {int(self.delay() - since_boot)} s."
        if self.last_finished is not None and time.monotonic() - self.last_finished < self.gap():
            return "waiting", f"Next scenario in {int(self.gap() - (time.monotonic() - self.last_finished))} s."
        return None

    # ---- loop -----------------------------------------------------------------------------------------------

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="steward-scenario-autoplay", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self._stop.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as error:  # never let the loop die; show why in the status
                self.state, self.reason = "error", f"{type(error).__name__}: {str(error)[:200]}"
            if self._stop.wait(TICK_SECONDS):
                return

    def _current(self) -> dict | None:
        """The auto run still playing (or whose fix workflow still plays); None once it is done."""
        if not self.current_run_id:
            return None
        run = self.store.get("scenario_run", self.current_run_id, "")
        if run and run["state"] == "running":
            return run
        fixes = (run or {}).get("fixWorkflowIds") or {}
        for workflow_id in fixes.values():
            try:
                if self.service.fixes.get(workflow_id).get("state") == "running":
                    return run
            except Exception:
                continue
        self.current_run_id = None
        self.last_finished = time.monotonic()
        return None

    def tick(self) -> dict | None:
        """One decision: keep playing, wait, or start the next scenario. Returns the run it started, if any."""
        with self.lock:
            current = self._current()
            if current:
                self.state, self.reason = "playing", f"Playing {current['title']}."
                return None
            blocked = self.blocked()
            if blocked:
                self.state, self.reason = blocked
                return None
            playlist = self.playlist()
            if not playlist:
                self.state, self.reason = "off", "No scenarios to play."
                return None
            index = int(self.store.meta("autoplay:index") or 0) % len(playlist)
            scenario_id = playlist[index]
            run = self.service.scenarios.start(scenario_id, OPERATOR, speed=self.speed(), origin="autoplay")
            self.store.meta("autoplay:index", str((index + 1) % len(playlist)))
            self.store.meta(f"autoplay:played:{self._today()}", str(self.played_today() + 1))
            self.current_run_id = run["id"]
            self.state, self.reason = "playing", f"Playing {run['title']}."
            return run

    # ---- status -------------------------------------------------------------------------------------------

    def status(self) -> dict:
        playlist = self.playlist()
        index = int(self.store.meta("autoplay:index") or 0) % len(playlist) if playlist else 0
        run = self.store.get("scenario_run", self.current_run_id, "") if self.current_run_id else None
        current = dict(kind="scenario", runId=run["id"], scenarioId=run["scenarioId"], title=run["title"], state=run["state"],
                       stepIndex=run["stepIndex"], stepCount=run["stepCount"]) if run else None
        walks = getattr(self.service, "walks", None)
        return dict(enabled=self.enabled(), state=self.state, reason=self.reason,
                    current=current, patrols=False,
                    walks=dict(continuous=bool(walks and walks.enabled()), status="/api/walks/status",
                               note="Each site's Engineer walks on its own; the playlist plays scenarios only."),
                    next=playlist[index] if playlist else None, playlist=playlist, speed=self.speed(), gapSeconds=self.gap(),
                    cooldownSeconds=self.cooldown(), playedToday=self.played_today(), maxPerDay=self.max_per_day(),
                    liveSwitches=live_switches(), liveAllowed=_flag("STEWARD_SCENARIO_AUTOPLAY_LIVE"), synthetic=True)
