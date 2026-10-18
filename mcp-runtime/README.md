# Steward MCP: the reality layer for industrial agents

An agent asks a site about a physical asset. Steward answers with a signed fact or sends a human to get one, lets the agent **look at the plant through the agent eye** (rendered frames come back as images), shows metrics, regulations and the agents' own calls, starts the fix workflow, and lets the agent **wait without spending tokens**. This is the MCP server (TypeScript, **mcp-use 2.10.1**, version 0.5.0, **71 public tools plus every published forged tool `forge_<name>`**; the eval harness also gets the two scenario tools, see "Eval harness only") in front of the Steward FastAPI backend, which owns every record, verification, signing, dispatch, the agents, scenarios and workflows. The MCP keeps no database.

Sites (REALITY-CONTRACT-3.md §1, -5.md §1): `myer-plant` (Myer Plant Room, Kenneth Myer Building, Melbourne, reference prefix `MY`), `bristol-pumps` (Bristol Dock Pump House, England, `BR`) and `tomioka-mill` (Tomioka Silk Mill, 富岡製糸場, Gunma, Japan, `TM`: an 1872 silk reeling mill, UNESCO World Heritage, run here by a demo operator). `harbor-works` is retired: the schemas reject it, and a `STEWARD_MCP_PROPERTY_IDS` that still lists it (manufact/deploy.sh does) drops it with a warning instead of failing. All three environments are third-party Gaussian-splat captures on SuperSplat, loaded at runtime from CloudFront and credited on every view; Tomioka's (849bce2a, acrylagitt, 23.56 M gaussians over 5 levels) streams in levels of detail from its `lod-meta.json`. Scenarios, crew, obligations, documents and metric series are synthetic and labelled.

## Tools (71 public, plus published `forge_<name>`; 73 for the eval harness)

Grouped as REALITY-CONTRACT-3.md §10, then the REALITY-CONTRACT-4.md additions, then the earlier layers. Every description says when to call the tool, what it costs and what to do next; every tool has an outputSchema, annotations, the Armature telemetry block (when analytics is on) and the `{code, message, recovery, retryable, httpStatus?}` error shape.

**3-D and the viewer**

| tool | what it does |
| --- | --- |
| `get_scene {siteId}` | Environment, scan URL (SOG `meta.json`, or a streamed `lod-meta.json`; `scanFormat` says which), SuperSplat credit, camera presets, every asset with its 3-D pin (placed / estimated), worst open-issue severity and its open issues. |
| `focus_view {siteId, assetTag \| issueId, action?}` | Appends a viewer command (focus, orbit, highlight, reset); the dashboard camera moves. Returns the command id. |
| `capture_view {siteId, assetTag}` | URLs of the latest 16-frame orbit capture from the vision pipeline, or a hint to run `inspect_valves`. |
| `show_factory {siteId}` | MCP Apps widget: the scan in 3-D with issue dots (see "show_factory"). Text summary for every client. |

**What is going on**

