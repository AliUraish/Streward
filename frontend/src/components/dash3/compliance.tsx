"use client";

/* /app/[site]/compliance: compliance issues with what is wrong, why (the regulation, its provision and our summary),
   who is responsible and the "Ask the agents to fix it" demo control followed through its six steps; obligations;
   the regulations with their cached official PDFs; documents, notices, agent document emails and notifications.
   A demo rule pack, not legal advice. */
import { useEffect, useMemo, useState } from "react";
import { api3, normaliseFix } from "@/lib/api-3";
import { useCrew, useDocumentEmails, useDocuments3, useIssue, useIssues3, useNotices, useNotifications, useObligations, useRegulations } from "@/lib/hooks-3";
import { agentName, site3, teamOf } from "@/lib/sites-3";
import type { CrewMember, FixRun, Issue3, Obligation, Regulation, SiteId3 } from "@/lib/types-3";
import Pdf3 from "./pdf3";
import { Btn, DemoTag, PageHead, Reveal, State, SynthTag, ago, day, errorText, when, words } from "./ui3";

const statusWord: Record<Obligation["status"], string> = { ok: "ok", due_soon: "due soon", overdue: "overdue", blocked: "blocked" };
const sigOf = (s: Obligation["status"]) => s === "ok" ? "ok" : s === "due_soon" ? "warn" : "bad";
const ORDER: Record<Obligation["status"], number> = { blocked: 0, overdue: 1, due_soon: 2, ok: 3 };
const COMPLIANCE_KIND = /complian|certif|inspection|permit|obligation|overdue|document|regulat|expired/i;
const regIds = (x: { regulationIds?: string[] | null; regulationId?: string | null; why?: { regulationId?: string | null } | null }) =>
  [...(x.regulationIds ?? []), ...(x.regulationId ? [x.regulationId] : []), ...(x.why?.regulationId ? [x.why.regulationId] : [])].filter((v, i, a) => a.indexOf(v) === i);
export const isComplianceIssue = (i: Issue3) => regIds(i).length > 0 || Boolean(i.obligationId) || COMPLIANCE_KIND.test(i.kind);

