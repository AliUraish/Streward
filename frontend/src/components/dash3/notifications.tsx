"use client";

/* /app/notifications: what last happened, newest first. What Steward sent the owner (the emails carrying the compliance
   snapshot PDF, the calls, the texts, each with what became of it) and the events at the sites, polled every 10 s so
   new ones arrive while the page is open; filtered by site and kind. Each item links to its issue, conversation,
   maintenance window or walkthrough, and to its attachments (PDFs open in a new tab). The header downloads the
   compliance snapshot and prepares a digest now, shown here as the item it becomes. The outbox (outbox.tsx) shows what
   is waiting to reach you and when it goes out, what was sent, and what the daily limit held. The page's own Human ·
   Agent switch (remembered on this device, or ?mode=agent) shows the feed as an agent reads it: the Markdown of
   ?format=md, the same items as JSON lines, the outbox as text, and the MCP tools that return them. */
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import {
  NOTIFICATION_TOOLS, api8, cleanMarkdown, feedPath, isPdf, jsonLine, kindWord, snapshotPath,
  type NotificationAttachment, type NotificationFilters, type OwnerNotification,
} from "@/lib/api-8";
import { feedKey, markNotificationsSeen, readNotificationsSeen, useIssueTargets, useOwnerNotifications, useOwnerNotificationsMarkdown, type IssueAt } from "@/lib/hooks-8";
import { clock, outboxText, outboxPath, type OutboxItem, type OutboxStatus } from "@/lib/api-10";
import { useOutbox, useOutboxStatus } from "@/lib/hooks-10";
import { readinessOf, type Remote } from "@/lib/reality";
import { SITES3, isSite3, site3 } from "@/lib/sites-3";
import { OutboxSection } from "./outbox";
import { Btn, LinkedText, Reveal, State, ago, when } from "./ui3";
import s from "./notifications.module.css";

type View = "human" | "agent";
type Feed = Remote<{ key: string; items: OwnerNotification[] }>;
const VIEW_KEY = "steward.notifications.view";
const PAGE = 50;
const MAX = 200;
const enc = encodeURIComponent;
const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
const time = (iso: string | null | undefined) => { const t = iso ? Date.parse(iso) : NaN; return Number.isNaN(t) ? 0 : t; };
const count = (n: number) => `${n} notification${n === 1 ? "" : "s"}`;


/* What became of it: "Emailed you", "Ready to send: live messaging is off", "Held: today's limit reached",
   "Failed: <reason>". A plain event has no chip. */
const VIA: Record<string, string> = { email: "Email", call: "Call", sms: "Text" };
const SENT: Record<string, string> = { email: "Emailed you", call: "Called you", sms: "Texted you" };
type Tone = "sent" | "held" | "fail";
function delivery(n: OwnerNotification): { via: string | null; text: string; tone: Tone } | null {
  if (n.mode === "event" || (n.channel === "dashboard" && n.mode === "sent")) return null;
  const via = VIA[n.channel] ?? null;
  if (n.mode === "sent") return { via: null, text: SENT[n.channel] ?? "Sent to you", tone: "sent" };
  if (n.mode === "queued") return { via, text: n.goesOutAt ? `Waiting: goes out at ${clock(n.goesOutAt)}` : "Waiting to go out", tone: "held" };
  if (n.mode === "dry_run") return { via, text: "Ready to send: live messaging is off", tone: "held" };
  if (n.mode === "capped") return { via, text: "Held: today's limit reached", tone: "held" };
  if (n.mode === "failed") return { via, text: n.reason ? `Failed: ${n.reason}` : "Failed", tone: "fail" };
  return { via, text: cap(n.mode.replace(/_/g, " ")), tone: "held" };
}

/* The pages that already show each linked record: the issue on its asset (the environment page), the conversation,
   the site's maintenance schedule, the walkthrough line on the environment page, the owner alerts on compliance. */
