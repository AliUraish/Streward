"use client";

/* Site KPIs from GET /api/metrics/summary: average pressure and flow, uptime, open issues, compliance, crew on
   shift and agent actions today. One figure per KPI, the label under it. */
import type { Remote } from "@/lib/reality";
import type { SiteSummary } from "@/lib/types-3";
import { NotYet } from "./ui3";

const f = (v: number | null, d = 0) => v === null ? "–" : new Intl.NumberFormat(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }).format(v);
export const KPI_DEFS: { key: keyof SiteSummary; label: string; unit?: string; digits: number; bad?: (v: number) => boolean }[] = [
  { key: "avgPressure", label: "Average pressure", unit: "bar", digits: 2 },
  { key: "avgFlow", label: "Average flow", unit: "m³/h", digits: 1 },
  { key: "uptimePct", label: "Uptime", unit: "%", digits: 1 },
  { key: "openIssues", label: "Open issues", digits: 0, bad: v => v > 0 },
  { key: "compliancePct", label: "Compliance", unit: "%", digits: 0, bad: v => v < 100 },
  { key: "crewOnShift", label: "Crew on shift", digits: 0 },
  { key: "agentActionsToday", label: "Agent actions today", digits: 0 },
];

export function Kpis({ s, remote, compact, only }: { s: SiteSummary | null; remote: Remote<unknown>; compact?: boolean; only?: (keyof SiteSummary)[] }) {
  const defs = only ? KPI_DEFS.filter(d => only.includes(d.key)) : KPI_DEFS;
  if (!s) return <div className={`kpis3 ${compact ? "compact" : ""} missing`}><NotYet remote={remote} what="the metrics summary" /></div>;
  return <dl className={`kpis3 ${compact ? "compact" : ""}`}>
    {defs.map(d => { const v = s[d.key] as number | null; return <div key={d.key} className="kpi">
      <dt>{d.label}</dt>
      <dd className={v !== null && d.key === "openIssues" && d.bad?.(v) ? "bad" : ""}>{f(v, d.digits)}{v !== null && d.unit ? <small>{d.unit}</small> : null}</dd>
    </div>; })}
  </dl>;
}
