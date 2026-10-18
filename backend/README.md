# Steward local backend

Canonical application settings use `STEWARD_*`. Existing `PHY_*` environment variables remain backward-compatible aliases; an explicitly set `STEWARD_*` value takes precedence. The current database is `backend/data/steward.sqlite3`. On the first upgrade, the application snapshots the previous database with SQLite's backup API (including committed WAL data), keeps a recovery copy under `.migration-backups/`, and migrates display branding without changing record IDs, attachments, jobs or property names. Original seed PDF headers are updated; uploaded originals remain byte-for-byte unchanged.

Run `bash backend/run.sh` from the repository root. The backend binds to `127.0.0.1:8001`; the Next.js application proxies `/api/*`. No cloud deployment is required or performed. `/health` verifies SQLite access; `/docs` contains the interactive API documentation; `/mcp` is a stateless Streamable HTTP MCP JSON-RPC endpoint.

The first startup generates three original site workspaces (`myer-plant`, `bristol-pumps`, `tomioka-mill`), original PDF project specifications, a per-site asset register (24 assets at each plant, 25 at the mill) with four linked project checks per asset, and synthetic baseline evidence. A database created before the mill existed gains it once at startup (`seed.add_new_sites`, after a `pre-third-site-<stamp>` backup). These are demonstration project records, not actual building code, physical inspection, or official approval. Original fixture PDFs carry the same disclosure. Uploaded originals and source pages remain available.

The default property workers perform actual deterministic record checks: extract project source text, validate unique equipment tags and model bounds, match evidence to property/equipment/requirement, persist assessments, recompute readiness, create source-linked memory, and generate an escaped HTML/JSON report. They do not pretend to run model vision. The portfolio coordinator queues work in each site's separate context. Jobs, checkpoints, append-only events, user edits and files persist in `backend/data`; interrupted jobs resume after restart. There are no artificial progress delays.

Copy `.env.example` to `.env` to configure optional providers. Credentials stay server-side. `STEWARD_MODEL_PROVIDER=openai` uses an OpenAI-compatible chat gateway with `STEWARD_MODEL_BASE_URL`, `STEWARD_MODEL_API_KEY` and `STEWARD_MODEL_NAME`; `claude_cli` uses a previously authenticated local Claude CLI without granting file or shell tools. `eve` invokes the optional local model runtime using its configured provider keys. No provider is marked connected merely because an environment variable exists; failures produce an explicit local fallback and event.

`GET /api/integrations?propertyId=myer-plant` returns explicit action `capabilities` derived from current credentials, the selected property's identity, and configured action gates. The frontend uses these booleans rather than inferring permission from prose or a historical connection status. Capability availability means an action can be attempted, not that the provider has already verified the credentials.

## Evidence import

Evidence images and PDFs are preserved. Unstructured attachments remain pending without a model review. Machine-readable JSON records are checked for exact identifiers:

