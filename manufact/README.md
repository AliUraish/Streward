# Manufact for Steward

Manufact Cloud (https://docs.manufact.com) hosts MCP servers, puts a gateway in front of them (Sessions, Gateway Requests, analytics), runs Publish checks, offers a hosted Public Chat and one-click client connection. Steward's MCP server (`mcp-runtime`, a `mcp-use 2.10.1` TypeScript server) gets hosted there; it reaches the FastAPI backend on the laptop through the Inkbox tunnel URL (docs/INKBOX.md §4). The judge sees the server in Manufact's dashboard with live sessions from Claude Code during the demo.

Read on 2026-10-17 from https://docs.manufact.com (index https://docs.manufact.com/llms.txt), https://docs.mcp-use.com/v2/typescript/server/deployment/mcp-use.md, the mcp-use ServerConfig reference and the installed `mcp-use` type declarations. **Unverified** items are marked.

## Files here

| File | Purpose |
| --- | --- |
| `deploy.sh` | The exact `mcp-use deploy` command with Steward's flags and env. Prints the MCP URL. |
| `Dockerfile` | Fallback only: `node:24-slim` image (our `run.sh` refuses Node < 24; Manufact's default Node version is **unverified**). Point "Dockerfile path" at it if the auto build fails on the Node check. |

Manufact requires **no manifest file** in the repo for a Node project: "Node.js: detected from `package.json` plus a lockfile" and "By default, Manufact runs your `build` script (if present) and your `start` script." (`mcp-use build` writes a `dist/mcp-use.json` manifest for mcp-use-CLI projects; ours builds with `tsc`, so there is none and none is needed.) `.mcp-use/project.json` / `.mcp-use/cloud/link.json` are written by the CLI after the first deploy to link later deploys to the same server; keep whichever appears out of git until the user decides.

## Required code change (MCP stream, before deploying)

`mcp-runtime/src/start.ts` currently calls `server.listen(config.port, { host: '127.0.0.1' })`. From the installed mcp-use types: "port precedence is the argument, `PORT`, `config.port`, then `3000`; host precedence is `options.host`, `HOST`, `config.host`, then `127.0.0.1`" and "To serve publicly set `host: "0.0.0.0"`". An explicit argument therefore **overrides Manufact's `PORT`**, and `127.0.0.1` is unreachable from the gateway → "Health Checks" step fails ("usually points to a wrong start command or a missing environment variable"). Minimal change:

```ts
// start.ts: let PORT/HOST win when hosted; keep loopback defaults locally.
const hosted = Boolean(process.env.PORT);
const listener = await server.listen(hosted ? undefined : config.port, { host: hosted ? '0.0.0.0' : '127.0.0.1' });
```

Also in `server.ts`: `allowedOrigins` is a fixed localhost list. mcp-use: "When omitted, Origin validation is off (SDK-aligned)". Manufact's dashboard Chat/Inspector traffic arrives through its gateway; whether it carries a browser `Origin` is **unverified**. Safest: when `process.env.PORT` is set, omit `allowedOrigins` (gateway-fronted) and keep the list locally. And `config.ts` already accepts `STEWARD_ALLOW_REMOTE_BACKEND=true` for an https non-loopback backend (done).

## Deploy, step by step

**Prerequisite:** the tunnel is up and `https://<handle>.inkboxwire.com/api/health` (or any backend route) answers from the internet (docs/INKBOX.md §4). The hosted MCP calls the backend there.

**Option 1, CLI without GitHub (works tonight, before the repo is public):**

```sh
npx -y mcp-use@latest login            # browser login; `--device-code` on a headless shell
STEWARD_BACKEND_URL=https://<handle>.inkboxwire.com bash manufact/deploy.sh
```

`deploy.sh` runs `npx -y mcp-use@latest deploy --name steward --root-dir mcp-runtime --runtime node --build-command "npm run build" --start-command "npm start" --env STEWARD_BACKEND_URL=… --env STEWARD_ALLOW_REMOTE_BACKEND=true … --no-github -y`. Docs: "`--no-github` uploads local source as a tarball" to a "Manufact-managed repo, no GitHub setup"; `--root-dir <path>` is the "Repository-relative app root" ("Repository-relative paths are resolved from the Git root even when the command is run inside the app directory"); `--port` default 3000 (we leave it; Manufact passes `PORT`). The CLI "streams build logs live" and "After a successful deploy, it prints the server's MCP URL." Follow a build: `npx mcp-use deployments logs <DEPLOYMENT_ID> --build --follow`.

**Option 2, dashboard import from GitHub (after the public repo exists, Sunday 08:00):** Servers → **New Server** → **Import from GitHub** → install the Manufact GitHub App → pick the repo → Configure: branch `main`, region `AUTO`, **Root directory** `mcp-runtime` (Advanced), paste env (below), Deploy. "Deploying clones, analyzes, builds, deploys, and health-checks the code before routing traffic." Pipeline steps shown live: Cloning, Analyzing, Building, Deploying, Health Checks, Complete. Pushes to `main` redeploy automatically. Note: "Deploying from a GitHub organization repository requires the Hobby plan or higher" (personal repos are fine on Free).

**Option 3, connect by URL (no hosting):** New Server → "Connect an existing server" → paste `https://<handle>.inkboxwire.com/mcp` if the tunnel were pointed at the MCP instead of the backend. Gives Inspector, Chat, Testing, publish checklist, **but "Sessions are not available on direct external servers"** and no Public Chat, so it is not the demo path.

## Environment variables (Server → Environment Variables tab, or `--env`)

| Var | Value | Why |
| --- | --- | --- |
| `STEWARD_BACKEND_URL` | `https://<handle>.inkboxwire.com` | Backend origin through the tunnel; origin only, no path |
| `STEWARD_ALLOW_REMOTE_BACKEND` | `true` | `config.ts` refuses a non-loopback backend otherwise |
| `STEWARD_MCP_PROPERTY_IDS` | `cedar,harbor,juniper` | optional, default is all three |
| `STEWARD_BACKEND_TOKEN` | same as the backend's API token, if the backend stream enabled one | MCP → backend auth |
| `STEWARD_MCP_TOKEN` | optional bearer for clients | If set, add it in Manufact's server auth settings and in Armature's MCP Setup credentials |
| `ARMATURE_API_KEY`, `ANALYTICS_INGEST_API_KEY`, `ANALYTICS_INGEST_URL` | Armature ingest key (+ URL for EU) | armature/README.md |
| `PORT` | **do not set**; Manufact injects it | Docs: Manufact "injects some variables at deploy time, such as `MCP_URL` and `CSP_URLS`"; `PORT` handling is from mcp-use's `listen()` precedence (above) |
| `STEWARD_MCP_PORT` | not needed when hosted | local only |

"Saving variables does not restart your server." → **Redeploy** from the Deployments tab after any change.

## URL and client connect

Production URL: `https://<your-slug>.run.mcp-use.com/mcp` (customise the slug under Domains; preview branches get `https://<slug>--br-<branch>.run.mcp-use.com/mcp`, Hobby+). **Add to client**: click the URL chip on the server page → "one-click installs or copy-paste config for Cursor, VS Code, VS Code Insiders, Claude Desktop, Claude Code, Gemini CLI, Codex CLI, TypeScript and Python mcp-use snippets". For Claude Code the generated command is the standard `claude mcp add --transport http steward https://<slug>.run.mcp-use.com/mcp` (exact text comes from the dialog). The dashboard's **Chat / Tools / Prompts / Resources** tabs exercise the server directly.

## What the judge sees

- **Sessions** (`Sessions` tab): "Browse, filter, and replay MCP interactions." Each row: client + version, actor, goal/outcome (Achieved/Failed/Unknown once labelled), tool calls, errors, last seen; click → "session timeline drawer that shows gateway events in order: initialization, tool listing, tool calls, and errors." Turn on **Settings → Analytics capture → Capture payloads** before the demo so the drawer shows `resolve`/`attest`/`check` arguments and results ("By default, only request metadata is stored"). **Identify actors** labels the Claude Code session.
- **Gateway Requests** (`Observability`): "Monitor live gateway requests, filter by status and client, and optionally capture payloads", refreshed every few seconds; methods `initialize`, `tools/list`, `tools/call`. Retention 7 days on Free.
- **Analytics**: tool calls, sessions, error rate, latency, clients (Claude, Cursor…), issues, goals.
- **Publish checks** (`Publish → Checklist`): "basic checklist covers protocol compliance and platform readiness: initialization behavior, tool schemas, error handling, and metadata quality", "$0.10 per run", any plan; results passed/warning/error/skipped with "How to fix". E2E checks in ChatGPT/Claude need Hobby ($2/run). Run once after the deploy and screenshot the score. Free scoring without an account also exists at https://manufact.com/mcp-catalog.
- **Public Chat** (`Publish → Public Chat`, **Hobby plan or higher, $25/mo**): hosted chat at `https://<slug>.run.mcp-use.com/chat` with title, description and up to 8 suggested questions; "A Public transcripts table shows chat threads". Suggested starters: "Is P-101 at Harbor Works cleared for restart?", "What is the pressure on P-101? Spend up to $2.", "Verify attestation <id>". Warning from the docs: if the server requires auth, "visitors use the server's configured credentials" — leave `STEWARD_MCP_TOKEN` unset for the public chat or accept that exposure.
- **Testing** (`Testing` tab): dashboard-defined suites ("defines a task and passing criteria", 70% threshold, clients Inspector/ChatGPT/Claude/Claude Code/Codex CLI/Pi). Optional; Armature evals cover the same ground (armature/README.md §4). Not file-based, not run on deploy ("Run a suite on demand").

Plans (https://docs.manufact.com/dashboard/billing): Free $0 with $5 monthly credits, 7-day retention, no previews, no Public Chat, no E2E checks; Hobby $25/mo unlocks those and 30-day retention.

## Unverified

- Default Node major in Manufact's Node preset (our `run.sh` exits if `node -p` reports < 24). If the Analyzing/Building step fails there, switch to **Dockerfile path** `manufact/Dockerfile` with the repository root as context (`--dockerfile manufact/Dockerfile`, drop `--root-dir`) — whether the Dockerfile build context is the repo root or `--root-dir` is also unverified; the Dockerfile assumes the repo root.
- Whether Manufact sets `HOST` (we bind `0.0.0.0` ourselves when `PORT` is present, so it does not matter).
- Whether dashboard Chat/Inspector requests carry a browser `Origin` (we drop origin validation when hosted).
- Health-check path and timeout: not documented; the gateway probes the MCP endpoint, so a server that answers `initialize` on `/mcp` is expected to pass.

## Live deployment (Oct 18 2026, 03:14 UTC)

- MCP URL: https://dark-wave-okfom.run.mcp-use.com/mcp (deployment 3c39c29b, built from mcp-runtime/Dockerfile, node:24-slim).
- Backend reached through the Inkbox tunnel https://steward-atlas.inkboxwire.com (scripts/inkbox_tunnel.py must be running on the laptop).
- Armature doctor against the hosted URL: healthy, 30 tools with the telemetry contract, ingest auth ok.
- Redeploy: `STEWARD_BACKEND_URL=https://steward-atlas.inkboxwire.com bash manufact/deploy.sh` with the Armature ingest env exported.
