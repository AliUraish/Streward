"use client";

/* /app/[site]/tools and /app/tools (REALITY-CONTRACT-6.md): the tools the agents built for themselves when no existing
   tool could answer a task. Each tool shows who built it and when, why (the task, the gap, the tools it considered and
   why not), the recipe as a readable step list, the test, who approved it, usage over time and tokens saved. "Ask the
   team for a new tool" follows the lifecycle live: the request, then validate, test, approve and publish, each state as
   it lands. Until GET /api/tools answers, the contract's two planned tools are shown, with nothing about them invented. */
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { Remote } from "@/lib/reality";
import { api3 } from "@/lib/api-3";
import { useTool, useTools } from "@/lib/hooks-3";
import { SITES3, agentName, site3, teamOf } from "@/lib/sites-3";
import { CONTRACT_TOOLS, DEMO_TASK, LIFECYCLE, OP_WORDS, approverFor, isDone, mcpName, statusRank, statusWord } from "@/lib/tools-6";
import type { ForgedTool, SiteId3, ToolRequestInput } from "@/lib/types-3";
import { ColumnChart } from "./charts";
import { Btn, DemoTag, PageHead, Reveal, State, SynthTag, ago, day, errorText, n, when, words } from "./ui3";

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
const sigOf = (s: string) => s === "published" ? "ok" : s === "rejected" ? "bad" : s === "retired" || s === "contract" ? "off" : "warn";
/* Newest first; published before the rest; retired last. */
const order = (a: ForgedTool, b: ForgedTool) => (a.status === "retired" ? 1 : 0) - (b.status === "retired" ? 1 : 0) || (b.createdAt || "").localeCompare(a.createdAt || "");

export default function ToolsPage({ siteId }: { siteId?: SiteId3 }) {
  const site = siteId ? site3(siteId) : null;
  const remote = useTools(siteId);
  const filter: string = "all";
  const [open, setOpen] = useState<string | null>(null);
  /* While GET /api/tools is missing: the contract's planned tools for this page's sites. */
  const fallback = useMemo(() => remote.readiness === "not_ready" ? CONTRACT_TOOLS.filter(t => !siteId || t.siteId === siteId) : null, [remote.readiness, siteId]);
  const all = useMemo(() => [...(remote.data ?? fallback ?? [])].filter(t => !siteId || t.siteId === siteId).sort(order), [remote.data, fallback, siteId]);
  const shown = all.filter(t => filter === "all" || t.siteId === filter);
  useEffect(() => { const q = new URLSearchParams(window.location.search).get("id"); if (q) setOpen(q); }, []);
  useEffect(() => { if ((!open || !all.some(t => t.id === open)) && shown.length && !remote.data?.some(t => t.id === open)) setOpen(shown[0].id); }, [shown, all, open, remote.data]);
  const current = all.find(t => t.id === open) ?? null;
  const source: Remote<ForgedTool[]> = fallback ? { ...remote, data: fallback, readiness: "ready" } : remote;
  const published = all.filter(t => t.status === "published").length;
  return <div className="page3">
    <PageHead id="tools" title="Tools">
    </PageHead>


    {fallback ? <p className="note3">The tool register is not available yet, so this shows the planned {fallback.length === 1 ? "tool" : "tools"}: not yet built, validated, tested, approved or used. <button type="button" className="retry" onClick={remote.reload}>Retry</button></p> : null}
    <State remote={source} what="forged tools" isEmpty={() => shown.length === 0} empty={site ? `No tools built at ${site.short} yet. When an agent lacks a tool, the site's team builds and approves one.` : "No tools built yet. When an agent lacks a tool, the site's team builds and approves one."}>
      {() => <div className="tools3">
        <Reveal as="nav" className="tool-list" aria-label="Forged tools">
          <p className="meta tl-count">{all.length} tool{all.length === 1 ? "" : "s"}{remote.data ? `, ${published} published` : ""}</p>
          <ul className="rows3">{shown.map(t => <li key={t.id} className={t.id === current?.id ? "sel" : ""}><button type="button" className="row-btn" aria-pressed={t.id === current?.id} onClick={() => setOpen(t.id)}>
            <span className="r1"><span className={`sig ${sigOf(t.status)}`} aria-hidden="true" /><code className="tname">{mcpName(t.name)}</code><span className="tg">{statusWord[t.status] ?? words(t.status)}</span><SynthTag rec={t} /></span>
            <span className="r2">{t.why.task || t.description || "No task recorded."}</span>
            <span className="r3">{t.placeholder ? "To be built by" : "Built by"} {agentName(t.createdBy)}{t.createdAt ? `, ${day(t.createdAt)}` : ""}{!siteId ? `, ${site3(t.siteId).short}` : ""}{t.placeholder ? "" : `; ${n(t.usage.calls)} call${t.usage.calls === 1 ? "" : "s"}`}</span>
          </button></li>)}</ul>
        </Reveal>
        {current ? <ToolDetail key={current.id} tool={current} onChanged={remote.reload} /> : null}
      </div>}
    </State>
  </div>;
}

