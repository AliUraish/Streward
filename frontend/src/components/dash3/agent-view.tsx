"use client";

/* /app/agent-view: what the agents see and say, live. The latest eye frame of each of the three sites with a HUD of
   the tags in view, the stream of tool calls, eye moves and A2A messages typing in, the agent map pulsing where agents
   work or talk, and token meters. Black and white; the stream is set in the mono face because it is machine traffic. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useAgentActivity, useConversations, useEvalFindings, useEyeFeed, useA2ATasks } from "@/lib/hooks-3";
import { AGENTS3, SITES3, agentName, site3 } from "@/lib/sites-3";
import type { EyeFrame, SiteId3 } from "@/lib/types-3";
import { CLUSTERS, MAP_EDGES, MAP_H, MAP_POS, MAP_W, edgePath, pairKey, useExchanges } from "./agent-map";
import { actionText } from "./environment";
import { useNowRows } from "./portfolio";
import { useShared } from "./shell";
import { ago } from "./ui3";
import { useHudEvents, useLive } from "@/lib/live-3";

interface Ev { id: string; at: string; who: string; kind: "tool" | "a2a" | "eye" | "call"; text: string; tokens?: number | null }
const reduced = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

export default function AgentView() {
  const [clock, setClock] = useState("");
  useEffect(() => { const t = () => setClock(new Date().toISOString().slice(11, 19)); t(); const id = setInterval(t, 1000); return () => clearInterval(id); }, []);
  const myer = useEyeFeed("myer-plant", 2_000);
  const bristol = useEyeFeed("bristol-pumps", 2_000);
  const tomioka = useEyeFeed("tomioka-mill", 2_000);
  const feeds = { "myer-plant": myer, "bristol-pumps": bristol, "tomioka-mill": tomioka } as const;
  const conversations = useConversations();
  const tasks = useA2ATasks();
  const findings = useEvalFindings();
  const acts = AGENTS3.map(a => a.id).filter(id => id !== "operator");
  /* One activity poll per agent (the director and three teams of four); the hooks are called in a fixed order. */
  const a0 = useAgentActivity(acts[0]), a1 = useAgentActivity(acts[1]), a2 = useAgentActivity(acts[2]), a3 = useAgentActivity(acts[3]), a4 = useAgentActivity(acts[4]);
  const a5 = useAgentActivity(acts[5]), a6 = useAgentActivity(acts[6]), a7 = useAgentActivity(acts[7]), a8 = useAgentActivity(acts[8]);
  const a9 = useAgentActivity(acts[9]), a10 = useAgentActivity(acts[10]), a11 = useAgentActivity(acts[11]), a12 = useAgentActivity(acts[12]);
  const activity = [a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12];
  useHudEvents("all", {
    eye_frame: e => (feeds[e.siteId as SiteId3] ?? myer).reload(),
    agent_action: () => activity.forEach(r => r.reload()),
    conversation_line: () => { conversations.reload(); tasks.reload(); },
  });
  const live = useLive();

  const events = useMemo(() => {
    const out: Ev[] = [];
    activity.forEach((r, i) => (r.data?.lastActions ?? []).forEach((c, j) => out.push({ id: `t:${acts[i]}:${c.at}:${j}`, at: c.at, who: acts[i], kind: "tool", text: `${c.tool}${c.target ? ` ${c.target}` : ""}`, tokens: c.tokens ?? null })));
    for (const f of [...(myer.data?.frames ?? []), ...(bristol.data?.frames ?? []), ...(tomioka.data?.frames ?? [])]) out.push({ id: `e:${f.id}`, at: f.at, who: f.actor ?? "", kind: "eye", text: `eye_${f.action ?? "look"} ${actionText(f)}${f.visiblePins.length ? `, sees ${f.visiblePins.filter(p => !p.occluded).map(p => p.assetTag).slice(0, 4).join(" ")}` : ""}` });
    for (const c of conversations.data ?? []) c.transcript.forEach((t, j) => out.push({ id: `c:${c.id}:${j}`, at: t.at ?? c.startedAt, who: t.speaker, kind: c.kind === "call" ? "call" : "a2a", text: `${c.participants.filter(p => p !== t.speaker).map(agentName).join(", ") || "all"}: ${t.text}` }));
    for (const t of tasks.data ?? []) out.push({ id: `a:${t.id}:${t.state}`, at: t.at, who: t.caller, kind: "a2a", text: `${agentName(t.target)}: task ${t.state}` });
    const known = (id: string) => !/harbor/.test(id);
    return out.filter(e => e.at && known(e.who) && known(e.text)).sort((a, b) => a.at.localeCompare(b.at)).slice(-12);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [myer.data, bristol.data, tomioka.data, conversations.data, tasks.data, ...activity.map(r => r.data)]);
  const anyLive = [myer, bristol, tomioka, conversations, tasks, findings, ...activity].some(r => r.readiness === "ready");

  return <div className="agent-view" data-dissolve="">
    <header className="av-head">
      <h1>Agent view</h1>
      <p>What the agents see and say, live. Frames come from the agent eye; the stream is their tool calls, eye moves and A2A messages.</p>
      <span className="av-clock" aria-label="UTC time">{clock} UTC</span>
      <span className="av-live">{live.realtime ? "realtime" : "polling every 2 to 6 s"}</span>
    </header>
    <div className="av-grid">
      <section className="av-eyes" aria-label="Agent eyes">
        {SITES3.map(s => { const feed = feeds[s.id]; return <EyePanel key={s.id} siteId={s.id} frames={feed.data?.frames ?? []} readiness={feed.readiness} renderers={feed.data?.renderers ? feed.data.renderers.filter(r => !r.stale).length : null} />; })}
      </section>
      <section className="av-stream" aria-label="Stream">
        <h2>Stream</h2>
        <ol role="log" aria-live="off">{events.length ? events.map((e, i) => <StreamRow key={e.id} e={e} typeIt={i >= events.length - 3} />) : <li className="quiet">{anyLive ? "Quiet. Nothing has happened in the last while." : "Waiting for the first tool calls, eye frames and messages."}</li>}</ol>
      </section>
      <section className="av-map" aria-label="Agent map"><h2>Agents</h2><MiniMap /></section>
      <section className="av-meters" aria-label="Tokens this hour">
        <h2>Tokens this hour</h2>
        <Meters values={Object.fromEntries((findings.data?.agents ?? []).map(a => [a.agentId, a.tokensThisHour ?? 0]))} fallback={Object.fromEntries(activity.map((r, i) => [acts[i], r.data?.tokensThisHour ?? null]))} />
        <p className="src">{(findings.data?.source || "Steward telemetry").replace(/,?\s*also delivered to Armature/i, "")}; estimates, not billed usage.</p>
      </section>
    </div>
  </div>;
}

