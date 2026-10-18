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
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx

from .env import env
from .providers import clean_env
from .store import now, uid

BASE_URL = "https://api.supermemory.ai"
NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9_:-]{1,100}$")
MEMORY_KINDS = ("decision", "board_meeting", "scenario_outcome", "reconfigure", "document_review", "note")


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
              synthetic: bool = False) -> dict:
        record = dict(id=uid("amem"), agentId=agent_id, container=namespace_for(agent_id), kind=kind if kind in MEMORY_KINDS else "note",
                      content=content[:4000], siteId=site_id, refs={k: v for k, v in (refs or {}).items() if v}, at=now(),
                      synthetic=bool(synthetic), providerStatus="local_only", providerId=None)
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
                                            synthetic=record.get("synthetic", False)))
            record.update(providerStatus=str(response.get("status") or "queued"), providerId=response.get("id"), syncedAt=now())
        except Exception as error:
            record.update(providerStatus="failed", providerError=f"{type(error).__name__}"[:120])
        self._save(record)

    def local(self, agent_id: str, query: str | None = None, limit: int = 20) -> list[dict]:
        records = [m for m in self.store.all("agent_memory", "") if m["agentId"] == agent_id]
        if query:
            tokens = [t for t in re.findall(r"[a-z0-9.-]+", query.casefold()) if len(t) > 1]
            scored = []
            for record in records:
                text = record["content"].casefold()
                score = sum(text.count(token) for token in tokens)
                if score:
                    scored.append((score, record))
            records = [record for _, record in sorted(scored, key=lambda pair: (pair[0], pair[1]["at"]), reverse=True)]
        else:
            records = sorted(records, key=lambda r: r["at"], reverse=True)
        return records[:limit]

    def recall(self, agent_id: str, query: str | None = None, limit: int = 20) -> dict:
        namespace = namespace_for(agent_id)
        result = dict(agentId=agent_id, container=namespace, query=query or None, local=self.local(agent_id, query, limit),
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
