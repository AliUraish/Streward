"use client";

/* /app/[site]/maintenance: the schedule the agents keep. The site's manager books each window on its own, for the
   obligation it serves, and lines it up with the other sites' windows over a chat (contract 4 section 7: Myer and
   Bristol's examiner visit; contract 5 section 5: Tomioka and Bristol's heritage-safe sensor work); nobody here has to
   ask. Each window shows its date and the site's local time, the assets, who scheduled it, the obligation it serves and
   the other site's window it was aligned with, with the chat that coordinated it; the obligations falling due sit in
   the same agenda by date. Fields the planner has not sent yet are left out. */
import Link from "next/link";
import { useMemo } from "react";
import { strings } from "@/lib/api-7";
import { useMaintenance, useObligations } from "@/lib/hooks-3";
import { agentName, canonicalId, isSite3, rn, site3, siteList, type Site3 } from "@/lib/sites-3";
import type { MaintenanceWindow, Obligation, SiteId3 } from "@/lib/types-3";
import { PageHead, Reveal, State, SynthTag, ago, day } from "./ui3";
import { regulationName } from "./walkthrough";
import "./dash7.css";

type Row = { at: string; kind: "window"; w: MaintenanceWindow } | { at: string; kind: "due"; o: Obligation };
const statusWord: Record<string, string> = { proposed: "proposed", approved: "approved", scheduled: "scheduled", confirmed: "confirmed", done: "done" };
const isBooked = (status: string) => ["approved", "scheduled", "confirmed", "done"].includes(status);

/* ---- the window record, whatever the planner calls its fields -------------------------------------------- */
type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const obj = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? v as Raw : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
/* Records keep provenance words for the audit trail ("Synthetic pump contractor (demo)"); the schedule shows the role. */
const clean = (s: string | null | undefined): string | null => {
  const t = (rn(s ?? "") ?? "").trim();
  return t ? t[0].toUpperCase() + t.slice(1) : null;
};
const startOf = (w: MaintenanceWindow) => { const x = w as MaintenanceWindow & Raw; return str(x.start ?? x.startsAt ?? x.startAt ?? obj(x.window).start) ?? (w.date || null); };
const endOf = (w: MaintenanceWindow) => { const x = w as MaintenanceWindow & Raw; return str(x.end ?? x.endsAt ?? x.endAt ?? x.until ?? obj(x.window).end); };
const dateOnly = (iso: string) => /^\d{4}-\d{2}-\d{2}$/.test(iso);
/* "Tue 21 Oct 2026, 09:00 to 12:00 Bristol time": a date-only window has no time; times are the site's own. */
function whenText(start: string | null, end: string | null, site: Site3, localTime?: string | null): string {
  if (!start) return "Undated";
  const d = dateOnly(start) ? new Date(`${start}T12:00:00Z`) : new Date(start);
  if (Number.isNaN(d.getTime())) return start;
  const date = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: dateOnly(start) ? "UTC" : site.tz });
  const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: site.tz });
  if (dateOnly(start)) return localTime ? `${date}, ${localTime} ${site.short} time` : date;
  const until = end && !dateOnly(end) && !Number.isNaN(new Date(end).getTime()) ? ` to ${time(end)}` : "";
  return `${date}, ${time(start)}${until} ${site.short} time`;
}
const monthOf = (iso: string) => { const d = dateOnly(iso) ? new Date(`${iso}T12:00:00Z`) : new Date(iso); return Number.isNaN(d.getTime()) ? "Undated" : d.toLocaleDateString([], { month: "long", year: "numeric", timeZone: dateOnly(iso) ? "UTC" : undefined }); };
interface Aligned { siteId: string | null; windowId: string | null; at: string | null; conversationId: string | null }
/* The other sites' windows this one was lined up with: alignedWith / coordination (a record, an id or a list). */
function alignedOf(w: MaintenanceWindow, all: MaintenanceWindow[], siteId: string): Aligned[] {
  const x = w as MaintenanceWindow & Raw;
  const raw: unknown[] = [x.alignedWith, x.coordination, x.coordinatedWith, x.alignment, x.aligned].flatMap(v => (Array.isArray(v) ? v : v ? [v] : []));
  if (x.alignedWindowId || x.alignedSiteId) raw.push({ windowId: x.alignedWindowId, siteId: x.alignedSiteId });
  const out: Aligned[] = [];
  for (const r of raw) {
    const o = typeof r === "string" ? (isSite3(r) ? { siteId: r } : { windowId: r }) : obj(r);
    const windowId = str(o.windowId ?? o.maintenanceId ?? o.id);
    const hit = windowId ? all.find(y => y.id === windowId) : undefined;
    const other = str(o.siteId) ?? strings(o.siteIds).find(s => s !== siteId) ?? hit?.siteIds.find(s => s !== siteId) ?? null;
    if (!other && !hit) continue;
    out.push({ siteId: other, windowId, at: str(o.start ?? o.date ?? o.at) ?? (hit ? startOf(hit) : null), conversationId: str(o.conversationId ?? o.callId) });
  }
  return out;
}

