# Steward — local property workspace

A local reconstruction of the reference video's property-inspection workflow: a navigable mechanical room, twelve survey views, source-linked requirements, PDF documents, evidence, property agents, memory and reports.

The source repository and original scan were unavailable. This application has an original Three.js room with real geometry and stable equipment IDs. Its three fictional properties and baseline observations are labeled demonstration data. A verified project record is not a physical inspection or statutory certification.

## Start and restart

The dependencies and project-local runtimes are already installed in this checkout. From this directory:

```sh
npm run dev
```

Open **http://127.0.0.1:3000**. The API is at **http://127.0.0.1:8001**, interactive API documentation at **http://127.0.0.1:8001/docs**, and the TypeScript mcp-use endpoint at **http://127.0.0.1:8002/mcp**. One command starts all three services. The frontend proxies `/api/*` to FastAPI and `/mcp` to the TypeScript adapter. Port 8000 belongs to another application on this machine.

Stop with **Ctrl+C in the terminal that launched the app**, then run the same command to restart. Restart the backend after changing its environment. Do not terminate unrelated processes to free a port. If port 8001 is occupied, `BACKEND_PORT=8003 npm run dev` starts the services with matching API connections. Set `STEWARD_MCP_PORT=8004` to move the MCP listener. The frontend remains on port 3000.

For separate terminals, use `npm run dev:backend`, `npm run dev:frontend` and `npm run dev:mcp`. If you override ports in separate terminals, set `BACKEND_PORT` for FastAPI, `BACKEND_URL` and `MCP_URL` for Next.js, and `STEWARD_BACKEND_URL`/`STEWARD_MCP_PORT` for the MCP adapter.

No Vercel or other cloud deployment is needed or performed by these commands. `npm run dev` installs missing Python dependencies from the existing pinned requirements if necessary; it does not provision provider accounts or resources.

## The four views

| View | Working features |
| --- | --- |
| **Workspace** | Navigate the industrial room, select equipment, inspect related requirements and evidence, toggle markers/clearance guides, upload evidence and create purchase proposals. Orbit controls use drag/scroll; Walk mode supports W/A/S/D and Shift. |
| **Inspection wall** | Twelve viewpoints of the same real geometry. Run a persisted inspection and follow its actual job state and tool events. |
| **Codes & standards** | Search source documents and requirements, inspect the system/subsystem/component hierarchy, open source pages in the PDF reader, and ingest uploaded documents. Seed documents are original project specifications. |
| **Agents** | Chat, assign property or portfolio inspection work, view the four agent contexts, inspect persistent memory, open the optional inbox, review purchase proposals, export reports and connect an MCP client. |

Switch between **Cedar House**, **Harbor Works** and **Juniper Residence** using the property selector. Each property has separate records, evidence and memory; the geometric room template is shared.

Try: ask about `P-103`, run an inspection, open its requirement source, attach evidence to an exact check, and export a report. “Inspect all properties” runs the coordinator and the three scoped property workers. The event history records each source read, component check and completed job.

## What works without credentials

The default is **local deterministic execution**. It reads actual source files, extracts searchable text, checks unique asset identifiers and scene bounds, verifies the property/equipment/requirement identifiers in machine-readable evidence, persists findings, updates readiness, saves source-linked memory and generates a report. Jobs finish when this work finishes; progress has no artificial delays.

This mode does not simulate model vision or external communications. A photo or unstructured attachment is retained as pending evidence when it cannot be assessed. Structured passing records verify record consistency. Wrong-property or wrong-equipment records become issues. The JSON evidence format and explicit project-requirement import syntax are documented in [backend/README.md](backend/README.md).

**Steward Coordinator** coordinates the portfolio. **Steward Cedar**, **Steward Harbor** and **Steward Juniper** keep their respective property contexts. The optional model runtime also defines this coordinator and these three scoped specialists with real typed property tools. Missing model access is shown explicitly.

## Data and configuration

The default durable data is in **`backend/data/`**: SQLite (`steward.sqlite3`) plus uploaded/generated files under `files/`. First startup seeds records idempotently. User edits, memory, events and job checkpoints survive restart, and interrupted jobs resume. Back up the entire directory with the app stopped if you want a consistent portable copy. Removing it resets the project, so it is not part of the restart procedure.

Create `backend/.env` from [backend/.env.example](backend/.env.example) only if you need optional services. Keep real credentials in the ignored environment file. The server also reads a root `.env` when present; existing process environment variables take precedence. `STEWARD_DATA_DIR` may override the data location; use an absolute path when launching from different directories.

