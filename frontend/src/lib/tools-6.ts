/* The Tool Forge (REALITY-CONTRACT-6.md) as contract facts the dashboard can show before the backend answers: the
   lifecycle, who approves what, readable names for the allow-listed operations, and the two demo tools the contract
   agrees (Myer's pump_spec_breaches, Bristol's visitor_route_readiness). The demo tools are shown only while
   GET /api/tools is missing, as contract drafts: their task, gap and inputs are the contract's words; nothing about
   them is invented, so they carry no recipe, test, approval or usage until the backend drafts them. */
import { roleOf } from "./sites-3";
import type { ForgedTool, SiteId3 } from "./types-3";

export const LIFECYCLE: { status: string; title: string; what: string }[] = [
  { status: "draft", title: "Draft", what: "The agent records the gap and drafts a declarative definition." },
  { status: "validated", title: "Validate", what: "Schema, allow-listed operations, templates and the agent's own site as scope." },
  { status: "tested", title: "Test", what: "One run on live local data with a test input." },
  { status: "approved", title: "Approve", what: "The site's manager for read-only tools, the Operations Director for any write." },
  { status: "published", title: "Publish", what: "Registered in MCP as forge_<name>; every connected client sees it." },
];
const RANK: Record<string, number> = { draft: 0, validated: 1, tested: 2, approved: 3, published: 4, retired: 5 };
export const statusRank = (s: string) => RANK[s] ?? -1;
export const isDone = (s: string) => s === "published" || s === "retired" || s === "rejected";
export const statusWord: Record<string, string> = {
  draft: "draft", validated: "validated", tested: "tested", approved: "approved", published: "published", rejected: "refused", retired: "retired", contract: "planned",
};
/* The contract's approval rule: the site's manager for read-only tools, the Operations Director for any write. */
export function approverFor(t: { siteId: string; readOnly: boolean | null }): string {
  if (t.readOnly === false) return "director";
  try { return roleOf(t.siteId as SiteId3, "manager").id; } catch { return "director"; }
}
export const mcpName = (name: string) => `forge_${name.replace(/^forge_/, "")}`;

/* Readable names for the allow-listed operations; anything else is shown by its op name. */
export const OP_WORDS: Record<string, string> = {
  "facts.list": "Read the facts", "metrics.series": "Read the metric series", "issues.list": "List the issues", "obligations.list": "List the obligations",
  "crew.responsible": "Ask who is responsible", "conversations.list": "List the conversations", "maintenance.list": "List the maintenance windows",
  "eye.go_to": "Send the agent eye to", "eye.look": "Look through the agent eye", resolve: "Resolve a fact",
  filter: "Keep the rows where", map: "Reshape each row", group_count: "Count the rows per", sort: "Sort by", take: "Keep the first", join_on: "Join on",
};
/* The demo task each site's form suggests, from the contract (none agreed for the mill). */
export const DEMO_TASK: Partial<Record<SiteId3, { agentId: string; task: string }>> = {
  "myer-plant": { agentId: "myer-engineer", task: "Which pumps went over their pressure spec more than three times in the last 7 days, and who is responsible for each?" },
  "bristol-pumps": { agentId: "bristol-compliance", task: "List every asset on the visitor route that has an open issue or an overdue obligation, the regulation involved, and who must act." },
};

const empty = { calls: 0, lastCalledAt: null, tokensSavedEstimate: null, history: [] as [string, number][] };
export const CONTRACT_TOOLS: ForgedTool[] = [
  {
    id: "contract-pump-spec-breaches", name: "pump_spec_breaches", version: 1, status: "contract", siteId: "myer-plant",
    createdBy: "myer-engineer", createdAt: "", approvedBy: null,
    why: {
      task: "Which pumps went over their pressure spec more than three times in the last 7 days, and who is responsible for each?", requestedBy: "operator",
      gap: "get_metrics returns raw series and who_is_responsible takes one issue kind; nothing counts breaches per asset or joins owners.",
      consideredTools: [
        { name: "get_metrics", whyNot: "Returns raw series; nothing counts breaches per asset." },
        { name: "who_is_responsible", whyNot: "Takes one issue kind; nothing joins owners to assets." },
      ],
    },
    description: "", inputSchema: { properties: { days: {}, minBreaches: {} } }, steps: [],
    output: { template: "[{assetTag, breaches, worstValue, unit, owner}]", schema: {} }, readOnly: true, test: null, usage: empty,
    generator: "hand-seed", synthetic: true, placeholder: true,
  },
  {
    id: "contract-visitor-route-readiness", name: "visitor_route_readiness", version: 1, status: "contract", siteId: "bristol-pumps",
    createdBy: "bristol-compliance", createdAt: "", approvedBy: null,
    why: {
      task: "List every asset on the visitor route that has an open issue or an overdue obligation, the regulation involved, and who must act.", requestedBy: "bristol-manager",
      gap: "Issues and obligations are separate tools without route membership or the regulation link.",
      consideredTools: [
        { name: "list_issues", whyNot: "Lists issues without route membership or the regulation link." },
        { name: "list_obligations", whyNot: "Lists obligations separately, without route membership or the regulation link." },
      ],
    },
    description: "", inputSchema: { properties: {} }, steps: [],
    output: { template: "[{assetTag, kind, issueOrObligation, regulation, owner, blocking}], plus a ready boolean", schema: {} }, readOnly: true, test: null, usage: empty,
    generator: "hand-seed", synthetic: true, placeholder: true,
  },
];