interface ItemLink { href: string; label: string }
function linksOf(n: OwnerNotification, issue: IssueAt | null | undefined): ItemLink[] {
  const site = n.siteId && isSite3(n.siteId) ? n.siteId : null;
  const out: ItemLink[] = [];
  if (n.links.issueId) {
    const at = issue?.siteId && isSite3(issue.siteId) ? issue.siteId : site;
    const tag = issue?.assetTag ?? n.assetTag;
    if (at) out.push({ href: `/app/${at}/environment${tag ? `?asset=${enc(tag)}` : ""}`, label: tag ? `Open the issue on ${tag}` : "Open the issue" });
  }
  if (n.links.conversationId) out.push({ href: `/app/conversations?id=${enc(n.links.conversationId)}`, label: "Read the conversation" });
  if (n.links.windowId && site) out.push({ href: `/app/${site}/maintenance`, label: "Open the maintenance window" });
  if (n.links.patrolId && site) out.push({ href: `/app/${site}/environment`, label: "Open the walkthrough" });
  if (n.links.alertId && site) out.push({ href: `/app/${site}/compliance#oa-${site}-h`, label: "Open the alert" });
  if (n.links.phoneCallId) out.push({ href: `/app/conversations?call=${enc(n.links.phoneCallId)}`, label: "Read the call" });
  if (n.links.outboxId) out.push({ href: `/app/notifications#ob-${enc(n.links.outboxId)}`, label: "See it in the outbox" });
  if (n.links.inspectionId && site) out.push({ href: `/app/${site}/compliance#insp-${site}-h`, label: "Open the inspection" });
  if (n.links.caseId && site) out.push({ href: `/app/${site}/employees`, label: "Open the employee log" });
  return out;
}

function sizeText(bytes: number | null): string {
  if (!bytes || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}
function Attachment({ a }: { a: NotificationAttachment }) {
  const pdf = isPdf(a);
  const ext = pdf ? "PDF" : (/\.([a-z0-9]{1,4})$/i.exec(a.filename)?.[1] ?? "").toUpperCase();
  const size = sizeText(a.size);
  const body = <>{ext ? <span className={s.ftype}>{ext}</span> : null}<span className={s.fname}>{a.filename}</span>{size ? <span className={s.fsize}>{size}</span> : null}</>;
  if (!a.url) return <span className={`${s.file} ${s.nolink}`}>{body}</span>;
  return pdf
    ? <a className={s.file} href={a.url} target="_blank" rel="noreferrer">{body}<span className="sr-only"> (opens in a new tab)</span></a>
    : <a className={s.file} href={a.url} download={a.filename}>{body}</a>;
}

function Item({ n, isNew, fresh, issue }: { n: OwnerNotification; isNew: boolean; fresh: boolean; issue: IssueAt | null | undefined }) {
  const d = delivery(n);
  const where = n.siteId ? (isSite3(n.siteId) ? site3(n.siteId).short : n.siteId) : "All sites";
  const links = linksOf(n, issue);
  const t = n.at && Date.now() - time(n.at) < 10_000 ? "just now" : ago(n.at);
  return <li className={fresh ? s.fresh : undefined}>
    <span className="r1">{isNew ? <><span className="sig ok" aria-hidden="true" /><span className="sr-only">New: </span></> : null}<span className="tg">{kindWord(n.kind)}</span><strong className={s.title}>{n.title}</strong></span>
    {n.summary ? <p className={`r2 ${s.text}`}><LinkedText text={n.summary} /></p> : null}
    <span className={s.metaLine}>
      {d ? <span className={s.delivery}>{d.via ? <span className={s.via}>{d.via}</span> : null}<span className={`${s.chip} ${s[d.tone]}`}>{d.text}</span></span> : null}
      <span className="r3">{where}{t ? <>, <time dateTime={n.at} title={when(n.at)}>{t}</time></> : null}</span>
    </span>
    {n.attachments.length ? <ul className={s.files} aria-label="Attachments">{n.attachments.map((a, i) => <li key={`${a.filename}-${i}`}><Attachment a={a} /></li>)}</ul> : null}
    {links.length ? <span className={`r3 ${s.links}`}>{links.map(l => <Link key={`${l.label}-${l.href}`} className="lnk" href={l.href}>{l.label}</Link>)}</span> : null}
  </li>;
}


function copyText(text: string): Promise<boolean> {
  const fallback = () => {
    try {
      const ta = document.createElement("textarea"); ta.value = text; ta.setAttribute("readonly", "");
      ta.style.position = "fixed"; ta.style.top = "0"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); const ok = document.execCommand("copy"); ta.remove(); return ok;
    } catch { return false; }
  };
  try { if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text).then(() => true, fallback); } catch { /* no clipboard */ }
  return Promise.resolve(fallback());
}
function CopyBtn({ text, what }: { text: string; what: string }) {
  const [done, setDone] = useState<"" | "ok" | "fail">("");
  useEffect(() => { if (!done) return; const t = window.setTimeout(() => setDone(""), 1800); return () => window.clearTimeout(t); }, [done]);
  return <>
    <Btn quiet small disabled={!text} onClick={() => { void copyText(text).then(ok => setDone(ok ? "ok" : "fail")); }}>{done === "ok" ? "Copied" : done === "fail" ? "Copy failed" : "Copy"}<span className="sr-only"> {what}</span></Btn>
    <span className="sr-only" role="status">{done === "ok" ? `Copied ${what}` : done === "fail" ? `Could not copy ${what}; select the text instead` : ""}</span>
  </>;
}

