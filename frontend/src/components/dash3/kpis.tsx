"use client";

/* Site KPIs. The sensor figures (average pressure, flow and humidity, the crack width, employees checked in) are live
   readings from GET /api/metrics/live, every 5 s, with the direction since the previous reading and a High or Low mark
   outside the normal band; until that answers they are the figures of GET /api/metrics/summary. Uptime, open issues,
   compliance, crew on shift and agent actions come from the summary, polled every 10 s, with the direction since its
   previous answer. One figure per KPI, the label under it; the issue signal marks open issues and readings out of band. */
import { useState } from "react";
import type { Remote } from "@/lib/reality";
import type { LiveFigure, LiveKpis, LiveState, LiveTrend, MetricSeries, SiteSummary } from "@/lib/types-3";
import { BandMark, NotYet, TrendMark } from "./ui3";

const f = (v: number | null, d = 0) => v === null ? "–" : new Intl.NumberFormat(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }).format(v);
export interface KpiDef {
  key: keyof SiteSummary; label: string; unit?: string; digits: number;
  /* The live KPI that replaces the summary figure, and its label when it does (a reading now, not a 24-hour figure). */
  live?: string; liveLabel?: string;
  /* The normal band for the summary figure; live readings carry their own state. */
  band?: { min?: number; max?: number };
  /* Figures shown in the issue signal whatever the band (open issues above zero). */
  signal?: (v: number) => boolean;
}
export const KPI_DEFS: KpiDef[] = [
  { key: "avgPressure", label: "Average pressure", unit: "bar", digits: 2, live: "pressure" },
  { key: "avgFlow", label: "Average flow", unit: "m³/h", digits: 1, live: "flow" },
  { key: "uptimePct", label: "Uptime", unit: "%", digits: 1 },
  /* Preservation band 40 to 65 % (contract 5 §3); the crack is out of spec above 0.3 mm. */
  { key: "avgHumidity", label: "Average humidity", unit: "%", digits: 1, live: "humidity", band: { min: 40, max: 65 } },
  { key: "maxCrackWidth", label: "Widest crack", unit: "mm", digits: 3, live: "crackWidth", liveLabel: "Crack width", band: { max: 0.3 } },
  { key: "employeesCheckedIn", label: "Employees checked in", digits: 0, live: "checkedIn" },
  { key: "openIssues", label: "Open issues", digits: 0, signal: v => v > 0 },
  /* The real figure, styled like any other: below 100 % is normal while compliance issues are open. */
  { key: "compliancePct", label: "Compliance", unit: "%", digits: 0 },
  { key: "crewOnShift", label: "Crew on shift", digits: 0 },
  { key: "agentActionsToday", label: "Agent actions today", digits: 0 },
];
/* The portfolio's set. */
export const DEFAULT_KPIS: (keyof SiteSummary)[] = ["avgPressure", "avgFlow", "uptimePct", "employeesCheckedIn", "openIssues", "compliancePct", "crewOnShift", "agentActionsToday"];

const bandOf = (v: number | null, band?: { min?: number; max?: number }): LiveState => v === null || !band ? "normal" : band.max !== undefined && v > band.max ? "high" : band.min !== undefined && v < band.min ? "low" : "normal";
/* The direction of each figure since the previous answer (at changes once per answer, even when no value moves). */
function useTrends(values: Record<string, number | null>, at: number): Record<string, LiveTrend> {
  const [held, setHeld] = useState<{ at: number; values: Record<string, number | null>; trends: Record<string, LiveTrend> }>({ at, values, trends: {} });
  if (at !== held.at) {
    const trends: Record<string, LiveTrend> = {};
    for (const [k, v] of Object.entries(values)) { const p = held.values[k]; trends[k] = v === null || p === null || p === undefined ? "flat" : v > p ? "up" : v < p ? "down" : "flat"; }
    setHeld({ at, values, trends });
  }
  return held.trends;
}
/* A total across sites (employees checked in): the sum now and before; high or low when any site's reading is. */
export function totalOf(figures: (LiveFigure | undefined)[]): LiveFigure | undefined {
  const got = figures.filter((x): x is LiveFigure => Boolean(x) && typeof x!.value === "number");
  if (!got.length) return undefined;
  const value = got.reduce((a, x) => a + (x.value ?? 0), 0), previous = got.reduce((a, x) => a + (x.previous ?? x.value ?? 0), 0);
  const state: LiveState = got.some(x => x.state === "high") ? "high" : got.some(x => x.state === "low") ? "low" : "normal";
  return { value, previous, delta: value - previous, trend: value > previous ? "up" : value < previous ? "down" : "flat", state, unit: got[0].unit };
}

