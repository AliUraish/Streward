"use client";

/* /app/agents: the full agent map. The Owner's agent and the Operations Director at the top with the three cross-site
   agents beside the director (Site Inspector, Compliance Counsel, People Officer), the three site teams as clusters
   (manager, engineer, technician, compliance officer), the Steward Dispatch Line below. In each cluster the
   manager sits on top and the compliance officer at the foot, so the cross-site lines (manager to manager, compliance
   to compliance) run straight between clusters without crossing a node. Edges light up when a conversation or an A2A
   task between two agents happens; each node shows its task and status. Click a node for its activity, memory and
   tokens. On a phone the map becomes a list in the same order. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { Remote } from "@/lib/reality";
import { useA2ATasks, useConversations } from "@/lib/hooks-3";
import { AGENTS3, DISPATCH, SITES3, agentById, agentName } from "@/lib/sites-3";
import { SiteTitle } from "./ui3";
import { AgentDetail } from "./agent-detail";
import { useNowRows, type NowRow } from "./portfolio";
import { useShared } from "./shell";
import { NotYet, PageHead, Reveal, ago } from "./ui3";
import { useHudEvents } from "@/lib/live-3";

export const MAP_W = 1200, MAP_H = 960;
const W = MAP_W, H = MAP_H;
/* Three clusters of 372 by 500 at x 24, 414 and 804; centres 210, 600, 990. The team's name sits in the cluster's top
   left, above the manager. Rows: manager 395, engineer and technician 545 (96 either side of the centre), compliance
   695. The technician sits on the side nearer the dispatch line. */
export const CLUSTERS: { siteId: string; x: number; y: number; w: number; h: number }[] = SITES3.map((s, i) => ({ siteId: s.id, x: 24 + i * 390, y: 280, w: 372, h: 500 }));
const cx = (i: number) => 210 + i * 390;
export const MAP_POS: Record<string, [number, number]> = {
  operator: [600, 62], director: [600, 190],
  /* Contract 8: the cross-site agents share the director's row. */
  "site-inspector": [330, 190], "compliance-counsel": [870, 190], "people-officer": [1110, 190],
  "myer-manager": [cx(0), 395], "myer-engineer": [cx(0) - 96, 545], "myer-technician": [cx(0) + 96, 545], "myer-compliance": [cx(0), 695],
  "bristol-manager": [cx(1), 395], "bristol-engineer": [cx(1) - 96, 545], "bristol-technician": [cx(1) + 96, 545], "bristol-compliance": [cx(1), 695],
  "tomioka-manager": [cx(2), 395], "tomioka-technician": [cx(2) - 96, 545], "tomioka-engineer": [cx(2) + 96, 545], "tomioka-compliance": [cx(2), 695],
  dispatch: [600, 885],
};
export type EdgeKind = "line" | "arc-up" | "arc-down" | [number, number];
export const MAP_EDGES: [string, string, EdgeKind][] = [
  ["operator", "director", "line"], ["director", "myer-manager", "line"], ["director", "bristol-manager", "line"], ["director", "tomioka-manager", "line"],
  ...SITES3.map(s => s.id.split("-")[0]).flatMap(k => [[`${k}-manager`, `${k}-engineer`, "line"], [`${k}-manager`, `${k}-technician`, "line"], [`${k}-manager`, `${k}-compliance`, "line"]] as [string, string, EdgeKind][]),
  /* Cross-site, as the contracts allow it: manager to manager, compliance to compliance, between neighbouring clusters. */
  ["myer-manager", "bristol-manager", "line"], ["bristol-manager", "tomioka-manager", "line"],
  ["myer-compliance", "bristol-compliance", "line"], ["bristol-compliance", "tomioka-compliance", "line"],
  /* Bristol's technician bends round its compliance officer on the way down to the dispatch line. */
  ["myer-technician", "dispatch", "line"], ["bristol-technician", "dispatch", [800, 790]], ["tomioka-technician", "dispatch", "line"],
];
export const pairKey = (a: string, b: string) => [a, b].sort().join("|");
export function edgePath(a: string, b: string, kind: EdgeKind = "line") {
  const [x1, y1] = MAP_POS[a]; const [x2, y2] = MAP_POS[b];
  if (Array.isArray(kind)) return `M${x1},${y1}Q${kind[0]},${kind[1]} ${x2},${y2}`;
  /* A pair on one row with a cluster between them (Myer and Tomioka) arcs over the middle one. */
  if (kind === "line" && Math.abs(y1 - y2) < 1 && Math.abs(x1 - x2) > 400) kind = y1 < 520 ? "arc-up" : "arc-down";
  if (kind === "line") return `M${x1},${y1}L${x2},${y2}`;
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 + (kind === "arc-up" ? -150 : 150);
  return `M${x1},${y1}Q${mx},${my} ${x2},${y2}`;
}

/* Recent exchanges by pair: conversations (participants) and A2A tasks (caller, target), with the latest time. */
export function useExchanges() {
  const conversations = useConversations();
  const tasks = useA2ATasks();
  useHudEvents("all", { conversation_line: () => { conversations.reload(); tasks.reload(); } });
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
    <PageHead id="agents" title="Agents map" />
    <Reveal as="section" className="p3 map-panel" aria-labelledby="map-h">
      <div className="p-head"><h2 id="map-h">Who is talking to whom</h2><span className="meta">{ready ? `lit edges: an exchange in the last 15 minutes` : <NotYet remote={conversations as Remote<unknown>} what="conversations" />}</span></div>
      <div className="map3" role="group" aria-label="Agent map">
        <svg className="edges" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          {CLUSTERS.map(c => <rect key={c.siteId} className="cluster" x={c.x} y={c.y} width={c.w} height={c.h} />)}
          {MAP_EDGES.map(([a, b, kind]) => { const k = pairKey(a, b); return <path key={k} d={edgePath(a, b, kind)} className={`edge ${recent(k) ? "lit" : ""} ${flash[k] && now - flash[k] < 8000 ? "flash" : ""}`} />; })}
          {extra.map(k => { const [a, b] = k.split("|"); return <path key={k} d={edgePath(a, b)} className={`edge extra ${recent(k) ? "lit" : ""} ${flash[k] && now - flash[k] < 8000 ? "flash" : ""}`} />; })}
        </svg>
        {SITES3.map((s, i) => <span key={s.id} className="cluster-name" style={{ left: `${(CLUSTERS[i].x + 14) / W * 100}%`, top: `${(CLUSTERS[i].y + 12) / H * 100}%` }}><SiteTitle site={s} /> team</span>)}
        {[...AGENTS3.map(a => a.id), "dispatch"].map(id => <MapNode key={id} id={id} row={rows.find(r => r.id === id)} on={selected === id} talking={[...pairs.entries()].filter(([k]) => k.split("|").includes(id) && recent(k)).map(([k]) => k.split("|").find(x => x !== id) ?? "")} onClick={() => setSelected(id)} />)}
      </div>
    </Reveal>
    {me ? <AgentDetail key={me.id} me={me} info={agents.data?.find(x => x.id === me.id)} />
      : <Reveal className="p3"><div className="p-head"><h2>{DISPATCH.name}</h2></div><p className="r2">{DISPATCH.role}</p></Reveal>}
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
    <span className="r3" title={talking.length ? `Talking with ${talking.map(agentName).join(", ")}` : undefined}>{talking.length ? `talking with ${agentName(talking[0])}${talking.length > 1 ? ` and ${talking.length - 1} more` : ""}` : isDispatch ? "the one phone number" : row?.since ? `${status}, ${ago(row.since)}` : status}</span>
  </button>;
}
