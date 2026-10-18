"""Asynchronous Supabase mirror through PostgREST. SQLite stays the source of truth.

Enabled only when SUPABASE_URL and SUPABASE_SERVICE_KEY are both set. Each put of a mirrored kind is queued and
upserted (`Prefer: resolution=merge-duplicates`, conflict on `id`; attestations `ignore-duplicates`, they are
append-only) on one background thread that batches what is pending; failures become store events and never raise on
the request path. Column names are snake_case of the camelCase fields, nested objects stay JSON (jsonb). See
backend/SUPABASE-COLUMNS.md for the exact emitted columns.

Authority (supabase/migrations/0003_authority.sql): when agent passwords and the publishable key are configured, a row
an agent originated is written with that agent's own access token, so Postgres's RLS decides; a refusal is recorded,
never retried with the service key. System rows (machine readings, seeds, the change feed) use the service key.
Contact details never leave the backend: phone numbers and email addresses in mirrored text are masked (signed
attestations are sent byte-exact, with the canonical JSON the backend signed as `signed_payload`).
Every write asks the budget guard (src/supa_budget.py) first: past 80 % of the database cap simulated sensor rows stay
local, at the cap every row does.
"""
from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .signing import canonical_json, verify as verify_signature
from .store import now
from .supa_auth import AgentTokens
from .supa_authority import author_for, current_actor
from .supa_budget import Budget
from .supa_client import Supa, SupabaseError, publishable_key, service_key, supabase_url

TABLES = {"fact": "facts", "attestation": "attestations", "work_item": "work_items", "dispatch": "dispatches",
          "change": "changes", "subscription": "subscriptions",
          # contract 3
          "crew_member": "crew_members", "obligation": "obligations", "issue": "issues", "conversation": "conversations",
          "viewer_command": "viewer_commands", "agent_memory": "memories", "telemetry": "telemetry", "finding": "findings",
          # contract 4
          "notification": "notifications", "maintenance_window": "maintenance_windows", "eye_frame": "eye_frames"}