export default function CompliancePage({ siteId }: { siteId: SiteId3 }) {
  const site = site3(siteId);
  const obligations = useObligations(siteId);
  const documents = useDocuments3(siteId);
  const notices = useNotices(siteId);
  const emails = useDocumentEmails(siteId);
  const notifications = useNotifications(siteId);
  const crew = useCrew(siteId);
  const issues = useIssues3(siteId);
  const regulations = useRegulations(siteId);
  const [pdf, setPdf] = useState<string | null>(null);
  const regs = useMemo(() => regulations.data ?? [], [regulations.data]);
  useEffect(() => { if (!pdf && regs.length) setPdf(regs[0].id); }, [regs, pdf]);
  const owner = (id: string | null | undefined) => (id && (crew.data?.find(c => c.id === id)?.name ?? agentName(id))) || "nobody yet";
  const docTitle = (id: string) => documents.data?.find(d => d.id === id)?.title ?? id;
  const counts = (obligations.data ?? []).reduce<Record<string, number>>((m, o) => { m[o.status] = (m[o.status] ?? 0) + 1; return m; }, {});
  const compIssues = (issues.data ?? []).filter(isComplianceIssue);
  const officer = teamOf(siteId).find(a => a.team === "compliance");
  const openPdf = (id: string) => { setPdf(id); document.getElementById("regs")?.scrollIntoView({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }); };
  return <div className="page3">
    <PageHead id="compliance" title="Compliance" sub={`${site.name}: what the ${site.short} team must keep doing, the regulations behind it and what is broken now. Kept by the ${officer?.name ?? "Compliance Officer"}. A demo rule pack explained in our own words, not legal advice.`} />

    <Reveal as="section" className="p3 ci3" aria-labelledby="ci-h">
      <div className="p-head"><h2 id="ci-h">Compliance issues</h2><DemoTag /></div>
      <State remote={issues} what="issues" isEmpty={() => compIssues.length === 0} empty="No compliance issues on this site. Start a scenario on the portfolio page to raise one.">
        {() => <ul className="ci-list">{compIssues.map(i => <ComplianceIssue key={i.id} issue={i} regs={regs} crew={crew.data ?? []} officerName={officer?.name ?? "Compliance Officer"} onPdf={openPdf} />)}</ul>}
      </State>
    </Reveal>

    <Reveal as="section" className="p3 obl3" aria-labelledby="obl-h">
      <div className="p-head"><h2 id="obl-h">Obligations</h2>{obligations.data ? <span className="meta counts">{(["blocked", "overdue", "due_soon", "ok"] as const).map(k => <span key={k} className={k === "blocked" || k === "overdue" ? (counts[k] ? "bad" : "") : ""}><span className={`sig ${counts[k] ? sigOf(k) : "off"}`} aria-hidden="true" />{counts[k] ?? 0} {statusWord[k]}</span>)}</span> : null}</div>
      <State remote={obligations} what="obligations" isEmpty={o => o.length === 0} empty="No obligations recorded for this site.">
        {list => <div className="tbl3 obl-tbl" role="table" aria-label="Obligations">
          <div className="tr head" role="row"><span role="columnheader">Obligation</span><span role="columnheader">Rule and frequency</span><span role="columnheader">Last done</span><span role="columnheader">Due</span><span role="columnheader">Status</span></div>
          {[...list].sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.dueAt ?? "").localeCompare(b.dueAt ?? "")).map(o => { const r = regIds(o).map(id => regs.find(x => x.id === id)).filter((x): x is Regulation => Boolean(x));
            return <div className="tr" role="row" key={o.id}>
              <span role="cell" className="c-title"><strong>{o.title}</strong><SynthTag rec={o} /><small>{o.status === "blocked" && o.blockedReason ? `${o.blockedReason} ` : ""}{o.assetTag ? `${o.assetTag}, ` : ""}owner {owner(o.ownerId)}{o.documentId ? <>, <a className="lnk" href={api3.documentFileUrl(o.documentId)} target="_blank" rel="noreferrer">document</a></> : null}</small></span>
              <span role="cell">{o.frequency}<small>{r.length ? r.map(x => <button key={x.id} type="button" className="lnk-btn" onClick={() => openPdf(x.id)}>{x.instrument}{x.provision ? `, ${x.provision}` : ""}</button>) : `demo rule ${o.ruleRef}`}</small></span>
              <span role="cell">{day(o.lastDoneAt)}</span>
              <span role="cell">{day(o.dueAt)}<small>{o.dueAt ? ago(o.dueAt) : ""}</small></span>
              <span role="cell" className={`c-st ${sigOf(o.status) === "bad" ? "bad" : ""}`}><span className={`sig ${sigOf(o.status)}`} aria-hidden="true" />{statusWord[o.status]}</span>
            </div>; })}
        </div>}
      </State>
    </Reveal>

    <Reveal as="section" className="p3 regs3" id="regs" aria-labelledby="regs-h">
      <div className="p-head"><h2 id="regs-h">Regulations</h2><span className="meta">official sources, cached with attribution</span></div>
      <State remote={regulations} what="the regulations" isEmpty={r => r.length === 0} empty="No regulations recorded for this site.">
        {() => <div className="regs-wrap">
          <ul className="rows3">{regs.map(r => <li key={r.id} className={pdf === r.id ? "sel" : ""}><button type="button" className="row-btn" aria-pressed={pdf === r.id} onClick={() => setPdf(r.id)}>
            <span className="r1"><strong>{r.instrument}</strong>{r.provision ? <span className="sev">{r.provision}</span> : null}<span className="tg">{r.jurisdiction === "ENG-UK" ? "England" : r.jurisdiction === "VIC-AU" ? "Victoria" : r.jurisdiction}</span></span>
            <span className="r2">{r.summary ?? r.title}</span>
          </button></li>)}</ul>
          {pdf ? <RegulationView reg={regs.find(r => r.id === pdf) ?? null} /> : null}
        </div>}
      </State>
    </Reveal>

    <div className="comp3">
      <Reveal as="section" className="p3 docs3" i={1} aria-labelledby="docs-h">
        <div className="p-head"><h2 id="docs-h">Documents</h2><span className="meta">{documents.data ? documents.data.length : ""}</span></div>
        <State remote={documents} what="documents" isEmpty={d => d.length === 0} empty="No documents for this site.">
          {list => <ul className="rows3 plain">{list.map(d => <li key={d.id} className={d.flagged ? "flagged" : ""}>
            <span className="r1"><strong>{d.title}</strong><SynthTag rec={d} />{d.flagged ? <span className="tg bad">flagged</span> : null}</span>
            <span className="r2">{[d.reference ?? "", d.kind ? words(d.kind) : "", d.issuedAt ? `issued ${day(d.issuedAt)}` : "", d.expiresAt ? `${new Date(d.expiresAt).getTime() < Date.now() ? "expired" : "expires"} ${day(d.expiresAt)}` : ""].filter(Boolean).join(", ")}</span>
            {d.flagged ? <span className="r2 bad">{d.flagReason ?? "Contains instructions; treated as data, not followed."}</span> : null}
            <a className="lnk r3" href={d.fileUrl ?? api3.documentFileUrl(d.id)} target="_blank" rel="noreferrer">Open the PDF</a>
          </li>)}</ul>}
        </State>
      </Reveal>
      <Reveal as="section" className="p3 notices3" i={2} aria-labelledby="not-h">
        <div className="p-head"><h2 id="not-h">Notices</h2><span className="meta">{notices.data ? `${notices.data.filter(x => x.acknowledgedAt).length} of ${notices.data.length} acknowledged` : ""}</span></div>
        <State remote={notices} what="notices" isEmpty={x => x.length === 0} empty="No notices sent yet.">
          {list => <ul className="rows3 plain">{[...list].sort((a, b) => b.sentAt.localeCompare(a.sentAt)).map(x => <li key={x.id}>
            <span className="r1"><span className={`sig ${x.acknowledgedAt ? "ok" : "warn"}`} aria-hidden="true" /><strong>{x.subject ?? "Notice"}</strong><SynthTag rec={x} />{x.mode && x.mode !== "sent" ? <span className="tg">{words(x.mode)}</span> : x.dryRun ? <span className="tg">dry run</span> : null}</span>
            <span className="r2">To {x.to}{x.channel ? ` by ${x.channel}` : ""}, sent {when(x.sentAt)}; {x.acknowledgedAt ? `acknowledged ${when(x.acknowledgedAt)}` : "not acknowledged yet"}</span>
            {x.text ? <span className="r3">{x.text}</span> : null}
            {x.reason ? <span className="r3">{x.reason}</span> : null}
          </li>)}</ul>}
        </State>
      </Reveal>
      <Reveal as="section" className="p3 mails3" i={3} aria-labelledby="mail-h">
        <div className="p-head"><h2 id="mail-h">Documents between agents</h2></div>
        <State remote={emails} what="agent document emails" isEmpty={x => x.length === 0} empty="No agent has emailed a document yet.">
          {list => <ul className="rows3 plain">{[...list].sort((a, b) => b.at.localeCompare(a.at)).map(m => <li key={m.id}>
            <span className="r1"><strong>{agentName(m.from)}</strong><span className="sev">to</span><strong>{agentName(m.to)}</strong><SynthTag rec={m} />{m.status && m.status !== "sent" ? <span className="tg">{words(m.status)}</span> : null}</span>
            <span className="r2">{m.documentTitle ?? docTitle(m.documentId)}{m.note ? `: ${m.note}` : ""}</span>
            <span className="r3">{when(m.at)}{m.reason ? `; ${m.reason}` : ""}</span>
          </li>)}</ul>}
        </State>
      </Reveal>
      <Reveal as="section" className="p3 notif3" i={4} aria-labelledby="nf-h">
        <div className="p-head"><h2 id="nf-h">Notifications</h2><span className="meta">records only for synthetic crew</span></div>
        <State remote={notifications} what="notifications" isEmpty={x => x.length === 0} empty="No notifications yet. The last step of a fix informs everyone on the roster.">
          {list => <ul className="rows3 plain">{[...list].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 12).map(x => <li key={x.id}>
            <span className="r1"><strong>{agentName(x.to)}</strong>{x.role ? <span className="sev">{x.role}</span> : null}<SynthTag rec={x} />{x.mode && x.mode !== "sent" ? <span className="tg">{words(x.mode)}</span> : null}</span>
            <span className="r2">{x.text}</span><span className="r3">{when(x.at)}{x.channel ? `, ${x.channel}` : ""}</span>
          </li>)}</ul>}
        </State>
      </Reveal>
    </div>
  </div>;
}

