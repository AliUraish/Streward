"""What the agents spent and called, live (owner, Oct 18: "bring back the evals page, which tells the latest tool calls, model
usage and stuff"). `GET /api/usage?limit=` gives today's Claude usage per part of Steward that calls it (the walk judge, the
agent chats, the phone-call reader, the Tool Forge drafter, the event director: calls, tokens, estimated USD and the daily
caps, from each one's own usage record) and the latest tool calls from local telemetry (the same events the MCP runtime
ships to Armature), plus today's tool-call totals and the busiest tools. Read-only."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request

from .agents import display_name
from .env import env
from .service import public

router = APIRouter(tags=["usage"])

# (key, label, store meta prefix, max-calls env and default, budget env and default)
PARTS = (
    ("walks", "Walk judge (each stop)", "walks:claude:", "STEWARD_WALK_CLAUDE_MAX_CALLS_PER_DAY", 300, "STEWARD_WALK_CLAUDE_BUDGET_USD_PER_DAY", 10.0),
    ("chats", "Agent chats and summaries", "chats:claude:", "STEWARD_CHAT_CLAUDE_MAX_CALLS_PER_DAY", 400, "STEWARD_CHAT_CLAUDE_BUDGET_USD_PER_DAY", 6.0),
    ("calls", "Phone-call outcomes", "calls:claude:", "STEWARD_CALL_CLAUDE_MAX_CALLS_PER_DAY", 60, "STEWARD_CALL_CLAUDE_BUDGET_USD_PER_DAY", 3.0),
    ("forge", "Tool Forge drafts", "forge:claude:", "STEWARD_FORGE_CLAUDE_MAX_CALLS_PER_DAY", 20, "STEWARD_FORGE_CLAUDE_BUDGET_USD_PER_DAY", 3.0),
    ("events", "Site events", "events:claude:", "STEWARD_EVENTS_MAX_CALLS_PER_DAY", 120, "STEWARD_EVENTS_BUDGET_USD_PER_DAY", 10.0),
)
MODEL = "claude-opus-5-5"


def _number(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)) or default)
    except ValueError:
        return default


def _int(value) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


DETAIL = re.compile(r"est\. tokens in (\d+) out (\d+)(?:; requester ([\w.:@/-]+))?")


def _mcp_rows(service, since: str | None, limit: int) -> list[dict]:
    """MCP tool calls only: rows of kind `mcp` (the runtime's own report of each call, or the backend's record of a call
    that named its tool), newest first."""
    with service.store.connect() as db:
        rows = db.execute("SELECT * FROM telemetry WHERE kind='mcp'" + (" AND at>=?" if since else "") + " ORDER BY seq DESC LIMIT ?",
                          ((since, int(limit)) if since else (int(limit),))).fetchall()
    out = []
    for row in rows:
        r = service.telemetry._shape(row)
        detail = str(r.get("detail") or "")
        match = DETAIL.search(detail)
        out.append(dict(at=r["at"], agentId=r["agentId"], agentName=display_name(r["agentId"]), tool=r.get("tool"), ok=r.get("ok"), ms=r.get("ms"),
                        tokens=r.get("tokens"), tokensIn=int(match.group(1)) if match else None, tokensOut=int(match.group(2)) if match else None,
                        client=(match.group(3) if match and match.group(3) else None), siteId=r.get("siteId"),
                        request=None if match else (detail or None)))
    return out


@router.get("/api/usage")
def usage(request: Request, limit: int = Query(default=40, ge=1, le=200)):
    service = request.app.state.service
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    models, total = [], dict(calls=0, inputTokens=0, outputTokens=0, usd=0.0)
    for key, label, prefix, calls_env, calls_default, budget_env, budget_default in PARTS:
        try:
            stored = json.loads(service.store.meta(prefix + day) or "{}")
        except ValueError:
            stored = {}
        row = dict(key=key, label=label, model=MODEL, calls=_int(stored.get("calls")), inputTokens=_int(stored.get("inputTokens")),
                   outputTokens=_int(stored.get("outputTokens")), usd=round(float(stored.get("usd") or 0.0), 4), errors=_int(stored.get("errors")),
                   fallbacks=_int(stored.get("rules")) + _int(stored.get("fallbacks")) + _int(stored.get("templates")),
                   capCalls=int(_number(calls_env, calls_default)), capUsd=_number(budget_env, budget_default))
        models.append(row)
        for k in ("calls", "inputTokens", "outputTokens"):
            total[k] += row[k]
        total["usd"] = round(total["usd"] + row["usd"], 4)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = service.telemetry.rows(limit=limit)
    today = service.telemetry.rows(since=since, limit=5000)
    per_tool: dict[str, dict] = {}
    for row in today:
        name = row.get("tool") or row.get("kind") or "action"
        entry = per_tool.setdefault(name, dict(tool=name, calls=0, tokens=0, failures=0))
        entry["calls"] += 1
        entry["tokens"] += _int(row.get("tokens"))
        entry["failures"] += 0 if row.get("ok") else 1
    calls = [dict(at=r["at"], agentId=r["agentId"], agentName=display_name(r["agentId"]), siteId=r.get("siteId"), kind=r.get("kind"), tool=r.get("tool"),
                  tokens=r.get("tokens"), ms=r.get("ms"), ok=r.get("ok"), source=r.get("source")) for r in recent]
    mcp_recent = _mcp_rows(service, None, limit)
    mcp_today = _mcp_rows(service, since, 5000)
    clients: dict[str, int] = {}
    mcp_tools: dict[str, dict] = {}
    for row in mcp_today:
        clients[row["client"] or "unknown client"] = clients.get(row["client"] or "unknown client", 0) + 1
        entry = mcp_tools.setdefault(row["tool"] or "tool", dict(tool=row["tool"] or "tool", calls=0, failures=0, ms=0))
        entry["calls"] += 1
        entry["failures"] += 0 if row["ok"] else 1
        entry["ms"] += _int(row["ms"])
    timed = [r["ms"] for r in mcp_today if isinstance(r["ms"], int)]
    mcp = dict(calls=mcp_recent, today=dict(calls=len(mcp_today), failures=sum(0 if r["ok"] else 1 for r in mcp_today), tokens=sum(_int(r["tokens"]) for r in mcp_today),
                                           avgMs=round(sum(timed) / len(timed)) if timed else None, clients=[dict(client=k, calls=v) for k, v in sorted(clients.items(), key=lambda kv: -kv[1])]),
               topTools=[dict(t, avgMs=round(t["ms"] / t["calls"]) if t["calls"] else None) for t in sorted(mcp_tools.values(), key=lambda t: -t["calls"])[:10]])
    return public(dict(day=day, model=MODEL, models=models, total=total, toolCalls=calls, mcp=mcp,
                       toolCallsToday=dict(calls=len(today), tokens=sum(_int(r.get("tokens")) for r in today), failures=sum(0 if r.get("ok") else 1 for r in today)),
                       topTools=sorted(per_tool.values(), key=lambda t: -t["calls"])[:8],
                       note="Claude usage is each part's own count of today's calls (UTC); tokens in tool calls are local estimates. The same tool calls go to Armature."))
