"""Minimal Chrome DevTools Protocol client: launch headless Chrome, drive one tab over a websocket.

Only what capture.py needs (Page.navigate, Runtime.evaluate). Chrome is started with its own
temporary profile and stopped by the PID we launched; nothing else is touched.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SWIFTSHADER_FLAGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
# Hardware WebGL through ANGLE's Metal backend (macOS); --ignore-gpu-blocklist is added for both.
GPU_FLAGS = ["--use-angle=metal", "--enable-gpu-rasterization"]


class CDPError(RuntimeError):
    pass


class CDPClosed(CDPError):
    """Chrome closed the DevTools websocket (crashed, killed or exited)."""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_json(url: str, method: str = "GET", timeout: float = 3.0):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class Chrome:
    def __init__(self, chrome_path: str = DEFAULT_CHROME, headless: bool = True, window: str = "800,800",
                 extra_flags: list[str] | None = None, gl_flags: list[str] | None = None):
        if not Path(chrome_path).exists():
            raise CDPError(f"Chrome not found at {chrome_path}")
        self.chrome_path, self.headless, self.window = chrome_path, headless, window
        self.extra_flags = extra_flags or []
        self.gl_flags = SWIFTSHADER_FLAGS if gl_flags is None else gl_flags
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.profile = ""
        self.version: dict = {}

    def start(self, timeout: float = 30.0) -> "Chrome":
        self.port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="steward-vision-chrome-")
        args = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self.profile}",
            f"--window-size={self.window}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--disable-sync", "--mute-audio", "--hide-scrollbars",
            "--ignore-gpu-blocklist", "--enable-webgl",
            *self.gl_flags, *self.extra_flags,
        ]
        if self.headless:
            args.insert(1, "--headless=new")
        args.append("about:blank")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise CDPError(f"Chrome exited early with code {self.proc.returncode}")
            try:
                self.version = _get_json(f"http://127.0.0.1:{self.port}/json/version")
                return self
            except OSError:
                time.sleep(0.2)
        self.stop()
        raise CDPError(f"Chrome DevTools endpoint did not come up on port {self.port} within {timeout}s")

    def page_ws_url(self) -> str:
        targets = _get_json(f"http://127.0.0.1:{self.port}/json/list")
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            pages = [_get_json(f"http://127.0.0.1:{self.port}/json/new?about:blank", method="PUT")]
        return pages[0]["webSocketDebuggerUrl"]

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


class Session:
    """One websocket to one page target. Events are buffered (console/exception) for diagnostics."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._ids = itertools.count(1)
        self.console: list[str] = []

    async def __aenter__(self):
        self.ws = await websockets.connect(self.ws_url, max_size=None, ping_interval=None)
        return self

    async def __aexit__(self, *exc):
        await self.ws.close()

    async def send(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        msg_id = next(self._ids)
        try:
            await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        except websockets.ConnectionClosed as exc:
            raise CDPClosed(f"Chrome closed the DevTools connection during {method}: {exc}") from exc
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CDPError(f"CDP {method} timed out after {timeout}s")
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError) as exc:
                raise CDPError(f"CDP {method} timed out after {timeout}s (page busy?)") from exc
            except websockets.ConnectionClosed as exc:
                raise CDPClosed(f"Chrome closed the DevTools connection during {method}: {exc}") from exc
            msg = json.loads(raw)
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise CDPError(f"CDP {method} failed: {msg['error']}")
                return msg.get("result", {})
            self._event(msg)

    def _event(self, msg: dict) -> None:
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning"):
            text = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            self.console.append(f"console.{p['type']}: {text[:300]}")
        elif m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            self.console.append("exception: " + str(d.get("exception", {}).get("description") or d.get("text"))[:300])
        self.console = self.console[-20:]

    async def evaluate(self, expression: str, timeout: float = 60.0):
        res = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                   "awaitPromise": True}, timeout=timeout)
        if res.get("exceptionDetails"):
            raise CDPError(f"evaluate failed: {res['exceptionDetails'].get('text')}")
        return res.get("result", {}).get("value")
