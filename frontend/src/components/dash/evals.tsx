"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { age, useEvals } from "@/lib/reality";
import type { EvalRun, EvalSuite } from "@/lib/types-2";
import { errorMessage } from "../ui";
import { NotReady, Panel } from "./rail";
import { useSite } from "./shell";

const SUITES: { id: EvalSuite; label: string }[] = [{ id: "demo-workflow", label: "Run demo workflow" }, { id: "mission-workflow", label: "Run mission workflow" }];
const ARMATURE_URL = process.env.NEXT_PUBLIC_ARMATURE_URL;

export default function EvalsView() {
  const { notify } = useSite();
  const [launching, setLaunching] = useState<EvalSuite | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [result, setResult] = useState("");
  const evals = useEvals(Boolean(launching));
  const runs = useMemo(() => [...(evals.data ?? [])].sort((a, b) => b.startedAt.localeCompare(a.startedAt)), [evals.data]);
  const anyRunning = runs.some(r => !r.finishedAt);
  const running = Boolean(launching) || anyRunning;
  useEffect(() => { if (!selectedId && runs.length) setSelectedId(runs[0].id); }, [runs, selectedId]);
  const selected = runs.find(r => r.id === selectedId) ?? null;
  async function run(suite: EvalSuite) {
    setLaunching(suite); setResult("");
    try { const r = await api.runEval(suite); setResult(`${suite}: ${r.passed} passed, ${r.failed} failed${r.finishedAt ? "" : ", still running"}.`); setSelectedId(r.id); evals.reload(); }
    catch (e) { setResult(errorMessage(e)); notify(errorMessage(e)); }
    finally { setLaunching(null); }
  }
  return <div className="evals">
    <div className="runs">
      <Panel title="Eval runs" count={runs.length || undefined} demo>
        <div className="controls">
          {SUITES.map(s => <button key={s.id} className={`btn btn-small ${s.id === "demo-workflow" ? "btn-primary" : ""}`} onClick={() => run(s.id)} disabled={running}>{launching === s.id ? "Running" : s.label}</button>)}
          {running ? <span className="result">A run is in progress; the list refreshes every 3 s.</span> : result ? <span className="result">{result}</span> : null}
        </div>
        <div className="panel-body">
          {runs.length === 0 ? <NotReady readiness={evals.readiness} error={evals.error} reload={evals.reload} empty="No runs yet. Run the demo workflow to replay resolve, dispatch, wrong tag, right tag and check." /> : null}
          {runs.map(r => <button key={r.id} className={`row run-row ${selected?.id === r.id ? "selected" : ""}`} onClick={() => setSelectedId(r.id)}>
            <div className="top"><span className="tag">{r.suite}</span><span className={`state ${!r.finishedAt ? "running" : r.failed ? "failed" : "resolved"}`}>{!r.finishedAt ? "running" : r.failed ? `${r.failed} failed` : "all passed"}</span></div>
            <div className="counts">{r.passed}<small>passed</small>{r.failed ? <> · {r.failed}<small>failed</small></> : null}</div>
            <div className="sub"><span>{new Date(r.startedAt).toLocaleString()}</span><span>{age(r.startedAt)}</span>{r.finishedAt ? <span>{Math.max(0, Math.round((new Date(r.finishedAt).getTime() - new Date(r.startedAt).getTime()) / 100) / 10)} s</span> : null}</div>
          </button>)}
        </div>
      </Panel>
      <div className="armature">{ARMATURE_URL ? <a className="link" href={ARMATURE_URL} target="_blank" rel="noreferrer">Open in Armature</a> : "The Armature dashboard link appears here when NEXT_PUBLIC_ARMATURE_URL is configured."}</div>
    </div>
    <RunDetail run={selected} />
  </div>;
}

function RunDetail({ run }: { run: EvalRun | null }) {
  return <section className="run-detail panel" aria-label="Run detail">
    <div className="panel-head"><h2>{run ? `${run.suite} · ${new Date(run.startedAt).toLocaleTimeString()}` : "Run detail"}{run ? <span className="count"> {run.passed} passed · {run.failed} failed</span> : null}</h2></div>
    {!run ? <div className="panel-body"><div className="empty">Select a run to see its steps.</div></div>
      : run.steps.length === 0 ? <div className="panel-body"><div className="empty">{run.finishedAt ? "This run recorded no steps." : "Steps appear as the run progresses."}</div></div>
      : <table className="run-table"><thead><tr><th>Step</th><th>Target</th><th>Result</th><th>ms</th><th>Detail</th></tr></thead><tbody>
        {run.steps.map((s, i) => <tr key={`${s.name}-${i}`}><td>{s.name}</td><td className="target">{s.target}</td><td className={`res ${s.result}`}>{s.result === "PASS" ? "passed" : "failed"}</td><td className="ms">{s.ms}</td><td className="detail">{s.detail}</td></tr>)}
      </tbody></table>}
  </section>;
}
