#!/usr/bin/env python
"""Draft a Tool Forge tool (contract 6) with Claude: one structured-JSON request per task.

Default is --dry-run: it writes the prompt and the exact request body to backend/seed/synthetic/_prompts/forge-<slug>.json
and calls nothing. With --live it calls Claude (model claude-opus-5-5, effort high, structured output constrained by a
closed JSON Schema with no optional properties, server-side refusal fallbacks `fallbacks: "default"` under the
`server-side-fallback-2026-07-01` beta), turns the structured draft into a ForgedTool definition and posts it to the
local backend (`POST /api/tools/requests` with `generator: "claude-opus-5-5"`), optionally validating and testing it.
Approval and publishing stay with the site's manager (read-only tools) or the Operations Director (any write step).
Definitions are declarative only: allow-listed Steward ops and pure transforms; no generated code ever runs.

Usage (from the repository root; --live needs ANTHROPIC_API_KEY in the root .env and the backend running):
  backend/.venv/bin/python scripts/synth/forge.py --site myer-plant --agent myer-engineer --task "Which pumps ..."
  backend/.venv/bin/python scripts/synth/forge.py --request treq-1234            # the task of a recorded gap
  backend/.venv/bin/python scripts/synth/forge.py --request treq-1234 --live --validate --test
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PROMPTS = BACKEND / "seed" / "synthetic" / "_prompts"
MODEL = "claude-opus-5-5"
sys.path.insert(0, str(BACKEND))

# The prompt, the closed schema and the draft → definition mapping live in the backend now (live drafting runs there on its own,
# REALITY-CONTRACT-6.md + the Oct 18 automatic pipeline); this script keeps the dry-run and the by-hand --live path.
from src.forge_drafter import (FIELD_TYPES, SYSTEM, catalog_text, draft_schema, examples, request_body as _request_body,  # noqa: E402,F401
                               to_definition)

DRAFT_SCHEMA = draft_schema()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:48] or "task"


def request_body(site: str, agent: str, task: str) -> dict:
    return _request_body(site, agent, task, effort="high", model=MODEL)


def write_dry_run(name: str, body: dict, context: dict) -> Path:
    PROMPTS.mkdir(parents=True, exist_ok=True)
    path = PROMPTS / f"forge-{name}.json"
    path.write_text(json.dumps(dict(mode="dry-run", note="Request body only; nothing was sent.", context=context, request=body), ensure_ascii=False, indent=1))
    return path


def run_live(body: dict, context: dict, backend: str, validate: bool, test: bool, actor: str) -> dict:
    try:
        import anthropic
        import httpx
        from dotenv import load_dotenv
    except ImportError as error:
        raise SystemExit(f"Install the backend requirements first ({error.name}).")
    load_dotenv(ROOT / ".env")
    client = anthropic.Anthropic()
    response = client.beta.messages.create(**body)
    if response.stop_reason == "refusal":
        raise SystemExit(f"The draft request was declined ({getattr(response, 'stop_details', None)}); nothing was posted.")
    if response.stop_reason == "max_tokens":
        raise SystemExit("The draft hit max_tokens; shorten the task or raise max_tokens.")
    draft = json.loads(next(block.text for block in response.content if block.type == "text"))
    definition = to_definition(draft, context["task"])
    headers = {"X-Steward-Actor": actor}
    payload = dict(siteId=context["siteId"], agentId=context["agentId"], task=context["task"], draft=definition, generator=MODEL)
    if context.get("requestId"):
        payload["requestId"] = context["requestId"]
    posted = httpx.post(f"{backend}/api/tools/requests", json=payload, headers=headers, timeout=60)
    posted.raise_for_status()
    tool = posted.json()["tool"]
    if validate or test:
        tool = httpx.post(f"{backend}/api/tools/{tool['id']}/validate", headers=headers, timeout=60).json()
    if test and tool.get("status") == "validated":
        tool = httpx.post(f"{backend}/api/tools/{tool['id']}/test", headers=headers, timeout=120).json()
    return tool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", help="site id (myer-plant, bristol-pumps, tomioka-mill)")
    parser.add_argument("--agent", help="the agent that builds the tool (its own site's team member or the director)")
    parser.add_argument("--task", help="the task the agent could not answer")
    parser.add_argument("--request", help="a recorded tool request id (GET /api/tools/requests); supplies site, agent and task")
    parser.add_argument("--backend", default="http://127.0.0.1:8001", help="local backend URL (default %(default)s)")
    parser.add_argument("--actor", default="operator", help="X-Steward-Actor for the backend calls (default %(default)s)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="write the prompt and request body only (default)")
    mode.add_argument("--live", action="store_true", help="call Claude and post the draft to the backend")
    parser.add_argument("--validate", action="store_true", help="after a live draft, validate it")
    parser.add_argument("--test", action="store_true", help="after a live draft, validate and test it")
    args = parser.parse_args()
    context = dict(siteId=args.site, agentId=args.agent, task=args.task, requestId=args.request)
    if args.request:
        import httpx
        records = httpx.get(f"{args.backend}/api/tools/requests", timeout=30).json()
        record = next((r for r in records if r["id"] == args.request), None)
        if not record:
            raise SystemExit(f"No tool request {args.request} at {args.backend}.")
        context.update(siteId=record["siteId"], agentId=record["agentId"], task=record["task"])
    if not (context["siteId"] and context["agentId"] and context["task"]):
        parser.error("give --request, or --site, --agent and --task")
    body = request_body(context["siteId"], context["agentId"], context["task"])
    if args.live:
        tool = run_live(body, context, args.backend, args.validate, args.test, args.actor)
        print(f"drafted {tool.get('mcpName') or tool.get('name')} ({tool.get('id')}): status {tool.get('status')}")
    else:
        print(f"dry run, request body at {write_dry_run(slug(context['task']), body, context)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
