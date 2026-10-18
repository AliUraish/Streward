"use client";

/* /app/agents: the full agent map. The Owner's agent and the Operations Director at the top, the two factory teams as
   clusters (plant manager, site engineer, compliance officer, field technician), the Steward Dispatch Line below.
   Edges light up when a conversation or an A2A task between two agents happens; each node shows its task and status.
   Click a node for its activity, memory and tokens. On a phone the map becomes a list in the same order. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { Remote } from "@/lib/reality";
import { useA2ATasks, useConversations } from "@/lib/hooks-3";
import { AGENTS3, DISPATCH, SITES3, agentById, agentName } from "@/lib/sites-3";
import { AgentDetail, useSpeaker } from "./agent-detail";
import { useNowRows, type NowRow } from "./portfolio";
import { useShared } from "./shell";
import { NotYet, PageHead, Reveal, ago } from "./ui3";

const W = 1200, H = 720;
export const MAP_POS: Record<string, [number, number]> = {
  operator: [600, 56], director: [600, 176],
  "myer-manager": [300, 330], "myer-engineer": [128, 492], "myer-compliance": [300, 492], "myer-technician": [472, 492],
  "bristol-manager": [900, 330], "bristol-engineer": [728, 492], "bristol-compliance": [900, 492], "bristol-technician": [1072, 492],
  dispatch: [600, 650],
};
export const MAP_EDGES: [string, string, "line" | "arc-up" | "arc-down"][] = [
  ["operator", "director", "line"], ["director", "myer-manager", "line"], ["director", "bristol-manager", "line"],
  ["myer-manager", "myer-engineer", "line"], ["myer-manager", "myer-compliance", "line"], ["myer-manager", "myer-technician", "line"],
  ["bristol-manager", "bristol-engineer", "line"], ["bristol-manager", "bristol-compliance", "line"], ["bristol-manager", "bristol-technician", "line"],
  ["myer-manager", "bristol-manager", "arc-up"], ["myer-compliance", "bristol-compliance", "arc-down"],
  ["myer-technician", "dispatch", "line"], ["bristol-technician", "dispatch", "line"],
];
export const pairKey = (a: string, b: string) => [a, b].sort().join("|");
export function edgePath(a: string, b: string, kind: "line" | "arc-up" | "arc-down" = "line") {
  const [x1, y1] = MAP_POS[a]; const [x2, y2] = MAP_POS[b];
  if (kind === "line") return `M${x1},${y1}L${x2},${y2}`;
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 + (kind === "arc-up" ? -70 : 96);
  return `M${x1},${y1}Q${mx},${my} ${x2},${y2}`;
}

/* Recent exchanges by pair: conversations (participants) and A2A tasks (caller, target), with the latest time. */
export function useExchanges() {
  const conversations = useConversations();
  const tasks = useA2ATasks();
  const pairs = useMemo(() => {
    const m = new Map<string, { at: string; what: string }>();
    const add = (a: string, b: string, at: string, what: string) => { if (!a || !b || a === b || !(a in MAP_POS) || !(b in MAP_POS)) return; const k = pairKey(a, b); const prev = m.get(k); if (!prev || at > prev.at) m.set(k, { at, what }); };
    for (const c of conversations.data ?? []) { const ps = c.participants; for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) add(ps[i], ps[j], c.endedAt ?? c.startedAt, c.summary?.headline ?? c.title ?? c.kind); }
    for (const t of tasks.data ?? []) add(t.caller, t.target, t.at, "A2A task");
    return m;
  }, [conversations.data, tasks.data]);
  return { pairs, conversations, tasks };
}

