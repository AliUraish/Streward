"""Eval runs: `POST /api/evals/run` spawns `node evals/run.mjs --json --mcp <url> --backend <self>` with the
project-local Node 24 and stores the result as kind `eval_run`. Local only: the MCP URL must be loopback.
`STEWARD_EVAL_RUNNER` overrides the command (tests use it); the override still receives `--json --mcp --backend`.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

from .env import env
from .errors import RealityError
from .sites import DEMO_SITE
from .store import now, uid

ROOT = Path(__file__).resolve().parents[2]
NODE = ROOT / "agent-runtime" / "node_modules" / "node" / "bin" / "node"
RUNNER = ROOT / "evals" / "run.mjs"
SUITES = {"demo-workflow": ROOT / "evals" / "demo-workflow.json"}
# Contract 3 suites, owned by the MCP stream; offered when their files exist (evals/<suite>.json).
OPTIONAL_SUITES = ("mission-workflow", "factory-workflow", "safety", "efficiency")


def suites() -> dict:
    found = dict(SUITES)
    for name in OPTIONAL_SUITES:
        path = ROOT / "evals" / f"{name}.json"
        if path.exists():
            found[name] = path
    return found
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


def is_loopback(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in ("http", "https") and (parsed.hostname or "") in LOOPBACK


class EvalRunner:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.Lock()

    def runs(self) -> list[dict]:
        return sorted(self.store.all("eval_run", ""), key=lambda r: r["startedAt"], reverse=True)

    def run_record(self, run_id: str) -> dict:
        record = self.store.get("eval_run", run_id, "")
        if not record:
            raise RealityError("Eval run not found.", "NOT_FOUND", "List runs with GET /api/evals.", 404)
        return record

    def command(self, mcp_url: str, backend_url: str, suite: str) -> list[str]:
        override = env("STEWARD_EVAL_RUNNER", "")
        base = shlex.split(override) if override else [str(NODE), str(RUNNER)]
        return base + ["--json", "--mcp", mcp_url, "--backend", backend_url, "--workflow", str(suites()[suite])]

    def start(self, suite: str, mcp_url: str | None = None, backend_url: str | None = None) -> dict:
        available = suites()
        if suite not in available:
            raise RealityError(f"Unknown suite '{suite[:40]}'.", "INVALID_REQUEST", "Use one of: " + ", ".join(sorted(available)) + ".")
        mcp_url = (mcp_url or env("STEWARD_MCP_URL", "http://127.0.0.1:8002/mcp")).strip()
        backend_url = (backend_url or env("STEWARD_SELF_URL", f"http://127.0.0.1:{env('BACKEND_PORT', '8001')}")).strip().rstrip("/")
        if not is_loopback(mcp_url) or not is_loopback(backend_url):
            raise RealityError("Evals run locally only; the MCP and backend URLs must be loopback.", "NOT_LOOPBACK",
                               "Use http://127.0.0.1:8002/mcp (STEWARD_MCP_URL) and a loopback backend URL.")
        if not env("STEWARD_EVAL_RUNNER", "") and not NODE.exists():
            raise RealityError("Project-local Node is missing (agent-runtime/node_modules/node/bin/node).", "NOT_CONFIGURED",
                               "Run npm install in agent-runtime, or set STEWARD_EVAL_RUNNER.")
        record = dict(id=uid("eval"), suite=suite, startedAt=now(), finishedAt=None, passed=0, failed=0, steps=[], state="running",
                      mcpUrl=mcp_url, backendUrl=backend_url, error=None)
        self.store.put("eval_run", record, "")
        if self.service.start_workers:
            threading.Thread(target=self._execute, args=(record["id"],), name="steward-eval", daemon=True).start()
        else:
            self._execute(record["id"])
        return self.run_record(record["id"])

    def _execute(self, run_id: str) -> None:
        record = self.run_record(run_id)
        try:
            completed = subprocess.run(self.command(record["mcpUrl"], record["backendUrl"], record["suite"]), cwd=ROOT, capture_output=True, text=True, timeout=600,
                                       env={**os.environ, "MCP_USE_ANONYMIZED_TELEMETRY": "false"})
            payload = None
            stdout = completed.stdout.strip()
            start = stdout.find("{")
            if start >= 0:
                try:
                    payload = json.loads(stdout[start:])
                except ValueError:
                    payload = None
            if payload is None:
                record.update(state="failed", error=f"runner exit {completed.returncode}; no JSON report: {(completed.stderr or stdout)[-400:]}")
            else:
                steps = [dict(name=row.get("id", "?"), target=row.get("target", ""), result="PASS" if row.get("ok") else "FAIL", ms=int(row.get("ms") or 0),
                              detail=str(row.get("detail") or "")[:500]) for row in payload.get("rows", [])]
                record.update(state="finished", steps=steps, passed=int(payload.get("passed", sum(s["result"] == "PASS" for s in steps))),
                              failed=int(payload.get("failed", sum(s["result"] == "FAIL" for s in steps))), suiteName=payload.get("name"))
        except subprocess.TimeoutExpired:
            record.update(state="failed", error="runner timed out after 600 s")
        except Exception as error:
            record.update(state="failed", error=f"runner could not start ({type(error).__name__})")
        record["finishedAt"] = now()
        with self.lock:
            self.store.put("eval_run", record, "")
        summary = f"Eval {record['suite']}: {record['passed']} passed, {record['failed']} failed" + (f" ({record['error']})" if record.get("error") else "")
        self.service.reality.emit_change(DEMO_SITE, "eval", record["id"], summary)
