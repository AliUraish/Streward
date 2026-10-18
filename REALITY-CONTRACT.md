# Steward reality layer: implementation contract

Written Oct 17 2026, 18:30. Every workstream builds against this file. Product framing is in AGENT-NATIVE-PLAN.md. Site == property: the backend keeps `propertyId` and the `/api/properties/{id}` prefix; the MCP presents it as `siteId`. IDs stay `cedar`, `harbor`, `juniper`. Demo site is `harbor` (Harbor Works).

## Workstreams and file ownership

| Stream | Owns | Must not touch |
| --- | --- | --- |
| Backend | `backend/**` | everything else |
| MCP | `mcp-runtime/**`, `evals/**` | backend, frontend |
| Frontend | `frontend/**` | backend, mcp-runtime, `shared/scene.json` |
| Integrations | `supabase/**`, `docs/**`, `armature/**`, `manufact/**`, root `.env.example`, `README.md` sections marked for it | code dirs above |
| Root (orchestrator) | `shared/types.ts` additions, `package.json` scripts, this file | |

Shared types below are the contract. The orchestrator adds them to `shared/types.ts`; backend and MCP mirror them exactly (camelCase JSON, ISO UTC timestamps).

## Domain types

```ts
export type AttributeClass = 'reading' | 'condition' | 'document' | 'identity';
export type SourceKind = 'scan' | 'camera' | 'sensor' | 'patrol' | 'human' | 'agent' | 'owner';
export type FactStatus = 'known' | 'stale' | 'unknown' | 'conflict';
export type Verdict = 'accepted' | 'rejected' | 'needs_clarification';
export type WorkState = 'open' | 'dispatched' | 'waiting' | 'needs_clarification' | 'escalated' | 'resolved' | 'rejected' | 'expired';
export type Channel = 'local' | 'email' | 'sms' | 'imessage' | 'call';

export interface Source { kind: SourceKind; ref: string; }           // ref: evidence id, sensor id, job id, thread id, agent name
export interface Check { name: 'scope'|'identity'|'geometry'|'plausibility'|'time'|'integrity'; passed: boolean; reason: string; }

export interface Fact {
  id: string; propertyId: string; assetTag: string; componentId: string;
  attribute: string; attributeClass: AttributeClass; value: string | number | boolean; unit?: string | null;
  observedAt: string; ttlSeconds: number | null; expiresAt: string | null;
  source: Source; attestationId: string; version: number; createdAt: string;
}

export interface Attestation {
  id: string; propertyId: string; assetTag: string; componentId: string; attribute: string;
  value: string | number | boolean; unit?: string | null; observedAt: string;
  evidenceHashes: string[]; checks: Check[]; verdict: Verdict; source: Source;
  verifierVersion: string; signedAt: string; publicKey: string; signature: string;   // Ed25519, base64; payload = canonical JSON of all fields except signature
}

export interface Dispatch { id: string; channel: Channel; to: string; reference: string; sentAt: string; providerRef?: string | null; body: string; }

export interface Receipt { waitedSeconds: number; tokensWhileWaiting: 0; estimatedPollingTokens: number; dispatches: number; cost: number; currency: 'USD'; }

export interface WorkItem {
  id: string; propertyId: string; assetTag: string; componentId: string; attribute: string; attributeClass: AttributeClass;
  reference: string;                      // e.g. HW-P101-PRESSURE-0042, used in subject lines and message bodies
  state: WorkState; requester: string; budget: number; deadlineAt: string | null;
  dispatches: Dispatch[]; verdicts: { attestationId: string; verdict: Verdict; reasons: string[]; at: string }[];
  factId?: string | null; attestationId?: string | null; receipt?: Receipt | null;
  createdAt: string; updatedAt: string;
}

export interface Change { version: number; type: 'fact'|'work_item'|'attestation'|'dispatch'|'escalation'|'owner_decision'; propertyId: string; assetTag?: string; refId: string; summary: string; at: string; }

export interface ResolveResult {
  status: FactStatus; propertyId: string; assetTag: string; attribute: string;
  value?: string | number | boolean; unit?: string | null; observedAt?: string; ageSeconds?: number; attestationId?: string;
  conflicts?: { attestationId: string; value: string | number | boolean; observedAt: string }[];
  workItemId?: string; workState?: WorkState; reference?: string; dispatchedVia?: Channel; expiresAt?: string;
  cost?: number; nextStep: string;
}

export interface AttestResult { verdict: Verdict; reasons: string[]; checks: Check[]; attestationId?: string; factId?: string; workItemId?: string; nextStep: string; }

export interface Subscription { id: string; propertyId: string; callbackUrl: string; requester: string; createdAt: string; }

export interface ClearanceResult { clear: boolean; widthM: number; blockingAssetTag?: string | null; blockingComponentId?: string | null; path: [number, number][]; }

export interface ContextMin { propertyId: string; name: string; version: number; assets: number; facts: { known: number; stale: number; unknown: number }; blockers: { assetTag: string; attribute: string; state: WorkState; reference: string }[]; sensors: { assetTag: string; attribute: string; value: string|number|boolean; ageSeconds: number }[]; }
```

