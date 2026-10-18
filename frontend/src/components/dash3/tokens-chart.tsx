"use client";

/* Before/after tokens per mission, one row per agent: grouped horizontal bars on one axis, black and white only.
   Before is a mid grey, after is white; both are direct-labelled and named in the legend, so identity never rests on
   tone alone. Each bar carries a native tooltip and the same numbers sit in a table for screen readers. */
import { useState } from "react";
import { agentName } from "@/lib/sites-3";
import type { TokenPoint } from "@/lib/types-3";

const fmt = (v: number) => new Intl.NumberFormat().format(Math.round(v));
function niceMax(v: number) { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)); const m = v / p; return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p; }

export default function TokensChart({ points, budget, source }: { points: TokenPoint[]; budget?: number | null; source: string }) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = points.filter(p => p.before !== null || p.after !== null);
  const max = niceMax(Math.max(budget ?? 0, ...rows.flatMap(p => [p.before ?? 0, p.after ?? 0])));
  const W = 640, labelW = 132, valueW = 72, rowH = 44, bar = 12, gap = 2, top = 8, axisH = 28;
  const plotW = W - labelW - valueW;
  const H = top + rows.length * rowH + axisH;
  const x = (v: number) => labelW + (v / max) * plotW;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => t * max);
  const hasAfter = rows.some(r => r.after !== null);
  return <figure className="chart3">
    <div className="legend3" aria-hidden="true"><span><i className="sw before" />Before the reconfigure</span>{hasAfter ? <span><i className="sw after" />After</span> : null}{budget ? <span><i className="sw budget" />Budget {fmt(budget)}</span> : null}</div>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="tok-title tok-desc" preserveAspectRatio="xMinYMin meet">
      <title id="tok-title">Tokens per mission, before and after the reconfigure</title>
      <desc id="tok-desc">{rows.map(r => `${agentName(r.agentId)}: ${r.before !== null ? fmt(r.before) : "no data"} before, ${r.after !== null ? fmt(r.after) : "not yet rerun"} after`).join("; ")}.</desc>
      {ticks.map(t => <text key={t} x={x(t)} y={H - 8} className="tick" textAnchor={t === 0 ? "start" : "middle"}>{fmt(t)}</text>)}
      {budget ? <rect x={x(budget) - 1} y={top} width={2} height={rows.length * rowH} className="budget" /> : null}
      {rows.map((r, i) => {
        const y = top + i * rowH + (rowH - (bar * 2 + gap)) / 2;
        const dim = hover && hover !== r.agentId;
        return <g key={r.agentId} className={dim ? "dim" : ""} onMouseEnter={() => setHover(r.agentId)} onMouseLeave={() => setHover(null)}>
          <rect x={0} y={top + i * rowH} width={W} height={rowH} className="hit" />
          <text x={0} y={y + bar + 1} className="lbl">{agentName(r.agentId)}</text>
          {r.before !== null ? <><rect x={labelW} y={y} width={Math.max(2, x(r.before) - labelW)} height={bar} className="before"><title>{`${agentName(r.agentId)} before: ${fmt(r.before)} tokens per mission`}</title></rect>
            <text x={x(r.before) + 6} y={y + bar - 2} className="val">{fmt(r.before)}</text></> : null}
          {r.after !== null ? <><rect x={labelW} y={y + bar + gap} width={Math.max(2, x(r.after) - labelW)} height={bar} className="after"><title>{`${agentName(r.agentId)} after: ${fmt(r.after)} tokens per mission`}</title></rect>
            <text x={x(r.after) + 6} y={y + bar * 2 + gap - 2} className="val strong">{fmt(r.after)}</text></> : null}
        </g>;
      })}
    </svg>
    <figcaption>Source: {source}.</figcaption>
    <table className="sr-only"><caption>Tokens per mission by agent</caption><thead><tr><th scope="col">Agent</th><th scope="col">Before</th><th scope="col">After</th></tr></thead>
      <tbody>{rows.map(r => <tr key={r.agentId}><th scope="row">{agentName(r.agentId)}</th><td>{r.before !== null ? fmt(r.before) : "no data"}</td><td>{r.after !== null ? fmt(r.after) : "not yet rerun"}</td></tr>)}</tbody></table>
  </figure>;
}
