"use client";

/* /app, the overview (owner, Oct 18): the three environments, the telemetry of all three together, the live log, and the
   rest of the picture kept short (the latest calls and chats, the latest inspection per site, the maintenance coming up).
   Agent mode on the same page: how an agent connects over MCP, the tools it uses, each site as the agent sees it, the
   site tours, and the live agent view (what the agents read, the agent map, their streams). */
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Remote } from "@/lib/reality";
import { useConversations, useEyeFeed, useMaintenance, useMetricsLive, useMetricsSummary } from "@/lib/hooks-3";
import { useWalk } from "@/lib/hooks-7";
import { useInspections, usePhoneCalls } from "@/lib/hooks-10";
import { READING_TYPES, logHref, typeWord, useLogs } from "@/lib/logs-9";
import { useMode } from "@/lib/mode-11";
import { SITES3, rn, site3, type Site3 } from "@/lib/sites-3";
import type { LiveKpis, SiteOverview, SiteSummary } from "@/lib/types-3";
import { callStatusWord, purposeWord, roleWord } from "@/lib/api-10";
import AgentView from "./agent-view";
import LogsPage from "./logs";
import { ConnectPanel, SiteAgentEnvironment, SiteTours } from "./agent-env";
import { LatestInspection } from "./inspections";
import { Kpis, totalOf } from "./kpis";
import { averageOf } from "./portfolio";
import { useShared } from "./shell";
import { Btn, PageHead, Reveal, SiteTitle, State, ago } from "./ui3";

export default function OverviewPage() {
  const [mode] = useMode();
  return mode === "agent" ? <AgentOverview /> : <HumanOverview />;
}

function HumanOverview() {
  const { overview } = useShared();
  const summary = useMetricsSummary();
  const live = useMetricsLive();
  const liveAverage = useMemo<LiveKpis | null>(() => live.data ? { ...live.data.average, checkedIn: totalOf(live.data.sites.map(x => x.kpis.checkedIn)) } : null, [live.data]);
  const covered = summary.data?.sites.map(x => x.siteId) ?? [];
  const average = covered.length === SITES3.length ? summary.data?.average ?? averageOf(summary.data?.sites ?? []) : averageOf(summary.data?.sites ?? []) ?? summary.data?.average ?? null;
  return <div className="page3">
    <PageHead id="overview" title="Overview" sub="Three environments, their agent teams and what happened last, live." />
    <div className="envs11">
      {SITES3.map((s, i) => <EnvCard key={s.id} site={s} i={i} sum={summary.data?.sites.find(x => x.siteId === s.id) ?? null} live={live.data?.sites.find(x => x.siteId === s.id)?.kpis ?? null} ov={overview.data?.sites.find(x => x.siteId === s.id) ?? null} />)}
    </div>
    <Reveal as="section" className="p3 avg3" i={1} aria-labelledby="avg-h">
      <div className="p-head"><h2 id="avg-h">All three together</h2>{live.data ? <span className="meta">live, every 5 s</span> : null}</div>
      <Kpis s={average} live={liveAverage} liveAt={live.data?.at} remote={summary as Remote<unknown>} />
    </Reveal>
    {/* One column, no sidebar (owner, Oct 18): the log across the width, then three equal cards. */}
    <LiveLog i={2} />
    <div className="envs11">
      <LatestCalls i={2} />
      <LatestChats i={3} />
      <UpcomingMaintenance i={4} />
    </div>
    <div className="envs11">{SITES3.map((s, i) => <LatestInspection key={s.id} siteId={s.id} compact i={3 + i} title={`Latest inspection, ${s.short}`} />)}</div>
  </div>;
}

