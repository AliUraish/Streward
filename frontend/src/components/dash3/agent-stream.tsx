"use client";

/* The top of the agent view: what the agents read, as it arrives, and the readings it carries as live charts.
   The parse view streams compact JSON lines, newest at the bottom: each 5-second tick of GET /api/metrics/live (every
   site's KPIs and readings: value, previous, delta, trend, band state, unit, spec), the walk at each site, the newest
   walk labels with what the engineer saw, and the latest changes (GET /api/properties/{id}/changes?since=, read from a
   cursor). Until the live route answers, each series' last two points stand in for value and previous. The charts are
   small multiples per site over the last 15 minutes at 5-second points: seeded from the series (read again every
   minute, every 5 s while the live readings are missing), then fed by the live readings, so the window moves. */
import { memo, useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ApiError, request } from "@/lib/api";
import { list } from "@/lib/api-3";
import type { WalkLabel, WalkNow } from "@/lib/api-7";
import { useMetrics, useMetricsLive } from "@/lib/hooks-3";
import { useLabels, useWalk } from "@/lib/hooks-7";
import type { Remote } from "@/lib/reality";
import { rn, site3 } from "@/lib/sites-3";
import type { LiveFigure, LiveMetrics, LiveReading, MetricSeries, MetricsResponse, SiteId3 } from "@/lib/types-3";
import { LineChart } from "./charts";
import { bandState, defFor, seriesFor, type MetricDef } from "./factory-overview";
import { latestOf, useRolling } from "./metrics";
import { BandMark, State, TrendMark } from "./ui3";
import { stopWords } from "./walkthrough";
import css from "./agent-stream.module.css";

const WINDOW_MS = 15 * 60_000;
const CAP = 200;
/* The key series, in this order, where the site has them. */
const KEY_SERIES = ["pressure_bar", "flow_m3h", "humidity_pct", "checked_in", "vibration_mms", "temperature_c", "power_kw"];
const HOT = ["value", "state"];
const still = () => typeof window !== "undefined" && Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
const textBytes = typeof TextEncoder !== "undefined" ? new TextEncoder() : null;
const byteLength = (t: string) => (textBytes ? textBytes.encode(t).length : t.length);
const r3 = (v: number | null) => (v === null ? null : Math.round(v * 1000) / 1000);
const nf = (v: number) => new Intl.NumberFormat().format(v);
const fmtV = (v: number | null, digits: number) => (v === null ? "–" : new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(v));

const timeOf = (iso: string | null | undefined) => { const t = iso ? Date.parse(iso) : NaN; return Number.isFinite(t) ? t : 0; };

/* ---- lines ----------------------------------------------------------------------------------------------- */
type Kind = "tick" | "kpi" | "reading" | "walk" | "label" | "change";
interface TickStats { bytes: number; sites: number; out: number }
/* A tick line carries the counters for its tick, shown when it is read out. */
interface Line { id: string; kind: Kind; obj: Record<string, unknown>; bytes: number; hot: string[]; stats?: TickStats }
/* Line ids stay unique across a hot reload of this module (the run prefix changes with it). */
const RUN = Math.random().toString(36).slice(2, 8);
let seq = 0;
function makeLine(kind: Kind, obj: Record<string, unknown>, hot: string[] = []): Line {
  return { id: `${RUN}:${++seq}`, kind, obj, bytes: byteLength(JSON.stringify(obj)) + 1, hot };
}
function figure(base: Record<string, unknown>, f: LiveFigure, spec?: LiveReading["spec"]): Record<string, unknown> {
  return { ...base, value: f.value, previous: f.previous, delta: r3(f.delta), trend: f.trend, state: f.state, unit: f.unit,
    ...(spec !== undefined ? { spec: spec ? { min: spec.min ?? null, max: spec.max ?? null } : null } : {}) };
}
/* Without the live readings: each series' last two points as value and previous, the band from its spec. */
function readingsOf(m: MetricsResponse | null): { at: string | null; readings: LiveReading[] } {
  if (!m) return { at: null, readings: [] };
  let at: string | null = null;
  const readings = m.series.flatMap((x): LiveReading[] => {
    const last = x.points.at(-1), prev = x.points.at(-2);
    if (!last) return [];
    if (!at || timeOf(last[0]) > timeOf(at)) at = last[0];
    const value = last[1], previous = prev ? prev[1] : last[1], delta = r3(value - previous) ?? 0;
    return [{ key: x.key, label: x.label ?? null, assetTag: x.assetTag ?? null, unit: x.unit ?? null, spec: x.spec ?? null, value, previous, delta,
      trend: delta > 0 ? "up" : delta < 0 ? "down" : "flat", state: bandState(value, x.spec) }];
  });
  return { at, readings };
}
function labelLine(siteId: string, l: WalkLabel): Line {
  const w = l.mark?.world;
  return makeLine("label", {
    site: siteId, label: l.assetTag, verdict: l.verdict, observation: l.observation ?? l.reasons[0] ?? l.title,
    ...(l.confidence !== null ? { confidence: Math.round(l.confidence * 100) / 100 } : {}),
    ...(l.mark ? { mark: { x: r3(l.mark.x), y: r3(l.mark.y), ...(w ? { world: w.map(v => Math.round(v * 100) / 100) } : {}) } } : {}),
  });
}

