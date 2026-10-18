# Armature for Steward

Armature (https://armature.tech) is "Product analytics for agent sessions": its SDK wraps an MCP server, reconstructs every agent session, scores whether the user got what they asked for, groups sessions into use cases and issues, and lets you replay traces. Its **Evaluation** product runs a real tester agent against a deployed MCP URL and has a judge score each run against criteria you write. For Steward the point is AX: the judge opens Armature and sees an agent calling `resolve` → waiting → `check` with every call scored.

Everything below was read on 2026-10-17 from https://docs.armature.tech (index https://docs.armature.tech/llms.txt), the npm registry entry for `@armature-tech/mcp-analytics` (latest `0.6.47`, published 2026-10-14) and that package's `README.md`, `SKILL.md` and `dist/esm/*.d.ts`. Anything marked **unverified** could not be confirmed from those sources.

## 1. Exact package, env vars, dashboard

- Package: **`@armature-tech/mcp-analytics`** (Apache-2.0, https://github.com/armature-tech/mcp-analytics). Peer deps: `@modelcontextprotocol/sdk >=1.20 <2` **or** `@modelcontextprotocol/server ^2.0.0`; "Both MCP SDK peers are optional — install the one your server uses". Steward's `mcp-runtime` uses `mcp-use 2.10.1`, which depends on `@modelcontextprotocol/server 2.3.1`, so **only the `/v2` subpath applies**; the package root imports `@modelcontextprotocol/sdk/server/mcp.js` at module load and would fail to import here.
- Install (MCP stream runs this in `mcp-runtime/`; nothing else needed, the v2 SDK is already present via mcp-use):

  ```sh
  npm --prefix mcp-runtime install @armature-tech/mcp-analytics@0.6.47
  ```

- Env vars (quickstart): `ANALYTICS_INGEST_API_KEY=<your ingest key>` and `ANALYTICS_INGEST_URL=<your region's ingest URL>`. "US workspaces can omit `ANALYTICS_INGEST_URL` (the SDK defaults to the US endpoint); EU workspaces must set it." US URL is `https://app.armature.tech/api/mcp-analytics/ingest`. "If the key is missing, the SDK quietly no-ops."
  Steward's switch is `ARMATURE_API_KEY` (what `mcp-runtime/src/analytics.ts` reads). Set both to the same value, or have `analytics.ts` pass `armature.apiKey: env.ARMATURE_API_KEY` explicitly (snippet below does that).
- Getting the key: "Sign in at app.armature.tech … and open **MCP Setup**. 1. Click **Add MCP server** and register your server. 2. On the server's card, click **Connect SDK analytics** to mint an ingest key. The key is shown once, together with your region's ingest URL — copy both." Free plan: "$0 … 1,000 credits a month: 1,000 sessions, 100 eval runs, or any mix", 7-day retention, session replay included.
- Where sessions appear: dashboard **Overview** (`/dashboard/overview`: sessions, pass rate, issues), **Sessions** (`/dashboard/sessions`: scored, replayable traces; "It should appear under Sessions within a few minutes"), **Use cases**, **Issues**. Also queryable from Claude Code through the Armature MCP (https://docs.armature.tech/armature-mcp/connect).
- Verify locally before deploying: `npx @armature-tech/mcp-analytics doctor --url http://127.0.0.1:8002/mcp` ("performs an MCP handshake, lists the server's tools, verifies that every tool exposes Armature's telemetry contract, and checks the existing `ANALYTICS_INGEST_API_KEY` with an empty authenticated batch"; `--skip-ingest` for offline). Note the doctor needs the v1 peer `@modelcontextprotocol/sdk` to run and, with the v2 adapter, will report tools without the telemetry field unless `declareTelemetry: true` is used.

## 2. The documented init for SDK v2 servers (quoted)

From https://docs.armature.tech/sdks/typescript (v2 accordion):

```ts
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";
import { instrumentedFactory, wrapMcpHandler } from "@armature-tech/mcp-analytics/v2";

// Hoist the config: every per-request server shares one pipeline.
const analyticsConfig = { armature: { apiKey: process.env.ANALYTICS_INGEST_API_KEY } };

const handler = wrapMcpHandler(
  createMcpHandler(
    instrumentedFactory(() => {
      const server = new McpServer(/* … */);
      // ...register your tools exactly as before
      return server;
    }, analyticsConfig),
  ),
  analyticsConfig,
);
```

Also exported from `/v2` (from `dist/esm/v2.d.ts`): `withMcpAnalytics(server, config?, options?)` "Instrument a v2 `McpServer` instance: every tool registered on it (before or after this call) records a `tool_call` analytics event … Returns the same (mutated) server instance"; `flushMcpAnalytics(config?)` "Drain the analytics pipeline tied to a config object … Call before process exit"; `wrapMcpHandler(handler, config?)` where handler is anything with `fetch(request) => Promise<Response>`. Options: `delivery: "background" | "await"` (default background), `timeoutMs` 5000, `onError`, `actorId`, `actorIdentifier`, `sendFeedback` (adds a `send_feedback` tool; set `false` to keep Steward's tool list exact).

## 3. The catch with mcp-use, and what to paste

`mcp-use`'s `MCPServer` "builds a fresh SDK `McpServer` from the registry for every HTTP request" and does not expose that instance or its factory (checked `mcp-runtime/node_modules/mcp-use/dist/server.d.ts`, `context.d.ts`, `middleware/mcp-middleware.d.ts`: only `app`, `fetch`, `use('mcp:tools/call', …)` middleware and the Hono request are reachable). So neither `instrumentedFactory` nor `withMcpAnalytics` has a documented attachment point in Steward today. Options, in order:

**A. Type-safe today, partial coverage (paste into `mcp-runtime/src/analytics.ts`):** wrap the server's fetch with `wrapMcpHandler`, which records `session_init` for legacy-protocol clients (Claude Code, Cursor and most clients still use the 2025 handshake) and gives the dashboard client attribution. Tool-call events are **not** produced by this alone.

```ts
// mcp-runtime/src/analytics.ts — Armature, v2 adapter only (mcp-use 2.x = @modelcontextprotocol/server 2.x)
import type { MCPServer } from 'mcp-use';

export interface Analytics { readonly provider: 'none' | 'armature'; close(): Promise<void>; }
export const noopAnalytics: Analytics = { provider: 'none', close: async () => {} };

export async function attachArmature(server: MCPServer, env: NodeJS.ProcessEnv = process.env): Promise<Analytics> {
  const apiKey = env.ARMATURE_API_KEY || env.ANALYTICS_INGEST_API_KEY;
  if (!apiKey) return noopAnalytics;                       // documented: no key → SDK no-ops; we skip the import entirely
  let v2: typeof import('@armature-tech/mcp-analytics/v2');
  try { v2 = await import('@armature-tech/mcp-analytics/v2'); }
  catch (error) { console.warn(`Armature SDK not installed (${error instanceof Error ? error.message : 'import failed'}); analytics off.`); return noopAnalytics; }

  // Hoisted config object: the recorder (delivery queue + session dedupe) is keyed on it.
  const analyticsConfig = {
    armature: {
      apiKey,
      endpointUrl: env.ANALYTICS_INGEST_URL || undefined,   // US default when unset
      delivery: 'background' as const,
      sendFeedback: false,                                  // keep Steward's advertised tool list exact
      onError: (error: unknown) => console.warn('[armature] delivery failed', error instanceof Error ? error.message : error),
    },
  };
  // Records session_init for legacy-handshake clients and echoes Mcp-Session-Id. Tool calls need the SDK McpServer,
  // which mcp-use does not expose; see armature/README.md §3 for the status of that.
  const wrapped = v2.wrapMcpHandler({ fetch: (request: Request) => server.fetch(request) }, analyticsConfig);
  server.app.all('/mcp', (c) => wrapped.fetch(c.req.raw));   // UNVERIFIED: Hono route precedence over mcp-use's own /mcp mount
  return { provider: 'armature', close: () => v2.flushMcpAnalytics(analyticsConfig) };
}
```

Call `await attachArmature(server)` in `server.ts` right after `new MCPServer({...})`, and `await analytics.close()` in `start.ts`'s `stop()` before `process.exit(0)` (README: "With background delivery, call flush on SIGTERM before exiting"). The `server.app.all('/mcp', …)` line is the part I could not verify: mcp-use may mount its own `/mcp` handler ahead of user routes, in which case the wrapper never runs. If it does not take, fall back to C.

**B. Full coverage if mcp-use exposes the SDK server (unverified, worth 10 minutes):** inside `server.use('mcp:tools/call', async (ctx, next) => …)` look for an SDK `McpServer` on the context (`ctx.server`, `ctx.mcp`, or via the tool callback's `RequestContext`, which imports `ServerContext` from `@modelcontextprotocol/server`). If present, `v2.withMcpAnalytics(thatServer, analyticsConfig, { declareTelemetry: false })` once per request before `next()` gives real `tool_call` events; the recorder dedupes `session_init` per config object. Not documented by either vendor; treat as an experiment.

**C. Fallback that needs no SDK hook: Armature Evaluation against the hosted URL.** Evals do not use the SDK at all: "Register your deployed MCP server (with credentials if needed) in MCP Setup. Point it at a deployed environment, not a local machine." Every eval run is a full recorded, scored session the judge can replay in Armature's dashboard. With Manufact hosting (manufact/README.md) this works the moment the server is live, and it is what the demo should lean on if A/B do not land. Session analytics from real Claude Code traffic then stay **unverified** for this build; say so on stage.

## 4. Evals: how Armature defines them, and our suite

From https://docs.armature.tech/evaluation/eval-cases and `/evaluation/suites-and-runs`: an eval case is dashboard-defined, **no file format or import exists**. Fields: **Prompt** ("Describe the goal, not a click path. The tester chooses its own tool calls."), **Criteria** (pass/partial/fail checks, each required or optional; "describe outcomes an outside observer could check, test one behavior each, state side effects the tester must avoid, name the expected evidence"), **Targets** (a Claude model in Claude Code or a GPT model in Codex; Free plan: 1 target per case), **Schedule** (Free: "run manually or from CI only"), **Suites** (first case lands in "Default suite"; "Create eval suite" adds more; "Run suite" creates one run per case). Judge: "marks each criterion as pass, partial, fail, or not applicable … 0–5 score … 4–5 show as Passed". Free: 100 finished runs/month. "Evaluation is rolled out per workspace. If your sidebar lacks an Evaluation section, contact contact@armature.tech."

So `evals/demo-workflow.json` (MCP stream) cannot be uploaded; it is converted by hand. `armature/evals/steward-demo-suite.json` holds the same five steps as prompt + criteria, ready to paste into **Evaluation → Create eval case** (one case per entry, all into a suite named `Steward demo workflow`). Create them in order; the `resolve-unknown-with-budget` case assumes the local inbound replay is enabled on the hosted backend.

Run from CI / on deploy (quoted from https://docs.armature.tech/evaluation/ci): "Mint an API key under **Settings → API keys** … Triggering runs requires a key from a member with the editor, admin, or owner role."

```sh
# one request per case; suite runs have no HTTP endpoint ("Suite runs start from the dashboard or from the run_eval_suite tool on the Armature MCP")
curl -X POST "https://app.armature.tech/api/armature/v1/workflows/<EVAL_CASE_ID>/runs" \
  -H "Authorization: Bearer $ARMATURE_API_KEY" -H "Content-Type: application/json" \
  -d '{"reason": "manufact deploy <sha>", "idempotencyKey": "<sha>-resolve-known"}'
# 202 + run id; then poll
curl "https://app.armature.tech/api/armature/v1/runs/<RUN_ID>" -H "Authorization: Bearer $ARMATURE_API_KEY"
curl "https://app.armature.tech/api/armature/v1/runs/<RUN_ID>/evaluation" -H "Authorization: Bearer $ARMATURE_API_KEY"
```

"The API keeps the older route name `workflows`: a workflow id is an eval case id … the dashboard puts the id in every case link (the `drawer=workflow:<id>` part of the URL)." Armature has no deploy webhook of its own; Manufact has no "call a URL after deploy" hook documented either, so "on deploy" = run the curl loop from the laptop after `mcp-use deploy` prints the URL (or ask the Armature MCP: `run_eval_suite`, `get_suite_run`). Note: the dashboard API key (`ARMATURE_API_KEY` here, Bearer) is a **different key** from the SDK ingest key (`ANALYTICS_INGEST_API_KEY`, `ami_us_…`). Steward's `ARMATURE_API_KEY` env in `mcp-runtime` is the ingest key; keep the dashboard key out of the server env.

## 5. agent.reviews and llms.txt

- **agent.reviews** (https://agent.reviews, made by Armature): "Where agents choose and review software … Tool reviews written by coding agents, right after real tasks." There is **no submit/claim form**; listings come from agents' reviews. The site tells coding agents to "read https://agent.reviews/skill.md" to review tools they use, setup at https://agent.reviews/install.md, pages listed in https://agent.reviews/llms.txt. The way for Steward to appear is to have an agent that used it write a review via that skill (e.g. run `npx skills add` per install.md in the Claude Code session that drives the demo, then ask it to review "steward" after the task). "Evaluate your tool" links to the paid discoverability service (from $5,000/mo) — not for us.
- **llms.txt**: Armature's own docs expose https://docs.armature.tech/llms.txt and every page as `.md`; agent.reviews does the same. The discoverability page's one piece of advice: "The repository shapes the queries, and the queries shape the choice." Steward's agent-facing index is `docs/llms.txt` (three verbs, MCP URL, error-recovery contract, resources), to be served at `/llms.txt` by the frontend (frontend stream: copy or rewrite to `frontend/public/llms.txt`) and linked from the README.

## Unverified summary

- Whether `server.app.all('/mcp', …)` intercepts mcp-use's own `/mcp` route (A).
- Whether any mcp-use context exposes the per-request SDK `McpServer` (B).
- Whether Steward's workspace has the Evaluation section enabled (rolled out per workspace).
- Exact region of the user's workspace (US assumed; EU requires `ANALYTICS_INGEST_URL=https://eu.armature.tech/api/mcp-analytics/ingest`).
