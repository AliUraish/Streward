"use client";

/* Charts for the dashboard, inline SVG, black and white. One axis per chart, no grid lines; the spec band is a step
   of tone behind the line, values outside it are drawn in the issue signal. Every chart has a hover readout (pointer
   and arrow keys), direct labels, a legend when there is more than one series, and the numbers in a table for screen
   readers. Text stays in the ink tokens; the marks carry identity by tone and dash, never by colour alone. */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

export interface LineSeries { id: string; label: string; short?: string; points: [string, number][] }
const STROKES = [
  { stroke: "#ffffff", dash: "" }, { stroke: "#a1a1a1", dash: "" }, { stroke: "#ffffff", dash: "6 4" }, { stroke: "#a1a1a1", dash: "6 4" }, { stroke: "#6b6b6b", dash: "" },
];
const fmtN = (v: number, digits?: number) => new Intl.NumberFormat(undefined, { maximumFractionDigits: digits ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2) }).format(v);
function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / count; const p = 10 ** Math.floor(Math.log10(raw)); const m = raw / p;
  const step = (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  const out: number[] = []; for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function useWidth<T extends HTMLElement>(initial = 640) {
  const ref = useRef<T | null>(null); const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current; if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(e => { const cw = Math.round(e[0].contentRect.width); if (cw > 0) setW(cw); });
    ro.observe(el); return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}
const timeLabel = (t: number, spanMs: number) => {
  const d = new Date(t);
  return spanMs > 2 * 86_400_000 ? d.toLocaleDateString([], { weekday: "short", day: "numeric" }) : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export function LineChart({ title, unit, series, spec, height = 220, yDomain, digits }: { title: string; unit?: string | null; series: LineSeries[]; spec?: { min?: number | null; max?: number | null } | null; height?: number; yDomain?: [number, number]; digits?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const tableId = useId();
  const parsed = useMemo(() => series.map(s => ({ ...s, pts: s.points.map(([t, v]) => [new Date(t).getTime(), v] as [number, number]).filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v)).sort((a, b) => a[0] - b[0]) })).filter(s => s.pts.length), [series]);
  const M = { l: 48, r: parsed.length > 1 ? 112 : 64, t: 12, b: 28 };
  const W = Math.max(280, width), H = height, pw = W - M.l - M.r, ph = H - M.t - M.b;
  const all = parsed.flatMap(s => s.pts);
  const t0 = Math.min(...all.map(p => p[0])), t1 = Math.max(...all.map(p => p[0]));
  const vals = all.map(p => p[1]).concat([spec?.min, spec?.max].filter((v): v is number => typeof v === "number"));
  let lo = yDomain ? yDomain[0] : Math.min(...vals), hi = yDomain ? yDomain[1] : Math.max(...vals);
  if (!yDomain) { const pad = (hi - lo || Math.abs(hi) || 1) * 0.1; lo -= pad; hi += pad; }
  const x = (t: number) => M.l + (t1 > t0 ? (t - t0) / (t1 - t0) : 0.5) * pw;
  const y = (v: number) => M.t + (hi > lo ? (hi - v) / (hi - lo) : 0.5) * ph;
  const out = (v: number) => (typeof spec?.max === "number" && v > spec.max) || (typeof spec?.min === "number" && v < spec.min);
  const paths = useMemo(() => parsed.map(s => {
    let d = "", bad = "";
    s.pts.forEach(([t, v], i) => {
      d += `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
      if (i && (out(v) || out(s.pts[i - 1][1]))) bad += `M${x(s.pts[i - 1][0]).toFixed(1)},${y(s.pts[i - 1][1]).toFixed(1)}L${x(t).toFixed(1)},${y(v).toFixed(1)}`;
    });
    return { d, bad };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [parsed, W, H, lo, hi, spec?.min, spec?.max]);
  if (!parsed.length) return <div className="chart-empty">No points in this range.</div>;
  const base = parsed[0].pts;
  const hi_i = hover === null ? null : Math.max(0, Math.min(base.length - 1, hover));
  const ht = hi_i === null ? null : base[hi_i][0];
  const near = (s: (typeof parsed)[number], t: number) => { let best = s.pts[0]; for (const p of s.pts) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p; return best; };
  function move(e: PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect(); const px = (e.clientX - r.left) * (W / r.width);
    const t = t0 + ((px - M.l) / pw) * (t1 - t0);
    let lo2 = 0, hi2 = base.length - 1; while (hi2 - lo2 > 1) { const mid = (lo2 + hi2) >> 1; if (base[mid][0] < t) lo2 = mid; else hi2 = mid; }
    setHover(Math.abs(base[lo2][0] - t) < Math.abs(base[hi2][0] - t) ? lo2 : hi2);
  }
  function key(e: KeyboardEvent<SVGSVGElement>) {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); const stepN = Math.max(1, Math.round(base.length / 48)); setHover(h => Math.max(0, Math.min(base.length - 1, (h ?? base.length - 1) + (e.key === "ArrowRight" ? stepN : -stepN)))); }
    if (e.key === "Escape") setHover(null);
  }
  const span = t1 - t0;
  /* Direct labels at the line ends, pushed apart so close values never overlap. */
  const endLabels = parsed.map((s, i) => { const last = s.pts[s.pts.length - 1]; return { id: s.id, i, x: x(last[0]) + 8, y: y(last[1]) + 4, text: `${parsed.length > 1 ? `${s.short ?? s.label} ` : ""}${fmtN(last[1], digits)}` }; })
    .sort((a, b) => a.y - b.y).reduce<{ id: string; i: number; x: number; y: number; text: string }[]>((acc, l) => { const prev = acc[acc.length - 1]; acc.push(prev && l.y - prev.y < 15 ? { ...l, y: prev.y + 15 } : l); return acc; }, []);
  /* A plot narrower than three time labels (a small multiple, a phone) gets its two ends only. */
  const tickCount = pw < 200 ? 2 : W < 640 ? 3 : 5;
  const xticks = Array.from({ length: tickCount }, (_, i) => t0 + (span * i) / (tickCount - 1));
  const yticks = niceTicks(lo, hi, 4).filter(v => v >= lo && v <= hi);
  const stats = parsed.map(s => { const v = s.pts.map(p => p[1]); return { label: s.label, latest: v[v.length - 1], min: Math.min(...v), max: Math.max(...v) }; });
  const summary = `${title}${unit ? ` in ${unit}` : ""}, ${timeLabel(t0, span)} to ${timeLabel(t1, span)}. ` + stats.map(s => `${parsed.length > 1 ? `${s.label}: ` : ""}latest ${fmtN(s.latest, digits)}, low ${fmtN(s.min, digits)}, high ${fmtN(s.max, digits)}`).join("; ") + (spec && (spec.min != null || spec.max != null) ? `. Spec ${spec.min ?? "–"} to ${spec.max ?? "–"}.` : ".");
  const readX = ht === null ? 0 : x(ht);
  return <figure className="lc3" ref={ref}>
    {parsed.length > 1 ? <div className="legend3" aria-hidden="true">{parsed.map((s, i) => <span key={s.id}><svg width="18" height="10"><line x1="0" y1="5" x2="18" y2="5" stroke={STROKES[i % STROKES.length].stroke} strokeWidth="2" strokeDasharray={STROKES[i % STROKES.length].dash} /></svg>{s.label}</span>)}{spec ? <span><i className="sw band" />spec band</span> : null}</div> : null}
    <div className="lc-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={summary} aria-describedby={tableId} tabIndex={0} onPointerMove={move} onPointerLeave={() => setHover(null)} onKeyDown={key} onBlur={() => setHover(null)}>
        {spec && (spec.min != null || spec.max != null) ? <rect className="band" x={M.l} width={pw} y={y(Math.min(hi, spec.max ?? hi))} height={Math.max(0, y(Math.max(lo, spec.min ?? lo)) - y(Math.min(hi, spec.max ?? hi)))} /> : null}
        {yticks.map(v => <text key={v} className="tick" x={M.l - 8} y={y(v) + 4} textAnchor="end">{fmtN(v)}</text>)}
        {xticks.map((t, i) => <text key={t} className="tick" x={x(t)} y={H - 8} textAnchor={i === 0 ? "start" : i === xticks.length - 1 ? "end" : "middle"}>{timeLabel(t, span)}</text>)}
        {paths.map((p, i) => <g key={parsed[i].id}><path d={p.d} className="line" stroke={STROKES[i % STROKES.length].stroke} strokeDasharray={STROKES[i % STROKES.length].dash} />{p.bad ? <path d={p.bad} className="line out" /> : null}</g>)}
        {endLabels.map(l => <text key={l.id} className={`end ${l.i ? "" : "strong"}`} x={l.x} y={l.y}>{l.text}</text>)}
        {ht !== null ? <g className="hover">
          <rect x={readX - 1} y={M.t} width={2} height={ph} className="cursor" />
          {parsed.map((s, i) => { const p = near(s, ht); return <rect key={s.id} x={x(p[0]) - 4} y={y(p[1]) - 4} width={8} height={8} className={`mark ${out(p[1]) ? "out" : ""}`} fill={STROKES[i % STROKES.length].stroke} />; })}
        </g> : null}
      </svg>
      {ht !== null ? <div className="readout3" style={{ left: `${(readX / W) * 100}%`, transform: `translateX(${readX > W * 0.66 ? "-100%" : "8px"})` }} aria-live="polite">
        <span className="t">{new Date(ht).toLocaleString([], span < 3_600_000 ? { hour: "2-digit", minute: "2-digit", second: "2-digit" } : { weekday: "short", hour: "2-digit", minute: "2-digit" })}</span>
        {parsed.map(s => { const p = near(s, ht); return <span key={s.id} className={out(p[1]) ? "bad" : ""}>{parsed.length > 1 ? `${s.label}: ` : ""}{fmtN(p[1], digits)}{unit ? ` ${unit}` : ""}</span>; })}
      </div> : null}
    </div>
    <table className="sr-only" id={tableId}><caption>{title}</caption><thead><tr><th scope="col">Series</th><th scope="col">Latest</th><th scope="col">Low</th><th scope="col">High</th></tr></thead>
      <tbody>{stats.map(s => <tr key={s.label}><th scope="row">{s.label}</th><td>{fmtN(s.latest, digits)}</td><td>{fmtN(s.min, digits)}</td><td>{fmtN(s.max, digits)}</td></tr>)}</tbody></table>
  </figure>;
}

/* A sparkline: the last stretch of one series with its spec band; no axes. */
export function Sparkline({ points, spec, label }: { points: [string, number][]; spec?: { min?: number | null; max?: number | null } | null; label: string }) {
  const pts = points.map(([t, v]) => [new Date(t).getTime(), v] as [number, number]).filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v));
  if (pts.length < 2) return <div className="spark3 empty" aria-label={`${label}: no points`} />;
  const W = 200, H = 48;
  const vs = pts.map(p => p[1]).concat([spec?.min, spec?.max].filter((v): v is number => typeof v === "number"));
  let lo = Math.min(...vs), hi = Math.max(...vs); const pad = (hi - lo || 1) * 0.12; lo -= pad; hi += pad;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const x = (t: number) => ((t - t0) / (t1 - t0 || 1)) * W, y = (v: number) => ((hi - v) / (hi - lo)) * H;
  const d = pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const last = pts[pts.length - 1][1];
  const bad = (typeof spec?.max === "number" && last > spec.max) || (typeof spec?.min === "number" && last < spec.min);
  return <svg className={`spark3 ${bad ? "bad" : ""}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${label}, last ${pts.length} points, latest ${fmtN(last)}${bad ? ", outside spec" : ""}`}>
    {spec && (spec.min != null || spec.max != null) ? <rect className="band" x={0} width={W} y={y(Math.min(hi, spec.max ?? hi))} height={Math.max(0, y(Math.max(lo, spec.min ?? lo)) - y(Math.min(hi, spec.max ?? hi)))} /> : null}
    <path d={d} className="line" vectorEffect="non-scaling-stroke" />
  </svg>;
}

/* Horizontal bars, one row per label, direct-labelled; hover dims the others. */
export function BarChart({ rows, unit, title, digits }: { rows: { label: string; value: number; tone?: "strong" | "dim" | "bad" }[]; unit?: string; title: string; digits?: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const tableId = useId();
  if (!rows.length) return <div className="chart-empty">No values yet.</div>;
  const max = Math.max(...rows.map(r => r.value), 0) || 1;
  return <figure className="bc3">
    <ul aria-describedby={tableId}>{rows.map(r => <li key={r.label} className={hover && hover !== r.label ? "dim" : ""} onMouseEnter={() => setHover(r.label)} onMouseLeave={() => setHover(null)} title={`${r.label}: ${fmtN(r.value, digits)}${unit ? ` ${unit}` : ""}`}>
      <span className="lbl">{r.label}</span>
      <span className="track"><span className={`fill ${r.tone ?? ""}`} style={{ width: `${Math.max(1, (r.value / max) * 100)}%` }} /></span>
      <span className="val">{fmtN(r.value, digits)}{unit ? <small> {unit}</small> : null}</span>
    </li>)}</ul>
    <table className="sr-only" id={tableId}><caption>{title}</caption><tbody>{rows.map(r => <tr key={r.label}><th scope="row">{r.label}</th><td>{fmtN(r.value, digits)}{unit ? ` ${unit}` : ""}</td></tr>)}</tbody></table>
  </figure>;
}

/* Columns over days (A2A messages per day). */
export function ColumnChart({ points, title, unit }: { points: [string, number][]; title: string; unit?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const tableId = useId();
  if (!points.length) return <div className="chart-empty">No values yet.</div>;
  const max = Math.max(...points.map(p => p[1]), 0) || 1;
  /* A date without a time ("2026-10-16") is that calendar day, not UTC midnight shown as the day before. */
  const label = (t: string) => { const d = /^\d{4}-\d{2}-\d{2}$/.test(t) ? new Date(`${t}T12:00:00`) : new Date(t); return Number.isNaN(d.getTime()) ? t : d.toLocaleDateString([], { weekday: "short", day: "numeric" }); };
  return <figure className="cc3">
    <div className="cols" role="img" aria-label={`${title}: ${points.map(p => `${label(p[0])} ${fmtN(p[1])}`).join(", ")}`} aria-describedby={tableId}>
      {points.map((p, i) => <div key={p[0]} className={`col ${hover !== null && hover !== i ? "dim" : ""}`} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} title={`${label(p[0])}: ${fmtN(p[1])}${unit ? ` ${unit}` : ""}`}>
        <span className="v">{hover === i || i === points.length - 1 ? fmtN(p[1]) : ""}</span>
        <span className="bar" style={{ height: `${Math.max(2, (p[1] / max) * 100)}%` }} />
        <span className="d">{label(p[0])}</span>
      </div>)}
    </div>
    <table className="sr-only" id={tableId}><caption>{title}</caption><tbody>{points.map(p => <tr key={p[0]}><th scope="row">{label(p[0])}</th><td>{fmtN(p[1])}</td></tr>)}</tbody></table>
  </figure>;
}
