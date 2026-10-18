"""Tool Forge (contract 6): an agent that lacks a tool builds one. Definitions are declarative; no generated code runs.

A `forged_tool` record:
`{id, name, version, status: draft | validated | tested | approved | published | rejected | retired, siteId, createdBy,
createdAt, approvedBy?, approvedAt?, why: {task, requestedBy, gap, consideredTools: [{name, whyNot}]}, description,
inputSchema, steps: [{id, op, args: {name: template}}], output: {template, schema}, readOnly, test?, usage: {calls,
lastCalledAt?, tokensSavedEstimate, history}, generator: claude-opus-5-5 | hand-seed, synthetic, requestId,
conversationId, validation?, rejection?, previousVersionId?, supersededBy?}`.

- `steps[].op` is one of `OPS` (existing Steward reads and acts, each mapped to the authority action it needs) or a pure
  transform (`filter`, `map`, `group_count`, `sort`, `take`, `join_on`, plus `concat`). Every op runs as the CREATING agent
  (`authorize(createdBy, action, tool.siteId)`), always against the tool's own site: no op accepts a site argument and a
  value naming another site fails validation, so a tool can never read or write outside its scope. The runner reads the
  local store only; no Supabase read happens here (a Supabase-backed op would have to use that agent's own token).
- Templates are dotted paths in `{{...}}` over `input.<name>`, `steps.<id>` (earlier steps only) and, inside per-item
  transform arguments, `item`; pseudo-fields `length`, `empty`, `first`, `last`. A value that is exactly one template
  keeps its type; anything else is string interpolation. Conditions (`filter.where`, a map field starting `if:`) are
  `path op value` terms joined by all-`and` or all-`or`; ops `== != > >= < <= in contains exists missing`; values are
  numbers, quoted strings, true/false/null, `[a, b]` lists or `item.<path>`.
- Lifecycle: request (gap and considered tools recorded; the matching hand-seeded draft, else a live Claude draft,
  forge_drafter.py) → validate → test (live local data; write ops are previewed, never executed) → approve (the site's
  manager for read-only tools, the Operations Director for any write; a refusal is recorded) → publish → call
  (`POST /api/tools/{id}/call` with the caller's actor; usage and telemetry) → retire. Automatic since Oct 18
  (`STEWARD_FORGE_AUTO`, default true): every draft goes through validate → test on its own (a failing Claude draft is
  revised once with the errors, else rejected); a read-only tool that passed is reviewed in a short chat between the
  builder and the site's manager, approved by the manager and published by the builder; a tool with any write step stops
  at `tested`, awaiting the Operations Director. It runs in a background thread with the workers, inline without. A new
  version of a name keeps the old one's usage history and supersedes it when published. Every step is a Change of type
  `tool` (wait events `tool.changed`, `tool.published`) and a line in the request's conversation (so it shows in both
  agents' transcripts).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from .agents import (DIRECTOR, OPERATOR, OWNER, authorize, compliance_id, display_name, engineer_id, is_known, manager_id, message_allowed,
                     site_of)
from .env import env
from .errors import RealityError
from .forge_drafter import MODEL as DRAFT_MODEL, ForgeDrafter
from .sites import SITE_BY_ID, SITE_IDS
from .store import now, uid
from .synthetic import load_family
from .telemetry import estimate_tokens

STATUSES = ("draft", "validated", "tested", "approved", "published", "rejected", "retired")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
STEP_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,24}$")
TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z_][\w-]*(?:\.[\w-]+)*)\s*\}\}")
MAX_STEPS = 20
MAX_INPUT_PROPERTIES = 24
MAX_ROWS = 5000
SCHEMA_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")
TRANSFORMS = {
    "filter": dict(args=("from", "where"), required=("from", "where"), item=("where",)),
    "map": dict(args=None, required=("from",), item="*"),
    "group_count": dict(args=("from", "by", "max", "min", "sum"), required=("from", "by"), item=()),
    "sort": dict(args=("from", "by", "order"), required=("from", "by"), item=()),
    "take": dict(args=("from", "count"), required=("from", "count"), item=()),
    "join_on": dict(args=("left", "right", "on", "as", "mode"), required=("left", "right", "on", "as"), item=()),
    "concat": dict(args=None, required=(), item=()),
}
# op -> (kind, authority action, allowed args, required args, what it returns). `act` ops change something (a camera
# move, a dispatch, an issue, a viewer command): a tool with one is not read-only and needs the Director's approval.
OPS = {
    "facts.list": ("read", "read", ("assetTag", "attribute"), (), "latest facts [{assetTag, attribute, value, unit, status, observedAt, attestationId, source}]"),
    "metrics.series": ("read", "read", ("series", "days", "step"), ("series",), "series [{key, assetTag, unit, label, spec, points}]"),
    "metrics.samples": ("read", "read", ("series", "days"), ("series",), "one row per 5-minute point [{assetTag, series, label, unit, at, value, min, max}]"),
    "issues.list": ("read", "read", ("status",), (), "issues [{id, assetTag, kind, severity, status, summary, ownerId, obligationId, regulationIds, regulation, source}]"),
    "obligations.list": ("read", "read", ("status",), (), "obligations [{id, assetTag, title, status, dueAt, ownerId, regulationIds, regulation}]; "
                                                        "status ok | due_soon (due within 14 days) | overdue | blocked; ownerId is a crew id"),
    "crew.list": ("read", "read", (), (), "crew [{id, name, role, onShift, owns}] (no contact details)"),
    "crew.responsible": ("read", "read", ("issueKind",), ("issueKind",), "{issueKind, owner: {id, name, role, onShift} | null, agent, agentName, fallback}"),
    "components.list": ("read", "read", (), (), "assets [{tag, id, name, kind, system, subsystem, description, status}]"),
    "regulations.list": ("read", "read", (), (), "binding regulations [{id, instrument, provision, title, appliesTo}]"),
    "conversations.list": ("read", "read", ("kind", "limit"), (), "conversations [{id, kind, topic, participants, status, startedAt, headline}]"),
    "maintenance.list": ("read", "read", (), (), "maintenance windows [{id, date, scope, status, siteIds, examiner, obligationId, assetTag}]; "
                                                    "status proposed | approved | done; obligationId is null for a window not booked for an obligation"),
    "resolve": ("read", "resolve", ("assetTag", "attribute", "budget"), ("assetTag", "attribute"),
                "{status, value, unit, attestationId, observedAt}; a budget above 0 dispatches a person (an act)"),
    "eye.go_to": ("act", "eye", ("assetTag",), ("assetTag",), "{frameId, frameUrl, visiblePins}: moves the agent eye"),
    "eye.look": ("act", "eye", (), (), "{frameId, frameUrl, visiblePins}: renders the current eye view"),
    "issues.raise": ("act", "raise_issue", ("kind", "severity", "summary", "assetTag"), ("kind", "severity", "summary"), "the issue record"),
    "viewer.focus": ("act", "viewer", ("assetTag",), ("assetTag",), "the viewer command: moves the dashboard camera"),
}
CATALOG = [  # the existing tools an agent looks at before it builds one (MCP names), for `consideredTools`
    ("get_metrics", "raw synthetic series for one site; no counting or joining"),
    ("who_is_responsible", "the owner of one issue kind at a time"),
    ("list_issues", "open issues without route membership or regulation"),
    ("list_obligations", "obligations, separately from issues"),
    ("get_facts", "latest facts per asset attribute"),
    ("list_components", "the asset register"),
    ("get_regulations", "regulations without asset links"),
    ("list_maintenance", "maintenance windows"),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- templates and conditions ------------------------------------------------------------------------------------

class _Missing:
    pass


MISSING = _Missing()


def resolve_path(path: str, scope: dict):
    parts = path.split(".")
    if parts[0] not in scope:
        return MISSING
    value = scope[parts[0]]
    for part in parts[1:]:
        if part == "length" and isinstance(value, (list, str, dict)):
            value = len(value)
        elif part == "empty" and isinstance(value, (list, str, dict)):
            value = len(value) == 0
        elif part in ("first", "last") and isinstance(value, list) and not (value and isinstance(value[0], dict) and part in value[0]):
            value = (value[0] if part == "first" else value[-1]) if value else None
        elif isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if index < len(value) else None
        else:
            return None
    return value


def render(template, scope: dict):
    """A template string: exactly one `{{path}}` keeps the value's type; otherwise each path is interpolated as text."""
    if not isinstance(template, str):
        return template
    whole = TEMPLATE_RE.fullmatch(template.strip())
    if whole:
        value = resolve_path(whole.group(1), scope)
        return None if value is MISSING else value

    def text(match):
        value = resolve_path(match.group(1), scope)
        if value is MISSING or value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if isinstance(value, float) and value.is_integer():
            return str(int(value)) if abs(value) < 1e15 else str(value)
        return str(value)
    return TEMPLATE_RE.sub(text, template)