function EyePanel({ siteId, frames, readiness, renderers }: { siteId: SiteId3; frames: EyeFrame[]; readiness: string; renderers: number | null }) {
  const s = site3(siteId);
  const live = useLive(siteId);
  const online = live.presence?.rendererOnline ?? (renderers === null ? null : renderers > 0);
  const f = useMemo(() => [...frames].sort((a, b) => b.at.localeCompare(a.at))[0] ?? null, [frames]);
  const pos = f?.camera?.position;
  /* A frame whose URL no longer loads (an expired signature) gives way to the capture's thumbnail. */
  const [broken, setBroken] = useState<string | null>(null);
  const src = f && broken !== f.frameUrl ? f.frameUrl : s.thumbnailUrl;
  return <figure className={`eye3 ${f ? "live" : ""}`}>
    <div className="frame">
      <img src={src} onError={() => { if (f && src === f.frameUrl) setBroken(f.frameUrl); }} alt={f && src === f.frameUrl ? `${s.name}: the frame ${agentName(f.actor)} last rendered` : `${s.name}: the capture's thumbnail; ${f ? "the latest frame did not load" : "the eye has not looked yet"}`} />
      {f ? <div className="hud">{f.visiblePins.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1).map(p => <span key={p.assetTag} className={`pin ${p.occluded ? "occluded" : ""}`} style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}><i aria-hidden="true" />{p.assetTag}{typeof p.distance === "number" ? <small>{p.distance.toFixed(1)} m</small> : null}</span>)}</div> : null}
      <div className="hud-top"><strong>{s.short}</strong>{online !== null ? <span className={`ren ${online ? "on" : ""}`}>{online ? "renderer online" : "no renderer"}</span> : null}{f ? <span>{agentName(f.actor)}: {actionText(f)}</span> : <span>{readiness === "ready" ? "The eye has not looked yet" : readiness === "loading" ? "Connecting to the eye" : "Eye feed not available yet"}</span>}</div>
      <div className="hud-bottom">{f ? <><span>{pos && pos.length >= 3 ? `pos ${pos.slice(0, 3).map(v => Number(v).toFixed(1)).join(", ")}` : ""}{f.camera?.fov ? ` · fov ${Math.round(f.camera.fov)}` : ""}</span><span>{ago(f.at)} · {f.visiblePins.filter(p => !p.occluded).length} tags in view</span></> : <span>{s.place}</span>}</div>
    </div>
  </figure>;
}

