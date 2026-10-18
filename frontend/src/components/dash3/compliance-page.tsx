"use client";

/* /app/[site]/compliance: compliance issues with what is wrong, why (the regulation, its provision and our summary),
   who is responsible and the agent that has taken it on (owner, Oct 18: the agents decide what to do, so there is no
   "fix it" button; the fix workflow's steps show as they run); obligations; the regulations with their cached official
   PDFs; documents, notices, agent document emails and notifications. */
import { useEffect, useMemo, useState } from "react";
import { api3, normaliseFix } from "@/lib/api-3";
import { useCrew, useDocumentEmails, useDocuments3, useIssue, useIssues3, useNotices, useNotifications, useObligations, useRegulationsWithComparison } from "@/lib/hooks-3";
import { agentName, teamOf } from "@/lib/sites-3";
import type { CrewMember, FixRun, Issue3, Obligation, Regulation, SiteId3, WhyRef } from "@/lib/types-3";
import { COMPARISON_NOTE, REGULATIONS_PACK, atPage, comparisonForIssue, comparisonRegsForSite, embedAttribution, hostOf, isComparison, isPdfUrl, jurisdictionName, linkedNote, regsForIssue, regsForSite, siteJurisdiction, sourceUrl, translationOf } from "@/lib/regulations-3";
import Pdf3 from "./pdf3";
import { LatestInspection } from "./inspections";
import OwnerAlerts from "./owner-alerts";
import { Btn, DemoTag, JaText, LinkedText, PageHead, Reveal, State, SynthTag, ago, day, errorText, when, words } from "./ui3";

const statusWord: Record<Obligation["status"], string> = { ok: "ok", due_soon: "due soon", overdue: "overdue", blocked: "blocked" };
const sigOf = (s: Obligation["status"]) => s === "ok" ? "ok" : s === "due_soon" ? "warn" : "bad";
const ORDER: Record<Obligation["status"], number> = { blocked: 0, overdue: 1, due_soon: 2, ok: 3 };
const COMPLIANCE_KIND = /complian|certif|inspection|permit|obligation|regulat|document|notice/i;
const whyOf = (x: { why?: WhyRef[] | WhyRef | null }): WhyRef[] => Array.isArray(x.why) ? x.why : x.why ? [x.why] : [];
const regIds = (x: { regulationIds?: string[] | null; regulationId?: string | null; why?: WhyRef[] | WhyRef | null }) =>
  [...(x.regulationIds ?? []), ...(x.regulationId ? [x.regulationId] : []), ...whyOf(x).map(w => w.regulationId ?? "")].filter((v, i, a) => v && a.indexOf(v) === i);
