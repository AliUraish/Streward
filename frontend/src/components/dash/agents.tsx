"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { age, missionActive, useAgents, useChanges, useMission, useMissions, useTranscript } from "@/lib/reality";
import { siteName } from "@/lib/site";
import type { A2AState, AgentInfo, Change, Mission, MissionStep, TranscriptEntry, TranscriptKind } from "@/lib/types-2";
import { errorMessage } from "../ui";
import { AttestationDrawer, NotReady, Panel } from "./rail";
import { useSite } from "./shell";

const kindWord: Record<TranscriptKind, string> = { a2a: "a2a", sms: "sms", email: "email", imessage: "imessage", call: "call", mcp: "mcp", decision: "decision", system: "system" };
const stateWord: Record<Mission["state"], string> = { running: "running", input_required: "waiting for the owner", completed: "completed", failed: "failed" };
const taskWord: Record<A2AState | "none", string> = { none: "not started", submitted: "submitted", working: "working", input_required: "needs input", completed: "completed", failed: "failed", canceled: "canceled" };

/* The four agents in level order; the Warden shown is the selected site's. A missing endpoint yields placeholders so the layout holds. */
function fallbackAgents(siteId: string): AgentInfo[] {
  return [
    { id: "operator", level: 1, name: "Operator", role: "the customer's own agent, holds the mandate", status: "idle", lastActivityAt: null, authority: [] },
    { id: "atlas", level: 2, name: "Atlas", role: "portfolio coordinator: delegates, cross-checks sites, declares readiness, asks the owner", status: "idle", lastActivityAt: null, authority: [] },
    { id: `warden:${siteId}`, level: 3, name: `Warden · ${siteName(siteId)}`, role: "site agent: resolves, verifies, signs for one site", status: "idle", lastActivityAt: null, authority: [] },
    { id: "runner", level: 4, name: "Runner", role: "field agent: reaches employees and contractors by SMS, email and call, collects evidence", status: "idle", lastActivityAt: null, authority: [] },
  ];
}
function orderAgents(list: AgentInfo[], siteId: string, requestId: string): AgentInfo[] {
  const warden = list.find(a => a.id === `warden:${siteId}`) ?? list.find(a => a.id === `warden:${requestId}`) ?? list.find(a => a.id.startsWith("warden:"));
  const picked = [list.find(a => a.id === "operator"), list.find(a => a.id === "atlas"), warden, list.find(a => a.id === "runner")];
  const fb = fallbackAgents(siteId);
  return picked.map((a, i) => a ?? fb[i]);
}

export default function AgentsView() {
  const { siteId, requestId, notify } = useSite();
  const agents = useAgents();
  const missions = useMissions(requestId);
  const [selectedAgent, setSelectedAgent] = useState<string>("atlas");
  const [missionId, setMissionId] = useState<string | null>(null);
  const [attestationId, setAttestationId] = useState<string | null>(null);
  const changes = useChanges(requestId);
  const cards = useMemo(() => orderAgents(agents.data ?? [], siteId, requestId), [agents.data, siteId, requestId]);
  useEffect(() => { if (!missionId && missions.data?.length) setMissionId([...missions.data].sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0].id); }, [missions.data, missionId]);
  useEffect(() => { setMissionId(null); }, [siteId]);
  const mission = useMission(missionId);
  const running = missionActive(mission.data);
  const transcript = useTranscript(selectedAgent, running);
  const selected = cards.find(a => a.id === selectedAgent) ?? cards[1];

  return <div className="agents">
    <div className="agent-cards">
      {agents.readiness === "not_ready" || agents.readiness === "error" ? <div className="panel"><div className="panel-body" style={{ paddingTop: 12 }}><NotReady readiness={agents.readiness} error={agents.error} reload={agents.reload} empty="" /></div></div> : null}
      {cards.map(a => <AgentCard key={a.id} agent={a} selected={a.id === selected?.id} onSelect={() => setSelectedAgent(a.id)} placeholder={agents.readiness !== "ready"} />)}
    </div>
    <TranscriptPanel agent={selected} entries={transcript.data ?? []} readiness={transcript.readiness} error={transcript.error} reload={transcript.reload} onOpenAttestation={setAttestationId} onOpenMission={setMissionId} />
    <aside className="mission">
      <MissionPanel siteId={siteId} requestId={requestId} mission={mission.data ?? null} readiness={missions.readiness} error={missions.error} reload={() => { missions.reload(); mission.reload(); }} missions={missions.data ?? []} onStarted={m => { setMissionId(m.id); missions.reload(); }} onPick={setMissionId} notify={notify} onOpenAttestation={setAttestationId} />
      <ChainPanel siteId={siteId} mission={mission.data ?? null} changes={changes.data?.changes ?? []} />
    </aside>
    {attestationId ? <AttestationDrawer id={attestationId} onClose={() => setAttestationId(null)} /> : null}
  </div>;
}