export function Kpis({ s, live, liveAt, remote, compact, only, missingText }: { s: SiteSummary | null; live?: LiveKpis | null; liveAt?: string | null; remote: Remote<unknown>; compact?: boolean; only?: (keyof SiteSummary)[]; missingText?: string }) {
  const keys = only ?? DEFAULT_KPIS;
  const defs = keys.map(k => KPI_DEFS.find(d => d.key === k)).filter((d): d is KpiDef => Boolean(d));
  const trends = useTrends(Object.fromEntries(defs.map(d => [d.key, (s?.[d.key] ?? null) as number | null])), remote.at);
  const rows = defs.map(d => {
    const lf = d.live ? live?.[d.live] : undefined;
    if (lf && typeof lf.value === "number") return { d, label: d.liveLabel ?? d.label, value: lf.value, trend: lf.trend, state: lf.state, at: liveAt ?? null };
    const value = (s?.[d.key] ?? null) as number | null;
    return { d, label: d.label, value, trend: trends[d.key] ?? "flat", state: bandOf(value, d.band), at: remote.at || null };
  });
  if (!s && !rows.some(r => r.value !== null)) return <div className={`kpis3 ${compact ? "compact" : ""} missing`}>{remote.readiness === "ready" ? <span className="st3-inline">{missingText ?? "No figures yet."}</span> : <NotYet remote={remote} what="the metrics summary" />}</div>;
  return <dl className={`kpis3 ${compact ? "compact" : ""}`}>
    {rows.map(({ d, label, value, trend, state, at }) => <div key={d.key} className="kpi">
      <dt>{label}<BandMark state={state} /></dt>
      <dd className={value !== null && (state !== "normal" || d.signal?.(value)) ? "bad" : ""}>{f(value, d.digits)}{value !== null && d.unit ? <small>{d.unit}</small> : null}{value !== null ? <TrendMark trend={trend} at={at} /> : null}</dd>
    </div>)}
  </dl>;
}

/* A site's figures from its own metric series, for when the summary does not carry them yet: the mean humidity over the
   window, the widest latest crack and the employees checked in now (the badge readers' latest count). */
export function figuresFrom(series: MetricSeries[]): Pick<SiteSummary, "avgHumidity" | "employeesCheckedIn" | "maxCrackWidth"> {
  const of = (k: string) => series.filter(s => s.key.split(":")[0] === k);
  const latest = (k: string) => of(k).map(s => s.points.at(-1)?.[1]).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const hum = of("humidity_pct").flatMap(s => s.points.map(p => p[1])).filter(Number.isFinite);
  const cracks = latest("crack_width_mm"), checked = latest("checked_in");
  return { avgHumidity: hum.length ? hum.reduce((a, b) => a + b, 0) / hum.length : null, employeesCheckedIn: checked.length ? Math.round(checked.reduce((a, b) => a + b, 0)) : null, maxCrackWidth: cracks.length ? Math.max(...cracks) : null };
}
/* A summary row with the gaps filled from the series (the summary's own values win). */
export function withFigures(s: SiteSummary | null, series: MetricSeries[] | null | undefined, siteId: string): SiteSummary | null {
  if (!series?.length) return s;
  const got = figuresFrom(series);
  if (got.avgHumidity === null && got.employeesCheckedIn === null && got.maxCrackWidth === null) return s;
  const base: SiteSummary = s ?? { siteId, avgPressure: null, avgFlow: null, uptimePct: null, openIssues: null, compliancePct: null, crewOnShift: null, agentActionsToday: null };
  return { ...base, avgHumidity: base.avgHumidity ?? got.avgHumidity, employeesCheckedIn: base.employeesCheckedIn ?? got.employeesCheckedIn, maxCrackWidth: base.maxCrackWidth ?? got.maxCrackWidth };
}