/* One environment: the agent eye's latest frame, who is walking or inspecting there now, and its three figures. */
function EnvCard({ site, sum, live, ov, i }: { site: Site3; sum: SiteSummary | null; live: LiveKpis | null; ov: SiteOverview | null; i: number }) {
  const eye = useEyeFeed(site.id, 6_000);
  const walk = useWalk(site.id, 4_000).data;
  const inspection = useInspections(site.id, 1).data?.[0] ?? null;
  const frame = useMemo(() => [...(eye.data?.frames ?? [])].sort((a, b) => b.at.localeCompare(a.at))[0] ?? null, [eye.data]);
  const [broken, setBroken] = useState(false);
  const inspecting = inspection && /running|walking|in_progress/.test(inspection.state ?? "");
  const state = inspecting ? `Site Inspector inspecting${inspection?.primary?.assetTag ? `, ${inspection.primary.assetTag}` : ""}`
    : walk?.walking ? `${walk.agentName} walking${walk.stop && walk.of ? `: stop ${walk.stop} of ${walk.of}` : ""}${walk.assetTag ? `, ${walk.assetTag}` : ""}`
      : walk ? `${walk.agentName}, between walks` : null;
  const issues = ov?.issues ? (ov.issues.high ?? 0) + (ov.issues.medium ?? 0) + (ov.issues.low ?? 0) : sum?.openIssues ?? null;
  const compliance = sum?.compliancePct ?? null;
  const checkedIn = live?.checkedIn?.value ?? sum?.employeesCheckedIn ?? null;
  const fig = (v: number | null | undefined, unit = "") => typeof v === "number" ? `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(v)}${unit}` : "–";
  return <Reveal as="article" i={i}>
    <Link href={`/app/${site.id}`} className="env11" aria-label={`Open ${site.name}`}>
      <div className="pic">
        <img src={frame && !broken ? frame.frameUrl : site.thumbnailUrl} onError={() => setBroken(true)} alt={frame && !broken ? `${site.name}: what the agent eye saw last` : `${site.name}, 3-D scan`} loading="lazy" />
        {state ? <span className="state"><span className={`sig ${walk?.walking || inspecting ? "ok" : "off"}`} aria-hidden="true" />{state}{frame ? <span className="r3" style={{ marginLeft: "auto" }}>{ago(frame.at)}</span> : null}</span> : null}
      </div>
      <div className="body">
        <div><h2><SiteTitle site={site} /></h2><p className="place">{site.line}</p></div>
        <dl>
          <div><dt>Compliance</dt><dd className={typeof compliance === "number" && compliance < 80 ? "bad" : ""}>{fig(compliance, " %")}</dd></div>
          <div><dt>Open issues</dt><dd className={ov?.issues?.high ? "bad" : ""}>{fig(issues)}</dd></div>
          <div><dt>Checked in</dt><dd>{fig(checkedIn)}</dd></div>
        </dl>
        <span className="open">Open {site.short} →</span>
      </div>
    </Link>
  </Reveal>;
}

const clock = (at: string) => { const d = new Date(at); return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }); };

/* What happened last, across the sites (or at one site), newest first, without the raw sensor feed. */
export function LiveLog({ siteId, i = 0, lines = 12 }: { siteId?: string; i?: number; lines?: number }) {
  const { overview } = useShared();
  const logs = useLogs(siteId ? 80 : 50, 5_000);
  const [shown, setShown] = useState(lines);
  const [all, setAll] = useState(false);
  const items = (logs.data ?? []).filter(e => !READING_TYPES.has(e.type) && (!siteId || e.siteId === siteId));
  const hid = `log-${siteId ?? "all"}-h`;
  /* "See all": the full log with its filters and search, in place. */
  if (all) return <section className="logs11-all" aria-labelledby={hid} id="logs">
    <div className="p-head"><h2 id={hid}>What happened last</h2><button type="button" className="lnk" onClick={() => setAll(false)}>Show less</button></div>
    <div className="embed11"><LogsPage initialSite={siteId ?? ""} /></div>
  </section>;
  /* The site log reads every site's changes and keeps going when one fails, so "nothing yet" waits for the backend. */
  const offline = !items.length && overview.readiness !== "ready";
  return <Reveal as="section" className="p3" i={i} aria-labelledby={hid} id="logs">
    <div className="p-head"><h2 id={hid}>What happened last</h2><span className="p-tools11">{logs.data && !offline ? <span className="meta">live, every 5 s</span> : null}<button type="button" className="lnk" onClick={() => setAll(true)}>See all</button></span></div>
    {offline ? <div className="st3 not-ready" role="status"><strong>Not available yet</strong><span>The log appears when the sites report.</span></div> : <State remote={logs} what="the log" isEmpty={() => items.length === 0} empty="Nothing logged yet.">
      {() => <>
        <ol className={`loglist11 ${siteId ? "site" : ""}`} role="log" aria-live="off">{items.slice(0, shown).map(e => { const href = logHref(e); return <li key={e.id}>
          <span className="tm">{clock(e.at)}</span>
          {siteId ? null : <span className="st">{site3(e.siteId).short}</span>}
          <span className="ty">{typeWord(e.type)}</span>
          <span className="sm">{href ? <Link href={href} className="lnk-plain">{rn(e.summary) || typeWord(e.type)}</Link> : rn(e.summary)}</span>
        </li>; })}</ol>
        {items.length > shown ? <div style={{ marginTop: 10 }}><Btn small quiet onClick={() => setShown(n => n + 30)}>Show more</Btn></div> : null}
      </>}
    </State>}
  </Reveal>;
}