# Exact emitted columns per table (backend/SUPABASE-COLUMNS.md mirrors this). A field outside the list is never sent,
# so a backend-only field can never make PostgREST reject the whole upsert (PGRST204).
COLUMNS: dict[str, tuple[str, ...]] = {
    "facts": ("id", "property_id", "asset_tag", "component_id", "attribute", "attribute_class", "value", "unit", "observed_at", "ttl_seconds",
              "expires_at", "source", "attestation_id", "version", "created_at"),
    "attestations": ("id", "property_id", "asset_tag", "component_id", "attribute", "value", "unit", "observed_at", "evidence_hashes", "checks",
                     "verdict", "source", "verifier_version", "signed_at", "public_key", "signature", "signed_payload"),
    "work_items": ("id", "property_id", "asset_tag", "component_id", "attribute", "attribute_class", "reference", "state", "requester", "budget",
                   "deadline_at", "dispatches", "verdicts", "fact_id", "attestation_id", "receipt", "escalation_level", "created_at", "updated_at"),
    "dispatches": ("id", "channel", "to", "reference", "sent_at", "provider_ref", "body", "work_item_id", "property_id"),
    "changes": ("id", "version", "type", "property_id", "asset_tag", "ref_id", "summary", "at"),
    "subscriptions": ("id", "property_id", "callback_url", "requester", "created_at"),
    "crew_members": ("id", "site_id", "name", "role", "shift", "on_shift", "phone", "email", "contactable", "certifications", "owns", "synthetic",
                     "generator", "updated_at"),
    "obligations": ("id", "site_id", "asset_tag", "title", "rule_ref", "frequency", "last_done_at", "due_at", "status", "document_id", "owner_id",
                    "blocked_by", "blocked_reason", "regulation_ids", "note", "synthetic", "generator", "updated_at"),
    "issues": ("id", "site_id", "asset_tag", "component_id", "kind", "severity", "status", "summary", "ref_id", "pin", "at", "updated_at",
               "scenario_id", "run_id", "source", "owner_id", "assignee_id", "obligation_id", "document_id", "evidence_frame_ids", "synthetic"),
    "conversations": ("id", "kind", "topic", "convener", "participants", "site_ids", "transport", "provider_task_ids", "a2a_task_ids", "transcript",
                      "summary", "summary_by", "started_at", "ended_at", "status", "issue_id", "issue_kind", "scenario_id", "run_id", "resolution",
                      "contact", "synthetic"),
    "viewer_commands": ("id", "seq", "site_id", "action", "asset_tag", "issue_id", "pin", "issued_by", "at"),
    "memories": ("id", "agent_id", "container", "kind", "content", "site_id", "refs", "at", "synthetic", "provider_status", "provider_id"),
    "telemetry": ("id", "at", "agent_id", "site_id", "kind", "tool", "tokens", "ms", "ok", "mission_id", "scenario_id", "run_id", "source",
                  "synthetic", "detail"),
    "findings": ("id", "site_id", "asset_tag", "component_id", "status", "score", "threshold", "model", "frames", "explanation", "issue_id",
                 "source", "synthetic", "run_id", "ingested_at"),
    "notifications": ("id", "site_id", "workflow_id", "issue_id", "sender", "to_kind", "to", "to_name", "channel", "text", "mode", "notice_id",
                      "a2a_task_id", "transport", "synthetic", "at"),
    "maintenance_windows": ("id", "site_ids", "date", "scope", "examiner", "status", "conversation_id", "approval_conversation_id", "asset_tags",
                            "obligation_id", "proposed_by", "approved_by", "scenario_id", "synthetic", "created_at", "updated_at"),
    "eye_frames": ("id", "seq", "site_id", "command_id", "action", "params", "actor", "camera", "visible_pins", "index", "renderer_id", "size",
                   "sha256", "url", "at"),
}
# jsonb columns per table (documentation and the SQL migration; values are sent as JSON either way).
JSON_BY_TABLE: dict[str, set[str]] = {
    "facts": {"value", "source"}, "attestations": {"value", "evidence_hashes", "checks", "source"}, "work_items": {"dispatches", "verdicts", "receipt"},
    "dispatches": set(), "changes": set(), "subscriptions": set(), "crew_members": {"certifications", "owns"}, "obligations": {"regulation_ids"},
    "issues": {"pin", "evidence_frame_ids"}, "conversations": {"participants", "site_ids", "provider_task_ids", "a2a_task_ids", "transcript", "summary", "contact"},
    "viewer_commands": {"pin"}, "memories": {"refs"}, "telemetry": set(), "findings": {"frames", "explanation"}, "notifications": set(),
    "maintenance_windows": {"site_ids", "asset_tags"}, "eye_frames": {"params", "camera", "visible_pins"},
}
JSON_COLUMNS = set().union(*JSON_BY_TABLE.values())


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


BATCH_ROWS = 200
PHONE_RE = re.compile(r"\+\d[\d ]{6,16}\d")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
REDACT_SKIP = {"id", "signature", "public_key", "signed_payload", "sha256", "url", "reference", "evidence_hashes"}
MACHINE_TABLES = {"facts", "attestations", "changes"}


