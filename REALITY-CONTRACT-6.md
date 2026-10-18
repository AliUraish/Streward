# Contract addendum 6: Tomioka withdrawn; agents that build their own tools

Written Oct 18 2026, 00:40 PDT. Update 00:50 PDT: the user restored contract 5, so the product has three sites (`myer-plant`, `bristol-pumps`, `tomioka-mill`). Tool Forge below works for all three; the two demo tools stay Myer and Bristol. Same rules as before: no git, no paid calls (Claude only in dry-run during the build), never kill by pattern, do not restart 3000/8001/8002.

## Tool Forge: an agent that lacks a tool builds one

A task arrives for an agent that no existing tool can answer. The agent records the gap, drafts a tool, Steward validates and tests it, a manager or the Director approves it, and it becomes a real MCP tool every connected client sees at once. A Tools page shows every tool, who built it, when and why.

### Tool definition (declarative only; no generated code ever runs)

```ts
interface ForgedTool {
  id: string; name: string;               // snake_case, unique, prefixed forge_ in MCP
  version: number; status: 'draft'|'validated'|'tested'|'approved'|'published'|'rejected'|'retired';
  siteId: 'myer-plant'|'bristol-pumps'|'tomioka-mill';  // scope; the tool can never read or write outside it
  createdBy: string;                      // agent id
  createdAt: string; approvedBy?: string; approvedAt?: string;
  why: { task: string; requestedBy: string; gap: string; consideredTools: { name: string; whyNot: string }[] };
  description: string;                    // written for an agent: when to call, cost, next step
  inputSchema: object;                    // JSON Schema, additionalProperties false
  steps: { id: string; op: string; args: Record<string, string>; }[];   // op from the allow-list below; args are templates over input and earlier steps
  output: { template: string; schema: object };                        // shape returned to the caller
  readOnly: boolean;                      // true when every step is a read op
  test?: { input: object; output: object; passed: boolean; ms: number; at: string; notes: string[] };
  usage: { calls: number; lastCalledAt?: string; tokensSavedEstimate: number };
  generator: 'claude-opus-5-5' | 'hand-seed'; synthetic: boolean;
}
```

Allowed `op` values are existing, authority-checked Steward operations only, for example `facts.list`, `metrics.series`, `issues.list`, `obligations.list`, `crew.responsible`, `conversations.list`, `maintenance.list`, `eye.go_to`, `eye.look`, `resolve`, plus the pure transforms `filter`, `map`, `group_count`, `sort`, `take`, `join_on`. Every step runs with the creating agent's authority (backend checks, and for any Supabase read the agent's own Supabase token, so RLS binds the tool). A tool with any write op is never auto-approved.

### Lifecycle

1. `POST /api/tools/requests {agentId, siteId, task}`: the agent looks at its current tools, records the gap and `consideredTools`.
2. Draft: Claude Opus 5.5 (structured output against the ForgedTool schema, `fallbacks: "default"`) writes the definition; `--dry-run`/build mode uses the prepared hand-seeded drafts below. Record `generator`.
3. Validate: schema, allow-listed ops, templates resolve, scope is the agent's own site, output schema closed.
4. Test: run once on live local data with a sample input; store the result.
5. Approve: the site's Plant Manager for read-only tools, the Operations Director for any write; refusal is recorded with a reason.
6. Publish: the MCP registers it as `forge_<name>` and sends `notifications/tools/list_changed`; every call goes through `POST /api/tools/{id}/call` with the caller's actor header, increments usage and writes telemetry.
7. Retire or version: a new version keeps the old one's usage history.

Endpoints: `POST /api/tools/requests`, `GET /api/tools?siteId=&status=`, `GET /api/tools/{id}`, `POST /api/tools/{id}/validate`, `POST /api/tools/{id}/test`, `POST /api/tools/{id}/approve {approve, reason}`, `POST /api/tools/{id}/publish`, `POST /api/tools/{id}/call {args}`, `POST /api/tools/{id}/retire`. Every step is a Change of type `tool` and appears in the agent's transcript as a conversation line ("I don't have a tool for this; drafting forge_pump_spec_breaches").

### The two demo tools (hand-seeded drafts so the demo needs no live call; live generation is the end-to-end test)

- Myer, built by the Site Engineer · Myer, asked by the Owner's agent: "Which pumps went over their pressure spec more than three times in the last 7 days, and who is responsible for each?" Gap: `get_metrics` returns raw series and `who_is_responsible` takes one issue kind; nothing counts breaches per asset or joins owners. Tool: `pump_spec_breaches {days, minBreaches}` → `[{assetTag, breaches, worstValue, unit, owner}]`. Read-only; approved by the Plant Manager · Myer.
- Bristol, built by the Compliance Officer · Bristol, asked by the Plant Manager · Bristol before a visitor opening: "List every asset on the visitor route that has an open issue or an overdue obligation, the regulation involved, and who must act." Gap: issues and obligations are separate tools without route membership or the regulation link. Tool: `visitor_route_readiness {}` → `[{assetTag, kind, issueOrObligation, regulation, owner, blocking}]`, plus a `ready` boolean. Read-only; approved by the Plant Manager · Bristol.

### MCP

Published forged tools appear as first-class tools (`forge_pump_spec_breaches`), descriptions start with "Built by <agent> on <date> because <why.gap>", and the server emits `notifications/tools/list_changed` when one is published or retired. If mcp-use cannot add tools to a running stateless server, keep stable `list_forged_tools` and `call_forged_tool {toolId, args}` and document why. Also `request_tool {siteId, task}` so an outside agent can ask the site's team to build one, paired with `wait_for`.

### Dashboard

A Tools page per factory (`/app/[site]/tools`) and a portfolio view in the sidebar: each tool with name, the agent that built it, when, why (the task, the gap, the tools it considered and why not), the recipe as a readable step list, the test result, who approved it, usage over time and tokens saved; a demo control "Ask the team for a new tool" (pick an agent, type the task) that follows the lifecycle live. Forged tools also show on each agent's page.
