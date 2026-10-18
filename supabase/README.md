# Supabase for Steward

Supabase mirrors the backend's SQLite record so the dashboard can subscribe to changes in real time and so a judge can open the Supabase dashboard and see the signed rows land. SQLite stays the source of truth (REALITY-CONTRACT.md, "Supabase mirror"); every put of kinds `fact`, `attestation`, `work_item`, `dispatch`, `change`, `subscription` is upserted on `id` through PostgREST, asynchronously, never blocking a request.

Files here:

| File | Purpose |
| --- | --- |
| `migrations/0001_reality.sql` | Tables `properties`, `facts`, `attestations`, `work_items`, `dispatches`, `changes`, `subscriptions`; indexes; RLS; Realtime publication. Idempotent. |
| `seed.sql` | The three sites (`cedar`, `harbor`, `juniper`). Nothing signed is seeded. |

## 1. Create the project (3 minutes)

1. https://supabase.com/dashboard → **New project**. Any name (`steward`), any region near you, set a database password and keep it (only needed for `supabase db push`).
2. Wait for the project to finish provisioning (status "Active").

## 2. Apply the migration

**Option A, SQL editor (fastest, no CLI):**

1. Dashboard → **SQL Editor** → **New query**.
2. Paste the whole of `supabase/migrations/0001_reality.sql`, click **Run**. It ends with "Success. No rows returned".
3. New query, paste `supabase/seed.sql`, **Run**.

**Option B, Supabase CLI (`supabase db push`):** the CLI reads `supabase/migrations/` from the repo root, which is exactly where this file lives. From the docs (https://supabase.com/docs/guides/deployment/database-migrations): "`supabase login` … Sign in to the Supabase CLI using an auto-generated Personal Access Token", "`supabase link` … Link to your remote project by selecting from the on-screen prompt", "`supabase db push` … push your migrations to the remote database". Migration files are applied in timestamp order and named `<timestamp>_<description>.sql`.

```sh
npx supabase login
npx supabase link            # pick the project from the prompt; asks for the DB password
npx supabase db push         # applies supabase/migrations/0001_reality.sql
npx supabase db query --linked -f supabase/seed.sql   # if your CLI lacks `db query`, paste seed.sql in the SQL editor
```

If `db push` rejects the `0001_` prefix as not a timestamp, rename the file to `20261017000001_reality.sql` (content unchanged) and re-run. Do not commit that rename unless asked; the SQL-editor route needs no rename.

## 3. Keys → env vars

Dashboard → **Settings → API Keys** (https://supabase.com/dashboard/project/_/settings/api-keys/). Per the docs: "Every key lives there, legacy or not, and there is no separate Settings > API page." The project URL and publishable key are also in the **Connect** dialog.

| Env var | File | Which key | Why |
| --- | --- | --- | --- |
| `SUPABASE_URL` | `backend/.env` | Project URL, `https://<ref>.supabase.co` | PostgREST base for the mirror |
| `SUPABASE_SERVICE_KEY` | `backend/.env` | **Secret key** `sb_secret_…` (or the legacy `service_role` JWT) | Docs: "A secret key authorizes access through the `service_role` Postgres role, which has the `bypassrls` attribute." Backend only. Never in the frontend. |
| `NEXT_PUBLIC_SUPABASE_URL` | `frontend/.env.local` | same Project URL | Realtime subscription in the dashboard |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `frontend/.env.local` | **Publishable key** `sb_publishable_…` (or the legacy `anon` JWT) | Docs: "Safe to expose online: web page, mobile or desktop app…". Maps to the `anon` Postgres role, which the migration limits to `select` on `properties`, `facts`, `attestations`, `changes`. |

Restart `npm run dev` after editing `backend/.env`. The backend reports `supabase` as `connected` in `GET /api/integrations` only after one successful upsert.

## 4. Verify

SQL editor:

```sql
-- tables, RLS on, policies present
select tablename, rowsecurity from pg_tables where schemaname = 'public' order by 1;
select tablename, policyname, roles from pg_policies where schemaname = 'public' order by 1, 2;

-- realtime publication contains the three tables
select tablename from pg_publication_tables where pubname = 'supabase_realtime' order by 1;
-- expected: changes, facts, work_items

-- three sites
select id, name from public.properties order by id;

-- after the demo: latest facts for Harbor and the signed attestation behind each
select f.asset_tag, f.attribute, f.value, f.observed_at, a.verdict, a.verifier_version
from public.facts f join public.attestations a on a.id = f.attestation_id
where f.property_id = 'harbor' order by f.version desc limit 20;

-- the timeline the dashboard streams
select version, type, asset_tag, summary, at from public.changes where property_id = 'harbor' order by version desc limit 20;
```

Anon read check from a terminal (expects `[]` or rows, never 401):

```sh
curl -s "$NEXT_PUBLIC_SUPABASE_URL/rest/v1/facts?property_id=eq.harbor&select=asset_tag,attribute,value" \
  -H "apikey: $NEXT_PUBLIC_SUPABASE_ANON_KEY" -H "Authorization: Bearer $NEXT_PUBLIC_SUPABASE_ANON_KEY"
```

## 5. What the backend sends (for the backend stream)

PostgREST upsert on `id`, one row per put: `POST {SUPABASE_URL}/rest/v1/{table}` with headers `apikey: <service key>`, `Authorization: Bearer <service key>`, `Content-Type: application/json`, `Prefer: resolution=merge-duplicates,return=minimal`, body = JSON object (or array) whose keys are the snake_case column names in the migration. Nested objects (`source`, `checks`, `dispatches`, `verdicts`, `receipt`) and arrays (`evidence_hashes`) go in as JSON; they are `jsonb` columns. `value` is `jsonb` and accepts a string, number or boolean. `changes.id` has no counterpart in the contract type; use `"{property_id}:{version}"`. `dispatches."to"` is the contract's `to` (quoted because it is a reserved word; the JSON key is just `to`). Reconcile against `backend/SUPABASE-COLUMNS.md` when it exists; the migration was written from REALITY-CONTRACT.md types.

## 6. Realtime notes

The migration runs `alter publication supabase_realtime add table …` for `changes`, `work_items`, `facts` (guarded, so re-running is safe). Realtime `postgres_changes` applies RLS, so an anon subscriber receives `changes` and `facts` events but not `work_items` events (no anon policy; the dashboard reads work items via the backend API, by design). Docs caution: "RLS policies are not applied to `DELETE` statements". `changes` has `replica identity full` so UPDATE/DELETE events carry old values; the backend only inserts there.

Frontend subscription shape (from https://supabase.com/docs/guides/realtime/postgres-changes):

```js
supabase.channel('steward-changes')
  .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'changes', filter: 'property_id=eq.harbor' }, payload => { /* refetch /changes */ })
  .subscribe()
```

## What the judge sees

Dashboard → **Table Editor** → `attestations`: signed rows with `verdict`, `checks`, `signature`, `public_key`. **Database → Publications** → `supabase_realtime` lists `changes`, `facts`, `work_items`. **Logs → API** shows the backend's upserts arriving during the demo.
