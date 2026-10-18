# Supabase for Steward

SQLite in the backend stays the source of truth. Supabase holds a mirror of it plus five features: authority in
Postgres (one Auth user per agent, RLS mirroring REALITY-CONTRACT-4.md §1), a tamper-proof attestation ledger, a live HUD
over Realtime Broadcast and Presence, an inbox that never sleeps (Edge Function + pgmq), and private Storage for eye
frames and evidence. Everything is guarded by the backend's budget guard (`backend/src/supa_budget.py`) so the project
stays well inside its plan, and nothing about the project is hardcoded: the URL, keys, ref and plan come from the root
`.env` (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_PROJECT_REF`, `SUPABASE_PLAN`) and `frontend/.env.local`
(`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`).

## Files

| File | Purpose |
| --- | --- |
| `migrations/0001_reality.sql` | **Superseded** by 0002–0007 (contract-1 shape: three sites, NOT NULLs and CHECKs the mirror no longer satisfies, anon reads on facts/attestations/changes). Kept for history; do not apply it. 0002 converges a database that ran it. |
| `migrations/0002_steward.sql` | Every table and column in `backend/SUPABASE-COLUMNS.md` (all nullable but `id`), `public.agents` (the 14 agents of contracts 4 and 5), indexes on `(property_id, version)` and the lookup keys, `written_by`/`mirrored_at` stamped from the caller's JWT, RLS on everywhere with no anon/authenticated privileges, Realtime publication for `changes`, `issues`, `notifications` only. |
| `migrations/0003_authority.sql` | The custom access token hook (`steward.custom_access_token_hook`), the authority matrix `steward.authority` and the RLS policies generated from it, anon SELECT on four non-sensitive tables, and `public.steward_authority_probe()` for the demo. |
| `migrations/0004_ledger.sql` | Append-only attestations (triggers + revoked privileges), the sha256 hash chain, signed-payload binding, trusted keys, Ed25519 verification with pgsodium, `public.verify_ledger()`. |
| `migrations/0005_realtime_hud.sql` | Realtime Authorization on `realtime.messages` for the private `site:<siteId>:hud` channels. |
| `migrations/0006_inbox_queue.sql` | pgmq queue `inkbox_inbound`, dedupe table, daily Edge Function counter and cap, service-only RPC wrappers, pg_cron retention. |
| `migrations/0007_storage.sql` | Private buckets `eye-frames` and `evidence`, a restrictive policy that keeps them closed to anon/authenticated, usage RPCs (`steward_db_size`, `steward_storage_usage`). |
| `functions/inkbox-inbox/` | The Edge Function (Deno): verify the Inkbox HMAC, dedupe, enqueue. `verify.ts` is shared with a Node test. |
| `config.toml` | Deliberately minimal: only the access token hook and the function's `verify_jwt = false`. `supabase config push` pushes only what the file declares. No project ref in it. |
| `tests/standin.sql` | A local stand-in for the Supabase objects the migrations touch; `backend/tests/test_supabase_sql.py` applies the migrations to a throwaway local Postgres with it. |
| `seed.sql` | Contract-1 era site rows for 0001's `properties` table; not used by 0002+. |

## Apply to a project

Every command takes the ref from the root `.env`; never put it in a file. The CLI must be logged in.

```sh
REF=$(grep '^SUPABASE_PROJECT_REF=' .env | cut -d= -f2)
for f in supabase/migrations/000{2,3,4,5,6,7}_*.sql; do supabase db query --linked --project-ref "$REF" -f "$f"; done   # each file is idempotent
backend/.venv/bin/python backend/scripts/supabase_agents.py            # 14 Auth users; passwords only into the root .env
supabase config push --project-ref "$REF"                              # enables the access token hook (diff first: supabase config diff)
backend/.venv/bin/python backend/scripts/supabase_agents.py --verify   # every agent signs in and carries agent_id/agent_level/site_id
# function secrets: the INKBOX_WEBHOOK_SIGNING_KEY* lines from .env, through a temporary 0600 file that is deleted afterwards
supabase secrets set --project-ref "$REF" --env-file /path/to/tmp-signing-keys.env
supabase functions deploy inkbox-inbox --project-ref "$REF" --no-verify-jwt --use-api
backend/.venv/bin/python backend/scripts/supabase_sync.py              # backfill within the caps
```

Recommended dashboard toggle (no CLI or config support): Realtime → Settings → turn off **Allow public access**, so only
private (authorised) channels exist on the project.

## Budget: plan, caps and how they are counted

`SUPABASE_PLAN=free|pro` selects the default caps (free is the shipped default). Any `SUPABASE_CAP_*` env value lowers a
cap; a value above 90 % of what the plan includes is clamped. `GET /api/supabase/usage` reports every counter against its
cap, the plan's included amount and the free limit. A refusal never raises: the caller falls back to local behaviour
and one `supabase.budget` event is recorded per cap per UTC day.

| Counter (env) | Free default | Pro default | Free includes | Pro includes | Counted as |
| --- | --- | --- | --- | --- | --- |
| `SUPABASE_CAP_REALTIME_MSGS_DAY` | 40,000 | 100,000 | 2,000,000 / month | 5,000,000 / month | a broadcast to N viewers = 1 + N (Supabase bills "one message sent plus one per subscribed client"); presence join 2 + N, leave N |
| `SUPABASE_CAP_REALTIME_MSGS_MONTH` | 1,000,000 | 3,000,000 | 2,000,000 | 5,000,000 | same |
| `SUPABASE_CAP_REALTIME_VIEWERS` | 20 | 50 | 200 concurrent | 500 concurrent | heartbeating viewers; more are told to keep polling |
| `SUPABASE_CAP_STORAGE_MB` | 600 | 5,120 | 1 GB | 100 GB | our objects; past 80 % the oldest eye frames leave the bucket (local copies kept) |
| `SUPABASE_CAP_UPLOAD_MB` | 5 | 10 | 50 MB / object | 500 GB / object | per object, checked before upload |
| `SUPABASE_CAP_EDGE_CALLS_DAY` | 5,000 | 20,000 | 500,000 / month | 2,000,000 / month | signed calls, counted in the database by `inkbox_enqueue`; past the cap the function answers 429 |
| `SUPABASE_CAP_DB_MB` | 300 | 2,048 | 500 MB | 8 GB | `pg_database_size` every 10 minutes; past 80 % simulated sensor rows stay local, at the cap every row does |
| `SUPABASE_CAP_EGRESS_MB_DAY` | 500 | 3,072 | 5 GB / month | 250 GB / month | bytes served: signed URLs minted (object size × expected viewers) and HUD payloads × viewers |
| `SUPABASE_CAP_EGRESS_MB_MONTH` | 4,000 | 90,000 | 5 GB | 250 GB | same |
| `SUPABASE_CAP_TRANSFORM_ORIGINS_MONTH` | 0 (not on free) | 80 | none | 100 origin images | distinct origin images transformed this month; then Pillow thumbnails |

Monthly active users stay at 14 (one Auth user per agent across myer-plant, bristol-pumps and tomioka-mill; tokens cached for their lifetime). Nothing here creates
projects, branches, replicas, compute add-ons, PITR or custom domains.

## 1. Schema (0002)

All tables and columns of `backend/SUPABASE-COLUMNS.md`, `id text primary key`, jsonb for nested values, timestamptz for
`*_at`, plus `agents (id, level, site_id, role, display_name, auth_user_id)`. Extra columns: `written_by` and
`mirrored_at` on every mirrored table (stamped by a trigger from the JWT: `myer-engineer`, `service_role`, ...), and
`signed_payload`, `chain_seq`, `prev_hash`, `row_hash` on attestations. Realtime publication: `changes`, `issues`,
`notifications` only; anon has no SELECT on them, so an anonymous subscriber receives none of their changes.

## 2. Authority in Postgres (0003)

One Auth user per agent, 14 in all (`agent+<id>@steward.invalid`, created by `backend/scripts/supabase_agents.py` with the secret key;
the passwords exist only in the root `.env` as `STEWARD_AGENT_PASSWORD_<SUFFIX>`). The access token hook adds
`agent_id`, `agent_level`, `site_id` and `agent_role` from `public.agents`. RLS reads `steward.agent_*()`, which look the
caller up by `auth.uid()` and require the `agent_id` claim to match, so a token can never claim another agent. Nothing lists
sites: a site exists for authority and for the HUD once its agents are in `public.agents` (contract 5's `tomioka-mill` needed only
four seed rows and four Auth users; the Director covers all three sites).

The matrix (`steward.authority`, mirrored by `backend/src/supa_authority.py` and kept identical by tests):

| Table | Writers (own site; operator and director both sites) | Bound to |
| --- | --- | --- |
| attestations | operator, engineer (append-only; must carry the backend-signed payload) | |
| facts | operator, engineer (must cite an attestation already in the ledger) | |
| work_items | operator, director, manager, engineer, technician | |
| dispatches | operator, engineer, technician | |
| obligations | compliance | |
| issues | operator, director, manager, engineer, compliance | |
| conversations | every agent (shared rows: a participating site) | convener |
| notifications | every agent | sender |
| telemetry, memories | every agent | agent_id |
| eye_frames | operator, director, manager, engineer | actor |
| viewer_commands | operator, director, manager, engineer, compliance | issued_by |
| findings | operator, director, manager, engineer | |
| maintenance_windows | operator, director, manager (shared rows: a participating site) | |
| crew_members, subscriptions | operator + manager / operator + engineer | |
| changes, agents | nobody but the service role | |

Reads are site-scoped the same way. Technicians can never insert attestations or facts; cross-site writes are refused.
anon may SELECT only `facts`, `eye_frames`, `findings` and `maintenance_windows` (no people, contact details,
transcripts, telemetry, memories or document text; documents and document emails never leave SQLite).
`POST /api/supabase/authority-check {agentId, table, action}` signs that agent in and calls
`public.steward_authority_probe()` as it (SECURITY INVOKER, always rolled back), returning Postgres's own answer, e.g.
`42501 new row violates row-level security policy for table "attestations"` for `myer-technician`.

## 3. Tamper-proof ledger (0004)

UPDATE, DELETE and TRUNCATE on `attestations` raise for every role (trigger) and are revoked from anon, authenticated and
service_role. A BEFORE INSERT trigger takes an advisory lock and sets `chain_seq`, `prev_hash` and
`row_hash = sha256(prev_hash || canonical row)`. When `signed_payload` is present it must match the row's columns, its key
must be in `steward.signing_keys` (the backend's key, registered by the setup script), and with pgsodium installed the
Ed25519 signature must verify (`pgsodium.crypto_sign_verify_detached`; verified working on the project). RLS requires
`signed_payload` from every agent, so a forged attestation is refused by the database itself. `public.verify_ledger()`
returns `ok` or the first broken link; `GET /api/supabase/ledger` verifies incrementally from a locally kept anchor
(`?full=true` for the whole chain) and reports if the anchored link moved.

## 4. Live HUD (0005)

Private channels `site:<siteId>:hud`. anon and authenticated may receive (Broadcast, Presence) and track presence on hud
topics of known sites; nobody may send Broadcast (no INSERT policy for it), so no browser can spoof a HUD event; the
backend sends through `POST /realtime/v1/api/broadcast` with the secret key. Events: `eye_frame` (signed Storage URL,
never bytes), `agent_action`, `conversation_line`, `issue_change`; at most one message per second per site, only while
viewers heartbeat (`POST /api/supabase/viewers`), slower past 50 % / 75 % of the day's budget, none at 100 %. Contact
details are masked in every line. Frontend: `frontend/src/lib/realtime` (`isRealtimeEnabled`, `useHudChannel`,
`useSitePresence`), which disconnects while the tab is hidden.

## 5. Inbox that never sleeps (0006 + functions/inkbox-inbox)

Unsigned requests are refused before the body is read (measured 0.10 ms inside the function); signatures are checked
against every `INKBOX_WEBHOOK_SIGNING_KEY*` function secret; duplicates (same envelope id) are absorbed; the exact request
is queued and the backend replays it every 5 s through `/api/inbound/inkbox` (which verifies the signature again), then
archives it. Archived bodies are deleted after 3 days. The webhook subscriptions still point at the tunnel until
`scripts/inkbox_use_supabase_inbox.py --apply` is run (dry run without `--apply`; `--revert --apply` goes back).

## 6. Storage (0007)

Buckets `eye-frames` (`<site>/<frameId>.jpg`, `<site>/thumbs/<frameId>.jpg`) and `evidence` (`<site>/<sha256><ext>`),
private, 10 MB server-side limit; the backend enforces the per-object cap first. Signed URLs live 15 minutes and are
reused for 10. `GET /api/eye/frames/{id}.jpg` answers a browser with a 307 to the signed URL when the frame is in Storage
and the egress budget allows (agents sending `X-Steward-Actor`, and `?local=1`, always get the local bytes); the feed adds
`signedUrl`, `thumbUrl` and `localUrl`. On Pro the thumbnail is an image transformation until 80 origin images a month.

## Verify

```sql
select tablename, rowsecurity from pg_tables where schemaname = 'public' order by 1;              -- RLS on everywhere
select table_name, privilege_type from information_schema.role_table_grants where table_schema = 'public' and grantee = 'anon';
select tablename from pg_publication_tables where pubname = 'supabase_realtime';                  -- changes, issues, notifications
select public.verify_ledger();                                                                     -- {"ok": true, ...}
select written_by, count(*) from public.attestations group by 1;                                   -- service_role (sensors) and engineers
select * from public.inkbox_inbox_stats();
select public.steward_db_size(), public.steward_storage_usage();
```

Anon refusals through PostgREST (publishable key): `GET /rest/v1/crew_members`, `telemetry`, `memories` answer
`401 permission denied`; `documents` and `document_emails` do not exist in Supabase (404).