function RegulationView({ reg }: { reg: Regulation | null }) {
  if (!reg) return null;
  return <article className="reg-view" aria-label={reg.title}>
    <header><h3>{reg.title}</h3><p>{reg.instrument}{reg.provision ? `, ${reg.provision}` : ""}</p></header>
    {reg.summary ? <p className="reg-sum">{reg.summary}</p> : null}
    <dl className="kv3">
      {reg.officialUrl ? <><dt>Official source</dt><dd><a className="lnk" href={reg.officialUrl} target="_blank" rel="noreferrer">{reg.officialUrl.replace(/^https?:\/\//, "")}</a></dd></> : null}
      {reg.licence ? <><dt>Licence</dt><dd>{reg.licence}</dd></> : null}
      {reg.retrievedAt ? <><dt>Retrieved</dt><dd>{day(reg.retrievedAt)}</dd></> : null}
      {reg.appliesTo ? <><dt>Applies to</dt><dd>{Array.isArray(reg.appliesTo) ? reg.appliesTo.join(", ") : reg.appliesTo}</dd></> : null}
    </dl>
    <Pdf3 key={reg.id} url={api3.regulationFileUrl(reg.id)} title={reg.title} />
  </article>;
}

/* One compliance issue: what, why, who, and the fix workflow's six steps, live. */
function ComplianceIssue({ issue, regs, crew, officerName, onPdf }: { issue: Issue3; regs: Regulation[]; crew: CrewMember[]; officerName: string; onPdf: (id: string) => void }) {
  const [fix, setFix] = useState<FixRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = Boolean(fix && !["done", "completed", "resolved", "failed"].includes(fix.state));
  const live = useIssue(fix ? issue.id : null, running);
  const latest: Issue3 = live.data ?? issue;
  const steps = useMemo(() => {
    const fromIssue = latest.fix ? normaliseFix(latest.fix, issue.id) : null;
    const base = fromIssue && fromIssue.steps.some(s => s.state !== "pending") ? fromIssue : fix;
    if (!base) return null;
    if (latest.status === "resolved") return { ...base, state: "done", steps: base.steps.map(s => ({ ...s, state: "done" })) };
    return base;
  }, [latest, fix, issue.id]);
  useEffect(() => { if (steps && fix && steps.state !== fix.state) setFix(steps); }, [steps, fix, setFix]);
  const rs = regIds(latest).map(id => regs.find(r => r.id === id)).filter((x): x is Regulation => Boolean(x));
  const who = crew.find(c => c.id === (latest.assigneeId ?? latest.ownerId ?? latest.assignedTo));
  async function start() {
    setBusy(true); setError("");
    try { setFix(await api3.fixIssue(issue.id)); live.reload(); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  const resolved = latest.status === "resolved";
  return <li className={`ci ${resolved ? "done" : ""}`}>
    <div className="ci-what">
      <span className="r1"><span className={`sig ${resolved ? "ok" : latest.severity === "high" ? "bad" : "warn"}`} aria-hidden="true" /><strong>{latest.assetTag}</strong><span className="sev">{latest.severity}, {words(latest.kind)}{latest.status ? `, ${words(latest.status)}` : ""}</span><SynthTag rec={latest} /></span>
      <p className="ci-sum">{latest.summary}</p>
    </div>
    <dl className="kv3 ci-why">
      <dt>Why</dt><dd>{rs.length ? rs.map(r => <span key={r.id} className="why-reg"><strong>{r.instrument}{r.provision ? `, ${r.provision}` : ""}.</strong> {latest.why?.summary ?? r.summary ?? r.title} <button type="button" className="lnk-btn" onClick={() => onPdf(r.id)}>Read the PDF</button>{r.officialUrl ? <> · <a className="lnk" href={r.officialUrl} target="_blank" rel="noreferrer">official source</a></> : null}</span>) : latest.why?.summary ?? "The regulation reference is not on this record yet."}</dd>
      <dt>Who</dt><dd>{who ? `${who.name}, ${who.role}` : "Owner not assigned yet"}; {officerName} keeps the record</dd>
    </dl>
    <div className="ci-fix">
      <Btn small arrow disabled={busy || running || resolved} onClick={start}>{resolved ? "Fixed" : running ? "The agents are on it" : busy ? "Starting" : "Ask the agents to fix it"}</Btn>
      {error ? <p className="err3" role="alert">{error}</p> : null}
      {steps ? <ol className="fix-steps" aria-label="Fix workflow">{steps.steps.map(s => <li key={s.key} className={s.state}>
        <span className={`sig ${s.state === "done" ? "ok" : s.state === "running" ? "warn" : s.state === "failed" ? "bad" : "off"}`} aria-hidden="true" />
        <strong>{s.title}</strong><span className="r3">{s.summary ?? (s.state === "running" ? "in progress" : s.state === "done" ? "done" : "waiting")}{s.at ? `, ${ago(s.at)}` : ""}</span>
      </li>)}</ol> : null}
    </div>
  </li>;
}