function AgentCard({ agent, selected, onSelect, placeholder }: { agent: AgentInfo; selected: boolean; onSelect: () => void; placeholder: boolean }) {
  return <button className={`agent-card ${selected ? "selected" : ""}`} onClick={onSelect} aria-pressed={selected}>
    <span className="lvl"><span>level {agent.level}</span><span className={`status ${agent.status}`}>{placeholder ? "status unknown" : agent.status}</span></span>
    <span className="name">{agent.name}</span>
    <span className="role">{agent.role}</span>
    {agent.handle ? <span className="handle">{agent.handle}</span> : <span className="handle muted">{agent.level === 1 ? "external requester" : "no identity handle configured"}</span>}
    {agent.currentTask ? <span className="task">{agent.currentTask}</span> : null}
    <span className="last">{agent.lastActivityAt ? `last activity ${age(agent.lastActivityAt)}` : placeholder ? "" : "no activity yet"}</span>
  </button>;
}

/* Chat-style transcript: agents talk in text. */
function TranscriptPanel({ agent, entries, readiness, error, reload, onOpenAttestation, onOpenMission }: { agent: AgentInfo | undefined; entries: TranscriptEntry[]; readiness: "loading" | "ready" | "not_ready" | "error"; error: string; reload: () => void; onOpenAttestation: (id: string) => void; onOpenMission: (id: string) => void }) {
  const [selectedEntry, setSelectedEntry] = useState<string | null>(null);
  useEffect(() => { setSelectedEntry(null); }, [agent?.id]);
  const rows = useMemo(() => [...entries].sort((a, b) => a.at.localeCompare(b.at)), [entries]);
  return <section className="transcript panel" aria-label="Transcript">
    <div className="panel-head">
      <h2>{agent?.name ?? "Transcript"}<span className="count"> {rows.length ? `${rows.length} entries` : ""}</span></h2>
    </div>
    <div className="chat">
      {rows.length === 0 ? <NotReady readiness={readiness} error={error} reload={reload} empty="No entries yet. Start a mission to watch the agents talk." /> : null}
      {rows.map(e => <div key={e.id} className={`msg ${e.direction} selectable ${selectedEntry === e.id ? "selected" : ""}`} onClick={() => setSelectedEntry(prev => prev === e.id ? null : e.id)} role="button" tabIndex={0} onKeyDown={ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setSelectedEntry(prev => prev === e.id ? null : e.id); } }}>
        <div className="meta"><span className="who">{e.direction === "out" ? `to ${e.counterpart}` : `from ${e.counterpart}`}</span><span className="kind-tag">{kindWord[e.kind] ?? e.kind}</span><span>{new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>{e.simulated ? <span className="sim-tag">simulated</span> : null}</div>
        <div className="text">{e.text}</div>
        {e.audioUrl ? <audio controls preload="none" src={e.audioUrl} onClick={ev => ev.stopPropagation()} /> : null}
        {(e.refs?.workItemId || e.refs?.attestationId || e.refs?.missionId || e.refs?.taskId) ? <div className="refs" onClick={ev => ev.stopPropagation()}>
          {e.refs.workItemId ? <a href={`/api/work-items/${encodeURIComponent(e.refs.workItemId)}`} target="_blank" rel="noreferrer">work item {e.refs.workItemId.slice(0, 12)}</a> : null}
          {e.refs.attestationId ? <button onClick={() => onOpenAttestation(e.refs.attestationId!)}>attestation {e.refs.attestationId.slice(0, 12)}</button> : null}
          {e.refs.missionId ? <button onClick={() => onOpenMission(e.refs.missionId!)}>mission {e.refs.missionId.slice(0, 12)}</button> : null}
          {e.refs.taskId ? <span className="mono muted">task {e.refs.taskId.slice(0, 12)}</span> : null}
        </div> : null}
      </div>)}
    </div>
  </section>;
}