| Service | Configuration and behavior |
| --- | --- |
| **Model gateway** | `STEWARD_MODEL_PROVIDER=openai`, `STEWARD_MODEL_BASE_URL`, `STEWARD_MODEL_API_KEY`, `STEWARD_MODEL_NAME`. An OpenAI-compatible gateway supplies grounded chat synthesis. Provider failures leave an explicit local answer and event. |
| **Claude CLI** | `STEWARD_MODEL_PROVIDER=claude_cli` after your own `claude auth login`. The backend invokes a read-only synthesis command with CLI tools disabled. CLI installation alone does not mean it is authenticated. |
| **Supermemory** | `SUPERMEMORY_API_KEY`. Manually sync source-linked local memories, then recall profile/search in a server-derived property namespace. External indexing is asynchronous. |
| **Inkbox** | `INKBOX_API_KEY` and `INKBOX_IDENTITY_CEDAR`, `INKBOX_IDENTITY_HARBOR`, `INKBOX_IDENTITY_JUNIPER` (or one shared `INKBOX_IDENTITY`). Lookup and inbox actions verify an existing identity. Sending additionally requires `STEWARD_ALLOW_EXTERNAL_MESSAGES=true` and exact recipients in `INKBOX_ALLOWED_RECIPIENTS`. Creating an identity requires `STEWARD_ALLOW_IDENTITY_PROVISION=true`. No phone number is provisioned automatically. |
| **Stripe sandbox** | `STRIPE_SECRET_KEY=sk_test_...` and `STRIPE_WEBHOOK_SECRET` for verified receipts. The explicit Checkout action creates an idempotent merchant test session. Live keys and live webhook events are refused. This does not order equipment from a supplier; proposals work locally without Stripe. |
| **InsForge** | `INSFORGE_BASE_URL` and `INSFORGE_ANON_KEY` for a read-only check against an existing project's `steward_properties` table. No project or schema is created; SQLite stays the active store. |
| **Manufact / MCP** | A real TypeScript mcp-use server runs on port 8002 and calls the same FastAPI services as the UI. Typed tools expose property context, scene objects, source retrieval, local inspection jobs, memory and reports. A guide resource and inspection prompt explain tool choice and error recovery. No hosted server is deployed. |

The UI uses backend-provided capability flags for optional actions. An available action means its local configuration permits an attempt; a connection is only verified after a successful provider request. Missing keys produce actionable errors, never fake success.

## Optional model agent runtime

The core app does not require this process. To use the **eve** coordinator and specialists locally, configure a supported model connection in `agent-runtime/.env.local` using [agent-runtime/.env.example](agent-runtime/.env.example). For example, set `AI_GATEWAY_API_KEY` there and choose a `STEWARD_EVE_MODEL` available to your account. The runtime can also use its supported local login flow. No hosting project or cloud deployment is required to run it.

Start the runtime in a separate terminal:

```sh
npm run dev:agents
```

It binds to **http://127.0.0.1:2000** using the installed project-local Node 24 runtime. In `backend/.env`, enable the bridge:

```dotenv
STEWARD_MODEL_PROVIDER=eve
STEWARD_EVE_URL=http://127.0.0.1:2000
STEWARD_EVE_READY=true
```

The backend and eve are separate processes with separate environment files. The model credential must be available to **eve**; `STEWARD_EVE_READY=true` merely tells the backend to attempt the already configured runtime. It does not authenticate or verify that runtime. Alternatively, a relevant provider key present in the backend environment can mark its eve adapter configured, but the runtime still needs its own working model connection.

Restart `npm run dev` after changing the backend environment. Ask a property question to exercise model synthesis. Read-only chat sessions cannot start inspection writes: the runtime enforces property scope and mutation mandates outside model prompts. Model session state and capability policies are stored in `agent-runtime/.eve/`. Local deterministic inspection jobs remain available regardless of model access. A failed model request falls back visibly to the local evidence answer.

The optional runtime uses an explicit local virtual filesystem. Built-in shell and filesystem tools are disabled; property tools call the API directly. No Docker daemon, VM provider or cloud sandbox is needed for this configuration.

## MCP demo in two clients

With `npm run dev` running, execute `npm run demo:mcp`. It connects to the same MCP endpoint using **mcp-use** and the **official MCP TypeScript client**, discovers tools, retrieves property context, checks an invalid scope error, and demonstrates a successful read after the error. It prints actual responses. Add `-- --run-inspection` to run and poll a real local inspection before retrieving the report. This only changes local demonstration records.

These are two independent protocol client libraries, not a claim of testing inside the ChatGPT or Claude applications. Desktop client configuration and the short demo sequence are documented in [mcp-runtime/README.md](mcp-runtime/README.md). A remote hosted client cannot reach a loopback URL without a separately configured connection. No public tunnel has been opened.

## Installed tools and checks

The installed Python runtime is project-managed under `.runtime/python/`; the backend environment is `backend/.venv/`. Node 24 is at `agent-runtime/node_modules/node/bin/node`. InsForge and Manufact CLI packages live under `tooling/node_modules/`; eve lives under `agent-runtime/node_modules/`. The Inkbox Python SDK is pinned in backend requirements.

These wrappers use the installed Node 24 runtime for CLI commands. Version checks read installed package metadata entirely offline:

```sh
npm run cli:insforge -- --version
npm run cli:manufact -- --version
npm run cli:eve -- --version
```

Use `--help` through the same wrappers to inspect supported commands. The wrappers do not install missing packages or log in automatically. Keep cloud provisioning/deployment as a separately authorized step.

```sh
npm run test:backend
npm run test:agents
npm run build:agents
npm run build:mcp
npm run demo:mcp
npm test
```

`npm test` runs backend API/persistence/provider tests, the agent mutation-scope test, MCP adapter tests/build, frontend TypeScript checks and the production frontend build. Stop the dev frontend before a production build because both use `.next/`. Provider tests use temporary databases and mocked transports; they do not send live emails, charge cards or create cloud resources.

The API contract is in [API-CONTRACT.md](API-CONTRACT.md), backend details in [backend/README.md](backend/README.md), and implementation status plus earlier product context in [STEWARD-BUILD-BRIEF.md](STEWARD-BUILD-BRIEF.md).

The completed reference comparison and browser verification are in [design-qa.md](design-qa.md); the final local preview is saved in [qa/steward-final.png](qa/steward-final.png). All 28 automated checks and the frontend, MCP and optional agent-runtime builds passed. Live provider actions still require the account configuration described above.