```json
{
  "propertyId": "myer-plant",
  "componentId": "pump-01",
  "tag": "P-101",
  "requirementId": "myer-plant-pump-01-cond",
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

## Reality layer

Agents ask the plant for a fact; the plant answers with a signed proof or sends someone to get it. Code lives in
`src/specs.py` (attribute table), `src/signing.py` (Ed25519), `src/verify.py` (six checks), `src/reality.py`
(resolver, dispatch, escalation, inbound routing, patrol, clearance, context.min), `src/mirror.py` (Supabase) and the
comms surface of `InkboxAdapter` in `src/providers.py`. Types and semantics follow `REALITY-CONTRACT.md`; known
departures are listed in `backend/DEVIATIONS.md`.

### Endpoints

| Method & path | Purpose |
| --- | --- |
| `POST /api/properties/{id}/resolve` | `{assetTag, attribute, maxAgeHours?, budget?, requester?, callbackUrl?}` → `ResolveResult` (`known`, `stale`, `unknown`, `conflict`). `budget > 0` opens a work item and dispatches. |
| `POST /api/properties/{id}/attest` | JSON or multipart (`file`) observation → `AttestResult` with the six checks. Only `accepted` writes a Fact. |
| `GET /api/attestations/{id}` | Signed attestation plus `valid` after signature re-verification. |
| `GET /api/attestations/public-key` | `{algorithm: "ed25519", publicKey, verifierVersion}`. |
| `GET /api/properties/{id}/facts?assetTag=&attribute=` | Latest fact per (tag, attribute) with `status` (`known`/`stale`). |
| `GET /api/properties/{id}/changes?since=&limit=` | `{version, changes, waiting}`; versions are monotonic per property. |
| `POST /api/properties/{id}/subscriptions` | `{callbackUrl, requester}`; every Change is POSTed as `{event: "steward.change", change, workItem?}` (5 s timeout, 3 retries, off the request path, attempts logged as events). |
| `GET /api/work-items/{id}` / `POST …/escalate` | Work item with dispatches, verdicts and receipt; `{level: 1-4, note?}` climbs the ladder. |
| `POST /api/properties/{id}/clearance` | `{from: [x, z], to: [x, z], widthM}` corridor test against component footprints on the floor plane. |
| `GET /api/properties/{id}/context.min` | `ContextMin`, kept under 1600 characters. |
| `GET /api/properties/{id}/specs` | The attribute table, TTLs and footprint radii. |
| `POST /api/properties/{id}/patrol` | Queues the inspection job and writes `identity` facts (source `patrol`, ref = job id) plus simulated sensor readings (source `sensor`, ref `sim:TS-801`). |
| `POST /api/properties/{id}/owner-decision` | `{workItemId, decision, note?}` writes an `owner_decision` condition fact (source `owner`) and resolves the item. |
| `POST /api/inbound/local` | Replay path and the dashboard's "reply as contractor" control (JSON or multipart). |
| `POST /api/inbound/inkbox` | Inkbox webhook receiver (see below). |

Errors from these endpoints are `{detail, code, recovery}`: `UNSUPPORTED_ATTRIBUTE` (400), `UNKNOWN_ASSET` (404),
`NOT_FOUND` (404), `WORK_ITEM_CLOSED` (409), `SCOPE` (409), `INVALID_CALLBACK`, `UNKNOWN_SCOPE`, `FILE_TOO_LARGE`,
`UNAUTHORIZED` (401).

### Verification checks (`steward-verify/1`)

All six must pass for `accepted`; any `rejected` wins, then any `needs_clarification`.

| check | rule |
| --- | --- |
| scope | property matches the register; with a work item its property and asset tag must match the submission. |
| identity | stated tag from JSON `statedTag`/`tag`, the message body (`\b[A-Z]{1,3}-\d{3,4}\b`) or the filename. None → `needs_clarification`; a different registered tag → `rejected` with "tag plate reads P-102, expected P-101, P-101 is 1.9 m west of P-102" (distance and direction from scene positions; +x east, −z north). |
| geometry | the stated tag's component is the expected `componentId`; same-kind siblings within 3 m are named in the reason. |
| plausibility | numeric value inside the spec range passes; outside → `needs_clarification` ("9.8 bar exceeds 3.5 bar spec; confirm with a second reading"); an enum value outside the set → `rejected`. |
| time | `observedAt` within `[workItem.createdAt − 5 min, now + 2 min]`. EXIF `DateTimeOriginal` from JPEG bytes (Pillow) wins, then the submitted `observedAt`, then the provider receipt time, then submission time; the reason says which. |
| integrity | SHA-256 of the file bytes (or the canonical JSON of the observation). The same hash already attached to a different work item → `rejected` "evidence reused from <id>". |

Attestations are Ed25519 signatures over the canonical JSON (sorted keys, no spaces, ASCII) of every field except
`signature`. The key is generated on first use at `<data dir>/signing.key` with mode 0600.

### Work items, references and dispatch

Reference format: `{SITE2}-{TAG without dash}-{ATTRIBUTE upper}-{seq:04d}`, with `MY`/`BR`/`TM` for myer-plant/bristol-pumps/tomioka-mill,
e.g. `MY-P101-PRESSURE_BAR-0042`. The task card is built from the scene: wall by the sign of z, the two nearest
neighbours by tag, the expected range from the spec table, and the reference on the last line. Channel selection:
`sms` only when `INKBOX_API_KEY`, the site's Field Technician identity, `STEWARD_ALLOW_EXTERNAL_MESSAGES=true` and an allowlisted
`INKBOX_CONTRACTOR_PHONE` matching `^\+?[0-9]{7,15}$` all exist; else `email` under the same rules with a valid
`INKBOX_CONTRACTOR_EMAIL`; otherwise `local` (card stored, item `waiting`, reply through `/api/inbound/local`) with the
failed condition in the dispatch `note` and the Change summary. Env values are read with inline comments stripped and
empty values treated as unset, so a template placeholder can never become a recipient. A send that cannot leave the machine is recorded
with `providerRef: null` and a body beginning `[not sent: <reason>]`; nothing is ever reported as delivered without a
provider receipt.

Escalation ladder: 1 re-send on the same thread, 2 email, 3 hosted voice call (`identity.place_call(mode="hosted_agent")`,
else a `call` dispatch with `providerRef: null`), 4 owner question by SMS to `INKBOX_OWNER_PHONE`. A scheduler thread
(every 30 s, only when workers are started) climbs the ladder at 50/70/85/95 % of the deadline window
(`STEWARD_WORK_DEADLINE_SECONDS`, default 7200) and marks past-deadline items `expired` with a Change. Receipts carry
`waitedSeconds`, `tokensWhileWaiting: 0`, `estimatedPollingTokens = ceil(waited/30) × 350`, `dispatches` and `cost: 0`.

### Inkbox identities and inbound routing

Contract 4: every agent has its own identity, `INKBOX_IDENTITY_<SUFFIX>` with an identity-scoped key
`INKBOX_AGENT_KEY_<SUFFIX>` (suffixes `DIRECTOR`, `MYER_MANAGER`, `MYER_ENGINEER`, `MYER_COMPLIANCE`, `MYER_TECHNICIAN`, `BRISTOL_*`, `TOMIOKA_*`).
The site identity that emails work-item task cards is the site's Field Technician; the shared `INKBOX_IDENTITY` is the
fallback. The single phone number is the shared "Steward Dispatch Line" (`INKBOX_IDENTITY_DISPATCH`, number
`STEWARD_DISPATCH_PHONE_NUMBER`; the legacy `INKBOX_PHONE_IDENTITY` is still read): SMS, iMessage and voice for both sites go
through it and the task card names the site. Inbound messages are scoped to the site whose team identity received them. The
retired identities (`steward-atlas`, `steward-warden-*`, `steward-counsel`) and their env names are never read. Every
outbound send still requires `STEWARD_ALLOW_EXTERNAL_MESSAGES=true` and the recipient in `INKBOX_ALLOWED_RECIPIENTS`.

Inbound is webhook subscriptions, not polling. `backend/scripts/inkbox_subscribe.py <site>` creates a subscription for
`text.received`, `message.received`, `imessage.received`, `call.ended` and the four `a2a.*` task events pointing at
`{STEWARD_PUBLIC_BASE_URL}/api/inbound/inkbox` with `auth_token = STEWARD_INBOUND_SECRET`. The receiver accepts the
secret as `X-Steward-Inbound-Secret` or `Authorization: Bearer …` (Inkbox cannot set custom headers), verifies
`X-Inkbox-Signature` (HMAC-SHA256 over `request_id.timestamp.body`) when `INKBOX_WEBHOOK_SIGNING_KEY` is set, and
deduplicates at-least-once deliveries with `store.mark_once` on the envelope `id`. Routing order for every inbound
message: by thread/provider reference (`conversation_id`, mail `thread_id`, call id) → by work-item reference in the
subject or body (the `HW`/`MY`/`BR` prefix disambiguates sites on a shared identity) → by sender among open items,
scoped to the site whose identity received the message when `data.agent_identities` names it. Unrouted messages are
stored under `inbound_unrouted` and announced as a Change. The reply with the verdict goes back on the same thread (or
is stored as a `local` dispatch).

### Local replay

Without Inkbox the whole loop runs locally: `resolve` with a budget stores the task card as a `local` dispatch; a
contractor reply is `POST /api/inbound/local` with `{reference, body, statedTag?, value?, observedAt?}` or multipart with
a `file`. The reference can also sit in the body ("Re: MY-P101-PRESSURE_BAR-0001 …") and the tag in the filename
(`IMG_P-101_gauge.jpg`). A wrong tag is rejected with the direction to the right asset; the correct one writes the fact,
signs the attestation, resolves the item and fires subscriptions. Seeded demo facts (myer-plant, the demo site: `P-101.commissioning_certificate`,
`V-501.position`, `TS-801/802.temperature_c`, `DB-401.status`, `FE-1001.pressure_ok`, `D-1101.closed`; identity serials
everywhere) are written once and survive restarts; seeded demo observations past their TTL are re-seeded on startup
(`seed:patrol-refresh`) only while nothing but seeds was ever written for that attribute, so the one-unknown demo mission
(`P-101.pressure_bar`) stays reproducible.

### Supabase mirror

With `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` set, every put of a mirrored kind (`backend/SUPABASE-COLUMNS.md`) is queued
and upserted through PostgREST by one background thread that batches what is pending (the latest version of a row wins;
attestations use `ignore-duplicates`, the ledger is append-only); failures become `mirror.failed` events and
`GET /api/integrations` reports `supabase` as `connected` only after one successful upsert. Phone numbers and email
addresses in mirrored text are masked; signed attestations go byte-exact with the canonical JSON the backend signed
(`signed_payload`). `backend/scripts/supabase_sync.py` backfills existing rows (and uploads stored eye frames and
evidence) within the caps. Schema, policies and setup: `supabase/README.md`.

## Supabase: budget guard, authority, ledger, live HUD, inbox, storage

All of it is off unless `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are set; the project ref, URL, keys and plan come only
from env (`SUPABASE_PROJECT_REF`, `SUPABASE_PLAN=free|pro`). Code: `src/supa_budget.py`, `src/supa_client.py`,
`src/supa_auth.py`, `src/supa_authority.py`, `src/supa_realtime.py`, `src/supa_storage.py`, `src/supa_inbox.py`,
`src/supa_services.py`, `src/supa_routes.py` (installed by two lines in `main.create_app`). The Storage, HUD, inbox and
usage threads start only when workers run.

