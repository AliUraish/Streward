"use client";

/* /app/[site]: the factory overview. KPIs and the latest readings (live, every 5 s), key metric sparklines, open issues,
   the team's status and the crew on shift. */
import Link from "next/link";
import { useMemo } from "react";
import type { Remote } from "@/lib/reality";
import { useConversations, useCrew, useIssues3, useMetrics, useMetricsLive, useMetricsSummary } from "@/lib/hooks-3";
import { site3 } from "@/lib/sites-3";
import type { LiveState, MetricSeries, SiteId3 } from "@/lib/types-3";
import { Sparkline } from "./charts";
import { Kpis, withFigures } from "./kpis";
import { NowCell, useNowRows } from "./portfolio";
import { useShared } from "./shell";
import { BandMark, NotYet, PageHead, Reveal, SiteTitle, State, SynthTag, TrendMark, ago, words } from "./ui3";
import { LatestInspection } from "./inspections";
import OwnerAlerts from "./owner-alerts";
import { SceneTally } from "./walkthrough";

export interface MetricDef { key: string; label: string; unit: string; digits: number }
export const METRIC_DEFS: MetricDef[] = [
  { key: "pressure_bar", label: "Pressure", unit: "bar", digits: 2 },
  { key: "flow_m3h", label: "Flow", unit: "m³/h", digits: 1 },
  { key: "temperature_c", label: "Temperature", unit: "°C", digits: 1 },
  { key: "level_pct", label: "Level", unit: "%", digits: 1 },
  { key: "vibration_mms", label: "Vibration", unit: "mm/s", digits: 2 },
  { key: "power_kw", label: "Power", unit: "kW", digits: 1 },
  /* The mill (contract 5 §3): preservation humidity and crack width; every site (contract 7): employees checked in. */
  { key: "humidity_pct", label: "Relative humidity", unit: "%", digits: 1 },
  { key: "checked_in", label: "Employees checked in", unit: "people", digits: 0 },
  { key: "crack_width_mm", label: "Crack width", unit: "mm", digits: 3 },
  { key: "seismic_gal", label: "Seismic acceleration", unit: "gal", digits: 1 },
];
/* The series a site's sensors send, in the order its pages show them. */
export const metricDefsFor = (siteId: SiteId3): MetricDef[] => site3(siteId).metrics.map(k => METRIC_DEFS.find(d => d.key === k) ?? { key: k, label: words(k), unit: "", digits: 2 });
/* A definition for a series the site's list does not name (the backend may send more). */
export const defFor = (key: string): MetricDef => METRIC_DEFS.find(d => d.key === key) ?? { key, label: words(key).replace(/^./, c => c.toUpperCase()), unit: "", digits: 2 };
export const seriesFor = (all: MetricSeries[], key: string) => all.filter(s => s.key === key || s.key.startsWith(`${key}:`) || s.key.startsWith(key));
const RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };
/* High or low against a series' spec band. */
export const bandState = (v: number | undefined | null, spec?: { min?: number | null; max?: number | null } | null): LiveState =>
  v === undefined || v === null || !spec ? "normal" : spec.max != null && v > spec.max ? "high" : spec.min != null && v < spec.min ? "low" : "normal";

