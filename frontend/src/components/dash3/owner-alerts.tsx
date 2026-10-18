"use client";

/* Owner alerts (REALITY-CONTRACT-7.md section 2): when a walkthrough finds a compliance problem, the site's team works it
   (the issue, a chat with the Compliance Officer, a chat with another site, the manager's decision), then the
   Compliance Officer emails you the file and the evidence and the Steward Dispatch Line calls you. Each alert shows its
   steps as they arrive, the email (subject, attachments) and the call, in plain words for what happened to each:
   "Emailed you", "Ready to send: live messaging is off", "Held: today's alert limit reached", or why it failed. */
import Link from "next/link";
import type { AlertCall, AlertEmail, OwnerAlert } from "@/lib/api-7";
import { useOwnerAlerts } from "@/lib/hooks-7";
import { site3 } from "@/lib/sites-3";
import type { SiteId3 } from "@/lib/types-3";
import { JaText, Reveal, State, ago, when } from "./ui3";
import "./dash7.css";

/* The workflow's steps in order, matched to the record's step names by their words. */
const STEPS: { label: string; re: RegExp }[] = [
  { label: "Issue raised", re: /issue/i },
  { label: "Teammate chat", re: /team|teammate|engineer/i },
  { label: "Cross-site chat", re: /cross|other.?site|peer/i },
  { label: "Manager's decision", re: /manager|decision|approv/i },
  { label: "Email to you", re: /mail/i },
  { label: "Call to you", re: /owner.?call|phone|^call$|dispatch/i },
];
function stepsOf(a: OwnerAlert) {
  const used = new Set<number>();
  const rows = STEPS.map(s => {
    const k = a.steps.findIndex((x, i) => !used.has(i) && s.re.test(x.name));
    if (k >= 0) used.add(k);
    return { label: s.label, step: k >= 0 ? a.steps[k] : null };
  });
  /* The email and the call count as done once they have a result, whatever the step list says. */
  if (!rows[4].step && a.email?.mode) rows[4].step = { name: "email", at: a.email.at, summary: null, status: a.email.mode };
  if (!rows[5].step && a.call?.mode) rows[5].step = { name: "call", at: a.call.at, summary: null, status: a.call.mode };
  const extra = a.steps.filter((_, i) => !used.has(i) && !/record/i.test(a.steps[i].name)).map(x => ({ label: x.name.replace(/[_-]+/g, " ").replace(/^./, c => c.toUpperCase()), step: x }));
  return [...rows, ...extra];
}
const tone = (mode: string | undefined) => mode === "sent" ? "" : mode === "failed" ? "fail" : "held";
function deliveryWord(d: AlertEmail | AlertCall | null, sent: string): string {
  if (!d || !d.mode) return "Not yet";
  switch (d.mode) {
    case "sent": return sent;
    case "dry_run": return "Ready to send: live messaging is off";
    case "capped": return "Held: today's alert limit reached";
    case "failed": return d.reason || "Failed";
    default: return d.reason || d.mode.replace(/_/g, " ");
  }
}
const CALL_LINKS = ["Teammate chat", "Cross-site chat", "Manager's decision"];

function AlertItem({ a }: { a: OwnerAlert }) {
  const steps = stepsOf(a);
  const files = a.email?.attachments ?? [];
  return <li className="oa-item">
    <p className="r1"><span className={`sig ${a.severity === "high" ? "bad" : a.severity === "low" ? "off" : "warn"}`} aria-hidden="true" /><strong><JaText text={a.title} /></strong>{a.severity ? <span className="sev">{a.severity}</span> : null}<span className="oa-when" title={when(a.at)}>{ago(a.at)}</span></p>
    <ol className="oa-steps" aria-label="Steps">{steps.map(s => <li key={s.label} className={s.step ? "done" : ""} title={s.step?.summary ?? undefined}>
      <span className={`sig ${s.step ? "ok" : "off"}`} aria-hidden="true" />{s.label}<span className="sr-only">{s.step ? ", done" : ", waiting"}</span>
    </li>)}</ol>
    <dl className="oa-ch">
      <div><dt>Email</dt><dd className={tone(a.email?.mode)}>{deliveryWord(a.email, "Emailed you")}{a.email?.subject ? <span className="subj"><JaText text={a.email.subject} /></span> : null}</dd></div>
      {files.length ? <div><dt>Attached</dt><dd className="oa-files">{files.map((f, i) => <span key={`${f.filename}-${i}`} className="oa-file">{f.filename}</span>)}</dd></div> : null}
      <div><dt>Call</dt><dd className={tone(a.call?.mode)}>{deliveryWord(a.call, "Called you")}</dd></div>
    </dl>
    {a.call?.brief ? <details className="oa-brief"><summary>What the call says</summary><p><JaText text={a.call.brief} /></p></details> : null}
    {a.conversationIds.length ? <p className="oa-links">{a.conversationIds.map((id, i) => <Link key={id} className="lnk" href={`/app/conversations?id=${encodeURIComponent(id)}`}>{CALL_LINKS[i] ?? `Chat ${i + 1}`}</Link>)}</p> : null}
  </li>;
}

export default function OwnerAlerts({ siteId, limit = 4, i = 0 }: { siteId: SiteId3; limit?: number; i?: number }) {
  const alerts = useOwnerAlerts(siteId, limit);
  const site = site3(siteId);
  const hid = `oa-${siteId}-h`;
  return <Reveal as="section" className="p3 oa7" i={i} aria-labelledby={hid}>
    <div className="p-head"><h2 id={hid}>Owner alerts</h2></div>
    <State remote={alerts} what="owner alerts" isEmpty={a => a.length === 0} empty={`No owner alerts at ${site.short}.`}>
      {a => <ol className="oa-list">{a.slice(0, limit).map(x => <AlertItem key={x.id} a={x} />)}</ol>}
    </State>
  </Reveal>;
}