def mask_phone(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "••• ••• " + digits[-4:]


def mask_email(match: re.Match) -> str:
    local, _, domain = match.group(0).partition("@")
    return f"{local[:1]}•••@{domain}"


def redact_text(text: str) -> str:
    return EMAIL_RE.sub(mask_email, PHONE_RE.sub(mask_phone, text))


def redact(value, key: str = ""):
    """Mask phone numbers and email addresses in every string of a row (ids, hashes and signatures untouched)."""
    if key in REDACT_SKIP or key.endswith("_id") or key.endswith("_ids"):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    return value


def signed_payload(body: dict) -> str | None:
    """The exact canonical JSON the backend signed for this attestation, when its signature verifies here."""
    payload = {k: v for k, v in body.items() if k != "signature" and not k.startswith("_")}
    try:
        if body.get("signature") and body.get("publicKey") and verify_signature(payload, body["signature"], body["publicKey"]):
            return canonical_json(payload).decode("ascii")
    except Exception:
        return None
    return None


def build_row(kind: str, body: dict, property_id: str = "") -> dict:
    """The row the mirror sends for one record: documented columns, site, signed payload or redaction."""
    table = TABLES[kind]
    row = row_for(kind, body)
    if property_id and "property_id" in COLUMNS[table] and "property_id" not in row:
        row["property_id"] = property_id
    if table == "attestations":
        row["signed_payload"] = signed_payload(body)
    else:
        row = redact(row)
    return json.loads(json.dumps(row, ensure_ascii=False, default=str))  # a snapshot: callers keep mutating their records


def is_machine(table: str, body: dict) -> bool:
    source = body.get("source") if isinstance(body.get("source"), dict) else {}
    return table in MACHINE_TABLES and bool(body.get("simulated") or source.get("kind") in ("sensor", "patrol", "scan"))


class Mirror:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport
        self.url = supabase_url()
        self.key = service_key()
        self.configured = bool(self.url and self.key)
        self.supa = Supa(self.url, self.key, publishable_key(), transport)
        self.budget = Budget(store)
        self.tokens = AgentTokens(self.supa, on_event=self._service_event)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="steward-mirror") if self.configured else None
        self.lock = threading.Lock()
        self.pending: list[tuple] = []
        self.successes = 0
        self.failures = 0
        self.refused = 0
        self.shed = 0
        self.rows_written = 0
        self.by_author: dict[str, int] = {}
        self.last_refusal: dict | None = None
        self.services = None  # SupaServices (storage, HUD, inbox, usage poller) when the app started them

    redact_text = staticmethod(redact_text)

    def close(self):
        if self.services is not None:
            try:
                self.services.close()
            except Exception:
                pass
            self.services = None
        if self.executor:
            self.executor.shutdown(wait=True)
        self.supa.close()

    def status(self) -> dict:
        if not self.configured:
            return dict(status="not_configured", detail="Set SUPABASE_URL and SUPABASE_SERVICE_KEY to mirror reality records, crew, obligations, issues, board meetings, viewer commands, memories, telemetry and findings.")
        recorded = self.store.meta("integration:supabase")
        if recorded:
            return json.loads(recorded)
        return dict(status="not_configured", detail="Credentials present; no upsert has been attempted yet.", checkedAt=now())

    def stats(self) -> dict:
        with self.lock:
            pending = len(self.pending)
        return dict(configured=self.configured, agentAuth=self.tokens.status(), pending=pending, batchesOk=self.successes, batchesFailed=self.failures,
                    rowsWritten=self.rows_written, rowsRefusedByPostgres=self.refused, rowsShedForBudget=self.shed, rowsByWriter=dict(self.by_author),
                    lastRefusal=self.last_refusal, dbState=self.budget.db_state())

    # ---- put ------------------------------------------------------------------------------------------------------

    def put(self, kind: str, body: dict, property_id: str = ""):
        """Queue an upsert. Never raises."""
        if not self.configured or kind not in TABLES:
            return
        if self.services is not None:
            self.services.tap(kind, body)  # HUD and Storage have their own budgets; a full database must not silence them
        try:
            table = TABLES[kind]
            state = self.budget.db_state()
            if state == "full":
                self.budget.refuse("db_mb", f"Database at its cap; {table} rows stay in local SQLite.")
                self.shed += 1
                return
            if state == "shed" and is_machine(table, body):
                self.shed += 1
                return
            row = build_row(kind, body, property_id)
            author = author_for(table, row, body, current_actor.get()) if self.tokens.enabled else None
            with self.lock:
                self.pending.append((table, row, author, property_id or row.get("property_id") or row.get("site_id") or ""))
            self.executor.submit(self._drain)
        except RuntimeError:
            return  # executor already shut down
        except Exception as error:
            self._service_event("Supabase mirror skipped a record", f"{kind}: {type(error).__name__}")

    # ---- writer -----------------------------------------------------------------------------------------------------

    def _drain(self):
        with self.lock:
            items, self.pending = self.pending, []
        if not items:
            return
        last = {}
        for index, (table, row, _author, _site) in enumerate(items):
            last[(table, row.get("id"))] = index
        groups: OrderedDict[tuple, list] = OrderedDict()
        for index, (table, row, author, site) in enumerate(items):
            if last[(table, row.get("id"))] != index:
                continue  # a later version of the same row is pending; send only that one
            groups.setdefault((table, author), []).append((row, site))
        for (table, author), entries in groups.items():
            for start in range(0, len(entries), BATCH_ROWS):
                chunk = entries[start:start + BATCH_ROWS]
                self._write(table, author, [row for row, _ in chunk], next((site for _, site in chunk if site), ""))

    def _write(self, table: str, author: str | None, rows: list[dict], site: str, split: bool = True):
        token = None
        if author:
            token = self.tokens.token(author)
            if token is None:
                self._refused(table, author, rows, site, "no access token for this agent (sign-in failed or no password configured)", None)
                return
        try:
            self.supa.upsert(table, rows, token=token, ignore_duplicates=(table == "attestations"))
        except SupabaseError as error:
            if error.status in (401, 403) or error.code == "42501":
                self._refused(table, author, rows, site, error.message or str(error), error.code)
                return
            if split and len(rows) > 1 and 400 <= error.status < 500:
                for row in rows:  # isolate the row Postgres rejects instead of dropping the whole batch
                    self._write(table, author, [row], site, split=False)
                return
            self._failed(table, site, error)
            return
        except Exception as error:
            self._failed(table, site, error)
            return
        with self.lock:
            self.successes += 1
            self.rows_written += len(rows)
            writer = author or "service_role"
            self.by_author[writer] = self.by_author.get(writer, 0) + len(rows)
        self.store.meta("integration:supabase", json.dumps(dict(status="connected", detail=f"PostgREST upsert into {table} succeeded"
                                                                f" as {author or 'the service role'}.", checkedAt=now())))

    def _failed(self, table: str, site: str, error: Exception):
        with self.lock:
            self.failures += 1
        detail = f"Upsert into {table} failed ({type(error).__name__}). Local SQLite remains authoritative."
        self.store.meta("integration:supabase", json.dumps(dict(status="error", detail=detail, checkedAt=now())))
        if site:
            self.store.event(site, "portfolio", "mirror.failed", "Supabase mirror failed", detail)

    def _refused(self, table: str, author: str | None, rows: list[dict], site: str, message: str, code: str | None):
        with self.lock:
            self.refused += len(rows)
            self.last_refusal = dict(table=table, writer=author, rows=len(rows), code=code, message=message[:300], at=now())
        try:
            if self.store.mark_once(f"supa:refused:{table}:{author}:{now()[:10]}"):
                self.store.event(site or "myer-plant", author or "director", "mirror.refused", f"Supabase refused a write by {author or 'the service role'}",
                                 f"{table}: {message[:300]} (row kept in local SQLite)")
        except Exception:
            pass

    def _service_event(self, title: str, detail: str):
        try:
            if self.store.mark_once(f"supa:event:{title}:{now()[:13]}"):
                self.store.event("myer-plant", "director", "supabase.service", title, detail[:500])
        except Exception:
            pass

    # ---- direct upsert (backfill) --------------------------------------------------------------------------------------

    def upsert(self, table: str, rows: list[dict], token: str | None = None) -> None:
        """Synchronous upsert of rows into `table` (service key unless a token is given); raises on failure."""
        self.supa.upsert(table, rows, token=token, ignore_duplicates=(table == "attestations"))

    def write_now(self, table: str, rows: list[dict], author: str | None) -> dict:
        """Synchronous author-aware write used by the backfill: returns {written, refused, failed}."""
        before = (self.rows_written, self.refused, self.failures)
        site = (rows[0].get("property_id") or rows[0].get("site_id") or "") if rows else ""
        if rows:
            self._write(table, author, rows, site)
        return dict(written=self.rows_written - before[0], refused=self.refused - before[1], failed=self.failures - before[2])
