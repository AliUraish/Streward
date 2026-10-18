# Contract addendum 2: four agents, environments, evals, transcripts

Written Oct 17 2026, 19:40, revised 20:05. Extends REALITY-CONTRACT.md; everything there stands except site IDs and agent names, which change as below. Nothing is residential any more.

## Site IDs (rename everywhere: backend, MCP enum, evals, frontend, supabase seed)

| old id | new id | reference prefix | name |
| --- | --- | --- | --- |
| harbor | `harbor-works` | HW | Harbor Works |
| cedar | `myer-plant` | MY | Myer Plant Room |
| juniper | `bristol-pumps` | BR | Bristol Dock Machine Room |

Existing SQLite databases are migrated in place (records.property_id, job/work item/fact bodies, events) by the backend on startup, idempotently. Site IDs match `^[a-z][a-z0-9-]{2,30}$`. The demo site is `harbor-works`.

## Agent names

| level | id | display name | role line | Inkbox handle env |
| --- | --- | --- | --- | --- |
| 1 | `operator` | Operator | the customer's own agent, holds the mandate | none |
| 2 | `atlas` | Atlas | portfolio coordinator: delegates, cross-checks sites, declares readiness, asks the owner | `INKBOX_IDENTITY_ATLAS` |
| 3 | `warden:<siteId>` | Warden · <site name> | site agent: resolves, verifies, signs for one site | `INKBOX_IDENTITY_WARDEN_HARBOR_WORKS` etc. |
| 4 | `runner` | Runner | field agent: reaches employees and contractors by SMS, email and call, collects evidence | `INKBOX_IDENTITY_RUNNER` |

Wherever the addendum below says coordinator/site/field it means Atlas/Warden/Runner.

## Simulation

`STEWARD_SIMULATION=true` (default true in local dev, documented) runs `backend/src/simulate.py` as a background thread (only with start_workers): every 20 s a sensor reading for each sensor-kind asset on every site (source `sensor`, ref `sim:<tag>`), every 2 min one plausible event on a non-demo site chosen from: a reading drifting out of range (creates an issue), a patrol identity fact, a short Atlas→Warden A2A status task that completes by itself, an expired work item escalation. Every simulated record carries `simulated: true` and the dashboard labels it. The demo site `harbor-works` gets only the sensor readings, never fabricated work items or verdicts, so the live demo is untouched. `GET /api/simulation` reports on/off and counts; `POST /api/simulation {enabled}` toggles it (actor operator).

## Environments

| id | name | kind | source | notes |
| --- | --- | --- | --- | --- |
| harbor-works | Harbor Works | `fixture` | Three.js twin from `shared/scene.json` | the demo site, 24 tagged assets |
| myer-plant | Myer Plant Room | `splat` | SuperSplat `66b655d3`, iframe `https://superspl.at/s?id=66b655d3`, thumbnail `https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/66b655d3/v1/xl.webp` | Gaussian splat of an industrial plant room, captured with a portal camera by its author |
| bristol-pumps | Bristol Dock Machine Room | `splat` | SuperSplat `8a8ce192`, iframe `https://superspl.at/s?id=8a8ce192`, thumbnail `.../splat/8a8ce192/v1/xl.webp` | 1907 pump room under restoration |

Backend seed renames the properties (name, address → "site", jurisdiction → "operator", phase → "status" with industrial values: "operational", "restart pending", "under restoration") and adds `environment: {kind, splatId?, embedUrl?, thumbnailUrl?, credit, captureNote}` to each property record; existing databases are migrated in place. `captureNote` for splats: "Scene rendered from a third-party capture hosted on SuperSplat; shown here as the site environment." No claim that we captured it.

Splat sites keep the same 24-asset register (tags, kinds, specs) so facts, work items and verification work identically; each asset additionally gets `pin: {x, y}` as a normalised 0..1 position on the environment viewer for 2-D overlay pins (seeded with plausible values, documented as approximate).

Issues for an environment = open work items in `needs_clarification`/`escalated`/`expired`, latest facts outside spec range, rejected verdicts in the last 24 h, assets with no identity fact. `GET /api/properties/{id}/issues` → `Issue[] {id, assetTag, componentId, kind: 'out_of_range'|'rejected_evidence'|'overdue'|'unknown_identity'|'escalated', severity: 'low'|'medium'|'high', summary, refId, pin, at}`.

## The four agents (managerial levels)

| level | id | name | identity handle env | authority (enforced in code) |
| --- | --- | --- | --- | --- |
| 1 | `operator` | Operator agent | none (external MCP requester) | start missions, set budgets, read everything; cannot write facts, dispatch, or decide |
| 2 | `atlas` | Atlas, portfolio coordinator | `INKBOX_IDENTITY_ATLAS` | delegate tasks to site agents, run cross-site checks, declare restart readiness, ask the owner; cannot attest, cannot dispatch people |
| 3 | `warden:<siteId>` | Warden, site agent (one per site) | `INKBOX_IDENTITY_WARDEN_<SITE>` | resolve/attest/sign for its own site only, delegate field work to the field agent; cannot touch another site, cannot exceed its budget, cannot decide safety |
| 4 | `runner` | Runner, field agent | `INKBOX_IDENTITY_RUNNER` | talk to employees and contractors by SMS, email and call, collect evidence and hand it to the site agent; cannot attest, cannot write facts |

Every mutating endpoint accepts the acting agent through header `X-Steward-Actor: <agent id>` (MCP passes `operator` unless the client is one of our agents). The backend checks the authority table and rejects with `{code: 'AUTHORITY_DENIED', recovery}` naming who may do it. `GET /api/agents` → `AgentInfo[] {id, level, name, role, handle?, status: 'idle'|'working'|'waiting', currentTask?, lastActivityAt, authority: string[]}`.