/* ---- the lifecycle, run from the dashboard ----------------------------------------------------------------------- */

type RunState = "pending" | "running" | "done" | "failed" | "waiting";
interface RunRow { key: string; title: string; state: RunState; summary?: string; at?: string }
const RUN_STEPS: { key: string; title: string }[] = [
  { key: "request", title: "Request" }, { key: "draft", title: "Draft" }, { key: "validate", title: "Validate" },
  { key: "test", title: "Test" }, { key: "approve", title: "Approve" }, { key: "publish", title: "Publish" },
];
function stepSummary(key: string, t: ForgedTool): string {
  switch (key) {
    case "validate": return "Schema, allow-listed operations, templates and scope check out.";
    case "test": return t.test ? `${t.test.passed ? "Passed" : "Failed"} on live local data${t.test.ms !== null ? ` in ${n(t.test.ms)} ms` : ""}${t.test.notes[0] ? `; ${t.test.notes[0]}` : ""}` : "Tested on live local data.";
    case "approve": return `Approved by the ${agentName(t.approvedBy ?? approverFor(t))}${t.approvedAt ? `, ${ago(t.approvedAt)}` : ""}.`;
    case "publish": return `Published as ${mcpName(t.name)}; every connected MCP client sees it now.`;
    default: return "";
  }
}

/* Walks a tool through validate, test, approve and publish, one endpoint at a time, so each state shows as it lands.
   Steps the backend has already taken are marked done; a refusal or an error stops the walk and says why. A tool that
   writes stops at Approve: only the Operations Director approves it, never automatically. */