/* "Building Regulations 2018, reg. 195": the instrument without its citation in brackets, then the provision. */
const shortRef = (r: { instrument?: string | null; provision?: string | null }) => `${(r.instrument ?? "").replace(/\s*\(.*$/, "")}${r.provision ? `, ${r.provision.replace(/\s*\(.*$/, "")}` : ""}`;
export const isComplianceIssue = (i: Issue3, siteRegs: Regulation[] = []) => regIds(i).length > 0 || Boolean(i.obligationId) || Boolean(i.documentId) || COMPLIANCE_KIND.test(i.kind) || regsForIssue(i, siteRegs).length > 0;

export default function CompliancePage({ siteId }: { siteId: SiteId3 }) {
  const obligations = useObligations(siteId);
  const documents = useDocuments3(siteId);
  const notices = useNotices(siteId);
  const emails = useDocumentEmails(siteId);
  const notifications = useNotifications(siteId);
  const crew = useCrew(siteId);
  const issues = useIssues3(siteId);
  const regulations = useRegulationsWithComparison(siteId);
  const [pdf, setPdf] = useState<string | null>(null);
  const [cmp, setCmp] = useState<string | null>(null);
  /* The binding law first: the API's records when it answers, else the rule pack in the repository, labelled as such.
     California's records are a comparison only and are kept apart (contract addition, US-CA). */
  const served = useMemo(() => regulations.data ?? [], [regulations.data]);
  const binding = useMemo(() => regsForSite(siteId, served), [served, siteId]);
  const fromPack = binding.length === 0;
  const regs = useMemo(() => binding.length ? binding : regsForSite(siteId, REGULATIONS_PACK), [binding, siteId]);
  const servedCmp = useMemo(() => comparisonRegsForSite(siteId, served.filter(isComparison)), [served, siteId]);
  const comparisons = useMemo(() => servedCmp.length ? servedCmp : comparisonRegsForSite(siteId, REGULATIONS_PACK), [servedCmp, siteId]);
  useEffect(() => { if (!pdf && regs.length) setPdf(regs[0].id); }, [regs, pdf]);
  useEffect(() => { if (!cmp && comparisons.length) setCmp(comparisons[0].id); }, [comparisons, cmp]);
  const owner = (id: string | null | undefined) => (id && (crew.data?.find(c => c.id === id)?.name ?? agentName(id))) || "nobody yet";
  const docTitle = (id: string) => documents.data?.find(d => d.id === id)?.title ?? id;
  const counts = (obligations.data ?? []).reduce<Record<string, number>>((m, o) => { m[o.status] = (m[o.status] ?? 0) + 1; return m; }, {});
  const compIssues = (issues.data ?? []).filter(i => isComplianceIssue(i, regs)).sort((a, b) => (a.status === "resolved" ? 1 : 0) - (b.status === "resolved" ? 1 : 0) || b.at.localeCompare(a.at));
  const [allIssues, setAllIssues] = useState(false);
  const officer = teamOf(siteId).find(a => a.team === "compliance");
  const scrollTo = (el: string) => document.getElementById(el)?.scrollIntoView({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  const openPdf = (id: string) => { if (comparisons.some(r => r.id === id) && !regs.some(r => r.id === id)) { setCmp(id); scrollTo("regs-ca"); } else { setPdf(id); scrollTo("regs"); } };
  return <div className="page3">
    <PageHead id="compliance" title="Compliance" />

    <Reveal as="section" className="p3 ci3" aria-labelledby="ci-h">
      <div className="p-head"><h2 id="ci-h">Compliance issues</h2><DemoTag /></div>
      <State remote={issues} what="issues" isEmpty={() => compIssues.length === 0} empty="No compliance issues on this site.">
        {() => <>
          <ul className="ci-list">{(allIssues ? compIssues : compIssues.slice(0, 6)).map(i => <ComplianceIssue key={i.id} siteId={siteId} issue={i} regs={regsForIssue(i, regs)} comparisons={comparisonForIssue(i, comparisons)} crew={crew.data ?? []} officerName={officer?.name ?? "Compliance Officer"} onPdf={openPdf} />)}</ul>
          {compIssues.length > 6 ? <div className="row-actions"><Btn quiet small onClick={() => setAllIssues(!allIssues)}>{allIssues ? "Show the first six" : `Show all ${compIssues.length}`}</Btn></div> : null}
        </>}
      </State>
    </Reveal>

    <LatestInspection siteId={siteId} />

    <OwnerAlerts siteId={siteId} limit={6} />

    <Reveal as="section" className="p3 obl3" aria-labelledby="obl-h">
      <div className="p-head"><h2 id="obl-h">Obligations</h2>{obligations.data ? <span className="meta counts">{(["blocked", "overdue", "due_soon", "ok"] as const).map(k => <span key={k} className={k === "blocked" || k === "overdue" ? (counts[k] ? "bad" : "") : ""}><span className={`sig ${counts[k] ? sigOf(k) : "off"}`} aria-hidden="true" />{counts[k] ?? 0} {statusWord[k]}</span>)}</span> : null}</div>
      <State remote={obligations} what="obligations" isEmpty={o => o.length === 0} empty="No obligations recorded for this site.">
        {list => <div className="tbl3 obl-tbl" role="table" aria-label="Obligations">
          <div className="tr head" role="row"><span role="columnheader">Obligation</span><span role="columnheader">Rule and frequency</span><span role="columnheader">Last done</span><span role="columnheader">Due</span><span role="columnheader">Status</span></div>
          {[...list].sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.dueAt ?? "").localeCompare(b.dueAt ?? "")).map(o => { const r = regIds(o).map(id => regs.find(x => x.id === id)).filter((x): x is Regulation => Boolean(x));
            return <div className="tr" role="row" key={o.id}>
              <span role="cell" className="c-title"><strong>{o.title}</strong><SynthTag rec={o} /><small>{o.status === "blocked" && o.blockedReason ? `${o.blockedReason} ` : ""}{o.assetTag ? `${o.assetTag}, ` : ""}owner {owner(o.ownerId)}{o.documentId ? <>, <a className="lnk" href={api3.documentFileUrl(o.documentId)} target="_blank" rel="noreferrer">document</a></> : null}</small></span>
              <span role="cell">{o.frequency}<small>{r.length ? <>{r.slice(0, 2).map(x => <button key={x.id} type="button" className="lnk-btn" onClick={() => openPdf(x.id)}>{shortRef(x)}</button>)}{r.length > 2 ? `and ${r.length - 2} more` : ""}</> : `rule ${o.ruleRef}`}</small></span>
              <span role="cell">{day(o.lastDoneAt)}</span>
              <span role="cell">{day(o.dueAt)}<small>{o.dueAt ? ago(o.dueAt) : ""}</small></span>
              <span role="cell" className={`c-st ${sigOf(o.status) === "bad" ? "bad" : ""}`}><span className={`sig ${sigOf(o.status)}`} aria-hidden="true" />{statusWord[o.status]}</span>
            </div>; })}
        </div>}
      </State>
    </Reveal>

    <Reveal as="section" className="p3 regs3" id="regs" aria-labelledby="regs-h">
      <div className="p-head"><h2 id="regs-h">Regulations, {jurisdictionName(siteJurisdiction(siteId))}</h2></div>
      {fromPack && regulations.readiness === "loading" ? <p className="note3">Loading the regulations.</p> : null}
      {regs.length ? <div className="regs-wrap">
        <ul className="rows3">{regs.map(r => <li key={r.id} className={pdf === r.id ? "sel" : ""}><button type="button" className="row-btn" aria-pressed={pdf === r.id} onClick={() => setPdf(r.id)}>
          <span className="r1"><strong><JaText text={r.title} /></strong>{r.sourceType === "guidance" ? <span className="tg">guidance, not law</span> : null}{r.servePdf ? null : <span className="tg">linked</span>}</span>
          <span className="r3"><JaText text={`${r.instrument}${r.provision ? `, ${r.provision}` : ""}`} /></span>
        </button></li>)}</ul>
        {pdf ? <RegulationView reg={regs.find(r => r.id === pdf) ?? null} /> : null}
      </div> : <p className="st3 empty">No regulations recorded for this site.</p>}
    </Reveal>

    <Reveal as="section" className="p3 regs3 cmp3" id="regs-ca" aria-labelledby="regs-ca-h">
      <div className="p-head"><h2 id="regs-ca-h">If this site were in California</h2><span className="meta"><span className="tg cmp">{COMPARISON_NOTE}</span></span></div>
      {comparisons.length ? <>
        <div className="regs-wrap">
          <ul className="rows3">{comparisons.map(r => <li key={r.id} className={cmp === r.id ? "sel" : ""}><button type="button" className="row-btn" aria-pressed={cmp === r.id} onClick={() => setCmp(r.id)}>
            <span className="r1"><strong>{r.title}</strong><span className="tg cmp">{COMPARISON_NOTE}</span>{r.servePdf ? null : <span className="tg">linked</span>}</span>
            <span className="r3">{r.instrument}{r.provision ? `, ${r.provision}` : ""}</span>
          </button></li>)}</ul>
          {cmp ? <RegulationView reg={comparisons.find(r => r.id === cmp) ?? null} comparison /> : null}
        </div>
      </> : <p className="st3 empty">No California comparison records yet.</p>}
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
        <div className="p-head"><h2 id="nf-h">Notifications</h2></div>
        <State remote={notifications} what="notifications" isEmpty={x => x.length === 0} empty="No notifications yet.">
          {list => <ul className="rows3 plain">{[...list].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 12).map(x => <li key={x.id}>
            <span className="r1"><strong>{agentName(x.to)}</strong>{x.role ? <span className="sev">{x.role}</span> : null}<SynthTag rec={x} />{x.mode && x.mode !== "sent" ? <span className="tg">{words(x.mode)}</span> : null}</span>
            <span className="r2">{x.text}</span><span className="r3">{when(x.at)}{x.channel ? `, ${x.channel === "a2a" ? "message" : x.channel}` : ""}</span>
          </li>)}</ul>}
        </State>
      </Reveal>
    </div>
  </div>;
}