## Attribute classes, TTLs and spec ranges

TTL by class: `reading` 3600 s, `condition` 86400 s, `document` 31536000 s, `identity` null (never expires).

Spec ranges live in `backend/src/specs.py` keyed by component `kind`, and are also exported at `GET /api/properties/{id}/specs`:

| kind | attributes (class, unit, range or enum) |
| --- | --- |
| pump | `pressure_bar` (reading, bar, 1.5–3.5), `running` (condition, enum on/off), `commissioning_certificate` (document), `serial` (identity) |
| gauge | `pressure_bar` (reading, bar, 0–6), `serial` (identity) |
| valve | `position` (reading, enum open/closed/partial), `serial` (identity) |
| sensor | `temperature_c` (reading, °C, 5–40), `serial` (identity) |
| tank | `level_pct` (reading, %, 10–95), `serial` (identity) |
| exchanger | `outlet_temperature_c` (reading, °C, 30–80), `serial` (identity) |
| panel | `status` (condition, enum normal/tripped/alarm), `serial` (identity) |
| duct | `airflow_ok` (condition, enum yes/no), `serial` (identity) |
| light | `working` (condition, enum yes/no) |
| fire | `inspection_tag_date` (document), `pressure_ok` (condition, enum yes/no) |
| door | `closed` (condition, enum yes/no) |

Unknown attribute for a kind → HTTP 400 `UNSUPPORTED_ATTRIBUTE` listing supported ones.

Seeded facts for the demo (harbor): `P-101.commissioning_certificate` known (observed 4 months ago, source document), `V-501.position` = open (40 min old, source patrol), `TS-801.temperature_c` and `TS-802.temperature_c` (sensor, 2 min old). `P-101.pressure_bar` deliberately has no fact. Cedar and juniper get identity facts only.

## Verification engine (`backend/src/verify.py`)

Input: work item (optional), submitted observation (assetTag, attribute, value, observedAt, stated tag from message body or JSON, file bytes optional, source). Checks, all must pass for `accepted`:

| name | rule |
| --- | --- |
| scope | `propertyId` matches; if a work item is given, its `propertyId` and `assetTag` match the submission. Wrong site → rejected. |
| identity | stated tag (JSON `tag`, message body regex `\b[A-Z]{1,3}-\d{3,4}\b`, or filename) equals the expected asset tag. Photo OCR is optional; absence of a stated tag → `needs_clarification`, a different tag → `rejected` with "tag plate reads X, expected Y, Y is N m <direction> of X" computed from scene positions. |
| geometry | the stated tag's component exists at the expected `componentId`; a sibling of the same kind within 3 m is reported by name in the reason. |
| plausibility | numeric value inside spec range → pass; outside → `needs_clarification` ("9.8 bar exceeds 3.5 bar spec; confirm with a second reading"); enum not in set → rejected. |
| time | `observedAt` within `[workItem.createdAt - 5 min, now + 2 min]`; EXIF DateTimeOriginal used when present in a JPEG, else provider receipt time, else submission time. |
| integrity | SHA-256 of file bytes (or canonical JSON of the observation when no file); the same hash already attached to a different work item → rejected "evidence reused from <id>". |

`verifierVersion` = `"steward-verify/1"`. Verdict precedence: any rejected → `rejected`; else any needs_clarification → `needs_clarification`; else `accepted`. Only `accepted` writes a Fact, signs an Attestation, updates the component in the scene (status + `lastFactAt`), resolves the work item, emits a Change, posts to subscribers.

Signing: Ed25519 via `cryptography`. Key at `<data dir>/signing.key` (generated, 0600, gitignored by `backend/data/`). Public key exported base64 at `GET /api/attestations/public-key`.

## Resolver policy (`backend/src/reality.py`)

1. Validate attribute for the component kind.
2. Latest accepted facts for (property, tag, attribute). If two facts within the class TTL disagree → `conflict`, open a work item in `needs_clarification`.
3. Fresh (age ≤ min(ttl, maxAgeHours)) → `known`.
4. Stale and `budget > 0` → dispatch, return `stale` with old value and `workItemId`. Stale and no budget → `stale` with old value only.
5. Unknown and `budget > 0` → dispatch, return `unknown` with `workItemId`. No budget → `unknown` with `nextStep: "call resolve again with budget > 0 to dispatch"`.
6. An open work item already exists for the same (property, tag, attribute) → return it instead of creating a second one.

