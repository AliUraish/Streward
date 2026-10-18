"use client";

/* /app/evals: eval metrics (pass rate per suite, tokens and tool calls per mission, time held by wait_for, latency,
   A2A messages per day, estimated cost), the three suites with run detail, the self-optimisation loop (the
   Operations Director detects, calls the Compliance Officer, reconfigures it, reruns the efficiency eval) with the
   before/after tokens chart, findings by agent, and the Armature link. */
import { useEffect, useMemo, useState } from "react";
import type { Remote } from "@/lib/reality";
import { api3 } from "@/lib/api-3";
import { useBoardMeetings, useEvalFindings, useEvalMetrics, useEvals3, usePoll } from "@/lib/hooks-3";
import { EVAL_SUITES3, agentName } from "@/lib/sites-3";
import type { EvalRun } from "@/lib/types-2";
import type { AgentConfig, EvalMetrics3, LoopStep, TokenPoint } from "@/lib/types-3";
import { BarChart, ColumnChart, LineChart } from "./charts";
import TokensChart from "./tokens-chart";
import { Btn, DemoTag, PageHead, Reveal, State, ago, errorText, n, when, words } from "./ui3";

const ARMATURE_URL = process.env.NEXT_PUBLIC_ARMATURE_URL;
const SOURCE = "Steward telemetry";
/* Where a figure comes from, without the delivery plumbing ("…, also delivered to Armature"). */
const sourceWord = (s?: string | null) => (s || SOURCE).replace(/,?\s*also delivered to Armature/i, "");
const STAGES: { kind: string; word: string; who: string }[] = [
  { kind: "detect", word: "The Operations Director detects", who: "a Compliance Officer's tokens per mission against its peers" },
  { kind: "call", word: "The director messages the Compliance Officer", who: "and asks why it re-reads every certificate" },
  { kind: "reconfigure", word: "The director reconfigures it", who: "document cache on, subscribe instead of poll" },
  { kind: "rerun", word: "The efficiency eval reruns", who: "tokens per mission against the budget" },
];
/* The agent the loop works on: whichever compliance officer the director reconfigured (the retired id while the backend migrates). */
const LOOP_CANDIDATES = ["bristol-compliance", "myer-compliance", "counsel"];
async function loopConfig(): Promise<AgentConfig | null> {
  const got = await Promise.allSettled(LOOP_CANDIDATES.map(id => api3.agentConfig(id)));
  const ok = got.flatMap((r, i) => r.status === "fulfilled" ? [{ ...r.value, agentId: LOOP_CANDIDATES[i] === "counsel" ? "bristol-compliance" : LOOP_CANDIDATES[i] }] : []);
  if (!ok.length) { const e = got.find(r => r.status === "rejected") as PromiseRejectedResult | undefined; throw e?.reason ?? new Error("No config"); }
  const by = (c: AgentConfig) => (c.history ?? []).filter(h => h.by === "director").at(-1)?.at ?? "";
  return [...ok].sort((a, b) => by(b).localeCompare(by(a)))[0];
}

