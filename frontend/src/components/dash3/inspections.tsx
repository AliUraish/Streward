"use client";

/* The Site Inspector's inspections (REALITY-CONTRACT-8.md section 6), on the site's compliance page (in full) and its
   overview (compact). The latest inspection: what the inspector found, then the chain in order: the report chat with
   the site's Compliance Officer, the evidence to the manager, the manager's email to you (owner) with Compliance Counsel
   copied, Compliance Counsel's email to you (contractor), the manager's call with you (contractor), and the booking.
   Each step links to its chat, outbox item, call or maintenance window. Agent mode shows the same as text. */
import Link from "next/link";
import { chainOf, inspectionText, inspectionsPath, type ChainRow, type Inspection } from "@/lib/api-10";
import { useInspections } from "@/lib/hooks-10";
import { agentName, site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { AgentText, ViewSwitch, useViewMode } from "./mode10";
import { JaText, Reveal, State, ago, day, when } from "./ui3";
import "./dash10.css";

const enc = encodeURIComponent;
function stepHref(r: ChainRow, siteId: SiteId3): { href: string; label: string } | null {
  if (!r.ref) return null;
  switch (r.kind) {
    case "chat": return { href: `/app/conversations?id=${enc(r.ref)}`, label: "Read the chat" };
    case "outbox": return { href: `/app/notifications#ob-${enc(r.ref)}`, label: "The email" };
    case "call": return { href: `/app/conversations?call=${enc(r.ref)}`, label: "The call" };
    case "window": return { href: `/app/${siteId}#maintenance`, label: "Maintenance" };
  }
}
const stateWord = (s: string) => (s === "completed" ? "done" : s === "failed" ? "stopped" : "in progress");

function Chain({ i, siteId, compact }: { i: Inspection; siteId: SiteId3; compact?: boolean }) {
  const rows = chainOf(i);
  const next = rows.findIndex(r => !r.step);
  if (compact) return <ol className="oa-steps insp-chips" aria-label="Steps">{rows.map((r, k) => <li key={r.key} className={r.step ? "done" : k === next && i.state === "running" ? "now" : ""} title={r.step?.summary ?? undefined}>
    <span className={`sig ${r.step ? "ok" : "off"}`} aria-hidden="true" />{r.label}<span className="sr-only">{r.step ? ", done" : k === next ? ", next" : ", waiting"}</span>
  </li>)}</ol>;
  return <ol className="insp-chain" aria-label="The chain">{rows.map((r, k) => { const link = stepHref(r, siteId);
    return <li key={r.key} className={r.step ? "done" : k === next && i.state === "running" ? "now" : ""}>
      <span className="n" aria-hidden="true">{k + 1}</span>
      <div className="say">
        <p className="r1"><strong>{r.label}</strong>{r.step?.at ? <span className="r3">{when(r.step.at)}</span> : <span className="r3">{k === next && i.state === "running" ? "next" : r.step ? "" : "waiting"}</span>}</p>
        {r.step?.summary ? <p className="r2"><JaText text={r.step.summary} /></p> : null}
        {link || r.extraRef ? <p className="links">
          {link ? <Link className="lnk" href={link.href}>{link.label}</Link> : null}
          {r.extraRef ? <Link className="lnk" href={`/app/notifications#ob-${enc(r.extraRef)}`}>{r.kind === "window" ? "The confirmation" : "The evidence email"}</Link> : null}
        </p> : null}
      </div>
    </li>; })}</ol>;
}

function Finding({ i }: { i: Inspection }) {
  const p = i.primary;
  const also = i.findings.filter(f => f !== p && !(p && f.assetTag === p.assetTag && f.title === p.title));
  return <div className="insp-find">
    {p ? <>
      <p className="r1"><span className={`sig ${p.severity === "high" ? "bad" : "warn"}`} aria-hidden="true" /><strong>{p.assetTag ? `${p.assetTag}: ` : ""}<JaText text={p.title} /></strong>{p.severity ? <span className="sev">{p.severity}</span> : null}</p>
      {p.reasons.length ? <ul className="insp-reasons">{p.reasons.slice(0, 3).map((r, k) => <li key={k}><JaText text={r} /></li>)}</ul> : null}
    </> : <p className="r2">{i.state === "running" ? "Inspecting." : "Nothing out of order."}</p>}
    {also.length ? <p className="r3">Also noted: {also.slice(0, 4).map(f => `${f.assetTag ? `${f.assetTag} ` : ""}${f.title}`).join("; ")}</p> : null}
  </div>;
}

export function LatestInspection({ siteId, compact, i = 1, title = "Latest inspection" }: { siteId: SiteId3; compact?: boolean; i?: number; title?: string }) {
  const list = useInspections(siteId, 5);
  const [view, setView] = useViewMode(`steward.inspections.view`);
  const hid = `insp-${siteId}-h`;
  const latest = list.data?.[0] ?? null;
  const agent = !compact && view === "agent";
  return <Reveal as="section" className={`p3 insp10 ${compact ? "compact" : ""}`} i={i} aria-labelledby={hid} id={compact ? undefined : `inspections-${siteId}`}>
    <div className="p-head"><h2 id={hid}>{title}</h2>
      <span className="insp-tools">
        {latest ? <span className="meta">{agentName(latest.inspectorId)}, {stateWord(latest.state)}, {ago(latest.startedAt)}</span> : null}
        {compact ? <Link className="lnk" href={`/app/${siteId}#compliance`}>Compliance</Link> : view ? <ViewSwitch small agent={agent} onChange={a => setView(a ? "agent" : "human")} label="Agent mode for the inspection" /> : null}
      </span>
    </div>
    <State remote={list} what="inspections" isEmpty={l => l.length === 0} empty={`No inspection at ${site3(siteId).short} yet; the Site Inspector visits each site in turn.`}>
      {l => agent ? <AgentText what="the inspection" endpoints={[inspectionsPath(siteId, 5)]} text={l.map(inspectionText).join("\n\n")} json={l[0]} />
        : <>
          <Finding i={l[0]} />
          <Chain i={l[0]} siteId={siteId} compact={compact} />
          {!compact && l.length > 1 ? <div className="insp-earlier"><h3>Earlier</h3><ul className="rows3 plain">{l.slice(1).map(x => <li key={x.id}>
            <span className="r1"><strong>{x.primary ? `${x.primary.assetTag ? `${x.primary.assetTag}: ` : ""}${x.primary.title}` : "Nothing out of order"}</strong><span className="sev">{stateWord(x.state)}</span></span>
            <span className="r3">{day(x.startedAt)}, {chainOf(x).filter(r => r.step).length} of 6 steps</span>
          </li>)}</ul></div> : null}
        </>}
    </State>
  </Reveal>;
}
