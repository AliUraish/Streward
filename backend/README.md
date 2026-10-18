# Steward local backend

Canonical application settings use `STEWARD_*`. Existing `PHY_*` environment variables remain backward-compatible aliases; an explicitly set `STEWARD_*` value takes precedence. The current database is `backend/data/steward.sqlite3`. On the first upgrade, the application snapshots the previous database with SQLite's backup API (including committed WAL data), keeps a recovery copy under `.migration-backups/`, and migrates display branding without changing record IDs, attachments, jobs or property names. Original seed PDF headers are updated; uploaded originals remain byte-for-byte unchanged.

Run `bash backend/run.sh` from the repository root. The backend binds to `127.0.0.1:8001`; the Next.js application proxies `/api/*`. No cloud deployment is required or performed. `/health` verifies SQLite access; `/docs` contains the interactive API documentation; `/mcp` is a stateless Streamable HTTP MCP JSON-RPC endpoint.

The first startup generates three original project workspaces, original PDF project specifications, 24 scene objects per property, 96 linked project checks per property, and synthetic baseline evidence. These are demonstration project records, not actual building code, physical inspection, or official approval. Original fixture PDFs carry the same disclosure. Uploaded originals and source pages remain available.

The default property workers perform actual deterministic record checks: extract project source text, validate unique equipment tags and model bounds, match evidence to property/equipment/requirement, persist assessments, recompute readiness, create source-linked memory, and generate an escaped HTML/JSON report. They do not pretend to run model vision. The portfolio coordinator queues work in the three separate property contexts. Jobs, checkpoints, append-only events, user edits and files persist in `backend/data`; interrupted jobs resume after restart. There are no artificial progress delays.

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

Reference format: `{SITE2}-{TAG without dash}-{ATTRIBUTE upper}-{seq:04d}`, with `HW`/`MY`/`BR` for harbor-works/myer-plant/bristol-pumps,
e.g. `HW-P101-PRESSURE_BAR-0042`. The task card is built from the scene: wall by the sign of z, the two nearest
neighbours by tag, the expected range from the spec table, and the reference on the last line. Channel selection:
`sms` only when `INKBOX_API_KEY`, the site's Warden identity, `STEWARD_ALLOW_EXTERNAL_MESSAGES=true` and an allowlisted
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

The site identity is its Warden (`INKBOX_IDENTITY_WARDEN_HARBOR_WORKS` / `_MYER_PLANT` / `_BRISTOL_PUMPS`; the legacy
`INKBOX_IDENTITY_<SITE>` form is still read), with a single `INKBOX_IDENTITY` as the fallback for every site. Phone numbers are a separate quota: if only one number exists, set
`INKBOX_PHONE_IDENTITY` to the handle that owns it and SMS, iMessage and voice for every site go through that identity;
the task card always names the site. Every outbound send still requires `STEWARD_ALLOW_EXTERNAL_MESSAGES=true` and the
recipient in `INKBOX_ALLOWED_RECIPIENTS`.

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
a `file`. The reference can also sit in the body ("Re: HW-P101-PRESSURE_BAR-0001 …") and the tag in the filename
(`IMG_P-101_gauge.jpg`). A wrong tag is rejected with the direction to the right asset; the correct one writes the fact,
signs the attestation, resolves the item and fires subscriptions. Seeded demo facts (harbor-works: `P-101.commissioning_certificate`,
`V-501.position`, `TS-801/802.temperature_c`, `DB-401.status`, `FE-1001.pressure_ok`, `D-1101.closed`; identity serials
everywhere) are written once and survive restarts; seeded demo observations past their TTL are re-seeded on startup
(`seed:patrol-refresh`) only while nothing but seeds was ever written for that attribute, so the one-unknown demo mission
(`P-101.pressure_bar`) stays reproducible.

### Supabase mirror

With `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` set, every put of `fact`, `attestation`, `work_item`, `dispatch`, `change`
and `subscription` is upserted through PostgREST on a background thread; failures become `mirror.failed` events and
`GET /api/integrations` reports `supabase` as `connected` only after one successful upsert. Column names are in
`backend/SUPABASE-COLUMNS.md`; `backend/scripts/supabase_sync.py` backfills existing rows.

## Sites and environments

Site == property: the API keeps `/api/properties/{id}` and `propertyId`. IDs (`^[a-z][a-z0-9-]{2,30}$`) and reference
prefixes: `harbor-works` (HW, the demo, a Three.js fixture twin from `shared/scene.json`), `myer-plant` (MY, SuperSplat
scene `66b655d3`) and `bristol-pumps` (BR, SuperSplat scene `8a8ce192`). The registry lives in `src/sites.py`. Property
records are industrial, not residential: `{id, name, site, operator, status: operational | restart pending | under
restoration, environment, readiness, componentCount, openIssues, updatedAt}`. `environment` is `{kind: fixture | splat,
splatId?, embedUrl? (https://superspl.at/s?id=<id>), thumbnailUrl?, credit, captureNote}`; the splat scenes are
third-party captures hosted on SuperSplat, the credit says so, and `captureNote` is exactly "Scene rendered from a
third-party capture hosted on SuperSplat; shown here as the site environment." We did not capture them.