## Agent-to-agent (Inkbox A2A 1.0)

Transport `backend/src/a2a.py`: `A2ABus` with two transports behind one interface: `inkbox` when `INKBOX_API_KEY` and the handles exist (send via `identity.a2a_client()` → `send(target_card, text or parts, contextId?, taskId?)`; worker replies via `identity.a2a_reply(task_id, intent, parts)`; inbound via webhooks `a2a.task.created`, `a2a.task.message`, `a2a.task.canceled`, `a2a.sent_task.updated` on `/api/inbound/inkbox`; recovery by polling `a2a_tasks(state='submitted')` on start), and `local` otherwise (same envelope, in-process delivery, persisted identically). Every task is persisted as kind `a2a_task` `{id, contextId, caller, target, state, messages: [{role, parts, at}], transport, providerTaskId?, createdAt, updatedAt}` and every message emits a Change of type `a2a`. Task parts carry a structured `data` part `{steward: {missionId, siteId, assetTag?, attribute?, workItemId?, attestationId?, budget?}}` plus a text part humans can read.

Each identity advertises skills on its Agent Card via `a2a_set_skills` at startup when configured: Atlas `clear-site-for-restart`, `cross-site-check`; Warden `resolve-fact`, `attest-evidence`; Runner `dispatch-technician`, `collect-evidence`.

## Missions (the conversation the judges watch)

`POST /api/missions {siteId, goal: 'clear_for_restart', budget, requester}` (actor must be `operator`) → `Mission {id, siteId, goal, state: 'running'|'input_required'|'completed'|'failed', steps: MissionStep[], contextId, createdAt, updatedAt}`.

The coordinator runs it as a state machine (worker thread, checkpointed, resumable):

1. coordinator → site agent task: "resolve restart set for <site>": every attribute in the site's restart set (`pump.commissioning_certificate`, `pump.pressure_bar`, `valve.position`, `panel.status`, `fire.pressure_ok`, `door.closed`) with the mission budget.
2. site agent resolves each; known ones reply `progress` with attestation IDs; unknown ones → site agent → field agent task "collect <attribute> for <tag>" → field agent dispatches (existing dispatch path, SMS/email/local) and waits.
3. inbound evidence → field agent hands it to the site agent (task reply with the evidence ref) → site agent runs verification → attest → replies `complete` with the attestation ID, or `progress` with the rejection reason and keeps waiting.
4. coordinator `check`s every attestation; if a reading is out of range it opens a cross-site task to the other site agents ("verify your <tag> serial / reading") and marks the mission `input_required`, sending the owner one question (existing owner-decision path).
5. coordinator replies to the operator's mission with `completed` and a restart checklist `{assetTag, attribute, value, attestationId, valid}` or `failed` with what is missing.

`GET /api/missions/{id}`, `GET /api/missions?siteId=`. MCP tools (added later by the MCP stream): `start_mission`, `get_mission`, `list_agents`, `get_transcript`.

## Transcripts

`GET /api/agents/{agentId}/transcript?since=0&limit=200` → `TranscriptEntry[] {id, agentId, at, kind: 'a2a'|'sms'|'email'|'imessage'|'call'|'mcp'|'decision'|'system', direction: 'in'|'out', counterpart, text, parts?, audioUrl?, refs: {missionId?, taskId?, workItemId?, attestationId?}}`. Call entries carry the Inkbox transcript entries as text and `audioUrl` when a recording URL is present. MCP calls by the operator are logged as `mcp` entries with tool name and compact args.

## Evals

`POST /api/evals/run {suite: 'demo-workflow'}` spawns `node evals/run.mjs --json --mcp <local mcp url> --backend <self url>` with the project-local Node 24 (`agent-runtime/node_modules/node/bin/node`), stores `EvalRun {id, suite, startedAt, finishedAt, passed, failed, steps: [{name, target, result, ms, detail}]}` as kind `eval_run`, emits a Change. `GET /api/evals` lists runs newest first, `GET /api/evals/{id}` one run. Local only; refuses when the MCP URL is not loopback. Armature runs are linked by URL only (no API call) through `armature/README.md`.

## Dashboard (frontend, `/app`)

Three top-level sections in a left nav, each a route: `/app/environment`, `/app/agents`, `/app/evals`; `/app` redirects to environment. Site switcher in the header. No residential words anywhere.

- **Environment**: for `fixture` sites the Three.js twin; for `splat` sites the SuperSplat iframe (`embedUrl`, allow fullscreen, loading state, credit line and `captureNote` under it) with a 2-D pin layer over the viewer for issues (`pin` positions, labelled approximate), an issues list beside it (from `/issues`) that highlights the pin, and a "capture frames" strip under the viewer: `thumbnailUrl` plus frames the frontend captured from the viewer at different camera angles (saved under `frontend/public/env/<id>/`), captioned "frames rendered from the hosted capture". Work items, facts and attestations panels stay (from the current rail), reorganised under the viewer.
- **Agents**: four cards in level order with status, current task and handle; selecting one opens its transcript (from `/transcript`) as a chat-style log with direction, counterpart and refs; a "Listen" control reads the selected entry or the whole transcript aloud with the Web Speech API (`speechSynthesis`, stop control, reduced-motion unaffected), and an `<audio>` player when `audioUrl` exists. A mission panel: start a mission (demo control, actor operator), live mission steps, the A2A task graph as a vertical list coordinator → site → field with task states.
- **Evals**: list of runs with pass/fail counts, a run detail table (step, target, result, ms, detail), a "Run demo workflow" control (demo control), and a link to the Armature dashboard URL from env `NEXT_PUBLIC_ARMATURE_URL` when set.
