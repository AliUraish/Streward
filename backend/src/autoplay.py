"""Scenario autoplay: the seeded scenarios start on their own, one after another, so the dashboard always shows the agent
teams at work without anyone pressing Start.

Before every start the autoplayer checks, in order:
- It is on: `STEWARD_SCENARIO_AUTOPLAY` (default true when the backend runs its workers) and not paused from the dashboard
  (`POST /api/scenario-autoplay {enabled}`, remembered across restarts).
- No live switch is on (real SMS, calls or email, Inkbox A2A, live Supermemory, a model provider). An auto-started run
  would otherwise send real messages or spend money on its own, again and again. `STEWARD_SCENARIO_AUTOPLAY_LIVE=true`
  overrides this on purpose.
- The Supabase realtime budget is less than half spent today, so the demo keeps the rest.
- Fewer than `STEWARD_SCENARIO_AUTOPLAY_MAX_PER_DAY` auto runs today (default 120).
- No other scenario run or fix workflow is active, and nobody started a scenario by hand (a presenter, the evals,
  `start_scenario` over MCP) in the last `STEWARD_SCENARIO_AUTOPLAY_COOLDOWN` seconds (default 600). Manual runs win.
- `STEWARD_SCENARIO_AUTOPLAY_GAP` seconds (default 30) passed since the last auto run and its fix workflow ended, and
  `STEWARD_SCENARIO_AUTOPLAY_DELAY` seconds (default 20) since the backend started.

Runs play at `STEWARD_SCENARIO_AUTOPLAY_SPEED` (default 10x, the contract-7 continuous pace) through the playlist
`STEWARD_SCENARIO_AUTOPLAY_PLAYLIST` (default every scenario, sites interleaved), resuming where the rotation left off.
Contract 7 §3: after every two scenarios the playlist walks a site (`patrol:<siteId>`, rotating myer-plant, bristol-pumps,
tomioka-mill; a custom playlist may name `patrol:<siteId>` entries too): the site's Engineer walks the scan with the agent
eye (`PatrolService.start(site, origin="autoplay")`), and the walkthrough counts as playing until it and the compliance
alerts it started finish. Walkthroughs drive the eye, so they are in the playlist by default only when the backend runs
its workers (`STEWARD_SCENARIO_AUTOPLAY_PATROLS` overrides). A running walkthrough started by hand also makes autoplay wait.
Auto runs carry `origin: "autoplay"` and `startedBy: "autoplay"`; everything they write stays synthetic.
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
LIVE_FLAGS = ("STEWARD_ALLOW_EXTERNAL_MESSAGES", "STEWARD_ALLOW_NOTICE_SMS", "STEWARD_ALLOW_AGENT_EMAIL", "STEWARD_SUPERMEMORY_LIVE",
              "STEWARD_ALLOW_OWNER_ALERTS")
PATROL_SITES = ("myer-plant", "bristol-pumps", "tomioka-mill")
PATROL_EVERY = 2  # scenarios between walkthroughs
PATROL_PREFIX = "patrol:"
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
    """The settings that make a scenario reach the real world or spend money, as they are now."""
    on = [name for name in LIVE_FLAGS if _flag(name)]
    transport = (env("STEWARD_A2A_TRANSPORT", "local") or "local").strip().lower()
    if transport not in ("", "local"):
        on.append(f"STEWARD_A2A_TRANSPORT={transport}")
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
        self.current_patrol_id: str | None = None
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

    def patrols_enabled(self) -> bool:
        return _flag("STEWARD_SCENARIO_AUTOPLAY_PATROLS", "true" if self.service.start_workers else "false")

    def patrol_site(self, entry: str) -> str | None:
        """The site of a `patrol:<siteId>` playlist entry, when that site exists."""
        if not entry.startswith(PATROL_PREFIX):
            return None
        site = entry[len(PATROL_PREFIX):].strip()
        return site if site and self.store.get("property", site) else None

    def playlist(self) -> list[str]:
        known = list(self.service.scenarios.scripts)
        raw = (env("STEWARD_SCENARIO_AUTOPLAY_PLAYLIST", "") or "").strip()
        if raw:
            return [s.strip() for s in raw.split(",") if s.strip() in known or self.patrol_site(s.strip())]
        ordered = [s for s in PLAYLIST_ORDER if s in known]
        scenarios = ordered + [s for s in known if s not in ordered]
        sites = [s for s in PATROL_SITES if self.store.get("property", s)]
        if not self.patrols_enabled() or not sites:
            return scenarios
        out, walks = [], 0
        for count, scenario in enumerate(scenarios, 1):
            out.append(scenario)
            if count % PATROL_EVERY == 0:
                out.append(PATROL_PREFIX + sites[walks % len(sites)])
                walks += 1
        return out

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
        return patrols.busy() if patrols is not None else None

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
        """The auto run still playing (or whose fix workflow still plays), or the auto walkthrough still walking (or whose
        compliance alerts still play); None once it is done."""
        if self.current_patrol_id:
            patrol = self.store.get("patrol", self.current_patrol_id)
            if patrol and self.service.patrols.active(patrol):
                return dict(patrol, title=f"the walkthrough of {patrol['place']}")
            self.current_patrol_id = None
            self.last_finished = time.monotonic()
            return None
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

    @staticmethod
    def _playing(current: dict) -> str:
        if "route" not in current:  # a scenario run
            return f"Playing {current['title']}."
        if current.get("state") == "running":
            return f"{current.get('line') or 'Walking ' + current['title']}."
        return f"Compliance alerts from {current['title']} are playing."

    def tick(self) -> dict | None:
        """One decision: keep playing, wait, or start the next scenario. Returns the run it started, if any."""
        with self.lock:
            current = self._current()
            if current:
                self.state, self.reason = "playing", self._playing(current)
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
            site = self.patrol_site(scenario_id)
            if site:
                # Advance first: a walkthrough that cannot start must not wedge the rotation on this entry.
                self.store.meta("autoplay:index", str((index + 1) % len(playlist)))
                try:
                    patrol = self.service.patrols.start(site, OPERATOR, origin="autoplay")
                except Exception as error:
                    self.state, self.reason = "error", f"Walkthrough of {site} did not start: {type(error).__name__}: {str(error)[:160]}"
                    return None
                self.store.meta(f"autoplay:played:{self._today()}", str(self.played_today() + 1))
                self.current_patrol_id, self.current_run_id = patrol["id"], None
                self.state, self.reason = "playing", f"Walking {patrol['place']} ({patrol['agentName']})."
                return patrol
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
        patrol = self.store.get("patrol", self.current_patrol_id) if self.current_patrol_id else None
        current = dict(kind="scenario", runId=run["id"], scenarioId=run["scenarioId"], title=run["title"], state=run["state"],
                       stepIndex=run["stepIndex"], stepCount=run["stepCount"]) if run else None
        if patrol:
            current = dict(kind="patrol", patrolId=patrol["id"], siteId=patrol["siteId"], title=f"Walkthrough of {patrol['place']}", state=patrol["state"],
                           agentId=patrol["agentId"], agentName=patrol["agentName"], stopIndex=patrol.get("stopIndex", 0), stopCount=len(patrol["route"]),
                           assetTag=patrol.get("currentAssetTag"), line=patrol.get("line"), alertIds=patrol.get("alertIds") or [])
        return dict(enabled=self.enabled(), state=self.state, reason=self.reason,
                    current=current, patrols=self.patrols_enabled(),
                    next=playlist[index] if playlist else None, playlist=playlist, speed=self.speed(), gapSeconds=self.gap(),
                    cooldownSeconds=self.cooldown(), playedToday=self.played_today(), maxPerDay=self.max_per_day(),
                    liveSwitches=live_switches(), liveAllowed=_flag("STEWARD_SCENARIO_AUTOPLAY_LIVE"), synthetic=True)
