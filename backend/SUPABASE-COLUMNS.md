# Supabase mirror: exact columns emitted by the backend

Source: `backend/src/mirror.py` (`TABLES`, `COLUMNS`, `row_for`). Every public (non-underscore) field of a record is emitted
with its name converted from camelCase to snake_case, **restricted to the columns listed here** (anything else is dropped
before the upsert, so a backend-only field can never make PostgREST reject a row). Nested objects and arrays are sent as JSON
and must be `jsonb`. Upserts go to `POST {SUPABASE_URL}/rest/v1/{table}?on_conflict=id` with
`Prefer: resolution=merge-duplicates,return=minimal`, so every table needs `id text primary key`. Timestamps (`*_at`, `at`) are
ISO-8601 UTC strings (`timestamptz` works; `text` also works). A row may omit columns the record does not have yet; missing
values must therefore be nullable (except `id`).

| table | backend kind | columns (in emitted order) | jsonb columns | non-text columns |
| --- | --- | --- | --- | --- |
| `facts` | `fact` | `id`, `property_id`, `asset_tag`, `component_id`, `attribute`, `attribute_class`, `value`, `unit`, `observed_at`, `ttl_seconds`, `expires_at`, `source`, `attestation_id`, `version`, `created_at` | `value`, `source` | `ttl_seconds` (int), `version` (int) |
| `attestations` | `attestation` | `id`, `property_id`, `asset_tag`, `component_id`, `attribute`, `value`, `unit`, `observed_at`, `evidence_hashes`, `checks`, `verdict`, `source`, `verifier_version`, `signed_at`, `public_key`, `signature`, `signed_payload` | `value`, `evidence_hashes`, `checks`, `source` | none |
| `work_items` | `work_item` | `id`, `property_id`, `asset_tag`, `component_id`, `attribute`, `attribute_class`, `reference`, `state`, `requester`, `budget`, `deadline_at`, `dispatches`, `verdicts`, `fact_id`, `attestation_id`, `receipt`, `escalation_level`, `created_at`, `updated_at` | `dispatches`, `verdicts`, `receipt` | `budget` (numeric), `escalation_level` (int) |
| `dispatches` | `dispatch` | `id`, `channel`, `to`, `reference`, `sent_at`, `provider_ref`, `body`, `work_item_id`, `property_id` | none | none |
| `changes` | `change` | `id`, `version`, `type`, `property_id`, `asset_tag`, `ref_id`, `summary`, `at` | none | `version` (int) |
| `subscriptions` | `subscription` | `id`, `property_id`, `callback_url`, `requester`, `created_at` | none | none |
| `crew_members` | `crew_member` | `id`, `site_id`, `name`, `role`, `shift`, `on_shift`, `phone`, `email`, `contactable`, `certifications`, `owns`, `synthetic`, `generator`, `updated_at` | `certifications`, `owns` | `on_shift` (boolean), `contactable` (boolean), `synthetic` (boolean) |
| `obligations` | `obligation` | `id`, `site_id`, `asset_tag`, `title`, `rule_ref`, `frequency`, `last_done_at`, `due_at`, `status`, `document_id`, `owner_id`, `blocked_by`, `blocked_reason`, `regulation_ids`, `note`, `synthetic`, `generator`, `updated_at` | `regulation_ids` | `synthetic` (boolean) |
| `issues` | `issue` | `id`, `site_id`, `asset_tag`, `component_id`, `kind`, `severity`, `status`, `summary`, `ref_id`, `pin`, `at`, `updated_at`, `scenario_id`, `run_id`, `source`, `owner_id`, `assignee_id`, `obligation_id`, `document_id`, `evidence_frame_ids`, `synthetic` | `pin`, `evidence_frame_ids` | `synthetic` (boolean) |
| `conversations` | `conversation` | `id`, `kind`, `topic`, `convener`, `participants`, `site_ids`, `transport`, `provider_task_ids`, `a2a_task_ids`, `transcript`, `summary`, `summary_by`, `started_at`, `ended_at`, `status`, `issue_id`, `issue_kind`, `scenario_id`, `run_id`, `resolution`, `contact`, `synthetic` | `participants`, `site_ids`, `provider_task_ids`, `a2a_task_ids`, `transcript`, `summary`, `contact` | `synthetic` (boolean) |
| `viewer_commands` | `viewer_command` | `id`, `seq`, `site_id`, `action`, `asset_tag`, `issue_id`, `pin`, `issued_by`, `at` | `pin` | `seq` (int) |
| `memories` | `agent_memory` | `id`, `agent_id`, `container`, `kind`, `content`, `site_id`, `refs`, `at`, `synthetic`, `provider_status`, `provider_id` | `refs` | `synthetic` (boolean) |
| `telemetry` | `telemetry` | `id`, `at`, `agent_id`, `site_id`, `kind`, `tool`, `tokens`, `ms`, `ok`, `mission_id`, `scenario_id`, `run_id`, `source`, `synthetic`, `detail` | none | `tokens` (int), `ms` (int), `ok` (boolean), `synthetic` (boolean) |
| `findings` | `finding` | `id`, `site_id`, `asset_tag`, `component_id`, `status`, `score`, `threshold`, `model`, `frames`, `explanation`, `issue_id`, `source`, `synthetic`, `run_id`, `ingested_at` | `frames`, `explanation` | `score` (numeric), `threshold` (numeric), `synthetic` (boolean) |
| `notifications` | `notification` | `id`, `site_id`, `workflow_id`, `issue_id`, `sender`, `to_kind`, `to`, `to_name`, `channel`, `text`, `mode`, `notice_id`, `a2a_task_id`, `transport`, `synthetic`, `at` | none | `synthetic` (boolean) |
| `maintenance_windows` | `maintenance_window` | `id`, `site_ids`, `date`, `scope`, `examiner`, `status`, `conversation_id`, `approval_conversation_id`, `asset_tags`, `obligation_id`, `proposed_by`, `approved_by`, `scenario_id`, `synthetic`, `created_at`, `updated_at` | `site_ids`, `asset_tags` | `date` (date), `synthetic` (boolean) |
| `eye_frames` | `eye_frame` | `id`, `seq`, `site_id`, `command_id`, `action`, `params`, `actor`, `camera`, `visible_pins`, `index`, `renderer_id`, `size`, `sha256`, `url`, `at` | `params`, `camera`, `visible_pins` | `seq` (int), `index` (int), `size` (int) |