/* What an agent reads: the tools, the feed's URL, the Markdown, the same items as JSON lines. */
function AgentPane({ filters, feed, items, current, outbox, outboxStatus }: { filters: NotificationFilters; feed: Feed; items: OwnerNotification[]; current: boolean; outbox: Remote<OutboxItem[]>; outboxStatus: Remote<OutboxStatus> }) {
  const md = useOwnerNotificationsMarkdown(filters);
  const mdCurrent = md.data?.key === feedKey(filters);
  const origin = window.location.origin;
  const mdPath = feedPath(filters, "md");
  const pdfPath = snapshotPath(filters.siteId);
  const text = useMemo(() => (md.data ? cleanMarkdown(md.data.text) : ""), [md.data]);
  const lines = useMemo(() => items.map(jsonLine), [items]);
  const nLines = text ? text.split("\n").length : 0;
  const obText = useMemo(() => outboxText((outbox.data ?? []).filter(x => !filters.siteId || !x.siteId || x.siteId === filters.siteId), outboxStatus.data ?? null), [outbox.data, outboxStatus.data, filters.siteId]);
  const obPath = outboxPath({ siteId: filters.siteId, limit: 60 });
  return <>
    <Reveal as="section" className="p3" i={2} aria-label="MCP tools and URLs">
      <dl className={s.kv}>
        <div><dt>MCP tools</dt><dd>{NOTIFICATION_TOOLS.map(t => <code key={t} className={s.tool}>{t}</code>)}</dd></div>
        <div><dt>Markdown feed</dt><dd><a className={`lnk ${s.url}`} href={mdPath} target="_blank" rel="noreferrer">{origin}{mdPath}</a><CopyBtn text={`${origin}${mdPath}`} what="the feed URL" /></dd></div>
        <div><dt>Snapshot PDF</dt><dd><a className={`lnk ${s.url}`} href={pdfPath} target="_blank" rel="noreferrer">{origin}{pdfPath}</a></dd></div>
        <div><dt>Outbox</dt><dd><a className={`lnk ${s.url}`} href={obPath} target="_blank" rel="noreferrer">{origin}{obPath}</a><a className={`lnk ${s.url}`} href="/api/outbox/status" target="_blank" rel="noreferrer">{origin}/api/outbox/status</a></dd></div>
      </dl>
    </Reveal>
    <div className={s.blocks}>
      <Reveal as="section" className={`p3 ${s.block}`} i={3} aria-labelledby="nt-md-h">
        <div className="p-head"><h2 id="nt-md-h">Markdown</h2><span className={s.headTools}><span className="meta">{!md.data ? "" : !mdCurrent ? "Loading" : `${nLines} line${nLines === 1 ? "" : "s"}`}</span><CopyBtn text={text} what="the Markdown" /></span></div>
        <State remote={md} what="the Markdown feed" isEmpty={() => !text.trim()} empty="Empty.">
          {() => <pre className={s.pre} tabIndex={0} aria-label="Notifications as Markdown">{text}</pre>}
        </State>
      </Reveal>
      <Reveal as="section" className={`p3 ${s.block}`} i={4} aria-labelledby="nt-ob-h">
        <div className="p-head"><h2 id="nt-ob-h">Outbox</h2><span className={s.headTools}><span className="meta">{outbox.data ? `${outbox.data.length} item${outbox.data.length === 1 ? "" : "s"}` : ""}</span><CopyBtn text={obText} what="the outbox" /></span></div>
        <State remote={outbox} what="the outbox">
          {() => <pre className={s.pre} tabIndex={0} aria-label="The outbox as text">{obText}</pre>}
        </State>
      </Reveal>
      <Reveal as="section" className={`p3 ${s.block}`} i={4} aria-labelledby="nt-jl-h">
        <div className="p-head"><h2 id="nt-jl-h">JSON lines</h2><span className={s.headTools}><span className="meta">{!feed.data ? "" : !current ? "Loading" : `${lines.length} item${lines.length === 1 ? "" : "s"}`}</span><CopyBtn text={lines.join("\n")} what="the JSON lines" /></span></div>
        <State remote={feed} what="notifications" isEmpty={() => lines.length === 0} empty="Empty.">
          {() => <pre className={s.pre} tabIndex={0} aria-label="Notifications as JSON lines">{lines.map((l, i) => <span key={i} className={s.jl}>{l}</span>)}</pre>}
        </State>
      </Reveal>
    </div>
  </>;
}

