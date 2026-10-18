# Supabase mirror: exact columns emitted by the backend

Source: `backend/src/mirror.py` (`row_for`). Every public (non-underscore) field of the record is emitted with its
name converted from camelCase to snake_case. Nested objects and arrays are sent as JSON and must be `jsonb`.
Upserts go to `POST {SUPABASE_URL}/rest/v1/{table}?on_conflict=id` with `Prefer: resolution=merge-duplicates,return=minimal`,
so every table needs `id text primary key`. Timestamps are ISO-8601 UTC strings (`timestamptz` works; `text` also works).
`value` on facts and attestations is `string | number | boolean`, so it must be `jsonb`, not `text`.

| table | columns (in emitted order) | jsonb columns |
| --- | --- | --- |
| `facts` | `id`, `property_id`, `asset_tag`, `component_id`, `attribute`, `attribute_class`, `value`, `unit`, `observed_at`, `ttl_seconds` (int, nullable), `expires_at` (nullable), `source`, `attestation_id`, `version` (int), `created_at` | `value`, `source` |
| `attestations` | `id`, `property_id`, `asset_tag`, `component_id`, `attribute`, `value`, `unit` (nullable), `observed_at`, `evidence_hashes`, `checks`, `verdict`, `source`, `verifier_version`, `signed_at`, `public_key`, `signature` | `value`, `evidence_hashes`, `checks`, `source` |
| `work_items` | `id`, `property_id`, `asset_tag`, `component_id`, `attribute`, `attribute_class`, `reference`, `state`, `requester`, `budget` (numeric), `deadline_at` (nullable), `dispatches`, `verdicts`, `fact_id` (nullable), `attestation_id` (nullable), `receipt` (nullable), `escalation_level` (int), `created_at`, `updated_at` | `dispatches`, `verdicts`, `receipt` |
| `dispatches` | `id`, `channel`, `to`, `reference`, `sent_at`, `provider_ref` (nullable), `body`, `work_item_id`, `property_id` | none |
| `changes` | `id`, `version` (int), `type`, `property_id`, `asset_tag` (nullable), `ref_id`, `summary`, `at` | none |
| `subscriptions` | `id`, `property_id`, `callback_url`, `requester`, `created_at` | none |

Notes for the migration:

- `dispatches.to` is a reserved word in SQL; declare it as `"to" text` (PostgREST handles the quoting on insert).
- `changes.id` is `"{property_id}:{version}"` (for example `harbor-works:42`); `(property_id, version)` is unique and is the Realtime cursor the dashboard uses.
- Internal fields that start with `_` (`_threadRef`, `_workItemId`, `_propertyId`) are never emitted.
- The row set is a strict superset of the TypeScript types in `REALITY-CONTRACT.md`: `work_items.escalation_level`,
  `dispatches.work_item_id` and `dispatches.property_id` are backend additions needed for a flat table.
- Extra columns are harmless; missing columns make PostgREST reject the whole upsert (`PGRST204`), which the
  backend records as a `mirror.failed` event and reports as `supabase: error` on `GET /api/integrations`.
- Backfill: `backend/.venv/bin/python backend/scripts/supabase_sync.py` upserts every existing row in batches of 200.
- Addendum 2 fields with no column are dropped before upsert: `simulated` (every kind), `owner_decision` (work items) and
  dispatch `note`. New change types `a2a` and `eval` fit the existing `type` text column; `assetTag` is omitted when absent.
