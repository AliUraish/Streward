"use client";

/* /app/[site]/maintenance: the schedule, including the windows the two factories share (contract 4 section 7), and
   the obligations falling due, as one agenda by date. */
import Link from "next/link";
import { useMemo } from "react";
import { useMaintenance, useObligations } from "@/lib/hooks-3";
import { site3 } from "@/lib/sites-3";
import type { MaintenanceWindow, Obligation, SiteId3 } from "@/lib/types-3";
import { PageHead, Reveal, State, SynthTag, ago, day } from "./ui3";

type Row = { at: string; kind: "window"; w: MaintenanceWindow } | { at: string; kind: "due"; o: Obligation };
const statusWord: Record<string, string> = { proposed: "proposed", approved: "approved by the Operations Director", done: "done" };

export default function MaintenancePage({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const windows = useMaintenance(siteId);
  const obligations = useObligations(siteId);
  const rows = useMemo(() => {
    const out: Row[] = [];
    for (const w of windows.data ?? []) out.push({ at: w.date, kind: "window", w });
    const horizon = Date.now() + 60 * 86_400_000;
    for (const o of obligations.data ?? []) if (o.dueAt && new Date(o.dueAt).getTime() < horizon) out.push({ at: o.dueAt, kind: "due", o });
    return out.sort((a, b) => a.at.localeCompare(b.at));
  }, [windows.data, obligations.data]);
  const shared = (windows.data ?? []).filter(w => w.siteIds.length > 1);
  const months = useMemo(() => {
    const m = new Map<string, Row[]>();
    for (const r of rows) { const d = new Date(r.at); const k = Number.isNaN(d.getTime()) ? "Undated" : d.toLocaleDateString([], { month: "long", year: "numeric" }); m.set(k, [...(m.get(k) ?? []), r]); }
    return [...m.entries()];
  }, [rows]);
  return <div className="page3">
    <PageHead id="maintenance" title="Maintenance" sub={`${site.name}: maintenance windows the Plant Manager schedules, the ones shared with the other factory, and the obligations falling due in the next 60 days.`} />
    <Reveal as="section" className="p3 shared3" aria-labelledby="shared-h">
      <div className="p-head"><h2 id="shared-h">Shared with the other factory</h2><span className="meta">{windows.data ? `${shared.length} window${shared.length === 1 ? "" : "s"}` : ""}</span></div>
      <State remote={windows} what="maintenance windows" isEmpty={() => shared.length === 0} empty="No shared windows yet. The shared examiner visit scenario proposes one.">
        {() => <ul className="rows3 plain">{shared.map(w => <li key={w.id}>
          <span className="r1"><span className={`sig ${w.status === "approved" || w.status === "done" ? "ok" : "warn"}`} aria-hidden="true" /><strong>{w.title ?? w.scope}</strong><span className="tg">both factories</span><SynthTag rec={w} /></span>
          <span className="r2">{day(w.date)}, {statusWord[w.status] ?? w.status}{w.examiner ? `; examiner ${w.examiner}` : ""}</span>
          {w.title && w.scope ? <span className="r3">{w.scope}</span> : null}
          {w.conversationId ? <Link className="lnk r3" href={`/app/conversations?id=${encodeURIComponent(w.conversationId)}`}>Read the call that agreed it</Link> : null}
        </li>)}</ul>}
      </State>
    </Reveal>
    <Reveal as="section" className="p3 agenda3" i={1} aria-labelledby="agenda-h">
      <div className="p-head"><h2 id="agenda-h">Schedule</h2><span className="meta">windows and obligations by date</span></div>
      {windows.readiness !== "ready" && obligations.readiness !== "ready" ? <State remote={windows} what="the schedule">{() => null}</State>
        : rows.length === 0 ? <p className="st3 empty">Nothing scheduled in the next 60 days.</p>
        : <div className="agenda">{months.map(([m, list]) => <div key={m} className="month"><h3>{m}</h3><ol className="rows3 plain">{list.map(r => r.kind === "window"
          ? <li key={`w-${r.w.id}`}><span className="r1"><span className={`sig ${r.w.status === "approved" || r.w.status === "done" ? "ok" : "warn"}`} aria-hidden="true" /><strong>{day(r.at)}</strong><span className="sev">maintenance window{r.w.siteIds.length > 1 ? ", both factories" : ""}</span><SynthTag rec={r.w} /></span><span className="r2">{r.w.scope}</span><span className="r3">{statusWord[r.w.status] ?? r.w.status}{r.w.examiner ? `; examiner ${r.w.examiner}` : ""}</span></li>
          : <li key={`o-${r.o.id}`}><span className="r1"><span className={`sig ${r.o.status === "ok" ? "off" : r.o.status === "due_soon" ? "warn" : "bad"}`} aria-hidden="true" /><strong>{day(r.at)}</strong><span className="sev">obligation due, {ago(r.at)}</span><SynthTag rec={r.o} /></span><span className="r2">{r.o.title}{r.o.assetTag ? `, ${r.o.assetTag}` : ""}</span><span className="r3">{r.o.frequency}</span></li>)}</ol></div>)}</div>}
    </Reveal>
  </div>;
}