/* ---- the changes, from a cursor per site ------------------------------------------------------------------- */
type Raw = Record<string, unknown>;
/* "TS-801.temperature_c = 22.1 °C (sensor:sim:TS-801)": the source reference in brackets is the record's own. */
const plainChange = (s: string) => rn(s.replace(/\s*\((?:[\w-]+:)+[^()]*\)/g, "").trim());
function useChangeFeed(siteIds: string[], onLines: (lines: Line[]) => void, intervalMs = 5_000) {
  const cb = useRef(onLines); cb.current = onLines;
  const key = siteIds.join(",");
  useEffect(() => {
    let alive = true; let timer = 0;
    const ids = key.split(",");
    const cursor = new Map<string, number>();
    async function run() {
      const got: { at: string; line: Line }[] = []; let missing = 0;
      await Promise.all(ids.map(async id => {
        try {
          const since = cursor.get(id);
          const res = await request<Raw>(`/api/properties/${encodeURIComponent(id)}/changes?latest=true&${since === undefined ? "limit=6" : `since=${since}&limit=25`}`);
          const head = Number(res.version);
          const rows = list<Raw>(res, "changes");
          /* The first answer keeps only the newest few; a backlog longer than a page skips to the newest. */
          const floor = since === undefined || rows.length >= 25 ? (Number.isFinite(head) ? head - 6 : 0) : since;
          for (const r of rows) {
            const v = Number(r.version); const summary = typeof r.summary === "string" ? plainChange(r.summary) : "";
            if (!Number.isFinite(v) || v <= floor || !summary || r.type === "scenario" || /^seeded\b/i.test(summary)) continue;
            got.push({ at: String(r.at ?? ""), line: makeLine("change", { site: id, change: v, type: String(r.type ?? ""), ...(typeof r.assetTag === "string" ? { asset: r.assetTag } : {}), summary }) });
          }
          if (Number.isFinite(head)) cursor.set(id, Math.max(since ?? 0, head));
        } catch (e) { if (e instanceof ApiError && e.notReady) missing++; }
      }));
      if (!alive) return;
      if (got.length) cb.current(got.sort((a, b) => timeOf(a.at) - timeOf(b.at)).map(g => g.line));
      timer = window.setTimeout(run, missing === ids.length ? 30_000 : intervalMs);
    }
    void run();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [key, intervalMs]);
}

/* ---- the stream: lines queue up as they arrive (capped); the parse view reads them out at a reading pace -------- */
interface Sink { q: Line[]; perStep: number; push: (batch: Line[]) => void; subscribe: (f: () => void) => () => void }
function createSink(): Sink {
  const subs = new Set<() => void>();
  const sink: Sink = {
    q: [], perStep: 1,
    push(batch) {
      if (!batch.length) return;
      sink.q.push(...batch);
      if (sink.q.length > CAP) sink.q.splice(0, sink.q.length - CAP);
      /* What is queued is read out over about 4 s, a step every 50 ms. */
      sink.perStep = Math.max(1, Math.ceil(sink.q.length / 80));
      subs.forEach(f => f());
    },
    subscribe(f) { subs.add(f); return () => { subs.delete(f); }; },
  };
  return sink;
}

/* Keys, strings, numbers and booleans in their own greys; an out-of-band value and its state in the issue signal. A
   line wraps after a comma, never inside a value. */
function renderJson(v: unknown, hot: string[]): ReactNode[] {
  const out: ReactNode[] = []; let k = 0;
  const span = (cls: string, text: string) => { out.push(<span key={k++} className={cls}>{text}</span>); };
  const comma = () => { out.push(","); out.push(<wbr key={k++} />); };
  const walk = (x: unknown, key: string, depth: number) => {
    const isHot = depth === 1 && hot.includes(key);
    if (x === null || typeof x === "boolean") span(isHot ? css.hot : css.b, String(x));
    else if (typeof x === "number") span(isHot ? css.hot : css.n, Number.isFinite(x) ? String(x) : "null");
    else if (typeof x === "string") span(isHot ? css.hot : css.s, JSON.stringify(x));
    else if (Array.isArray(x)) { out.push("["); x.forEach((y, i) => { if (i) comma(); walk(y, key, depth + 1); }); out.push("]"); }
    else if (typeof x === "object") {
      out.push("{");
      Object.entries(x as Raw).filter(([, y]) => y !== undefined).forEach(([kk, y], i) => { if (i) comma(); span(css.k, JSON.stringify(kk)); out.push(":"); walk(y, kk, depth + 1); });
      out.push("}");
    }
  };
  walk(v, "", 0);
  return out;
}
const Row = memo(function Row({ line }: { line: Line }) {
  return <li className={css.line} data-kind={line.kind}>{renderJson(line.obj, line.hot)}</li>;
});

/* ---- per site: the 15-minute window --------------------------------------------------------------------------- */
interface SiteStream { siteId: SiteId3; metrics: Remote<MetricsResponse>; rolled: MetricsResponse | null; readings: LiveReading[] | null; at: string | null }
function useSiteStream(siteId: SiteId3, live: Remote<LiveMetrics>): SiteStream {
  const liveSite = live.data?.sites.find(x => x.siteId === siteId) ?? null;
  const readings = liveSite?.readings.length ? liveSite.readings : null;
  const at = readings ? live.data?.at ?? null : null;
  const metrics = useMetrics(siteId, WINDOW_MS / 3_600_000, 5, readings && at ? 60_000 : 5_000);
  const rolled = useRolling(metrics.data, `${siteId}:agent-view`, WINDOW_MS, readings, at);
  return { siteId, metrics, rolled, readings: at ? readings : null, at };
}

export default function AgentStream() {
  const live = useMetricsLive();
  const my = useSiteStream("myer-plant", live), br = useSiteStream("bristol-pumps", live), tm = useSiteStream("tomioka-mill", live);
  const wm = useWalk("myer-plant"), wb = useWalk("bristol-pumps"), wt = useWalk("tomioka-mill");
  const lm = useLabels("myer-plant"), lb = useLabels("bristol-pumps"), lt = useLabels("tomioka-mill");
  const [sink] = useState(createSink);
  const push = sink.push;

  /* Bytes per tick: each site's latest walk, KPIs and readings, plus the label and change lines since the tick before. */
  const book = useRef({ site: new Map<string, { bytes: number; out: number; at: number }>(), extra: 0 });
  const seen = useRef({ ticks: new Map<string, string>(), labels: new Set<string>(), labelSites: new Set<string>() });
  /* The walk and labels as of this render, for the next tick to read. */
  const walkNow = useRef<Record<string, { walk: WalkNow | null; labels: WalkLabel[] }>>({});
  walkNow.current = { "myer-plant": { walk: wm.data, labels: lm.data ?? [] }, "bristol-pumps": { walk: wb.data, labels: lb.data ?? [] }, "tomioka-mill": { walk: wt.data, labels: lt.data ?? [] } };
  const pushExtra = useCallback((lines: Line[]) => {
    if (!lines.length) return;
    book.current.extra += lines.reduce((n, l) => n + l.bytes, 0);
    push(lines);
  }, [push]);

  /* A tick: the live answer's time (else the series' newest point) moved for a site. Each site's part of it is the
     walk there (where the engineer is and what it saw), the KPIs, then every reading. */
  useEffect(() => {
    const batch: Line[] = []; let readings = 0, outOfBand = 0, at: string | null = null; let sites = 0;
    for (const st of [my, br, tm]) {
      const src = st.readings && st.at ? { at: st.at, readings: st.readings, kpis: live.data?.sites.find(x => x.siteId === st.siteId)?.kpis ?? null } : { ...readingsOf(st.rolled), kpis: null };
      if (!src.at || !src.readings.length || seen.current.ticks.get(st.siteId) === src.at) continue;
      seen.current.ticks.set(st.siteId, src.at);
      const lines: Line[] = [];
      const here = walkNow.current[st.siteId]; const w = here?.walk;
      if (w) lines.push(makeLine("walk", { site: st.siteId, walking: w.walking, stop: w.stop, of: w.of, asset: w.assetTag, observation: stopWords(w, here.labels).text }));
      for (const [name, f] of Object.entries(src.kpis ?? {})) if (f) lines.push(makeLine("kpi", figure({ site: st.siteId, kpi: name }, f), f.state !== "normal" ? HOT : []));
      for (const r of src.readings) lines.push(makeLine("reading", figure({ site: st.siteId, key: r.key }, r, r.spec), r.state !== "normal" ? HOT : []));
      const out = src.readings.filter(r => r.state !== "normal").length;
      readings += src.readings.length; outOfBand += out; sites += 1;
      if (!at || timeOf(src.at) > timeOf(at)) at = src.at;
      book.current.site.set(st.siteId, { bytes: lines.reduce((n, l) => n + l.bytes, 0), out, at: Date.now() });
      batch.push(...lines);
    }
    if (!batch.length) return;
    const head = makeLine("tick", { at, sites, readings, outOfBand }, outOfBand ? ["outOfBand"] : []);
    const fresh = [...book.current.site.values()].filter(x => Date.now() - x.at < 20_000);
    head.stats = { bytes: fresh.reduce((n, x) => n + x.bytes, 0) + book.current.extra + head.bytes, sites: fresh.length, out: fresh.reduce((n, x) => n + x.out, 0) };
    book.current.extra = 0;
    push([head, ...batch]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.data, my.rolled, br.rolled, tm.rolled, push]);


  /* New walk labels: the newest two per site at first, then each one as it lands. */
  useEffect(() => {
    const lines: Line[] = [];
    for (const [id, r] of [["myer-plant", lm], ["bristol-pumps", lb], ["tomioka-mill", lt]] as const) {
      const all = r.data; if (!all) continue;
      const first = !seen.current.labelSites.has(id); seen.current.labelSites.add(id);
      const fresh = all.filter(l => !seen.current.labels.has(`${l.id}|${l.at}`)).sort((a, b) => timeOf(a.at) - timeOf(b.at));
      fresh.forEach(l => seen.current.labels.add(`${l.id}|${l.at}`));
      for (const l of first ? fresh.slice(-2) : fresh) lines.push(labelLine(id, l));
    }
    pushExtra(lines);
  }, [lm.data, lb.data, lt.data, pushExtra]);

  useChangeFeed(["myer-plant", "bristol-pumps", "tomioka-mill"], pushExtra);

  const anyReady = [live, my.metrics, br.metrics, tm.metrics].some(r => r.readiness === "ready");
  return <div className={css.wrap}>
    <ParseView sink={sink} anyReady={anyReady} />
    <section className={css.panel} aria-labelledby="av-live-h">
      <div className={css.head}><h2 id="av-live-h">Live readings · 15 min</h2></div>
      <div className={css.sites}>{[my, br, tm].map(st => <SiteGraphs key={st.siteId} st={st} />)}</div>
    </section>
  </div>;
}

/* The parse view owns the reading out, so its 50 ms steps re-render the stream alone, not the charts. */
function ParseView({ sink, anyReady }: { sink: Sink; anyReady: boolean }) {
  const [paused, setPaused] = useState(false);
  const [lines, setLines] = useState<Line[]>([]);
  const [parsed, setParsed] = useState(0);
  const [waiting, setWaiting] = useState(0);
  const [stats, setStats] = useState<TickStats>({ bytes: 0, sites: 0, out: 0 });
  useEffect(() => sink.subscribe(() => setWaiting(sink.q.length)), [sink]);
  useEffect(() => {
    if (paused) return;
    const whole = still();
    const id = window.setInterval(() => {
      const q = sink.q; if (!q.length) return;
      const take = q.splice(0, whole || q.length > 120 ? q.length : sink.perStep);
      setLines(prev => { const next = prev.length + take.length > CAP ? prev.slice(prev.length + take.length - CAP) : prev.slice(); next.push(...take); return next; });
      setParsed(p => p + take.length); setWaiting(q.length);
      const tick = take.findLast(l => l.stats)?.stats; if (tick) setStats(tick);
    }, 50);
    return () => window.clearInterval(id);
  }, [paused, sink]);
  const onPause = setPaused;
  const box = useRef<HTMLOListElement>(null);
  const stick = useRef(true);
  /* Newest at the bottom: follow it unless the reader has scrolled up or paused. */
  useEffect(() => { const el = box.current; if (el && stick.current && !paused) el.scrollTop = el.scrollHeight; }, [lines, paused]);
  return <section className={css.panel} aria-labelledby="av-parse-h">
    <div className={css.head}>
      <h2 id="av-parse-h">What the agents read</h2>
      <dl className={css.counters}>
        <div><dt>lines parsed</dt><dd>{nf(parsed)}</dd></div>
        <div><dt>bytes / tick</dt><dd>{nf(stats.bytes)}</dd></div>
        <div><dt>≈ tokens / tick</dt><dd>{nf(Math.round(stats.bytes / 4))}</dd></div>
        <div><dt>sites</dt><dd>{stats.sites}</dd></div>
        <div className={stats.out ? css.hotCount : ""}><dt>out of band</dt><dd>{stats.out}</dd></div>
      </dl>
      <span className={css.tools}>
        {paused && waiting ? <span className={css.waiting}>{nf(waiting)} waiting</span> : null}
        <button type="button" className={css.pause} aria-pressed={paused} onClick={() => onPause(!paused)}>{paused ? "Resume" : "Pause"}</button>
      </span>
    </div>
    <ol ref={box} className={css.log} role="log" aria-live="off" aria-label="Parsed lines, newest last" tabIndex={0}
      onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32; }}>
      {lines.length ? lines.map(l => <Row key={l.id} line={l} />) : <li className={css.idle}>{anyReady ? "Waiting for the next tick" : "Connecting to the live readings"}</li>}
    </ol>
  </section>;
}

