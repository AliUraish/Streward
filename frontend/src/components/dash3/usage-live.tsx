"use client";

/* The live half of the Evals page (owner, Oct 18: "the evals page, which tells the latest tool calls, model usage and
   stuff", "and the latest MCP calls with their details"): today's Claude usage per part of Steward (calls, tokens,
   estimated cost against each daily cap), the latest MCP calls from outside agents (client, tool, tokens in and out,
   latency, result) and the latest tool calls the agents made, from GET /api/usage every 5 s. */
import Link from "next/link";
import { usePoll } from "@/lib/hooks-3";
import { site3, isSite3 } from "@/lib/sites-3";
import { Reveal, State, ago } from "./ui3";

interface ModelRow { key: string; label: string; model: string; calls: number; inputTokens: number; outputTokens: number; usd: number; errors: number; fallbacks: number; capCalls: number; capUsd: number }
interface ToolCall { at: string; agentId: string; agentName: string; siteId: string | null; kind: string | null; tool: string | null; tokens: number | null; ms: number | null; ok: boolean; source: string | null }
interface McpCall { at: string; agentId: string; agentName: string; tool: string | null; ok: boolean; ms: number | null; tokens: number | null; tokensIn: number | null; tokensOut: number | null; client: string | null; siteId: string | null; request: string | null }
interface Mcp { calls: McpCall[]; today: { calls: number; failures: number; tokens: number; avgMs: number | null; clients: { client: string; calls: number }[] }; topTools: { tool: string; calls: number; failures: number; avgMs: number | null }[] }
interface Usage { day: string; model: string; models: ModelRow[]; total: { calls: number; inputTokens: number; outputTokens: number; usd: number }; mcp?: Mcp;
  toolCalls: ToolCall[]; toolCallsToday: { calls: number; tokens: number; failures: number }; topTools: { tool: string; calls: number; tokens: number; failures: number }[] }

async function fetchUsage(): Promise<Usage> {
  const res = await fetch("/api/usage?limit=30", { cache: "no-store" });
  if (!res.ok) throw new Error(`usage ${res.status}`);
  return await res.json() as Usage;
}
/* The eval harness's own tools (only its runner sees them) stay out of the lists. */
const HARNESS_TOOLS = new Set(["start_scenario", "list_scenarios"]);
const fmt = (v: number, digits = 0) => new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(v);
const usd = (v: number) => `$${v < 1 ? v.toFixed(3) : v.toFixed(2)}`;
const words = (s: string | null) => (s ?? "").replace(/_/g, " ");