def render_json(template: str, scope: dict):
    """The output template: each `{{path}}` is replaced by the JSON of its value, then the whole is parsed."""
    whole = TEMPLATE_RE.fullmatch(template.strip())
    if whole:
        value = resolve_path(whole.group(1), scope)
        return None if value is MISSING else value
    filled = TEMPLATE_RE.sub(lambda m: json.dumps(None if (v := resolve_path(m.group(1), scope)) is MISSING else v, ensure_ascii=False), template)
    try:
        return json.loads(filled)
    except ValueError as error:
        raise RealityError(f"The output template did not render to JSON ({error.msg}).", "TOOL_OUTPUT", "Fix output.template.")


_TOKEN_RE = re.compile(r"""\s*(?:("(?:[^"\\]|\\.)*")|('(?:[^'\\]|\\.)*')|(==|!=|>=|<=|>|<)|(\[|\]|,)|([^\s\[\],'"=!<>]+))""")
COMPARATORS = ("==", "!=", ">", ">=", "<", "<=", "in", "contains", "exists", "missing")


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens, position = [], 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if not match or match.end() == position:
            if text[position:].strip() == "":
                break
            raise RealityError(f"Cannot read the condition near '{text[position:position + 20]}'.", "TOOL_INVALID", "Write `field op value` terms.")
        position = match.end()
        if match.group(1) is not None:
            tokens.append(("str", json.loads(match.group(1))))
        elif match.group(2) is not None:
            tokens.append(("str", match.group(2)[1:-1].replace("\\'", "'")))
        elif match.group(3) is not None:
            tokens.append(("op", match.group(3)))
        elif match.group(4) is not None:
            tokens.append(("punct", match.group(4)))
        elif match.group(5) is not None:
            word = match.group(5)
            if word in ("and", "or"):
                tokens.append(("join", word))
            elif word in ("in", "contains", "exists", "missing"):
                tokens.append(("op", word))
            else:
                tokens.append(("word", word))
    return tokens


def _literal(token: tuple[str, str]):
    kind, value = token
    if kind == "str":
        return ("value", value)
    if value in ("true", "false"):
        return ("value", value == "true")
    if value == "null":
        return ("value", None)
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return ("value", float(value) if "." in value else int(value))
    if value.startswith("item."):
        return ("path", value[5:])
    return ("value", value)  # a bare word is a string (e.g. high)


def parse_condition(text: str) -> tuple[str, list]:
    """`path op value [and|or ...]` (no mixing of and/or) → (joiner, [(path, op, operand)])."""
    tokens = _tokens(text or "")
    terms, joiners, index = [], set(), 0
    while index < len(tokens):
        if tokens[index][0] != "word":
            raise RealityError(f"A condition term must start with a field name: {text[:80]}", "TOOL_INVALID", "Example: value > item.max.")
        path = tokens[index][1]
        path = path[5:] if path.startswith("item.") else path
        index += 1
        if index >= len(tokens) or tokens[index][0] != "op":
            raise RealityError(f"Missing comparison after '{path}'.", "TOOL_INVALID", "Use == != > >= < <= in contains exists missing.")
        op = tokens[index][1]
        index += 1
        operand = None
        if op not in ("exists", "missing"):
            if index >= len(tokens):
                raise RealityError(f"Missing value after '{path} {op}'.", "TOOL_INVALID", "Give the value to compare with.")
            if tokens[index] == ("punct", "["):
                items = []
                index += 1
                while index < len(tokens) and tokens[index] != ("punct", "]"):
                    if tokens[index] != ("punct", ","):
                        items.append(_literal(tokens[index])[1])
                    index += 1
                index += 1
                operand = ("value", items)
            elif op == "in":
                items = [_literal(tokens[index])[1]]
                index += 1
                while index + 1 < len(tokens) and tokens[index] == ("punct", ","):
                    items.append(_literal(tokens[index + 1])[1])
                    index += 2
                operand = ("value", items)
            else:
                operand = _literal(tokens[index])
                index += 1
        terms.append((path, op, operand))
        if index < len(tokens):
            if tokens[index][0] != "join":
                raise RealityError(f"Expected and/or in: {text[:80]}", "TOOL_INVALID", "Join terms with and, or with or (not both).")
            joiners.add(tokens[index][1])
            index += 1
            if index >= len(tokens):
                raise RealityError("A condition cannot end with and/or.", "TOOL_INVALID", "Finish the last term.")
    if not terms:
        raise RealityError("Empty condition.", "TOOL_INVALID", "Write at least one `field op value` term.")
    if len(joiners) > 1:
        raise RealityError("Do not mix and/or in one condition.", "TOOL_INVALID", "Split it into two filter steps.")
    return (joiners.pop() if joiners else "and"), terms


