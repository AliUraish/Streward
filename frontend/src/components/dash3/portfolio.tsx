"use client";

/* /app, the portfolio: the three sites side by side, the three-site figures (live readings every 5 s) and what is
   happening at each right now. */
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Remote } from "@/lib/reality";
import { api3 } from "@/lib/api-3";
import { useConversations, useMetricsLive, useMetricsSummary, usePoll } from "@/lib/hooks-3";
import { AGENTS3, SITES3, rn, siteList, type Site3 } from "@/lib/sites-3";
import type { AgentInfo } from "@/lib/types-2";
import type { Conversation, LiveKpis, Overview, SiteOverview, SiteSummary } from "@/lib/types-3";
import { Kpis, totalOf, withFigures } from "./kpis";
import { useShared } from "./shell";
import { NotYet, PageHead, Reveal, SiteTitle, ago } from "./ui3";

export default function PortfolioPage() {
  const { overview, agents } = useShared();
  const summary = useMetricsSummary();
  const live = useMetricsLive();
  const conversations = useConversations();
  const covered = summary.data?.sites.map(x => x.siteId) ?? [];
  const missing = SITES3.filter(x => !covered.includes(x.id));
  const average = covered.length === SITES3.length ? summary.data?.average ?? averageOf(summary.data?.sites ?? []) : averageOf(summary.data?.sites ?? []) ?? summary.data?.average ?? null;
  /* Across the sites: the backend's averages, but people checked in as a total, as the other counts are. */
  const liveAverage = useMemo<LiveKpis | null>(() => live.data ? { ...live.data.average, checkedIn: totalOf(live.data.sites.map(x => x.kpis.checkedIn)) } : null, [live.data]);
  return <div className="page3">
    <PageHead id="portfolio" title="Portfolio" />
    <Reveal as="section" className="p3 avg3" aria-labelledby="avg-h">
      <div className="p-head"><h2 id="avg-h">All three sites</h2>{summary.data && missing.length ? <span className="meta">{siteList(missing.map(x => x.id))} not reporting yet</span> : live.data ? <span className="meta">live, every 5 s</span> : null}</div>
      <Kpis s={average} live={liveAverage} liveAt={live.data?.at} remote={summary as Remote<unknown>} />
    </Reveal>
    <div className="tiles3 three">
      {SITES3.map((s, i) => <FactoryTile key={s.id} site={s} i={i} sum={summary.data?.sites.find(x => x.siteId === s.id) ?? null} summary={summary as Remote<unknown>} live={live.data?.sites.find(x => x.siteId === s.id)?.kpis ?? null} liveAt={live.data?.at ?? null} ov={overview.data?.sites.find(x => x.siteId === s.id) ?? null} overview={overview} />)}
    </div>
    <NowBoard overview={overview} agents={agents} conversations={conversations.data ?? []} />
  </div>;
}