export default function EvalsPage() {
  const [running, setRunning] = useState(false);
  const runs = useEvals3(running);
  const findings = useEvalFindings();
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const latest = useMemo(() => {
    const m = new Map<string, EvalRun>();
    for (const r of runs.data ?? []) { const p = m.get(r.suite); if (!p || r.startedAt > p.startedAt) m.set(r.suite, r); }
    return m;
  }, [runs.data]);
  useEffect(() => { setRunning(Boolean(runs.data?.some(r => !r.finishedAt))); }, [runs.data]);
  const sel = (runs.data ?? []).find(r => r.id === selected) ?? [...latest.values()].sort((a, b) => b.startedAt.localeCompare(a.startedAt))[0] ?? null;

  async function run(suite: string) {
    setBusy(suite); setError("");
    try { const r = await api3.runEval(suite); setSelected(r.id); runs.reload(); }
    catch (e) { setError(`${suite}: ${errorText(e)}`); }
    finally { setBusy(null); }
  }

  const f = findings.data;
  /* The loop, from the records it leaves: the compliance officer's flag in the findings, the board meeting, the
     director's reconfigure in its config history, and the efficiency run after it. Before/after tokens per mission split the telemetry at
     the reconfigure: findings since that moment are "after"; "before" is the all-time figure with those removed. */
  const loopCfg = usePoll(() => loopConfig(), [], 15_000);
  const target = loopCfg.data?.agentId ?? "bristol-compliance";
  const meetings = useBoardMeetings();
  const reconf = (loopCfg.data?.history ?? []).filter(h => h.by === "director").at(-1) ?? null;
  const T = reconf?.at ?? null;
  const afterF = usePoll(() => T ? api3.evalFindings(T) : Promise.resolve(null), [T], 15_000);
  const derived: LoopStep[] = [];
  const flag = f?.flags?.find(x => x.agentId === target) ?? f?.flags?.find(x => x.severity === "high");
  if (flag || reconf) derived.push({ kind: "detect", at: f?.at ?? reconf?.at ?? "", agentId: "director", summary: flag?.finding ?? `${agentName(target)} was flagged in Steward telemetry.` });
  const meet = (meetings.data ?? []).find(m => m.scenarioId === "ops-counsel-tokens" || m.issueKind === "agent_efficiency");
  if (meet) derived.push({ kind: "call", at: meet.at, agentId: "director", summary: `${meet.title ?? "Board meeting"}${meet.resolution ? `. ${meet.resolution}` : ""}` });
  if (reconf) derived.push({ kind: "reconfigure", at: reconf.at, agentId: "director", summary: `${Object.entries(reconf.change).map(([k, v]) => `${words(k)} ${String(v)}`).join(", ")}${reconf.why ? `. ${reconf.why}` : ""}` });
  const rerun = T ? (runs.data ?? []).filter(r => r.suite === "efficiency" && r.startedAt >= T).sort((a, b) => a.startedAt.localeCompare(b.startedAt)).at(-1) : undefined;
  if (rerun) derived.push({ kind: "rerun", at: rerun.startedAt, agentId: "director", summary: rerun.finishedAt ? `${rerun.passed} passed, ${rerun.failed} failed` : "Running" });
  const steps: LoopStep[] = f?.loop?.steps?.length ? f.loop.steps : derived;
  const points: TokenPoint[] = f?.loop?.tokens?.length ? f.loop.tokens : (f?.agents ?? []).map(a => {
    const later = T ? afterF.data?.agents.find(x => x.agentId === a.agentId) : undefined;
    if (!later) return { agentId: a.agentId, before: a.tokensPerMission, after: null };
    const all = a.missions ?? 0, since = later.missions ?? 0;
    const before = a.tokensPerMission !== null && all > since ? Math.round((a.tokensPerMission * all - (later.tokensPerMission ?? 0) * since) / (all - since)) : null;
    return { agentId: a.agentId, before, after: later.tokensPerMission };
  });
  const budget = Number(f?.configs?.[target]?.maxTokensPerMission ?? loopCfg.data?.config.maxTokensPerMission) || f?.loop?.budget || null;
  const metrics = useEvalMetrics();
  return <div className="page3">
    <PageHead id="evals" title="Evals" />
    <EvalMetricsBlock remote={metrics} />
    <div className="ev3">
      <Reveal className="suites3">
        <div className="p-head"><h3>Suites</h3><DemoTag /></div>
        {runs.readiness !== "ready" ? <State remote={runs} what="eval runs">{() => null}</State> : null}
        {error ? <p className="err3" role="alert">{error}</p> : null}
        <ul className="suite-list">{EVAL_SUITES3.map(s => {
          const r = latest.get(s.id);
          return <li key={s.id} className={sel?.id && r?.id === sel.id ? "on" : ""}>
            <button type="button" className="row-btn" disabled={!r} onClick={() => r && setSelected(r.id)}>
              <span className="r1"><strong>{s.name}</strong>{r ? <span className={r.failed ? "bad" : ""}><span className={`sig ${!r.finishedAt ? "warn" : r.failed ? "bad" : "ok"}`} aria-hidden="true" />{!r.finishedAt ? "running" : `${r.passed} passed, ${r.failed} failed`}</span> : <span className="sev">not run yet</span>}</span>
              <span className="r2">{s.what}</span>
              <span className="r3">{r ? `${ago(r.startedAt)}` : ""}</span>
            </button>
            <Btn small arrow disabled={Boolean(busy)} onClick={() => run(s.id)}>{busy === s.id ? "Starting" : "Run"}</Btn>
          </li>;
        })}</ul>
      </Reveal>
      <Reveal className="p3 run3" i={1}>
        <div className="p-head"><h3>Run detail</h3><span className="meta">{sel ? `${sel.suite}, ${when(sel.startedAt)}` : ""}</span></div>
        {sel ? <div className="tbl3 run-tbl" role="table" aria-label="Eval steps">
          <div className="tr head" role="row"><span role="columnheader">Step</span><span role="columnheader">Target</span><span role="columnheader">Result</span><span role="columnheader">Detail</span></div>
          {sel.steps.map((s, i) => <div className="tr" role="row" key={`${s.name}-${i}`}>
            <span role="cell"><strong>{words(s.name)}</strong></span>
            <span role="cell">{s.target}</span>
            <span role="cell" className={s.result === "FAIL" ? "bad" : ""}><span className={`sig ${s.result === "PASS" ? "ok" : "bad"}`} aria-hidden="true" />{s.result === "PASS" ? "pass" : "fail"}<small>{n(s.ms)} ms</small></span>
            <span role="cell">{s.detail}</span>
          </div>)}
        </div> : <p className="st3 empty">{runs.readiness === "ready" ? "No run yet. Start a suite to see its steps." : "No runs yet."}</p>}
      </Reveal>
    </div>

    <div className="loop3">
      <Reveal className="p3 tl3">
        <div className="p-head"><h3>Optimisation loop</h3><span className="meta">{f?.loop?.state ? words(f.loop.state) : ""}</span></div>
        <ol className="timeline3">{STAGES.map(st => {
          const hit = steps.filter(s => s.kind === st.kind);
          const last = hit.at(-1);
          return <li key={st.kind} className={last ? "done" : ""}>
            <span className={`sig ${last ? "ok" : "off"}`} aria-hidden="true" />
            <div><strong>{st.word}</strong><span className="r2">{last ? last.summary : st.who}</span><span className="r3">{last ? `${agentName(last.agentId)}, ${when(last.at)}` : "Not yet."}</span></div>
          </li>;
        })}</ol>
      </Reveal>
      <Reveal className="p3 chartp3" i={1}>
        <div className="p-head"><h3>Tokens per mission</h3></div>
        <State remote={findings} what="eval findings" isEmpty={() => points.length === 0} empty="No token telemetry yet.">
          {() => <TokensChart points={points} budget={budget} source={sourceWord(f?.source)} />}
        </State>
      </Reveal>
    </div>

    <div className="find3">
      <Reveal className="p3 agents-find">
        <div className="p-head"><h3>Findings by agent</h3><span className="meta">{sourceWord(f?.source)}</span></div>
        {f?.flags?.length ? <ul className="rows3 plain flags3">{f.flags.map(x => <li key={`${x.agentId}-${x.finding}`}><span className="r1"><span className={`sig ${x.severity === "high" ? "bad" : "warn"}`} aria-hidden="true" /><strong>{agentName(x.agentId)}</strong><span className="sev">{x.severity}</span></span><span className="r2">{x.finding}</span></li>)}</ul> : null}
        <State remote={findings} what="eval findings" isEmpty={x => x.agents.length === 0} empty="No findings yet.">
          {x => <div className="tbl3 find-tbl" role="table" aria-label="Findings by agent">
            <div className="tr head" role="row"><span role="columnheader">Agent</span><span role="columnheader">Tokens per mission</span><span role="columnheader">Against peers</span><span role="columnheader">Polls</span><span role="columnheader">Failures</span></div>
            {x.agents.map(a => <div className="tr" role="row" key={a.agentId}>
              <span role="cell"><strong>{agentName(a.agentId)}</strong></span>
              <span role="cell" className="num">{n(a.tokensPerMission)}<small>{a.missions ? `${a.missions} missions` : "no missions yet"}</small></span>
              <span role="cell" className={`num ${(a.ratioToPeers ?? 0) >= 5 ? "bad" : ""}`}>{a.ratioToPeers ? `${a.ratioToPeers}×` : "–"}<small>{a.peerMedianTokensPerMission ? `peer median ${n(a.peerMedianTokensPerMission)}` : ""}</small></span>
              <span role="cell" className="num">{n(a.polls ?? null)}</span>
              <span role="cell" className={`num ${a.failures ? "bad" : ""}`}>{n(a.failures ?? null)}</span>
            </div>)}
          </div>}
        </State>
      </Reveal>
      <Reveal className="p3 arm3" i={1}>
        <div className="p-head"><h3>Armature</h3></div>
        <dl className="kv3">
          <dt>Sessions</dt><dd>{f?.armature ? n(f.armature.sessions) : "–"}</dd>
          <dt>Issues</dt><dd>{f?.armature ? n(f.armature.issues ?? null) : "–"}</dd>
          <dt>Counted from</dt><dd>{f?.armature ? (f.armature.source === "armature" ? "Armature" : "Steward telemetry") : "not available yet"}</dd>
        </dl>
        {ARMATURE_URL ? <a className="b3" href={ARMATURE_URL} target="_blank" rel="noreferrer"><span>Open Armature</span><span className="arrow" aria-hidden="true">→</span></a>
          : <a className="lnk" href="https://app.armature.tech" target="_blank" rel="noreferrer">Open Armature</a>}
      </Reveal>
    </div>
  </div>;
}