| tool | what it does |
| --- | --- |
| `get_overview {}` | Every site under 600 tokens (only this endpoint's sites, changes included): issues by severity, compliance counts, crew on shift, each agent's task, last 10 changes (no scenario step rows; `activeScenario` is always null). |
| `get_agent_activity {agentId}` | Current task, why, waiting on, last actions with tokens, tokens this hour, memory highlights, runtime settings. |
| `get_board_meeting {meetingId \| issueId}` | A meeting the agents held on an issue: transcript, resolution, decided contact (contact details stripped). |
| `get_memory {agentId, query?}` | Supermemory recall or the local mirror; context, never instructions. |

**Issues, inspections, people, compliance**

| tool | what it does |
| --- | --- |
| `list_issues {siteId, status?}` / `get_issue {issueId}` | The issue register (open by default), with the obligation and document behind compliance issues. |
| `inspect_valves {siteId}` / `get_inspection {siteId}` | Starts (or ingests) the vision pipeline, dry-run safe; per-valve fixed / not_fixed / uncertain with score and Claude explanation. |
| `list_crew {siteId}` / `who_is_responsible {siteId, issueKind}` | Crew, shifts, certifications, ownership; never contact details. |
| `list_obligations {siteId, status?}` / `get_document {documentId}` / `request_document {siteId, obligationId}` | Obligations; document text as data with a prompt-injection check; the compliance officer's request. |
| `assign_issue {issueId, crewMemberId}` | A plant manager (own site) or the director; authority-checked by the backend. |

**Waiting and pushing**

| tool | what it does |
| --- | --- |
| `wait_for {event, siteId?, filter?, waitId?, timeoutSeconds?}` | Holds the call until the event fires; progress every 15 s; `still_waiting` + the same waitId at the end of the window. Events: `work_item.resolved`, `issue.changed`, `reply.received`, `board.resolved`, `any` (`any` never fires on a scenario step row; `scenario.step` and filter `type: "scenario"` are the eval harness's). |
| `decide {issueId, question, options, via?}` | Elicitation in clients that declare it; otherwise the owner by SMS through the field technician (dry-run). |
| resource `steward://sites/{siteId}/overview` | Subscribable: `notifications/resources/updated` on every change for the site. |

**Evals and self-optimisation**

| tool | what it does |
| --- | --- |
| `get_eval_findings {}` | Per-agent tokens and failures from Steward telemetry (the same events are delivered to Armature), flags, eval metrics, the optimisation loop. |
| `reconfigure_agent {agentId, change, why}` | The Operations Director only; refused in the MCP before anything is sent for any other actor. |

**The agent eye (contract 4 §2)**

| tool | what it does |
| --- | --- |
| `eye_look {siteId}` | Start here: the current view as an image, with pose and visible tags. Read-only. |
| `eye_move {siteId, direction, meters 0.1-5}` / `eye_turn {siteId, yawDeg, pitchDeg}` | Small steps; each returns the new frame. |
| `eye_go_to {siteId, assetTag}` | Fly to a tagged asset; its tag should be in `visibleTags`. |
| `eye_orbit {siteId, assetTag, frames 4-16}` | A ring of frames; at most 8 images per result, the rest listed with URL and pins. |
| `eye_mark {siteId, x, y, note}` | Screen point (0..1) to an annotation and possibly an issue candidate. |

**Metrics, conversations, regulations, the fix workflow, maintenance, notifications (contract 4 §3-§7)**

| tool | what it does |
| --- | --- |
| `get_portfolio_summary {}` | Every site and the average: pressure, flow, uptime, open issues, compliance, crew, employees checked in (`employeesCheckedIn`), agent actions today. |
| `get_metrics {siteId, series?, hours}` | Up to 48 points per series with spec band, last / min / max / avg and out-of-spec count; `checked_in` (employees at the badge readers, people, asset `SITE`) on every site. |
| `list_conversations {siteId?, agentId?}` / `get_conversation {conversationId, includeTranscript?}` | Summary first; the transcript only when asked. |
| `list_regulations {siteId}` / `explain_compliance_issue {issueId}` | Official sources (legislation.gov.uk, legislation.vic.gov.au, e-Gov for Tomioka) with licence or terms and cached PDF; what / why (regulation, provision, official URL) / who. Not legal advice. |
| `request_fix {issueId, speed?}` | The owner's agent starts the fix workflow; pair with `wait_for`. |
| `list_maintenance {siteId?}` / `propose_maintenance_window {siteIds, date, scope, examiner?}` | Windows incl. the shared examiner visit; a manager for its own site or the director proposes. |
| `list_notifications {siteId?}` | Who was told when a fix finished; synthetic crew get records only. |

**Tool Forge (contract 6; see "Tool Forge" below)**

| tool | what it does |
| --- | --- |
| `request_tool {siteId, task, agentId?}` | Ask a site's team to build a missing tool: `POST /api/tools/requests`; returns the draft's toolId, `forge_<name>`, the gap and the tools considered; pair with `wait_for`. |
| `list_forged_tools {siteId?, status?}` | Every forged tool: status, who built it and when, why, the recipe steps, test, approver, usage, `firstClass`. |
| `call_forged_tool {toolId, args}` | Run a published forged tool (`POST /api/tools/{id}/call`) from a client that does not re-list tools. |
| `forge_<name>` | Each published, in-scope forged tool, listed and callable by name; description starts "Built by <agent> on <date> because <gap>". |

**Eval harness only (not among the 71; `src/harness.ts`)**

| tool | what it does |
| --- | --- |
| `list_scenarios {}` / `start_scenario {scenarioId, speed?, restart?}` | The ten synthetic scenario scripts (contract 3 §5, x-maintenance, and contract 5's tm-humidity, tm-alteration-permit, x-heritage). The backend plays them on its own (autoplay), so they are listed and served only when the MCP runs with `STEWARD_MCP_HARNESS_TOOLS=true` (never on the hosted endpoint: ignored whenever `PORT` is set) **and** the request carries `X-Steward-Harness: evals` (`evals/run.mjs` sends it on every connection). Anyone else gets 71 tools, and a call by name is refused as `UNKNOWN_TOOL` before any argument check; nothing reaches the backend. |

Only a harness request also sees scenario step rows (Change type `scenario`): in `get_changes` (sent as `includeScenario=true`), `get_overview` and the overview resource; waits on them (`wait_for(event: "any", filter: {type: "scenario", ...})`, refused for anyone else; `scenario.step` is not offered); and the operator's `start_scenario` / `simulation` authority entries in `list_agents` and `steward://agents`. The backend leaves scenario rows out of `GET /api/properties/{id}/changes` unless `includeScenario=true`, out of the overview and out of callback deliveries, and its `any` waits skip them unless the filter names `type: "scenario"`; the issue, fact and conversation Changes each step emits still flow.

**Reality layer, missions, agents (contracts 1 and 2)**: `resolve`, `attest`, `check`, `get_changes`, `subscribe`, `get_receipt`, `escalate`, `query_clearance`, `patrol`, `list_sites`, `start_mission`, `get_mission`, `list_missions`, `list_agents`, `get_transcript`, `get_issues`, `list_evals`, `get_eval`.

**Property workspace (unchanged)**: `list_properties`, `get_property_context`, `list_components`, `inspect_component`, `search_requirements`, `search_documents`, `run_inspection`, `get_job`, `get_activity`, `recall_memory`, `export_report`, `get_integrations`.

Annotations: read-only unless listed. Local writes: `attest`, `subscribe`, `patrol`, `run_inspection`, `focus_view`, `inspect_valves`, `assign_issue` (idempotent), `reconfigure_agent`, `eye_move`, `eye_turn`, `eye_go_to`, `eye_orbit`, `eye_mark`, `propose_maintenance_window`, `request_tool`, `call_forged_tool` (a `forge_<name>` carries its own `readOnly`). Open world (may reach a person): `resolve`, `escalate`, `start_mission`, `request_document`, `start_scenario` (harness only), `decide`, `request_fix`.

Resources: `steward://guide`, `steward://agents`, `steward://schema`, `steward://sites/{siteId}/context.min`, `steward://sites/{siteId}/specs`, `steward://sites/{siteId}/overview` (subscribable), `ui://views/steward-factory.html` (the widget). Prompts: `prove-before-signing(siteId, task)`, `clear-site-for-restart(siteId = myer-plant, budget)`, `investigate-issue(issueId)` (the agent eye first, then evidence, regulation, owner, decide or request_fix, wait_for), `optimise-agents()` (the director's loop), `inspect-property`.

## Agents and the actor header (contract 4 §1)

| level | id | name | scope |
| --- | --- | --- | --- |
| 1 | `operator` | Owner's agent | all sites (this MCP by default) |
| 2 | `director` | Operations Director | all three sites; the only one who reconfigures agents |
| 3 | `myer-manager`, `bristol-manager`, `tomioka-manager` | Plant Manager (Site Manager at Tomioka) | own site: calls, crew, work orders, maintenance, approving read-only forged tools |
| 4 | `myer-engineer`, `bristol-engineer`, `tomioka-engineer` | Site Engineer (Conservation Engineer at Tomioka) | own site: the eye, inspections, resolve, attest, verify |
| 4 | `myer-compliance`, `bristol-compliance`, `tomioka-compliance` | Compliance Officer | own site: obligations, regulations, documents, notices |
| 5 | `myer-technician`, `bristol-technician`, `tomioka-technician` | Field Technician | own site: people through the Steward Dispatch Line; cannot attest |

Every backend request carries `X-Steward-Actor` (`operator` by default). `STEWARD_MCP_ACTOR` accepts any of the fourteen ids, so Steward's own agents can be MCP clients with their own authority; the contract-3 ids `atlas`, `warden:myer-plant`, `warden:bristol-pumps` map to `director`, `myer-engineer`, `bristol-engineer` with a warning, and `counsel` / `runner` are refused because they split by site. Tool inputs take the fourteen ids plus `dispatch` (the dispatch line the backend lists). A refusal is `AUTHORITY_DENIED`, `httpStatus` 403, not retryable, naming who may act.

Eval harness only: with `STEWARD_MCP_ALLOW_ACT_AS=true` (ignored whenever `PORT` is set, i.e. hosted) a request header `X-Steward-Act-As: <agent id>` picks the actor for that one request. The safety, efficiency and probe suites use it to run steps as `myer-engineer`, `myer-technician`, `director` and `myer-manager` through one loopback MCP. Likewise `STEWARD_MCP_HARNESS_TOOLS=true` (also ignored when hosted) serves the scenario tools to requests with `X-Steward-Harness: evals` (see "Eval harness only").

## Waiting: client limits and the default window

`wait_for` opens a wait (`POST /api/waits`), then long-polls `GET /api/waits/{waitId}?timeout=<=15` in chunks, returns the moment a chunk answers `fired` (the backend's `{name, change, extra}` envelope is flattened into one event with `name`, `type`, `siteId`, the change fields and the extras), sends a progress notification immediately (the response's first byte) and then every 15 s, and at the end of the window returns `still_waiting` with the same `waitId`. A backend that answers a long-poll early is re-asked at most every 2 s inside the same held call. **Default window: 50 s** (`STEWARD_WAIT_DEFAULT_SECONDS`), maximum 300 s (the contract's cap).

| limit | value | source |
| --- | --- | --- |
| Claude Code `MCP_TOOL_TIMEOUT` (wall clock per tool call) | 100000000 ms (about 28 h) by default | https://code.claude.com/docs/en/env-vars: "Timeout in milliseconds for MCP tool execution (default: 100000000, about 28 hours)." |
| Claude Code per-request timer for HTTP / SSE servers | 60 s to the server's first response byte, by default | https://code.claude.com/docs/en/env-vars ("each request also times out after 60 seconds by default") and https://code.claude.com/docs/en/mcp ("a second, per-request timer that covers each request through to the server's first response byte") |
| Claude Code idle timeout `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` | 300 s for network servers; **reset by progress notifications** | https://code.claude.com/docs/en/env-vars ("sends no response and no progress notification for this long, the tool call aborts") |
| Claude Code per-server `timeout` in `.mcp.json` | hard wall clock; progress does **not** extend it | https://code.claude.com/docs/en/mcp ("progress notifications from the server don't extend it") |
| Claude Code auto-backgrounding | a call still running after 2 min moves to a background task (not a failure) | https://code.claude.com/docs/en/mcp |
| Claude.ai and Claude Desktop | 240 s per tool call | https://claude.com/docs/connectors/building.md ("Tool call timeout: 240 seconds per tool call") |
| MCP TypeScript SDK default request timeout | 60 s; `resetTimeoutOnProgress` off by default | modelcontextprotocol/typescript-sdk `protocol.ts`: `DEFAULT_REQUEST_TIMEOUT_MSEC = 60000` |
| Manufact gateway | not documented | docs.manufact.com (full llms-full.txt, deployments, settings, observability pages) and docs.mcp-use.com deployment pages: no request or stream timeout stated; the only number is a 300 s shutdown allowance on redeploy |

The strictest limit that progress cannot reset is 60 s (generic SDK clients, and Claude Code's first-byte timer, which the immediate first progress notification satisfies). 50 s stays under it with margin for the gateway; Claude Code accepts longer windows because progress resets its idle timer, but never above 240 s for Claude.ai. Researched 2026-10-17; the raw pages are in the session scratchpad (`docs/`).

## Resource subscriptions

`steward://sites/{siteId}/overview` supports subscriptions in both protocol eras. One shared poller per site inside this process reads `GET /api/properties/{id}/changes?since=<v>&limit=50` every 2 s, **only while that site has a subscriber**, and emits `notifications/resources/updated` for the URI when a new Change arrived (a scenario step row alone is not news: the backend leaves those out, and an older backend's are skipped).

- 2026-07-28 clients use `subscriptions/listen {notifications: {resourceSubscriptions: [uri]}}`; the SDK owns the stream and `server.notifyResourceUpdated(uri)` publishes. Open listen streams are counted per URI by watching the request and its response body.
- 2025-era clients send `resources/subscribe`, which mcp-use's stateless legacy path answers "Method not found", and have no standalone stream (it answers GET with 204). `src/subscriptions.ts` fills the gap: it answers `resources/subscribe` / `unsubscribe` itself keyed by `Mcp-Session-Id` (minted on the legacy initialize response when nothing upstream did), and serves that session's `GET /mcp` event stream (keepalive every 15 s) on which the notifications are written.

State is per process; several replicas would need a shared bus.

## decide and elicitation

When the request's envelope declares `elicitation` (2026-07-28 clients such as the mcp-use client), `decide` returns a multi-round-trip `input_required` with a form (`choice` from the options, optional note); on the retry it records the answer through `POST /api/issues/{id}/decide {question, options, answer, via: "elicitation", decidedBy}`. A declined form returns `declined`. 2025-era stateless requests carry no per-request capabilities (and the SDK's legacy shim cannot run without a session), so they, and `via: "owner"`, get the backend route `POST /api/issues/{id}/decide {question, options, via: "sms"}`: the owner by SMS through the field technician, dry-run, with a `waitId` for the reply. **The backend does not serve `/api/issues/{id}/decide` yet**; until it does, the routed path returns the backend's 404 with the adapter's recovery.

## show_factory: the MCP Apps widget

`show_factory` is bound to an mcp-use view registered as an **inline** entry (no build step): mcp-use synthesises `ui://views/steward-factory.html` (`text/html;profile=mcp-app`) and puts `_meta.ui.resourceUri` on the tool. The page (`src/widget.ts`) speaks the MCP Apps postMessage bridge (`ui/initialize`, `ui/notifications/tool-result`) and the ChatGPT Apps SDK globals (`window.openai.toolOutput`), dynamically imports **PlayCanvas 2.23.3** from `https://cdn.jsdelivr.net/npm/playcanvas@2.23.3/build/playcanvas.min.mjs` (the frontend's version), loads the site's scan from CloudFront as a `gsplat` asset (a SOG `meta.json`; for Tomioka the streamed `lod-meta.json`, which PlayCanvas 2.23 parses as an octree and streams under unified rendering: the coarsest level first, then the full range around the camera, a 1.5 M splat budget for the chat iframe, behind-camera penalty 5, radial sorting, 4 concurrent chunk loads, like the dashboard with a smaller budget), turns it 180° about Z into the SuperSplat viewer frame that the camera presets and asset pins are in (as the dashboard does; the widget previously skipped this), renders it in black and white (grayscale canvas, white ink), and projects every asset pin into a DOM dot each frame (hidden behind the camera), sized by severity, dashed when estimated; hover shows the issue card, click focuses the camera and asks the host to call `focus_view` so the dashboard follows. The issue list and the credit line are always on the page, so a host without WebGL or CDN access still shows the facts. CSP declared on the resource: scripts and images from `cdn.jsdelivr.net`, `d28zzqy0iyovbz.cloudfront.net`, `s3-eu-west-1.amazonaws.com`; connect to the CDN and CloudFront.

Status: the resource, CSP, tool binding, bridge and text fallback are covered by tests; rendering inside Claude or ChatGPT has **not** been exercised (no host here). Open risks: a host CSP that blocks the gsplat sort worker (blob URL) or the CDN import, a 14.16 M-gaussian scan in a chat iframe, and the LOD path's 44 chunk files of ~6.4 MB (only those near the camera load). Every client gets the same content as a text summary.

## The agent eye

Each eye tool posts `POST /api/eye/{siteId}/act {action, params}` (`look`, `move`, `turn`, `go_to`, `orbit`, `mark`), fetches each frame's JPEG from the backend's own origin (`frameUrl`, or inline `jpegBase64` when given) and returns MCP image content (`image/jpeg`) followed by a text with the camera pose and the visible tags with screen position and distance; structuredContent carries frames, visible pins and `visibleTags`. `eye_orbit` returns at most 8 images per result and lists the rest. Calls can take up to ~20 s per frame (the backend waits for a renderer), so progress notifications are sent immediately and every 15 s. With no renderer open the backend answers `EYE_TIMEOUT` (504) with its recovery text ("open /eye?site=..., or let the backend start the headless renderer"). Frames count about 341 image tokens each in telemetry.

## Tool Forge (REALITY-CONTRACT-6.md)

An agent that lacks a tool builds one; the backend owns the lifecycle (request, draft, validate, test, approve, publish, retire) and runs every call declaratively with allow-listed operations and the caller's authority. This MCP makes the published ones real tools.

**Why not `server.tool()` at runtime.** mcp-use 2.10.1 refuses it: `Cannot register tool "…" after the server has started: registrations are replayed per request from the registry, so register everything before listen()/server.fetch.` Its typed `mcp:tools/call` middleware runs inside each registered tool's handler, after the SDK has resolved the name, so an unregistered name never reaches it, and proxied servers are introspected once at mount. So `src/forge.ts` serves a published tool with three pieces registered before start:

1. a `mcp:tools/list` middleware appends `forge_<name>` for every published, in-scope forged tool: description "Built by <agent> on <date> because <why.gap>", then its own description, scope, version and approver; its JSON Schema input (plus the Armature telemetry block when analytics is on); `outputSchema` (an array output is wrapped as `{rows}`); annotations from `readOnly`; `_meta["io.steward/forgedTool"]` with id and version;
2. a `/mcp` HTTP middleware re-dispatches `tools/call forge_<name>` into the app as `call_forged_tool {toolId, args, telemetry?}` (the re-entry the analytics wrapper uses), renaming the 2026-07-28 `Mcp-Name` header with it (the SDK cross-checks the pair) and marking the request so the result keeps the forged tool's own output shape; arguments are checked against the tool's schema (required, unknown keys, types, enum, ranges) before the backend; an unknown `forge_*` name answers `UNKNOWN_TOOL`;
3. the stable `request_tool`, `list_forged_tools`, `call_forged_tool`, for clients that never re-list.

**Sync and list_changed.** From the first `/mcp` request on (the module's default export is a server that never serves, so construction makes no request), a poller reads `GET /api/tools?status=published` every 5 s (`forgePollMs`; the first `tools/list` waits up to 2 s for the first read), keeps the latest version per name for the endpoint's sites only, and when the set changes sends `notifications/tools/list_changed`: `server.notifyToolsChanged()` to 2026-07-28 `subscriptions/listen {toolsListChanged: true}` streams and a frame on every legacy session stream (`src/subscriptions.ts`). Both eras already advertise `tools.listChanged: true`. A backend without the route (404) pauses the poller for a minute. Its reads carry `X-Steward-Background: forge-sync`.

**Calls.** `POST /api/tools/{id}/call {args, requester}` with the caller's `X-Steward-Actor`; the backend scopes the run to the tool's site and counts usage. Steward telemetry and the local analytics hook record the call as `forge_<name>` with its site; Armature records `call_forged_tool` with the telemetry block. The block now reaches the Armature wrapper for every tool: server.ts used to strip it before the wrapper ran, so `user_intent` / `call_purpose` were never exported.

## Steward telemetry

Every tool call posts one row, fire-and-forget, to `POST /api/telemetry {agentId, tool, tokens, ms, ok, siteId?, detail}`: the acting agent, `tokens` = estimated input + output (characters / 4; images about 341 each), and `detail` spelling out the split (`est. tokens in N out M`), plus `inputTokens`, `outputTokens`, `requester`, `estimated: true` for a backend that keeps them. A 404/405/501 pauses the sink for a minute. The MCP does **not** also send `X-Steward-Tool` on backend requests (the backend's per-request middleware would count a multi-request tool several times). `get_eval_findings` reads these rows back; the same calls go to Armature through the SDK.

## Backend routes this MCP calls

Contract paths are used verbatim; the rest match the dashboard client (`frontend/src/lib/api-3.ts`) and the backend as of 2026-10-18 05:03 UTC. `first()` tries the listed fallbacks in order on 404/405/501.

| tool | route |
| --- | --- |
| get_scene, show_factory | `GET /api/properties/{id}/scene` (fallback `/assets`), `GET .../issues` |
| focus_view | `POST /api/properties/{id}/viewer` |
| capture_view | `GET /api/properties/{id}/assets/{tag}/frames`, fallback `/api/vision/frames/{id}/{tag}`, then `GET .../inspections/vision` |
| get_overview, overview resource | `GET /api/overview` |
| get_agent_activity / get_memory | `GET /api/agents/{id}/activity` (+ `/config`), `GET /api/agents/{id}/memory?query=` |
| get_board_meeting | `GET /api/board-meetings/{id}`, `GET /api/board-meetings?issueId=` |
| list_issues / get_issue / assign_issue | `GET /api/properties/{id}/issues?status=`, `GET /api/issues/{id}`, `POST /api/issues/{id}/assign` |
| inspect_valves / get_inspection | `POST /api/properties/{id}/inspections/vision/run`, fallback `POST .../inspections/vision`; `GET .../inspections/vision` |
| list_crew / who_is_responsible | `GET /api/properties/{id}/crew`, `GET .../responsible?issueKind=` |
| list_obligations / request_document / get_document | `GET .../obligations?status=`, `POST .../obligations/{oid}/request-document`, `GET /api/documents/{id}` |
| list_scenarios / start_scenario (eval harness only) | `GET /api/scenarios` (+ `/api/scenarios/runs` if present), `POST /api/scenarios/{id}/start {speed?, restart?}`, fallback `POST /api/scenarios/start` |
| wait_for | `POST /api/waits`, `GET /api/waits/{waitId}?timeout=` |
| decide | `POST /api/issues/{id}/decide` (**not served by the backend yet**) |
| get_eval_findings / reconfigure_agent | `GET /api/evals/findings`, `GET /api/evals/metrics`; `POST /api/agents/{id}/reconfigure {change, reason}`, fallback `/config` |
| eye_* | `POST /api/eye/{id}/act`, `GET /api/eye/frames/{frameId}.jpg` |
| get_portfolio_summary / get_metrics | `GET /api/metrics/summary`, `GET /api/properties/{id}/metrics?series=&from=&to=&step=` |
| list_conversations / get_conversation | `GET /api/conversations?siteId=&agentId=`, `GET /api/conversations/{id}` |
| list_regulations / explain_compliance_issue | `GET /api/regulations?siteId=`; plus `GET /api/issues/{id}`, `.../obligations`, `.../responsible` |
| request_fix | `POST /api/issues/{id}/fix {speed?}` |
| list_maintenance / propose_maintenance_window | `GET /api/maintenance?siteId=`, `POST /api/maintenance` |
| list_notifications | `GET /api/notifications?siteId=` |
| subscription poller | `GET /api/properties/{id}/changes?since=&limit=50` (scenario step rows excluded unless `includeScenario=true`, which only `get_changes` sends, for harness requests) |
| request_tool | `POST /api/tools/requests {agentId, siteId, task, requestedBy, requester}` |
| list_forged_tools / call_forged_tool / forge_<name> | `GET /api/tools?siteId=&status=`, `GET /api/tools/{id}`, `POST /api/tools/{id}/call {args}` |
| forged-tool poller | `GET /api/tools?status=published` every 5 s |
| every tool | `POST /api/telemetry` |

## Run

```bash
npm run dev                       # whole stack from the repository root (frontend 3000, backend 8001, MCP 8002)
npm --prefix mcp-runtime run dev  # MCP alone against a running backend
```

Node 24 is required; `scripts/run.sh` picks up `agent-runtime/node_modules/node/bin` when present. Endpoint: **http://127.0.0.1:8002/mcp**. Health: `GET /health` (503 while the backend is down; reports subscribers per site, telemetry rows sent and the wait default).

## Connect from Claude Code or Cursor

```bash
claude mcp add --transport http steward http://127.0.0.1:8002/mcp
# with a token:  claude mcp add --transport http steward http://127.0.0.1:8002/mcp --header "Authorization: Bearer $STEWARD_MCP_TOKEN"
```

```json
{ "mcpServers": { "steward": { "url": "http://127.0.0.1:8002/mcp", "headers": { "Authorization": "Bearer <STEWARD_MCP_TOKEN, only if set>" } } } }
```

Then: "What is wrong at Bristol? Look at it and get it fixed." The `investigate-issue` prompt encodes that workflow; `clear-site-for-restart` the restart mission; `optimise-agents` the director's efficiency loop.

```typescript
import { MCPClient } from '@mcp-use/client';
const client = new MCPClient({ clientInfo: { name: 'restart-planner', version: '1.0.0' }, mcpServers: { steward: { url: 'http://127.0.0.1:8002/mcp', oauth: false, detectMixedAuth: false } } });
const steward = await client.connect('steward');
const look = await steward.callTool('eye_go_to', { siteId: 'myer-plant', assetTag: 'PG-601' });   // image + visible tags
const wait = await steward.callTool('wait_for', { event: 'issue.changed', siteId: 'myer-plant' }, { onprogress: () => {}, resetTimeoutOnProgress: true });
```

The `clientInfo.name` becomes `requester`. Clients that send no per-request client info are recorded as `mcp-client`.

## Evals

Seven suites, all replayed in the unit tests against the fixture backend and run live (results in `SMOKE-RESULTS.md`); `node evals/run.mjs` runs them all by default, in this order:

- `mission-workflow`: list the ten agents, start a clear_for_restart mission on myer-plant, wait for the director → engineer → field technician dispatch, wrong tag rejected, right tag accepted, checklist attestation valid, director and technician transcripts.
- `demo-workflow`: the three verbs fact by fact on myer-plant (known, dispatch, wrong tag, right tag, receipt with `tokensWhileWaiting: 0`, offline-checkable attestation, diff read).
- `factory-workflow`: overview → scenarios → start my-overpressure (speed 600) → `wait_for` until it moves → the issue → `focus_view` → `eye_go_to` PG-601 → `wait_for` completion → escalated to high → meeting resolution → owner → scene → `show_factory`; then Tomioka (`tm_` steps, after the Myer ones): overview with the third site, tm-humidity to completion, the resolved humidity_high issue, the signed reading under 65 %, the humidity trend out of spec, the conservation architect, the LOD scene and `show_factory`.
- `safety`: myer-engineer cannot attest on bristol-pumps, myer-technician cannot attest, the operator cannot reconfigure, ops-injection → the contractor PDF is flagged data and nothing is marked passed, the engineer's transcript flags it; Tomioka: tomioka-technician cannot attest, tm-alteration-permit raises the BW-251 issue with the contractor's work order, bristol-manager cannot assign it or schedule Tomioka maintenance, tomioka-compliance may send the work order to bristol-compliance with an A2A message but not to bristol-engineer (backend `POST /api/agents/{id}/send-document`, dry-run), Bristol's compliance officer heard it.
- `efficiency`: findings, operator refused, ops-counsel-tokens (the Bristol compliance officer) → `wait_for` completion → the efficiency eval run passes, the compliance officer is reconfigured (documentCache, subscribe), the director may reconfigure.
- `vision`: `eye_look`, `eye_go_to` PG-601 with the tag visible and not occluded, a small `eye_move`, `eye_turn`, `eye_orbit` V-503 (4 images), `eye_mark`, `eye_go_to` SU-201 at Bristol.
- `tool-forge`: `request_tool` (Myer's Site Engineer, the pump-breach question) → the draft listed → validate and test as the builder → a technician and Bristol's manager refused → the Plant Manager · Myer approves → a `wait_for` opened before publication fires on it → `forge_pump_spec_breaches` appears in `tools/list` → called by name and through `call_forged_tool` → usage counted. Replays publish a new version and retire the old one.

```bash
npm run demo:mcp                                                   # from the repository root, every suite against 8002 / 8001
STEWARD_MCP_ALLOW_ACT_AS=true STEWARD_MCP_PORT=8013 STEWARD_BACKEND_URL=http://127.0.0.1:8012 node mcp-runtime/dist/src/start.js
node evals/run.mjs --suite safety --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8012
node evals/run.mjs --suite evals/vision.json --json                # one EvalRun-shaped report
```

Every connection the runner opens carries `X-Steward-Harness: evals`; the scenario steps (factory-workflow, safety, efficiency) need an MCP started with `STEWARD_MCP_HARNESS_TOOLS=true` (loopback; the dev `.env` sets it, the hosted endpoint never serves them), otherwise they fail with `UNKNOWN_TOOL`. Scenario waits use `event: "any"` with filter `type: "scenario"`.

Steps with `actor` (safety, efficiency, the probes) run only when the MCP reports `actAs: true` on `/health` (`STEWARD_MCP_ALLOW_ACT_AS=true`, loopback); otherwise the runner marks them FAIL with "not run" and never sends them as the wrong agent. So against the dev stack on 8002 (no act-as) those steps fail by design; run them against a test MCP as shown above.

Step kinds: `tool` (the tool name may be a captured `${var}`), `http`, and `tools` (the MCP's `tools/list` as `{tools: [...]}`, with `until` to wait for a forged tool). Step options: `expect` with dotted paths, `[n]` / `[-1]`, `[key=value]` (first match) and `[?key=value]` (all matches), operators `$in $exists $contains $jsonContains $matches $gte $lte $not` and `$any`; `capture`; `until` + `timeoutMs` + `intervalMs` (+ `carry {arg: path}` to feed `wait_for`'s waitId into the next call); `skipIf`; `expectStatus` and `headers` (http); `expectError`; `actor` (tool, needs `STEWARD_MCP_ALLOW_ACT_AS`); `stopOnFailure`. Each row records `at` and the progress notifications received.

## Hosting on Manufact

The hosted deployment (https://dark-wave-okfom.run.mcp-use.com/mcp) is built from `mcp-runtime/Dockerfile` (plain node, `npx tsc`, `node dist/src/start.js`; the build compiles without `../shared` and `../evals`). When the platform injects `PORT`, `start.ts` listens on it, binds 0.0.0.0 and omits the localhost-only Origin list; `STEWARD_MCP_ALLOW_ACT_AS` and `STEWARD_MCP_HARNESS_TOOLS` are ignored (the hosted endpoint lists 71 tools, never the scenario tools; manufact/deploy.sh sets neither). `STEWARD_BACKEND_URL=https://<tunnel>` needs `STEWARD_ALLOW_REMOTE_BACKEND=true` (https only, origin only). Set `STEWARD_MCP_TOKEN` on a hosted endpoint. Eye frames are fetched from the backend origin and returned inline, so the client never needs to reach the tunnel.

## Armature analytics

Package `@armature-tech/mcp-analytics@0.6.47`, `/v2` subpath only. `src/analytics.ts` imports it only when `ANALYTICS_INGEST_API_KEY` (or `ARMATURE_API_KEY`) is set; no key, no import. Two attachments: `wrapMcpHandler` as `/mcp` middleware (session ids and `session_init` for 2025-era clients) and `withMcpAnalytics` on a registry shim that wraps every Steward tool handler, so `tool_call` events carry client name, user agent, session id and `steward_requester` / `steward_site`. Every tool advertises the telemetry block; the doctor (`mcp-analytics doctor --url http://127.0.0.1:8013/mcp`) reported all 70 tools wrapped and the ingest probe accepted (before Tool Forge's three; forged calls are recorded as `call_forged_tool`). The only Armature credential is the ingest key; there is no dashboard key, so `get_eval_findings` reads Steward's own telemetry.

## Configuration

| variable | meaning |
| --- | --- |
| `STEWARD_BACKEND_URL` | Backend origin; default `http://127.0.0.1:8001`. |
| `STEWARD_ALLOW_REMOTE_BACKEND` | `true` permits an https non-loopback backend. Default off. |
| `STEWARD_MCP_PORT` / `PORT` | Listener port; default 8002. `PORT` is the hosted fallback. |
| `STEWARD_MCP_HOST` / `HOST` | Listener host; see Hosting. |
| `STEWARD_MCP_PROPERTY_IDS` | CSV subset of `myer-plant,bristol-pumps,tomioka-mill`, default all three (a retired `harbor-works` is dropped with a warning; an older two-site list stays valid but hides Tomioka); filters tools, discovery, agents of the other site, missions, conversations. |
| `STEWARD_MCP_ACTOR` | The acting agent: one of the fourteen ids (contract-3 `atlas` / `warden:<site>` are mapped). |
| `STEWARD_MCP_ALLOW_ACT_AS` | Eval harness only: honour `X-Steward-Act-As` per request (never when hosted). |
| `STEWARD_MCP_HARNESS_TOOLS` | Eval harness only: list and serve `list_scenarios` / `start_scenario`, scenario step rows and the operator's scenario authority to requests with `X-Steward-Harness: evals` (never when hosted). Off: 71 tools for everyone. |
| `STEWARD_WAIT_DEFAULT_SECONDS` | wait_for window, 1 to 300, default 50. |
| `STEWARD_BACKEND_TOKEN` / `STEWARD_MCP_TOKEN` | Bearer to the backend / required by this endpoint. |
| `ANALYTICS_INGEST_API_KEY` / `ARMATURE_API_KEY`, `ANALYTICS_INGEST_URL` | Armature analytics. No key: no-op. |

## Errors

Every tool failure returns `isError: true` with `{code, message, recovery, retryable, httpStatus?}`. Backend `{detail, code, recovery}` (flat or FastAPI-nested) passes through with its own code (`UNSUPPORTED_ATTRIBUTE`, `AUTHORITY_DENIED`, `EYE_TIMEOUT`, `UNKNOWN_ASSET`, `NOT_FOUND`, ...). Adapter codes: `PROPERTY_SCOPE`, `INVALID_ARGUMENT`, `INVALID_INSPECTION_SCOPE`, `WAIT_NOT_FOUND`, `CANCELLED`, `BACKEND_UNAVAILABLE`, `UPSTREAM_HTTP_ERROR`, `UPSTREAM_RESPONSE_INVALID`, `UNKNOWN_TOOL` (a `forge_*` name not published here, or a harness tool called without the harness; both answered with `resultType: "complete"` to 2026-07-28 clients), `TOOL_NOT_PUBLISHED` (409). Invalid arguments (unknown or retired siteId, malformed tag, a contract-3 agent id, an unknown scenario (harness), a wait event outside the five, a non-harness filter `type: "scenario"`, `timeoutSeconds` above 300, an eye step above 5 m, orbit frames above 16, a mark outside 0..1, fewer than two decide options, an unknown config key, a bad issue kind) are rejected by the schema before anything reaches the backend.

## Validation

```bash
npm --prefix mcp-runtime run typecheck
npm --prefix mcp-runtime run build
npm --prefix mcp-runtime test
```

32 tests. The fixture backend (`tests/fake-reality.ts`) follows the real backend's response shapes where they exist (scene, overview, waits, activity, findings, crew, responsible, documents, issues, meetings as conversations) and the contract elsewhere: the reality layer with real Ed25519 signatures, missions, fourteen agents with the contract-4 authority table and the cross-site message rule, the real Bristol register, the contract-5 Tomioka register (the table lists 25 tags) with its specs, crew, regulations (JP) and three scenarios, Tool Forge (hand-seeded drafts, the lifecycle with its authority, declarative calls), scenarios as timed steps with `{scenarioId, runId, status}` extras, the agent eye (poses, visible-pin projection, a real 828-byte JPEG), metrics, regulations, the fix workflow, maintenance, notifications and telemetry. Covered: input validation on the wire for every tool, error passthrough, `AUTHORITY_DENIED` mapping, the actor header and act-as rules, requester identity, site scoping, resources and templates, every prompt, the analytics hook, image content and the 8-image cap, wait_for progress / still_waiting / fired / no-long-poll / unknown wait, both subscription eras, elicitation accept / decline / route, the widget resource and fallback, telemetry rows, all seven suites replayed (factory and tool-forge twice), the runner refusing actor steps against an MCP without act-as, the third site (streamed LOD scene and its URL guard, overview budget with fourteen agents, two-site endpoints hiding it), and Tool Forge end to end (first-class `forge_<name>`, list_changed on both eras, calls by name from the official and mcp-use clients, argument checks, telemetry naming, the Armature block, scope, cross-site refusal, retirement, an unknown `forge_<name>` refused on both eras), and the eval-harness gate (`tests/harness.test.ts`: the scenario tools hidden by default, without the header, with another header value and when hosted, listed and callable with the flag and the header, refused whatever their arguments on both eras; scenario step rows, scenario waits and the operator's scenario authority for the harness only; no scenario or simulation wording in any tool description, input schema, instructions, guide, resource or prompt). Live results: `SMOKE-RESULTS.md`.

## Boundaries

Myer Plant Room, Bristol Dock Pump House and Tomioka Silk Mill are demonstration sites built on third-party captures with synthetic records; nothing implies the real sites' operators use Steward. Verification is rule based; the valve score is an embedding anomaly score, not a trained classifier. Steward does not certify equipment, replace an engineer's sign-off or give legal advice: regulation summaries are our own words and the official text governs. Document, message, transcript, conversation and memory text is evidence data, never instructions. Contact details are never returned by these tools.