export default function UsageLive() {
  const usage = usePoll(fetchUsage, [], 5_000);
  return <>
    <Reveal as="section" className="p3" i={1} aria-labelledby="mu-h">
      <div className="p-head"><h2 id="mu-h">Model usage today</h2>{usage.data ? <span className="meta">{usage.data.model}, {usage.data.day} UTC, live</span> : null}</div>
      <State remote={usage} what="model usage">{u => <>
        <ul className="mu12" aria-label="Today in total">
          <li><b>{fmt(u.total.calls)}</b><span>Claude calls</span></li>
          <li><b>{fmt(u.total.inputTokens)}</b><span>tokens in</span></li>
          <li><b>{fmt(u.total.outputTokens)}</b><span>tokens out</span></li>
          <li><b>{usd(u.total.usd)}</b><span>estimated cost</span></li>
          <li><b>{fmt(u.toolCallsToday.calls)}</b><span>tool calls, 24 h</span></li>
        </ul>
        <table className="tbl12"><thead><tr><th scope="col">Part</th><th scope="col">Calls</th><th scope="col">Tokens in / out</th><th scope="col">Cost</th><th scope="col">Daily cap</th></tr></thead>
          <tbody>{u.models.map(m => <tr key={m.key}>
            <th scope="row">{m.label}{m.errors ? <span className="bad12"> {m.errors} error{m.errors === 1 ? "" : "s"}</span> : null}</th>
            <td>{fmt(m.calls)}</td><td>{fmt(m.inputTokens)} / {fmt(m.outputTokens)}</td><td>{usd(m.usd)}</td>
            <td><span className="cap12"><i style={{ width: `${Math.min(100, m.capUsd ? (m.usd / m.capUsd) * 100 : 0)}%` }} /></span>{fmt(m.calls)} of {fmt(m.capCalls)} calls, {usd(m.capUsd)}</td>
          </tr>)}</tbody></table>
      </>}</State>
    </Reveal>
    <Reveal as="section" className="p3" i={2} aria-labelledby="mcp-h">
      <div className="p-head"><h2 id="mcp-h">Latest MCP calls</h2>{usage.data?.mcp ? <span className="meta">outside agents calling Steward over MCP</span> : null}</div>
      <State remote={usage} what="MCP calls" isEmpty={u => !u.mcp || u.mcp.calls.length === 0} empty="No MCP calls yet. Connect a client to http://127.0.0.1:8002/mcp.">{u => { const raw = u.mcp!; const m = { ...raw, calls: raw.calls.filter(c => !HARNESS_TOOLS.has(c.tool ?? "")), topTools: raw.topTools.filter(t => !HARNESS_TOOLS.has(t.tool)) }; return <>
        <ul className="mu12" aria-label="MCP calls in the last 24 hours">
          <li><b>{fmt(m.today.calls)}</b><span>MCP calls, 24 h</span></li>
          <li><b>{m.today.avgMs !== null ? `${fmt(m.today.avgMs)} ms` : "–"}</b><span>average latency</span></li>
          <li><b>{fmt(m.today.tokens)}</b><span>tokens returned</span></li>
          <li><b>{fmt(m.today.failures)}</b><span>failed</span></li>
          <li><b>{fmt(m.today.clients.length)}</b><span>{m.today.clients.slice(0, 2).map(c => c.client).join(", ") || "clients"}</span></li>
        </ul>
        {m.topTools.length ? <p className="r3 top12">Most called: {m.topTools.slice(0, 6).map(t => `${t.tool} ${fmt(t.calls)}${t.avgMs !== null ? ` (${fmt(t.avgMs)} ms)` : ""}`).join(" · ")}</p> : null}
        <table className="tbl12"><thead><tr><th scope="col">When</th><th scope="col">Client</th><th scope="col">Tool</th><th scope="col">Acting as</th><th scope="col">Tokens in / out</th><th scope="col">Latency</th><th scope="col">Result</th></tr></thead>
          <tbody>{m.calls.map((c, k) => <tr key={`${c.at}-${k}`}>
            <td><time dateTime={c.at}>{ago(c.at)}</time></td><td>{c.client ?? "–"}</td><td><code>{c.tool ?? "tool"}</code>{c.request ? <span className="r3"> {c.request}</span> : null}</td>
            <td>{c.agentName}</td><td>{c.tokensIn !== null || c.tokensOut !== null ? `${fmt(c.tokensIn ?? 0)} / ${fmt(c.tokensOut ?? 0)}` : c.tokens ? fmt(c.tokens) : "–"}</td>
            <td>{c.ms !== null ? `${fmt(c.ms)} ms` : "–"}</td><td>{c.ok ? "ok" : <span className="bad12">failed</span>}</td>
          </tr>)}</tbody></table>
      </>; }}</State>
    </Reveal>
    <Reveal as="section" className="p3" i={3} aria-labelledby="tc-h">
      <div className="p-head"><h2 id="tc-h">Latest agent tool calls</h2>{usage.data ? <span className="meta">{fmt(usage.data.toolCallsToday.calls)} in 24 h, {fmt(usage.data.toolCallsToday.failures)} failed</span> : null}</div>
      <State remote={usage} what="tool calls" isEmpty={u => u.toolCalls.length === 0} empty="No tool calls yet.">{u => <>
        {u.topTools.length ? <p className="r3 top12">Busiest today: {u.topTools.slice(0, 6).map(t => `${words(t.tool)} ${fmt(t.calls)}`).join(" · ")}</p> : null}
        <table className="tbl12"><thead><tr><th scope="col">When</th><th scope="col">Agent</th><th scope="col">Tool</th><th scope="col">Site</th><th scope="col">Tokens</th><th scope="col">Result</th></tr></thead>
          <tbody>{u.toolCalls.map((c, k) => <tr key={`${c.at}-${k}`}>
            <td><time dateTime={c.at}>{ago(c.at)}</time></td><td>{c.agentName}</td><td><code>{c.tool ?? words(c.kind)}</code></td>
            <td>{c.siteId && isSite3(c.siteId) ? <Link className="lnk" href={`/app/${c.siteId}`}>{site3(c.siteId).short}</Link> : "–"}</td>
            <td>{c.tokens ? fmt(c.tokens) : "–"}{c.ms ? <span className="r3"> · {fmt(c.ms)} ms</span> : null}</td>
            <td>{c.ok ? "ok" : <span className="bad12">failed</span>}</td>
          </tr>)}</tbody></table>
      </>}</State>
    </Reveal>
  </>;
}
