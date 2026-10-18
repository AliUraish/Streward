"use client";

/* /app/agent-view: what the agents see and say, live. At the top, what the agents read (the parse view) and the live
   readings as charts (agent-stream.tsx); then the latest eye frame of each of the three sites with a HUD of the tags in
   view, the stream of tool calls, eye moves and messages typing in, the agent map pulsing where agents work or talk,
   and token meters. Black and white; the streams are set in the mono face because they are machine traffic. */
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
import AgentStream from "./agent-stream";
import { useWalk } from "@/lib/hooks-7";
import { READING_TYPES, useLogs } from "@/lib/logs-9";

interface Ev { id: string; at: string; who: string; kind: "tool" | "a2a" | "eye" | "call"; text: string; tokens?: number | null }
/* A tool line once: plain verbs for messaging, without the detail's own copy of the tool name or its "a->b:" prefix. */
const TOOL_WORDS: Record<string, string> = { a2a_send: "message", a2a_reply: "reply", a2a_message: "message" };
function toolLine(tool: string, target?: string | null) {
  let detail = (target ?? "").trim();
  if (detail.toLowerCase().startsWith(tool.toLowerCase())) detail = detail.slice(tool.length).trim();
  detail = detail.replace(/^[a-z0-9-]+\s*->\s*[a-z0-9-]+:\s*/i, "");
  const word = TOOL_WORDS[tool] ?? tool;
  return detail ? `${word} ${detail}` : word;
}
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
  /* One activity poll per agent (the director, three teams of four, then the Site Inspector, the People Officer and
     Compliance Counsel); the hooks are called in a fixed order. */
  const a0 = useAgentActivity(acts[0]), a1 = useAgentActivity(acts[1]), a2 = useAgentActivity(acts[2]), a3 = useAgentActivity(acts[3]), a4 = useAgentActivity(acts[4]);
  const a5 = useAgentActivity(acts[5]), a6 = useAgentActivity(acts[6]), a7 = useAgentActivity(acts[7]), a8 = useAgentActivity(acts[8]);
  const a9 = useAgentActivity(acts[9]), a10 = useAgentActivity(acts[10]), a11 = useAgentActivity(acts[11]), a12 = useAgentActivity(acts[12]);
  const a13 = useAgentActivity(acts[13]), a14 = useAgentActivity(acts[14]), a15 = useAgentActivity(acts[15]);
  const activity = [a0, a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15];
  useHudEvents("all", {
    eye_frame: e => (feeds[e.siteId as SiteId3] ?? myer).reload(),
    agent_action: () => activity.forEach(r => r.reload()),
    conversation_line: () => { conversations.reload(); tasks.reload(); },
  });

  const events = useMemo(() => {
    const out: Ev[] = [];
    activity.forEach((r, i) => (r.data?.lastActions ?? []).forEach((c, j) => out.push({ id: `t:${acts[i]}:${c.at}:${j}`, at: c.at, who: acts[i], kind: "tool", text: toolLine(c.tool, c.target), tokens: c.tokens ?? null })));
    for (const f of [...(myer.data?.frames ?? []), ...(bristol.data?.frames ?? []), ...(tomioka.data?.frames ?? [])]) out.push({ id: `e:${f.id}`, at: f.at, who: f.actor ?? "", kind: "eye", text: `eye_${f.action ?? "look"} ${actionText(f)}${f.visiblePins.length ? `, sees ${f.visiblePins.filter(p => !p.occluded).map(p => p.assetTag).slice(0, 4).join(" ")}` : ""}` });
    for (const c of conversations.data ?? []) c.transcript.forEach((t, j) => out.push({ id: `c:${c.id}:${j}`, at: t.at ?? c.startedAt, who: t.speaker, kind: c.kind === "call" ? "call" : "a2a", text: `${c.participants.filter(p => p !== t.speaker).map(agentName).join(", ") || "all"}: ${t.text}` }));
    const known = (id: string) => !/harbor/.test(id);
    return out.filter(e => e.at && known(e.who) && known(e.text)).sort((a, b) => a.at.localeCompare(b.at)).slice(-12);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [myer.data, bristol.data, tomioka.data, conversations.data, tasks.data, ...activity.map(r => r.data)]);
  const anyLive = [myer, bristol, tomioka, conversations, tasks, findings, ...activity].some(r => r.readiness === "ready");
  /* The log: what happened across the sites, newest first, the same entries the dashboard's Logs page lists. */
  const log = useLogs(60, 5_000);
  const logLines = (log.data ?? []).filter(e => !READING_TYPES.has(e.type)).slice(0, 14);

  return <div className="agent-view" data-dissolve="">
    <header className="av-head">
      <h1>Agent view</h1>
      <p>What the agents see and say, live. Frames come from the agent eye; the stream is their tool calls, eye moves and messages.</p>
      <span className="av-clock" aria-label="UTC time">{clock} UTC</span>
    </header>
    <AgentStream />
    <div className="av-grid">
      <section className="av-eyes" aria-label="Agent eyes">
        {SITES3.map(s => { const feed = feeds[s.id]; return <EyePanel key={s.id} siteId={s.id} frames={feed.data?.frames ?? []} readiness={feed.readiness} renderers={feed.data?.renderers ? feed.data.renderers.filter(r => !r.stale).length : null} />; })}
      </section>
      <section className="av-stream" aria-label="Stream">
        <h2>Stream</h2>
        <ol role="log" aria-live="off">{events.length ? events.map((e, i) => <StreamRow key={e.id} e={e} typeIt={i >= events.length - 3} />) : <li className="quiet">{anyLive ? "Quiet. Nothing has happened in the last while." : "Waiting for the first tool calls, eye frames and messages."}</li>}</ol>
      </section>
      <section className="av-map" aria-label="Agent map"><h2>Agents</h2><MiniMap /></section>
      <section className="av-stream av-log" aria-label="Log">
        <h2>Log</h2>
        <ol role="log" aria-live="off">{logLines.length ? logLines.map(e => <li key={e.id}><span className="tm">{(() => { const d = new Date(e.at); return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(11, 19); })()}</span><span className="tx">{e.siteId} {e.type}{e.assetTag ? ` ${e.assetTag}` : ""}: {e.summary}</span></li>) : <li className="quiet">{log.readiness === "ready" ? "Nothing logged yet." : "Reading the log."}</li>}</ol>
      </section>
      <section className="av-meters" aria-label="Tokens this hour">
        <h2>Tokens this hour</h2>
        <Meters values={Object.fromEntries((findings.data?.agents ?? []).map(a => [a.agentId, a.tokensThisHour ?? 0]))} fallback={Object.fromEntries(activity.map((r, i) => [acts[i], r.data?.tokensThisHour ?? null]))} />

      </section>
    </div>
  </div>;
}