/* A stream line types itself in when it is new; reduced motion shows it whole. */
function StreamRow({ e, typeIt }: { e: Ev; typeIt: boolean }) {
  const full = `${agentName(e.who)} ${e.kind === "tool" ? "→" : e.kind === "eye" ? "◉" : "⇄"} ${e.text}`;
  const [count, setCount] = useState(typeIt ? 0 : full.length);
  const done = useRef(!typeIt);
  useEffect(() => {
    if (done.current || !typeIt || reduced()) { done.current = true; setCount(full.length); return; }
    let raf = 0; const t0 = performance.now(); const dur = Math.min(1400, 18 * full.length);
    const step = (t: number) => { const k = Math.min(1, (t - t0) / dur); setCount(Math.ceil(k * full.length)); if (k < 1) raf = requestAnimationFrame(step); else done.current = true; };
    raf = requestAnimationFrame(step); return () => cancelAnimationFrame(raf);
  }, [typeIt, full]);
  const time = (() => { const d = new Date(e.at); return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(11, 19); })();
  return <li className={`k-${e.kind}`}><span className="tm">{time}</span><span className="tx" aria-label={full}>{full.slice(0, count)}{count < full.length ? <span className="caret" aria-hidden="true" /> : null}</span>{e.tokens ? <span className="tk">{e.tokens} tok</span> : null}</li>;
}

/* The agent map, small: squares that pulse when an agent works or talks; edges that light with recent exchanges. */
function MiniMap() {
  const { overview, agents } = useShared();
  const rows = useNowRows(overview, agents);
  const { pairs } = useExchanges();
  const now = Date.now();
  const recent = (k: string) => { const p = pairs.get(k); return p ? now - new Date(p.at).getTime() < 15 * 60_000 : false; };
  const talking = new Set([...pairs.keys()].filter(recent).flatMap(k => k.split("|")));
  const label: Record<string, string> = { operator: "Owner", director: "Director", dispatch: "Dispatch" };
  return <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="mini3" role="img" aria-label={`Agent map: ${rows.filter(r => r.status === "working").map(r => r.name).join(", ") || "no agent"} working now; ${talking.size ? `${[...talking].map(agentName).join(", ")} talking` : "no recent exchanges"}.`}>
    {CLUSTERS.map((c, i) => <text key={c.siteId} x={c.x + 20} y={c.y + 34} className="cl">{SITES3[i].short}</text>)}
    {MAP_EDGES.map(([a, b, kind]) => <path key={pairKey(a, b)} d={edgePath(a, b, kind)} className={`e ${recent(pairKey(a, b)) ? "lit" : ""}`} />)}
    {Object.entries(MAP_POS).map(([id, [x, y]]) => { const r = rows.find(z => z.id === id); const busy = r?.status === "working" || talking.has(id);
      const role = label[id] ?? (id.split("-")[1] ?? "").replace(/^./, c => c.toUpperCase());
      return <g key={id} className={`n ${busy ? "busy" : ""}`} transform={`translate(${x},${y})`}>
        {busy ? <rect className="pulse" x={-34} y={-34} width={68} height={68} /> : null}
        <rect className="dot" x={-22} y={-22} width={44} height={44} />
        <text y={58} textAnchor="middle">{role}</text>
      </g>; })}
  </svg>;
}

function Meters({ values, fallback }: { values: Record<string, number>; fallback: Record<string, number | null> }) {
  const ids = AGENTS3.map(a => a.id).filter(id => id !== "operator");
  const v = (id: string) => values[id] ?? fallback[id] ?? null;
  const known = ids.filter(id => v(id) !== null);
  const max = Math.max(1, ...known.map(id => v(id) as number));
  if (!known.length) return <p className="quiet">No token telemetry yet.</p>;
  return <ul className="meters">{ids.map(id => { const x = v(id); return <li key={id}>
    <span className="who">{agentName(id)}</span>
    <span className="bar" aria-hidden="true"><span style={{ transform: `scaleX(${x === null ? 0 : Math.max(0.01, x / max)})` }} /></span>
    <span className="val">{x === null ? "–" : new Intl.NumberFormat().format(x)}</span>
  </li>; })}</ul>;
}