export function LatestCalls({ siteId, i = 0 }: { siteId?: string; i?: number }) {
  const calls = usePhoneCalls({ siteId, limit: 3 });
  return <Reveal as="section" className="p3" i={i} aria-labelledby={`pc-${siteId ?? "all"}-h`}>
    <div className="p-head"><h2 id={`pc-${siteId ?? "all"}-h`}>Phone calls</h2><Link className="lnk" href="/app/conversations?tab=calls">All</Link></div>
    <State remote={calls} what="phone calls" isEmpty={c => c.length === 0} empty="No calls yet.">
      {c => <ul className="rows11">{c.slice(0, 3).map(x => <li key={x.id}><Link href={`/app/conversations?call=${encodeURIComponent(x.id)}`}>
        <span className="r1"><strong>{x.callerName} called {roleWord(x.calleeRole)}</strong><span className="r3">{callStatusWord(x.status)}, {ago(x.startedAt ?? x.queuedAt)}</span></span>
        <span className="r2">{rn(x.outcome?.summary ?? x.outcome?.decision ?? x.goal ?? purposeWord(x.purpose))}</span>
      </Link></li>)}</ul>}
    </State>
  </Reveal>;
}

export function LatestChats({ siteId, i = 0 }: { siteId?: string; i?: number }) {
  const conversations = useConversations(siteId ? { siteId } : {});
  return <Reveal as="section" className="p3" i={i} aria-labelledby={`ch-${siteId ?? "all"}-h`}>
    <div className="p-head"><h2 id={`ch-${siteId ?? "all"}-h`}>Agent chats</h2><Link className="lnk" href="/app/conversations">All</Link></div>
    <State remote={conversations} what="chats" isEmpty={c => c.length === 0} empty="No chats yet.">
      {c => <ul className="rows11">{[...c].sort((a, b) => (a.kind === "message" ? 1 : 0) - (b.kind === "message" ? 1 : 0) || b.startedAt.localeCompare(a.startedAt))
        .filter((x, k, all) => all.findIndex(y => (y.summary?.headline ?? y.title) === (x.summary?.headline ?? x.title)) === k).slice(0, 4).map(x => <li key={x.id}><Link href={`/app/conversations?id=${encodeURIComponent(x.id)}`}>
          <span className="r1"><strong>{rn(x.summary?.headline ?? x.title ?? "Chat")}</strong><span className="r3">{x.kind === "call" ? "chat" : x.kind}, {ago(x.startedAt)}</span></span>
          {x.summary?.decisions?.[0] ? <span className="r2">{rn(x.summary.decisions[0])}</span> : null}
        </Link></li>)}</ul>}
    </State>
  </Reveal>;
}

export function UpcomingMaintenance({ siteId, i = 0 }: { siteId?: string; i?: number }) {
  const windows = useMaintenance(siteId);
  const next = useMemo(() => (windows.data ?? []).filter(w => w.status !== "done" && Date.parse(w.date) >= Date.now() - 3_600_000).sort((a, b) => a.date.localeCompare(b.date)).slice(0, 6), [windows.data]);
  return <Reveal as="section" className="p3" i={i} aria-labelledby={`mw-${siteId ?? "all"}-h`}>
    <div className="p-head"><h2 id={`mw-${siteId ?? "all"}-h`}>Maintenance coming up</h2></div>
    <State remote={windows} what="maintenance" isEmpty={() => next.length === 0} empty="Nothing booked.">
      {() => <ul className="rows11">{next.map(w => <li key={w.id}><Link href={`/app/${w.siteIds[0] ?? ""}#maintenance`}>
        <span className="r1"><strong>{rn(w.title ?? w.scope)}</strong><span className="r3">{w.siteIds.map(x => site3(x).short).join(" and ")}</span></span>
        <span className="r2">{new Date(w.date).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}{w.examiner ? `, ${rn(w.examiner)}` : ""}, {w.status}</span>
      </Link></li>)}</ul>}
    </State>
  </Reveal>;
}

function AgentOverview() {
  return <div className="page3 agent11">
    <PageHead id="overview-agent" title="Overview, as an agent sees it" sub="Everything below is what an MCP client reads: the same text and JSON, the eye's frames, the tours." />
    <ConnectPanel i={0} />
    {SITES3.map((s, i) => <SiteAgentEnvironment key={s.id} siteId={s.id} i={1 + i} />)}
    <SiteTours i={4} limit={6} />
    <div className="embed11"><AgentView /></div>
  </div>;
}
