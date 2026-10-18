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

from src.forge import OPS, TRANSFORMS  # noqa: E402  (the allow-list the backend enforces)

FIELD_TYPES = ["string", "number", "integer", "boolean", "string_or_null", "number_or_null", "rows"]
SYSTEM = (
    "You are a Steward site agent building a missing tool for yourself. Steward runs industrial and heritage sites from their 3D scans; "
    "agents call tools that read the site's records. You write a DECLARATIVE recipe only: a list of steps, each one allow-listed op "
    "(a Steward read or act) or a pure transform, with string arguments that are literals or templates. No code. Every op runs as you, "
    "at your own site only; never name a site in an argument. Prefer read ops; a step that acts (eye moves, dispatch, raising issues, "
    "moving the dashboard camera) makes the tool need the Operations Director's approval. Keep it to the fewest steps that answer the "
    "task exactly, and write the description for another agent: when to call it, what it costs, what to do next."
)


def _row(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


NAME_VALUE = _row({"name": {"type": "string"}, "value": {"type": "string"}}, ["name", "value"])
FIELD = _row({"name": {"type": "string"}, "type": {"type": "string", "enum": FIELD_TYPES}}, ["name", "type"])
# Closed schema: every object sets additionalProperties false and every property is required (0 optional properties, within
# the structured-output limit of 24); nullable values use a type list. No numeric or string constraints (not supported).
DRAFT_SCHEMA = _row({
    "name": {"type": "string"},
    "description": {"type": "string"},
    "gap": {"type": "string"},
    "consideredTools": {"type": "array", "items": _row({"name": {"type": "string"}, "whyNot": {"type": "string"}}, ["name", "whyNot"])},
    "inputs": {"type": "array", "items": _row({"name": {"type": "string"}, "type": {"type": "string", "enum": ["integer", "number", "string", "boolean"]},
                                               "description": {"type": "string"}, "defaultValue": {"type": ["string", "null"]},
                                               "required": {"type": "boolean"}}, ["name", "type", "description", "defaultValue", "required"])},
    "steps": {"type": "array", "items": _row({"id": {"type": "string"}, "op": {"type": "string", "enum": sorted(OPS) + sorted(TRANSFORMS)},
                                              "args": {"type": "array", "items": NAME_VALUE}}, ["id", "op", "args"])},
    "outputShape": {"type": "string", "enum": ["list", "object"]},
    "outputFields": {"type": "array", "items": FIELD},
    "rowFields": {"type": "array", "items": FIELD},
    "outputTemplate": {"type": "string"},
    "testInput": {"type": "array", "items": NAME_VALUE},
}, ["name", "description", "gap", "consideredTools", "inputs", "steps", "outputShape", "outputFields", "rowFields", "outputTemplate", "testInput"])


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:48] or "task"


def catalog_text() -> str:
    lines = ["Ops (kind, args; required args first):"]
    for op, (kind, _action, args, required, returns) in OPS.items():
        lines.append(f"- {op} [{kind}] args {list(required)} + optional {[a for a in args if a not in required]} -> {returns}")
    lines.append("Pure transforms: filter {from, where}; map {from, <field>: template or 'if: <condition>'}; group_count {from, by, max?, min?, sum?} -> "
                 "[{<by>, count, first, max?, min?, sum?}]; sort {from, by, order: asc|desc}; take {from, count}; "
                 "join_on {left, right, on: 'leftField=rightField', as, mode: inner|left}; concat {<any name>: list template, ...}.")
    lines.append("Templates: {{input.<name>}}, {{steps.<id>[.<field>]}} (earlier steps only), {{item.<field>}} inside per-item arguments "
                 "(map fields, filter where); pseudo-fields length, empty, first, last. A value that is exactly one template keeps its type.")
    lines.append("Conditions: '<field> <op> <value>' terms joined by all 'and' or all 'or'; ops == != > >= < <= in contains exists missing; "
                 "values: numbers, 'quoted text', true/false/null, [a, b], item.<field>.")
    lines.append("outputTemplate: '{{steps.<id>}}' for a list, or a JSON text such as '{\"items\": {{steps.x}}, \"ready\": {{steps.y.empty}}}'.")
    return "\n".join(lines)


def examples() -> str:
    seed = json.loads((BACKEND / "seed" / "synthetic" / "forged_tools.json").read_text())
    return json.dumps([{k: r[k] for k in ("name", "task", "why", "description", "inputSchema", "steps", "output")} for r in seed["records"]],
                      ensure_ascii=False, indent=1)


def request_body(site: str, agent: str, task: str) -> dict:
    prompt = (f"Site: {site}. You are {agent}. Task you were given and could not answer with your current tools:\n{task}\n\n"
              f"{catalog_text()}\n\nTwo tools other agents built (the definition shape the backend stores; your answer uses the "
              f"structured fields of the schema instead):\n{examples()}\n\n"
              "Return the draft: a snake_case name, the description, the gap (why no existing tool answers the task), the tools you "
              "considered with why not, the inputs, the steps, the output shape and fields, the output template and a test input.")
    return dict(model=MODEL, max_tokens=16000, system=SYSTEM, messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "high", "format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")


def _field_schema(kind: str, rows: dict | None = None) -> dict:
    if kind == "string_or_null":
        return {"type": ["string", "null"]}
    if kind == "number_or_null":
        return {"type": ["number", "null"]}
    if kind == "rows":
        return {"type": "array", "items": rows or _row({}, [])}
    return {"type": kind}


def _typed(value: str | None, kind: str):
    if value is None:
        return None
    if kind == "integer":
        return int(float(value))
    if kind == "number":
        return float(value)
    if kind == "boolean":
        return str(value).strip().lower() == "true"
    return value


def to_definition(draft: dict, task: str) -> dict:
    """The structured draft → the ForgedTool definition the backend validates."""
    properties, required = {}, []
    for spec in draft["inputs"]:
        prop = {"type": spec["type"], "description": spec["description"]}
        if spec.get("defaultValue") is not None:
            prop["default"] = _typed(spec["defaultValue"], spec["type"])
        properties[spec["name"]] = prop
        if spec.get("required"):
            required.append(spec["name"])
    rows = _row({f["name"]: _field_schema(f["type"]) for f in draft["rowFields"]}, [f["name"] for f in draft["rowFields"]])
    fields = _row({f["name"]: _field_schema(f["type"], rows) for f in draft["outputFields"]}, [f["name"] for f in draft["outputFields"]])
    schema = {"type": "array", "items": fields} if draft["outputShape"] == "list" else fields
    types = {spec["name"]: spec["type"] for spec in draft["inputs"]}
    return dict(name=draft["name"], description=draft["description"],
                why=dict(gap=draft["gap"], consideredTools=draft["consideredTools"], task=task),
                inputSchema={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                steps=[dict(id=s["id"], op=s["op"], args={a["name"]: a["value"] for a in s["args"]}) for s in draft["steps"]],
                output=dict(template=draft["outputTemplate"], schema=schema),
                test=dict(input={t["name"]: _typed(t["value"], types.get(t["name"], "string")) for t in draft["testInput"]}))


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
