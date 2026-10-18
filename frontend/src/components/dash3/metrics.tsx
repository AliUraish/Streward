"use client";

/* /app/[site]/metrics: the site's series with their spec bands. The plants send pressure, flow, temperature, level,
   vibration and power; the mill humidity, temperature, vibration, crack width and power (contract 5 §3); every site the
   employees checked in (contract 7). Any further series the backend sends follow the site's own, so nothing it measures
   is hidden. The first range is the last 15 minutes at 5-second points, polled every 5 s, so the lines move as readings
   arrive; every card leads with each series' latest reading, its direction since the one before and a High or Low mark
   outside the band (GET /api/metrics/live when it answers, else the series' last two points). */
import { useMemo, useRef, useState } from "react";
import { useMetrics, useMetricsLive } from "@/lib/hooks-3";
import { site3 } from "@/lib/sites-3";
import type { LiveReading, LiveState, LiveTrend, MetricSeries, MetricsResponse, SiteId3 } from "@/lib/types-3";
import { LineChart } from "./charts";
import { bandState, defFor, metricDefsFor, seriesFor, type MetricDef } from "./factory-overview";
import { BandMark, PageHead, Reveal, State, TrendMark } from "./ui3";

/* step is in seconds: 5-second points for the live window, 5-minute points for a day, 30-minute points for a week. */
const RANGES = [
  { key: "live", hours: 0.25, label: "15 minutes", step: 5, poll: 5_000 },
  { key: "day", hours: 24, label: "24 hours", step: 300, poll: 10_000 },
  { key: "week", hours: 168, label: "7 days", step: 1800, poll: 60_000 },
];
const fmtV = (v: number | null, digits: number) => v === null ? "–" : new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(v);

/* The live window keeps every 5-second point it has seen: the series carries 5-second points only since its last
   5-minute boundary, so without the buffer the line would coarsen every five minutes. The live readings join it as they
   come. For the longer ranges (windowMs 0) the latest live reading is drawn after the series' last point. */
function useRolling(data: MetricsResponse | null, key: string, windowMs: number, readings: LiveReading[] | null, at: string | null): MetricsResponse | null {
  const store = useRef<{ key: string; series: Map<string, Map<number, number>> }>({ key: "", series: new Map() });
  return useMemo(() => {
    if (!data) return null;
    const atMs = at ? new Date(at).getTime() : NaN;
    const readingOf = (k: string) => { const r = readings?.find(x => x.key === k); return r && typeof r.value === "number" && Number.isFinite(atMs) ? r.value : null; };
    if (!windowMs) return { ...data, series: data.series.map(s => {
      const v = readingOf(s.key); const lastT = s.points.length ? new Date(s.points[s.points.length - 1][0]).getTime() : -Infinity;
      return v !== null && atMs > lastT ? { ...s, points: [...s.points, [at as string, v] as [string, number]] } : s;
    }) };
    if (store.current.key !== key) store.current = { key, series: new Map() };
    const cut = Date.now() - windowMs;
    return { ...data, series: data.series.map(s => {
      let buf = store.current.series.get(s.key);
      if (!buf) { buf = new Map(); store.current.series.set(s.key, buf); }
      for (const [t, v] of s.points) { const ms = new Date(t).getTime(); if (Number.isFinite(ms)) buf.set(ms, v); }
      const v = readingOf(s.key); if (v !== null) buf.set(atMs, v);
      for (const t of [...buf.keys()]) if (t < cut) buf.delete(t);
      return { ...s, points: [...buf.entries()].sort((a, b) => a[0] - b[0]).map(([t, x]) => [new Date(t).toISOString(), x] as [string, number]) };
    }) };
  }, [data, key, windowMs, readings, at]);
}

