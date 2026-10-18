"""Live drafting for the Tool Forge (contract 6; automatic since Oct 18 2026): when no prepared draft answers a task, the
builder asks Claude for a declarative recipe over the allow-listed Steward ops and pure transforms (no code ever runs),
and once more with the errors when validation or the test fails.

The prompt, the closed structured-output schema and `to_definition` used to live in `scripts/synth/forge.py`, which now
imports them from here. One Messages API call per draft or revision (claude-opus-5-5, `STEWARD_FORGE_EFFORT`, default
medium; structured JSON output; `fallbacks: "default"` under the server-side-fallback beta; no SDK retries), with daily
caps in the store: `STEWARD_FORGE_CLAUDE_MAX_CALLS_PER_DAY` (20) and `STEWARD_FORGE_CLAUDE_BUDGET_USD_PER_DAY` (3, priced
like walks.py). `STEWARD_FORGE_CLAUDE=false`, no ANTHROPIC_API_KEY, a cap or an API error: no draft, and the reason says
which; the request then waits for a draft as before.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .env import env
from .providers import clean_env

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORTS = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 16000
CALL_TIMEOUT_SECONDS = 150.0
BACKOFF_SECONDS = 60.0
DEFAULT_MAX_CALLS = 20
DEFAULT_BUDGET_USD = 3.0
USAGE_META = "forge:claude:"
MILLION = 1_000_000
SEED = Path(__file__).resolve().parents[1] / "seed" / "synthetic" / "forged_tools.json"
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


def draft_schema() -> dict:
    """Closed schema: every object sets additionalProperties false and every property is required (no optional properties);
    nullable values use a type list; no numeric or string constraints (structured outputs do not support them)."""
    from .forge import OPS, TRANSFORMS  # the allow-list the backend enforces (imported late: forge.py imports this module)
    return _row({
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


def catalog_text() -> str:
    from .forge import OPS
    lines = ["Ops (kind, args; required args first):"]
    for op, (kind, _action, args, required, returns) in OPS.items():
        lines.append(f"- {op} [{kind}] args {list(required)} + optional {[a for a in args if a not in required]} -> {returns}")
    lines.append("Pure transforms: filter {from, where}; map {from, <field>: template or 'if: <condition>'}; group_count {from, by, max?, min?, sum?} -> "
                 "[{<by>, count, first, max?, min?, sum?}]; sort {from, by, order: asc|desc}; take {from, count}; "
                 "join_on {left, right, on: 'leftField=rightField', as, mode: inner|left} (mode left keeps unmatched rows with <as> null); "
                 "concat {<any name>: list template, ...}.")
    lines.append("Templates: {{input.<name>}}, {{steps.<id>[.<field>]}} (earlier steps only), {{item.<field>}} inside per-item arguments "
                 "(map fields, filter where); pseudo-fields length, empty, first, last. A value that is exactly one template keeps its type.")
    lines.append("Conditions: '<field> <op> <value>' terms joined by all 'and' or all 'or'; ops == != > >= < <= in contains exists missing; "
                 "values: numbers, 'quoted text', true/false/null, [a, b], item.<field>. 'x missing' is true when x is null or absent.")
    lines.append("outputTemplate: '{{steps.<id>}}' for a list, or a JSON text such as '{\"items\": {{steps.x}}, \"ready\": {{steps.y.empty}}}'.")
    return "\n".join(lines)


def examples() -> str:
    seed = json.loads(SEED.read_text())
    return json.dumps([{k: r[k] for k in ("name", "task", "why", "description", "inputSchema", "steps", "output")} for r in seed["records"]],
                      ensure_ascii=False, indent=1)


def _body(prompt: str, effort: str, model: str) -> dict:
    return dict(model=model, max_tokens=MAX_TOKENS, system=SYSTEM, messages=[{"role": "user", "content": prompt}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": draft_schema()}},
                betas=[FALLBACK_BETA], fallbacks="default")


def request_body(site: str, agent: str, task: str, effort: str = "high", model: str = MODEL) -> dict:
    prompt = (f"Site: {site}. You are {agent}. Task you were given and could not answer with your current tools:\n{task}\n\n"
              f"{catalog_text()}\n\nTwo tools other agents built (the definition shape the backend stores; your answer uses the "
              f"structured fields of the schema instead):\n{examples()}\n\n"
              "Return the draft: a snake_case name, the description, the gap (why no existing tool answers the task), the tools you "
              "considered with why not, the inputs, the steps, the output shape and fields, the output template and a test input.")
    return _body(prompt, effort, model)


def revise_body(site: str, agent: str, task: str, definition: dict, errors: list[str], effort: str = DEFAULT_EFFORT, model: str = MODEL) -> dict:
    previous = {k: definition.get(k) for k in ("name", "description", "inputSchema", "steps", "output")}
    prompt = (f"Site: {site}. You are {agent}. You drafted a tool for this task:\n{task}\n\nYour draft:\n"
              f"{json.dumps(previous, ensure_ascii=False, indent=1)[:12000]}\n\nSteward's checks failed:\n- "
              + "\n- ".join(str(e)[:300] for e in errors[:12])
              + f"\n\n{catalog_text()}\n\nReturn a corrected draft that keeps the same name and answers the task exactly.")
    return _body(prompt, effort, model)


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


def _number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(env(name, str(default)) or default)
    except ValueError:
        return default
    return max(low, min(high, value))


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class ForgeDrafter:
    """Claude for the Tool Forge: one structured call per draft or revision, under daily caps; never raises."""

    def __init__(self, service, client=None):
        self.service = service
        self.store = service.store
        self.client = client  # tests inject a fake with `.beta.messages.create(**kwargs)`
        self._real = None
        self._fingerprint: str | None = None
        self.lock = threading.RLock()
        self.backoff_until = 0.0
        self.last_error: str | None = None

    @staticmethod
    def model() -> str:
        return (env("STEWARD_FORGE_MODEL", MODEL) or MODEL).strip() or MODEL

    @staticmethod
    def effort() -> str:
        value = (env("STEWARD_FORGE_EFFORT", DEFAULT_EFFORT) or DEFAULT_EFFORT).strip().lower()
        return value if value in EFFORTS else DEFAULT_EFFORT

    @staticmethod
    def max_calls() -> int:
        return int(_number("STEWARD_FORGE_CLAUDE_MAX_CALLS_PER_DAY", DEFAULT_MAX_CALLS, 0, 1000))

    @staticmethod
    def budget_usd() -> float:
        return _number("STEWARD_FORGE_CLAUDE_BUDGET_USD_PER_DAY", DEFAULT_BUDGET_USD, 0, 1000)

    def usage(self, day: str | None = None) -> dict:
        day = day or utc_day()
        base = dict(day=day, calls=0, errors=0, inputTokens=0, outputTokens=0, usd=0.0)
        try:
            stored = json.loads(self.store.meta(USAGE_META + day) or "{}")
        except ValueError:
            stored = {}
        base.update({k: v for k, v in stored.items() if k in base and k != "day" and isinstance(v, (int, float))})
        return base

    def _bump(self, **delta) -> None:
        with self.store.lock:
            current = self.usage()
            for key, value in delta.items():
                current[key] = round(current[key] + value, 6) if key == "usd" else int(current[key] + value)
            self.store.meta(USAGE_META + current["day"], json.dumps(current))

    def unavailable(self) -> str | None:
        """Why live drafting cannot run now, or None."""
        if (env("STEWARD_FORGE_CLAUDE", "true") or "true").strip().lower() != "true":
            return "live drafting is switched off (STEWARD_FORGE_CLAUDE=false)"
        if self.client is None and not clean_env("ANTHROPIC_API_KEY"):
            return "ANTHROPIC_API_KEY is not set"
        left = self.backoff_until - time.monotonic()
        if left > 0:
            return f"backing off after a Claude API error ({int(left) + 1} s left)"
        used = self.usage()
        if used["calls"] >= self.max_calls():
            return f"the daily drafting cap is reached ({used['calls']} of {self.max_calls()} calls today)"
        if used["usd"] >= self.budget_usd():
            return f"the daily drafting budget is spent (${used['usd']:.2f} of ${self.budget_usd():.2f} today)"
        return None

    def _client(self):
        if self.client is not None:
            return self.client
        key = clean_env("ANTHROPIC_API_KEY")
        fingerprint = hashlib.sha256(key.encode()).hexdigest()  # never keep or log the key itself
        with self.lock:
            if self._real is None or self._fingerprint != fingerprint:
                import anthropic
                self._real = anthropic.Anthropic(api_key=key, max_retries=0, timeout=CALL_TIMEOUT_SECONDS)
                self._fingerprint = fingerprint
            return self._real

    @staticmethod
    def _cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
        from .walks import PRICES
        price = PRICES.get(str(model or "")) or PRICES.get(MODEL)
        return (input_tokens * price["input"] + output_tokens * price["output"]) / MILLION if price else 0.0

    def _ask(self, body: dict, task: str) -> tuple[dict | None, str | None, dict]:
        reason = self.unavailable()
        if reason:
            return None, reason, {}
        started = time.monotonic()
        try:
            response = self._client().beta.messages.create(timeout=CALL_TIMEOUT_SECONDS, **body)
        except Exception as error:  # noqa: BLE001 - any API failure leaves the request waiting, never raises
            self.backoff_until = time.monotonic() + BACKOFF_SECONDS
            self.last_error = f"{type(error).__name__}: {str(error)[:200]}"
            self._bump(calls=1, errors=1)
            return None, f"the Claude call failed ({type(error).__name__})", {}
        usage = getattr(response, "usage", None)
        tokens_in, tokens_out = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
        served = getattr(response, "model", None) or body.get("model")
        cost = self._cost(served, tokens_in, tokens_out)
        self._bump(calls=1, inputTokens=tokens_in, outputTokens=tokens_out, usd=cost)
        meta = dict(model=served, ms=int((time.monotonic() - started) * 1000), inputTokens=tokens_in, outputTokens=tokens_out, usd=round(cost, 4))
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            return None, "the draft request was declined", meta
        if stop == "max_tokens":
            return None, "the draft hit the output limit", meta
        try:
            text = next(block.text for block in response.content if getattr(block, "type", None) == "text")
            return to_definition(json.loads(text), task), None, meta
        except (StopIteration, ValueError, KeyError, TypeError) as error:
            self._bump(errors=1)
            return None, f"the draft could not be read ({type(error).__name__})", meta

    def draft(self, site: str, agent: str, task: str) -> tuple[dict | None, str | None, dict]:
        return self._ask(request_body(site, agent, task, self.effort(), self.model()), task)

    def revise(self, site: str, agent: str, task: str, definition: dict, errors: list[str]) -> tuple[dict | None, str | None, dict]:
        return self._ask(revise_body(site, agent, task, definition, errors, self.effort(), self.model()), task)

    def status(self) -> dict:
        return dict(model=self.model(), effort=self.effort(), unavailable=self.unavailable(), usage=self.usage(), maxCalls=self.max_calls(),
                    budgetUsd=self.budget_usd(), lastError=self.last_error)