/* Start mission (demo control, actor operator), live state and steps, restart checklist when complete. */
function MissionPanel({ siteId, requestId, mission, missions, readiness, error, reload, onStarted, onPick, notify, onOpenAttestation }: { siteId: string; requestId: string; mission: Mission | null; missions: Mission[]; readiness: "loading" | "ready" | "not_ready" | "error"; error: string; reload: () => void; onStarted: (m: Mission) => void; onPick: (id: string) => void; notify: (m: string) => void; onOpenAttestation: (id: string) => void }) {
  const [budget, setBudget] = useState(250);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  async function start(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setResult("");
    try { const m = await api.startMission({ siteId: requestId, goal: "clear_for_restart", budget, requester: "dashboard-operator" }); setResult(`Mission ${m.id.slice(0, 12)} started.`); onStarted(m); }
    catch (err) { setResult(errorMessage(err)); notify(errorMessage(err)); }
    finally { setBusy(false); }
  }
  const steps = useMemo(() => [...(mission?.steps ?? [])].sort((a, b) => a.at.localeCompare(b.at)), [mission?.steps]);
  const recent = [...missions].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).slice(0, 5);
  return <Panel title="Mission" demo count={mission ? `${siteName(siteId)}` : undefined}>
    <form className="form" onSubmit={start}>
      <div className="budget">
        <label className="field">Budget (USD)<input type="number" min={0} step={10} value={budget} onChange={e => setBudget(Number(e.target.value))} /></label>
        <button className="btn btn-primary btn-small" type="submit" disabled={busy || missionActive(mission)}>{busy ? "Starting" : "Start mission: clear site for restart"}</button>
      </div>
      {result ? <div className="result">{result}</div> : null}
    </form>
    <div className="panel-body">
      {!mission ? <NotReady readiness={readiness} error={error} reload={reload} empty="No mission on this site yet." /> : <div className="row">
        <div className="top"><span className="tag">{mission.id.slice(0, 16)}</span><span className={`state ${mission.state === "completed" ? "resolved" : mission.state}`}>{stateWord[mission.state]}</span></div>
        <div className="mline"><span>goal {mission.goal.replace(/_/g, " ")}</span><span>budget {mission.budget} USD</span><span>by {mission.requester}</span><span>{age(mission.updatedAt)}</span></div>
      </div>}
      {recent.length > 1 ? <div className="sub" style={{ padding: "4px 4px 0", display: "flex", gap: 8, flexWrap: "wrap", fontSize: 13 }}><span className="muted">earlier:</span>{recent.filter(m => m.id !== mission?.id).map(m => <button key={m.id} className="link mono" onClick={() => onPick(m.id)}>{m.id.slice(0, 10)} · {stateWord[m.state]}</button>)}</div> : null}
    </div>
    {steps.length ? <div className="steps">{steps.map(s => <StepRow key={s.id} step={s} onOpenAttestation={onOpenAttestation} />)}</div> : null}
    {mission?.checklist?.length ? <table className="checklist"><thead><tr><th>Asset</th><th>Attribute</th><th>Value</th><th>Signed</th></tr></thead><tbody>{mission.checklist.map(c => <tr key={`${c.assetTag}:${c.attribute}`}><td className="mono">{c.assetTag}</td><td>{c.attribute.replace(/_/g, " ")}</td><td>{String(c.value)}</td><td className={c.valid ? "ok" : ""}><button className="link mono" onClick={() => onOpenAttestation(c.attestationId)}>{c.valid ? "valid" : "invalid"}</button></td></tr>)}</tbody></table> : null}
    {mission?.state === "failed" && mission.missing?.length ? <div className="panel-body"><div className="empty">Missing: {mission.missing.join(", ")}</div></div> : null}
  </Panel>;
}
function StepRow({ step, onOpenAttestation }: { step: MissionStep; onOpenAttestation: (id: string) => void }) {
  return <div className="step">
    <span className="at">{new Date(step.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
    <span><span className="who">{agentShort(step.agentId)}</span>{step.summary}{step.attestationId ? <> <button className="link mono" onClick={() => onOpenAttestation(step.attestationId!)}>{step.attestationId.slice(0, 10)}</button></> : null}{step.workItemId ? <> <a className="link mono" href={`/api/work-items/${encodeURIComponent(step.workItemId)}`} target="_blank" rel="noreferrer">{step.workItemId.slice(0, 10)}</a></> : null}</span>
  </div>;
}
const agentShort = (id: string) => id === "atlas" ? "Atlas" : id === "runner" ? "Runner" : id === "operator" ? "Operator" : id.startsWith("warden") ? "Warden" : id;

/* A2A chain Atlas → Warden → Runner: each node's state and last message, read from mission steps and a2a changes. */
interface ChainNode { id: string; name: string; state: A2AState | "none"; last: string; at: string }
export function chainFromMission(mission: Mission | null, changes: Change[], siteId: string): ChainNode[] {
  const ids = [{ id: "atlas", name: "Atlas" }, { id: `warden:${siteId}`, name: `Warden · ${siteName(siteId)}` }, { id: "runner", name: "Runner" }];
  const steps = [...(mission?.steps ?? [])].sort((a, b) => a.at.localeCompare(b.at));
  const a2a = changes.filter(c => c.type === "a2a").sort((a, b) => a.at.localeCompare(b.at));
  return ids.map(({ id, name }, i) => {
    const base = id.split(":")[0];
    const mine = steps.filter(s => s.agentId === id || s.agentId.split(":")[0] === base);
    const mention = a2a.filter(c => new RegExp(`\\b${base}\\b`, "i").test(c.summary));
    const lastStep = mine.at(-1); const lastChange = mention.at(-1);
    const last = lastStep && (!lastChange || lastStep.at >= lastChange.at) ? lastStep.summary : lastChange?.summary ?? "";
    const at = lastStep && (!lastChange || lastStep.at >= lastChange.at) ? lastStep.at : lastChange?.at ?? "";
    let state: ChainNode["state"] = "none";
    if (lastStep?.state) state = lastStep.state;
    else if (!mission) state = "none";
    else if (mission.state === "completed") state = mine.length || i === 0 ? "completed" : "none";
    else if (mission.state === "failed") state = mine.length ? "failed" : "none";
    else if (mission.state === "input_required") state = i === 0 ? "input_required" : mine.length ? "working" : "none";
    else state = mine.length ? "working" : i === 0 ? "submitted" : "none";
    return { id, name, state, last, at };
  });
}
function ChainPanel({ siteId, mission, changes }: { siteId: string; mission: Mission | null; changes: Change[] }) {
  const nodes = useMemo(() => chainFromMission(mission, changes, siteId), [mission, changes, siteId]);
  return <Panel title="Agent chain" count={mission ? "Atlas → Warden → Runner" : undefined}>
    <div className="chain">
      {nodes.map((n, i) => <div key={n.id}>
        {i > 0 ? <div className="arrow" aria-hidden="true" /> : null}
        <div className="node">
          <div className="head"><b>{n.name}</b><span className={`tstate ${n.state}`}>{taskWord[n.state]}</span></div>
          {n.last ? <div className="last">{n.last}{n.at ? <span className="muted"> · {age(n.at)}</span> : null}</div> : <div className="none">{mission ? "no task yet" : "starts with a mission"}</div>}
        </div>
      </div>)}
    </div>
  </Panel>;
}