/* `embedded`: the environment page's "Today" tab, under the agent's window, so no title and no picture of the site. */
export default function FactoryOverview({ siteId, embedded }: { siteId: SiteId3; embedded?: boolean }) {
  const site = site3(siteId);
  const { overview, agents } = useShared();
  const summary = useMetricsSummary();
  const metrics = useMetrics(siteId, 24, 300);
  const live = useMetricsLive(siteId);
  const liveSite = live.data?.sites.find(x => x.siteId === siteId) ?? null;
  const issues = useIssues3(siteId);
  const crew = useCrew(siteId);
  const calls = useConversations({ siteId });
  const rows = useNowRows(overview, agents).filter(r => r.siteId === siteId);
  const open = useMemo(() => (issues.data ?? []).filter(i => !i.status || !["resolved", "closed"].includes(i.status)).sort((a, b) => (RANK[b.severity] ?? 0) - (RANK[a.severity] ?? 0)), [issues.data]);
  const onShift = (crew.data ?? []).filter(c => c.onShift);
  /* The site's lead figures, then the counts every site shares. */
  const kpis = [...site.kpis.filter(k => !["compliancePct", "crewOnShift", "agentActionsToday"].includes(k)), "openIssues", "compliancePct", "crewOnShift", "agentActionsToday"] as typeof site.kpis;
  const defs = metricDefsFor(siteId);
  const kpiPanel = <Reveal as="section" className="p3 fo-kpis" i={1} aria-labelledby="kpi-h">
        <div className="p-head"><h2 id="kpi-h">Today at {site.short}</h2>{liveSite ? <span className="meta">live, every 5 s</span> : null}</div>
        <Kpis s={withFigures(summary.data?.sites.find(s => s.siteId === siteId) ?? null, metrics.data?.series, siteId)} live={liveSite?.kpis ?? null} liveAt={live.data?.at} remote={(metrics.data && !summary.data ? metrics : summary) as Remote<unknown>} only={kpis} missingText="No figures yet." />
      </Reveal>;
  const metricsHref = embedded ? "#metrics" : `/app/${siteId}#metrics`;
  return <div className="page3">
    {embedded ? kpiPanel : <>
      <PageHead id="factory" title={<SiteTitle site={site} />} sub={`${site.about}.`}>
        <Link className="b3 small" href={`/app/${siteId}`}><span>Open the agent eye</span><span className="arrow" aria-hidden="true">→</span></Link>
      </PageHead>
      <div className="fo-top">
        <Reveal as="figure" className="fo-pic">
          <Link href={`/app/${siteId}`} aria-label={`Open the agent eye on ${site.name}`}><img src={site.thumbnailUrl} alt={`${site.name}, 3-D scan`} width={960} height={540} /></Link>
          <SceneTally siteId={siteId} />
        </Reveal>
        {kpiPanel}
      </div>
    </>}
    <Reveal as="section" className="p3 sparks3" i={1} aria-labelledby="spark-h">
      <div className="p-head"><h2 id="spark-h">Last 24 hours</h2><Link className="lnk" href={metricsHref}>All metrics</Link></div>
      {metrics.data ? <ul className="spark-grid">{defs.map(d => {
        const ss = seriesFor(metrics.data!.series, d.key); const s = ss[0];
        /* The live reading of the card's series when it answers, else the series' latest point. */
        const reading = s ? liveSite?.readings.find(r => r.key === s.key) : undefined;
        const last = typeof reading?.value === "number" ? reading.value : s?.points.at(-1)?.[1];
        const state = reading ? reading.state : bandState(last, s?.spec);
        return <li key={d.key}>
          <Link href={metricsHref} className="spark-card">
            <span className={`spark-v ${state !== "normal" ? "bad" : ""}`}>{last !== undefined ? new Intl.NumberFormat(undefined, { maximumFractionDigits: d.digits }).format(last) : "–"}<small>{s?.unit ?? d.unit}</small>{reading ? <TrendMark trend={reading.trend} at={live.data?.at} /> : null}</span>
            <span className="r1"><strong>{d.label}</strong>{s?.assetTag && s.assetTag !== "SITE" ? <span className="sev">{s.assetTag}{ss.length > 1 ? ` +${ss.length - 1}` : ""}</span> : null}{s ? <SynthTag rec={s.synthetic === undefined ? metrics.data : s} /> : null}<BandMark state={state} /></span>
            <span className="r3">{s?.spec ? `spec ${s.spec.min ?? "–"} to ${s.spec.max ?? "–"} ${s.unit ?? d.unit}` : "no spec"}</span>
            {s ? <Sparkline points={s.points.slice(-288)} spec={s.spec} label={`${d.label} at ${site.short}`} /> : <span className="spark3 empty" />}
          </Link>
        </li>;
      })}</ul> : <State remote={metrics} what="metrics">{() => null}</State>}
    </Reveal>
    <div className="fo-grid">
      <Reveal as="section" className="p3" i={2} aria-labelledby="iss-h">
        <div className="p-head"><h2 id="iss-h">Open issues</h2><span className="meta">{issues.data ? open.length : ""}</span></div>
        <State remote={issues} what="issues" isEmpty={() => open.length === 0} empty="No open issues on this site.">
          {() => <ul className="rows3">{open.slice(0, 8).map(i => <li key={i.id}><Link className="row-btn" href={`/app/${siteId}?asset=${encodeURIComponent(i.assetTag)}`}>
            <span className="r1"><span className={`sig ${i.severity === "high" ? "bad" : i.severity === "medium" ? "warn" : "off"}`} aria-hidden="true" /><strong>{i.assetTag}</strong><span className="sev">{i.severity}, {words(i.kind)}</span><SynthTag rec={i} /></span>
            <span className="r2">{i.summary}</span>
          </Link></li>)}</ul>}
        </State>
      </Reveal>
      <div className="fo-side">
        <LatestInspection siteId={siteId} compact i={3} />
        <OwnerAlerts siteId={siteId} limit={3} i={3} />
        <Reveal as="section" className="p3" i={3} aria-labelledby="team-h">
          <div className="p-head"><h2 id="team-h">Team</h2><Link className="lnk" href={embedded ? "#team" : `/app/${siteId}#team`}>Team and chats</Link></div>
          {!rows.some(r => r.known) ? <p className="note3"><NotYet remote={overview.readiness === "ready" ? agents as Remote<unknown> : overview as Remote<unknown>} what="agent status" /></p> : null}
          <ol className="now-strip team">{rows.map(r => <NowCell key={r.id} r={r} />)}</ol>
        </Reveal>
        <Reveal as="section" className="p3" i={4} aria-labelledby="crew-h">
          <div className="p-head"><h2 id="crew-h">Crew on shift</h2><span className="meta">{crew.data ? `${onShift.length} of ${crew.data.length}` : ""}</span></div>
          <State remote={crew} what="the crew" isEmpty={() => onShift.length === 0} empty="Nobody on shift.">
            {() => <ul className="rows3 plain">{onShift.map(c => <li key={c.id}><span className="r1"><span className="sig ok" aria-hidden="true" /><strong>{c.name}</strong><SynthTag rec={c} /></span><span className="r3">{c.role}, {typeof c.shift === "string" ? c.shift : c.shift.label ?? ""}</span></li>)}</ul>}
          </State>
        </Reveal>
        <Reveal as="section" className="p3" i={5} aria-labelledby="calls-h">
          <div className="p-head"><h2 id="calls-h">Latest chats</h2><Link className="lnk" href="/app/conversations">All</Link></div>
          <State remote={calls} what="conversations" isEmpty={c => c.length === 0} empty="No chats or meetings yet.">
            {c => <ul className="rows3">{[...c].sort((a, b) => (a.kind === "message" ? 1 : 0) - (b.kind === "message" ? 1 : 0) || b.startedAt.localeCompare(a.startedAt)).filter((x, i, all) => all.findIndex(y => (y.summary?.headline ?? y.title) === (x.summary?.headline ?? x.title)) === i).slice(0, 3).map(x => <li key={x.id}><Link className="row-btn" href={`/app/conversations?id=${encodeURIComponent(x.id)}`}>
              <span className="r1"><strong>{x.summary?.headline ?? x.title ?? "Conversation"}</strong><SynthTag rec={x} /></span>
              <span className="r3">{x.kind === "call" ? "chat" : x.kind}, {ago(x.startedAt)}</span>
            </Link></li>)}</ul>}
          </State>
        </Reveal>
      </div>
    </div>
  </div>;
}
