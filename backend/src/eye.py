"""The agent eye (contract 4 §2): the 3D scan is an interface for agents. Humans watch it; agents operate it.

A renderer (any viewer page in eye mode, or a headless Chrome worker this backend starts) registers with a
heartbeat, long-polls for camera commands, executes them and posts the frame back. Agents act through
`POST /api/eye/{siteId}/act` and get the frame, camera pose and visible pins.

- `POST /api/eye/{siteId}/renderers {rendererId}` registers or heartbeats (every 5 s; stale after 15 s).
- `GET /api/eye/{siteId}/commands?rendererId=&since=` long-polls (≤ 25 s) for commands after `since` (a per-site
  sequence). Commands are broadcast: every open renderer moves its camera, the first renderer to post a frame for a
  command produces it.
- `POST /api/eye/{siteId}/frames {commandId, jpegBase64, camera, visiblePins, index?, annotation? | mark?}` stores the JPEG
  under `<data>/eye/frames/` (served at `GET /api/eye/frames/{frameId}.jpg`) and completes the command once its
  expected frames arrived (1, or N for `orbit`).
- `POST /api/eye/{siteId}/act {action, params}` (engineer, manager, director or operator; site-scoped for team roles)
  waits up to 20 s for the frame (orbit: longer, bounded) and returns `{frameId, frameUrl, camera, visiblePins, actor, at}`
  (`orbit` returns `frames`). No fresh renderer → the worker starts headless Chrome on
  `http://127.0.0.1:3000/eye?site=<id>&renderer=headless` (GPU flags first, SwiftShader as the fallback), tracks its
  PID and stops it after 5 idle minutes. Every act is a Change of type `eye` and a telemetry row.
  A cold act (the worker had to start) waits up to 90 s for the first frame and gives up early when the worker exits.
  A worker left behind by an earlier backend run still holds its profile lock and would make every new launch abort;
  it is stopped first, identified by the PID in that profile's SingletonLock and by its own command line naming the profile.
  `STEWARD_EYE_PREWARM=all` (or a comma list of site ids) starts those renderers with the backend and keeps them warm.
- `GET /api/eye/{siteId}/feed?since=` returns recent frames with actor and action for the dashboard's agent mode.

Frames are rendered from the hosted third-party capture; synthetic defects (vision pipeline) stay labelled there.

Reproducible views: `go_to` and `orbit` carry the asset's stored `viewPose {position, target, fov}` (set through the pin
route, or passed explicitly in `params.viewPose`) so the renderer starts from the same pose every time instead of the
camera's current side. A `mark` frame's picked world point arrives as `mark` (or `annotation`) and is returned by the
act as `world` / `hit`. Acts with `params.purpose == "survey"` (the PINS stream's placement surveys) tag their frames
`survey: true` so the dashboard can hide them (`GET /feed?excludeSurvey=true`).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

from .agents import authorize, display_name
from .env import env
from .errors import RealityError
from .store import now, uid

ACTIONS = ("look", "move", "turn", "go_to", "orbit", "mark")
DIRECTIONS = ("forward", "back", "left", "right", "up", "down")
HEARTBEAT_STALE_SECONDS = 15
COMMAND_LONG_POLL_MAX = 25
ACT_TIMEOUT_SECONDS = 20
# The first act after a backend restart starts headless Chrome, which compiles /eye and loads the scan before it can
# register and draw, so a cold act waits longer (STEWARD_EYE_COLD_START_TIMEOUT) instead of failing at 20 s.
COLD_START_TIMEOUT_SECONDS = 90
MAX_COLD_ACT_SECONDS = 120
IDLE_STOP_SECONDS = 300
GPU_REGISTER_GRACE_SECONDS = 25
RENDERER_LOST_SECONDS = 30  # a worker whose page registered and then went silent this long is restarted
SINGLETON_FILES = ("SingletonLock", "SingletonSocket", "SingletonCookie")
MAX_FRAME_BYTES = 3 * 1024 * 1024
IMAGE_TOKENS = 350  # rough vision-token cost of one 640x400 frame, for telemetry estimates
CHROME_CANDIDATES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Chromium.app/Contents/MacOS/Chromium",
                     "google-chrome", "chromium", "chromium-browser")


def _finite(value, low: float, high: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RealityError(f"{name} must be a number.", "INVALID_REQUEST", f"Send {name} between {low:g} and {high:g}.")
    if not math.isfinite(number) or not low <= number <= high:
        raise RealityError(f"{name} must be between {low:g} and {high:g}.", "INVALID_REQUEST", f"Send {name} between {low:g} and {high:g}.")
    return number


class EyeWorker:
    """At most one headless Chrome renderer per site, started on demand and tracked by PID (its own process group)."""

    def __init__(self, service):
        self.service = service
        self.procs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.launcher = None  # tests inject: callable(args, log_path) -> object with .pid, .poll(), .terminate()

    @property
    def enabled(self) -> bool:
        default = "true" if self.service.start_workers else "false"
        return env("STEWARD_EYE_AUTOSTART", default).strip().lower() == "true"

    @staticmethod
    def chrome_path() -> str | None:
        explicit = env("STEWARD_CHROME_PATH", "")
        if explicit:
            return explicit if Path(explicit).exists() or shutil.which(explicit) else None
        for candidate in CHROME_CANDIDATES:
            if Path(candidate).exists():
                return candidate
            found = shutil.which(candidate)
            if found:
                return found
        return None

    @staticmethod
    def url(site_id: str) -> str:
        base = env("STEWARD_EYE_URL", "http://127.0.0.1:3000/eye").rstrip("?")
        return f"{base}?site={site_id}&renderer=headless"

    def profile_dir(self, site_id: str) -> Path:
        return self.service.store.directory / "eye" / f"chrome-{site_id}"

    def args(self, chrome: str, site_id: str, mode: str) -> list[str]:
        profile = self.profile_dir(site_id)
        profile.mkdir(parents=True, exist_ok=True)
        common = [chrome, "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                  "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                  "--mute-audio", "--hide-scrollbars", "--window-size=1280,800"]
        if mode == "gpu":
            flags = ["--enable-gpu", "--ignore-gpu-blocklist", "--enable-webgl", "--use-gl=angle",
                     "--use-angle=metal" if os.uname().sysname == "Darwin" else "--use-angle=default"]
        else:
            flags = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--enable-webgl"]
        return common + flags + [self.url(site_id)]

    def _launch(self, args: list[str], log_path: Path):
        if self.launcher:
            return self.launcher(args, log_path)
        log = open(log_path, "ab")
        try:
            return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        finally:
            log.close()

    def status(self) -> dict:
        with self.lock:
            out = {}
            for site, proc in self.procs.items():
                running = proc["popen"].poll() is None
                out[site] = dict(pid=proc["pid"], mode=proc["mode"], startedAt=proc["startedAt"], lastUsedAt=proc["lastUsedIso"], running=running,
                                 url=proc["url"])
            return out

    def ensure(self, site_id: str) -> dict:
        """Start a headless renderer for the site unless one is already running. Returns its status (or why not)."""
        if not self.enabled:
            return dict(started=False, reason="STEWARD_EYE_AUTOSTART is off; open /eye?site=<id> in a browser or enable autostart.")
        with self.lock:
            proc = self.procs.get(site_id)
            if proc and proc["popen"].poll() is None:
                proc["lastUsed"] = time.monotonic()
                proc["lastUsedIso"] = now()
                return dict(started=False, running=True, pid=proc["pid"], mode=proc["mode"])
        return self.start(site_id, "gpu")

    def start(self, site_id: str, mode: str) -> dict:
        chrome = self.chrome_path()
        if not chrome and not self.launcher:
            return dict(started=False, reason="Chrome not found; set STEWARD_CHROME_PATH.")
        if not self.launcher:
            self.reap_orphan(site_id)
        args = self.args(chrome or "chrome", site_id, mode)
        log_path = self.service.store.directory / "eye" / f"chrome-{site_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        popen = self._launch(args, log_path)
        with self.lock:
            self.procs[site_id] = dict(pid=popen.pid, popen=popen, mode=mode, started=time.monotonic(), startedAt=now(), lastUsed=time.monotonic(),
                                       lastUsedIso=now(), url=self.url(site_id))
        self.service.store.event(site_id, "director", "eye.worker_started", f"Headless renderer started ({mode})", f"pid {popen.pid}: {self.url(site_id)}")
        return dict(started=True, pid=popen.pid, mode=mode)

    def touch(self, site_id: str) -> None:
        with self.lock:
            proc = self.procs.get(site_id)
            if proc:
                proc["lastUsed"] = time.monotonic()
                proc["lastUsedIso"] = now()

    def _signal(self, proc: dict, sig: int) -> None:
        popen = proc["popen"]
        if popen.poll() is not None:
            return
        try:
            if self.launcher:
                popen.terminate()
            else:
                os.killpg(popen.pid, sig)  # the process group this backend created for that PID only
        except (ProcessLookupError, PermissionError):
            pass

    def _settle(self, proc: dict, timeout: float) -> None:
        """Wait for a signalled worker to exit; SIGKILL its group when it does not."""
        popen = proc["popen"]
        if self.launcher or popen.poll() is not None:
            return
        try:
            popen.wait(timeout=max(0.0, timeout))
        except subprocess.TimeoutExpired:
            self._signal(proc, signal.SIGKILL)

    def running(self, site_id: str) -> bool:
        with self.lock:
            proc = self.procs.get(site_id)
        return bool(proc) and proc["popen"].poll() is None

    def stop(self, site_id: str, reason: str = "idle") -> bool:
        with self.lock:
            proc = self.procs.pop(site_id, None)
        if not proc:
            return False
        self._signal(proc, signal.SIGTERM)
        self._settle(proc, 5)
        self.service.store.event(site_id, "director", "eye.worker_stopped", "Headless renderer stopped", f"pid {proc['pid']} ({reason})")
        return True

    @staticmethod
    def _pid_state(pid: int) -> tuple[bool, int | None, str]:
        """(alive, process group, command line) for one PID; a zombie counts as gone."""
        try:
            out = subprocess.run(["ps", "-o", "stat=", "-o", "pgid=", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                                 timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return False, None, ""
        parts = out.split(None, 2)
        if len(parts) < 2 or parts[0].startswith("Z"):
            return False, None, ""
        pgid = int(parts[1]) if parts[1].isdigit() else None
        return True, pgid, parts[2] if len(parts) > 2 else ""

    def reap_orphan(self, site_id: str) -> dict | None:
        """Stop a headless renderer an earlier backend run started for this site and never stopped.

        Such a Chrome still holds the profile's SingletonLock, so every new launch for the site aborts ("Failed to create a
        ProcessSingleton"). Only that exact process is touched: its PID comes from the lock in this site's own profile
        directory, and its command line must name that profile and run headless. A lock whose PID is gone is cleared."""
        profile = self.profile_dir(site_id)
        try:
            target = os.readlink(profile / "SingletonLock")
        except OSError:
            return None
        host, _, pid_text = target.rpartition("-")
        if not pid_text.isdigit() or host != socket.gethostname():
            return None
        pid = int(pid_text)
        with self.lock:
            if any(proc["pid"] == pid for proc in self.procs.values()):
                return None  # tracked by this run
        alive, pgid, command = self._pid_state(pid)
        if alive and not (f"--user-data-dir={profile}" in command and "--headless" in command):
            return None  # some other program: never touch it
        if alive:
            try:
                if pgid == pid:
                    os.killpg(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and self._pid_state(pid)[0]:
                time.sleep(0.2)
            if self._pid_state(pid)[0]:
                try:
                    if pgid == pid:
                        os.killpg(pid, signal.SIGKILL)
                    else:
                        os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                time.sleep(0.3)
        if not self._pid_state(pid)[0]:
            for name in SINGLETON_FILES:
                try:
                    (profile / name).unlink()
                except OSError:
                    pass
        if alive:
            self.service.store.event(site_id, "director", "eye.worker_reaped", "Leftover headless renderer stopped",
                                     f"pid {pid} from an earlier backend run held the {site_id} profile")
        return dict(siteId=site_id, pid=pid, reaped=alive)

    def reap_all(self) -> list[dict]:
        root = self.service.store.directory / "eye"
        out = []
        for profile in sorted(root.glob("chrome-*")) if root.is_dir() else []:
            if profile.is_dir():
                reaped = self.reap_orphan(profile.name[len("chrome-"):])
                if reaped:
                    out.append(reaped)
        return out

    def keep_warm(self) -> set[str]:
        raw = env("STEWARD_EYE_PREWARM", "").strip().lower()
        if not raw:
            return set()
        from .sites import SITE_IDS
        sites = set(SITE_IDS) if raw == "all" else {s.strip() for s in raw.split(",") if s.strip()}
        return sites & set(SITE_IDS)

    def check(self, renderers_fresh) -> None:
        """One supervision pass: GPU attempt that never registered → retry with SwiftShader; a page that registered and
        went silent → restart; idle → stop (except pre-warmed sites); exited → forget (pre-warmed sites start again)."""
        warm = self.keep_warm() if self.enabled else set()
        for site_id, proc in list(self.procs.items()):
            if proc["popen"].poll() is not None:
                with self.lock:
                    self.procs.pop(site_id, None)
                continue
            age = time.monotonic() - proc["started"]
            seen = bool(renderers_fresh(site_id, headless=True))
            if seen:
                proc["seen"] = time.monotonic()
            if proc["mode"] == "gpu" and age > GPU_REGISTER_GRACE_SECONDS and not seen and not proc.get("seen"):
                self.stop(site_id, "GPU renderer never registered; retrying with SwiftShader")
                self.start(site_id, "swiftshader")
                continue
            if proc.get("seen") and not seen and time.monotonic() - proc["seen"] > RENDERER_LOST_SECONDS:
                mode = proc["mode"]
                self.stop(site_id, "renderer page stopped answering; restarting")
                self.start(site_id, mode)
                continue
            if site_id not in warm and time.monotonic() - proc["lastUsed"] > IDLE_STOP_SECONDS:
                self.stop(site_id, "idle for 5 minutes")
        for site_id in sorted(warm - set(self.procs)):
            if not renderers_fresh(site_id):
                self.start(site_id, "gpu")

    def close(self) -> None:
        with self.lock:
            procs = list(self.procs.items())
            self.procs.clear()
        for _site_id, proc in procs:
            self._signal(proc, signal.SIGTERM)
        deadline = time.monotonic() + 2.5
        for site_id, proc in procs:
            self._settle(proc, deadline - time.monotonic())
            try:
                self.service.store.event(site_id, "director", "eye.worker_stopped", "Headless renderer stopped", f"pid {proc['pid']} (backend shutdown)")
            except Exception:
                pass


class EyeService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.Lock()
        self.renderers: dict[str, dict[str, dict]] = {}
        self.command_waiters: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}
        self.done_events: dict[str, threading.Event] = {}
        self.done_waiters: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}
        self.worker = EyeWorker(service)
        self.frames_dir = self.store.directory / "eye" / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()
        self._thread = None
        if service.start_workers:
            self._thread = threading.Thread(target=self._supervise, name="steward-eye-worker", daemon=True)
            self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self.worker.close()

    def _supervise(self):
        if self.worker.enabled:
            try:
                self.worker.reap_all()
            except Exception as error:
                self.store.event("myer-plant", "director", "eye.worker_failed", "Eye worker reaping failed", type(error).__name__)
        while not self._stop.wait(5):
            try:
                self.worker.check(self.fresh)
            except Exception as error:
                self.store.event("myer-plant", "director", "eye.worker_failed", "Eye worker supervision failed", type(error).__name__)

    # ---- renderers ------------------------------------------------------------------------------------------

    def register(self, site_id: str, renderer_id: str, kind: str | None = None, user_agent: str | None = None) -> dict:
        self.service.require_property(site_id)
        if not renderer_id or len(renderer_id) > 80:
            raise RealityError("rendererId is required (≤ 80 characters).", "INVALID_REQUEST", "Send a stable id per open viewer.")
        kind = kind or ("headless" if renderer_id.startswith("headless") else "browser")
        with self.lock:
            site = self.renderers.setdefault(site_id, {})
            entry = site.get(renderer_id) or dict(rendererId=renderer_id, siteId=site_id, kind=kind, registeredAt=now())
            entry.update(lastSeen=time.monotonic(), lastSeenAt=now(), kind=kind, userAgent=(user_agent or "")[:160] or entry.get("userAgent"))
            site[renderer_id] = entry
        return dict(registered=True, rendererId=renderer_id, siteId=site_id, kind=kind, heartbeatSeconds=5, staleAfterSeconds=HEARTBEAT_STALE_SECONDS)

    def fresh(self, site_id: str, headless: bool | None = None) -> list[dict]:
        cutoff = time.monotonic() - HEARTBEAT_STALE_SECONDS
        with self.lock:
            entries = list(self.renderers.get(site_id, {}).values())
        return [{k: v for k, v in e.items() if k != "lastSeen"} for e in entries
                if e["lastSeen"] >= cutoff and (headless is None or (e["kind"] == "headless") == headless)]

    # ---- commands -------------------------------------------------------------------------------------------

    def _seq(self, site_id: str, name: str) -> int:
        with self.store.lock:
            value = int(self.store.meta(f"eye:{name}:{site_id}") or 0) + 1
            self.store.meta(f"eye:{name}:{site_id}", str(value))
            return value

    def enqueue(self, site_id: str, action: str, params: dict, actor: str) -> dict:
        expected = int(params.get("frames", 1)) if action == "orbit" else 1
        command = dict(id=uid("eyc"), seq=self._seq(site_id, "seq"), siteId=site_id, action=action, params=params, actor=actor,
                       actorName=display_name(actor), status="queued", expectedFrames=expected, frameIds=[], rendererId=None,
                       createdAt=now(), completedAt=None)
        self.store.put("eye_command", command, site_id)
        with self.lock:
            self.done_events[command["id"]] = threading.Event()
            waiters = self.command_waiters.pop(site_id, [])
        for loop, event in waiters:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass
        return command

    def pending(self, site_id: str, since: int) -> list[dict]:
        horizon = 90.0
        out = []
        for command in self.store.all("eye_command", site_id):
            if command["seq"] <= since or command["status"] != "queued":
                continue
            out.append(command)
        out.sort(key=lambda c: c["seq"])
        return [c for c in out if self._age(c) <= horizon]

    @staticmethod
    def _age(command: dict) -> float:
        from .verify import parse_time
        created = parse_time(command["createdAt"])
        if not created:
            return 0.0
        from datetime import datetime, timezone
        return (datetime.now(timezone.utc) - created).total_seconds()

    async def poll_commands(self, site_id: str, renderer_id: str, since: int, timeout: float) -> dict:
        self.register(site_id, renderer_id)
        timeout = max(0.0, min(float(timeout), COMMAND_LONG_POLL_MAX))
        commands = self.pending(site_id, since)
        if not commands and timeout > 0:
            loop = asyncio.get_running_loop()
            event = asyncio.Event()
            with self.lock:
                self.command_waiters.setdefault(site_id, []).append((loop, event))
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            finally:
                with self.lock:
                    self.command_waiters[site_id] = [(l, e) for l, e in self.command_waiters.get(site_id, []) if e is not event]
            commands = self.pending(site_id, since)
        return dict(siteId=site_id, rendererId=renderer_id, latest=int(self.store.meta(f"eye:seq:{site_id}") or 0), commands=commands)

    # ---- frames ---------------------------------------------------------------------------------------------

    def post_frame(self, site_id: str, command_id: str, jpeg_base64: str, camera: dict | None, visible_pins: list | None,
                   renderer_id: str | None = None, index: int | None = None, annotation: dict | None = None) -> dict:
        command = self.store.get("eye_command", command_id, site_id)
        if not command:
            raise RealityError("Eye command not found for this site.", "NOT_FOUND", "Post frames for commands from GET /api/eye/{siteId}/commands.", 404)
        if command["status"] != "queued":
            return dict(accepted=False, reason=f"command already {command['status']}", commandId=command_id)
        if command.get("rendererId") and renderer_id and command["rendererId"] != renderer_id:
            return dict(accepted=False, reason="another renderer is producing this command", commandId=command_id)
        try:
            data = base64.b64decode((jpeg_base64 or "").split(",", 1)[-1], validate=False)
        except (ValueError, TypeError):
            raise RealityError("jpegBase64 is not valid base64.", "INVALID_REQUEST", "Send the canvas JPEG as base64 or a data URL.")
        if len(data) > MAX_FRAME_BYTES or data[:3] != b"\xff\xd8\xff":
            raise RealityError("Frame must be a JPEG under 3 MB.", "INVALID_REQUEST", "Capture the canvas with toDataURL('image/jpeg').")
        frame_id = uid("eyf")
        (self.frames_dir / f"{frame_id}.jpg").write_bytes(data)
        pins = []
        for pin in (visible_pins or [])[:64]:
            if isinstance(pin, dict) and pin.get("assetTag"):
                pins.append({k: pin.get(k) for k in ("assetTag", "x", "y", "distance", "occluded")})
        annotation = self._clean_annotation(annotation)
        survey = (command.get("params") or {}).get("purpose") == "survey"
        frame = dict(id=frame_id, seq=self._seq(site_id, "frame"), siteId=site_id, commandId=command_id, action=command["action"], params=command["params"],
                     actor=command["actor"], actorName=command["actorName"], camera=camera if isinstance(camera, dict) else None, visiblePins=pins,
                     index=int(index) if isinstance(index, int) else len(command["frameIds"]), rendererId=renderer_id, size=len(data),
                     sha256=hashlib.sha256(data).hexdigest(), url=f"/api/eye/frames/{frame_id}.jpg", at=now(),
                     annotation=annotation, survey=survey, purpose=(command.get("params") or {}).get("purpose"))
        self.store.put("eye_frame", frame, site_id)
        self.service.reality.mirror.put("eye_frame", frame, site_id)
        command["frameIds"].append(frame_id)
        command["rendererId"] = command.get("rendererId") or renderer_id
        if len(command["frameIds"]) >= command["expectedFrames"]:
            command.update(status="done", completedAt=now())
        self.store.put("eye_command", command, site_id)
        if command["status"] == "done":
            self._signal_done(command_id)
        return dict(accepted=True, frameId=frame_id, frameUrl=frame["url"], commandId=command_id, commandStatus=command["status"])

    @staticmethod
    def _clean_annotation(annotation) -> dict | None:
        """The mark record a renderer posts: screen x/y (0-1), the picked `world` point ([x, y, z] or {x, y, z}), `hit`
        (true when the depth pick hit the scan, false for a point along the ray) and the note."""
        if not isinstance(annotation, dict):
            return None
        from .viewer import _vec3
        out = {}
        for key in ("x", "y"):
            value = annotation.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                out[key] = round(float(value), 4)
        point = _vec3(annotation.get("world"))
        world = dict(x=point[0], y=point[1], z=point[2]) if point else None  # same {x, y, z} shape as pins
        out["world"] = world
        out["hit"] = bool(annotation.get("hit")) if world else False
        if annotation.get("note") is not None:
            out["note"] = str(annotation.get("note"))[:300]
        return out

    def _signal_done(self, command_id: str) -> None:
        with self.lock:
            event = self.done_events.get(command_id)
            waiters = self.done_waiters.pop(command_id, [])
        if event:
            event.set()
        for loop, async_event in waiters:
            try:
                loop.call_soon_threadsafe(async_event.set)
            except RuntimeError:
                pass

    def frame_path(self, frame_id: str) -> Path:
        if not frame_id.startswith("eyf-") or not all(c.isalnum() or c == "-" for c in frame_id):
            raise RealityError("Frame not found.", "NOT_FOUND", "Use a frame id from the feed.", 404)
        path = self.frames_dir / f"{frame_id}.jpg"
        if not path.is_file():
            raise RealityError("Frame not found.", "NOT_FOUND", "Use a frame id from the feed.", 404)
        return path

    def feed(self, site_id: str, since: int = 0, limit: int = 50, exclude_survey: bool = False) -> dict:
        self.service.require_property(site_id)
        frames = sorted((f for f in self.store.all("eye_frame", site_id) if f["seq"] > since and not (exclude_survey and f.get("survey"))),
                        key=lambda f: f["seq"])[-limit:]
        last = frames[-1] if frames else None
        return dict(siteId=site_id, latest=int(self.store.meta(f"eye:frame:{site_id}") or 0), frames=frames,
                    operating=dict(actor=last["actor"], actorName=last["actorName"], action=last["action"], at=last["at"]) if last else None,
                    renderers=self.fresh(site_id), worker=self.worker.status().get(site_id))

    # ---- act --------------------------------------------------------------------------------------------------

    def validate(self, site_id: str, action: str, params: dict) -> dict:
        if action not in ACTIONS:
            raise RealityError(f"action must be one of: {', '.join(ACTIONS)}.", "INVALID_REQUEST", "Pick look, move, turn, go_to, orbit or mark.")
        params = dict(params or {})
        clean: dict = {}
        if action == "move":
            if params.get("direction") not in DIRECTIONS:
                raise RealityError("direction must be forward, back, left, right, up or down.", "INVALID_REQUEST", "Send a direction.")
            clean = dict(direction=params["direction"], meters=_finite(params.get("meters", 1), 0.1, 5, "meters"))
        elif action == "turn":
            clean = dict(yawDeg=_finite(params.get("yawDeg", 0), -180, 180, "yawDeg"), pitchDeg=_finite(params.get("pitchDeg", 0), -89, 89, "pitchDeg"))
        elif action in ("go_to", "orbit"):
            from .viewer import parse_view_pose
            component = self.service.reality.component_by_tag(site_id, str(params.get("assetTag") or ""))
            clean = dict(assetTag=component["tag"], target=component.get("pin"), pinSource=component.get("pinSource", "estimated"))
            if params.get("viewPose") is not None:
                pose = parse_view_pose(params["viewPose"])
                if pose is None:
                    raise RealityError("viewPose needs position and target as [x, y, z] within ±1000 m, apart, and fov 10-120 if given.",
                                       "INVALID_REQUEST", "Omit viewPose to use the asset's stored pose.")
                clean.update(viewPose=pose, viewPoseSource="request")
            elif component.get("viewPose"):
                stored = component["viewPose"]
                clean.update(viewPose=dict(position=stored["position"], target=stored["target"], fov=stored.get("fov")), viewPoseSource="asset")
            if params.get("distance") is not None:
                clean["distance"] = _finite(params["distance"], 0.4, 8, "distance")
            if action == "orbit":
                frames = params.get("frames", 8)
                if not isinstance(frames, int) or isinstance(frames, bool) or not 4 <= frames <= 16:
                    raise RealityError("frames must be an integer from 4 to 16.", "INVALID_REQUEST", "Send frames: 8.")
                clean["frames"] = frames
        elif action == "mark":
            clean = dict(x=_finite(params.get("x"), 0, 1, "x"), y=_finite(params.get("y"), 0, 1, "y"), note=str(params.get("note") or "")[:300],
                         issue=bool(params.get("issue")), severity=params.get("severity") if params.get("severity") in ("low", "medium", "high") else "low")
        purpose = params.get("purpose")
        if purpose is not None:
            if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 40:
                raise RealityError("purpose must be a short label such as survey.", "INVALID_REQUEST", "Send purpose: survey for placement surveys.")
            clean["purpose"] = purpose.strip().lower()
        return clean

    def prepare(self, site_id: str, action: str, params: dict, actor: str) -> dict:
        self.service.require_property(site_id)
        actor = authorize(actor, "eye", site_id)
        clean = self.validate(site_id, action, params)
        renderer = None
        if not self.fresh(site_id):
            renderer = self.worker.ensure(site_id)
        else:
            self.worker.touch(site_id)
        cold = bool(renderer and (renderer.get("started") or renderer.get("running")))
        return dict(command=self.enqueue(site_id, action, clean, actor), worker=renderer, cold=cold)

    def timeout_for(self, command: dict, cold: bool = False) -> float:
        base = float(env("STEWARD_EYE_ACT_TIMEOUT", str(ACT_TIMEOUT_SECONDS)) or ACT_TIMEOUT_SECONDS)
        extra = (command["expectedFrames"] - 1) * 2.0
        if cold:
            start = float(env("STEWARD_EYE_COLD_START_TIMEOUT", str(COLD_START_TIMEOUT_SECONDS)) or COLD_START_TIMEOUT_SECONDS)
            return min(max(base, start) + extra, MAX_COLD_ACT_SECONDS)
        return min(base + extra, 60.0)

    def _hopeless(self, site_id: str, prepared: dict) -> bool:
        """Nothing can answer this act: no renderer is registered and the headless worker it relied on has exited."""
        if not prepared.get("cold") or self.fresh(site_id):
            return False
        return not self.worker.running(site_id)

    def finish(self, command_id: str, site_id: str, worker: dict | None, waited: float | None = None) -> dict:
        command = self.store.get("eye_command", command_id, site_id)
        if command["status"] != "done":
            command.update(status="expired", completedAt=now())
            self.store.put("eye_command", command, site_id)
            renderers = self.fresh(site_id)
            if renderers:
                hint = "A renderer is registered but did not answer in time."
            elif worker and (worker.get("started") or worker.get("running")):
                state = "is still starting; call again in a moment" if self.worker.running(site_id) else "exited before it registered"
                hint = f"No renderer is open; the headless renderer (pid {worker.get('pid')}) {state}. Its log is data/eye/chrome-{site_id}.log."
            elif worker:
                hint = f"No renderer is open; headless worker: {worker.get('reason')}."
            else:
                hint = "No renderer is open."
            self.service.telemetry.record(command["actor"], "eye", f"eye_{command['action']}", tokens=60, ok=False, site_id=site_id,
                                          detail=f"timeout: {hint}"[:200])
            seconds = waited if waited is not None else self.timeout_for(command)
            raise RealityError(f"No frame within {seconds:g} s for eye {command['action']}. {hint}", "EYE_TIMEOUT",
                               "Open /eye?site=<id> in a browser, or let the backend start the headless renderer (STEWARD_EYE_AUTOSTART=true).", 504)
        frames = [self.store.get("eye_frame", fid, site_id) for fid in command["frameIds"]]
        frames = [f for f in frames if f]
        self.service.telemetry.record(command["actor"], "eye", f"eye_{command['action']}", tokens=IMAGE_TOKENS * len(frames) + 60, site_id=site_id,
                                      detail=f"{command['action']} {command['params'].get('assetTag') or command['params'].get('direction') or ''}".strip()[:200])
        self.worker.touch(site_id)
        result = self.shape(command, frames)
        if command["action"] == "mark":
            annotation = self.annotate(site_id, command, frames[0] if frames else None)
            result.update(annotation=annotation, world=annotation["world"], hit=annotation.get("hit", False))
        survey = command["params"].get("purpose") == "survey"
        if survey:
            result["survey"] = True
        self.service.reality.emit_change(site_id, "eye", command["id"], f"{command['actorName']} eye {command['action']}"
                                         + (f" {command['params'].get('assetTag')}" if command["params"].get("assetTag") else "") + f": {len(frames)} frame(s).",
                                         command["params"].get("assetTag"),
                                         extra=dict(frameId=frames[0]["id"] if frames else None, commandId=command["id"], action=command["action"], actor=command["actor"],
                                                    survey=survey))
        return result

    @staticmethod
    def shape(command: dict, frames: list[dict]) -> dict:
        def one(frame):
            return dict(frameId=frame["id"], frameUrl=frame["url"], camera=frame["camera"], visiblePins=frame["visiblePins"], actor=frame["actor"], at=frame["at"],
                        index=frame["index"])
        base = dict(commandId=command["id"], action=command["action"], actor=command["actor"], actorName=command["actorName"], params=command["params"])
        if command["action"] == "orbit":
            return dict(base, frames=[one(f) for f in sorted(frames, key=lambda f: f["index"])])
        return dict(base, **one(frames[0])) if frames else base

    def annotate(self, site_id: str, command: dict, frame: dict | None) -> dict:
        params = command["params"]
        nearest = None
        if frame and frame.get("visiblePins"):
            visible = [p for p in frame["visiblePins"] if not p.get("occluded") and isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float))]
            if visible:
                nearest = min(visible, key=lambda p: (p["x"] - params["x"]) ** 2 + (p["y"] - params["y"]) ** 2)["assetTag"]
        picked = (frame or {}).get("annotation") or {}
        annotation = dict(id=uid("eya"), siteId=site_id, screen=dict(x=params["x"], y=params["y"]), world=picked.get("world"), hit=bool(picked.get("hit")),
                          note=params["note"], actor=command["actor"], frameId=(frame or {}).get("id"), nearestAssetTag=nearest, issueId=None, at=now(),
                          survey=params.get("purpose") == "survey")
        if params.get("issue"):
            issue = self.service.issues.raise_issue(site_id, "eye_observation", params.get("severity", "low"),
                                                    f"Eye mark by {display_name(command['actor'])}: {params['note'] or 'observation'}"
                                                    + (f" (near {nearest})" if nearest else ""), asset_tag=nearest, source="eye", synthetic=False,
                                                    actor=command["actor"], issue_id=f"iss-eye-{annotation['id'][-12:]}",
                                                    extra=dict(candidate=True, frameIds=[(frame or {}).get("id")]))
            annotation["issueId"] = issue["id"]
        self.store.put("eye_annotation", annotation, site_id)
        return annotation

    async def act(self, site_id: str, action: str, params: dict, actor: str) -> dict:
        # prepare may launch Chrome (and stop a leftover one first): keep that off the event loop
        prepared = await asyncio.to_thread(self.prepare, site_id, action, params, actor)
        command = prepared["command"]
        waited = self.timeout_for(command, prepared["cold"])
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        with self.lock:
            done = self.done_events.get(command["id"])
            self.done_waiters.setdefault(command["id"], []).append((loop, event))
        deadline = loop.time() + waited
        gone = 0
        while not (done and done.is_set()):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=min(remaining, 1.0))
                break
            except asyncio.TimeoutError:
                pass
            gone = gone + 1 if self._hopeless(site_id, prepared) else 0
            if gone >= 3:  # three checks a second apart: a SwiftShader retry swaps the worker in well under that
                break
        with self.lock:
            self.done_waiters.pop(command["id"], None)
        return self.finish(command["id"], site_id, prepared["worker"], waited)

    def act_sync(self, site_id: str, action: str, params: dict, actor: str, timeout: float | None = None) -> dict:
        """Blocking variant for worker threads (fix workflow, forged tools). `timeout` is the warm wait; a cold act
        (the headless renderer had to start) waits at least the cold-start window."""
        prepared = self.prepare(site_id, action, params, actor)
        command = prepared["command"]
        waited = self.timeout_for(command, prepared["cold"]) if timeout is None else (
            max(timeout, self.timeout_for(command, True)) if prepared["cold"] else timeout)
        event = self.done_events.get(command["id"])
        if event:
            deadline = time.monotonic() + waited
            gone = 0
            while not event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or event.wait(min(remaining, 1.0)):
                    break
                gone = gone + 1 if self._hopeless(site_id, prepared) else 0
                if gone >= 3:
                    break
        return self.finish(command["id"], site_id, prepared["worker"], waited)