- **Budget guard** (`src/supa_budget.py`). Every Supabase write path asks it first; counters persist in SQLite `meta`
  (`supa:budget:*`); a refusal falls back to local behaviour and records one `supabase.budget` event per cap per day.
  Free defaults: 40,000 Realtime messages a day and 1,000,000 a month, 20 viewers, 600 MB storage, 5 MB per object,
  5,000 Edge Function calls a day, 300 MB database, 500 MB egress a day and 4,000 MB a month, no image transformations.
  `SUPABASE_PLAN=pro`: 100,000 / 3,000,000 messages, 50 viewers, 5,120 MB storage, 10 MB per object, 20,000 calls a day,
  2,048 MB database, 3,072 MB egress a day and 90,000 MB a month, 80 transformation origin images a month. Env
  (`SUPABASE_CAP_*`) lowers a cap; above 90 % of the plan it is clamped. Realtime is counted the way Supabase bills it:
  a broadcast to N viewers costs 1 + N. `GET /api/supabase/usage` reports every counter against its cap and limits.
- **Authority** (`src/supa_authority.py`, migration 0003). Each of the 14 agents (contract 5 adds the `tomioka-*` team) has a
  Supabase Auth user; rows an agent originated
  are written with that agent's own access token (password grant, cached until a minute before expiry, refreshed, backed
  off after a failure), so RLS decides; a refusal is recorded (`mirror.refused`), never retried with the secret key.
  System rows (sensor feed, patrols, seeds, the change feed, crew) use the secret key. Without agent passwords and the
  publishable key everything uses the secret key. `POST /api/supabase/authority-check {agentId, table, action, siteId?}`
  returns Postgres's own answer to that agent's write (always rolled back).
- **Ledger** (migration 0004). Attestations are append-only for every role, hash-chained and Ed25519-checked in Postgres
  with pgsodium. `GET /api/supabase/ledger` runs `verify_ledger()` incrementally from a local anchor (`?full=true`).
- **Live HUD** (`src/supa_realtime.py`, migration 0005). `POST /api/supabase/viewers {siteId, viewerId, role?, leave?}`
  heartbeats (10 s, stale after 30 s). Eye frames, agent actions (telemetry), conversation lines and issue changes are
  coalesced to at most one Broadcast per second per site, only while a viewer is present, slower as the day's budget is
  spent. Frontend module: `frontend/src/lib/realtime`.
- **Inbox** (`src/supa_inbox.py`, migration 0006, Edge Function `inkbox-inbox`). Every 5 s the drainer reads the pgmq
  queue, replays each webhook through `POST /api/inbound/inkbox` in process (signature verified again) and archives it;
  five failed reads archive it as poison with an event.
- **Storage** (`src/supa_storage.py`, migration 0007). Eye frames and their 320 px Pillow thumbnails, and evidence files,
  go to private buckets after the guard approves; past 80 % of the storage cap the oldest eye frames leave the bucket
  (local copies stay). `GET /api/eye/frames/{id}.jpg` answers browsers with a 307 to a 15-minute signed URL when the
  frame is uploaded (agents with `X-Steward-Actor` and `?local=1` get the bytes); the feed adds `signedUrl`/`thumbUrl`;
  `GET /api/supabase/evidence/{sha256}` redirects to a signed evidence URL.

## Sites and environments (contract 3)

Site == property: the API keeps `/api/properties/{id}` and `propertyId`. Three sites (`src/sites.py`): `myer-plant` (MY,
the demo site, SuperSplat scene `66b655d3`, "industrial plant room within Kenneth Myer building" by azha007), `bristol-pumps`
(BR, "Bristol Dock Pump House", scene `8a8ce192`, "1907 pumps being restored" by scanomatic_labs) and, from contract 5,
`tomioka-mill` (TM, the Tomioka Silk Mill, 富岡製糸場, Gunma, Japan; UNESCO World Heritage, buildings designated National
Treasures; open to visitors; run here by a fictional demonstration operator; jurisdiction `JP`; scene `849bce2a`
"富岡製糸場" by acrylagitt). All are third-party Gaussian-splat captures loaded at runtime from the CloudFront origin, never
copied. Myer and Bristol are single SOG files (`environment.sogMetaUrl`, `format`/`scanFormat: "sog"`); the mill streams by
level of detail (`lod-meta.json`, LOD v1, 23,564,860 gaussians over 5 levels in 44 chunk files): its `sogMetaUrl`, `sogUrl`,
`lodMetaUrl` and `contentUrl` all carry that URL with `format`/`scanFormat: "lod"` and an `environment.lod` summary.
`environment` also carries `viewerUrl`, `embedUrl`, `thumbnailUrl`, `credit`, `captureNote`, the gaussian count and camera
presets (the mill: position [-32.414, 0.287, -43.351], target [-33.558, 0.001, -44.495], fov 75). Property records carry
`jurisdiction` (`VIC-AU`, `ENG-UK`, `JP`), `prefix` and `siteKind`. `GET /api/properties/{id}/scene` adds `sogUrl`, `contentUrl`,
`scanFormat` and each asset's `viewPose`.

The mill's register (`src/registers.py`, contract 5 §3, 25 tags: the contract's table lists 25 under a "24" heading) is a section
of the 1872 Silk Reeling Mill: six preserved automatic reeling machine rows RM-101..106 (`machine`), king-post roof trusses
TR-201..204 and the east brick wall BW-251, National Treasure fabric (`structure`), humidity and temperature sensors HS-301..303
and the seismic sensor VS-401 (kind `sensor` with `specKind` `sensor:humidity` / `sensor:seismic`), extinguishers FE-501..503,
the indoor hydrant FH-601 (`hydrant`), visitor exits D-701/702, the walkway W-801, the panel EP-901, the CCTV camera CC-1001
(`camera`) and the mobile dehumidifier DH-1101 (`dehumidifier`). New spec kinds: machine `vibration_mms` 0-4.5 and `status`
running/stopped/fault; structure `crack_width_mm` 0-0.3 and `condition` sound/watch/defect; `sensor:humidity` `humidity_pct`
40-65 and `temperature_c` 5-30; `sensor:seismic` `seismic_gal` 0-80; hydrant `pressure_ok`; camera `working`; dehumidifier
`running`. Its estimated pins sit inside the capture's occupied volume around the initial camera target (read from the LOD
octree), `pinSource: estimated`, until the PINS stream places them.

`harbor-works` and its Three.js fixture twin were retired: `retire_sites` (startup, once, after a SQLite backup
`pre-two-sites-<stamp>.sqlite3`) moves every record of that site to kind `archived:<kind>` under property
`archived:harbor-works`, plus its events and meta counters; bodies (and signatures) are unchanged and nothing reads them again.
Databases with the first-generation IDs (`cedar`/`harbor`/`juniper`) are still renamed first by `migrate_site_ids`.

Each site has its own 24-asset register (`src/registers.py`): Myer is a modern plant room (circulation pumps, handwheel
isolation valves, gauges incl. PG-601 on the 3.5 bar primary circuit, expansion and buffer vessels, exchangers, panels); Bristol
is a 1907 pump house (steam pumping engines SP-101/SP-102, drainage pumps, sump SU-201, steam receiver pressure vessel PV-301,
valves, gauges, egress door D-1101, visitor walkway W-1201). New kinds: `sump` (`level_pct` 0-85 %), `vessel` (`pressure_bar`,
`inspection_certificate`, `serial`), `walkway` (`clear`). `position` stays the register layout in metres (geometry checks, task
cards, clearance); `pin: {x, y, z}` is a point in the scan's world coordinates with `pinSource: placed | estimated`. Seeded
pins are estimated (a scaled copy of the layout within a few metres of the scan origin) and every component, issue, viewer
command, scene asset and vision finding says so. `sync_registers` (once, `steward_register_version=3`) moves existing databases
onto these registers: unchanged IDs are updated in place (a placed pin survives), assets that left the register are archived
with their checks, evidence, facts and work items, and the seed PDFs are regenerated only when a register changed.