export default function MetricsPage({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const [range, setRange] = useState(RANGES[0]);
  const metrics = useMetrics(siteId, range.hours, range.step, range.poll);
  const live = useMetricsLive(siteId);
  const readings = live.data?.sites.find(x => x.siteId === siteId)?.readings ?? null;
  const at = live.data?.at ?? null;
  const shown = useRolling(metrics.data, `${siteId}:${range.key}`, range.key === "live" ? range.hours * 3_600_000 : 0, readings, at);
  const defs = metricDefsFor(siteId);
  return <div className="page3">
    <PageHead id="metrics" title="Metrics" sub={`${site.name}: ${defs.length} series from the site's sensors, each with its spec band. Readings update every 5 seconds; hover or use the arrow keys on a chart to read a value.`}>
      <div className="tabs3" role="tablist" aria-label="Range">{RANGES.map(r => <button key={r.key} type="button" role="tab" aria-selected={range.key === r.key} className={range.key === r.key ? "on" : ""} onClick={() => setRange(r)}>{r.label}</button>)}</div>
    </PageHead>
    <State remote={metrics} what="metrics" isEmpty={m => m.series.length === 0} empty="No metric series for this site yet.">
      {m => {
        const data = shown ?? m;
        const extra = [...new Set(data.series.map(s => s.key.split(":")[0]))].filter(k => !defs.some(d => seriesFor([{ key: k } as MetricSeries], d.key).length)).map(defFor);
        return <div className="charts3">{[...defs, ...extra].map((d, i) => <MetricCard key={d.key} d={d} i={i} series={seriesFor(data.series, d.key)} readings={readings} at={at} siteShort={site.short} />)}</div>;
      }}
    </State>
  </div>;
}

/* A series' latest reading: the live one when it answers, else its last point against the one before (compared at the
   digits shown, so the arrow never points at a change the figure does not show). */
function latestOf(s: MetricSeries, readings: LiveReading[] | null, at: string | null, digits: number): { id: string; name: string; value: number | null; trend: LiveTrend; state: LiveState; at: string | null } {
  const name = s.assetTag && s.assetTag !== "SITE" ? s.assetTag : s.label ?? s.key;
  const r = readings?.find(x => x.key === s.key);
  if (r && typeof r.value === "number") return { id: s.key, name, value: r.value, trend: r.trend, state: r.state, at };
  const last = s.points.at(-1), prev = s.points.at(-2);
  const round = (v: number) => Number(v.toFixed(digits));
  const trend: LiveTrend = !last || !prev ? "flat" : round(last[1]) > round(prev[1]) ? "up" : round(last[1]) < round(prev[1]) ? "down" : "flat";
  return { id: s.key, name, value: last ? last[1] : null, trend, state: bandState(last?.[1], s.spec), at: last?.[0] ?? null };
}

function MetricCard({ d, i, series: ss, readings, at, siteShort }: { d: MetricDef; i: number; series: MetricSeries[]; readings: LiveReading[] | null; at: string | null; siteShort: string }) {
  const spec = ss.find(s => s.spec)?.spec ?? null;
  const unit = ss[0]?.unit ?? d.unit;
  const latest = ss.map(s => latestOf(s, readings, at, d.digits));
  return <Reveal as="section" id={d.key} className="p3 chart-card" i={i % 2} aria-labelledby={`${d.key}-h`}>
    <div className="p-head"><h2 id={`${d.key}-h`}>{d.label}</h2><span className="meta">{ss.length ? `${unit}${spec ? `, spec ${spec.min ?? "–"} to ${spec.max ?? "–"}` : ", no spec"}${ss.length > 1 ? `, ${ss.length} series` : ""}` : ""}</span></div>
    {latest.length ? <ul className="latest3" aria-label={`${d.label}, latest readings`}>{latest.map(x => <li key={x.id} className={x.state !== "normal" ? "out" : ""}>
      {ss.length > 1 ? <span className="nm">{x.name}</span> : null}
      <span className="v">{fmtV(x.value, d.digits)}{x.value !== null && unit ? <small>{unit}</small> : null}{x.value !== null ? <TrendMark trend={x.trend} at={x.at} /> : null}</span>
      <BandMark state={x.state} />
    </li>)}</ul> : null}
    {ss.length ? <LineChart title={`${d.label} at ${siteShort}`} unit={unit} digits={d.digits} spec={spec}
      series={ss.map(s => ({ id: `${s.key}:${s.assetTag ?? ""}`, label: s.label ?? s.assetTag ?? d.label, short: s.assetTag ?? undefined, points: s.points }))} /> : <p className="st3 empty">No {d.label.toLowerCase()} series for this site.</p>}
  </Reveal>;
}