/* The averages when the backend's own row is missing or covers fewer sites than the page shows. */
export function averageOf(sites: SiteSummary[]): SiteSummary | null {
  if (sites.length < 2) return null;
  const avg = (k: keyof SiteSummary) => { const v = sites.map(s => s[k]).filter((x): x is number => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const sum = (k: keyof SiteSummary) => { const v = sites.map(s => s[k]).filter((x): x is number => typeof x === "number"); return v.length ? v.reduce((a, b) => a + b, 0) : null; };
  return { siteId: "average", avgPressure: avg("avgPressure"), avgFlow: avg("avgFlow"), uptimePct: avg("uptimePct"), openIssues: sum("openIssues"), compliancePct: avg("compliancePct"), crewOnShift: sum("crewOnShift"), agentActionsToday: sum("agentActionsToday"), employeesCheckedIn: sum("employeesCheckedIn") };
}

function FactoryTile({ site, sum, summary, live, liveAt, ov, overview, i }: { site: Site3; sum: SiteSummary | null; summary: Remote<unknown>; live: LiveKpis | null; liveAt: string | null; ov: SiteOverview | null; overview: Remote<Overview>; i: number }) {
  /* Until the overview answers, the severity counts come straight from the site's issues. */
  const fromIssues = usePoll(() => ov ? Promise.resolve(null) : api3.issues(site.id), [site.id, Boolean(ov)], 10_000);
  /* The mill's figures come from its own series while the summary does not carry them. */
  const wants = site.kpis.filter(k => k === "avgHumidity" || k === "maxCrackWidth");
  const needSeries = wants.length > 0 && (!sum || wants.some(k => sum[k] === undefined || sum[k] === null));
  const series = usePoll(() => {
    if (!needSeries) return Promise.resolve(null);
    const to = new Date(); const from = new Date(to.getTime() - 24 * 3_600_000);
    return api3.metrics(site.id, { from: from.toISOString(), to: to.toISOString(), step: 300 });
  }, [site.id, needSeries], 60_000);
  const figures = withFigures(sum, series.data?.series, site.id);
  const counts = ov?.issues ?? (fromIssues.data ? fromIssues.data.filter(x => !x.status || !["resolved", "closed"].includes(x.status)).reduce((m, x) => ({ ...m, [x.severity]: (m[x.severity] ?? 0) + 1 }), { high: 0, medium: 0, low: 0 } as Record<string, number>) : null);
  const c = ov?.compliance;
  return <Reveal as="article" className="tile3" i={i}>
    <Link href={`/app/${site.id}`} className="thumb" aria-label={`Open ${site.name}`}>
      <img src={site.thumbnailUrl} alt={`${site.name}, 3-D scan`} width={960} height={540} loading="lazy" />
    </Link>
    <div className="tile-body">
      <div className="tile-head">
        <div><h2><SiteTitle site={site} /></h2><p className="place">{site.line}</p></div>
      </div>
      <dl className="stats3">
        <div className="stat">
          <dt>Open issues</dt>
          <dd>{counts ? <span className="sev-row">
            <span className={`fig ${counts.high ? "bad" : ""}`}>{counts.high}<small>high</small></span>
            <span className="fig">{counts.medium}<small>medium</small></span>
            <span className="fig dim">{counts.low}<small>low</small></span>
          </span> : <NotYet remote={ov ? overview : fromIssues} what="issue counts" />}</dd>
        </div>
        <div className="stat">
          <dt>Obligations</dt>
          <dd>{c ? <span className="comp-row">
            <span><span className="sig ok" aria-hidden="true" />{c.ok} ok</span>
            <span><span className="sig warn" aria-hidden="true" />{c.due_soon} due soon</span>
            <span className={c.overdue ? "bad" : ""}><span className={`sig ${c.overdue ? "bad" : "off"}`} aria-hidden="true" />{c.overdue} overdue</span>
            <span className={c.blocked ? "bad" : ""}><span className={`sig ${c.blocked ? "bad" : "off"}`} aria-hidden="true" />{c.blocked} blocked</span>
          </span> : overview.readiness === "ready" ? <span className="st3-inline">Not available yet</span> : <NotYet remote={overview} what="compliance" />}</dd>
        </div>
      </dl>
      <Kpis s={figures ?? (ov ? { siteId: site.id, avgPressure: null, avgFlow: null, uptimePct: null, openIssues: null, compliancePct: null, crewOnShift: typeof ov.crewOnShift === "number" ? ov.crewOnShift : ov.crewOnShift.count, agentActionsToday: null } : null)} live={live} liveAt={liveAt} remote={summary} compact only={site.kpis} missingText="No figures yet." />
      <div className="tile-foot">
        <Link className="b3 small" href={`/app/${site.id}`}><span>Open {site.short}</span><span className="arrow" aria-hidden="true">→</span></Link>
      </div>
    </div>
  </Reveal>;
}

/* What is happening right now: the director and the owner's agent, then each factory's team, changes and calls. */
/* What just happened at one site: its own newest changes, full text, without the raw sensor feed (the KPIs show it). */
const QUIET_TYPES = new Set(["fact", "attestation", "scenario", "eye"]);
type SiteChange = { type?: string; summary?: string; at?: string; siteId?: string; site?: string };
function useSiteChanges(siteId: string) {
  return usePoll(async () => {
    const res = await fetch(`/api/properties/${encodeURIComponent(siteId)}/changes?latest=true&limit=60`, { cache: "no-store" });
    if (!res.ok) throw new Error(`changes ${res.status}`);
    const body = await res.json() as { changes?: SiteChange[] };
    return (body.changes ?? []).filter(c => !QUIET_TYPES.has(c.type ?? "")).reverse().slice(0, 4);
  }, [siteId], 5_000);
}
function SiteChanges({ siteId, fallback }: { siteId: string; fallback: SiteChange[] }) {
  const remote = useSiteChanges(siteId);
  const mine = remote.data ?? fallback;
  return mine.length ? <ul className="rows3 plain changes">{mine.map((c, i) => <li key={`${c.at}-${i}`}><span className="r2">{rn(c.summary ?? "")}</span><span className="r3">{c.type ? c.type.replace(/_/g, " ") : ""}{c.at ? `, ${c.at.length <= 8 ? c.at : ago(c.at)}` : ""}</span></li>)}</ul>
    : <p className="st3 empty">{remote.readiness === "ready" ? "No changes in the last few minutes." : "No changes yet."}</p>;
}
function NowBoard({ overview, agents, conversations }: { overview: Remote<Overview>; agents: Remote<AgentInfo[]>; conversations: Conversation[] }) {
  const rows = useNowRows(overview, agents);
  const changes = overview.data?.changes ?? [];
  const known = rows.some(r => r.known);
  return <Reveal as="section" className="now3" i={1} aria-labelledby="now-h">
    <div className="now-head"><h2 id="now-h">Right now</h2>{known ? <span className="meta">live, every 3 s</span> : <NotYet remote={overview.readiness === "ready" ? agents as Remote<unknown> : overview as Remote<unknown>} what="agent status" />}</div>
    <ol className="now-top">{rows.filter(r => !r.siteId).map(r => <NowCell key={r.id} r={r} />)}</ol>
    <div className="now-sites">
      {SITES3.map(s => {
        const tag = (c: { siteId?: string; site?: string }) => c.siteId ?? c.site ?? "";
        const mine = changes.filter(c => { const t = tag(c as { siteId?: string; site?: string }); return t === s.id || t.startsWith(s.id.slice(0, 2)) || t.toLowerCase() === s.prefix.toLowerCase(); }).slice(0, 4);
        const call = conversations.find(c => c.siteIds.includes(s.id));
        return <div className="now-site" key={s.id}>
          <h3><Link href={`/app/${s.id}`} className="lnk-plain">{s.name}</Link></h3>
          <ol className="now-strip">{rows.filter(r => r.siteId === s.id).map(r => <NowCell key={r.id} r={r} />)}</ol>
          <div className="now-feed">
            {call ? <p className="call"><strong>{call.kind === "meeting" ? "Meeting" : call.kind === "call" ? "Chat" : "Message"}:</strong> {call.summary?.headline ?? call.title ?? "conversation"} <span className="r3">{ago(call.startedAt)}</span> <Link className="lnk" href={`/app/conversations?id=${encodeURIComponent(call.id)}`}>Read</Link></p> : null}
            <SiteChanges siteId={s.id} fallback={mine as SiteChange[]} />
          </div>
        </div>;
      })}
    </div>
  </Reveal>;
}
export interface NowRow { id: string; name: string; level: number; siteId?: string; status: string | null; task: string | null; why: string | null; waitingOn: string | null; since: string | null; known: boolean }
export function useNowRows(overview: Remote<Overview>, agents: Remote<AgentInfo[]>): NowRow[] {
  return useMemo(() => {
    const fromOverview = overview.data?.agents ?? [];
    const fromList = agents.data ?? [];
    return AGENTS3.map(a => {
      const o = fromOverview.find(x => x.agentId === a.id);
      const l = fromList.find(x => x.id === a.id);
      return { id: a.id, name: a.name, level: a.level, siteId: a.siteId, status: o?.status ?? l?.status ?? null, task: l?.currentTask ?? o?.currentTask ?? null, why: l?.why ?? o?.why ?? null, waitingOn: l?.waitingOn ?? o?.waitingOn ?? null, since: o?.since ?? l?.lastActivityAt ?? null, known: Boolean(o || l) };
    });
  }, [overview.data, agents.data]);
}
export function NowCell({ r }: { r: NowRow }) {
  const [prev, setPrev] = useState(r.task);
  const [flash, setFlash] = useState(0);
  if (prev !== r.task) { setPrev(r.task); setFlash(f => f + 1); }
  const status = r.status ?? (r.known ? "idle" : "unknown");
  return <li className="now-cell" data-status={status}>
    {flash ? <span className="flash" key={flash} aria-hidden="true" /> : null}
    <span className="who"><span className={`sig ${status === "working" ? "ok" : status === "waiting" ? "warn" : "off"}`} aria-hidden="true" /><span className="nm">{r.name}</span></span>
    <span className="task" key={r.task ?? "none"}>{r.task ?? (r.known ? "No task" : "Status not available yet")}</span>
    {r.why ? <span className="why">Why: {r.why}</span> : null}
    {r.waitingOn ? <span className="wait">Waiting on {r.waitingOn}</span> : null}
    <span className="since">{status}{r.since ? `, ${ago(r.since)}` : ""}</span>
  </li>;
}