export function useForgeRun(onTool: (t: ForgedTool) => void) {
  const [rows, setRows] = useState<RunRow[] | null>(null);
  const [tool, setTool] = useState<ForgedTool | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const cb = useRef(onTool); cb.current = onTool;
  useEffect(() => () => { alive.current = false; }, []);
  const mark = (key: string, state: RunState, summary?: string) => alive.current && setRows(rs => rs?.map(r => r.key === key ? { ...r, state, summary: summary ?? r.summary, at: new Date().toISOString() } : r) ?? rs);
  const got = (t: ForgedTool) => { if (!alive.current) return; setTool(t); cb.current(t); };

  async function advance(start: ForgedTool, approveAsDirector = false) {
    let t = start;
    const plan: [string, string, (x: ForgedTool) => Promise<ForgedTool>][] = [
      ["validate", "validated", x => api3.validateTool(x.id)],
      ["test", "tested", x => api3.testTool(x.id)],
      ["approve", "approved", x => api3.approveTool(x.id, true, x.readOnly === false ? "Approved by the Operations Director after review." : `Read-only and scoped to ${site3(x.siteId).name}.`, approverFor(x))],
      ["publish", "published", x => api3.publishTool(x.id)],
    ];
    for (const [key, target, call] of plan) {
      if (t.status === "rejected") { mark(key, "failed", t.rejectedReason ? `Refused: ${t.rejectedReason}` : "Refused."); return; }
      if (statusRank(t.status) >= statusRank(target)) { mark(key, "done", stepSummary(key, t)); continue; }
      if (key === "approve" && t.readOnly !== true && !approveAsDirector) { mark(key, "waiting", t.readOnly === false ? "This tool writes, so it waits for the Operations Director; it is never approved automatically." : "The draft does not say it is read-only, so it waits for the Operations Director."); return; }
      mark(key, "running");
      await sleep(450);
      try { t = await call(t); }
      catch (e) { mark(key, "failed", errorText(e)); return; }
      got(t);
      if (t.status === "rejected") { mark(key, "failed", t.rejectedReason ? `Refused: ${t.rejectedReason}` : "Refused."); return; }
      mark(key, "done", stepSummary(key, t));
    }
  }

  async function start(input: ToolRequestInput) {
    setBusy(true); setTool(null);
    setRows(RUN_STEPS.map(s => ({ key: s.key, title: s.title, state: "pending" })));
    mark("request", "running", `${agentName(input.agentId)} checks its current tools.`);
    try {
      let r;
      try { r = await api3.requestTool(input); }
      catch (e) { mark("request", "failed", errorText(e)); return; }
      mark("request", "done", r.gap ? `Gap: ${r.gap}` : "The gap is recorded.");
      mark("draft", "running");
      let t = r.tool;
      if (!t && r.toolId) { try { t = await api3.tool(r.toolId); } catch { t = null; } }
      if (!t) { mark("draft", "failed", "The request was recorded, but no draft came back."); return; }
      got(t);
      mark("draft", "done", `${mcpName(t.name)} drafted.`);
      await advance(t);
    } finally { if (alive.current) setBusy(false); }
  }
  async function decide(approve: boolean) {
    if (!tool) return;
    setBusy(true);
    try {
      if (approve) { await advance(tool, true); return; }
      mark("approve", "running");
      try { const t = await api3.approveTool(tool.id, false, "Refused by the Operations Director from the dashboard.", "director"); got(t); mark("approve", "failed", `Refused${t.rejectedReason ? `: ${t.rejectedReason}` : "."}`); }
      catch (e) { mark("approve", "failed", errorText(e)); }
    } finally { if (alive.current) setBusy(false); }
  }
  const waiting = rows?.some(r => r.key === "approve" && r.state === "waiting") ?? false;
  return { rows, tool, busy, waiting, start, decide, resume: (t: ForgedTool) => { setTool(t); setRows(RUN_STEPS.map(s => ({ key: s.key, title: s.title, state: "pending" }))); mark("request", "done", t.why.gap ? `Gap: ${t.why.gap}` : undefined); mark("draft", "done", `${mcpName(t.name)} drafted.`); setBusy(true); void advance(t).finally(() => alive.current && setBusy(false)); } };
}

