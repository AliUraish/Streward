"use client";

/* /app/[site]/employees: the employees' badge log (REALITY-CONTRACT-8.md section 5). Fourteen working days per employee,
   in the site's own dates: on time, late (by how many minutes), absent, or a rest day. When someone is late two working
   days running, the People Officer looks into it: a chat with the site's manager, then a call to the employee (on your
   phone: you are the employee), and the case closes with what was agreed. Agent mode shows the log and the cases as an
   agent reads them. */
import Link from "next/link";
import { useMemo } from "react";
import { attendancePath, attendanceText, callStatusWord, casesPath, caseStatusWord, resultWord, type AttendanceCase, type AttendanceEntry, type AttendanceLog } from "@/lib/api-10";
import { useAttendance, useAttendanceCases, useConversation, usePhoneCall } from "@/lib/hooks-10";
import { site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { AgentText, ViewSwitch, useViewMode } from "./mode10";
import { JaText, Reveal, State, ago, when } from "./ui3";
import "./dash10.css";

const DAYS = 14;
/* "Thu" and "15" for a local date (YYYY-MM-DD), read as that calendar day wherever the viewer is. */
const dayParts = (date: string) => {
  const d = new Date(`${date}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return { wd: "", dn: date };
  return { wd: d.toLocaleDateString([], { weekday: "short", timeZone: "UTC" }), dn: String(d.getUTCDate()) };
};
const longDay = (date: string) => { const d = new Date(`${date}T12:00:00Z`); return Number.isNaN(d.getTime()) ? date : d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }); };
const timeOf = (v: string | null) => { if (!v) return ""; const m = /T?(\d{2}:\d{2})/.exec(v); return m ? m[1] : v; };

function Cell({ e, date }: { e: AttendanceEntry | undefined; date: string }) {
  if (!e) return <td className="d none"><span className="sr-only">{longDay(date)}: no entry</span></td>;
  const said = e.status === "late" ? `late by ${e.lateMinutes ?? "?"} minutes${e.checkIn ? `, in at ${timeOf(e.checkIn)}` : ""}`
    : e.status === "absent" ? "absent" : e.status === "rest_day" ? "rest day" : `on time${e.checkIn ? `, in at ${timeOf(e.checkIn)}` : ""}`;
  return <td className={`d ${e.status}`} title={`${longDay(date)}: ${said}`}>
    <span aria-hidden="true">{e.status === "late" ? `+${e.lateMinutes ?? "?"}` : e.status === "absent" ? "A" : e.status === "rest_day" ? "–" : ""}</span>
    <span className="sr-only">{longDay(date)}: {said}</span>
  </td>;
}

function BadgeGrid({ log }: { log: AttendanceLog }) {
  const dates = log.dates.slice(-DAYS);
  if (!log.employees.length) return <p className="st3 empty">No badge entries yet.</p>;
  return <>
    <div className="emp-scroll" tabIndex={0} role="region" aria-label="Badge log, scrolls sideways">
      <table className="emp-grid">
        <caption className="sr-only">Badge log for the last {dates.length} days</caption>
        <thead><tr><th scope="col" className="who">Employee</th>{dates.map(d => { const p = dayParts(d); return <th key={d} scope="col" className="d"><span className="wd">{p.wd}</span><span className="dn">{p.dn}</span></th>; })}</tr></thead>
        <tbody>{log.employees.map(emp => { const by = new Map(emp.entries.map(x => [x.date, x])); const lates = emp.entries.filter(x => x.status === "late").length;
          return <tr key={emp.crewId}>
            <th scope="row" className="who"><strong>{emp.name}</strong><small>{[emp.role, emp.shift].filter(Boolean).join(", ")}{lates ? `; late ${lates}×` : ""}</small></th>
            {dates.map(d => <Cell key={d} e={by.get(d)} date={d} />)}
          </tr>; })}</tbody>
      </table>
    </div>
    <ul className="emp-legend" aria-label="Key">
      <li><span className="sw on_time" aria-hidden="true" />On time</li>
      <li><span className="sw late" aria-hidden="true">+12</span>Late, minutes</li>
      <li><span className="sw absent" aria-hidden="true">A</span>Absent</li>
      <li><span className="sw rest_day" aria-hidden="true">–</span>Rest day</li>
    </ul>
  </>;
}

function CaseItem({ c }: { c: AttendanceCase }) {
  const chat = useConversation(c.conversationIds[0] ?? null);
  const call = usePhoneCall(c.callId, c.status === "calling");
  const s = chat.data?.summary;
  const o = c.outcome ?? (call.data?.outcome ? { result: call.data.outcome.result, decision: call.data.outcome.decision, summary: call.data.outcome.summary } : null);
  const open = c.status === "open" || c.status === "calling";
  return <li className={`case10 ${open ? "open" : ""}`}>
    <p className="r1"><span className={`sig ${open ? "warn" : c.status === "unreachable" ? "bad" : "ok"}`} aria-hidden="true" /><strong>{c.name}</strong>{c.role ? <span className="sev">{c.role}</span> : null}<span className={`chip10 ${open ? "held" : c.status === "unreachable" ? "bad" : "ok"}`}>{caseStatusWord(c.status)}</span></p>
    {c.days.length ? <p className="case-days">{c.days.map(d => <span key={d.date} className="day">{longDay(d.date)}<strong>+{d.lateMinutes ?? "?"} min</strong></span>)}</p> : null}
    {s ? <div className="case-chat"><span className="k">People Officer with the manager</span><p>{s.headline}</p>{s.decisions[0] ? <p className="r3">{s.decisions[0]}</p> : null}</div>
      : c.conversationIds.length ? <p className="r3">The People Officer is talking it over with the site manager.</p> : null}
    {o ? <div className="case-out"><span className="k">The call</span><p>{o.result ? <span className="chip10 ok">{resultWord(o.result)}</span> : null}<JaText text={o.decision ?? o.summary ?? ""} /></p></div>
      : call.data ? <p className="r3">Call: {callStatusWord(call.data.status)}</p> : null}
    <p className="case-links r3">
      {c.openedAt || c.resolvedAt ? <span>{[c.openedAt ? `Opened ${ago(c.openedAt)}` : "", c.resolvedAt ? `resolved ${when(c.resolvedAt)}` : ""].filter(Boolean).join(", ")}</span> : null}
      {c.conversationIds[0] ? <Link className="lnk" href={`/app/conversations?id=${encodeURIComponent(c.conversationIds[0])}`}>Read the chat</Link> : null}
      {c.callId ? <Link className="lnk" href={`/app/conversations?call=${encodeURIComponent(c.callId)}`}>Read the call</Link> : null}
    </p>
  </li>;
}

export default function EmployeesPage({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const log = useAttendance(siteId, DAYS);
  const cases = useAttendanceCases(siteId);
  const [view, setView] = useViewMode("steward.employees.view");
  /* The cases endpoint is the source; the log's own copy fills in until it answers. */
  const allCases = useMemo(() => {
    const list = cases.data ?? log.data?.cases ?? [];
    return [...list].sort((a, b) => Number(b.status === "open" || b.status === "calling") - Number(a.status === "open" || a.status === "calling") || (b.openedAt ?? "").localeCompare(a.openedAt ?? ""));
  }, [cases.data, log.data]);
  const agent = view === "agent";
  return <div className="page3">
    <Reveal as="header" className="sh3 page hd10">
      <h1 id="employees-h">Employees</h1>
      <div className="hd-switch">{view ? <ViewSwitch agent={agent} onChange={a => setView(a ? "agent" : "human")} label="Agent mode for this page" /> : null}</div>
      {!agent ? <p className="hd-sub">Badge check-ins at {site.short} for the last {DAYS} days, in local time. When someone is late two working days running, the People Officer calls them and agrees a fix.</p> : null}
    </Reveal>
    {agent ? <Reveal as="section" className="p3" i={1} aria-label="The badge log as an agent reads it">
      <State remote={log} what="the badge log">
        {l => <AgentText what="the badge log" endpoints={[attendancePath(siteId, DAYS), casesPath(siteId, 30)]} text={attendanceText(l, allCases)} json={{ log: l, cases: allCases }} />}
      </State>
    </Reveal> : <>
      <Reveal as="section" className="p3 emp10" i={1} aria-labelledby="badge-h">
        <div className="p-head"><h2 id="badge-h">Badge log</h2>{log.data?.timezone ? <span className="meta">{log.data.timezone}</span> : null}</div>
        <State remote={log} what="the badge log" isEmpty={l => l.employees.length === 0} empty="No badge entries yet.">
          {l => <BadgeGrid log={l} />}
        </State>
      </Reveal>
      <Reveal as="section" className="p3" i={2} aria-labelledby="cases-h">
        <div className="p-head"><h2 id="cases-h">Late twice running</h2><span className="meta">{allCases.length ? `${allCases.filter(c => c.status === "open" || c.status === "calling").length} open, ${allCases.length} in all` : ""}</span></div>
        <State remote={cases.data || !log.data ? cases : { ...cases, data: log.data.cases, readiness: "ready" as const }} what="cases" isEmpty={() => allCases.length === 0} empty="Nobody has been late two working days running.">
          {() => <ol className="rows3 plain cases10">{allCases.map(c => <CaseItem key={c.id} c={c} />)}</ol>}
        </State>
      </Reveal>
    </>}
  </div>;
}