function WindowItem({ w, siteId, all, obligations }: { w: MaintenanceWindow; siteId: SiteId3; all: MaintenanceWindow[]; obligations: Obligation[] }) {
  const x = w as MaintenanceWindow & Raw;
  const site = site3(siteId);
  const assets = strings(x.assetTags ?? x.assets ?? x.assetTag);
  const byId = str(x.scheduledBy ?? x.proposedBy ?? x.createdBy ?? x.by ?? x.agentId);
  const approvedId = str(x.approvedBy);
  const oid = str(x.obligationId ?? obj(x.obligation).id);
  const ob = (oid ? obligations.find(o => o.id === oid) : undefined) ?? (str(obj(x.obligation).title) ? obj(x.obligation) as Obligation : undefined);
  const obTitle = clean(ob?.title ?? str(x.obligationTitle));
  const reg = ob?.regulationIds?.[0] ?? ob?.regulationId ?? null;
  const aligned = alignedOf(w, all, siteId);
  const callId = str(x.conversationId ?? x.coordinationConversationId ?? x.callId) ?? aligned.find(a => a.conversationId)?.conversationId ?? null;
  const others = w.siteIds.filter(id => id !== siteId);
  const scope = clean(w.scope); const title = clean(w.title);
  const examiner = clean(w.examiner);
  const note = clean(str(x.note ?? x.reason ?? x.why ?? obj(x.coordination).note));
  return <li className="mw7">
    <span className="r1"><span className={`sig ${isBooked(w.status) ? "ok" : "warn"}`} aria-hidden="true" /><strong className="mw-when">{whenText(startOf(w), endOf(w), site, str(x.localTime ?? x.localStart))}</strong><span className="sev">{statusWord[w.status] ?? w.status}{approvedId ? ` by ${agentName(canonicalId(approvedId))}` : ""}</span>{others.length ? <span className="tg">shared with {siteList(others)}</span> : null}<SynthTag rec={w} /></span>
    <span className="r2">{title ?? scope}</span>
    {title && scope ? <span className="r3">{scope}</span> : null}
    <span className="mw-facts">
      {assets.length ? <span>Assets <strong>{assets.join(", ")}</strong></span> : null}
      {byId ? <span>Scheduled by <strong>{agentName(canonicalId(byId))}</strong></span> : null}
      {examiner ? <span>With <strong>{examiner}</strong></span> : null}
    </span>
    {obTitle ? <span className="mw-facts"><span>For <strong>{obTitle}</strong>{reg ? `, ${regulationName(reg)}` : ""}{ob?.dueAt ? <>, due {day(ob.dueAt)}{ob.status === "overdue" || ob.status === "blocked" ? <span className="bad">, {ob.status}</span> : null}</> : null}</span></span> : null}
    {aligned.length || callId || note ? <span className="mw-co">
      {aligned.map((a, i) => { const s = a.siteId && isSite3(a.siteId) ? site3(a.siteId) : null; return <span key={`${a.windowId ?? a.siteId}-${i}`}>Aligned with {s ? `${s.short}'s` : "another site's"} window{a.at && s ? `, ${whenText(a.at, null, s)}` : ""}</span>; })}
      {note ? <span>{note}</span> : null}
      {callId ? <Link className="lnk" href={`/app/conversations?id=${encodeURIComponent(callId)}`}>Read the chat that coordinated it</Link> : null}
    </span> : null}
  </li>;
}