/* A kind's series, one chart per spec band: lines that share a band share a chart, so a band and its out-of-band
   segments always belong to the line drawn over them. */
function bySpec(series: MetricSeries[]): MetricSeries[][] {
  const groups = new Map<string, MetricSeries[]>();
  for (const x of series) { const k = JSON.stringify([x.spec?.min ?? null, x.spec?.max ?? null]); groups.set(k, [...(groups.get(k) ?? []), x]); }
  return [...groups.values()];
}
/* Redrawn when the site's window or readings move, not on every render of the page. */
const SiteGraphs = memo(function SiteGraphs({ st }: { st: SiteStream }) {
  const site = site3(st.siteId);
  const data = st.rolled;
  const charts = data ? KEY_SERIES.map(defFor).flatMap(d => { const groups = bySpec(seriesFor(data.series, d.key)); return groups.map((g, i) => ({ d, series: g, key: `${d.key}:${i}`, split: groups.length > 1 })); }) : [];
  return <section className={css.site} aria-labelledby={`av-live-${st.siteId}`}>
    <div className={css.siteHead}><h3 id={`av-live-${st.siteId}`}>{site.name}</h3></div>
    {!data ? <State remote={st.metrics} what="the readings">{() => null}</State>
      : !charts.length ? <p className="st3 empty">No readings for this site yet.</p>
      : <ul className={css.grid}>{charts.map(c => <li key={c.key}><StreamChart d={c.d} series={c.series} split={c.split} readings={st.readings} at={st.at} siteShort={site.short} /></li>)}</ul>}
  </section>;
}, (a, b) => a.st.rolled === b.st.rolled && a.st.readings === b.st.readings && a.st.at === b.st.at && a.st.metrics.readiness === b.st.metrics.readiness && a.st.metrics.error === b.st.metrics.error);

