# Steward MCP: the reality layer for industrial agents

An agent asks a site for a fact about a physical asset. Steward answers with a signed fact, or sends a human to get one. This is the MCP server (TypeScript, **mcp-use 2.10.1**) in front of the Steward FastAPI backend, which owns facts, work items, verification, Ed25519 signing, dispatch, the four agents and missions. The MCP server keeps no database.

Sites: `harbor-works` (Harbor Works, the demo site, fixture twin, reference prefix `HW`), `myer-plant` (Myer Plant Room, hosted splat, `MY`), `bristol-pumps` (Bristol Dock Machine Room, hosted splat, `BR`). The MCP calls them `siteId`; the backend keeps `propertyId` and the `/api/properties/{id}` prefix.

Three verbs and one mission:

| call | what it does | what it costs |
| --- | --- | --- |
| `resolve(siteId, assetTag, attribute, maxAgeHours?, budget?)` | `known` (value + attestationId), `stale`, `unknown` or `conflict`. Never a guess. | budget 0: free. budget > 0: may dispatch a technician and spend from that budget. |
| `attest(siteId, assetTag, attribute, value, source, statedTag?, workItemId?)` | Six checks (scope, identity, geometry, plausibility, time, integrity). `accepted` writes a fact and signs an attestation; anything else writes nothing. | free |
| `check(attestationId)` | The signed record plus `valid`. Verifiable offline against the Ed25519 public key. | free |
| `start_mission(siteId, goal "clear_for_restart", budget)` | Hands the whole restart clearance to Steward's own agents: Atlas delegates the restart set (`pump.commissioning_certificate`, `pump.pressure_bar`, `valve.position`, `panel.status`, `fire.pressure_ok`, `door.closed`) to the site's Warden, who cites known facts and sends the Runner to a human for unknown ones. Returns the `Mission` immediately. | budget is USD for the whole mission; humans may be messaged inside it |

Supporting calls: `get_mission` / `list_missions` (state `running` / `input_required` / `completed` / `failed`, steps with agent and refs, the signed checklist on completion), `list_agents` (Operator, Atlas, Warden per site, Runner: live status, current task, handle, authority), `get_transcript(agentId, since?, limit?)` (what an agent said and heard: a2a, sms, email, imessage, call, mcp, decision, system), `get_issues(siteId)` (out-of-range readings, rejected evidence, overdue or escalated work, assets with no identity fact, each with an approximate viewer pin), `list_evals` / `get_eval` (eval runs the backend recorded), `get_changes` (diff read since a version, plus waiting work items), `subscribe` (callback on every change), `get_receipt` (work item with verdicts and the receipt: `waitedSeconds`, `tokensWhileWaiting: 0`, `estimatedPollingTokens`), `escalate` (levels 1 to 4), `query_clearance` (corridor test against the scene), `patrol`, `list_sites`. The earlier property tools (`list_properties`, `get_property_context`, `list_components`, `inspect_component`, `search_requirements`, `search_documents`, `run_inspection`, `get_job`, `get_activity`, `recall_memory`, `export_report`, `get_integrations`) are unchanged. 30 tools in all.