def _compare(left, op, right) -> bool:
    if op == "exists":
        return left is not None
    if op == "missing":
        return left is None
    if op == "contains":
        if isinstance(left, list):
            return right in left
        return isinstance(left, str) and isinstance(right, str) and right.casefold() in left.casefold()
    if op == "in":
        return left in (right or [])
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    try:
        if isinstance(left, bool) or isinstance(right, bool) or left is None or right is None:
            return False
        return {">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[op]
    except TypeError:
        return False


def evaluate(condition: tuple[str, list], item) -> bool:
    joiner, terms = condition
    results = []
    for path, op, operand in terms:
        left = resolve_path("item." + path, {"item": item})
        left = None if left is MISSING else left
        right = None
        if operand is not None:
            kind, value = operand
            right = resolve_path("item." + value, {"item": item}) if kind == "path" else value
            right = None if right is MISSING else right
        results.append(_compare(left, op, right))
    return all(results) if joiner == "and" else any(results)


# ---- a minimal JSON Schema check (types, properties, required, closed objects, items, enum) -------------------------

def schema_errors(value, schema: dict, path: str = "$") -> list[str]:
    if not isinstance(schema, dict):
        return []
    errors = []
    types = schema.get("type")
    allowed = [types] if isinstance(types, str) else list(types or [])
    if allowed:
        def is_type(kind):
            return {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
                    "boolean": isinstance(value, bool), "null": value is None,
                    "integer": isinstance(value, int) and not isinstance(value, bool) or (isinstance(value, float) and value.is_integer()),
                    "number": isinstance(value, (int, float)) and not isinstance(value, bool)}.get(kind, False)
        if not any(is_type(kind) for kind in allowed):
            return [f"{path}: expected {'/'.join(allowed)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"{path}.{key}: required")
        if schema.get("additionalProperties") is False:
            errors += [f"{path}.{key}: not allowed" for key in value if key not in properties]
        for key, item in value.items():
            if key in properties:
                errors += schema_errors(item, properties[key], f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value[:200]):
            errors += schema_errors(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if schema.get("minimum") is not None and value < schema["minimum"]:
            errors.append(f"{path}: below the minimum {schema['minimum']}")
        if schema.get("maximum") is not None and value > schema["maximum"]:
            errors.append(f"{path}: above the maximum {schema['maximum']}")
    return errors[:20]


def closed_schema_errors(schema, path: str = "$") -> list[str]:
    """Every object in an output/input schema must be closed (additionalProperties false) and typed."""
    if not isinstance(schema, dict):
        return [f"{path}: a schema must be an object"]
    types = schema.get("type")
    kinds = [types] if isinstance(types, str) else list(types or [])
    if not kinds or any(kind not in SCHEMA_TYPES for kind in kinds):
        return [f"{path}: type must be one of {', '.join(SCHEMA_TYPES)}"]
    errors = []
    if "object" in kinds:
        if schema.get("additionalProperties") is not False:
            errors.append(f"{path}: objects must set additionalProperties false")
        for key, sub in (schema.get("properties") or {}).items():
            errors += closed_schema_errors(sub, f"{path}.{key}")
        missing = [key for key in schema.get("required") or [] if key not in (schema.get("properties") or {})]
        if missing:
            errors.append(f"{path}: required names unknown properties {missing}")
    if "array" in kinds:
        if not isinstance(schema.get("items"), dict):
            errors.append(f"{path}: arrays must declare items")
        else:
            errors += closed_schema_errors(schema["items"], f"{path}[]")
    return errors


# ---- the service -------------------------------------------------------------------------------------------------

class ForgeService:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.lock = threading.RLock()
        self.drafter = ForgeDrafter(service)  # live Claude drafts and revisions (forge_drafter.py)
        self._advancing: set[str] = set()

    @staticmethod
    def auto_enabled() -> bool:
        """STEWARD_FORGE_AUTO (default true): drafts move through validate, test, approve and publish on their own."""
        return (env("STEWARD_FORGE_AUTO", "true") or "true").strip().lower() == "true"

    def _spawn(self, fn, *args) -> None:
        """A background thread with the workers; inline without (tests), so a call returns with the outcome."""
        if self.service.start_workers:
            threading.Thread(target=self._safely, args=(fn, *args), name="steward-forge", daemon=True).start()
        else:
            self._safely(fn, *args)

    def _safely(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as error:  # noqa: BLE001 - a broken pipeline step is recorded, never raised into the caller
            site = next((a for a in args if isinstance(a, str) and a in SITE_BY_ID), None) or SITE_IDS[0]
            self.store.event(site, "director", "forge.error", "Tool Forge pipeline stopped", f"{type(error).__name__}: {str(error)[:200]}")

    # ---- records ---------------------------------------------------------------------------------------------

    def get(self, tool_id: str) -> dict:
        record = self.store.get("forged_tool", tool_id)
        if not record:
            raise RealityError("Forged tool not found.", "NOT_FOUND", "List tools with GET /api/tools.", 404)
        return record

    def list(self, site_id: str | None = None, status: str | None = None, agent_id: str | None = None) -> list[dict]:
        if site_id:
            self.service.require_property(site_id)
        if status and status not in STATUSES:
            raise RealityError(f"status must be one of {', '.join(STATUSES)}.", "INVALID_REQUEST", "Pass ?status=published for example.")
        records = self.store.all("forged_tool", site_id) if site_id else self.store.all("forged_tool")
        if status:
            records = [r for r in records if r["status"] == status]
        if agent_id:
            records = [r for r in records if r["createdBy"] == agent_id]
        return sorted(records, key=lambda r: r["createdAt"], reverse=True)

    def requests(self, site_id: str | None = None) -> list[dict]:
        records = self.store.all("tool_request", site_id) if site_id else self.store.all("tool_request")
        return sorted(records, key=lambda r: r["at"], reverse=True)

    def request_record(self, request_id: str) -> dict:
        record = self.store.get("tool_request", request_id)
        if not record:
            raise RealityError("Tool request not found.", "NOT_FOUND", "List requests with GET /api/tools/requests.", 404)
        return record

    def _save(self, tool: dict) -> dict:
        tool["updatedAt"] = now()
        self.store.put("forged_tool", tool, tool["siteId"])
        return tool

    def _change(self, tool: dict, summary: str, step: str, actor: str) -> None:
        fields = dict(toolId=tool["id"], name=tool["name"], mcpName=self.mcp_name(tool), status=tool["status"], step=step, version=tool["version"],
                      actor=actor, requestId=tool.get("requestId"))
        self.service.reality.emit_change(tool["siteId"], "tool", tool["id"], summary[:480], extra=fields, fields=fields)
        self.service.telemetry.record(actor if actor != OWNER else OPERATOR, "tool", f"forge_{step}", text=summary, site_id=tool["siteId"],
                                      detail=f"{tool['id']} forge_{tool['name']} v{tool['version']}: {step}")

    @staticmethod
    def mcp_name(tool: dict) -> str:
        return f"forge_{tool['name']}"

    def public(self, tool: dict) -> dict:
        view = dict(tool)
        view["mcpName"] = self.mcp_name(tool)
        view["mcpDescription"] = self.mcp_description(tool)
        view["recipe"] = self.recipe(tool)
        return view

    def mcp_description(self, tool: dict) -> str:
        built = (tool.get("createdAt") or now())[:10]
        return (f"Built by {display_name(tool['createdBy'])} on {built} because {tool['why']['gap'].rstrip('.')}. "
                f"{tool['description']}")[:1500]

    @staticmethod
    def recipe(tool: dict) -> list[str]:
        """The steps as readable lines for the Tools page."""
        lines = []
        for step in tool.get("steps") or []:
            args = ", ".join(f"{key}={value}" for key, value in (step.get("args") or {}).items())
            lines.append(f"{step['id']}: {step['op']}({args})"[:300])
        return lines

    # ---- authority helpers ------------------------------------------------------------------------------------

    @staticmethod
    def _creator_scope(agent_id: str, site_id: str) -> None:
        if not is_known(agent_id) or agent_id in (OPERATOR, OWNER):
            raise RealityError("Tools are built by a Steward agent: the Operations Director or a site team member.", "INVALID_REQUEST",
                               "Pass agentId such as myer-engineer.")
        if agent_id != DIRECTOR and site_of(agent_id) != site_id:
            raise RealityError(f"{display_name(agent_id)} may only build tools for its own site ({site_of(agent_id)}), not {site_id}.",
                               "AUTHORITY_DENIED", "Ask that site's team, or the Operations Director.", 403)

    def _approver_ok(self, tool: dict, actor: str) -> None:
        if not tool["readOnly"]:
            if actor != DIRECTOR:
                raise RealityError(f"{display_name(actor)} may not approve {self.mcp_name(tool)}: it has a write step, which needs the Operations Director.",
                                   "AUTHORITY_DENIED", "Ask the Operations Director to approve it.", 403)
            return
        if actor not in (DIRECTOR, manager_id(tool["siteId"])):
            raise RealityError(f"{display_name(actor)} may not approve {self.mcp_name(tool)}; read-only tools are approved by "
                               f"{display_name(manager_id(tool['siteId']))} or the Operations Director.", "AUTHORITY_DENIED",
                               f"Send X-Steward-Actor as {manager_id(tool['siteId'])}.", 403)

    # ---- conversation lines -----------------------------------------------------------------------------------

    def _open_conversation(self, request: dict) -> None:
        conversations, bus = self.service.conversations, self.service.bus
        requester, agent, site = request["requestedBy"], request["agentId"], request["siteId"]
        conversation = conversations._new("message", requester, [requester, agent], [site], f"Tool request: {request['task'][:110]}",
                                          toolRequestId=request["id"], synthetic=bool(request.get("synthetic")))
        task = bus.send(requester, agent, request["task"], dict(kind="tool_request", toolRequestId=request["id"], conversationId=conversation["id"]),
                        site, context_id=conversation["contextId"], deliver=False)
        conversations._line(conversation, requester, request["task"], task)
        request.update(conversationId=conversation["id"], a2aTaskId=task["id"])

    def _say(self, request_id: str | None, speaker: str, text: str, final: bool = False) -> None:
        """One line in the request's conversation, carried on its A2A task (so both agents' transcripts show it)."""
        if not request_id:
            return
        request = self.store.get("tool_request", request_id)
        if not request or not request.get("conversationId"):
            return
        conversations, bus = self.service.conversations, self.service.bus
        conversation = conversations.get(request["conversationId"])
        task = bus.task(request["a2aTaskId"]) if request.get("a2aTaskId") else None
        data = dict(kind="tool_step", toolRequestId=request_id, conversationId=conversation["id"])
        if task and task["state"] not in ("completed", "failed", "canceled") and speaker in (task["caller"], task["target"]):
            if speaker == task["target"]:
                task = bus.reply(speaker, task["id"], "complete" if final else "progress", text, data, deliver=False)
            else:
                task = bus.message(speaker, task["id"], text, data, deliver=False)
        else:
            task = bus.send(speaker, request["agentId"] if speaker != request["agentId"] else request["requestedBy"], text, data, request["siteId"],
                            context_id=conversation["contextId"], deliver=False)
            if speaker not in conversation["participants"]:
                conversation["participants"].append(speaker)
        conversations._line(conversation, speaker, text, task)
        if final and conversation.get("status") != "ended":
            conversations._finish(conversation, None, None, f"Tool request closed: {text[:160]}")

    # ---- step 1 + 2: request and draft ---------------------------------------------------------------------------

    @staticmethod
    def default_agent(site_id: str, task: str) -> str:
        words = (task or "").casefold()
        if any(word in words for word in ("obligation", "regulation", "permit", "certificate", "compliance", "visitor route", "notice")):
            return compliance_id(site_id)
        return engineer_id(site_id)

    def considered(self, task: str) -> list[dict]:
        words = set(re.findall(r"[a-z]+", (task or "").casefold()))
        hints = {"get_metrics": {"metric", "metrics", "pressure", "spec", "series", "humidity", "breach", "breaches", "reading"},
                 "who_is_responsible": {"responsible", "owner", "who", "act"}, "list_issues": {"issue", "issues", "open"},
                 "list_obligations": {"obligation", "obligations", "overdue"}, "get_facts": {"fact", "facts", "value"},
                 "list_components": {"asset", "assets", "pumps", "route"}, "get_regulations": {"regulation", "regulations", "law"},
                 "list_maintenance": {"maintenance", "window"}}
        chosen = [dict(name=name, whyNot=why) for name, why in CATALOG if words & hints.get(name, set())]
        return chosen or [dict(name=name, whyNot=why) for name, why in CATALOG[:3]]

    def prepared_draft(self, site_id: str, agent_id: str, task: str, key: str | None = None) -> dict | None:
        """Build mode: the hand-seeded draft whose keywords the task matches (or named by `draftKey`)."""
        words = set(re.findall(r"[a-z]+", (task or "").casefold()))
        for draft in load_family("forged_tools"):
            if draft["siteId"] != site_id:
                continue
            if key and key in (draft["id"], draft["name"]):
                return draft
            if draft.get("createdBy") == agent_id and len(words & set(draft.get("match") or [])) >= 3:
                return draft
        return None

    def request(self, agent_id: str | None, site_id: str, task: str, actor: str, requested_by: str | None = None, draft: dict | None = None,
                generator: str | None = None, draft_key: str | None = None, request_id: str | None = None) -> dict:
        self.service.require_property(site_id)
        actor = authorize(actor, "read")
        task = (task or "").strip()
        if not request_id and not 8 <= len(task) <= 600:
            raise RealityError("task must be 8 to 600 characters.", "INVALID_REQUEST", "Describe what the agent was asked and could not answer.")
        with self.lock:
            existing = self.request_record(request_id) if request_id else None
            if existing:
                if existing.get("toolId"):
                    raise RealityError("This request already has a draft.", "INVALID_REQUEST", "Version the tool with a new request.", 409)
                if existing["siteId"] != site_id:
                    raise RealityError("The request belongs to another site.", "SCOPE", "Use the request's own site.", 409)
                request = existing
                agent_id, task = request["agentId"], request["task"]
            else:
                agent_id = agent_id or self.default_agent(site_id, task)
                self._creator_scope(agent_id, site_id)
                requester = requested_by or actor
                if not is_known(requester) or requester == OWNER:
                    requester = OPERATOR
                if requester == agent_id:
                    requester = OPERATOR if agent_id == DIRECTOR else DIRECTOR
                allowed, why_not = message_allowed(requester, agent_id)
                if not allowed:
                    raise RealityError(why_not, "AUTHORITY_DENIED", "Ask the site's own team, its manager through yours, or the Operations Director.", 403)
                request = dict(id=uid("treq"), siteId=site_id, agentId=agent_id, task=task, requestedBy=requester, at=now(), status="received",
                               toolId=None, consideredTools=self.considered(task), gap=None, synthetic=False)
                self.store.put("tool_request", request, site_id)
                self._open_conversation(request)
                self.store.put("tool_request", request, site_id)
            source = None
            if draft is not None:
                source, generator = draft, (generator or "claude-opus-5-5")
            else:
                prepared = self.prepared_draft(site_id, agent_id, task, draft_key)
                if prepared:
                    source, generator = prepared, "hand-seed"
            if source is None:
                blocked = self.drafter.unavailable() if self.auto_enabled() else "automatic drafting is off (STEWARD_FORGE_AUTO=false)"
                status = "drafting" if not blocked else "awaiting_draft"
                request.update(status=status, gap=f"No existing tool answers: {task[:200]}", draftError=blocked)
                self.store.put("tool_request", request, site_id)
                if blocked:
                    self._say(request["id"], agent_id, f"I don't have a tool for this. Recorded the gap; a draft is needed ({blocked}; "
                                                       f"scripts/synth/forge.py --request {request['id']} --live drafts it by hand).")
                else:
                    self._say(request["id"], agent_id, "I don't have a tool for this. Drafting one now from Steward's own operations with Claude; "
                                                       "it is checked, tested, reviewed by the site manager and published in a minute or two.")
                fields = dict(toolRequestId=request["id"], requestId=request["id"], status=status, step="request", actor=agent_id)
                self.service.reality.emit_change(site_id, "tool", request["id"], f"{display_name(agent_id)} recorded a tool gap: {task[:200]}",
                                                 extra=fields, fields=fields)
                drafting = not blocked
                result = dict(request=request, tool=None)
            else:
                drafting = False
                result = None
        if result is not None:
            if drafting:
                self._spawn(self._draft_then_advance, request["id"])
                request = self.request_record(request["id"])
                tool = self.store.get("forged_tool", request["toolId"]) if request.get("toolId") else None
                return dict(request=request, tool=self.public(tool) if tool else None)
            return result
        with self.lock:
            tool = self._from_draft(source, request, generator)
            request.update(status="drafted", toolId=tool["id"], gap=tool["why"]["gap"], consideredTools=tool["why"]["consideredTools"],
                           synthetic=tool["synthetic"])
            self.store.put("tool_request", request, site_id)
        considered = "; ".join(f"{c['name']} ({c['whyNot']})" for c in tool["why"]["consideredTools"][:3])
        self._say(request["id"], agent_id, f"I don't have a tool for this; drafting {self.mcp_name(tool)}. Considered: {considered}.")
        self._change(tool, f"{display_name(agent_id)} drafted {self.mcp_name(tool)} v{tool['version']} ({generator}) for: {task[:160]}", "draft", agent_id)
        self.service.memory.write(agent_id, f"Drafted {self.mcp_name(tool)} because {tool['why']['gap'][:200]}", "decision", dict(toolId=tool["id"]),
                                  site_id, synthetic=tool["synthetic"])
        if tool.get("auto"):
            self._spawn(self.advance, tool["id"])
            tool = self.get(tool["id"])  # inline (no workers): already published, rejected or awaiting the Director
        return dict(request=self.request_record(request["id"]), tool=self.public(tool))

    def _from_draft(self, source: dict, request: dict, generator: str) -> dict:
        name = str(source.get("name") or "").strip()
        if not NAME_RE.fullmatch(name):
            raise RealityError("A tool name is snake_case, 3 to 41 characters.", "TOOL_INVALID", "Example: pump_spec_breaches.")
        site = request["siteId"]
        versions = [t for t in self.store.all("forged_tool", site) if t["name"] == name]
        previous = max(versions, key=lambda t: t["version"]) if versions else None
        why = dict(source.get("why") or {})
        why.update(task=request["task"], requestedBy=request["requestedBy"])
        why.setdefault("gap", f"No existing tool answers: {request['task'][:200]}")
        why["consideredTools"] = [dict(name=str(c.get("name"))[:60], whyNot=str(c.get("whyNot"))[:240]) for c in (why.get("consideredTools") or request["consideredTools"])
                                  if isinstance(c, dict) and c.get("name")][:8]
        usage = dict(calls=0, lastCalledAt=None, tokensSavedEstimate=0, history=[])
        if previous:
            old = previous.get("usage") or {}
            usage = dict(calls=int(old.get("calls") or 0), lastCalledAt=old.get("lastCalledAt"), tokensSavedEstimate=int(old.get("tokensSavedEstimate") or 0),
                         history=list(old.get("history") or []) + [dict(version=previous["version"], toolId=previous["id"], calls=int(old.get("calls") or 0),
                                                                       tokensSavedEstimate=int(old.get("tokensSavedEstimate") or 0))])
        tool = dict(id=uid("tool"), name=name, version=(previous["version"] + 1) if previous else 1, status="draft", siteId=site, createdBy=request["agentId"],
                    createdAt=now(), approvedBy=None, approvedAt=None, why=why, **self.definition_fields(source),
                    usage=usage, generator=generator, synthetic=generator == "hand-seed" or bool(source.get("synthetic")), requestId=request["id"],
                    conversationId=request.get("conversationId"), previousVersionId=previous["id"] if previous else None, validation=None, rejection=None,
                    auto=self.auto_enabled(), revisions=0, drafting=source.get("drafting"))
        tool["readOnly"] = self.read_only(tool)
        return self._save(tool)

    @staticmethod
    def definition_fields(source: dict) -> dict:
        """The parts of a draft the builder writes (and a revision replaces): description, input schema, steps, output, test input."""
        return dict(description=str(source.get("description") or "")[:1200],
                    inputSchema=source.get("inputSchema") or {"type": "object", "properties": {}, "additionalProperties": False},
                    steps=[dict(id=str(s.get("id")), op=str(s.get("op")), args={str(k): (v if isinstance(v, str) else json.dumps(v)) for k, v in (s.get("args") or {}).items()})
                           for s in (source.get("steps") or []) if isinstance(s, dict)],
                    output=dict(template=str((source.get("output") or {}).get("template") or ""), schema=(source.get("output") or {}).get("schema") or {}),
                    readOnly=True, test=dict(input=(source.get("test") or {}).get("input") or {}, output=None, passed=False, ms=0, at=None, notes=[]))

    # ---- step 3: validate ------------------------------------------------------------------------------------

    @staticmethod
    def step_kind(step: dict) -> str:
        if step["op"] in TRANSFORMS:
            return "transform"
        if step["op"] not in OPS:
            return "unknown"
        kind = OPS[step["op"]][0]
        if step["op"] == "resolve":
            budget = str((step.get("args") or {}).get("budget", "0")).strip()
            return "read" if budget in ("", "0", "0.0") else "act"
        return kind

    def read_only(self, tool: dict) -> bool:
        return all(self.step_kind(step) in ("read", "transform") for step in tool.get("steps") or [])

    def check(self, tool: dict) -> list[str]:
        errors: list[str] = []
        site = tool["siteId"]
        if site not in SITE_BY_ID:
            errors.append(f"scope: unknown site {site}")
        try:
            self._creator_scope(tool["createdBy"], site)
        except RealityError as error:
            errors.append(f"scope: {error.detail}")
        if not NAME_RE.fullmatch(tool["name"]):
            errors.append("name: snake_case, 3 to 41 characters")
        if not tool.get("description") or len(tool["description"]) < 20:
            errors.append("description: tell an agent when to call it, what it costs and what to do next (at least 20 characters)")
        why = tool.get("why") or {}
        if not why.get("gap") or not why.get("task"):
            errors.append("why: task and gap are required")
        schema = tool.get("inputSchema") or {}
        if schema.get("type") != "object":
            errors.append("inputSchema: must be an object schema")
        properties = schema.get("properties") or {}
        if len(properties) > MAX_INPUT_PROPERTIES:
            errors.append(f"inputSchema: at most {MAX_INPUT_PROPERTIES} properties")
        errors += [f"inputSchema: {e}" for e in closed_schema_errors(schema)]
        errors += [f"output.schema: {e}" for e in closed_schema_errors((tool.get("output") or {}).get("schema"))]
        steps = tool.get("steps") or []
        if not 1 <= len(steps) <= MAX_STEPS:
            errors.append(f"steps: 1 to {MAX_STEPS} steps")
        seen: list[str] = []
        other_sites = [s for s in SITE_IDS if s != site]
        for step in steps:
            sid, op, args = step.get("id"), step.get("op"), step.get("args") or {}
            label = f"step {sid}"
            if not STEP_ID_RE.fullmatch(str(sid or "")) or sid in seen or sid in ("input", "item", "steps"):
                errors.append(f"{label}: ids are unique short snake_case names")
            if op not in OPS and op not in TRANSFORMS:
                errors.append(f"{label}: op '{op}' is not on the allow-list")
                seen.append(str(sid))
                continue
            allowed, required = (OPS[op][2], OPS[op][3]) if op in OPS else (TRANSFORMS[op]["args"], TRANSFORMS[op]["required"])
            for key in required:
                if key not in args:
                    errors.append(f"{label}: {op} needs {key}")
            for key, value in args.items():
                if allowed is not None and key not in allowed:
                    errors.append(f"{label}: {op} does not take '{key}'")
                if key.casefold() in ("siteid", "propertyid", "site", "property"):
                    errors.append(f"scope: {label} may not choose a site; every op runs at {site}")
                if any(other in str(value) for other in other_sites):
                    errors.append(f"scope: {label} names another site; a tool reads and writes only {site}")
                per_item = op in TRANSFORMS and (TRANSFORMS[op]["item"] == "*" and key != "from" or key in (TRANSFORMS[op]["item"] or ()))
                for path in TEMPLATE_RE.findall(str(value)):
                    root, _, rest = path.partition(".")
                    if root == "input":
                        if rest.split(".")[0] not in properties:
                            errors.append(f"{label}: {{{{{path}}}}} names an input the schema does not declare")
                    elif root == "steps":
                        if rest.split(".")[0] not in seen:
                            errors.append(f"{label}: {{{{{path}}}}} refers to a step that has not run yet")
                    elif root == "item":
                        if not per_item:
                            errors.append(f"{label}: {{{{{path}}}}} is only available inside per-item arguments")
                    else:
                        errors.append(f"{label}: {{{{{path}}}}} must start with input., steps. or item.")
            if op == "filter" or op == "map":
                for key, value in args.items():
                    text = str(value)
                    if op == "filter" and key == "where" or op == "map" and text.startswith("if:"):
                        try:
                            parse_condition(TEMPLATE_RE.sub("0", text[3:] if text.startswith("if:") else text))
                        except RealityError as error:
                            errors.append(f"{label}: {error.detail}")
            seen.append(str(sid))
        template = (tool.get("output") or {}).get("template") or ""
        if not template:
            errors.append("output.template: required")
        for path in TEMPLATE_RE.findall(template):
            root, _, rest = path.partition(".")
            if root != "steps" or rest.split(".")[0] not in seen:
                errors.append(f"output.template: {{{{{path}}}}} must name a step")
        return errors

    def validate(self, tool_id: str, actor: str) -> dict:
        actor = authorize(actor, "read")
        tool = self.get(tool_id)
        if tool.get("auto") and tool["status"] in ("validated", "tested", "approved", "published"):
            return self.public(tool)  # the automatic pipeline already validated it
        if tool["status"] not in ("draft", "validated", "tested", "rejected"):
            raise RealityError(f"{self.mcp_name(tool)} is {tool['status']}.", "INVALID_REQUEST", "Only drafts are validated; version a published tool.", 409)
        errors = self.check(tool)
        tool["readOnly"] = self.read_only(tool)
        checks = ["schema", "allow-listed ops", "templates resolve", f"scope {tool['siteId']}", "output schema closed"]
        tool["validation"] = dict(ok=not errors, errors=errors, checks=checks, readOnly=tool["readOnly"], at=now(), by=actor)
        if not errors:
            tool["status"] = "validated"
        self._save(tool)
        summary = (f"Validated {self.mcp_name(tool)}: {len(tool['steps'])} steps, all allow-listed, {'read-only' if tool['readOnly'] else 'has write steps'}, "
                   f"scoped to {tool['siteId']}." if not errors else f"Validation failed for {self.mcp_name(tool)}: {'; '.join(errors)[:300]}")
        self._say(tool.get("requestId"), tool["createdBy"], summary)
        self._change(tool, summary, "validate", tool["createdBy"])
        return self.public(tool)

    # ---- step 4: test ---------------------------------------------------------------------------------------

    def default_input(self, tool: dict) -> dict:
        values = {}
        for key, spec in ((tool.get("inputSchema") or {}).get("properties") or {}).items():
            if isinstance(spec, dict) and "default" in spec:
                values[key] = spec["default"]
        return values

    def test(self, tool_id: str, actor: str, sample: dict | None = None) -> dict:
        actor = authorize(actor, "read")
        tool = self.get(tool_id)
        if tool.get("auto") and tool["status"] in ("tested", "approved", "published") and sample is None:
            return self.public(tool)  # the automatic pipeline already tested it
        if tool["status"] not in ("validated", "tested"):
            raise RealityError(f"{self.mcp_name(tool)} is {tool['status']}; validate it first.", "INVALID_REQUEST", "POST /api/tools/{id}/validate.", 409)
        given = sample if sample is not None else (tool.get("test") or {}).get("input") or self.default_input(tool)
        args = {**self.default_input(tool), **(given or {})}
        notes: list[str] = []
        started = time.monotonic()
        try:
            output, trace, _ = self.execute(tool, args, dry_run=True)
            # A previewed write has no real output to check; the schema is checked on read-only output only.
            errors = [] if any(t.get("preview") for t in trace) else schema_errors(output, tool["output"]["schema"])
        except RealityError as error:
            output, trace, errors = None, [], [error.detail]
        ms = int((time.monotonic() - started) * 1000)
        if any(t.get("preview") for t in trace):
            notes.append("write steps were previewed, not executed, during the test; the output schema is checked when it runs")
        rows = len(output) if isinstance(output, list) else len(output.get("items", [])) if isinstance(output, dict) and isinstance(output.get("items"), list) else None
        notes.append(f"{len(trace)} step(s) ran on live local data" + (f"; {rows} row(s)" if rows is not None else ""))
        notes += errors[:5]
        tool["test"] = dict(input=given or {}, output=output, passed=not errors, ms=ms, at=now(), notes=notes, trace=trace)
        if not errors:
            tool["status"] = "tested"
        self._save(tool)
        summary = (f"Tested {self.mcp_name(tool)} on live data: " + (f"{rows} row(s) " if rows is not None else "") + f"in {ms} ms; output matches the schema."
                   if not errors else f"Test failed for {self.mcp_name(tool)}: {'; '.join(errors)[:300]}")
        self._say(tool.get("requestId"), tool["createdBy"], summary)
        self._change(tool, summary, "test", tool["createdBy"])
        return self.public(tool)

    # ---- step 5 + 6: approve, publish -------------------------------------------------------------------------

    def approve(self, tool_id: str, actor: str, approve: bool, reason: str = "") -> dict:
        actor = authorize(actor, "read")
        tool = self.get(tool_id)
        if approve and tool.get("auto") and tool["status"] in ("approved", "published"):
            return self.public(tool)  # the site manager already approved it in the automatic pipeline
        if tool["status"] != "tested":
            raise RealityError(f"{self.mcp_name(tool)} is {tool['status']}; only a tested tool is approved.", "INVALID_REQUEST", "Validate and test it first.", 409)
        self._approver_ok(tool, actor)
        if approve:
            tool.update(status="approved", approvedBy=actor, approvedAt=now(), rejection=None)
            summary = f"Approved {self.mcp_name(tool)} ({'read-only' if tool['readOnly'] else 'with write steps'})" + (f": {reason[:200]}" if reason else ".")
        else:
            if not (reason or "").strip():
                raise RealityError("A refusal needs a reason.", "INVALID_REQUEST", "Send {approve: false, reason}.")
            tool.update(status="rejected", rejection=dict(by=actor, reason=reason[:500], at=now()))
            summary = f"Refused {self.mcp_name(tool)}: {reason[:300]}"
        self._save(tool)
        self._say(tool.get("requestId"), actor, summary, final=not approve)
        self._change(tool, f"{display_name(actor)} {summary[0].lower()}{summary[1:]}", "approve" if approve else "reject", actor)
        self.service.memory.write(actor, summary, "decision", dict(toolId=tool["id"]), tool["siteId"], synthetic=tool["synthetic"])
        return self.public(tool)

    def publish(self, tool_id: str, actor: str) -> dict:
        actor = authorize(actor, "read")
        tool = self.get(tool_id)
        if tool.get("auto") and tool["status"] == "published":
            return self.public(tool)  # already published by the automatic pipeline
        if tool["status"] != "approved":
            raise RealityError(f"{self.mcp_name(tool)} is {tool['status']}; only an approved tool is published.", "INVALID_REQUEST", "Approve it first.", 409)
        if actor not in (OPERATOR, DIRECTOR, manager_id(tool["siteId"]), tool["createdBy"]):
            raise RealityError(f"{display_name(actor)} may not publish {self.mcp_name(tool)}.", "AUTHORITY_DENIED",
                               "The Owner's agent, the Operations Director, the site's manager or the tool's builder publishes it.", 403)
        for other in self.store.all("forged_tool", tool["siteId"]):
            if other["name"] == tool["name"] and other["id"] != tool["id"] and other["status"] == "published":
                other.update(status="retired", supersededBy=tool["id"], retiredAt=now(), retiredBy=actor)
                self._save(other)
                self._change(other, f"{self.mcp_name(other)} v{other['version']} retired; superseded by v{tool['version']}.", "retire", actor)
        tool.update(status="published", publishedAt=now(), publishedBy=actor)
        self._save(tool)
        summary = f"Published {self.mcp_name(tool)} v{tool['version']}; every connected client sees it now."
        self._say(tool.get("requestId"), tool["createdBy"], summary, final=True)
        self._change(tool, summary, "publish", actor)
        return self.public(tool)

    def retire(self, tool_id: str, actor: str, reason: str = "") -> dict:
        actor = authorize(actor, "read")
        tool = self.get(tool_id)
        if tool["status"] == "retired":
            return self.public(tool)
        if actor not in (OPERATOR, DIRECTOR, manager_id(tool["siteId"]), tool["createdBy"]):
            raise RealityError(f"{display_name(actor)} may not retire {self.mcp_name(tool)}.", "AUTHORITY_DENIED",
                               "The Owner's agent, the Operations Director, the site's manager or the tool's builder retires it.", 403)
        tool.update(status="retired", retiredAt=now(), retiredBy=actor, retireReason=(reason or "")[:300] or None)
        self._save(tool)
        summary = f"Retired {self.mcp_name(tool)} v{tool['version']}" + (f": {reason[:200]}" if reason else ".")
        self._say(tool.get("requestId"), actor, summary, final=True)
        self._change(tool, summary, "retire", actor)
        return self.public(tool)

    # ---- the automatic pipeline (Oct 18): draft → validate → test → the manager's review → approve → publish --------------

    def _draft_then_advance(self, request_id: str) -> None:
        """Live drafting with Claude for a recorded gap, then the pipeline (through `request`, which starts it)."""
        request = self.request_record(request_id)
        site, agent = request["siteId"], request["agentId"]
        definition, reason, meta = self.drafter.draft(site, agent, request["task"])
        if definition is None:
            request.update(status="awaiting_draft", draftError=reason)
            self.store.put("tool_request", request, site)
            self._say(request_id, agent, f"I could not draft the tool ({reason}); the gap stays recorded and a draft can still be added.")
            fields = dict(toolRequestId=request_id, requestId=request_id, status="awaiting_draft", step="draft", actor=agent)
            self.service.reality.emit_change(site, "tool", request_id, f"{display_name(agent)} could not draft a tool: {reason}", extra=fields, fields=fields)
            return
        definition["drafting"] = meta
        self.request(agent, site, request["task"], agent, request.get("requestedBy"), definition, DRAFT_MODEL, None, request_id)

    def advance(self, tool_id: str) -> dict:
        """Move one tool through the pipeline as far as it may go on its own; safe to call again."""
        with self.lock:
            if tool_id in self._advancing:
                return self.public(self.get(tool_id))
            self._advancing.add(tool_id)
        try:
            return self._advance(tool_id)
        finally:
            with self.lock:
                self._advancing.discard(tool_id)

    def _advance(self, tool_id: str) -> dict:
        tool = self.get(tool_id)
        builder = tool["createdBy"]
        for _attempt in range(2):
            tool = self.get(tool_id)
            if tool["status"] == "draft":
                tool = self.validate(tool_id, builder)
                if not tool["validation"]["ok"]:
                    if self._revise(tool_id, tool["validation"]["errors"], "validation"):
                        continue
                    return self._reject(tool_id, f"validation failed: {'; '.join(tool['validation']['errors'])[:300]}")
            if tool["status"] == "validated":
                tool = self.test(tool_id, builder)
                if not tool["test"]["passed"]:
                    problems = [n for n in tool["test"]["notes"] if "step(s) ran" not in n and "previewed" not in n] or ["the test failed"]
                    if self._revise(tool_id, problems, "test"):
                        continue
                    return self._reject(tool_id, f"the test failed: {'; '.join(problems)[:300]}")
            break
        tool = self.get(tool_id)
        if tool["status"] != "tested":
            return self.public(tool)
        if not tool["readOnly"]:
            self._say(tool.get("requestId"), builder, f"{self.mcp_name(tool)} has a write step, so it waits for the Operations Director's approval; "
                                                     "a tool that writes is never approved automatically.")
            self._change(tool, f"{self.mcp_name(tool)} is tested and awaits the Operations Director (it has a write step).", "await_approval", builder)
            return self.public(tool)
        manager = manager_id(tool["siteId"])
        reason = self._review(tool, builder, manager)
        self.approve(tool_id, manager, True, reason)
        return self.publish(tool_id, builder)

    def _revise(self, tool_id: str, errors: list[str], stage: str) -> bool:
        """One Claude revision for a Claude draft that failed validation or its test; prepared drafts are not revised."""
        tool = self.get(tool_id)
        if tool.get("generator") != DRAFT_MODEL or int(tool.get("revisions") or 0) >= 1:
            return False
        current = dict(name=tool["name"], description=tool["description"], inputSchema=tool["inputSchema"], steps=tool["steps"], output=tool["output"])
        definition, reason, meta = self.drafter.revise(tool["siteId"], tool["createdBy"], tool["why"]["task"], current, errors)
        if definition is None:
            self._say(tool.get("requestId"), tool["createdBy"], f"I could not revise {self.mcp_name(tool)} ({reason}).")
            return False
        tool = self.get(tool_id)
        tool.update(**self.definition_fields(definition), status="draft", revisions=int(tool.get("revisions") or 0) + 1, validation=None)
        tool["readOnly"] = self.read_only(tool)
        self._save(tool)
        self._say(tool.get("requestId"), tool["createdBy"], f"The {stage} of {self.mcp_name(tool)} failed ({str(errors[0])[:160]}); revised the recipe and checking it again.")
        self._change(tool, f"{display_name(tool['createdBy'])} revised {self.mcp_name(tool)} after the {stage} failed.", "revise", tool["createdBy"])
        return True

    def _reject(self, tool_id: str, reason: str) -> dict:
        tool = self.get(tool_id)
        tool.update(status="rejected", rejection=dict(by=tool["createdBy"], reason=reason[:500], at=now()))
        self._save(tool)
        self._say(tool.get("requestId"), tool["createdBy"], f"{self.mcp_name(tool)} cannot be published: {reason[:300]}", final=True)
        self._change(tool, f"{self.mcp_name(tool)} was rejected: {reason[:300]}", "reject", tool["createdBy"])
        return self.public(tool)

    def _review(self, tool: dict, builder: str, manager: str) -> str:
        """The site manager reviews the recipe and the test in a short chat with the builder; returns the approval reason."""
        name, site = self.mcp_name(tool), SITE_BY_ID.get(tool["siteId"], {}).get("name", tool["siteId"])
        test = tool.get("test") or {}
        output = test.get("output")
        rows = len(output) if isinstance(output, list) else None
        sample = json.dumps(output[:2] if isinstance(output, list) else output, ensure_ascii=False, default=str)[:500]
        recipe = "; ".join(self.recipe(tool))[:900]
        reason = f"Read-only, scoped to {site}, tested on live data" + (f" ({rows} row(s))" if rows is not None else "") + "."
        shared = (f"Tool {name} at {site}, built by {display_name(builder)} for the task: {tool['why']['task'][:300]} Gap: {tool['why']['gap'][:200]} "
                  f"Recipe: {recipe}. Every step only reads {site}'s own records. Test on live local data: passed in {test.get('ms', 0)} ms"
                  + (f", {rows} row(s)" if rows is not None else "") + f". Sample output: {sample}")
        briefs = {builder: "You built this tool because no existing tool answered the task. Say in plain words what it does and what the test "
                           "returned, and ask the manager to approve it.",
                  manager: "You approve read-only tools for your site. Check the recipe only reads your own site's records, that the test passed "
                           "on live data and that the output answers the task, then approve it in one sentence."}
        fallback = [
            dict(speaker=builder, text=f"I built {name} for: {tool['why']['task'][:160]} It only reads our own records; the test on live data passed"
                                       + (f" with {rows} row(s)." if rows is not None else ".") + " Can you approve it?"),
            dict(speaker=manager, text=f"Reading the recipe: {len(tool['steps'])} step(s), all reads at {site}. What did the test return?"),
            dict(speaker=builder, text=f"It matched its output schema in {test.get('ms', 0)} ms" + (f", {rows} row(s)." if rows is not None else ".")),
            dict(speaker=manager, text=f"Approved: read-only, scoped to {site} and tested on live data. Publish it."),
        ]
        summary = dict(headline=f"{display_name(manager)} approved {name}", points=[f"{len(tool['steps'])} read step(s) at {site}", "test passed on live data"],
                       decisions=[f"Approve and publish {name}"], actions=[dict(owner=display_name(builder), task=f"Publish {name}", due="now")])
        try:
            chat = self.service.chats.run(convener=builder, participants=[builder, manager], topic=f"Review of {name}", site_ids=[tool["siteId"]],
                                          briefs=briefs, shared=shared, goal="the manager reviews the recipe and the test result and approves the tool",
                                          min_turns=4, max_turns=4, refs=dict(toolId=tool["id"], requestId=tool.get("requestId")), fallback=fallback,
                                          fallback_summary=summary, realtime=self.service.start_workers, origin="workflow", source="forge")
            tool = self.get(tool["id"])
            tool["reviewConversationId"] = chat.get("id")
            self._save(tool)
            headline = ((chat.get("summary") or {}).get("headline") or "").strip()
            return f"{reason} {headline}"[:400] if headline else reason
        except Exception as error:  # noqa: BLE001 - the review chat is a record; the approval stands on the checks
            self.store.event(tool["siteId"], manager, "forge.review", "The review chat could not run", f"{type(error).__name__}: {str(error)[:160]}")
            return reason

    # ---- step 7: call --------------------------------------------------------------------------------------

    def call(self, tool_id: str, args: dict | None, actor: str) -> dict:
        actor = authorize(actor, "read")
        tool = self.get(tool_id)
        if tool["status"] != "published":
            raise RealityError(f"{self.mcp_name(tool)} is {tool['status']}; only published tools can be called.", "TOOL_NOT_PUBLISHED",
                               "List published tools with GET /api/tools?status=published.", 409)
        if actor not in (OPERATOR, DIRECTOR) and site_of(actor) != tool["siteId"]:
            raise RealityError(f"{display_name(actor)} may not call {self.mcp_name(tool)}; it belongs to {tool['siteId']}.", "AUTHORITY_DENIED",
                               "Call it as that site's team, the Operations Director or the Owner's agent.", 403)
        values = {**self.default_input(tool), **(args or {})}
        errors = schema_errors(values, tool["inputSchema"])
        if errors:
            raise RealityError(f"Arguments do not match {self.mcp_name(tool)}'s input schema: {'; '.join(errors)[:300]}", "INVALID_REQUEST",
                               "Check inputSchema with GET /api/tools/{id}.")
        started = time.monotonic()
        output, trace, raw_tokens = self.execute(tool, values, dry_run=False)
        ms = int((time.monotonic() - started) * 1000)
        text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        out_tokens = estimate_tokens(text)
        saved = max(0, raw_tokens - out_tokens)
        with self.lock:
            tool = self.get(tool_id)
            usage = tool.setdefault("usage", dict(calls=0, lastCalledAt=None, tokensSavedEstimate=0, history=[]))
            usage.update(calls=int(usage.get("calls") or 0) + 1, lastCalledAt=now(), tokensSavedEstimate=int(usage.get("tokensSavedEstimate") or 0) + saved)
            self._save(tool)
        self.service.telemetry.record(actor, "tool", self.mcp_name(tool), tokens=out_tokens, ms=ms, site_id=tool["siteId"],
                                      detail=f"{tool['id']} v{tool['version']}: {len(trace)} step(s), ~{saved} tokens saved")
        return dict(toolId=tool["id"], name=tool["name"], mcpName=self.mcp_name(tool), version=tool["version"], siteId=tool["siteId"], output=output,
                    ms=ms, steps=[{k: v for k, v in t.items() if k in ("id", "op", "rows", "ms")} for t in trace], tokensSavedEstimate=saved,
                    usage=tool["usage"], calledBy=actor, ranAs=tool["createdBy"])

    # ---- the runner -------------------------------------------------------------------------------------------

    def execute(self, tool: dict, args: dict, dry_run: bool) -> tuple[object, list[dict], int]:
        """Run the steps in order as the creating agent, at the tool's site. Returns (output, trace, raw read tokens)."""
        scope = {"input": dict(args), "steps": {}}
        trace, raw_tokens = [], 0
        for step in tool["steps"]:
            started = time.monotonic()
            op = step["op"]
            if op in TRANSFORMS:
                result = self.transform(op, step.get("args") or {}, scope)
                entry = dict(id=step["id"], op=op)
            elif op in OPS:
                kind = self.step_kind(step)
                values = {key: render(value, scope) for key, value in (step.get("args") or {}).items()}
                if dry_run and kind == "act":
                    result = dict(preview=True, op=op, args=values)
                    entry = dict(id=step["id"], op=op, preview=True)
                else:
                    result = self.run_op(tool, op, values)
                    entry = dict(id=step["id"], op=op)
                    if kind == "read":
                        # What a caller would have read without the tool: the same data as the existing tool returns it
                        # (metric samples as [time, value] pairs, the shape get_metrics answers with).
                        raw = [[r.get("at"), r.get("value")] for r in result] if op == "metrics.samples" and isinstance(result, list) else result
                        raw_tokens += estimate_tokens(json.dumps(raw, ensure_ascii=False, default=str)[:400000])
            else:
                raise RealityError(f"Op '{op}' is not on the allow-list.", "TOOL_INVALID", "Validate the tool before running it.")
            if isinstance(result, list) and len(result) > MAX_ROWS:
                result = result[:MAX_ROWS]
            scope["steps"][step["id"]] = result
            entry.update(rows=len(result) if isinstance(result, list) else None, ms=int((time.monotonic() - started) * 1000))
            trace.append(entry)
        output = render_json(tool["output"]["template"], scope)
        return output, trace, raw_tokens

    def run_op(self, tool: dict, op: str, args: dict):
        """One allow-listed Steward operation, authorized as the tool's creator at the tool's site only."""
        site, agent = tool["siteId"], tool["createdBy"]
        kind, action = OPS[op][0], OPS[op][1]
        if op == "resolve":
            budget = float(args.get("budget") or 0)
            action = "dispatch" if budget > 0 else "resolve"
        authorize(agent, action, site)
        svc = self.service
        if op == "facts.list":
            facts = svc.reality.latest_facts(site)
            return [dict(assetTag=f["assetTag"], attribute=f["attribute"], value=f["value"], unit=f.get("unit"), status=f.get("status"),
                         observedAt=f.get("observedAt"), attestationId=f.get("attestationId"), source=(f.get("source") or {}).get("kind"))
                    for f in facts if (not args.get("assetTag") or f["assetTag"] == str(args["assetTag"]).upper())
                    and (not args.get("attribute") or f["attribute"] == args["attribute"])]
        if op in ("metrics.series", "metrics.samples"):
            days = max(1, min(7, int(float(args.get("days") or 1))))
            end = utcnow()
            data = svc.metrics.series(site, str(args["series"]), (end - timedelta(days=days)).isoformat(), end.isoformat(),
                                      int(float(args["step"])) if op == "metrics.series" and args.get("step") else None)
            if op == "metrics.series":
                return data["series"]
            rows = []
            for series in data["series"]:
                spec = series.get("spec") or {}
                for at, value in series["points"]:
                    rows.append(dict(assetTag=series["assetTag"], series=series["key"], label=series["label"], unit=series["unit"], at=at, value=value,
                                     min=spec.get("min"), max=spec.get("max")))
            return rows
        if op == "issues.list":
            status = args.get("status") or "open"
            out = []
            for issue in svc.issues.list(site, status):
                ids = svc.regulations.for_issue({**issue, "siteId": site})
                why = svc.regulations.why(ids[:1])
                out.append(dict(id=issue["id"], assetTag=issue.get("assetTag"), kind=issue["kind"], severity=issue["severity"], status=issue.get("status", "open"),
                                summary=issue.get("summary"), ownerId=issue.get("ownerId"), obligationId=issue.get("obligationId"), regulationIds=ids,
                                regulation=f"{why[0]['instrument']}, {why[0]['provision']}" if why else None, source=issue.get("source")))
            return out
        if op == "obligations.list":
            out = []
            for obligation in svc.people.obligations(site, args.get("status") or None):
                why = svc.regulations.why(obligation.get("regulationIds", [])[:1])
                out.append(dict(id=obligation["id"], assetTag=obligation.get("assetTag"), title=obligation["title"], status=obligation["status"],
                                dueAt=obligation.get("dueAt"), ownerId=obligation.get("ownerId"), regulationIds=obligation.get("regulationIds", []),
                                regulation=f"{why[0]['instrument']}, {why[0]['provision']}" if why else None))
            return out
        if op == "crew.list":
            return [dict(id=c["id"], name=c["name"], role=c["role"], onShift=c["onShift"], owns=c.get("owns", [])) for c in svc.people.crew(site)]
        if op == "crew.responsible":
            answer = svc.people.who_is_responsible(site, str(args["issueKind"]))
            owner = answer.get("owner")
            return dict(issueKind=answer["issueKind"], owner=dict(id=owner["id"], name=owner["name"], role=owner["role"], onShift=owner["onShift"]) if owner else None,
                        agent=answer["agent"], agentName=answer["agentName"], fallback=answer["fallback"])
        if op == "components.list":
            return [dict(tag=c["tag"], id=c["id"], name=c["name"], kind=c["kind"], system=c.get("system"), subsystem=c.get("subsystem"),
                         description=c.get("description"), status=c.get("status")) for c in svc.reality.components(site)]
        if op == "regulations.list":
            return [dict(id=r["id"], instrument=r.get("instrument"), provision=r.get("provision"), title=r.get("title"), appliesTo=r.get("appliesTo") or [])
                    for r in svc.regulations.list(site)]
        if op == "conversations.list":
            limit = max(1, min(100, int(float(args.get("limit") or 20))))
            return [dict(id=c["id"], kind=c["kind"], topic=c.get("topic"), participants=c.get("participants"), status=c.get("status"),
                         startedAt=c.get("startedAt"), headline=(c.get("summary") or {}).get("headline"))
                    for c in svc.conversations.list(site, None, args.get("kind") or None, limit)]
        if op == "maintenance.list":
            return [dict(id=w["id"], date=w["date"], scope=w["scope"], status=w["status"], siteIds=w["siteIds"], examiner=w.get("examiner"),
                         obligationId=w.get("obligationId"), assetTag=w.get("assetTag")) for w in svc.maintenance.list(site)]
        if op == "resolve":
            result = svc.reality.resolve(site, str(args["assetTag"]), str(args["attribute"]), budget=float(args.get("budget") or 0),
                                         requester=f"{agent}/forge:{tool['id']}")
            return {k: result.get(k) for k in ("status", "value", "unit", "attestationId", "observedAt", "workItemId", "reference")}
        if op in ("eye.go_to", "eye.look"):
            frame = svc.eye.act_sync(site, "go_to" if op == "eye.go_to" else "look", dict(assetTag=args.get("assetTag")) if op == "eye.go_to" else {}, agent)
            return dict(frameId=frame.get("frameId"), frameUrl=frame.get("frameUrl"), visiblePins=frame.get("visiblePins"))
        if op == "issues.raise":
            return svc.issues.raise_issue(site, str(args["kind"]), str(args["severity"]), str(args["summary"]), asset_tag=args.get("assetTag") or None,
                                          source="agent", synthetic=False, actor=agent, extra=dict(forgedToolId=tool["id"]))
        if op == "viewer.focus":
            return svc.viewer.post(site, "focus", str(args["assetTag"]), None, agent)
        raise RealityError(f"Op '{op}' is not on the allow-list.", "TOOL_INVALID", "Use an allow-listed op.")

    # ---- transforms (pure) -----------------------------------------------------------------------------------

    @staticmethod
    def _rows(value, name: str) -> list:
        if value is None:
            return []
        if not isinstance(value, list):
            raise RealityError(f"{name} must be a list (got {type(value).__name__}).", "TOOL_RUNTIME", "Point it at a step that returns rows.")
        return value

    def transform(self, op: str, args: dict, scope: dict):
        if op == "concat":
            out = []
            for key in args:
                out += self._rows(render(args[key], scope), f"concat.{key}")
            return out
        if op == "join_on":
            left, right = self._rows(render(args["left"], scope), "join_on.left"), self._rows(render(args["right"], scope), "join_on.right")
            left_key, _, right_key = str(args["on"]).partition("=")
            right_key = right_key or left_key
            name, mode = str(args["as"]), str(args.get("mode") or "inner")
            index: dict = {}
            for row in right:
                key = resolve_path("item." + right_key.strip(), {"item": row})
                index.setdefault(json.dumps(key, default=str), row)
            out = []
            for row in left:
                match = index.get(json.dumps(resolve_path("item." + left_key.strip(), {"item": row}), default=str))
                if match is None and mode != "left":
                    continue
                out.append({**row, name: match} if isinstance(row, dict) else {"value": row, name: match})
            return out
        rows = self._rows(render(args["from"], scope), f"{op}.from")
        if op == "filter":
            condition = parse_condition(self._condition_text(args["where"], scope))
            return [row for row in rows if evaluate(condition, row)]
        if op == "map":
            fields = {key: value for key, value in args.items() if key != "from"}
            out = []
            for row in rows:
                local = {**scope, "item": row}
                entry = {}
                for key, template in fields.items():
                    if isinstance(template, str) and template.startswith("if:"):
                        entry[key] = evaluate(parse_condition(self._condition_text(template[3:], scope)), row)
                    else:
                        entry[key] = render(template, local)
                out.append(entry)
            return out
        if op == "group_count":
            by = str(args["by"])
            groups: dict = {}
            for row in rows:
                key = resolve_path("item." + by, {"item": row})
                key = None if key is MISSING else key
                group = groups.setdefault(json.dumps(key, default=str), {by: key, "count": 0, "first": row, "_rows": []})
                group["count"] += 1
                group["_rows"].append(row)
            out = []
            for group in groups.values():
                for measure in ("max", "min", "sum"):
                    if args.get(measure):
                        values = [v for v in (resolve_path("item." + str(args[measure]), {"item": r}) for r in group["_rows"])
                                  if isinstance(v, (int, float)) and not isinstance(v, bool)]
                        group[measure] = (max(values) if measure == "max" else min(values) if measure == "min" else round(sum(values), 6)) if values else None
                group.pop("_rows")
                out.append(group)
            return out
        if op == "sort":
            by, descending = str(args["by"]), str(args.get("order") or "asc").lower() == "desc"

            def key(row):
                value = resolve_path("item." + by, {"item": row})
                value = None if value is MISSING else value
                return (value is None, value if isinstance(value, (int, float, str)) and not isinstance(value, bool) else (int(value) if isinstance(value, bool) else str(value)))
            present = [r for r in rows if key(r)[0] is False]
            absent = [r for r in rows if key(r)[0] is True]
            try:
                present.sort(key=lambda r: key(r)[1], reverse=descending)
            except TypeError:
                present.sort(key=lambda r: str(key(r)[1]), reverse=descending)
            return present + absent
        if op == "take":
            count = render(args["count"], scope)
            return rows[:max(0, min(MAX_ROWS, int(float(count or 0))))]
        raise RealityError(f"Unknown transform {op}.", "TOOL_INVALID", "Use filter, map, group_count, sort, take, join_on or concat.")

    @staticmethod
    def _condition_text(text: str, scope: dict) -> str:
        """Templates inside a condition are filled with JSON literals (numbers stay numbers, text is quoted)."""
        def literal(match):
            value = resolve_path(match.group(1), scope)
            value = None if value is MISSING else value
            return json.dumps(value) if not isinstance(value, bool) else ("true" if value else "false")
        return TEMPLATE_RE.sub(literal, text)

    # ---- the catalog (for the dashboard and the drafting prompt) ----------------------------------------------

    @staticmethod
    def catalog() -> dict:
        return dict(ops=[dict(op=op, kind=spec[0], authority=spec[1], args=list(spec[2]), required=list(spec[3]), returns=spec[4]) for op, spec in OPS.items()],
                    transforms=[dict(op=op, args=list(spec["args"]) if spec["args"] else "any", required=list(spec["required"])) for op, spec in TRANSFORMS.items()],
                    templates="{{input.<name>}}, {{steps.<id>[.<field>]}}, {{item.<field>}} in per-item arguments; pseudo-fields length, empty, first, last",
                    conditions="path op value [and ...|or ...]; ops == != > >= < <= in contains exists missing; values: numbers, 'text', true/false/null, [a, b], item.<path>",
                    statuses=list(STATUSES), maxSteps=MAX_STEPS, maxInputProperties=MAX_INPUT_PROPERTIES,
                    approval="read-only: the site's manager (or the Operations Director); any act step: the Operations Director")