/* One key series: the latest reading of each of its lines (value, the direction since the one before, High or Low
   outside the band) over the 15-minute chart. */
function StreamChart({ d, series, split, readings, at, siteShort }: { d: MetricDef; series: MetricSeries[]; split: boolean; readings: LiveReading[] | null; at: string | null; siteShort: string }) {
  const id = useId();
  const spec = series.find(x => x.spec)?.spec ?? null;
  const unit = series[0]?.unit ?? d.unit;
  const latest = series.map(x => latestOf(x, readings, at, d.digits));
  const title = split ? `${d.label} · ${series.map(x => x.assetTag ?? x.label ?? x.key).join(", ")}` : d.label;
  return <div className={css.chart} role="group" aria-labelledby={id}>
    <div className={css.chartHead}><span id={id} className={css.chartTitle}>{title}</span><span className={css.meta}>{unit}{spec ? `, ${spec.min ?? "–"} to ${spec.max ?? "–"}` : ""}</span></div>
    <ul className={`latest3 ${css.latest}`} aria-label={`${d.label} at ${siteShort}, latest`}>{latest.map(x => <li key={x.id} className={x.state !== "normal" ? "out" : ""}>
      {series.length > 1 ? <span className="nm">{x.name}</span> : null}
      <span className="v">{fmtV(x.value, d.digits)}{x.value !== null && unit ? <small>{unit}</small> : null}{x.value !== null ? <TrendMark trend={x.trend} at={x.at} /> : null}</span>
      <BandMark state={x.state} />
    </li>)}</ul>
    <LineChart title={`${title} at ${siteShort}`} unit={unit} digits={d.digits} spec={spec} height={136}
      series={series.map(x => ({ id: `${x.key}:${x.assetTag ?? ""}`, label: x.label ?? x.assetTag ?? d.label, short: x.assetTag ?? undefined, points: x.points }))} />
  </div>;
}