Dispatch: builds a task card from the scene (room wall by sign of z, nearest two neighbours by tag, expected range from specs) and sends through `CommsAdapter`. Channel selection: `INKBOX_*` configured → `sms` if a contact phone exists else `email`; otherwise `local` (card stored, work item `waiting`, reply accepted through `/api/inbound/local`). Reference format: `{SITE2}-{TAG no dash}-{ATTR upper}-{seq:04d}`, e.g. `HW-P101-PRESSURE_BAR-0042`.

Escalation ladder (`escalate(level)` and the scheduler every 30 s): `1` re-send same channel on same thread; `2` email; `3` call (Inkbox voice if configured, else record `call` dispatch with `providerRef: null` and reason); `4` owner question by SMS. Deadline passes with no accepted fact → `expired` and a Change.

Receipt: `waitedSeconds` = resolve → accepted; `estimatedPollingTokens` = ceil(waitedSeconds / 30) × 350; `cost` = 0 unless a paid dispatch is recorded (none in this build).

## HTTP API (FastAPI, port 8001) — additions

All under the existing auth/origin middleware. Errors: `{detail, code, recovery}`.

| Method & path | Body / query | Returns |
| --- | --- | --- |
| `POST /api/properties/{id}/resolve` | `{assetTag, attribute, maxAgeHours?, budget?, requester?, callbackUrl?}` | `ResolveResult` |
| `POST /api/properties/{id}/attest` | JSON `{assetTag, attribute, value, unit?, observedAt?, source:{kind,ref}, statedTag?, workItemId?}` or multipart with the same fields plus `file` | `AttestResult` |
| `GET /api/attestations/{attestationId}` | | `Attestation` (plus `valid: boolean` after signature re-verification) |
| `GET /api/attestations/public-key` | | `{algorithm:'ed25519', publicKey, verifierVersion}` |
| `GET /api/properties/{id}/facts` | `?assetTag=&attribute=` | `Fact[]` latest per (tag, attribute) with `status` computed |
| `GET /api/properties/{id}/changes` | `?since=0&limit=100` | `{version, changes: Change[], waiting: WorkItem[]}` |
| `POST /api/properties/{id}/subscriptions` | `{callbackUrl, requester}` | `Subscription` (callbackUrl must be http(s); loopback allowed) |
| `GET /api/work-items/{workItemId}` | | `WorkItem` |
| `POST /api/work-items/{workItemId}/escalate` | `{level: 1|2|3|4, note?}` | `WorkItem` |
| `POST /api/properties/{id}/clearance` | `{from:[x,z], to:[x,z], widthM}` | `ClearanceResult` (2-D corridor test against component footprints from scene; footprint radius by kind, default 0.6 m) |
| `GET /api/properties/{id}/context.min` | | `ContextMin` (≤ 400 tokens) |
| `GET /api/properties/{id}/specs` | | spec table |
| `POST /api/properties/{id}/patrol` | `{scope?}` | `Job` — existing inspection job plus: writes `identity` facts for every checked asset (source `patrol`, ref job id), refreshes `sensor` readings for sensor-kind assets from the simulated feed (clearly `source.kind='sensor'`, ref `sim:TS-801`), emits one Change per fact |
| `POST /api/inbound/inkbox` | provider payload; header `X-Steward-Inbound-Secret` must equal `STEWARD_INBOUND_SECRET` | `{routed: boolean, workItemId?, verdict?}` — route by thread/providerRef, then reference regex, then sender + open items; unrouted → stored under `inbound_unrouted` and a Change |
| `POST /api/inbound/local` | `{reference, body, statedTag?, value?, observedAt?}` + optional multipart `file` | same as above; used for replay and the dashboard's "reply as contractor" control |
| `POST /api/properties/{id}/owner-decision` | `{workItemId, decision, note?}` | writes a `condition` fact with `source.kind='owner'`, resolves the item, Change type `owner_decision` |

Subscriptions: on any Change for a property, POST `{event:'steward.change', change, workItem?}` to each callbackUrl with 5 s timeout, 3 retries, never blocking the request path. Delivery attempts are events.

