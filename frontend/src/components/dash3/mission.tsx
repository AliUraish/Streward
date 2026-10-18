"use client";

/* The mission view: the scan fills the screen and the factory team's work floats over it as HUD panels, in the
   dashboard's black and white. Tone-step panels at about 90 percent, no blur, no shadows, Geist; the mono face only
   for asset tags and record ids; white marks what is active, the one issue signal marks what is wrong. It leads with
   what is ours: the signed proof, the regulation cited, the team. Every panel collapses; Hide HUD clears them. */
import { useMemo, useState, type ReactNode } from "react";
import type { Remote } from "@/lib/reality";
import { api3 } from "@/lib/api-3";
import { useAgentConfig, useCrew, useEvalFindings, useEvals3, useFixWorkflows, useNotices, usePoll } from "@/lib/hooks-3";
import { REGULATIONS_PACK, jurisdictionName, regsForIssue, regsForSite, siteJurisdiction } from "@/lib/regulations-3";
import { DISPATCH, EVAL_SUITES3, PEERS, agentName, roleOf, site3, teamOf } from "@/lib/sites-3";
import type { AgentConfig, EyeFrame, Issue3, SiteId3, WhyRef } from "@/lib/types-3";
import { pairKey, useExchanges } from "./agent-map";
import { useLive } from "@/lib/live-3";
import { actionText } from "./environment";
import { useNowRows } from "./portfolio";
import { useShared } from "./shell";

