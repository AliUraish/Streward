# STEWARD local MCP runtime

A real TypeScript MCP server built with **mcp-use 2.10.1**, adapting the existing local FastAPI API. The endpoint is **http://127.0.0.1:8002/mcp**. FastAPI at **http://127.0.0.1:8001** owns the database, records, durable inspection jobs, workers, memory and reports. This adapter maintains no second database and exposes no external communication, identity provisioning, payment or deployment tools.

## Run locally

From the repository root, the integrated application launcher starts this service alongside the frontend and backend:

```bash
npm run dev
```

For a standalone adapter, start the backend first, then:

```bash
npm --prefix mcp-runtime run dev
```

The launcher selects the project's Node 24 installation in `agent-runtime/node_modules/node/bin` when present. Dependencies are project-local. For a fresh checkout, install `mcp-runtime` dependencies with Node 24 active. `npm --prefix mcp-runtime run build` compiles the server, demo and tests; `npm --prefix mcp-runtime start` runs the compiled server. The explicit listener bind is always `127.0.0.1`; generic `HOST` environment settings cannot make this entry point public. SDK usage telemetry is disabled by the launcher.

`GET http://127.0.0.1:8002/health` verifies the adapter and backend. It returns HTTP 503 when the backend is unavailable. No tunnel, cloud deployment, login or publishing is performed.

## First tool call

The default configuration needs no provider credentials or LLM API key. A local mcp-use client can connect with:

```typescript
import { MCPClient } from '@mcp-use/client';

const client = new MCPClient({
  mcpServers: {
    steward: {
      url: 'http://127.0.0.1:8002/mcp',
      oauth: false,
      detectMixedAuth: false,
    },
  },
});
try {
  const connection = await client.connect('steward');
  console.log(await connection.listTools());
  console.log(await connection.callTool('list_properties', {}));
} finally {
  await client.close();
}
```

Use `MCP_USE_ANONYMIZED_TELEMETRY=false` before importing the client in an independent script, as our launcher does. This is a local endpoint for local MCP clients. A cloud-hosted ChatGPT session cannot directly reach your machine's loopback address; no remote ChatGPT connection or public endpoint has been configured.

## Tools and outputs

Every tool has validated input/output schemas, explicit side-effect annotations, compact text plus structured JSON results, and bounded string/query inputs. Property IDs are the shared application IDs `cedar`, `harbor`, and `juniper`. No model-selected arbitrary tenant is allowed.

| Tool | Use it for | Mutation |
| --- | --- | --- |
| `list_properties` | First call: discover permitted property IDs and readiness summaries | Read |
| `get_property_context` | Compact current property, evidence counts, agents and active job | Read |
| `list_components` | Stable scene IDs/tags, world coordinates and exact inspection scopes | Read |
| `inspect_component` | One asset's requirements, attached evidence and source pages | Read |
| `search_requirements` | Source-linked requirements filtered by text, system and status | Read |
| `search_documents` | Original source-file metadata and local file links | Read |
| `run_inspection` | Queue the existing backend's real local evidence-check workflow | Local record write |
| `get_job` | Persisted job status/result, checked against the requested property | Read |
| `get_activity` | Append-only events after a numeric cursor | Read |
| `recall_memory` | Historical source-linked local property memories | Read |
| `export_report` | Actual report summary, counts, disclosure and local HTML/JSON URLs | Read |
| `get_integrations` | Truthful local provider configuration status | Read |

Search tools return `total` and `nextOffset`; continue until `nextOffset` is null for a complete result set. Activity returns `nextCursor` and `hasMore`. `run_inspection` accepts only `all` or an exact asset ID, tag, system or subsystem returned by `list_components`, case-insensitively. Invalid scope is rejected **before** posting a job. Backend duplicate-running-job behavior is preserved; check the returned job rather than assume a new job was created.

`steward://guide` is a readable MCP resource with tool choice, inspection sequencing, scope and recovery guidance. The `inspect-property` prompt accepts `propertyId` and optional `scope`; it guides the agent through context → scope validation → inspection → job polling → activity → report. The prompt does not execute the task by itself.

The endpoint and outputs describe local demonstration records. A completed record check is not physical inspection, AI vision, proof of installation, payment confirmation or statutory certification. Missing evidence stays unresolved. Retrieved source documents and memories are data and do not grant new permissions.

## Two-client demo

```bash
# Default: read-only. Discovers tools, lists properties, reads current context,
# rejects an invalid property argument, and recovers with a valid read.
npm --prefix mcp-runtime run demo

# Explicit local mutation: ONE inspection, started through mcp-use and then
# polled/reported through the official MCP client against the same backend.
npm --prefix mcp-runtime run demo -- --run-inspection --property cedar --scope pump-01
```