/* One regulation, the same licence rule for every jurisdiction. servePdf true (England under OGL v3.0, or a Japanese
   record whose site's terms allow it): the cached copy is embedded at its page with the record's attribution under it.
   servePdf false (Victoria, the VBA note, Japanese records whose terms do not allow serving a copy): never embedded;
   "Open the official source" opens it on its own site, with the licence note (a Japanese record's terms, verbatim). */
function RegulationView({ reg, comparison }: { reg: Regulation | null; comparison?: boolean }) {
  if (!reg) return null;
  const page = reg.pageHint ?? 1;
  const file = api3.regulationFileUrl(reg.id);
  const src = sourceUrl(reg);
  const pdf = isPdfUrl(src);
  const cachedPdf = !reg.pdfPath || /\.pdf$/i.test(reg.pdfPath);
  const en = translationOf(reg);
  return <article className="reg-view" aria-label={reg.title}>
    <header><span className="tg">{jurisdictionName(reg.jurisdiction)}</span>{comparison ? <span className="tg cmp">{COMPARISON_NOTE}</span> : null}{reg.sourceType === "guidance" ? <span className="tg">guidance, not law</span> : null}<h3><JaText text={reg.title} /></h3><p><JaText text={`${reg.instrument}${reg.provision ? `, ${reg.provision}` : ""}`} /></p></header>
    {reg.summary ? <p className="reg-sum">{reg.summary}</p> : null}
    <dl className="kv3">
      {reg.version ? <><dt>Version</dt><dd><JaText text={reg.version} /></dd></> : null}
      {reg.officialUrl ? <><dt>Official page</dt><dd><a className="lnk" href={reg.officialUrl} target="_blank" rel="noreferrer">{reg.officialUrl.replace(/^https?:\/\//, "")}</a></dd></> : null}
      {en ? <><dt>English translation</dt><dd><a className="lnk" href={en} target="_blank" rel="noreferrer">{en.replace(/^https?:\/\//, "")}</a></dd></> : null}
      {reg.retrievedAt ? <><dt>Retrieved</dt><dd>{day(reg.retrievedAt)}</dd></> : null}
    </dl>
    {reg.servePdf ? <>
      {cachedPdf ? <Pdf3 key={reg.id} url={file} title={reg.title} initialPage={page} />
        : <iframe key={reg.id} className="reg-frame" src={file} title={`${reg.title}, the cached copy`} sandbox="" loading="lazy" />}
      <p className="ogl"><LinkedText text={embedAttribution(reg)} /> <a className="lnk" href={cachedPdf ? atPage(file, page) : file} target="_blank" rel="noreferrer">{cachedPdf ? `Open the PDF at page ${page}` : "Open the cached copy"}</a>{src ? <> · <a className="lnk" href={pdf ? atPage(src, page) : src} target="_blank" rel="noreferrer">{hostOf(src) || "official"} copy</a></> : null}</p>
    </> : <div className="reg-linked">
      {src ? <a className="b3" href={pdf ? atPage(src, page) : src} target="_blank" rel="noreferrer"><span>{pdf ? "Open the official PDF" : "Open the official source"}</span><span className="arrow" aria-hidden="true">→</span></a> : null}
      <p className="note3"><JaText text={linkedNote(reg)} />{reg.pageHint && pdf ? `; opens at page ${page} of the PDF` : ""}.</p>
    </div>}
  </article>;
}

const COMPLIANCE_KINDS = new Set(["inspection_overdue", "certificate_expired", "walkway_closure", "permit_blocked", "alteration_permit", "visitor_route"]);
function takerOf(siteId: SiteId3, kind: string): string {
  if (kind === "agent_efficiency") return agentName("director");
  const role = kind.startsWith("compliance") || COMPLIANCE_KINDS.has(kind) ? "compliance" : "engineer";
  return teamOf(siteId).find(a => a.team === role)?.name ?? agentName(role);
}

/* One compliance issue: what, why, who has taken it on, and the fix workflow's steps as the agents run them. */
function ComplianceIssue({ siteId, issue, regs, comparisons, crew, officerName, onPdf }: { siteId: SiteId3; issue: Issue3; regs: Regulation[]; comparisons: Regulation[]; crew: CrewMember[]; officerName: string; onPdf: (id: string) => void }) {
  const [fix, setFix] = useState<FixRun | null>(null);
  const running = Boolean(fix && !["done", "completed", "resolved", "failed"].includes(fix.state));
  const live = useIssue(fix ? issue.id : null, running);
  const latest: Issue3 = live.data ?? issue;
  const steps = useMemo(() => {
    const fromIssue = latest.fix ? normaliseFix({ fix: latest.fix }, issue.id) : null;
    const base = fromIssue && fromIssue.steps.some(s => s.state !== "pending") ? fromIssue : fix;
    if (!base) return null;
    if (latest.status === "resolved") return { ...base, state: "done", steps: base.steps.map(s => ({ ...s, state: "done" })) };
    return base;
  }, [latest, fix, issue.id]);
  useEffect(() => { if (steps && fix && steps.state !== fix.state) setFix(steps); }, [steps, fix, setFix]);
  /* The issue's own "why" (regulation, provision, our summary) when the backend sends it; else the pack's matches. */
  const whys: WhyRef[] = whyOf(latest).length ? whyOf(latest) : regs.map(r => ({ regulationId: r.id, instrument: r.instrument, provision: r.provision, title: r.title, summary: r.summary, officialUrl: r.officialUrl, servePdf: r.servePdf, pageHint: r.pageHint }));
  const crewWho = crew.find(c => c.id === (latest.assigneeId ?? latest.ownerId ?? latest.assignedTo));
  const who = crewWho ? { name: crewWho.name, role: crewWho.role } : latest.responsible?.owner?.name ? { name: latest.responsible.owner.name, role: latest.responsible.owner.role ?? "" } : null;
  /* The agent that has taken the issue on (people.agent_for_kind): compliance kinds to the site's Compliance Officer, agent
     efficiency to the Operations Director, everything else to the Site Engineer. */
  const taker = takerOf(siteId, latest.kind);
  const resolved = latest.status === "resolved";
  return <li className={`ci ${resolved ? "done" : ""}`}>
    <div className="ci-what">
      <span className="r1"><span className={`sig ${resolved ? "ok" : latest.severity === "high" ? "bad" : "warn"}`} aria-hidden="true" /><strong>{latest.assetTag}</strong><span className="sev">{latest.severity}, {words(latest.kind)}{latest.status ? `, ${words(latest.status)}` : ""}</span><SynthTag rec={latest} /></span>
      <p className="ci-sum">{latest.summary}</p>
    </div>
    <dl className="kv3 ci-why">
      <dt>Why</dt><dd>{whys.length ? <>
        <span className="why-reg"><strong>{shortRef(whys[0])}.</strong> {whys[0].summary ?? whys[0].title} {whys[0].regulationId ? <button type="button" className="lnk-btn" onClick={() => onPdf(whys[0].regulationId!)}>{whys[0].servePdf ? "Read the PDF" : "Read the record"}</button> : null}{whys[0].officialUrl ? <a className="lnk" href={whys[0].officialUrl} target="_blank" rel="noreferrer">official page</a> : null}</span>
        {whys.length > 1 ? <span className="why-more">Also {whys.slice(1, 4).map((w, k) => <button key={w.regulationId ?? k} type="button" className="lnk-btn" onClick={() => w.regulationId && onPdf(w.regulationId)}>{shortRef(w)}</button>)}{whys.length > 4 ? `and ${whys.length - 4} more` : ""}</span> : null}
      </> : "The regulation reference is not on this record yet."}</dd>
      <dt>Who</dt><dd>{who ? `${who.name}${who.role ? `, ${who.role}` : ""}` : "Owner not assigned yet"}; {officerName} keeps the record</dd>
    </dl>
    <div className="ci-cmp" aria-label="If this site were in California">
      <span className="r1"><strong>If this site were in California</strong><span className="tg cmp">{COMPARISON_NOTE}</span></span>
      {comparisons.length ? <span className="r3">{comparisons.slice(0, 3).map(r => <button key={r.id} type="button" className="lnk-btn" onClick={() => onPdf(r.id)}>{shortRef(r)}</button>)}{comparisons.length > 3 ? `and ${comparisons.length - 3} more` : ""}</span>
        : <span className="r3">No California comparison on record for this issue.</span>}
    </div>
    <div className="ci-fix">
      <p className="ci-taker"><span className={`sig ${resolved ? "ok" : running ? "warn" : "off"}`} aria-hidden="true" /><strong>{taker}</strong>{resolved ? " closed it." : running ? " is on it now." : " has taken it on and decides the next step."}</p>
      {steps ? <ol className="fix-steps" aria-label="Fix workflow">{steps.steps.map(s => <li key={s.key} className={s.state}>
        <span className={`sig ${s.state === "done" ? "ok" : s.state === "running" ? "warn" : s.state === "failed" ? "bad" : "off"}`} aria-hidden="true" />
        <strong>{s.title}</strong><span className="r3">{s.summary ?? (s.state === "running" ? "in progress" : s.state === "done" ? "done" : "waiting")}{s.at ? `, ${ago(s.at)}` : ""}</span>
      </li>)}</ol> : null}
    </div>
  </li>;
}