Splat sites keep the same 24-asset register; every component there carries `pin: {x, y}` (normalised 0..1) for the
dashboard's 2-D overlay. Pins are **approximate**: derived from the register layout with a per-site offset, not measured on
the capture. `GET /api/properties/{id}/issues` → `Issue[] {id, assetTag, componentId, kind: out_of_range |
rejected_evidence | overdue | unknown_identity | escalated, severity, summary, refId, pin, at, simulated?}` from open
work items in `needs_clarification` / `escalated` / `expired`, latest facts outside spec, rejected verdicts in the last
24 h and assets without an identity fact.

Databases created with the old IDs (`cedar` / `harbor` / `juniper`) are migrated in place once on startup
(`src/sites.py::migrate_site_ids`, guarded by `steward_site_ids_version`): a backup goes to
`.migration-backups/pre-site-ids-<stamp>.sqlite3`, then `records.property_id`, embedded `propertyId`/`_propertyId`
fields, seed-derived record IDs and URLs (`cedar-spec` → `myer-plant-spec`, `agent-cedar` → `agent-myer-plant`,
`seed-cedar-…`, `cedar:<n>` change IDs), `CH-`/`JR-` references, events and `reality:*` meta keys are renamed and the seed
files on disk follow. Signed attestations whose body changed are re-signed with the local key (the backend is the
signer; a stale signature would read as tampering). `apply_site_shape` then de-residentialises the property records and
adds environments and pins.

## Four agents and authority

| level | id | name | role |
| --- | --- | --- | --- |
| 1 | `operator` | Operator | the customer's own agent, holds the mandate (external MCP requester, no Inkbox identity) |
| 2 | `atlas` | Atlas | portfolio coordinator: delegates, cross-checks sites, declares readiness, asks the owner |
| 3 | `warden:<siteId>` | Warden · <site name> | site agent: resolves, verifies, signs for one site |
| 4 | `runner` | Runner | field agent: reaches employees and contractors by SMS, email and call, collects evidence |

`GET /api/agents` → `AgentInfo[] {id, level, name, role, handle?, status: idle | working | waiting, currentTask?,
lastActivityAt, authority, transport}`; status is computed from the open A2A tasks the agent is part of. Every mutating
reality endpoint reads `X-Steward-Actor` (`operator` when absent, so existing callers keep working) and checks the
authority table in `src/agents.py`: Atlas cannot attest or dispatch people, a Warden acts only for its own site, Runner
cannot attest or write facts, the owner may only decide. A refusal is `403 {code: "AUTHORITY_DENIED", detail, recovery}`
naming who may do it. Two paths coexist on purpose: the **single-agent path** keeps the Operator's direct verbs
(`resolve`, `attest`, `escalate`, `owner-decision`) because the MCP tools, the dashboard controls and the demo eval use
them; the **four-agent path** is a mission, where the backend's own agents act under the table above. `operator` calls
are logged as `mcp` transcript entries (endpoint name and compact, secret-free args).

## A2A

`src/a2a.py` is one bus with two transports. Every task is kind `a2a_task` `{id, contextId, caller, target, state:
submitted | working | input_required | completed | failed | canceled, messages: [{role: caller | agent, parts, at,
intent?}], transport: local | inkbox, providerTaskId?, providerContextId?, siteId, steward, simulated?, createdAt,
updatedAt}`; every message emits a Change of type `a2a`. Parts are a text part a human can read plus
`{data: {steward: {missionId, siteId, assetTag?, attribute?, workItemId?, attestationId?, budget?, from, to, messageId}}}`.
`GET /api/a2a/tasks?siteId=&missionId=&agent=` and `GET /api/a2a/tasks/{id}` expose them.

- `local`: in-process delivery to the registered handler (Atlas, Warden, Runner in `src/missions.py`), persisted
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
  event. At startup (workers only) a daemon thread sets each configured identity's skills with `a2a_set_skills` (Atlas
  `clear-site-for-restart`, `cross-site-check`; Warden `resolve-fact`, `attest-evidence`; Runner `dispatch-technician`,
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

Atlas runs the five steps in `src/missions.py` as a checkpointed job (the record is rewritten after every reply, so a
restart resumes from `items`/`tasks`; `MissionEngine.recover` re-reads the work items and advances): (1) Atlas → Warden
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
inbound replies (`inbound_message` records, in) for the Runner, owner decisions (`decision`) for Atlas, Operator
endpoint calls (`mcp`) and mission steps (`system`). Call entries carry the Inkbox transcript lines as text, the
`transcript_url`, and `audioUrl` when the provider reported a recording URL. `since` is an offset into the
chronological list.

## Simulation

`src/simulate.py` runs as a daemon thread only with workers and `STEWARD_SIMULATION=true` (default; tests set it
false): every 20 s a sensor reading for each sensor-kind asset on every site (source `sensor`, ref `sim:<tag>`), every
2 min one plausible event on a non-demo site in rotation: a reading drifting out of range (an `out_of_range` issue), a
patrol identity fact (`sim:patrol`), a short Atlas → Warden A2A status task that completes by itself, an expired work
item (local card, `simulated`, nobody contacted). Every simulated fact, attestation, change, work item, dispatch and
task carries `simulated: true`; `harbor-works` gets only sensor readings. `GET /api/simulation` → `{enabled, running,
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
