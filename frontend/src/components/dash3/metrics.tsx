"use client";

/* /app/[site]/metrics: pressure, flow, temperature, level, vibration and power with their spec bands. */
import { useState } from "react";
import { useMetrics } from "@/lib/hooks-3";
import { site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { LineChart } from "./charts";
import { METRIC_DEFS, seriesFor } from "./factory-overview";
import { PageHead, Reveal, State, SynthTag } from "./ui3";

const RANGES = [{ hours: 24, label: "24 hours", step: "5m" }, { hours: 168, label: "7 days", step: "30m" }];

export default function MetricsPage({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const [range, setRange] = useState(RANGES[0]);
  const metrics = useMetrics(siteId, range.hours, range.step);
  return <div className="page3">
    <PageHead id="metrics" title="Metrics" sub={`${site.name}: six series from the plant's sensors, synthetic and labelled, with each one's spec band. Hover or use the arrow keys on a chart to read a value.`}>
      <div className="tabs3" role="tablist" aria-label="Range">{RANGES.map(r => <button key={r.hours} type="button" role="tab" aria-selected={range.hours === r.hours} className={range.hours === r.hours ? "on" : ""} onClick={() => setRange(r)}>{r.label}</button>)}</div>
    </PageHead>
    <State remote={metrics} what="metrics" isEmpty={m => m.series.length === 0} empty="No metric series for this site yet.">
      {m => <div className="charts3">{METRIC_DEFS.map((d, i) => {
        const ss = seriesFor(m.series, d.key);
        const spec = ss.find(s => s.spec)?.spec ?? null;
        return <Reveal as="section" key={d.key} id={d.key} className="p3 chart-card" i={i % 2} aria-labelledby={`${d.key}-h`}>
          <div className="p-head"><h2 id={`${d.key}-h`}>{d.label}</h2><span className="meta">{ss.length ? `${ss[0].unit ?? d.unit}${spec ? `, spec ${spec.min ?? "–"} to ${spec.max ?? "–"}` : ""}${ss.length > 1 ? `, ${ss.length} circuits` : ""}` : ""}{ss.some(s => s.synthetic) || m.synthetic ? <SynthTag always /> : null}</span></div>
          {ss.length ? <LineChart title={`${d.label} at ${site.short}`} unit={ss[0].unit ?? d.unit} digits={d.digits} spec={spec}
            series={ss.map(s => ({ id: `${s.key}:${s.assetTag ?? ""}`, label: s.label ?? s.assetTag ?? d.label, points: s.points }))} /> : <p className="st3 empty">No {d.label.toLowerCase()} series for this site.</p>}
        </Reveal>;
      })}</div>}
    </State>
  </div>;
}
