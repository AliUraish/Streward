# Steward local backend

Canonical application settings use `STEWARD_*`. Existing `PHY_*` environment variables remain backward-compatible aliases; an explicitly set `STEWARD_*` value takes precedence. The current database is `backend/data/steward.sqlite3`. On the first upgrade, the application snapshots the previous database with SQLite's backup API (including committed WAL data), keeps a recovery copy under `.migration-backups/`, and migrates display branding without changing record IDs, attachments, jobs or property names. Original seed PDF headers are updated; uploaded originals remain byte-for-byte unchanged.

Run `bash backend/run.sh` from the repository root. The backend binds to `127.0.0.1:8001`; the Next.js application proxies `/api/*`. No cloud deployment is required or performed. `/health` verifies SQLite access; `/docs` contains the interactive API documentation; `/mcp` is a stateless Streamable HTTP MCP JSON-RPC endpoint.

The first startup generates three original project workspaces, original PDF project specifications, 24 scene objects per property, 96 linked project checks per property, and synthetic baseline evidence. These are demonstration project records, not actual building code, physical inspection, or official approval. Original fixture PDFs carry the same disclosure. Uploaded originals and source pages remain available.

The default property workers perform actual deterministic record checks: extract project source text, validate unique equipment tags and model bounds, match evidence to property/equipment/requirement, persist assessments, recompute readiness, create source-linked memory, and generate an escaped HTML/JSON report. They do not pretend to run model vision. The portfolio coordinator queues work in the three separate property contexts. Jobs, checkpoints, append-only events, user edits and files persist in `backend/data`; interrupted jobs resume after restart. There are no artificial progress delays.

Copy `.env.example` to `.env` to configure optional providers. Credentials stay server-side. `STEWARD_MODEL_PROVIDER=openai` uses an OpenAI-compatible chat gateway with `STEWARD_MODEL_BASE_URL`, `STEWARD_MODEL_API_KEY` and `STEWARD_MODEL_NAME`; `claude_cli` uses a previously authenticated local Claude CLI without granting file or shell tools. `eve` invokes the optional local model runtime using its configured provider keys. No provider is marked connected merely because an environment variable exists; failures produce an explicit local fallback and event.

`GET /api/integrations?propertyId=cedar` returns explicit action `capabilities` derived from current credentials, the selected property's identity, and configured action gates. The frontend uses these booleans rather than inferring permission from prose or a historical connection status. Capability availability means an action can be attempted, not that the provider has already verified the credentials.

## Evidence import

Evidence images and PDFs are preserved. Unstructured attachments remain pending without a model review. Machine-readable JSON records are checked for exact identifiers:

```json
{
  "propertyId": "cedar",
  "componentId": "pump-01",
  "tag": "P-101",
  "requirementId": "cedar-pump-01-cond",
  "outcome": "pass",
  "note": "Project observation record"
}
```

A passing matching record verifies consistency of the submitted record; it does not establish physical condition or legal compliance. Mismatched property, asset or requirement IDs are rejected as an issue. A filename or note containing “PASS” cannot verify a check. A later matching record can supersede an earlier record for the check; the evidence history remains intact.

Documents are indexed for search. Explicit project requirement lines can be imported using `[REQ:PROJECT-88] P-101 | Title | Description`. General source prose is not automatically converted into asserted legal requirements. Scanned PDF text is not fabricated when OCR is unavailable.

## Optional providers

- **Supermemory:** namespace-scoped `/ns/steward-local-{propertyId}` API. `POST /api/properties/{id}/memory/sync` submits source-linked local memories; ingestion is asynchronous. `/memory/recall` accepts `{ "query": "..." }` and retrieves the profile and hybrid search separately.
- **Inkbox:** official Python SDK pinned in requirements. `GET /api/properties/{id}/identity` checks an existing configured handle; `/inbox` reads messages. Identity creation at `POST /identity` is disabled until `STEWARD_ALLOW_IDENTITY_PROVISION=true`. Sending at `POST /messages` requires both `STEWARD_ALLOW_EXTERNAL_MESSAGES=true` and every recipient in `INKBOX_ALLOWED_RECIPIENTS`. No external messages are sent by default or during tests.
- **Stripe:** proposals are local records awaiting authorization. `POST /api/properties/{id}/purchases/{purchaseId}/checkout` accepts only `sk_test_` keys and creates an idempotent sandbox merchant Checkout session. This is not supplier procurement. `/api/integrations/stripe/webhook` verifies the raw-body HMAC signature, timestamp, test mode, session ID, amount and currency, then deduplicates receipt events. A test payment never marks an order delivered or installed. Live keys/events are refused.
- **InsForge:** `POST /api/integrations/insforge/check` makes a read-only request against the existing project's `steward_properties` table. Missing schema is reported; it does not silently migrate or replace the working local database.
- **MCP:** initialize, tools/list, tools/call, resources/list/read and ping share the same application services as HTTP. Tools include project context, components, source search, local inspection jobs, portfolio coordination, memory and reports. No hosted Manufact deployment is created.

Run tests with `backend/.venv/bin/python -m pytest backend/tests -q` from the root or `.venv/bin/python -m pytest -q` from `backend`. The tests use temporary SQLite stores and mock provider transports; they perform no live messages, purchases or cloud provisioning.
