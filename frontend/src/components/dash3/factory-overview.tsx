"use client";

/* /app/[site]: the factory overview. KPIs, key metric sparklines, open issues, the team's status and the crew on shift. */
import Link from "next/link";
import { useMemo } from "react";
import type { Remote } from "@/lib/reality";
import { useConversations, useCrew, useIssues3, useMetrics, useMetricsSummary } from "@/lib/hooks-3";
import { site3 } from "@/lib/sites-3";
import type { MetricSeries, SiteId3 } from "@/lib/types-3";
import { Sparkline } from "./charts";
import { Kpis } from "./kpis";
import { NowCell, useNowRows } from "./portfolio";
import { useShared } from "./shell";
import { NotYet, PageHead, Reveal, State, SynthTag, ago, words } from "./ui3";

export const METRIC_DEFS: { key: string; label: string; unit: string; digits: number }[] = [
  { key: "pressure_bar", label: "Pressure", unit: "bar", digits: 2 },
  { key: "flow_m3h", label: "Flow", unit: "m³/h", digits: 1 },
  { key: "temperature_c", label: "Temperature", unit: "°C", digits: 1 },
  { key: "level_pct", label: "Level", unit: "%", digits: 1 },
  { key: "vibration_mms", label: "Vibration", unit: "mm/s", digits: 2 },
  { key: "power_kw", label: "Power", unit: "kW", digits: 1 },
];
export const seriesFor = (all: MetricSeries[], key: string) => all.filter(s => s.key === key || s.key.startsWith(`${key}:`) || s.key.startsWith(key));
const RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };

export default function FactoryOverview({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const { overview, agents } = useShared();
  const summary = useMetricsSummary();
  const metrics = useMetrics(siteId, 24);
  const issues = useIssues3(siteId);
  const crew = useCrew(siteId);
  const calls = useConversations({ siteId });
  const rows = useNowRows(overview, agents).filter(r => r.siteId === siteId);
  const open = useMemo(() => (issues.data ?? []).filter(i => !i.status || !["resolved", "closed"].includes(i.status)).sort((a, b) => (RANK[b.severity] ?? 0) - (RANK[a.severity] ?? 0)), [issues.data]);
  const onShift = (crew.data ?? []).filter(c => c.onShift);
  return <div className="page3">
    <PageHead id="factory" title={site.name} sub={`${site.place}. ${site.gaussians} gaussians, captured by ${site.author}; the scan loads from the hosted capture at runtime.`}>
      <Link className="b3 small" href={`/app/${siteId}/environment`}><span>Open the agent eye</span><span className="arrow" aria-hidden="true">→</span></Link>
    </PageHead>
    <Reveal as="section" className="p3" aria-labelledby="kpi-h">
      <div className="p-head"><h2 id="kpi-h">Today at {site.short}</h2><span className="meta">{summary.data?.synthetic ? "synthetic metrics" : ""}</span></div>
      <Kpis s={summary.data?.sites.find(s => s.siteId === siteId) ?? null} remote={summary as Remote<unknown>} />
    </Reveal>
    <Reveal as="section" className="p3 sparks3" i={1} aria-labelledby="spark-h">
      <div className="p-head"><h2 id="spark-h">Last 24 hours</h2><Link className="lnk" href={`/app/${siteId}/metrics`}>All metrics</Link></div>
      {metrics.data ? <ul className="spark-grid">{METRIC_DEFS.map(d => {
        const ss = seriesFor(metrics.data!.series, d.key); const s = ss[0];
        const last = s?.points.at(-1)?.[1];
        const out = s?.spec && last !== undefined && ((s.spec.max != null && last > s.spec.max) || (s.spec.min != null && last < s.spec.min));
        return <li key={d.key}>
          <Link href={`/app/${siteId}/metrics#${d.key}`} className="spark-card">
            <span className="r1"><strong>{d.label}</strong>{s?.assetTag ? <span className="sev">{s.assetTag}{ss.length > 1 ? ` +${ss.length - 1}` : ""}</span> : null}{s ? <SynthTag rec={s.synthetic === undefined ? metrics.data : s} /> : null}</span>
            <span className={`spark-v ${out ? "bad" : ""}`}>{last !== undefined ? new Intl.NumberFormat(undefined, { maximumFractionDigits: d.digits }).format(last) : "–"}<small>{s?.unit ?? d.unit}</small></span>
            {s ? <Sparkline points={s.points.slice(-288)} spec={s.spec} label={`${d.label} at ${site.short}`} /> : <span className="spark3 empty" />}
            <span className="r3">{s?.spec ? `spec ${s.spec.min ?? "–"} to ${s.spec.max ?? "–"} ${s.unit ?? d.unit}` : "no spec"}</span>
          </Link>
        </li>;
      })}</ul> : <State remote={metrics} what="metrics">{() => null}</State>}
    </Reveal>
    <div className="fo-grid">
      <Reveal as="section" className="p3" i={2} aria-labelledby="iss-h">
        <div className="p-head"><h2 id="iss-h">Open issues</h2><span className="meta">{issues.data ? open.length : ""}</span></div>
        <State remote={issues} what="issues" isEmpty={() => open.length === 0} empty="No open issues on this site.">
          {() => <ul className="rows3">{open.slice(0, 8).map(i => <li key={i.id}><Link className="row-btn" href={`/app/${siteId}/environment?asset=${encodeURIComponent(i.assetTag)}`}>
            <span className="r1"><span className={`sig ${i.severity === "high" ? "bad" : i.severity === "medium" ? "warn" : "off"}`} aria-hidden="true" /><strong>{i.assetTag}</strong><span className="sev">{i.severity}, {words(i.kind)}</span><SynthTag rec={i} /></span>
            <span className="r2">{i.summary}</span>
          </Link></li>)}</ul>}
        </State>
      </Reveal>
      <div className="fo-side">
        <Reveal as="section" className="p3" i={3} aria-labelledby="team-h">
          <div className="p-head"><h2 id="team-h">Team</h2><Link className="lnk" href={`/app/${siteId}/team`}>Team page</Link></div>
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
          <div className="p-head"><h2 id="calls-h">Latest calls</h2><Link className="lnk" href="/app/conversations">All</Link></div>
          <State remote={calls} what="conversations" isEmpty={c => c.length === 0} empty="No calls or meetings yet.">
            {c => <ul className="rows3">{c.slice(0, 3).map(x => <li key={x.id}><Link className="row-btn" href={`/app/conversations?id=${encodeURIComponent(x.id)}`}>
              <span className="r1"><strong>{x.summary?.headline ?? x.title ?? "Conversation"}</strong><SynthTag rec={x} /></span>
              <span className="r3">{x.kind}, {ago(x.startedAt)}</span>
            </Link></li>)}</ul>}
          </State>
        </Reveal>
      </div>
    </div>
  </div>;
}