const tzOf = (siteId: SiteId3) => site3(siteId).tz;
const RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };
const fmtTime = (iso: string | number | Date, tz: string) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false }).format(d); };
const shortRef = (r: { instrument?: string | null; provision?: string | null }) => `${(r.instrument ?? "").replace(/\s*\(.*$/, "")}${r.provision ? `, ${r.provision.replace(/\s*\(.*$/, "")}` : ""}`;
const pct = (v: number | null) => v === null ? "–" : `${Math.round(v)}%`;
const num = (v: number | null) => v === null ? "–" : new Intl.NumberFormat().format(Math.round(v));

export interface MissionProps {
  siteId: SiteId3; frames: EyeFrame[]; issues: Issue3[]; hidden: boolean; now: number; renderers?: number;
  onFocus: (assetTag: string) => void; onHide: () => void; onExit: () => void;
}

export default function MissionHud({ siteId, frames, issues, hidden, now, renderers, onFocus, onHide, onExit }: MissionProps) {
  const site = site3(siteId);
  const live = useLive(siteId);
  /* Presence from the realtime channel (tabs watching, a renderer tab online) when it is live; else the eye feed's own
     renderer list, polled. */
  const fromFeed = renderers !== undefined ? renderers > 0 : null;
  const rendererOnline = live.presence ? live.presence.rendererOnline || Boolean(fromFeed) : fromFeed;
  const watchers = live.presence?.watchers.length ?? null;
  const presenceText = [watchers !== null ? `${watchers} watching` : "", rendererOnline === null ? "" : rendererOnline ? "eye renderer online" : "no eye renderer", live.realtime ? "realtime" : "polling"].filter(Boolean).join(" · ");
  /* The site clock: the site's local time, now. */
  const clock = `${fmtTime(now, tzOf(siteId))} · ${tzOf(siteId).split("/")[1].replace(/_/g, " ")}`;
  const latest = [...frames].sort((a, b) => b.at.localeCompare(a.at))[0] ?? null;
  return <div className={`mission-hud ${hidden ? "hud-off" : ""}`}>
    <header className="mh-top">
      <span className="brand"><strong>Steward</strong> · {site.name} · run by the {site.short} team</span>
      <span className="presence" title={live.realtime ? "Presence on the site's realtime channel" : "Realtime is off; the eye feed is polled"}>{presenceText}</span>
      <span className="clock" title={`Site time, ${tzOf(siteId)}`}>{clock}</span>
      <span className="mh-actions">
        <button type="button" className="mh-btn" aria-pressed={hidden} onClick={onHide}>{hidden ? "Show HUD" : "Hide HUD"}</button>
        <button type="button" className="mh-btn" onClick={onExit}>Exit <span className="key">Esc</span></button>
      </span>
    </header>
    {!hidden ? <>
      <div className="mh-left">
        <Panel title="Agent cameras" meta={frames.length ? `latest ${Math.min(frames.length, 6)} frame${Math.min(frames.length, 6) === 1 ? "" : "s"}` : "views of the site until the eye looks"}><Cameras siteId={siteId} frames={frames} issues={issues} onFocus={onFocus} /></Panel>
        <Panel title="Evals per version" meta="Steward telemetry"><EvalVersions siteId={siteId} /></Panel>
        <Panel title="Changes to the next version" meta="by the Operations Director"><NextChanges siteId={siteId} /></Panel>
      </div>
      <div className="mh-right">
        <Panel title="Alerts" meta={`site time, ${tzOf(siteId).split("/")[1].replace("_", " ")}`}><Alerts siteId={siteId} issues={issues} onFocus={onFocus} /></Panel>
        <Panel title={`Team · ${site.short}`} meta="calls, email, dispatch line"><TeamGraph siteId={siteId} actor={latest?.actor ?? null} /></Panel>
      </div>
      <LiveLine siteId={siteId} frame={latest} />
    </> : null}
  </div>;
}

function Panel({ title, meta, children }: { title: string; meta?: string; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  return <section className={`mh-panel ${open ? "" : "shut"}`} aria-label={title}>
    <button type="button" className="mh-head" aria-expanded={open} onClick={() => setOpen(o => !o)}>
      <span className="t">{title}</span>{meta ? <span className="m">{meta}</span> : null}<span className="tog" aria-hidden="true">{open ? "−" : "+"}</span>
    </button>
    {open ? <div className="mh-body">{children}</div> : null}
  </section>;
}

/* A 3 × 2 grid of the latest eye frames; each says who looked at what, how many tags it sees and how many have issues. */
function Cameras({ siteId, frames, issues, onFocus }: { siteId: SiteId3; frames: EyeFrame[]; issues: Issue3[]; onFocus: (tag: string) => void }) {
  const site = site3(siteId);
  const openTags = new Set(issues.filter(i => !i.status || i.status !== "resolved").map(i => i.assetTag));
  const tiles = [...frames].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 6);
  /* Until the eye has looked six times, the empty tiles show views of the site (or its overview where none exist). */
  const renders = site.frames.length ? site.frames : [site.thumbnailUrl];
  const fill = Array.from({ length: Math.max(0, 6 - tiles.length) }, (_, i) => renders[i % renders.length]);
  return <ol className="mh-cams">
    {tiles.map(f => {
      const seen = f.visiblePins.filter(p => !p.occluded);
      const hit = seen.filter(p => openTags.has(p.assetTag)).length;
      const tag = (f.params as { assetTag?: string } | null)?.assetTag ?? seen[0]?.assetTag ?? "";
      return <li key={f.id} className={hit ? "issue" : ""}>
        <button type="button" onClick={() => tag && onFocus(tag)} aria-label={`${agentName(f.actor)} ${actionText(f)}; ${seen.length} assets in view, ${hit} with issues`}>
          <img src={f.frameUrl} alt="" />
          <span className="cap"><span className="who">{agentName(f.actor).split(" · ")[0]}{tag ? <> · <code>{tag}</code></> : null}</span><span className="n">{seen.length} asset{seen.length === 1 ? "" : "s"} · {hit} issue{hit === 1 ? "" : "s"}</span></span>
        </button>
      </li>;
    })}
    {fill.map((src, i) => <li key={`fill-${i}`} className="fill"><span className="ph"><img src={src} alt="" /><span className="cap"><span className="who">{site.frames.length ? `view ${(i % site.frames.length) + 1}` : "overview"}</span></span></span></li>)}
  </ol>;
}

/* Suites × agent-config versions: v1 before the director's first reconfigure, v2 after. The backend's byVersion is used
   when it sends one; otherwise the runs and telemetry are split at the reconfigure. Best value per row in white. */
function EvalVersions({ siteId }: { siteId: SiteId3 }) {
  const runs = useEvals3(false);
  const findings = useEvalFindings();
  const configs = useTeamConfigs(siteId);
  const T = configs.reconfigures[0]?.at ?? null;
  const after = usePoll(() => T ? api3.evalFindings(T) : Promise.resolve(null), [T], 20_000);
  const rows = useMemo(() => {
    const list = runs.data ?? [];
    const split = (suite: string, v: "v1" | "v2") => list.filter(r => r.suite === suite && (!T || (v === "v1" ? r.startedAt < T : r.startedAt >= T)));
    const pass = (rs: typeof list) => { const p = rs.reduce((a, r) => a + r.passed, 0), f = rs.reduce((a, r) => a + r.failed, 0); return p + f ? (p / (p + f)) * 100 : null; };
    const blocked = (rs: typeof list) => rs.length ? rs.reduce((a, r) => a + r.steps.filter(s => s.result === "PASS" && /denied|blocked|reject|cannot|refus/i.test(`${s.name} ${s.detail}`)).length, 0) : null;
    const tpm = (agents: { tokensPerMission: number | null; missions?: number | null }[] | undefined) => { const a = (agents ?? []).filter(x => x.tokensPerMission !== null && (x.missions ?? 0) > 0); const m = a.reduce((s, x) => s + (x.missions ?? 0), 0); return m ? a.reduce((s, x) => s + (x.tokensPerMission ?? 0) * (x.missions ?? 0), 0) / m : null; };
    const all = findings.data?.agents; const since = after.data?.agents;
    const allM = (all ?? []).reduce((s, x) => s + (x.missions ?? 0), 0), sinceM = (since ?? []).reduce((s, x) => s + (x.missions ?? 0), 0);
    const tAll = tpm(all), tSince = tpm(since);
    const tV1 = T && tAll !== null && tSince !== null && allM > sinceM ? (tAll * allM - tSince * sinceM) / (allM - sinceM) : tAll;
    return EVAL_SUITES3.map(s => ({ suite: s.name, v1: { pass: pass(split(s.id, "v1")), tokens: tV1, blocked: blocked(split(s.id, "v1")) }, v2: T ? { pass: pass(split(s.id, "v2")), tokens: tSince, blocked: blocked(split(s.id, "v2")) } : null }));
  }, [runs.data, findings.data, after.data, T]);
  if (runs.readiness !== "ready" && findings.readiness !== "ready") return <p className="mh-empty">{runs.readiness === "loading" ? "Loading eval runs." : "Eval runs are not available yet."}</p>;
  const cell = (v: number | null, other: number | null, better: "high" | "low", text: string) => {
    const best = v !== null && (other === null || (better === "high" ? v >= other : v <= other));
    return <td className={best ? "best" : ""}>{text}</td>;
  };
  return <table className="mh-table">
    <thead><tr><th scope="col">Suite</th><th scope="col">v1</th>{rows[0]?.v2 ? <th scope="col">v2</th> : null}</tr></thead>
    <tbody>{rows.map(r => {
      const reg = r.v2 && r.v1.pass !== null && r.v2.pass !== null && r.v2.pass < r.v1.pass;
      return <tr key={r.suite} className={reg ? "regressed" : ""}>
        <th scope="row">{r.suite}{reg ? <span className="flag">regressed</span> : null}</th>
        {cell(r.v1.pass, r.v2?.pass ?? null, "high", `${pct(r.v1.pass)} · ${num(r.v1.tokens)} tok${r.v1.blocked ? ` · ${r.v1.blocked} blocked` : ""}`)}
        {r.v2 ? cell(r.v2.pass, r.v1.pass, "high", `${pct(r.v2.pass)} · ${num(r.v2.tokens)} tok${r.v2.blocked ? ` · ${r.v2.blocked} blocked` : ""}`) : null}
      </tr>;
    })}</tbody>
    <caption>Pass rate · tokens per mission · unsafe actions blocked.{configs.reconfigures[0] ? ` v2 from ${new Date(configs.reconfigures[0].at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.` : " No reconfigure yet, so one version."}</caption>
  </table>;
}

/* The configs of the site's team and the director, with every change the director made. */
function useTeamConfigs(siteId: SiteId3) {
  const ids = teamOf(siteId).map(a => a.id);
  const c0 = useAgentConfig(ids[0]), c1 = useAgentConfig(ids[1]), c2 = useAgentConfig(ids[2]), c3 = useAgentConfig(ids[3]), cd = useAgentConfig("director");
  /* The compliance officers this site talks to (Bristol has two peers, Myer and Tomioka one each); hooks in fixed order. */
  const peers = PEERS[siteId].map(p => roleOf(p, "compliance").id);
  const p0 = useAgentConfig(peers[0]), p1 = useAgentConfig(peers[1] ?? peers[0]);
  const all: Remote<AgentConfig>[] = [c0, c1, c2, c3, cd, p0, ...(peers[1] ? [p1] : [])];
  const reconfigures = all.flatMap(r => (r.data?.history ?? []).filter(h => h.by === "director").map(h => ({ ...h, agentId: r.data!.agentId })))
    .sort((a, b) => a.at.localeCompare(b.at));
  return { reconfigures, ready: all.some(r => r.readiness === "ready") };
}

function NextChanges({ siteId }: { siteId: SiteId3 }) {
  const configs = useTeamConfigs(siteId);
  const findings = useEvalFindings();
  const T = configs.reconfigures[0]?.at ?? null;
  const after = usePoll(() => T ? api3.evalFindings(T) : Promise.resolve(null), [T], 20_000);
  if (!configs.ready) return <p className="mh-empty">Agent configs are not available yet.</p>;
  if (!configs.reconfigures.length) return <p className="mh-empty">No changes yet. The director reconfigures an agent when telemetry shows it wasting tokens.</p>;
  return <ul className="mh-changes">{configs.reconfigures.slice(-4).reverse().map((h, i) => {
    const a = findings.data?.agents.find(x => x.agentId === h.agentId); const b = after.data?.agents.find(x => x.agentId === h.agentId);
    const all = a?.missions ?? 0, since = b?.missions ?? 0;
    const before = a?.tokensPerMission != null && all > since ? (a.tokensPerMission * all - (b?.tokensPerMission ?? 0) * since) / (all - since) : null;
    const effect = before && b?.tokensPerMission != null ? Math.round(((b.tokensPerMission - before) / before) * 100) : null;
    const extra = h as unknown as { outcome?: string; status?: string; accepted?: boolean; effect?: string };
    const outcome = extra.outcome ?? extra.status ?? (extra.accepted === false ? "rejected" : "accepted");
    const what = Object.entries(h.change).map(([k, v]) => k === "documentCache" ? (v ? "Document cache" : "No document cache") : k === "pollStrategy" ? (v === "subscribe" ? "Subscribe, not poll" : "Poll") : k === "maxTokensPerMission" ? `Budget ${v}` : `${k} ${String(v)}`).join(", ");
    return <li key={`${h.at}-${i}`} className={outcome === "rejected" ? "rejected" : ""}>
      <span className="what">{what}, {agentName(h.agentId)}</span>
      <span className="eff">{extra.effect ?? (effect !== null ? `${effect > 0 ? "+" : "−"}${Math.abs(effect)}% tokens` : "effect measured after the next missions")} · <strong>{outcome}</strong></span>
    </li>;
  })}</ul>;
}

/* Open issues and compliance notices, newest first; a click turns the camera to the asset. */
function Alerts({ siteId, issues, onFocus }: { siteId: SiteId3; issues: Issue3[]; onFocus: (tag: string) => void }) {
  const notices = useNotices(siteId);
  const fixes = useFixWorkflows(siteId);
  const regs = useMemo(() => regsForSite(siteId, REGULATIONS_PACK), [siteId]);
  const open = issues.filter(i => !i.status || i.status !== "resolved").sort((a, b) => (RANK[b.severity] ?? 0) - (RANK[a.severity] ?? 0) || b.at.localeCompare(a.at)).slice(0, 6);
  const proof = (fixes.data ?? []).filter(w => w.attestationId).sort((a, b) => String(b.finishedAt ?? b.startedAt).localeCompare(String(a.finishedAt ?? a.startedAt)))[0];
  const raisedBy = (i: Issue3) => { const h = (i as unknown as { history?: { by?: string }[] }).history?.[0]?.by; return h ? agentName(h) : i.source === "vision" ? agentName(teamOf(siteId).find(a => a.team === "engineer")?.id) : i.source && i.source !== "scenario" ? i.source : "the record"; };
  return <div className="mh-alerts">
    {open.length ? <ul>{open.map(i => {
      const why: WhyRef[] = Array.isArray(i.why) ? i.why : i.why ? [i.why] : regsForIssue(i, regs).map(r => ({ instrument: r.instrument, provision: r.provision }));
      return <li key={i.id}><button type="button" onClick={() => onFocus(i.assetTag)}>
        <span className="r1"><span className={`sig ${i.severity === "high" ? "bad" : i.severity === "medium" ? "warn" : "off"}`} aria-hidden="true" /><code>{i.assetTag}</code><span className="sev">{i.severity}</span><span className="tm">{fmtTime(i.at, tzOf(siteId))}</span></span>
        <span className="sum">{i.summary}</span>
        <span className="by">raised by {raisedBy(i)}{why[0] ? <> · cites {shortRef(why[0])}</> : null}</span>
      </button></li>;
    })}</ul> : <p className="mh-empty">No open issues at {site3(siteId).short}.</p>}
    {(notices.data ?? []).slice(0, 2).map(n => <p key={n.id} className="mh-notice"><span className="sig warn" aria-hidden="true" />Notice to {n.to}{n.mode && n.mode !== "sent" ? `, ${n.mode.replace(/_/g, " ")}` : ""} · {fmtTime(n.sentAt, tzOf(siteId))}</p>)}
    <p className="mh-proof">{proof ? <>Last signed proof <code>{String(proof.attestationId)}</code>, Ed25519, verified by the {agentName(teamOf(siteId).find(a => a.team === "engineer")?.id)}</> : `Signed proof appears here when a fix is verified. ${jurisdictionName(siteJurisdiction(siteId))} rules apply.`}</p>
  </div>;
}

/* The team graph: director, manager, engineer, compliance, technician, the dispatch line and the crew on shift.
   The pair talking now is drawn in white; the acting node is filled white. */
function TeamGraph({ siteId, actor }: { siteId: SiteId3; actor: string | null }) {
  const { overview, agents } = useShared();
  const rows = useNowRows(overview, agents);
  const { pairs } = useExchanges();
  const crew = useCrew(siteId);
  const team = teamOf(siteId);
  const id = (t: string) => team.find(a => a.team === t)!.id;
  const pos: Record<string, [number, number]> = { director: [150, 22], [id("manager")]: [150, 70], [id("engineer")]: [48, 124], [id("compliance")]: [150, 124], [id("technician")]: [252, 124], dispatch: [252, 170] };
  const edges: [string, string][] = [["director", id("manager")], [id("manager"), id("engineer")], [id("manager"), id("compliance")], [id("manager"), id("technician")], [id("technician"), "dispatch"]];
  const now = Date.now();
  const live = (a: string, b: string) => { const p = pairs.get(pairKey(a, b)); return p ? now - new Date(p.at).getTime() < 5 * 60_000 : false; };
  const extra = [...pairs.keys()].map(k => k.split("|") as [string, string]).filter(([a, b]) => a in pos && b in pos && !edges.some(([x, y]) => pairKey(x, y) === pairKey(a, b)) && live(a, b));
  const onShift = (crew.data ?? []).filter(c => c.onShift).slice(0, 5);
  const acting = (n: string) => n === actor || rows.find(r => r.id === n)?.status === "working";
  const label: Record<string, string> = { director: "Director", dispatch: "Dispatch", [id("manager")]: "Manager", [id("engineer")]: "Engineer", [id("compliance")]: "Compliance", [id("technician")]: "Technician" };
  return <svg className="mh-graph" viewBox="0 0 300 232" role="img" aria-label={`${site3(siteId).short} team: ${team.map(a => `${a.name} ${rows.find(r => r.id === a.id)?.status ?? "unknown"}`).join(", ")}; ${DISPATCH.name}; ${onShift.length} crew on shift.`}>
    {[...edges, ...extra].map(([a, b]) => <line key={pairKey(a, b)} x1={pos[a][0]} y1={pos[a][1]} x2={pos[b][0]} y2={pos[b][1]} className={live(a, b) ? "lit" : ""} />)}
    {onShift.map((c, i) => { const x = 40 + i * 52; return <g key={c.id}><line x1={252} y1={170} x2={x} y2={210} className="crew-edge" /><rect x={x - 5} y={205} width={10} height={10} className="crew" /><title>{c.name}, {c.role}</title></g>; })}
    {Object.entries(pos).map(([n, [x, y]]) => <g key={n} className={`node ${acting(n) ? "act" : ""}`} transform={`translate(${x},${y})`}>
      <rect x={-8} y={-8} width={16} height={16} />
      <text y={n === "director" ? -14 : 24} textAnchor="middle">{label[n]}</text>
    </g>)}
    <text x={8} y={228} className="crew-label">crew on shift ({onShift.length})</text>
  </svg>;
}

/* One live line: what the acting agent is doing now. */
function LiveLine({ siteId, frame }: { siteId: SiteId3; frame: EyeFrame | null }) {
  const { overview, agents } = useShared();
  const rows = useNowRows(overview, agents).filter(r => r.siteId === siteId || r.id === "director");
  const working = rows.find(r => r.status === "working" && r.task);
  const fresh = frame && Date.now() - new Date(frame.at).getTime() < 10 * 60_000;
  const tag = (frame?.params as { assetTag?: string } | null)?.assetTag;
  return <p className="mh-live" aria-live="polite">
    <span className="sig ok" aria-hidden="true" />
    {fresh && frame ? <><strong>{agentName(frame.actor)}</strong> · eye_{frame.action ?? "look"}{tag ? <> <code>{tag}</code></> : null}{frame.seq ? ` · frame ${frame.seq}` : ""}</>
      : working ? <><strong>{working.name}</strong> · {working.task}</>
      : <>The {site3(siteId).short} team is idle; this line follows the next agent at work.</>}
  </p>;
}