Supabase mirror: when `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are set, every put of kinds `fact`, `attestation`, `work_item`, `dispatch`, `change`, `subscription` is mirrored to the matching table through PostgREST (upsert on `id`), asynchronously, with failures logged as events and never blocking. SQLite stays the source of truth in this build; `scripts/supabase-sync.py` backfills. `GET /api/integrations` reports `supabase` as `connected` only after one successful upsert.

Inkbox: extend the existing adapter with `send_sms(to, body)`, `send_email(to, subject, body, reference)`, `place_call(to, script)` (if the SDK exposes voice; else raise `ProviderNotConfigured` with the exact reason), `inbound mechanism` discovered from the installed SDK source under `backend/.venv/lib/python3.12/site-packages/inkbox/`. Keep allowlist and `STEWARD_ALLOW_EXTERNAL_MESSAGES` gates. New env: `INKBOX_OWNER_PHONE`, `INKBOX_CONTRACTOR_PHONE`, `INKBOX_CONTRACTOR_EMAIL`, `STEWARD_INBOUND_SECRET`, `STEWARD_PUBLIC_BASE_URL` (tunnel URL for callbacks).

## MCP surface (`mcp-runtime`)

New tools, same `tool()` helper, zod schemas mirroring the types above. `siteId` is the enum of property IDs.

| tool | annotations | input | output |
| --- | --- | --- | --- |
| `resolve` | write when budget>0 | `{siteId, assetTag, attribute, maxAgeHours?, budget?, callbackUrl?}` | `ResolveResult` |
| `attest` | write | `{siteId, assetTag, attribute, value, unit?, observedAt?, source, statedTag?, workItemId?}` | `AttestResult` |
| `check` | read | `{attestationId}` | `Attestation & {valid}` |
| `get_changes` | read | `{siteId, since?, limit?}` | `{version, changes, waiting}` |
| `subscribe` | write | `{siteId, callbackUrl}` | `Subscription` |
| `get_receipt` | read | `{workItemId}` | `WorkItem` |
| `escalate` | write | `{workItemId, level, note?}` | `WorkItem` |
| `query_clearance` | read | `{siteId, from, to, widthM}` | `ClearanceResult` |
| `patrol` | write | `{siteId, scope?}` | `{job, nextStep}` (keeps `run_inspection` as an alias) |
| `list_sites` | read | `{}` | alias of `list_properties` with `siteId` naming |

Resources: `steward://guide` (rewrite for the three verbs), `steward://schema` (the TS types above as text), `steward://sites/{siteId}/context.min`, `steward://sites/{siteId}/specs`. Prompt: `prove-before-signing(siteId, task)`. Errors keep `{code, message, recovery}`. Requester identity: the MCP passes `requester` = client name from the MCP session when available else `"mcp-client"`.

Armature: install their MCP analytics SDK per `docs.armature.tech` (integrations stream documents the exact package and init); wire it in `server.ts` behind `ARMATURE_API_KEY`; no key → no-op. Manufact: `manufact/` holds the deploy config and the README section; server must run with `STEWARD_BACKEND_URL` pointing at the tunnel URL when hosted (config.ts gains `STEWARD_ALLOW_REMOTE_BACKEND=true` to permit a non-loopback https backend, default off).

Evals: `evals/demo-workflow.json` describes the demo as replayable steps (resolve known → resolve unknown with budget → inbound wrong tag → inbound right tag → check). `evals/run.mjs` executes it against any MCP URL with mcp-use and prints a pass/fail table; the integrations stream maps it to Armature's eval format if one exists.

## Frontend (`frontend`)

- `/` website, `/app` dashboard. Black ground, white ink, one accent (`#3ddc84` family, used for verified and the primary action), tone-step surfaces, no hairlines, no eyebrows, no gradients, no shadows, Geist via `@fontsource`/`geist` package. Monospace only for tags, references, hashes.
- Website sections: hero with live `resolve` typed out from a real backend call; three eyes (scan, camera, sensor); rejected then accepted proof; signed attestation with a `check` call; "runs on" Inkbox, Manufact, Supabase, Armature. Motion: staggered entrances, reduced-motion fallback.
- Dashboard: twin dominant (existing scene components untouched), right rail: work items with state and reference, facts with freshness bars, attestation badges that open the signed record; timeline from `/changes`; "reply as contractor" control posting to `/api/inbound/local` with reference, stated tag, value and optional photo; owner decision control. Poll `/changes` every 2 s during an open work item; Supabase Realtime subscription when `NEXT_PUBLIC_SUPABASE_URL` and anon key exist.
- Keep the inspection wall and library views reachable but secondary.

## Definition of done per stream

- Backend: `npm run test:backend` green with new tests: resolve known/stale/unknown/conflict; attest wrong tag rejected with direction; plausibility; integrity reuse; signature verifies and tampering fails; local inbound routes by reference; subscription callback delivered (test server); patrol writes facts; context.min under 400 tokens (≤ 1600 chars).
- MCP: `npm run build:mcp` and `npm --prefix mcp-runtime test` green; `npm run demo:mcp` runs the demo workflow against the local backend and prints the table.
- Frontend: `npm run build` green; website and dashboard render at 1440/768/390; taste-skill inspector run and results recorded in `frontend/DESIGN-DECISION.md` with cited taste-library sections.
- Integrations: `supabase/migrations/0001_reality.sql` applies cleanly on a fresh project (tables, RLS, realtime publication, indexes); `docs/INTEGRATIONS.md` says exactly what each sponsor is used for, what key is needed, and what its judge can see; `armature/` and `manufact/` configs present; `.env.example` updated.