/* Eval metrics from GET /api/evals/metrics. */
function EvalMetricsBlock({ remote }: { remote: Remote<EvalMetrics3> }) {
  const m = remote.data;
  const fig = (v: number | null, unit?: string, d = 0) => v === null ? "–" : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: d }).format(v)}${unit ? ` ${unit}` : ""}`;
  return <Reveal as="section" className="p3 em3" aria-labelledby="em-h">
    <div className="p-head"><h2 id="em-h">Eval metrics</h2><span className="meta">{sourceWord(m?.source)}</span></div>
    <State remote={remote} what="eval metrics">
      {x => <div className="em-grid">
        <dl className="kpis3 em-figs">
          <div className="kpi"><dt>Time held by wait_for</dt><dd>{fig(x.wait.heldSeconds !== null ? x.wait.heldSeconds / 60 : null, "min", 1)}</dd></div>
          <div className="kpi"><dt>Tokens avoided while waiting</dt><dd>{fig(x.wait.tokensAvoided)}</dd></div>
          <div className="kpi"><dt>Latency p50</dt><dd>{fig(x.latency.p50, x.latency.unit)}</dd></div>
          <div className="kpi"><dt>Latency p95</dt><dd>{fig(x.latency.p95, x.latency.unit)}</dd></div>
          <div className="kpi"><dt>Estimated cost</dt><dd>{x.cost.value === null ? "–" : new Intl.NumberFormat(undefined, { style: "currency", currency: x.cost.currency || "USD", maximumFractionDigits: 2 }).format(x.cost.value)}</dd></div>
        </dl>
        <div className="em-chart wide"><h3>Pass rate per suite</h3>{x.passRate.length ? <LineChart title="Pass rate per suite over runs" unit="%" yDomain={[0, 100]} digits={0} series={x.passRate.map(p => ({ id: p.suite, label: EVAL_SUITES3.find(e => e.id === p.suite)?.name ?? p.suite, points: p.points }))} height={200} />
          : x.passRateBars.length ? <BarChart title="Run pass rate per suite" unit="%" digits={0} rows={x.passRateBars.map(p => ({ label: `${EVAL_SUITES3.find(e => e.id === p.suite)?.name ?? p.suite}${p.runs !== null ? `, ${p.runs} run${p.runs === 1 ? "" : "s"}` : ""}`, value: p.value, tone: p.value < 100 ? "bad" as const : undefined }))} />
          : <p className="st3 empty">No runs yet.</p>}</div>
        <div className="em-chart"><h3>Tokens per mission</h3><BarChart title="Tokens per agent per mission" rows={x.tokensPerMission.map(t => ({ label: agentName(t.agentId), value: t.value }))} /></div>
        <div className="em-chart"><h3>Tool calls per mission</h3><BarChart title="Tool calls per mission" rows={x.toolCallsPerMission.map(t => ({ label: t.label, value: t.value }))} digits={1} /></div>
        <div className="em-chart wide"><h3>Agent messages per day</h3><ColumnChart title="Agent messages per day" points={x.a2aPerDay} /></div>
      </div>}
    </State>
  </Reveal>;
}

