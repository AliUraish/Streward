"use client";

/* /app/logs: what happened, across the three sites, newest first, with what happened since your last visit. */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { SITES3, site3 } from "@/lib/sites-3";
import { READING_TYPES, logHref, typeWord, useLogs } from "@/lib/logs-9";
import { Btn, PageHead, Reveal, State, ago } from "./ui3";
import s from "./logs.module.css";

const VISIT_KEY = "steward.logs.lastVisit";
const read = () => { try { return window.localStorage.getItem(VISIT_KEY); } catch { return null; } };
const write = (v: string) => { try { window.localStorage.setItem(VISIT_KEY, v); } catch { /* storage off */ } };
const clock = (at: string) => { const d = new Date(at); return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }); };

export default function LogsPage() {
  const logs = useLogs(150, 5_000);
  const [site, setSite] = useState<string>("");
  const [type, setType] = useState<string>("");
  const [query, setQuery] = useState("");
  const [readings, setReadings] = useState(false);
  const [shown, setShown] = useState(80);
  const [lastVisit, setLastVisit] = useState<string | null>(null);
  useEffect(() => { setLastVisit(read()); const now = new Date().toISOString(); const t = window.setTimeout(() => write(now), 4_000); return () => window.clearTimeout(t); }, []);
  const all = useMemo(() => logs.data ?? [], [logs.data]);
  const types = useMemo(() => [...new Set(all.map(e => e.type))].filter(t => readings || !READING_TYPES.has(t)).sort(), [all, readings]);
  const q = query.trim().toLowerCase();
  const items = all.filter(e => (!site || e.siteId === site) && (!type || e.type === type) && (readings || !READING_TYPES.has(e.type))
    && (!q || `${e.summary} ${e.assetTag ?? ""} ${typeWord(e.type)}`.toLowerCase().includes(q)));
  const fresh = lastVisit ? items.filter(e => e.at > lastVisit) : [];
  const counts = fresh.reduce<Record<string, number>>((m, e) => ({ ...m, [typeWord(e.type)]: (m[typeWord(e.type)] ?? 0) + 1 }), {});
  const since = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, n]) => `${n} × ${k.toLowerCase()}`).join(", ");
  const firstOld = lastVisit && fresh.length ? items.findIndex(e => e.at <= lastVisit) : -1;
  return <div className="page3">
    <PageHead id="logs" title="Logs">
      <div className="tabs3" role="group" aria-label="Filter by site">{[{ id: "", short: "All sites" }, ...SITES3].map(x => <button key={x.id || "all"} type="button" aria-pressed={site === x.id} className={site === x.id ? "on" : ""} onClick={() => setSite(x.id)}>{x.short}</button>)}</div>
    </PageHead>
    <Reveal as="section" className="p3" i={1} aria-label="Log">
      <div className={s.bar}>
        <label className="fld">Type
          <select value={type} onChange={e => setType(e.target.value)}><option value="">All types</option>{types.map(t => <option key={t} value={t}>{typeWord(t)}</option>)}</select>
        </label>
        <label className="fld">Search
          <input type="search" placeholder="Words in the log" value={query} onChange={e => setQuery(e.target.value)} autoComplete="off" spellCheck={false} />
        </label>
        <label className={s.toggle}><input type="checkbox" checked={readings} onChange={e => setReadings(e.target.checked)} />Sensor readings</label>
      </div>
      {lastVisit && fresh.length ? <p className={s.since}>Since your last visit, {ago(lastVisit)}: {since}.</p> : null}
      <State remote={logs} what="the log" isEmpty={() => items.length === 0} empty="Nothing logged yet.">
        {() => <>
          <ol className={s.list}>
            {items.slice(0, shown).map((e, i) => {
              const href = logHref(e);
              return <li key={e.id}>
                {i === firstOld ? <div className={s.divider}>Your last visit, {ago(lastVisit!)}</div> : null}
                <div className={`${s.row} ${lastVisit && e.at > lastVisit ? s.new : ""}`}>
                  <span className={s.time}>{clock(e.at)}</span>
                  <span className={s.site}>{site3(e.siteId).short}</span>
                  <span className={s.type}>{typeWord(e.type)}</span>
                  <span className={s.summary}>{href ? <Link href={href} className="lnk-plain">{e.summary || typeWord(e.type)}</Link> : e.summary}</span>
                  <span className={s.ago}>{ago(e.at)}</span>
                </div>
              </li>;
            })}
          </ol>
          {items.length > shown ? <div className={s.more}><Btn small onClick={() => setShown(n => n + 80)}>Show more</Btn></div> : null}
        </>}
      </State>
    </Reveal>
  </div>;
}
