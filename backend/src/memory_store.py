"""Per-agent memory (contract 3 §8): a local mirror that always works, plus a Supermemory adapter behind a gate.

Each agent has one Supermemory namespace, `steward-<agentId>` (Supermemory API v5 calls these namespaces; v3/v4
called them container tags, same values). Namespace names allow letters, digits, `_`, `:` and `-`, so
`steward-warden:myer-plant` is valid. The first write to a namespace creates it.

- Write: `POST https://api.supermemory.ai/ns/{namespace}/document` `{content, id, metadata}`; ingestion is
  asynchronous (response `{id, status}`), so a submitted memory is not immediately searchable.
- Recall: `POST https://api.supermemory.ai/ns/{namespace}/search` `{query, searchMode: "hybrid", limit}` →
  `{results, searchTime}`.

Live calls happen only when `SUPERMEMORY_API_KEY` is set **and** `STEWARD_SUPERMEMORY_LIVE=true` (off by default).
Agents write a memory after each decision, board meeting and scenario outcome; the local record (kind
`agent_memory`, mirrored to Supabase `memories`) is the source of truth and says whether the provider accepted it.
Every memory carries `origin` (seed | run | workflow | inkbox, see real_only.py) and reads hide seed memories unless
`include=all`; `GET /api/memory` (`feed`) aggregates every agent's memories for the memory page.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx

from .env import env
from .providers import clean_env
from .real_only import ORIGINS, conversation_origins, include_all, memory_creation_origin, memory_origin
from .store import now, uid

BASE_URL = "https://api.supermemory.ai"
NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9_:-]{1,100}$")
MEMORY_KINDS = ("decision", "board_meeting", "scenario_outcome", "reconfigure", "document_review", "note")
# The record a memory came from, most specific first (the memory page links to it).
SOURCE_REFS = (("runId", "scenario_run"), ("workflowId", "fix_workflow"), ("patrolId", "patrol"), ("alertId", "owner_alert"),
               ("conversationId", "conversation"), ("missionId", "mission"), ("toolId", "forged_tool"), ("documentId", "document"),
               ("maintenanceId", "maintenance_window"), ("issueId", "issue"), ("scenarioId", "scenario"), ("agentId", "agent_config"))
LIVE_SEARCH_NAMESPACES = 4  # at most one site team per memory-page search when the Supermemory live switch is on


def search_tokens(query: str | None) -> list[str]:
    text = (query or "").strip().casefold()
    tokens = [t for t in re.findall(r"[\w.\-]+", text) if len(t) > 1 or not t.isascii()]
    return tokens or ([text] if text else [])


def namespace_for(agent_id: str) -> str:
    namespace = f"steward-{agent_id}"
    if not NAMESPACE_RE.match(namespace):
        raise ValueError(f"Invalid Supermemory namespace {namespace!r}")
    return namespace


class SupermemoryClient:
    def __init__(self, transport=None):
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(clean_env("SUPERMEMORY_API_KEY"))

    @property
    def live(self) -> bool:
        return self.configured and env("STEWARD_SUPERMEMORY_LIVE", "false").strip().lower() == "true"

    def _post(self, namespace: str, path: str, body: dict) -> dict:
        headers = {"Authorization": "Bearer " + clean_env("SUPERMEMORY_API_KEY"), "Content-Type": "application/json"}
        with httpx.Client(transport=self.transport, timeout=20) as client:
            response = client.post(f"{BASE_URL}/ns/{quote(namespace, safe=':')}/{path}", headers=headers, content=json.dumps(body))
        response.raise_for_status()
        return response.json()

    def add(self, namespace: str, memory_id: str, content: str, metadata: dict) -> dict:
        clean = {k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool)) or (isinstance(v, list) and all(isinstance(i, str) for i in v))}
        return self._post(namespace, "document", {"content": content[:12000], "id": memory_id, "metadata": clean})

    def search(self, namespace: str, query: str, limit: int = 5) -> dict:
        return self._post(namespace, "search", {"query": query[:2000], "searchMode": "hybrid", "limit": limit})


class MemoryStore:
    def __init__(self, service, client: SupermemoryClient | None = None):
        self.service = service
        self.store = service.store
        self.client = client or SupermemoryClient()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="steward-memory") if service.start_workers else None

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=True)

    def write(self, agent_id: str, content: str, kind: str = "note", refs: dict | None = None, site_id: str | None = None,
              synthetic: bool = False, origin: str | None = None) -> dict:
        """`origin` (seed | run | workflow | inkbox) defaults to `run` for a scenario run's memory, else `workflow`: a write
        happens while the system runs, so it is never `seed` unless a seed loader says so."""
        clean_refs = {k: v for k, v in (refs or {}).items() if v}
        record = dict(id=uid("amem"), agentId=agent_id, container=namespace_for(agent_id), kind=kind if kind in MEMORY_KINDS else "note",
                      content=content[:4000], siteId=site_id, refs=clean_refs, at=now(),
                      synthetic=bool(synthetic), origin=memory_creation_origin(clean_refs, origin), providerStatus="local_only", providerId=None)
        self._save(record)
        if self.client.live:
            if self.executor:
                try:
                    self.executor.submit(self._sync, record["id"])
                except RuntimeError:
                    pass
            else:
                self._sync(record["id"])
        return self.store.get("agent_memory", record["id"], "") or record

    def _save(self, record: dict):
        self.store.put("agent_memory", record, "")
        reality = getattr(self.service, "reality", None)
        if reality is not None:
            reality.mirror.put("agent_memory", record, record.get("siteId") or "")

    def _sync(self, memory_id: str):
        record = self.store.get("agent_memory", memory_id, "")
        if not record:
            return
        try:
            response = self.client.add(record["container"], record["id"], record["content"],
                                       dict(agentId=record["agentId"], kind=record["kind"], siteId=record.get("siteId") or "", at=record["at"],
                                            synthetic=record.get("synthetic", False), origin=record.get("origin") or ""))
            record.update(providerStatus=str(response.get("status") or "queued"), providerId=response.get("id"), syncedAt=now())
        except Exception as error:
            record.update(providerStatus="failed", providerError=f"{type(error).__name__}"[:120])
        self._save(record)

    def _classified(self, records: list[dict]) -> list[dict]:
        """Every record with `origin`; one written before the backfill (or by other code) is classified on read."""
        conversations = None
        out = []
        for record in records:
            if record.get("origin") not in ORIGINS:
                if conversations is None:
                    conversations = conversation_origins(self.store)
                record = dict(record, origin=memory_origin(record, conversations))
            out.append(record)
        return out

    def local(self, agent_id: str, query: str | None = None, limit: int = 20, include: str | None = None) -> list[dict]:
        """This agent's local memories, newest first (best match first with `query`); seed memories only with `include=all`."""
        records = self._classified([m for m in self.store.all("agent_memory", "") if m.get("agentId") == agent_id])
        if not include_all(include):
            records = [m for m in records if m["origin"] != "seed"]
        if query:
            tokens = [t for t in re.findall(r"[a-z0-9.-]+", query.casefold()) if len(t) > 1]
            scored = []
            for record in records:
                text = (record.get("content") or "").casefold()
                score = sum(text.count(token) for token in tokens)
                if score:
                    scored.append((score, record))
            records = [record for _, record in sorted(scored, key=lambda pair: (pair[0], pair[1].get("at") or ""), reverse=True)]
        else:
            records = sorted(records, key=lambda r: r.get("at") or "", reverse=True)
        return records[:limit]

    def recall(self, agent_id: str, query: str | None = None, limit: int = 20, include: str | None = None) -> dict:
        namespace = namespace_for(agent_id)
        result = dict(agentId=agent_id, container=namespace, query=query or None, local=self.local(agent_id, query, limit, include),
                      supermemory=dict(live=self.client.live, configured=self.client.configured))
        if not self.client.live:
            result["supermemory"]["detail"] = ("Set STEWARD_SUPERMEMORY_LIVE=true to recall from Supermemory." if self.client.configured
                                               else "SUPERMEMORY_API_KEY is not set; the local mirror is authoritative.")
            return result
        if not query:
            result["supermemory"]["detail"] = "Pass ?query= to search the agent's Supermemory namespace."
            return result
        try:
            payload = self.client.search(namespace, query, limit=min(limit, 10))
            result["supermemory"].update(results=payload.get("results", []), searchTime=payload.get("searchTime"))
        except Exception as error:
            result["supermemory"].update(error=f"Supermemory search failed ({type(error).__name__}); local mirror shown.")
        return result

    # ---- the memory page: every agent's memories -----------------------------------------------------------------

    @staticmethod
    def item(record: dict) -> dict:
        from .agents import display_name
        refs = dict(record.get("refs") or {})
        agent = record.get("agentId") or ""
        source = next((dict(kind=kind, id=refs[key]) for key, kind in SOURCE_REFS if refs.get(key)), dict(kind="agent", id=agent or None))
        content = record.get("content") or ""
        return dict(id=record.get("id"), agentId=agent, agentName=display_name(agent) if agent else "an agent", siteId=record.get("siteId"),
                    kind=record.get("kind") or "note", text=content, content=content, refs=refs, source=source, origin=record.get("origin"),
                    at=record.get("at"), container=record.get("container"), providerStatus=record.get("providerStatus"))

    def feed(self, site_id: str | None = None, agent_id: str | None = None, query: str | None = None, limit: int = 100,
             include: str | None = None) -> dict:
        """`GET /api/memory`: every agent's local memories, newest first, seed memories hidden unless `include=all`; `query`
        keeps the memories that contain every word (text, agent, kind, site and refs). Supermemory is searched only when
        its live switch is on, with a query, for one agent or one site team (never more than 4 namespaces)."""
        from .agents import display_name, site_team
        everything = include_all(include)
        records = self._classified(self.store.all("agent_memory", ""))
        hidden = 0
        if not everything:
            kept = [m for m in records if m["origin"] != "seed"]
            hidden, records = len(records) - len(kept), kept
        if site_id:
            records = [m for m in records if m.get("siteId") == site_id]
        if agent_id:
            records = [m for m in records if m.get("agentId") == agent_id]
        tokens = search_tokens(query)
        items = []
        for record in records:
            entry = self.item(record)
            if tokens:
                haystack = " ".join([entry["text"], entry["agentName"], entry["agentId"], entry["kind"], entry["siteId"] or "",
                                     " ".join(str(v) for v in entry["refs"].values())]).casefold()
                if not all(token in haystack for token in tokens):
                    continue
            items.append(entry)
        items.sort(key=lambda entry: entry["at"] or "", reverse=True)
        supermemory = dict(live=self.client.live, configured=self.client.configured)
        result = dict(items=items[:limit], total=len(items), hidden=hidden, include="all" if everything else "real", query=(query or "").strip() or None,
                      siteId=site_id, agentId=agent_id, source="local", supermemory=supermemory)
        if not self.client.live:
            supermemory["detail"] = ("Set STEWARD_SUPERMEMORY_LIVE=true to also search Supermemory." if self.client.configured
                                     else "SUPERMEMORY_API_KEY is not set; the local mirror is authoritative.")
            return result
        agents = [agent_id] if agent_id else (site_team(site_id) if site_id else [])
        if not tokens or not agents:
            supermemory["detail"] = "Pass ?query= with agentId or siteId to also search the agents' Supermemory namespaces."
            return result
        results, errors = [], []
        for agent in agents[:LIVE_SEARCH_NAMESPACES]:
            try:
                payload = self.client.search(namespace_for(agent), query, limit=min(limit, 10))
                results += [dict(r, agentId=agent, agentName=display_name(agent)) for r in payload.get("results", []) if isinstance(r, dict)]
            except Exception as error:
                errors.append(f"{agent} ({type(error).__name__})")
        supermemory.update(results=results, searched=[namespace_for(a) for a in agents[:LIVE_SEARCH_NAMESPACES]])
        if errors:
            supermemory["error"] = "Supermemory search failed for " + ", ".join(errors) + "; local memories shown."
        return result