function RunSteps({ rows }: { rows: RunRow[] }) {
  return <ol className="fix-steps run3" aria-label="Tool lifecycle">{rows.map(r => <li key={r.key} className={r.state}>
    <span className={`sig ${r.state === "done" ? "ok" : r.state === "running" || r.state === "waiting" ? "warn" : r.state === "failed" ? "bad" : "off"}`} aria-hidden="true" />
    <strong>{r.title}</strong><span className={`r3 ${r.state === "failed" ? "bad" : ""}`}>{r.summary ?? (r.state === "running" ? "in progress" : r.state === "pending" ? "waiting" : "")}{r.at && r.state !== "pending" ? ` · ${new Date(r.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}</span>
  </li>)}</ol>;
}

function AskForTool({ siteId, onTool }: { siteId?: SiteId3; onTool: (t: ForgedTool) => void }) {
  const [site, setSite] = useState<SiteId3>(siteId ?? "myer-plant");
  const team = teamOf(site);
  const demo = DEMO_TASK[site];
  const [agentId, setAgentId] = useState(demo?.agentId ?? team[1].id);
  const [task, setTask] = useState("");
  useEffect(() => { setAgentId(DEMO_TASK[site]?.agentId ?? teamOf(site)[1].id); }, [site]);
  const run = useForgeRun(onTool);
  function submit(e: FormEvent) { e.preventDefault(); const text = task.trim(); if (text && !run.busy) void run.start({ agentId, siteId: site, task: text }); }
  return <Reveal as="section" className="p3 ask3" aria-labelledby="ask-h">
    <div className="p-head"><h2 id="ask-h">Ask the team for a new tool</h2><DemoTag /></div>
    <div className="ask-grid">
      <form className="ask-form" onSubmit={submit}>
        <div className="ask-pick">
          {!siteId ? <label className="fld">Site<select value={site} onChange={e => setSite(e.target.value as SiteId3)}>{SITES3.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label> : null}
          <label className="fld">Agent<select value={agentId} onChange={e => setAgentId(e.target.value)}>{team.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
        </div>
        <label className="fld">Task<textarea rows={3} value={task} onChange={e => setTask(e.target.value)} placeholder={demo?.task ?? "What should the agent be able to answer that its tools cannot?"} /></label>
        <div className="row-actions">
          <Btn small arrow type="submit" disabled={run.busy || !task.trim()}>{run.busy ? "The team is on it" : "Ask the team"}</Btn>
          {demo && task.trim() !== demo.task ? <button type="button" className="lnk-btn" onClick={() => { setAgentId(demo.agentId); setTask(demo.task); }}>Use the suggested task</button> : null}
        </div>
      </form>
      <div className="ask-live" aria-live="polite">
        {run.rows ? <RunSteps rows={run.rows} /> : <ol className="fix-steps run3 idle" aria-label="Tool lifecycle">{[{ status: "request", title: "Request", what: "The agent checks its tools and records the gap and the tools it considered." }, ...LIFECYCLE].map(s => <li key={s.status}><span className="sig off" aria-hidden="true" /><strong>{s.title}</strong><span className="r3">{s.what}</span></li>)}</ol>}
        {run.tool ? <p className="r3 follow">Following <code className="tname">{mcpName(run.tool.name)}</code>, {statusWord[run.tool.status] ?? run.tool.status}. <button type="button" className="lnk-btn" onClick={() => onTool(run.tool!)}>Show it below</button></p> : null}
        {run.waiting ? <div className="row-actions"><Btn small arrow disabled={run.busy} onClick={() => void run.decide(true)}>Approve as the Operations Director</Btn><Btn small quiet disabled={run.busy} onClick={() => void run.decide(false)}>Refuse</Btn></div> : null}
      </div>
    </div>
  </Reveal>;
}

/* ---- one tool ----------------------------------------------------------------------------------------------------- */

/* Template references ({{input.days}}, {{steps.s1.rows}}) are set apart so a recipe reads as a sentence. */
function Tpl({ v }: { v: string }) {
  const parts = v.split(/(\{\{[^}]+\}\})/);
  return <>{parts.map((p, i) => i % 2 ? <code key={i} className="tpl">{p.slice(2, -2).trim()}</code> : p)}</>;
}
type Schema = { type?: string | string[]; description?: string; default?: unknown; minimum?: number; maximum?: number; enum?: unknown[]; items?: Schema; properties?: Record<string, Schema>; required?: string[] };
function fields(schema: Schema | null | undefined): { name: string; type: string; note: string; required: boolean }[] {
  if (!schema) return [];
  const base = schema.type === "array" && schema.items ? schema.items : schema;
  const req = new Set(base.required ?? []);
  return Object.entries(base.properties ?? {}).map(([name, s]) => ({
    name, required: req.has(name),
    type: Array.isArray(s?.type) ? s.type.join(" or ") : s?.type ?? (s?.enum ? "one of" : ""),
    note: [s?.description ?? "", s?.enum ? s.enum.map(String).join(", ") : "", s?.minimum !== undefined || s?.maximum !== undefined ? `${s.minimum ?? "…"} to ${s.maximum ?? "…"}` : "", s?.default !== undefined ? `default ${JSON.stringify(s.default)}` : ""].filter(Boolean).join("; "),
  }));
}
const json = (v: unknown, max = 1600) => { const s = JSON.stringify(v, null, 2) ?? ""; return s.length > max ? `${s.slice(0, max)}\n…` : s; };

function ToolDetail({ tool, onChanged }: { tool: ForgedTool; onChanged: () => void }) {
  const [fast, setFast] = useState(false);
  const live = useTool(tool.placeholder ? null : tool.id, fast);
  const t = live.data ?? tool;
  const site = site3(t.siteId);
  const run = useForgeRun(() => { onChanged(); live.reload(); });
  useEffect(() => { setFast(run.busy); }, [run.busy]);
  const ins = fields(t.inputSchema as Schema);
  const outs = fields(t.output?.schema as Schema);
  const approver = approverFor(t);
  return <Reveal as="article" className="p3 tool-view" i={1} aria-labelledby="tv-h">
    <header className="tv-head">
      <div className="tv-tags"><span className="tg">{statusWord[t.status] ?? words(t.status)}</span>{t.readOnly === true ? <span className="tg">read-only</span> : t.readOnly === false ? <span className="tg bad">writes</span> : null}{t.placeholder ? null : <span className="tg">version {t.version}</span>}<span className="tg">{site.short}</span><SynthTag rec={t} /></div>
      <h2 id="tv-h"><code className="tname">{mcpName(t.name)}</code></h2>
      <p className="r2">{t.placeholder
        ? <>To be built by the {agentName(t.createdBy)} for {site.name}; asked by {t.why.requestedBy === "operator" ? "the Owner's agent" : `the ${agentName(t.why.requestedBy)}`}. Approval would come from the {agentName(approver)}.</>
        : <>Built by the {agentName(t.createdBy)} on {when(t.createdAt)} for {site.name}; asked by {t.why.requestedBy === "operator" ? "the Owner's agent" : t.why.requestedBy ? `the ${agentName(t.why.requestedBy)}` : "nobody recorded"}.</>}</p>
    </header>

    <ol className="tv-pipe" aria-label="Lifecycle">{LIFECYCLE.map(s => {
      const reached = statusRank(t.status) >= statusRank(s.status);
      const refusedHere = t.status === "rejected" && s.status === "approved";
      return <li key={s.status} className={refusedHere ? "bad" : reached ? "on" : ""}><strong><span className={`sig ${refusedHere ? "bad" : reached ? "ok" : "off"}`} aria-hidden="true" />{s.title}</strong><span>{refusedHere ? "refused" : reached ? "done" : t.placeholder ? "not started" : "pending"}</span></li>;
    })}{t.status === "retired" ? <li className="on"><strong><span className="sig off" aria-hidden="true" />Retired</strong><span>{t.retiredAt ? ago(t.retiredAt) : "retired"}</span></li> : null}</ol>

    <section className="tv-sec" aria-label="Why">
      <h3>Why it exists</h3>
      <dl className="kv3">
        <dt>Task</dt><dd>“{t.why.task || "not recorded"}”</dd>
        <dt>Gap</dt><dd>{t.why.gap || "not recorded"}</dd>
        <dt>Considered</dt><dd>{t.why.consideredTools.length ? <ul className="considered">{t.why.consideredTools.map(c => <li key={c.name}><code className="tname">{c.name}</code> {c.whyNot}</li>)}</ul> : "No tools recorded as considered."}</dd>
      </dl>
    </section>

    {t.description ? <section className="tv-sec" aria-label="Description"><h3>What it tells an agent</h3><p className="r2">{t.description}</p></section> : null}

    <div className="tv-two">
      <section className="tv-sec" aria-label="Inputs">
        <h3>Inputs</h3>
        {ins.length ? <ul className="params">{ins.map(f => <li key={f.name}><code className="tname">{f.name}</code><span className="r3">{[f.type, f.required ? "required" : "", f.note].filter(Boolean).join(", ")}</span></li>)}</ul> : <p className="st3 empty">No inputs.</p>}
      </section>
      <section className="tv-sec" aria-label="Output">
        <h3>Returns</h3>
        {outs.length ? <ul className="params">{outs.map(f => <li key={f.name}><code className="tname">{f.name}</code><span className="r3">{[f.type, f.note].filter(Boolean).join(", ")}</span></li>)}</ul> : null}
        {t.output?.template ? <p className="r3 tpl-line"><Tpl v={t.output.template} /></p> : !outs.length ? <p className="st3 empty">No output shape on this record.</p> : null}
      </section>
    </div>

    <section className="tv-sec" aria-label="Recipe">
      <h3>Recipe</h3>
      {t.steps.length ? <ol className="recipe3">{t.steps.map((s, i) => <li key={s.id}>
        <span className="num">{i + 1}</span>
        <span className="what"><strong>{OP_WORDS[s.op] ?? words(s.op)}</strong> <code className="op">{s.op}</code></span>
        {Object.keys(s.args).length ? <span className="args">{Object.entries(s.args).map(([k, v]) => <span key={k} className="arg"><span className="k">{k}</span> <Tpl v={v} /></span>)}</span> : null}
        <span className="sid">{s.id}</span>
      </li>)}</ol> : <p className="st3 empty">{t.placeholder ? "The steps are written when the agent drafts the tool." : "No steps on this record."}</p>}
    </section>

    <div className="tv-two">
      <section className="tv-sec" aria-label="Test">
        <h3>Test</h3>
        {t.test ? <>
          <p className={`r2 ${t.test.passed ? "" : "bad"}`}><span className={`sig ${t.test.passed ? "ok" : "bad"}`} aria-hidden="true" />{t.test.passed ? "Passed" : "Failed"} on live local data{t.test.ms !== null ? ` in ${n(t.test.ms)} ms` : ""}{t.test.at ? `, ${when(t.test.at)}` : ""}.</p>
          {t.test.notes.length ? <ul className="notes">{t.test.notes.map((x, i) => <li key={i}>{x}</li>)}</ul> : null}
          <details className="io3"><summary>Test input and output</summary><pre>{json(t.test.input)}</pre><pre>{json(t.test.output)}</pre></details>
        </> : <p className="st3 empty">{t.placeholder ? "Not tested: the tool is not built yet." : "Not tested yet."}</p>}
      </section>
      <section className="tv-sec" aria-label="Approval">
        <h3>Approval</h3>
        {t.approvedBy ? <p className="r2"><span className="sig ok" aria-hidden="true" />Approved by the {agentName(t.approvedBy)}{t.approvedAt ? `, ${when(t.approvedAt)}` : ""}.</p>
          : t.status === "rejected" ? <p className="r2 bad"><span className="sig bad" aria-hidden="true" />Refused{t.rejectedBy ? ` by the ${agentName(t.rejectedBy)}` : ""}{t.rejectedReason ? `: ${t.rejectedReason}` : "."}</p>
          : <p className="st3 empty">{t.placeholder ? `The ${agentName(approver)} approves it once it is built and tested.` : `Waiting for the ${agentName(approver)}${t.readOnly === false ? ": a tool that writes is never approved automatically" : ""}.`}</p>}
      </section>
    </div>

    <section className="tv-sec" aria-label="Usage">
      <h3>Usage</h3>
      {t.placeholder ? <p className="st3 empty">No usage: the tool is not built yet.</p> : <>
        <dl className="tv-figs">
          <div><dt>Calls</dt><dd>{n(t.usage.calls)}</dd></div>
          <div><dt>Tokens saved, estimate</dt><dd>{t.usage.tokensSavedEstimate === null ? "–" : n(t.usage.tokensSavedEstimate)}</dd></div>
          <div><dt>Last called</dt><dd className="small">{t.usage.lastCalledAt ? ago(t.usage.lastCalledAt) : "never"}</dd></div>
        </dl>
        {t.usage.history.length > 1 ? <ColumnChart points={t.usage.history} title={`${mcpName(t.name)} calls per day`} unit="calls" /> : <p className="note3">Calls over time appear here once the tool has been called on more than one day.</p>}
      </>}
    </section>

    {t.history?.length ? <section className="tv-sec" aria-label="History"><h3>History</h3><ul className="rows3 plain">{t.history.slice(-8).map((h, i) => <li key={`${h.at}-${i}`}><span className="r1"><strong>{statusWord[h.status] ?? words(h.status)}</strong>{h.by ? <span className="sev">by the {agentName(h.by)}</span> : null}</span>{h.note ? <span className="r2">{h.note}</span> : null}<span className="r3">{when(h.at)}</span></li>)}</ul></section> : null}

  </Reveal>;
}

/* The next lifecycle step for this tool; for a planned tool, ask its builder to build it. */
function ToolActions({ tool: t, run }: { tool: ForgedTool; run: ReturnType<typeof useForgeRun> }) {
  const [result, setResult] = useState<string>("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function act(fn: () => Promise<unknown>, done?: (v: unknown) => void) {
    setBusy(true); setError("");
    try { const v = await fn(); done?.(v); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const nextLabel = t.status === "draft" ? "Validate, test and approve" : t.status === "validated" ? "Test and approve" : t.status === "tested" ? `Approve as the ${agentName(approverFor(t))}` : t.status === "approved" ? "Publish to MCP" : "";
  return <div className="tv-actions">
    <div className="p-head"><h3>Actions</h3></div>
    {t.placeholder ? <Btn small arrow disabled={run.busy} onClick={() => void run.start({ agentId: t.createdBy, siteId: t.siteId, task: t.why.task })}>Ask the {agentName(t.createdBy)} to build it</Btn>
      : <div className="row-actions">
        {nextLabel && !isDone(t.status) ? <Btn small arrow disabled={run.busy || busy} onClick={() => run.resume(t)}>{run.busy ? "Following the lifecycle" : nextLabel}</Btn> : null}
        {t.status === "published" ? <Btn small arrow disabled={busy} onClick={() => act(() => api3.callTool(t.id, t.test?.input ?? {}), v => setResult(json(v, 2400)))}>Call it with the test input</Btn> : null}
        {t.status === "published" ? <Btn small quiet disabled={busy} onClick={() => act(() => api3.retireTool(t.id))}>Retire</Btn> : null}
        {isDone(t.status) && t.status !== "published" ? <span className="meta">{t.status === "retired" ? "Retired: kept with its usage history." : "Refused: kept as a record of why."}</span> : null}
      </div>}
    {run.rows ? <RunSteps rows={run.rows} /> : null}
    {run.waiting ? <div className="row-actions"><Btn small arrow disabled={run.busy} onClick={() => void run.decide(true)}>Approve as the Operations Director</Btn><Btn small quiet disabled={run.busy} onClick={() => void run.decide(false)}>Refuse</Btn></div> : null}
    {error ? <p className="err3" role="alert">{error}</p> : null}
    {result ? <details className="io3" open><summary>Result of the call</summary><pre>{result}</pre></details> : null}
  </div>;
}

/* The tools an agent built, for its page (Team and the Agents map). */
export function AgentTools({ agentId, siteId }: { agentId: string; siteId?: SiteId3 }) {
  const remote = useTools();
  const fallback = remote.readiness === "not_ready" ? CONTRACT_TOOLS : null;
  const mine = (remote.data ?? fallback ?? []).filter(t => t.createdBy === agentId).sort(order);
  const source: Remote<ForgedTool[]> = fallback ? { ...remote, data: fallback, readiness: "ready" } : remote;
  const href = (t: ForgedTool) => `/app/tools?siteId=${encodeURIComponent(t.siteId)}&id=${encodeURIComponent(t.id)}`;
  return <>
    <div className="p-head"><h3>Forged tools</h3><span className="meta">{fallback ? "planned" : `${mine.length} built`}</span></div>
    <State remote={source} what="forged tools" isEmpty={() => mine.length === 0} empty="This agent has not built a tool yet.">
      {() => <ul className="rows3">{mine.map(t => <li key={t.id}><Link className="row-btn" href={href(t)}>
        <span className="r1"><span className={`sig ${sigOf(t.status)}`} aria-hidden="true" /><code className="tname">{mcpName(t.name)}</code><span className="tg">{statusWord[t.status] ?? words(t.status)}</span><SynthTag rec={t} /></span>
        <span className="r2">{t.why.task}</span>
        <span className="r3">{t.placeholder ? "planned" : `${t.createdAt ? `${day(t.createdAt)}, ` : ""}${n(t.usage.calls)} calls${t.usage.tokensSavedEstimate ? `, about ${n(t.usage.tokensSavedEstimate)} tokens saved` : ""}`}{!siteId ? `, ${site3(t.siteId).short}` : ""}</span>
      </Link></li>)}</ul>}
    </State>
  </>;
}
