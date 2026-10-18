# STEWARD MCP verification

Verified on **2026-10-17 at 22:42 UTC**, against the running integrated local application: MCP **127.0.0.1:8002**, FastAPI **127.0.0.1:8001**. These results came from the application's existing persistent database, not the test fixture backend.

## Read-only two-client run

Command: `npm --prefix mcp-runtime run demo`

| Check | @mcp-use/client 2.4.4 | @modelcontextprotocol/client 2.3.1 |
| --- | --- | --- |
| Connect through HTTP MCP | Passed | Passed |
| Discover tools | Same 12 tools | Same 12 tools |
| List real property IDs | cedar, harbor, juniper | cedar, harbor, juniper |
| Read current Cedar context | Passed | Passed |
| Actual evidence totals | 77 verified, 17 pending, 2 issues, 0 unknown, 96 total | Identical |

The official client rejected `propertyId="not-a-property"`, then successfully recovered with a valid Cedar context read. No inspection or report tool was called by the default run. Raw actual output: [SMOKE-READONLY.json](./SMOKE-READONLY.json).

## Explicit local inspection run

Command: `npm --prefix mcp-runtime run demo -- --run-inspection --property cedar --scope pump-01`

- mcp-use started actual backend job **job-8937c101588943e0** for **cedar / pump-01**.
- The official MCP client polled that same job and received **completed**, **100%**, **componentsChecked: 1**.
- Backend result explicitly reported **mode: local_deterministic**, **modelUsed: false**.
- The official client exported the actual report: **24 components**, **96 requirements**, totals **77 verified / 17 pending / 2 issues / 0 unknown**.
- Returned HTML/JSON report URLs pointed to the local backend's Cedar report endpoints.
- Job timestamps: created **22:42:41.152145Z**, completed **22:42:41.169887Z**; report read **22:42:41.666631Z**.

Raw actual output: [SMOKE-INSPECTION.json](./SMOKE-INSPECTION.json). This run intentionally updated local evidence records and appended a real inspection/job history entry. It performed no model call, external message, identity creation, purchase, charge, cloud deployment or physical inspection.

## Protocol, scope, auth and error tests

`npm --prefix mcp-runtime run typecheck`, `npm --prefix mcp-runtime run build`, and `npm --prefix mcp-runtime test` passed. The three test cases cover:

1. Local-only configuration and valid property subsets.
2. Two real SDK clients against an ephemeral MCP listener: matching discovery, typed outputs, raw server-side invalid-property rejection, invalid scope with zero job writes, cross-client job/report access, cross-property job rejection, resource/prompt retrieval, 404/503 propagation and successful recovery.
3. Separate MCP/backend bearer tokens and rejection of an untrusted browser Origin.

These tests use explicitly labeled fixture API responses on temporary loopback ports. The two CLI runs above separately verify the actual application. mcp-use builds on the official MCP SDK; the demo establishes compatibility through two client library interfaces, not independent wire implementations. No cloud-hosted ChatGPT session has been connected to the loopback endpoint.