export function EyePanel({ siteId, frames, readiness, renderers }: { siteId: SiteId3; frames: EyeFrame[]; readiness: string; renderers: number | null }) {
  const s = site3(siteId);
  const live = useLive(siteId);
  const reported = live.presence?.rendererOnline ?? (renderers === null ? null : renderers > 0);
  const f = useMemo(() => [...frames].sort((a, b) => b.at.localeCompare(a.at))[0] ?? null, [frames]);
  const pos = f?.camera?.position;
  /* Moving or still: the site's walk says whether its engineer is walking, and a frame from the last 25 s means the camera
     just moved; agents and people read the same line. */
  const walk = useWalk(siteId, 3_000).data;
  const fresh = f ? Date.now() - new Date(f.at).getTime() < 25_000 : false;
  /* A frame from the last 25 s means the eye is rendering, whatever the presence list says (headless renderers do not always report). */
  const online = fresh ? true : reported;
  const moving = Boolean(walk?.walking) || fresh;
  const motion = moving
    ? `moving${walk?.walking && walk.stop && walk.of ? ` · ${walk.stop}/${walk.of}` : ""}${walk?.assetTag ? ` · ${walk.assetTag}` : ""}`
    : "still";
  /* A frame whose URL no longer loads (an expired signature) gives way to the capture's thumbnail. */
  const [broken, setBroken] = useState<string | null>(null);
  const src = f && broken !== f.frameUrl ? f.frameUrl : s.thumbnailUrl;
  return <figure className={`eye3 ${f ? "live" : ""} ${moving ? "moving" : "still"}`}>
    <div className="frame">
      <img key={f?.id ?? "thumbnail"} className={f ? "fresh" : ""} src={src} onError={() => { if (f && src === f.frameUrl) setBroken(f.frameUrl); }} alt={f && src === f.frameUrl ? `${s.name}: the frame ${agentName(f.actor)} last rendered` : `${s.name}: the capture's thumbnail; ${f ? "the latest frame did not load" : "the eye has not looked yet"}`} />
      {f ? <div className="hud">{f.visiblePins.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1).map(p => <span key={p.assetTag} className={`pin ${p.occluded ? "occluded" : ""}`} style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%` }}><i aria-hidden="true" />{p.assetTag}{typeof p.distance === "number" ? <small>{p.distance.toFixed(1)} m</small> : null}</span>)}</div> : null}
      <div className="hud-top"><strong>{s.short}</strong><span className={`mv ${moving ? "on" : ""}`} aria-label={`Camera ${motion}`}>{motion}</span>{online !== null ? <span className={`ren ${online ? "on" : ""}`}>{online ? "eye online" : "eye idle"}</span> : null}{f ? <span>{agentName(f.actor)}: {actionText(f)}</span> : <span>{readiness === "ready" ? "The eye has not looked yet" : readiness === "loading" ? "Connecting to the eye" : "Eye feed not available yet"}</span>}</div>
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

/* The agent map, small: squares that pulse when an agent works or talks; every pair that talked in the last 15 minutes
   gets a lit line (off-chart pairs too, such as the director and a site engineer or two sites' managers) with a dot
   running from the caller to the callee, and the list under it says who is talking to whom. */
type Talk = { from: string; to: string; at: string; kind: string; what: string };
const TALK_WINDOW_MS = 15 * 60_000;
function MiniMap() {
  const { overview, agents } = useShared();
  const rows = useNowRows(overview, agents);
  const { conversations } = useExchanges();
  const talks = useMemo(() => {
    const out = new Map<string, Talk>();
    const put = (from: string, to: string, at: string, kind: string, what: string) => {
      if (!from || !to || from === to || !(from in MAP_POS) || !(to in MAP_POS) || !at) return;
      if (Date.now() - new Date(at).getTime() > TALK_WINDOW_MS) return;
      const k = pairKey(from, to); const prev = out.get(k);
      if (!prev || at > prev.at) out.set(k, { from, to, at, kind, what });
    };
    for (const c of conversations.data ?? []) {
      const [first, ...rest] = c.participants;
      for (const other of rest) put(first, other, c.endedAt ?? c.startedAt, c.kind, c.summary?.headline ?? c.title ?? c.kind);
    }
    return [...out.values()].sort((a, b) => b.at.localeCompare(a.at));
  }, [conversations.data]);
  const talking = new Set(talks.flatMap(t => [t.from, t.to]));
  const lit = new Set(talks.map(t => pairKey(t.from, t.to)));
  const kindOf = (a: string, b: string) => MAP_EDGES.find(([x, y]) => pairKey(x, y) === pairKey(a, b))?.[2] ?? "line";
  const fixed = new Set(MAP_EDGES.map(([a, b]) => pairKey(a, b)));
  const still = reduced();
  const label: Record<string, string> = { operator: "Owner", director: "Director", dispatch: "Dispatch", "site-inspector": "Inspector", "people-officer": "People", "compliance-counsel": "Counsel" };
  const said = talks.length ? talks.slice(0, 3).map(t => `${agentName(t.from)} to ${agentName(t.to)}`).join("; ") : "no one is talking";
  return <>
    <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="mini3" role="img" aria-label={`Agent map: ${rows.filter(r => r.status === "working").map(r => r.name).join(", ") || "no agent"} working now; ${said}.`}>
      {CLUSTERS.map((c, i) => <text key={c.siteId} x={c.x + 20} y={c.y + 34} className="cl">{SITES3[i].short}</text>)}
      {MAP_EDGES.map(([a, b, kind]) => <path key={pairKey(a, b)} d={edgePath(a, b, kind)} className={`e ${lit.has(pairKey(a, b)) ? "lit" : ""}`} />)}
      {talks.filter(t => !fixed.has(pairKey(t.from, t.to))).map(t => <path key={`talk-${pairKey(t.from, t.to)}`} d={edgePath(t.from, t.to)} className="e lit talk" />)}
      {still ? null : talks.slice(0, 8).map(t => <circle key={`spark-${pairKey(t.from, t.to)}`} r={10} className="spark">
        <animateMotion dur="1.8s" repeatCount="indefinite" path={edgePath(t.from, t.to, kindOf(t.from, t.to))} />
      </circle>)}
      {Object.entries(MAP_POS).map(([id, [x, y]]) => { const r = rows.find(z => z.id === id); const busy = r?.status === "working" || talking.has(id);
        const role = label[id] ?? (id.split("-")[1] ?? "").replace(/^./, c => c.toUpperCase());
        return <g key={id} className={`n ${busy ? "busy" : ""}`} transform={`translate(${x},${y})`}>
          {busy ? <rect className="pulse" x={-34} y={-34} width={68} height={68} /> : null}
          <rect className="dot" x={-22} y={-22} width={44} height={44} />
          <text y={58} textAnchor="middle">{role}</text>
        </g>; })}
    </svg>
    <ol className="av-talks" aria-label="Who is talking to whom">
      {talks.length ? talks.slice(0, 5).map(t => <li key={`${pairKey(t.from, t.to)}-${t.at}`}>
        <span className="who"><strong>{agentName(t.from)}</strong> → <strong>{agentName(t.to)}</strong></span>
        <span className="what">{t.kind === "call" ? "chat" : t.kind}{t.what ? `: ${t.what}` : ""}</span>
        <span className="r3">{ago(t.at)}</span>
      </li>) : <li className="quiet">No one is talking right now.</li>}
    </ol>
  </>;
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
