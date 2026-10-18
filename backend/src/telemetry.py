"""Local telemetry: one row per agent action and MCP/tool call, with an estimated token count.

This is Steward's own record of the same tool-call events the MCP runtime ships to Armature ("Steward telemetry,
also delivered to Armature"). Atlas reads it for `get_eval_findings`; `GET /api/agents/{id}/activity` reports tokens
this hour from it. Tokens are estimates (characters / 4 plus a small per-call overhead), never billed usage.

Rows live in their own SQLite table (indexed by agent and time) and are mirrored to Supabase table `telemetry`.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone

from .store import now, uid

SOURCE_LABEL = "Steward telemetry, also delivered to Armature"
CALL_OVERHEAD_TOKENS = 30


def estimate_tokens(text: str | None, overhead: int = CALL_OVERHEAD_TOKENS) -> int:
    return int(math.ceil(len(text or "") / 4)) + overhead


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Telemetry:
    COLUMNS = ("id", "at", "agentId", "siteId", "kind", "tool", "tokens", "ms", "ok", "missionId", "scenarioId", "runId", "source",
               "synthetic", "detail")

    def __init__(self, service):
        self.service = service
        self.store = service.store
        with self.store.lock, self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, at TEXT NOT NULL, agent_id TEXT NOT NULL,
                    site_id TEXT, kind TEXT NOT NULL, tool TEXT, tokens INTEGER NOT NULL DEFAULT 0, ms INTEGER, ok INTEGER NOT NULL DEFAULT 1,
                    mission_id TEXT, scenario_id TEXT, run_id TEXT, source TEXT NOT NULL DEFAULT 'steward', synthetic INTEGER NOT NULL DEFAULT 0,
                    detail TEXT);
                CREATE INDEX IF NOT EXISTS telemetry_agent_at ON telemetry(agent_id, at);
                CREATE INDEX IF NOT EXISTS telemetry_mission ON telemetry(mission_id);
            """)

    def record(self, agent_id: str, kind: str, tool: str | None = None, tokens: int | None = None, text: str | None = None,
               site_id: str | None = None, ms: int | None = None, ok: bool = True, mission_id: str | None = None,
               scenario_id: str | None = None, run_id: str | None = None, source: str = "steward", synthetic: bool = False,
               detail: str | None = None, at: str | None = None) -> dict:
        """Append one row. `tokens` wins over the estimate from `text`. Never raises on the request path."""
        row = dict(id=uid("tel"), at=at or now(), agentId=agent_id, siteId=site_id, kind=kind, tool=tool,
                   tokens=int(tokens if tokens is not None else estimate_tokens(text)), ms=ms, ok=bool(ok), missionId=mission_id,
                   scenarioId=scenario_id, runId=run_id, source=source, synthetic=bool(synthetic), detail=(detail or (text or "")[:200]) or None)
        try:
            with self.store.lock, self.store.connect() as db:
                db.execute("INSERT INTO telemetry(id,at,agent_id,site_id,kind,tool,tokens,ms,ok,mission_id,scenario_id,run_id,source,synthetic,detail) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (row["id"], row["at"], agent_id, site_id, kind, tool, row["tokens"], ms, int(row["ok"]), mission_id, scenario_id,
                            run_id, source, int(row["synthetic"]), row["detail"]))
        except Exception:
            return row
        reality = getattr(self.service, "reality", None)
        if reality is not None:
            reality.mirror.put("telemetry", row, site_id or "")
        return row

    @staticmethod
    def _shape(row) -> dict:
        return dict(id=row["id"], at=row["at"], agentId=row["agent_id"], siteId=row["site_id"], kind=row["kind"], tool=row["tool"],
                    tokens=row["tokens"], ms=row["ms"], ok=bool(row["ok"]), missionId=row["mission_id"], scenarioId=row["scenario_id"],
                    runId=row["run_id"], source=row["source"], synthetic=bool(row["synthetic"]), detail=row["detail"])

    def rows(self, agent_id: str | None = None, since: str | None = None, limit: int = 500, mission_prefix: str | None = None,
             run_id: str | None = None) -> list[dict]:
        clauses, params = [], []
        if agent_id:
            clauses.append("agent_id=?")
            params.append(agent_id)
        if since:
            clauses.append("at>=?")
            params.append(since)
        if mission_prefix:
            clauses.append("mission_id LIKE ?")
            params.append(mission_prefix + "%")
        if run_id:
            clauses.append("run_id=?")
            params.append(run_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.store.connect() as db:
            rows = db.execute(f"SELECT * FROM telemetry{where} ORDER BY seq DESC LIMIT ?", (*params, int(limit))).fetchall()
        return [self._shape(row) for row in rows]

    def tokens_since(self, agent_id: str, since: str) -> tuple[int, int]:
        with self.store.connect() as db:
            row = db.execute("SELECT COALESCE(SUM(tokens),0) AS tokens, COUNT(*) AS calls FROM telemetry WHERE agent_id=? AND at>=?",
                             (agent_id, since)).fetchone()
        return int(row["tokens"]), int(row["calls"])

    def hour_ago(self) -> str:
        return _iso(datetime.now(timezone.utc) - timedelta(hours=1))

    def per_mission(self, agent_id: str | None = None, since: str | None = None, mission_prefix: str | None = None) -> dict[str, dict]:
        """{missionId: {agentId, tokens, calls, polls, failures}} for rows that carry a mission id."""
        clauses, params = ["mission_id IS NOT NULL"], []
        if agent_id:
            clauses.append("agent_id=?")
            params.append(agent_id)
        if since:
            clauses.append("at>=?")
            params.append(since)
        if mission_prefix:
            clauses.append("mission_id LIKE ?")
            params.append(mission_prefix + "%")
        with self.store.connect() as db:
            rows = db.execute("SELECT mission_id, agent_id, SUM(tokens) AS tokens, COUNT(*) AS calls, SUM(kind='poll') AS polls, SUM(ok=0) AS failures "
                              f"FROM telemetry WHERE {' AND '.join(clauses)} GROUP BY mission_id, agent_id", params).fetchall()
        return {row["mission_id"]: dict(agentId=row["agent_id"], tokens=int(row["tokens"] or 0), calls=int(row["calls"]),
                                        polls=int(row["polls"] or 0), failures=int(row["failures"] or 0)) for row in rows}

    def findings(self, since: str | None = None) -> dict:
        """Per-agent quality from local telemetry: tokens per mission, poll counts, failures, tokens this hour, and a
        flag for agents whose tokens per mission exceed 5x the median of their peers."""
        from .agents import OPERATOR, all_agent_ids, display_name
        hour = self.hour_ago()
        missions = self.per_mission(since=since)
        agents = []
        per_agent_tpm = {}
        for agent_id in all_agent_ids():
            if agent_id == OPERATOR:
                continue
            mine = [m for m in missions.values() if m["agentId"] == agent_id]
            tokens_hour, calls_hour = self.tokens_since(agent_id, hour)
            with self.store.connect() as db:
                totals = db.execute("SELECT COALESCE(SUM(tokens),0) AS tokens, COUNT(*) AS calls, COALESCE(SUM(kind='poll'),0) AS polls, "
                                    "COALESCE(SUM(ok=0),0) AS failures FROM telemetry WHERE agent_id=?" + (" AND at>=?" if since else ""),
                                    (agent_id, since) if since else (agent_id,)).fetchone()
            tpm = round(sum(m["tokens"] for m in mine) / len(mine)) if mine else None
            if tpm is not None:
                per_agent_tpm[agent_id] = tpm
            agents.append(dict(agentId=agent_id, name=display_name(agent_id), missions=len(mine), tokensPerMission=tpm,
                               tokens=int(totals["tokens"]), calls=int(totals["calls"]), polls=int(totals["polls"]), failures=int(totals["failures"]),
                               tokensThisHour=tokens_hour, callsThisHour=calls_hour))
        flags = []
        for agent in agents:
            peers = [value for other, value in per_agent_tpm.items() if other != agent["agentId"]]
            median = statistics.median(peers) if peers else None
            agent["peerMedianTokensPerMission"] = round(median) if median else None
            agent["ratioToPeers"] = round(agent["tokensPerMission"] / median, 1) if median and agent["tokensPerMission"] else None
            if agent["ratioToPeers"] and agent["ratioToPeers"] >= 5:
                flags.append(dict(agentId=agent["agentId"], severity="high", finding=f"{agent['name']} spends {agent['ratioToPeers']}x its peers' median tokens per mission "
                                  f"({agent['tokensPerMission']} vs {agent['peerMedianTokensPerMission']}).", polls=agent["polls"]))
            elif agent["failures"]:
                flags.append(dict(agentId=agent["agentId"], severity="medium", finding=f"{agent['name']} has {agent['failures']} failed call(s) in telemetry."))
        return dict(source=SOURCE_LABEL, generatedAt=now(), since=since, agents=agents, flags=flags,
                    note="Tokens are estimates from local telemetry (characters/4 plus per-call overhead), not billed usage.")

    @staticmethod
    def detail_json(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:200]