- `PUT /api/properties/{id}/assets/{assetTag}/pin {x, y, z, source: placed | estimated}` (Owner's agent; `estimated` resets).
- `GET /api/properties/{id}/scene`: environment, SOG URL, credit, camera presets, every asset with its pin, pin source and open issues.
- `POST /api/properties/{id}/viewer {action: focus | orbit | reset | highlight, assetTag?, issueId?}` appends a viewer command
  (per-site `seq`, the asset's pin); `GET /api/properties/{id}/viewer?since=` returns the commands after a sequence.
- `GET /api/properties/{id}/issues?status=open|resolved|all`: computed issues plus stored ones (scenarios, vision, agents) with
  `assetTag`, `severity`, `scenarioId`, `synthetic`, `pinSource`. A computed `out_of_range` is hidden when a stored open issue covers the
  same asset; expired work items yield one `overdue` issue per asset attribute (latest, last 24 h, not superseded).
  `GET /api/issues/{id}` is the issue page: what is wrong, why (regulations), who is responsible, fix status.
  `POST /api/issues/{id}/assign {crewMemberId}` (manager or Owner's agent).
  `POST /api/issues/{id}/decide {question, options, actor?}` (alias `/decision-request`; the MCP `decide` fallback for clients without
  elicitation) sends the question to the site's Plant Manager as an A2A one-question conversation plus a notification, and to the owner
  by SMS through the dispatch line in live mode only (otherwise recorded `dry_run`); cross-site askers go through the director.
  `POST /api/decision-requests/{id}/answer {answer}` (Owner's agent, owner or that manager) closes it.

## Agents and authority (contract 4)

| level | id | name | scope |
| --- | --- | --- | --- |
| 1 | `operator` | Owner's agent | the customer's agent over MCP, all sites |
| 2 | `director` | Operations Director | all three sites |
| 3 | `myer-manager`, `bristol-manager`, `tomioka-manager` | Plant Manager · Myer / Bristol, Site Manager · Tomioka | own site |
| 4 | `myer-engineer`, `bristol-engineer`, `tomioka-engineer` | Site Engineer · Myer / Bristol, Conservation Engineer · Tomioka | own site |
| 4 | `myer-compliance`, `bristol-compliance`, `tomioka-compliance` | Compliance Officer · Myer / Bristol / Tomioka | own site |
| 5 | `myer-technician`, `bristol-technician`, `tomioka-technician` | Field Technician · Myer / Bristol / Tomioka | own site |

`GET /api/agents` lists them (plus the `dispatch` line entry, `actor: false`) with level, role, handle, email, status,
current task, why, waiting on, authority and transport. `src/agents.py` enforces the authority table: the Owner's agent reads
everything, starts scenarios and fix workflows, decides and sets budgets (and keeps the single-agent reality verbs, see
DEVIATIONS); the director works on all three sites, delegates to managers, reads metrics and telemetry, reconfigures agents and
approves cross-site maintenance; managers convene calls, assign crew, approve work orders (`STEWARD_WORK_ORDER_LIMIT_USD`) and
schedule maintenance; engineers drive the agent eye, run valve inspections, resolve, attest, verify and open issues; compliance
officers own obligations, regulations, documents and notices and email documents to any agent; technicians contact people
through the dispatch line and email and collect evidence but never attest. Team roles act only for their own site. The A2A bus
enforces the cross-site rule: manager↔manager, compliance↔compliance and anyone↔director only.

Stored records written with the old ids are migrated once (`steward_agent_ids_version=4`, backup `pre-agent-ids-<stamp>`):
`atlas`→`director`, `warden:<site>`→`<site>-engineer`, `counsel`→`<site>-compliance` (site-less→`bristol-compliance`),
`runner`→`<site>-technician` (site-less→`myer-technician`), in every agent-id field (callers, targets, A2A parts, steps,
requesters, memories, configs, events, telemetry); free text keeps its wording. Old ids sent as actors are refused as retired.

Runtime settings: `GET /api/agents/{id}/config`, `POST /api/agents/{id}/config` (Owner's agent or director) and
`POST /api/agents/{id}/reconfigure {change, reason}` (director only): `documentCache`, `pollStrategy: poll | subscribe`,
`pollIntervalSeconds`, `maxTokensPerMission`, `phrasing`; every change is versioned with who and why, a Change of type
`agent_config`, a decision transcript entry and a memory.

## A2A

`src/a2a.py` is one bus with two transports. Every task is kind `a2a_task` `{id, contextId, caller, target, state:
submitted | working | input_required | completed | failed | canceled, messages: [{role: caller | agent, parts, at,
intent?}], transport: local | inkbox, providerTaskId?, providerContextId?, siteId, steward, simulated?, createdAt,
updatedAt}`; every message emits a Change of type `a2a`. Parts are a text part a human can read plus
`{data: {steward: {missionId, siteId, assetTag?, attribute?, workItemId?, attestationId?, budget?, from, to, messageId}}}`.
`GET /api/a2a/tasks?siteId=&missionId=&agent=` and `GET /api/a2a/tasks/{id}` expose them.

- `local`: in-process delivery to the registered handler per role (director, manager, engineer, technician in `src/missions.py`,
  compliance in `src/scenarios.py`), persisted
  identically. Used whenever `INKBOX_API_KEY` or either handle is missing, and always for the Operator.
- `inkbox` (Inkbox A2A 1.0): the caller's identity-scoped key (`INKBOX_AGENT_KEY_ATLAS`, `INKBOX_AGENT_KEY_RUNNER`,
  `INKBOX_AGENT_KEY_WARDEN_<SITE>`) opens `identity.a2a_client()`, fetches the target's Agent Card (the sender's own
  `a2a_settings().card_url` with the handle swapped, or `INKBOX_A2A_CARD_URL_<HANDLE>`) and calls
  `client.send(card, parts=[...], message_id=<task id>, context_id?, task_id?)`, which is the documented JSON-RPC
  `SendMessage` with `A2A-Version: 1.0` and `X-API-Key`. The worker replies with `identity.a2a_reply(task_id, intent=
  progress | ask_caller | complete | fail, parts=[...])`. Because both ends of every task run in this process, a task sent
  over Inkbox is also delivered in-process at once; the webhook echoes (`a2a.task.created`, `a2a.task.message`,
  `a2a.task.canceled`, `a2a.sent_task.updated` on `/api/inbound/inkbox`) are deduplicated by provider task and message
  id, and tasks created by external callers are delivered to the addressed agent (`steward.to`, else by role). A provider
  context id is reused only between the same caller/worker pair (Inkbox rejects it otherwise). A failed provider call
  never pretends: the task is stored with `transport: "local"` and a bounded `providerError`, plus an `a2a.inkbox_failed`
  event. At startup (workers only) a daemon thread recovers submitted tasks; it re-sets Agent Card skills with `a2a_set_skills` only
  when `STEWARD_A2A_SET_SKILLS=true` (contract 4: the role skills are already on the cards; role skills per kind in `SKILLS`, e.g. engineer `resolve-fact`, technician `dispatch-technician`,
  `collect-evidence`) and recovers `a2a_tasks(state="submitted")`; failures are `a2a.startup_failed` events and never
  stop the server.

## Missions

`POST /api/missions {siteId, goal: "clear_for_restart", budget, requester, assetTags?}` (actor `operator`) → `Mission
{id, siteId, goal, budget, requester, state: running | input_required | completed | failed, steps: MissionStep[], contextId,
checklist, items, tasks, createdAt, updatedAt}`; `GET /api/missions/{id}`, `GET /api/missions?siteId=`. The restart set per
asset kind is `pump.commissioning_certificate`, `pump.pressure_bar`, `valve.position`, `panel.status`,
`fire.pressure_ok`, `door.closed`. By default the mission covers one representative asset per kind (register order:
P-101, V-501, DB-401, FE-1001, D-1101, six attributes); `assetTags` narrows it to named assets and `["all"]` covers every
asset of those kinds (15 attributes). On the seeded demo site exactly one attribute is unknown, `P-101.pressure_bar`.

The director runs the five steps in `src/missions.py` as a checkpointed job (contract 4: director → plant manager, who approves the
work order within the site limit → site engineer → field technician; the manager relays the engineer's reports up) (the record is rewritten after every reply, so a
restart resumes from `items`/`tasks`; `MissionEngine.recover` re-reads the work items and advances). In the step list below Atlas is
the director, the Warden the site engineer and Runner the site's field technician: (1) Atlas → Warden
task "resolve the restart set"; (2) the Warden resolves each attribute with budget 0, reports known ones with their
attestation IDs (`progress`) and opens a Warden → Runner task "collect <attribute> for <tag>" for the rest; the Runner
dispatches through the existing path (`resolve` with the budget, requester `runner/mission:<id>`) and reports the
reference and channel; (3) evidence arriving on `/api/inbound/local` or `/api/inbound/inkbox` for a mission work item
is verified on the inbound path (`steward-verify/1`, the same verifier the Warden signs with), the Runner replies
`complete` with the attestation ID or `progress` with the rejection reason, and the Warden records the verdict and keeps
waiting; the chain continues with no extra call; (4) Atlas `check`s every attestation (signature and spec range); an
out-of-range value opens cross-site tasks to the other Wardens, escalates a work item to level 4 (one owner question)
and marks the mission `input_required`; the owner's decision on `/owner-decision` resumes it; (5) Atlas replies to the
Operator's task with `complete` and the checklist `[{assetTag, attribute, value, attestationId, valid, ownerDecision?}]`,
or `fail` with what is missing (an expired work item fails the mission). Warden and Runner texts are templates; with
`STEWARD_AGENT_PHRASING=true` and a configured model they are rephrased, the template staying in the data part.

## Transcripts

`GET /api/agents/{agentId}/transcript?since=0&limit=200` → `TranscriptEntry[] {id, agentId, at, kind: a2a | sms |
email | imessage | call | mcp | decision | system, direction: in | out, counterpart, text, parts?, audioUrl?, refs:
{missionId?, taskId?, workItemId?, attestationId?}, simulated?}` assembled in `src/transcripts.py` from stored records
only: A2A messages for the agents on the task (`[intent] text`), dispatches (`sms`/`email`/`imessage`/`call`, out) and
inbound replies (`inbound_message` records, in) for the site's Field Technician, owner decisions (`decision`) for the director, Owner's-agent
endpoint calls (`mcp`) and mission steps (`system`). Call entries carry the Inkbox transcript lines as text, the
`transcript_url`, and `audioUrl` when the provider reported a recording URL. `since` is an offset into the
chronological list.

## Simulation

`src/simulate.py` runs as a daemon thread only with workers and `STEWARD_SIMULATION=true` (default; tests set it
false): every 20 s a sensor reading for each sensor-kind asset on every site (source `sensor`, ref `sim:<tag>`), every
2 min one plausible event on a non-demo site in rotation: a reading drifting out of range (an `out_of_range` issue), a
patrol identity fact (`sim:patrol`), a short director → site engineer A2A status task that completes by itself, an expired work
item (local card, `simulated`, nobody contacted). Every simulated fact, attestation, change, work item, dispatch and
task carries `simulated: true`; the demo site `myer-plant` gets only sensor readings. `GET /api/simulation` → `{enabled, running,
counts, …}`; `POST /api/simulation {enabled}` (actor `operator`) toggles it and persists the choice.

## Evals

`POST /api/evals/run {suite: "demo-workflow", mcpUrl?, backendUrl?}` (actor `operator`, 202) spawns
`agent-runtime/node_modules/node/bin/node evals/run.mjs --json --mcp <STEWARD_MCP_URL, default
http://127.0.0.1:8002/mcp> --backend <STEWARD_SELF_URL, default http://127.0.0.1:<BACKEND_PORT>> --workflow
evals/demo-workflow.json` from the repository root and stores kind `eval_run` `{id, suite, startedAt, finishedAt,
passed, failed, steps: [{name, target, result: PASS | FAIL, ms, detail}], state, error?}`, emitting a Change of type
`eval` on the demo site. `GET /api/evals` (newest first), `GET /api/evals/{id}`. Local only: non-loopback MCP or
backend URLs are refused with `NOT_LOOPBACK`. `STEWARD_EVAL_RUNNER` replaces the command (tests use it). Armature runs
are linked by URL only (see `armature/README.md`). Run the replayable suites by hand with
`agent-runtime/node_modules/node/bin/node evals/run.mjs --mcp http://127.0.0.1:8002/mcp --backend http://127.0.0.1:8001
[--workflow evals/mission-workflow.json]`; the demo suite expects no open `P-101.pressure_bar` work item, so run it before
the mission suite on a given database.

## People and compliance (contract 3 §6, contract 4 §5)

`src/people.py`. Crew per site (`GET /api/properties/{id}/crew`): role, shift, `onShift`, certifications with expiry status and
the issue kinds each person owns. The duty engineer on both sites is the user: contact comes from `INKBOX_CONTRACTOR_PHONE` /
`INKBOX_CONTRACTOR_EMAIL` at send time and is only ever shown masked; everyone else is synthetic with no contact details.
`GET /api/properties/{id}/responsible?issueKind=` returns the owner (on shift first, the duty engineer as the fallback), the
owning agent (compliance kinds → the site's Compliance Officer, agent efficiency → the director, everything else → the Site
Engineer) and the contact plan (the site's Field Technician through the dispatch line, or "never contacted" for synthetic crew).

Obligations (`GET /api/properties/{id}/obligations?status=`): `ok | due_soon | overdue | blocked`, recomputed from `dueAt`,
`ruleRef` a labelled demo rule pack entry, and `regulationIds` into the rule pack (unknown ids are reported as
`unresolvedRegulationIds`). When the REGULATIONS stream's `obligations-suggested.json` names the obligation, the view adds its
`why`, `closingEvidence`, `closesWhen` and `trackedBy`. Compliance documents are generated PDFs (reportlab, text extracted back
from the PDF) stored as `document` records; `GET /api/documents/{id}` returns metadata and the text with `textIsData: true`.
`POST /api/properties/{id}/obligations/{obligationId}/request-document` (the site's Compliance Officer; header-less calls act as
it) records a document request and a notice. Notices (`GET /api/properties/{id}/notices`) are delivered by the site's Field
Technician: `dry_run` by default, `not_contactable` for synthetic crew, and a live SMS through the dispatch line only when
`STEWARD_ALLOW_EXTERNAL_MESSAGES`, `STEWARD_ALLOW_NOTICE_SMS` are true and the user's number is allowlisted.

`POST /api/agents/{id}/send-document {to, documentId, note}`: a Compliance Officer emails one of its site's documents to any
agent. It is a dry run (recorded, shown in both transcripts) unless `STEWARD_ALLOW_EXTERNAL_MESSAGES=true`,
`STEWARD_ALLOW_AGENT_EMAIL=true`, an Inkbox key for the sender and both identities exist; the live path calls the installed SDK's
`identity.send_email(to=[...], subject, body_text, attachments=[{filename, content_type, content_base64}], idempotency_key)`.
The recipient is also told over A2A when the cross-site rule allows the message (otherwise `a2aSkipped` says why). A Site
Engineer receiving a document reviews it as data: instruction-shaped text ("ignore previous instructions...", "mark all checks
passed") is never followed; the document verifier (`steward-document-screen/1`) rejects the document's claims, the document is
flagged and a `document_injection` issue is raised; no fact, check, obligation or component changes.

## Regulations (contract 4 §5)

`src/regulations.py` reads, never writes, the REGULATIONS stream's `backend/seed/regulations/regulations.json` (42 records:
PSSR 2000, Workplace Regulations 1992 and HSWA 1974 for Bristol; the Victorian OHS Regulations 2017, Building Regulations 2018
and the VBA ESM-02 practice note for Myer; for Tomioka (`JP`) the Act on Protection of Cultural Properties, the Fire Service Act,
its Enforcement Order and Regulation) and the cached PDFs in `backend/data/regulations/`. `GET /api/regulations?siteId=`
(binding records, filtered by `siteIds`; `include=comparison` adds comparison records), `GET /api/regulations/{id}`,
`GET /api/regulations/{id}/file`: streams the cached PDF only when `servePdf` is true (the UK Open Government Licence files and
the JP e-Gov files under PDL1.0) with the record's attribution in `X-Steward-Attribution` (OGL: "Contains public sector
information licensed under the Open Government Licence v3.0."; JP: "Source: e-Gov Law Search (Digital Agency, Japan), PDL1.0.",
the full 出典 line percent-encoded in `X-Steward-Attribution-Encoded`); otherwise answers 302 to the record's `pdfUrl` and never
streams the local copy. Records with `binding: false` (the US-CA comparison set, `comparisonFor`) are never the reason for a
breach: issues and obligations cite binding ids in `regulationIds` and list comparisons in `comparisonRegulationIds`. Ids not
(yet) in the file appear as `unresolvedRegulationIds` with `regulationPending: true`. Views carry `readUrl` with `#page=<pageHint>`. Compliance issues cite their obligation's regulations, or the records whose
`appliesTo` names the issue kind or scenario at that site. `STEWARD_REGULATIONS_FILE` overrides the path (tests). Demo rule
pack, not legal advice.

## Scenarios, conversations and maintenance (contract 3 §5, contract 4 §4 and §7)

`GET /api/scenarios`, `GET /api/scenarios/{id}`, `POST /api/scenarios/{id}/start {speed?, restart?}` (Owner's agent),
`GET /api/scenario-runs/{runId}`, `POST /api/scenario-runs/{runId}/cancel`. Ten scripts (synthetic family `scenarios`):
`my-overpressure`, `my-extinguisher`, `br-sump` (headline), `br-vessel-cert`, `ops-counsel-tokens` (Bristol's Compliance
Officer re-reads every certificate on each poll; the director reads Steward telemetry, calls it, reconfigures it and reruns a
local efficiency eval stored as an `eval_run` with suite `efficiency`), `ops-injection` and `x-maintenance` (Bristol and Myer
compliance officers and managers agree a shared examiner visit; the director approves a cross-site maintenance window), and for
the mill (contract 5 §5) `tm-humidity` (headline: after a typhoon HS-301 reaches 88 % RH and rises; the Conservation Engineer raises
`humidity_high`, calls the Site Manager, the Compliance Officer cites the cultural-property management duty, the technician sends the
conservator to start DH-1101 and close the north windows; the script ends with the fix workflow, which verifies HS-301 back at 58 %
and signs it), `tm-alteration-permit` (a contractor work order, `doc-tm-contractor-wo`, would drill BW-251; compliance blocks it, the
manager's meeting chooses clamp mounts and the permission request for the cable entry is filed) and `x-heritage` (Tomioka and
Bristol compliance officers and managers share the clamp-mount method and the route-closure procedure; the director approves a
shared `Heritage-safe sensor installation` window on both sites; a `visitor_route` issue at W-801 is left for the fix workflow). The
runner compresses scenario minutes by `speed` (`STEWARD_SCENARIO_SPEED`, default 30) and plays inline at `speed: 0` or without
workers; every step is a Change of type `scenario` on each site the scenario touches.

Every agent-to-agent exchange is a conversation (`src/conversations.py`): meetings (the convener asks each participant over A2A;
the reply is the statement; the convener states the resolution; the contact comes from the crew ownership table), calls
(multi-turn A2A between two speakers, closed with `complete`; voice is browser text-to-speech, never a phone call) and derived
`message` conversations grouped by A2A context for everything else. `GET /api/conversations?siteId=&agentId=&kind=`,
`GET /api/conversations/{id}`, `POST /api/conversations/{id}/summary {summary, summaryBy}`. Scripted conversations carry
hand-seeded summaries; `GET /api/board-meetings?siteId=&issueId=` and `/api/board-meetings/{id}` remain as views of meeting
conversations. Transports: Inkbox A2A when both identities and keys exist, local otherwise.

Maintenance windows: `GET /api/maintenance?siteId=`, `POST /api/maintenance {siteIds, date, scope, examiner?}` (a manager for
a window that includes its own site, or the director), `POST /api/maintenance/{id}/approve` (own-site manager; cross-site
windows need the director).

## Waits (contract 3 §7)

`POST /api/waits {event, siteId?, filter?}` → wait; `GET /api/waits/{id}?timeout=` long-polls up to 300 s and returns
`{status: fired, event}` the moment a matching Change lands or `{status: still_waiting, waitId}`. Events: `work_item.resolved`,
`issue.changed`, `reply.received`, `board.resolved`, `scenario.step`, `conversation.ended`, `fix.step`, `eye.frame`, `tool.changed`,
`tool.published`, `any`; the
filter matches Change fields and event extras. The hub (`src/waits.py`) is called by `emit_change` and wakes the held request
through an `asyncio.Event`; nothing polls the database while a request is held.

## Vision ingest (contract 3 §3)

`POST /api/properties/{id}/inspections/vision` (body = the results JSON, or empty to read `vision/results/<site>.json`; the
site's engineer or manager, the director or the Owner's agent) turns valve results into `finding` records and
`valve_not_fixed` / `valve_uncertain` issues, resolving them when a later run reads the valve as fixed. Findings carry the score,
threshold, comparison `mode` (`baseline`: the valve's own clean capture; `peer`: the site's other valves), `pinWarning`,
`pinSource` and `located`; a valve whose pin is estimated is never presented as a located defect. `defect: none`/null is not a
synthetic defect. `GET /api/properties/{id}/inspections/vision` lists findings and counts.

## The agent eye (contract 4 §2)

`src/eye.py`. `POST /api/eye/{site}/renderers {rendererId}` (heartbeat every 5 s, stale after 15 s);
`GET /api/eye/{site}/commands?rendererId=&since=&timeout=` (long-poll ≤ 25 s; commands are broadcast to every open renderer,
the first to post a frame produces it); `POST /api/eye/{site}/frames {commandId, jpegBase64, camera, visiblePins, index?,
annotation?}`; `GET /api/eye/frames/{frameId}.jpg`; `POST /api/eye/{site}/act {action, params}` (engineer, manager, director or
Owner's agent, own site for team roles): `look`, `move {direction, meters 0.1-5}`, `turn {yawDeg, pitchDeg}`, `go_to {assetTag}`,
`orbit {assetTag, frames 4-16}`, `mark {x, y, note, issue?}` (an annotation near the closest visible pin, optionally an
`eye_observation` issue candidate). It waits up to 20 s (`STEWARD_EYE_ACT_TIMEOUT`; longer for orbits) and returns the frame,
camera and visible pins, or 504 `EYE_TIMEOUT`. With no fresh renderer the worker starts one headless Chrome on
`http://127.0.0.1:3000/eye?site=<id>&renderer=headless` (`STEWARD_EYE_URL`, `STEWARD_CHROME_PATH`; GPU/ANGLE flags first,
SwiftShader if it never registers within 25 s), tracks its PID in its own process group, stops it after 5 idle minutes, and is
off unless workers run (`STEWARD_EYE_AUTOSTART`). Every act is a Change of type `eye` and a telemetry row (~350 tokens a frame).
`GET /api/eye/{site}/feed?since=` returns recent frames with actor and action; `GET /api/eye/{site}/annotations`.

Reproducible views and marks: `PUT /api/properties/{id}/assets/{tag}/pin` also takes `viewPose {position, target, fov?}` (alone it
updates only the pose; `null` clears it; resetting the pin to `estimated` clears it). `go_to` and `orbit` send the stored pose (or an
explicit `params.viewPose`) with the command (`viewPoseSource: asset | request`) so the renderer starts from the same pose every time.
A `mark` frame's picked point is read from `mark` or `annotation` in `POST /frames` and returned by the act as `world` (`{x, y, z}`)
and `hit`. Acts with `params.purpose: "survey"` tag their frames and annotations `survey: true`; `GET /feed?excludeSurvey=true` hides them.

## The fix workflow and notifications (contract 4 §6)

`POST /api/issues/{id}/fix {speed?}` (Owner's agent; `STEWARD_FIX_SPEED`, default 1) plays: evidence (engineer `go_to` + 4-frame
`orbit`, frames attached to the issue, or a note when no renderer is open), call (engineer → manager → compliance with the
regulation reason; the manager assigns the responsible crew member), contact (technician opens a work item and contacts the person
through the dispatch line; synthetic crew are never contacted), fix (a simulated reply with a labelled synthetic photo and
reading through the normal inbound verifier, or in live mode the user's real reply, waited for up to
`STEWARD_FIX_LIVE_TIMEOUT_SECONDS`), verify (attestation re-checked, compliance closes the obligation and unblocks dependants,
the issue is resolved) and inform (the manager notifies every crew member, records only for synthetic crew, and every other
agent over A2A). `GET /api/fix-workflows?siteId=&issueId=`, `GET /api/fix-workflows/{id}`, `GET /api/notifications?siteId=`.

## Overview, activity, telemetry, memory, metrics and evals (contract 3 §8-§10, contract 4 §3)

- `GET /api/overview`: every site (open issues by severity, compliance counts, crew on shift), each agent's status and task,
  the active scenario and the last 10 Changes, kept under 600 estimated tokens.
- Telemetry (`src/telemetry.py`, its own SQLite table): every A2A message, mission step, meeting statement, document read,
  poll, eye act, reconfiguration and Owner's-agent call appends a row with estimated tokens. MCP calls that send
  `X-Steward-Tool` are logged with latency; `POST /api/telemetry` appends explicitly. "Steward telemetry, also delivered to Armature".
- `GET /api/agents/{id}/activity`: current task, why, waiting on, last actions, tokens and calls this hour, settings, memory highlights.
- Memory (`src/memory_store.py`): a local mirror per agent (kind `agent_memory`, namespace `steward-<agentId>`), written after
  decisions, meetings, reconfigurations, document reviews and scenario outcomes. With `SUPERMEMORY_API_KEY` and
  `STEWARD_SUPERMEMORY_LIVE=true` it also writes `POST /ns/{namespace}/document` and recalls `POST /ns/{namespace}/search`
  (hybrid). `GET /api/agents/{id}/memory?query=`.
- `GET /api/evals/findings`: tokens per mission, polls, failures and flags (≥ 5x the peers' median) from telemetry, plus the
  Armature MCP section (`src/armature.py`: Streamable HTTP JSON-RPC to `https://mcp.armature.tech/mcp` with
  `Bearer ARMATURE_API_KEY`; off unless `STEWARD_ARMATURE_LIVE=true` and a workspace read key is set).
- `GET /api/evals/metrics`: pass rate per suite, tokens and tool calls per agent per mission, time held by waits and tokens
  avoided, latency p50/p95, A2A messages per day and an estimated cost (`STEWARD_TOKEN_PRICE_USD_PER_MTOK`, default 7.2).
- `GET /api/properties/{id}/metrics?series=&from=&to=&step=`: synthetic series (`pressure_bar` per circuit, `flow_m3h`,
  `temperature_c`, `level_pct`, `vibration_mms`, `power_kw`; at the mill `humidity_pct` HS-301..303, `temperature_c`, `visitor_count`
  on W-801 (0 outside 09:00-17:00 JST), `vibration_mms` RM-101/RM-104, `crack_width_mm` BW-251 and `power_kw` EP-901) from a seeded
  random walk plus a daily cycle at 5-minute resolution
  over 7 days, with seeded daily pump outages, facts for the same asset merged in as overlays (scenario ramps, verified fixes,
  the simulated sensor feed) and 5-second live points while the simulation runs. `GET /api/metrics/summary`: per site and the
  portfolio average over the three sites (pressure, flow, uptime, open issues, compliance, crew on shift, agent actions today, and
  the mill's `avgHumidityPct`, `visitorsToday` and `maxCrackWidthMm`; a site without a series reports null and is left out of that average).

## Synthetic data

`backend/seed/synthetic/*.json` (crews, obligations, documents, sensor_history, scenarios, conversations, maintenance,
armature_traces, forged_tools) is the deterministic hand seed the backend loads (the Tomioka records are hand-seeded, ids matching the
REGULATIONS stream's suggested obligations: `ob-tm-*`, `crew-tm-*`); every record says `synthetic: true, generator: "hand-seed"`.
`scripts/synth/generate.py` (dry run by default: writes prompts and request bodies to `backend/seed/synthetic/_prompts/`) calls
`claude-opus-5-5` once per family with structured JSON output (a strict schema inferred from the hand seed, refusal fallbacks
`fallbacks: "default"`) on `--live`. `scripts/synth/summarise.py` (dry run by default) summarises conversations without a summary
and posts them back with `summaryBy: claude-opus-5-5` on `--live`. `scripts/synth/forge.py` (dry run by default) drafts a Tool Forge
tool for a task or a recorded request with `claude-opus-5-5` (effort high, structured output against a closed schema with no
optional properties, `fallbacks: "default"` under `server-side-fallback-2026-07-01`) and posts it to `POST /api/tools/requests` on
`--live` (`--validate --test` continue the lifecycle; approval stays with the site's manager or the Director).

## Safety switches

- `STEWARD_ALLOW_EXTERNAL_MESSAGES` is the single send-time gate (`providers.external_messages_allowed()`, read from the
  environment on every call) for every message to a person: work-item dispatch, scheduled escalations (re-send, email, voice
  call, owner SMS), replies on a thread, notices, fix-workflow contact, the `decide` SMS and agent document email. When it is
  not `true`, nothing is sent and the attempt is recorded as a dispatch / notice / email with `providerRef: null` and a body or
  mode that says `dry-run`. A test runs the scheduler's whole ladder on a work item with real-looking, allowlisted contacts and
  asserts no provider client is ever created.
- `STEWARD_A2A_TRANSPORT=auto | local | inkbox`: `local` never calls Inkbox A2A even when keys exist (sends, replies to
  webhook-created tasks, follow-ups, startup recovery, meetings, missions, simulation); `auto` (default) and `inkbox` use Inkbox
  whenever both identities and the sender's key exist.
- Telemetry: the MCP posts one `POST /api/telemetry {agentId, tool, tokens, ms, detail: {in, out}}` per tool call and does not send
  `X-Steward-Tool`; only requests carrying that header are counted by the middleware, and Owner's-agent endpoint calls are not
  counted again, so MCP calls appear once.

## Live switches for the end-to-end test

Everything above defaults to local or dry-run. Live paths and their switches: Inkbox A2A between the nine identities
(`STEWARD_A2A_TRANSPORT=auto` or `inkbox`, with `INKBOX_API_KEY` and both `INKBOX_IDENTITY_*` / `INKBOX_AGENT_KEY_*`); agent document email
(`STEWARD_ALLOW_EXTERNAL_MESSAGES` + `STEWARD_ALLOW_AGENT_EMAIL`); notices and fix-workflow SMS to the user through the dispatch line
(`STEWARD_ALLOW_EXTERNAL_MESSAGES` + `STEWARD_ALLOW_NOTICE_SMS` + the allowlisted `INKBOX_CONTRACTOR_PHONE` + `INKBOX_IDENTITY_DISPATCH`);
Supermemory (`STEWARD_SUPERMEMORY_LIVE=true`); Armature reads (`STEWARD_ARMATURE_LIVE=true` with a workspace read key);
Claude (`scripts/synth/*.py --live`); the headless eye (`STEWARD_EYE_AUTOSTART`, on by default when workers run).

## People and compliance at the mill (contract 5 §4)

Seven synthetic crew with Japanese names and no contact details, plus "Duty engineer (you)" (the user, contact resolved at send time
and shown masked, as on the other sites): site manager on duty, conservation architect (owns `humidity_high`, `alteration_permit`,
`certificate_expired`), the reeling-machine conservator, visitor safety lead (`visitor_route`, `walkway_closure`), fire and facilities
officer (`inspection_overdue`) and guide supervisor. Compliance kinds now include `alteration_permit` and `visitor_route` (owned by
the site's Compliance Officer). Obligations `ob-tm-humidity-watch`, `ob-tm-bw251-permit`, `ob-tm-fe-inspection`,
`ob-tm-fh601-inspection` and `ob-tm-heritage-mounting` cite `jp-cpa-1950-*` / `jp-fsa-1948-*` / `jp-fso-1961-*` / `jp-fsr-1961-*`
records; documents include the contractor work order `doc-tm-contractor-wo` (TM-WO-2026-117), the draft permission application
`doc-tm-permit-request`, the humidity log and the fire-equipment report, and Bristol's `doc-br-heritage-methods` method statement
that x-heritage emails to Tomioka's Compliance Officer.

## Tool Forge (contract 6)

`src/forge.py`. An agent that lacks a tool records the gap, drafts a declarative tool, Steward validates and tests it, a manager or the
Director approves it, and it is published for the MCP (which registers it as `forge_<name>`). No generated code runs: every step is
an allow-listed op (`facts.list`, `metrics.series`, `metrics.samples`, `issues.list`, `obligations.list`, `crew.list`,
`crew.responsible`, `components.list`, `regulations.list`, `conversations.list`, `maintenance.list`, `resolve`; acts `eye.go_to`,
`eye.look`, `issues.raise`, `viewer.focus`, and `resolve` with a budget) or a pure transform (`filter`, `map`, `group_count`, `sort`,
`take`, `join_on`, `concat`), with string arguments that are literals or `{{input.x}}` / `{{steps.id.field}}` / `{{item.field}}`
templates. Every op runs as the creating agent (`authorize(createdBy, action, siteId)`) at the tool's own site only.

| Method & path | Purpose |
| --- | --- |
| `POST /api/tools/requests {siteId, task, agentId?, requestedBy?, draft?, generator?, draftKey?, requestId?}` | Records the gap and the tools considered, opens the request conversation, drafts (the matching hand-seeded draft in build mode, or the posted `draft`); 201 with `{request, tool}`, or 202 `awaiting_draft` |
| `GET /api/tools/requests?siteId=` | Recorded requests |
| `GET /api/tools?siteId=&status=&agentId=` | Tools (`status=published` for the MCP), each with `mcpName`, `mcpDescription` ("Built by … on … because …"), `recipe` |
| `GET /api/tools/catalog` | The allow-list, transforms, template and condition grammar |
| `GET /api/tools/{id}` | One tool: why, recipe, validation, test, approval, usage |
| `POST /api/tools/{id}/validate` | Schema, allow-listed ops, templates resolve, scope is the builder's own site, closed output schema |
| `POST /api/tools/{id}/test {input?}` | One run on live local data (act steps previewed); stores `{input, output, passed, ms, at, notes}` |
| `POST /api/tools/{id}/approve {approve, reason}` | The site's manager (or the Director) for read-only tools; the Director for any act; a refusal needs a reason |
| `POST /api/tools/{id}/publish` | Published (an earlier published version is retired and superseded) |
| `POST /api/tools/{id}/call {args}` | Runs it for the caller (the site's team, the Director or the Owner's agent); usage, tokens saved, telemetry |
| `POST /api/tools/{id}/retire {reason?}` | Retired |

Every lifecycle step is a stored Change of type `tool` carrying `toolId`, `status`, `step` and `version` (wait events `tool.changed`,
`tool.published`) and a line on the request's A2A conversation, so it shows in both agents' transcripts ("I don't have a tool for this;
drafting forge_pump_spec_breaches"). A new version of a name keeps the old one's usage history. Hand-seeded demo drafts
(`backend/seed/synthetic/forged_tools.json`): `pump_spec_breaches {days, minBreaches}` for Myer (built by the Site Engineer · Myer,
asked by the Owner's agent, approved by the Plant Manager · Myer) and `visitor_route_readiness {}` for Bristol (built by the
Compliance Officer · Bristol, asked by the Plant Manager · Bristol). The runner and lifecycle work for every site, the mill included.