export default function AgentMapPage() {
  const { overview, agents } = useShared();
  const rows = useNowRows(overview, agents);
  const { pairs, conversations, tasks } = useExchanges();
  const [selected, setSelected] = useState<string>("director");
  const speaker = useSpeaker();
  /* An edge flashes when its pair's latest exchange is newer than what this page has seen. */
  const seen = useRef<Map<string, string>>(new Map());
  const [flash, setFlash] = useState<Record<string, number>>({});
  useEffect(() => {
    const fresh: Record<string, number> = {};
    for (const [k, v] of pairs) { const before = seen.current.get(k); if (before !== undefined && v.at > before) fresh[k] = Date.now(); seen.current.set(k, v.at); }
    if (Object.keys(fresh).length) setFlash(f => ({ ...f, ...fresh }));
  }, [pairs]);
  const now = Date.now();
  const recent = (k: string) => { const p = pairs.get(k); return p ? now - new Date(p.at).getTime() < 15 * 60_000 : false; };
  const extra = [...pairs.keys()].filter(k => !MAP_EDGES.some(([a, b]) => pairKey(a, b) === k));
  const me = agentById(selected);
  const ready = conversations.readiness === "ready" || tasks.readiness === "ready";
  return <div className="page3">
    <PageHead id="agents" title="Agents map" sub="Eleven seats: the Owner's agent, the Operations Director, two factory teams of four and the Steward Dispatch Line. Cross-site talk runs manager to manager, compliance to compliance, or through the director." />
    <Reveal as="section" className="p3 map-panel" aria-labelledby="map-h">
      <div className="p-head"><h2 id="map-h">Who is talking to whom</h2><span className="meta">{ready ? `lit edges: an exchange in the last 15 minutes` : <NotYet remote={conversations as Remote<unknown>} what="conversations" />}</span></div>
      <div className="map3" role="group" aria-label="Agent map">
        <svg className="edges" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          {SITES3.map((s, i) => <rect key={s.id} className="cluster" x={i ? 640 : 40} y={262} width={520} height={300} />)}
          {MAP_EDGES.map(([a, b, kind]) => { const k = pairKey(a, b); return <path key={k} d={edgePath(a, b, kind)} className={`edge ${recent(k) ? "lit" : ""} ${flash[k] && now - flash[k] < 8000 ? "flash" : ""}`} />; })}
          {extra.map(k => { const [a, b] = k.split("|"); return <path key={k} d={edgePath(a, b)} className={`edge extra ${recent(k) ? "lit" : ""} ${flash[k] && now - flash[k] < 8000 ? "flash" : ""}`} />; })}
        </svg>
        {SITES3.map((s, i) => <span key={s.id} className="cluster-name" style={{ left: `${((i ? 640 : 40) + 16) / W * 100}%`, top: `${(262 + 14) / H * 100}%` }}>{s.name}</span>)}
        {[...AGENTS3.map(a => a.id), "dispatch"].map(id => <MapNode key={id} id={id} row={rows.find(r => r.id === id)} on={selected === id} talking={[...pairs.entries()].filter(([k]) => k.split("|").includes(id) && recent(k)).map(([k]) => k.split("|").find(x => x !== id) ?? "")} onClick={() => setSelected(id)} />)}
      </div>
    </Reveal>
    {me ? <AgentDetail key={me.id} me={me} info={agents.data?.find(x => x.id === me.id)} speaker={speaker} />
      : <Reveal className="p3"><div className="p-head"><h2>{DISPATCH.name}</h2></div><p className="r2">{DISPATCH.role} It is a phone number, not an agent: it has no memory or tasks of its own, and only the duty engineer (the user) is ever reached through it in live mode.</p></Reveal>}
  </div>;
}

function MapNode({ id, row, on, talking, onClick }: { id: string; row?: NowRow; on: boolean; talking: string[]; onClick: () => void }) {
  const [x, y] = MAP_POS[id];
  const isDispatch = id === "dispatch";
  const status = isDispatch ? "line" : row?.status ?? (row?.known ? "idle" : "unknown");
  const lvl = isDispatch ? "dispatch" : agentById(id)?.level;
  return <button type="button" className={`node3 l${lvl} ${on ? "on" : ""} ${talking.length ? "talking" : ""} ${status === "working" ? "working" : ""}`} style={{ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` }} aria-pressed={on} onClick={onClick}>
    <span className="r1"><span className={`sig ${isDispatch ? "off" : status === "working" ? "ok" : status === "waiting" ? "warn" : "off"}`} aria-hidden="true" /><strong>{isDispatch ? DISPATCH.name : agentName(id)}</strong></span>
    <span className="task">{isDispatch ? "SMS and calls to people" : row?.task ?? (row?.known ? "No task" : "Status not available yet")}</span>
    <span className="r3">{talking.length ? `talking with ${talking.map(agentName).join(", ")}` : isDispatch ? "the one phone number" : row?.since ? `${status}, ${ago(row.since)}` : status}</span>
  </button>;
}