export default function NotificationsPage() {
  /* The one Human · Agent switch in the top bar (mode-11.ts) decides the view. */
  const [view] = useMode();
  const [site, setSite] = useState("");
  const [kind, setKind] = useState("");
  const [limit, setLimit] = useState(PAGE);
  /* The last visit before this one: anything newer is new. */
  const [since, setSince] = useState<string | null>(null);
  /* ?site= and ?kind= open the page filtered; ?mode=agent opens it in agent mode. */
  useEffect(() => {
    setSince(readNotificationsSeen());
    const p = new URLSearchParams(window.location.search);
    const s0 = p.get("site") ?? p.get("siteId"); const k0 = p.get("kind");
    if (isSite3(s0)) setSite(s0);
    if (k0) setKind(k0);
  }, []);
  const agent = view === "agent";

  const filters = useMemo<NotificationFilters>(() => ({ limit, siteId: site || undefined, kind: kind || undefined }), [limit, site, kind]);
  const key = feedKey(filters);
  const feed = useOwnerNotifications(filters);
  const outbox = useOutbox({ limit: 60, siteId: site || undefined });
  const outboxStatus = useOutboxStatus();
  const data = feed.data;
  const current = data?.key === key;
  /* Narrowed here too, so a new site or kind shows at once while its own answer loads. */
  const items = useMemo(() => (data?.items ?? []).filter(n => current || ((!site || !n.siteId || n.siteId === site) && (!kind || n.kind === kind))), [data, current, site, kind]);
  const issues = useIssueTargets(useMemo(() => items.flatMap(n => (n.links.issueId && !n.assetTag ? [n.links.issueId] : [])), [items]));

  /* The kinds seen so far, for the filter; the server filters by the one chosen. */
  const [kinds, setKinds] = useState<string[]>([]);
  useEffect(() => {
    if (!data) return;
    setKinds(prev => { const all = new Set([...prev, ...data.items.map(n => n.kind)]); return all.size === prev.length ? prev : [...all]; });
  }, [data]);
  const kindOptions = useMemo(() => [...new Set([...kinds, ...(kind ? [kind] : [])])].sort((a, b) => kindWord(a).localeCompare(kindWord(b))), [kinds, kind]);

  /* Seeing the feed is the visit: the sidebar's count starts again from the newest item shown. */
  useEffect(() => {
    if (!data?.items.length) return;
    markNotificationsSeen(data.items.reduce((m, n) => (time(n.at) > time(m) ? n.at : m), data.items[0].at));
  }, [data]);

  const emptyText = kind ? `No ${kindWord(kind).toLowerCase()} notifications${site ? ` at ${site3(site).short}` : ""} yet.` : site ? `Nothing at ${site3(site).short} yet.` : "Nothing has happened yet.";
  /* Items that arrive while the page is open rise once and are announced; a new filter starts afresh with one count. */
  const known = useRef<{ key: string; ids: Set<string> } | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set());
  /* Everything that arrived during this visit stays marked new until the next one. */
  const [arrived, setArrived] = useState<ReadonlySet<string>>(() => new Set());
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (!data || data.key !== key) return;
    if (known.current?.key !== data.key) {
      known.current = { key: data.key, ids: new Set(data.items.map(n => n.id)) };
      setSaid(data.items.length ? count(data.items.length) : emptyText);
      return;
    }
    const ids = known.current.ids;
    const added = data.items.filter(n => !ids.has(n.id));
    if (!added.length) return;
    added.forEach(n => ids.add(n.id));
    setFresh(new Set(added.map(n => n.id)));
    setArrived(prev => new Set([...prev, ...added.map(n => n.id)]));
    setSaid(added.length === 1 ? `New: ${added[0].title}` : `${added.length} new notifications`);
  }, [data, key, emptyText]);
  useEffect(() => { if (!fresh.size) return; const t = window.setTimeout(() => setFresh(new Set()), 2400); return () => window.clearTimeout(t); }, [fresh]);

  /* "Send me a snapshot now": the digest comes back as an item and stays at the top until the feed carries it. */
  const [sent, setSent] = useState<OwnerNotification | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<{ text: string; fail: boolean } | null>(null);
  async function sendNow() {
    if (sending) return;
    setSending(true); setSendError(null);
    try {
      const n = await api8.digest(site || undefined);
      known.current?.ids.add(n.id);
      setSent(n); setFresh(new Set([n.id])); setArrived(prev => new Set([...prev, n.id]));
      const d = delivery(n);
      setSaid(`Snapshot prepared${d ? `: ${d.text}` : ""}`);
      feed.reload();
    } catch (e) {
      const r = readinessOf(e);
      setSendError(r.readiness === "not_ready" ? { text: "Sending a snapshot is not available yet.", fail: false } : { text: `Could not prepare the snapshot: ${r.message}`, fail: true });
      if (r.readiness === "not_ready") setSaid("Sending a snapshot is not available yet.");
    } finally { setSending(false); }
  }
  /* Shown only under filters it matches, and only until the feed carries it. */
  const pinned = sent && (!site || !sent.siteId || sent.siteId === site) && (!kind || sent.kind === kind) ? sent : null;
  const shown = useMemo(() => {
    if (!pinned || items.some(n => n.id === pinned.id || (n.kind === pinned.kind && n.title === pinned.title && Math.abs(time(n.at) - time(pinned.at)) < 120_000))) return items;
    return [pinned, ...items];
  }, [items, pinned]);

  /* "Download compliance snapshot": fetched first, so a snapshot that is not there yet says so here. A modified click
     (new tab, save as) is left to the browser. */
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState<{ text: string; fail: boolean } | null>(null);
  async function download(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (pdfBusy) return;
    setPdfBusy(true); setPdfError(null);
    try {
      const f = await api8.snapshot(site || undefined);
      const href = URL.createObjectURL(f.blob);
      const a = document.createElement("a"); a.href = href; a.download = f.filename;
      document.body.appendChild(a); a.click(); a.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 60_000);
      setSaid("Compliance snapshot downloaded");
    } catch (err) {
      const r = readinessOf(err);
      setPdfError(r.readiness === "not_ready" ? { text: "The compliance snapshot is not available yet.", fail: false } : { text: `Could not download the compliance snapshot: ${r.message}`, fail: true });
      if (r.readiness === "not_ready") setSaid("The compliance snapshot is not available yet.");
    } finally { setPdfBusy(false); }
  }

  const isNew = (n: OwnerNotification) => arrived.has(n.id) || (Boolean(since) && time(n.at) > time(since));
  const heading = site ? site3(site).name : "All sites";

  return <div className="page3">
    {/* The page head with the switch pinned beside the title, so it stays under the pointer when the mode changes. */}
    <Reveal as="header" className={`sh3 page ${s.head}`}>
      <h1 id="notifications-h" className={s.hTitle}>Notifications</h1>
      {view === "human" ? <>
        <p className={s.hSub}>What is waiting to reach you, what Steward last sent you by email, call and text, and what last happened at the three sites, newest first.</p>
        <div className={`tools ${s.hActions}`}>
          <a className="b3 quiet" href={snapshotPath(site || undefined)} download onClick={download} aria-busy={pdfBusy || undefined}><span>{pdfBusy ? "Preparing the PDF" : "Download compliance snapshot"}</span></a>
          <Btn arrow onClick={sendNow} aria-busy={sending || undefined}>{sending ? "Preparing the snapshot" : "Send me a snapshot now"}</Btn>
        </div>
      </> : null}
    </Reveal>
    <div className={s.status}>{[pdfError, sendError].map((m, i) => m ? <p key={i} className={m.fail ? "err3" : "note3"} role={m.fail ? "alert" : undefined}>{m.text}</p> : null)}</div>
    <Reveal className={s.bar} i={1}>
      <div className={`tabs3 ${s.sites}`} role="group" aria-label="Filter by site">{[{ id: "", short: "All sites" }, ...SITES3].map(x => <button key={x.id || "all"} type="button" aria-pressed={site === x.id} className={site === x.id ? "on" : ""} onClick={() => { setSite(x.id); setLimit(PAGE); }}>{x.short}</button>)}</div>
      <label className={`fld ${s.kind}`}>Kind
        <select value={kind} onChange={ev => { setKind(ev.target.value); setLimit(PAGE); }}>
          <option value="">All kinds</option>
          {kindOptions.map(k => <option key={k} value={k}>{kindWord(k)}</option>)}
        </select>
      </label>
    </Reveal>
    {view === "agent" ? <AgentPane filters={filters} feed={feed} items={items} current={current} outbox={outbox} outboxStatus={outboxStatus} />
      : view === "human" ? <><OutboxSection items={outbox} status={outboxStatus} siteId={site || undefined} i={2} /><Reveal as="section" className="p3" i={3} aria-labelledby="nt-list-h">
        <div className="p-head"><h2 id="nt-list-h">{heading}</h2><span className="meta">{!data ? "" : !current ? "Loading" : `${count(shown.length)}, newest first`}</span></div>
        {pinned && !data ? <ol className={`rows3 plain ${s.list} ${s.solo}`} aria-label="Just prepared"><Item n={pinned} isNew={isNew(pinned)} fresh={fresh.has(pinned.id)} issue={undefined} /></ol> : null}
        <State remote={feed} what="notifications" isEmpty={() => shown.length === 0} empty={emptyText}>
          {() => <>
            <ol className={`rows3 plain ${s.list}`} aria-labelledby="nt-list-h">{shown.map(n => <Item key={n.id} n={n} isNew={isNew(n)} fresh={fresh.has(n.id)} issue={n.links.issueId ? issues.get(n.links.issueId) : undefined} />)}</ol>
            {current && data && data.items.length >= limit && limit < MAX ? <div className={s.more}><Btn quiet small onClick={() => setLimit(l => Math.min(MAX, l + PAGE))}>Show more</Btn></div> : null}
          </>}
        </State>
      </Reveal></> : null}
    <p className="sr-only" aria-live="polite" aria-atomic="true">{said}</p>
  </div>;
}