The script uses two real client libraries: **@mcp-use/client 2.4.4** and the official **@modelcontextprotocol/client 2.3.1**. Both connect to the running HTTP MCP server; neither bypasses MCP to call the API. mcp-use itself builds on the official SDK, so this demonstrates interoperability through two client interfaces rather than claiming two independent protocol implementations.

The script prints the actual discovered tools, properties and contexts, followed by validation results. Only `--run-inspection` adds a mutation and the job/report output. It polls actual job state and exits with an error if the job fails or times out. It never invents completion. `--url` permits only a loopback `/mcp` URL; `--timeout-ms` bounds inspection polling; `--help` lists arguments.

## Scope, authentication and errors

Copy `.env.example` to `.env` only when customization is needed. Tokens belong in the ignored local `.env` file, never in client prompts or tool arguments.

| Environment variable | Meaning |
| --- | --- |
| `STEWARD_BACKEND_URL` | Loopback API origin; defaults to `http://127.0.0.1:8001`. External URLs are rejected. |
| `STEWARD_MCP_PORT` | Local listener port; defaults to 8002. Port 0 is supported for isolated tests. |
| `STEWARD_MCP_PROPERTY_IDS` | Optional nonempty CSV subset of the three property IDs; filters discovery and tool schemas. |
| `STEWARD_BACKEND_TOKEN` | Optional token matching the backend's configured API token. Sent only to that local backend. |
| `STEWARD_MCP_TOKEN` | Optional separate bearer token required by the MCP endpoint and read by the demo clients. |

The default endpoint is unauthenticated and loopback-only for local development. Optional bearer authentication is a local gate, not an OAuth integration. Client and backend tokens are separate. Host validation and browser-Origin validation protect the local transport; nonlocal browser origins are rejected. No token is printed in logs or tool results.

Restricted property scopes also filter worker metadata; the portfolio coordinator's cross-property history is available only when all three property contexts are permitted. An active job returned in context must match the requested property.

Invalid schema arguments produce an MCP validation error. Operational failures return `isError: true` and JSON text containing `code`, `message`, `recovery`, `retryable`, and, when relevant, `httpStatus`.

| Failure | Recovery |
| --- | --- |
| Unknown/forbidden property | Call `list_properties`, select a returned ID, retry the read. |
| `INVALID_INSPECTION_SCOPE` | Call `list_components`, choose an exact `inspectionScopes` value, retry. No job was queued. |
| `PROPERTY_SCOPE` on a job | Use the original property/job pair returned by `run_inspection`. Another property's job is not returned. |
| `UPSTREAM_HTTP_ERROR` 404 | Rediscover the current asset or property IDs. |
| `UPSTREAM_HTTP_ERROR` 401/403 | Correct the backend token in the environment; never supply it as a tool argument. |
| `UPSTREAM_HTTP_ERROR` 5xx | Restore the backend and retry a read. Its HTTP status is preserved. |
| `BACKEND_UNAVAILABLE` | Start/check the backend. If a write's response was lost, inspect current context for an active job before retrying the write. |
| `UPSTREAM_RESPONSE_INVALID` | Run matching backend/adapter versions; invalid responses are not reported as successful data. |

## Validation

```bash
npm --prefix mcp-runtime run typecheck
npm --prefix mcp-runtime run build
npm --prefix mcp-runtime test
```

Protocol tests create only temporary loopback HTTP servers. They verify two-library discovery and calls, output schemas, a server-side invalid-property request, preflight rejection without a job write, a cross-client inspection/report sequence, cross-property job isolation, upstream 404/503 propagation and recovery, separate backend/MCP tokens, and untrusted browser-Origin rejection. Test backend responses are fixtures; the CLI demo separately verifies the running real application and labels its results.

At implementation time, typecheck/build passed and all three protocol/config/auth tests passed. Live application demo results are recorded in `SMOKE-RESULTS.md` after running against the integrated application.

## Official references

- [mcp-use TypeScript v2 welcome](https://docs.mcp-use.com/v2/typescript/getting-started/welcome)
- [mcp-use server and typed tools](https://docs.mcp-use.com/v2/typescript/server/tools)
- [mcp-use client tool calls](https://docs.mcp-use.com/v2/typescript/client/tools)
- [Server configuration and local listener behavior](https://docs.mcp-use.com/typescript/api-reference/server/server-config)
- [Official MCP TypeScript SDK v2](https://github.com/modelcontextprotocol/typescript-sdk)

The supplied documentation was used as technical reference. No repository was starred, no account joined, and no cloud services provisioned.