Tables from the reality layer (contract 1/2): `facts`, `attestations`, `work_items`, `dispatches`, `changes`, `subscriptions`. Contract 3 adds `crew_members`, `obligations`,
`issues`, `conversations` (replaces the contract-3 `board_meetings` table: board meetings are conversations of kind `meeting`),
`viewer_commands`, `memories`, `telemetry` and `findings`; contract 4 adds `notifications`, `maintenance_windows` and `eye_frames`.

Notes for the migration:

- `dispatches.to` and `notifications.to` are reserved words in SQL; declare them as `"to" text` (PostgREST handles the quoting). The same applies to
  `eye_frames.index` (`"index" int`).
- `changes.id` is `"{property_id}:{version}"` (for example `myer-plant:42`); `(property_id, version)` is unique and is the Realtime cursor.
- `value` on facts and attestations is `string | number | boolean`, so it must be `jsonb`.
- `crew_members.phone` / `email` carry only masked values (`••• ••• 4321`, `d•••@example.com`); real contact details never leave the backend.
- `telemetry` rows come from their own SQLite table (not the records table); `ok` and `synthetic` are booleans, `tokens` is an estimate.
- `conversations.site_ids` is a JSON array (a conversation can involve both factories); `summary` is `{headline, points, decisions, actions}` or null.
- `eye_frames` mirrors frame metadata only; the JPEG stays in the backend data directory (`GET /api/eye/frames/{id}.jpg`).
- `attestations.signed_payload` (text) is the exact canonical JSON the backend signed (sent only when the signature verifies locally),
  so Postgres can check the Ed25519 signature (supabase/migrations/0004_ledger.sql). Postgres adds `written_by`/`mirrored_at` to
  every table and `chain_seq`/`prev_hash`/`row_hash` to attestations itself; the backend never sends them. Phone numbers and email
  addresses in mirrored text (not in signed attestations) are masked before upsert.
- Internal fields that start with `_` are never emitted. Records not listed here (scenario runs, waits, agent configs, documents, notices,
  fix workflows, maintenance requests, eye commands and annotations) stay local in SQLite.
- Backfill: `backend/.venv/bin/python backend/scripts/supabase_sync.py` upserts every existing row of every table above in batches of 200.
- Migration from the contract-3 draft: drop `board_meetings` if it was created; `obligations.cites` became `regulation_ids` (jsonb) plus `note` (text).