export default function MaintenancePage({ siteId }: { siteId: SiteId3 }) {
  /* Every site's windows, so a window lined up with another site's can name that window's day and time. */
  const all = useMaintenance();
  const mine = useMemo(() => (all.data ? all.data.filter(w => w.siteIds.includes(siteId)) : null), [all.data, siteId]);
  const windows = { ...all, data: mine };
  const obligations = useObligations(siteId);
  const rows = useMemo(() => {
    const out: Row[] = [];
    for (const w of mine ?? []) out.push({ at: startOf(w) ?? "", kind: "window", w });
    const horizon = Date.now() + 60 * 86_400_000;
    for (const o of obligations.data ?? []) if (o.dueAt && new Date(o.dueAt).getTime() < horizon) out.push({ at: o.dueAt, kind: "due", o });
    return out.sort((a, b) => a.at.localeCompare(b.at));
  }, [mine, obligations.data]);
  const shared = (mine ?? []).filter(w => w.siteIds.length > 1 || alignedOf(w, all.data ?? [], siteId).length > 0);
  const months = useMemo(() => {
    const m = new Map<string, Row[]>();
    for (const r of rows) { const k = r.at ? monthOf(r.at) : "Undated"; m.set(k, [...(m.get(k) ?? []), r]); }
    return [...m.entries()];
  }, [rows]);
  const item = (w: MaintenanceWindow) => <WindowItem key={`w-${w.id}`} w={w} siteId={siteId} all={all.data ?? []} obligations={obligations.data ?? []} />;
  return <div className="page3">
    <PageHead id="maintenance" title="Maintenance" />
    <Reveal as="section" className="p3 agenda3" aria-labelledby="agenda-h">
      <div className="p-head"><h2 id="agenda-h">Schedule</h2></div>
      {all.readiness !== "ready" && obligations.readiness !== "ready" ? <State remote={windows} what="the schedule">{() => null}</State>
        : rows.length === 0 ? <p className="st3 empty">Nothing scheduled in the next 60 days.</p>
        : <div className="agenda">{months.map(([m, list]) => <div key={m} className="month"><h3>{m}</h3><ol className="rows3 plain">{list.map(r => r.kind === "window"
          ? item(r.w)
          : <li key={`o-${r.o.id}`}><span className="r1"><span className={`sig ${r.o.status === "ok" ? "off" : r.o.status === "due_soon" ? "warn" : "bad"}`} aria-hidden="true" /><strong>{day(r.at)}</strong><span className="sev">obligation due, {ago(r.at)}</span><SynthTag rec={r.o} /></span><span className="r2">{clean(r.o.title)}{r.o.assetTag ? `, ${r.o.assetTag}` : ""}</span><span className="r3">{r.o.frequency}{r.o.regulationIds?.[0] ? `; ${regulationName(r.o.regulationIds[0])}` : ""}</span></li>)}</ol></div>)}</div>}
    </Reveal>
    <Reveal as="section" className="p3 shared3" i={1} aria-labelledby="shared-h">
      <div className="p-head"><h2 id="shared-h">Shared with other sites</h2><span className="meta">{mine ? `${shared.length} window${shared.length === 1 ? "" : "s"}` : ""}</span></div>
      <State remote={windows} what="maintenance windows" isEmpty={() => shared.length === 0} empty="No shared windows yet.">
        {() => <ul className="rows3 plain">{shared.map(item)}</ul>}
      </State>
    </Reveal>
  </div>;
}