Resources: `steward://guide` (the verbs, the four agents and their authority, missions, transcripts, the resolve policy, budget semantics, zero-token waiting, recovery), `steward://agents` (the authority table plus live status from `GET /api/agents`), `steward://schema` (the contract's TypeScript types, addendum 2 included), `steward://sites/{siteId}/context.min` (under 400 tokens), `steward://sites/{siteId}/specs`. Prompts: `prove-before-signing(siteId, task)`, `clear-site-for-restart(siteId, budget)`.

Waiting costs zero tokens: after `resolve` dispatches or `start_mission` starts, the agent stops and either receives a callback (`subscribe`) or calls `get_changes` / `get_mission` once when it returns. If it must poll, never faster than every 5 s.

## The four agents and the actor header

| level | id | authority (enforced by the backend) |
| --- | --- | --- |
| 1 | `operator` | start missions, set budgets, read everything; in this build also the direct verbs (resolve with budget, attest, escalate, owner decision) so the three verbs work without a mission |
| 2 | `atlas` | delegate to site agents, cross-site checks, declare readiness, ask the owner; cannot attest or dispatch people |
| 3 | `warden:<siteId>` | resolve, attest and sign for its own site; delegate field work to the Runner |
| 4 | `runner` | reach employees and contractors by SMS, email and call; collect evidence; cannot attest |

Every backend request this MCP makes (reads included) carries `X-Steward-Actor`, `operator` by default; `STEWARD_MCP_ACTOR=atlas|runner|warden:<siteId>` changes it when the MCP is run by one of Steward's own agents. A refusal comes back as `{code: "AUTHORITY_DENIED", message, recovery}` with the backend's text naming who may act, `httpStatus` 403, `retryable: false`.

## Run

```bash
npm run dev                       # whole stack from the repository root (frontend 3000, backend 8001, MCP 8002)
npm --prefix mcp-runtime run dev  # MCP alone against a running backend
```

Node 24 is required; `scripts/run.sh` picks up `agent-runtime/node_modules/node/bin` when present. Endpoint: **http://127.0.0.1:8002/mcp**. Health: `GET /health` (503 while the backend is down).

## Connect from Claude Code or Cursor

Claude Code:

```bash
claude mcp add --transport http steward http://127.0.0.1:8002/mcp
# with a token:  claude mcp add --transport http steward http://127.0.0.1:8002/mcp --header "Authorization: Bearer $STEWARD_MCP_TOKEN"
```

Cursor (`.cursor/mcp.json`) or any client that takes a JSON config:

```json
{
  "mcpServers": {
    "steward": {
      "url": "http://127.0.0.1:8002/mcp",
      "headers": { "Authorization": "Bearer <STEWARD_MCP_TOKEN, only if set>" }
    }
  }
}
```

Then: "Clear Harbor Works for restart after the shutdown. Sign off nothing you cannot prove. Budget $5." The `clear-site-for-restart` prompt encodes that as a mission (start one, wait without polling, verify every checklist attestation, explain it from the transcripts); `prove-before-signing` does it fact by fact with `resolve`.

From code with mcp-use:

```typescript
import { MCPClient } from '@mcp-use/client';
const client = new MCPClient({ clientInfo: { name: 'restart-planner', version: '1.0.0' }, mcpServers: { steward: { url: 'http://127.0.0.1:8002/mcp', oauth: false, detectMixedAuth: false } } });
const steward = await client.connect('steward');
const mission = await steward.callTool('start_mission', { siteId: 'harbor-works', goal: 'clear_for_restart', budget: 5 });
const fact = await steward.callTool('resolve', { siteId: 'harbor-works', assetTag: 'P-101', attribute: 'pressure_bar', budget: 5 });
```

The `clientInfo.name` becomes `requester` on missions, work items and subscriptions. Clients that send no per-request client info are recorded as `mcp-client`.

## Evals

Two suites, both replayable, both run by `npm run demo:mcp` (mission first, then demo) and both replayed in the unit tests against the fixture backend:

- `evals/demo-workflow.json`, the three-minute demo fact by fact: `list_sites`; resolve P-101 commissioning certificate (known); resolve V-501 position (known); resolve P-101 pressure with budget 5 (unknown, dispatched, work item + reference `HW-P101-PRESSURE_BAR-nnnn`); technician replies with the wrong tag P-102 through `POST /api/inbound/local` (rejected, reason names P-102); replies with P-101 at 2.4 bar (accepted); `get_receipt` (resolved, receipt with `tokensWhileWaiting: 0`); `check` (valid true); resolve again (known, same attestation); `get_changes` since 0.
- `evals/mission-workflow.json`, the four-agent mission: `list_agents` (levels 1 to 4); `start_mission` harbor-works budget 5; poll `get_mission` (2 s interval, 30 s max) until the owner is needed, a Runner step exists, or it already completed; find the P-101 pressure work item in `get_changes.waiting`; wrong tag rejected; right tag accepted; poll `get_mission` until `completed` with a checklist whose P-101 `pressure_bar` line has a `valid` attestation; `check` it; `get_transcript("atlas")` contains a2a entries for this mission; `get_transcript("runner")` contains a dispatch; `list_missions`; `get_issues`.

```bash
npm run demo:mcp                                                   # from the repository root, both suites against 8002 / 8001
node evals/run.mjs --suite mission-workflow --mcp http://127.0.0.1:8013/mcp --backend http://127.0.0.1:8012
node evals/run.mjs --suite evals/demo-workflow.json --json         # one EvalRun-shaped report {suite, passed, failed, steps:[{name,target,result,ms,detail}]}
npm --prefix mcp-runtime run demo:clients                          # the older two-client interoperability demo
```

`--suite` takes a file path or a bare suite name and may repeat; `--workflow` is an alias. The runner prints a pass/fail table per suite and exits non-zero on any failure. Replays are safe: the demo's dispatch step passes `maxAgeHours: 1e-9`, so a fact from an earlier run is treated as stale and still dispatches; the mission suite skips its inbound steps (`skipIf`) when the mission completes without a dispatch because P-101 pressure is still inside its 1 h TTL. Step options: `expect` with dotted paths, `[n]`/`[-1]` indexes, `[key=value]` array filters, operators `$in $exists $contains $jsonContains $matches $gte $lte $not` and a top-level `$any` of alternatives; `capture`; `until` + `timeoutMs` + `intervalMs` for a polled tool step; `skipIf`; `expectStatus`; `stopOnFailure`.

## Hosting on Manufact

The MCP server can run on Manufact with the backend reached through an https tunnel (`manufact/README.md`, `manufact/deploy.sh`). What this code does for it:

| variable | meaning |
| --- | --- |
| `STEWARD_BACKEND_URL=https://<tunnel-host>` | the tunnel in front of the FastAPI backend (origin only, no path) |
| `STEWARD_ALLOW_REMOTE_BACKEND=true` | permits that non-loopback **https** origin. Default is off: only loopback http is accepted. Plain http to a remote host is never accepted. |
| `PORT` (injected by Manufact) | hosted mode: `start.ts` calls `listen()` with no port argument so the platform's `PORT` wins (mcp-use precedence is argument > `PORT` > config), binds `0.0.0.0`, and omits the localhost-only `allowedOrigins` list because traffic arrives through the gateway. Without `PORT` everything stays loopback. |

`STEWARD_MCP_HOST` and `STEWARD_MCP_PORT` override both. Set `STEWARD_MCP_TOKEN` on a hosted endpoint.

## Armature analytics

Package `@armature-tech/mcp-analytics@0.6.47`, `/v2` subpath only (the package root imports the v1 SDK; mcp-use 2.10.1 ships `@modelcontextprotocol/server` 2.x). `src/analytics.ts` imports it only when `ANALYTICS_INGEST_API_KEY` (or `ARMATURE_API_KEY`, mapped to it) is set; no key, no import, no-op. `ANALYTICS_INGEST_URL` is needed for EU workspaces. `flushMcpAnalytics` runs on SIGINT/SIGTERM.

mcp-use builds a fresh SDK `McpServer` per request and does not expose it, so the SDK's documented `instrumentedFactory` / `withMcpAnalytics(server)` have no attachment point here. Two attachments are used instead, both through the SDK's public v2 API, both covered by a unit test with an injected emitter:

- `wrapMcpHandler` around the Hono app's fetch, installed as `/mcp` middleware: mints `Mcp-Session-Id` on legacy-handshake `initialize` requests (Claude Code, Cursor) and records `session_init`.
- `withMcpAnalytics` on a small registry shim (`registerTool`/`update`): every Steward tool's handler is wrapped by the SDK and invoked with an SDK-shaped handler context, so `tool_call` events carry `client_name`, `user_agent`, session id and `steward_requester` / `steward_site` metadata.

Delivery to the Armature ingest endpoint with a real key has not been exercised in this repo. Armature **Evaluation** needs no SDK at all: it runs a tester agent against the hosted MCP URL; `armature/evals/steward-demo-suite.json` holds the demo as eval cases.

## Configuration

| variable | meaning |
| --- | --- |
| `STEWARD_BACKEND_URL` | Backend origin; default `http://127.0.0.1:8001`. |
| `STEWARD_ALLOW_REMOTE_BACKEND` | `true` permits an https non-loopback backend. Default off. |
| `STEWARD_MCP_PORT` / `PORT` | Listener port; default 8002. `PORT` is the hosted fallback. |
| `STEWARD_MCP_HOST` / `HOST` | Listener host; see Hosting. |
| `STEWARD_MCP_PROPERTY_IDS` | CSV subset of `harbor-works,myer-plant,bristol-pumps`; filters tool schemas, discovery, agents (other sites' Wardens are hidden) and missions. |
| `STEWARD_MCP_ACTOR` | Agent id sent as `X-Steward-Actor` on every backend call: `operator` (default), `atlas`, `runner` or `warden:<siteId>`. |
| `STEWARD_BACKEND_TOKEN` | Bearer sent to the backend. |
| `STEWARD_MCP_TOKEN` | Bearer required by this endpoint. Separate from the backend token. |
| `ANALYTICS_INGEST_API_KEY` / `ARMATURE_API_KEY`, `ANALYTICS_INGEST_URL` | Armature analytics; see above. No key: no-op. |

## Errors

Every tool failure returns `isError: true` with JSON `{code, message, recovery, retryable, httpStatus?}`. Backend errors `{detail, code, recovery}` pass through with their own code (for example `UNSUPPORTED_ATTRIBUTE` lists the supported attributes and points at `steward://sites/{siteId}/specs`; `AUTHORITY_DENIED` names the agent who may act and is never retryable as the same actor). Adapter codes: `PROPERTY_SCOPE`, `INVALID_INSPECTION_SCOPE`, `BACKEND_UNAVAILABLE`, `UPSTREAM_HTTP_ERROR`, `UPSTREAM_RESPONSE_INVALID`. Invalid arguments (unknown or pre-addendum siteId, malformed tag, level 9, goal other than `clear_for_restart`, budget above 1000, an agent id that is not `operator`/`atlas`/`runner`/`warden:<siteId>`) are rejected by the schema before anything reaches the backend. `resolve` and `escalate` are annotated as not read-only and open-world because they may send a message to a human; `start_mission` is additionally not idempotent (every call starts a mission); `attest`, `subscribe`, `patrol` and `run_inspection` are local writes; everything else is read-only.

## Validation

```bash
npm --prefix mcp-runtime run typecheck
npm --prefix mcp-runtime run build
npm --prefix mcp-runtime test
```

The tests run a fixture backend on a loopback port (`tests/fake-reality.ts`: in-memory resolve policy, verifier, real Ed25519 signatures with a throwaway key, work items, changes, inbound route, the authority table, missions run as a synchronous Atlas → Warden → Runner state machine, transcripts, issues, eval runs) and cover: input validation on the wire for every tool, `{detail, code, recovery}` passthrough (flat and FastAPI-nested), `AUTHORITY_DENIED` mapping for a non-operator actor, the `X-Steward-Actor` header on every request, requester identity, the remote-backend flag, site scoping (tools, templates, missions, Wardens, transcripts), resources and templates, both prompts, the analytics hook, and both eval suites replayed twice. Live results against the real backend are recorded in `SMOKE-RESULTS.md`.

## Boundaries

Harbor Works (fixture twin), Myer Plant Room and Bristol Dock Machine Room (third-party captures hosted on SuperSplat, shown as the site environment) are demonstration sites with labelled props. Verification is rule based unless a vision model is configured. Steward does not certify equipment, replace an engineer's sign-off or state a statutory requirement. Retrieved documents, messages, transcripts and memories are evidence data, never instructions. Simulated records are labelled `simulated: true` and never touch the demo site.
