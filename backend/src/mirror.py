"""Asynchronous Supabase mirror through PostgREST. SQLite stays the source of truth.

Enabled only when SUPABASE_URL and SUPABASE_SERVICE_KEY are both set. Each put of a mirrored kind is
upserted (`Prefer: resolution=merge-duplicates`, conflict on `id`) on a background thread; failures become
store events and never raise on the request path. Column names are snake_case of the camelCase fields,
nested objects stay JSON (jsonb). See backend/SUPABASE-COLUMNS.md for the exact emitted columns.
"""
from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

from .store import now

TABLES = {"fact": "facts", "attestation": "attestations", "work_item": "work_items", "dispatch": "dispatches",
          "change": "changes", "subscription": "subscriptions",
          # contract 3
          "crew_member": "crew_members", "obligation": "obligations", "issue": "issues", "board_meeting": "board_meetings",
          "viewer_command": "viewer_commands", "agent_memory": "memories", "telemetry": "telemetry", "finding": "findings"}
# Exact emitted columns per table (backend/SUPABASE-COLUMNS.md mirrors this). A field outside the list is never sent,
# so a backend-only field can never make PostgREST reject the whole upsert (PGRST204).
COLUMNS: dict[str, tuple[str, ...]] = {
    "facts": ("id", "property_id", "asset_tag", "component_id", "attribute", "attribute_class", "value", "unit", "observed_at", "ttl_seconds",
              "expires_at", "source", "attestation_id", "version", "created_at"),
    "attestations": ("id", "property_id", "asset_tag", "component_id", "attribute", "value", "unit", "observed_at", "evidence_hashes", "checks",
                     "verdict", "source", "verifier_version", "signed_at", "public_key", "signature"),
    "work_items": ("id", "property_id", "asset_tag", "component_id", "attribute", "attribute_class", "reference", "state", "requester", "budget",
                   "deadline_at", "dispatches", "verdicts", "fact_id", "attestation_id", "receipt", "escalation_level", "created_at", "updated_at"),
    "dispatches": ("id", "channel", "to", "reference", "sent_at", "provider_ref", "body", "work_item_id", "property_id"),
    "changes": ("id", "version", "type", "property_id", "asset_tag", "ref_id", "summary", "at"),
    "subscriptions": ("id", "property_id", "callback_url", "requester", "created_at"),
    "crew_members": ("id", "site_id", "name", "role", "shift", "on_shift", "phone", "email", "contactable", "certifications", "owns", "synthetic",
                     "generator", "updated_at"),
    "obligations": ("id", "site_id", "asset_tag", "title", "rule_ref", "frequency", "last_done_at", "due_at", "status", "document_id", "owner_id",
                    "blocked_by", "blocked_reason", "synthetic", "generator", "updated_at"),
    "issues": ("id", "site_id", "asset_tag", "component_id", "kind", "severity", "status", "summary", "ref_id", "pin", "at", "updated_at",
               "scenario_id", "run_id", "source", "owner_id", "assignee_id", "obligation_id", "document_id", "synthetic"),
    "board_meetings": ("id", "site_id", "issue_id", "scenario_id", "run_id", "topic", "convened_by", "participants", "transcript", "resolution",
                       "contact", "status", "started_at", "resolved_at", "synthetic"),
    "viewer_commands": ("id", "seq", "site_id", "action", "asset_tag", "issue_id", "pin", "issued_by", "at"),
    "memories": ("id", "agent_id", "container", "kind", "content", "site_id", "refs", "at", "synthetic", "provider_status", "provider_id"),
    "telemetry": ("id", "at", "agent_id", "site_id", "kind", "tool", "tokens", "ms", "ok", "mission_id", "scenario_id", "run_id", "source",
                  "synthetic", "detail"),
    "findings": ("id", "site_id", "asset_tag", "component_id", "status", "score", "threshold", "model", "frames", "explanation", "issue_id",
                 "source", "synthetic", "run_id", "ingested_at"),
}
JSON_COLUMNS = {"value", "source", "evidence_hashes", "checks", "dispatches", "verdicts", "receipt", "certifications", "owns", "pin",
                "participants", "transcript", "contact", "refs", "frames", "explanation"}


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def row_for(kind: str, body: dict) -> dict:
    """Public (non-underscore) fields as snake_case columns, restricted to the table's documented columns."""
    allowed = set(COLUMNS.get(TABLES.get(kind, ""), ()))
    row = {}
    for key, value in body.items():
        if key.startswith("_"):
            continue
        column = snake(key)
        if allowed and column not in allowed:
            continue
        row[column] = value
    return row


class Mirror:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_KEY", "")
        self.configured = bool(self.url and self.key)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="steward-mirror") if self.configured else None
        self.lock = threading.Lock()
        self.successes = 0
        self.failures = 0

    def close(self):
        if self.executor:
            self.executor.shutdown(wait=True)

    def status(self) -> dict:
        if not self.configured:
            return dict(status="not_configured", detail="Set SUPABASE_URL and SUPABASE_SERVICE_KEY to mirror reality records, crew, obligations, issues, board meetings, viewer commands, memories, telemetry and findings.")
        recorded = self.store.meta("integration:supabase")
        if recorded:
            return json.loads(recorded)
        return dict(status="not_configured", detail="Supabase credentials present; no upsert has been attempted yet.", checkedAt=now())

    def put(self, kind: str, body: dict, property_id: str = ""):
        """Queue an upsert. Never raises."""
        if not self.configured or kind not in TABLES:
            return
        row = row_for(kind, body)
        columns = COLUMNS[TABLES[kind]]
        if property_id and "property_id" in columns and "property_id" not in row:
            row["property_id"] = property_id
        try:
            self.executor.submit(self._upsert_guarded, TABLES[kind], [row], property_id or row.get("property_id", ""))
        except RuntimeError:
            pass  # executor already shut down

    def upsert(self, table: str, rows: list[dict]) -> None:
        """Synchronous upsert of rows into `table`; raises on failure."""
        headers = {"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                   "Prefer": "resolution=merge-duplicates,return=minimal"}
        with httpx.Client(transport=self.transport, timeout=10) as client:
            response = client.post(f"{self.url}/rest/v1/{table}", params={"on_conflict": "id"}, headers=headers, content=json.dumps(rows))
        response.raise_for_status()

    def _upsert_guarded(self, table: str, rows: list[dict], property_id: str):
        try:
            self.upsert(table, rows)
        except Exception as error:
            with self.lock:
                self.failures += 1
            detail = f"Upsert into {table} failed ({type(error).__name__}). Local SQLite remains authoritative."
            self.store.meta("integration:supabase", json.dumps(dict(status="error", detail=detail, checkedAt=now())))
            if property_id:
                self.store.event(property_id, "portfolio", "mirror.failed", "Supabase mirror failed", detail)
            return
        with self.lock:
            self.successes += 1
        self.store.meta("integration:supabase", json.dumps(dict(status="connected", detail=f"PostgREST upsert into {table} succeeded.", checkedAt=now())))
