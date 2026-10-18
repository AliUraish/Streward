"use client";

/* The outbox on the notifications page (REALITY-CONTRACT-8.md section 2): everything that reaches you goes through one
   paced queue, at most one email and one call every two minutes, never two calls at once, and nothing in the first
   minutes after a start. What is waiting says when it goes out; what was sent says when; what the daily limit held, or
   what did not go out and why, says so. Agent mode reads the same as plain text (outboxText). */
import Link from "next/link";
import { useMemo } from "react";
import {
  clock, goesOutAt, outboxChannelWord, outboxPurposeWord, outboxStatusWord, outboxTo, type OutboxItem, type OutboxStatus,
} from "@/lib/api-10";
import type { Remote } from "@/lib/reality";
import { isSite3, site3 } from "@/lib/sites-3";
import { JaText, NotYet, Reveal, State, ago, when } from "./ui3";
import "./dash10.css";

const GROUPS: { key: string; title: string; has: (i: OutboxItem) => boolean }[] = [
  { key: "waiting", title: "Waiting to go out", has: i => i.status === "queued" || i.status === "sending" },
  { key: "sent", title: "Sent", has: i => i.status === "sent" },
  { key: "held", title: "Held by the daily limit", has: i => i.status === "capped" },
  { key: "not", title: "Not sent", has: i => ["dry_run", "failed", "canceled"].includes(i.status) },
];
const tone = (s: string) => (s === "sent" ? "ok" : s === "failed" ? "bad" : "held");
const later = (iso: string | null) => Boolean(iso) && Date.parse(iso!) > Date.now();

/* "Next email from 14:32", "Next call: now". */
function nextWord(iso: string | null): string { return iso && later(iso) ? `from ${clock(iso)}` : "now"; }
export function PacingLine({ status }: { status: OutboxStatus }) {
  const parts: string[] = [];
  if (status.bootGraceUntil && later(status.bootGraceUntil)) parts.push(`Nothing goes out before ${clock(status.bootGraceUntil)}`);
  parts.push(`Next email ${nextWord(status.nextEmailAt)}`, `next call ${nextWord(status.nextCallAt)}`);
  if (status.emailsPerDay !== null || status.emailsToday !== null) parts.push(`${status.emailsToday ?? 0} of ${status.emailsPerDay ?? "–"} emails today`);
  if (status.callsPerDay !== null || status.callsToday !== null) parts.push(`${status.callsToday ?? 0} of ${status.callsPerDay ?? "–"} calls`);
  return <p className="ob-pace">{parts.join(" · ")}</p>;
}

function OutboxRow({ i }: { i: OutboxItem }) {
  const site = i.siteId && isSite3(i.siteId) ? site3(i.siteId).short : null;
  const at = goesOutAt(i);
  const state = i.status === "queued" || i.status === "sending" ? (at && later(at) ? `goes out at ${clock(at)}` : "goes out next")
    : i.status === "sent" ? (i.sentAt ? `sent at ${clock(i.sentAt)}` : "sent") : outboxStatusWord(i.status).toLowerCase();
  return <li id={`ob-${i.id}`}>
    <span className="r1"><span className="tg">{outboxChannelWord(i.channel)}</span><strong className="ob-title"><JaText text={i.subject ?? i.preview ?? outboxPurposeWord(i.purpose)} /></strong></span>
    <span className="r2">{i.senderName} {outboxTo(i)}{i.purpose && i.subject ? `; ${outboxPurposeWord(i.purpose)}` : ""}</span>
    <span className="ob-meta"><span className={`chip10 ${tone(i.status)}`}>{state}</span>
      {i.reason && i.status !== "sent" && i.status !== "queued" ? <span className="r3">{i.reason}</span> : null}
      <span className="r3">{site ? `${site}, ` : ""}<time dateTime={i.at} title={when(i.at)}>{ago(i.at)}</time></span></span>
    {i.attachments.length ? <span className="ob-files">{i.attachments.map((a, k) => <span key={`${a.filename}-${k}`} className="oa-file">{a.filename}</span>)}</span> : null}
    {i.phoneCallId ? <Link className="lnk" href={`/app/conversations?call=${encodeURIComponent(i.phoneCallId)}`}>The call</Link> : null}
  </li>;
}

export function OutboxSection({ items, status, siteId, i = 2 }: { items: Remote<OutboxItem[]>; status: Remote<OutboxStatus>; siteId?: string; i?: number }) {
  const list = useMemo(() => (items.data ?? []).filter(x => !siteId || !x.siteId || x.siteId === siteId), [items.data, siteId]);
  const groups = GROUPS.map(g => ({ ...g, rows: list.filter(g.has) })).filter(g => g.rows.length);
  return <Reveal as="section" className="p3 ob10" i={i} aria-labelledby="outbox-h" id="outbox">
    <div className="p-head"><h2 id="outbox-h">Outbox</h2><span className="meta">at most one email and one call every 2 minutes</span></div>
    {status.data ? <PacingLine status={status.data} /> : <p className="ob-pace"><NotYet remote={status as Remote<unknown>} what="the pacing" /></p>}
    <State remote={items} what="the outbox" isEmpty={() => list.length === 0} empty="Nothing in the outbox yet.">
      {() => <div className="ob-groups">{groups.map(g => <div key={g.key} className="ob-group">
        <h3>{g.title}<span className="meta"> {g.rows.length}</span></h3>
        <ol className="rows3 plain ob-list">{(g.key === "waiting" ? [...g.rows].sort((a, b) => (goesOutAt(a) ?? "").localeCompare(goesOutAt(b) ?? "")) : g.rows).slice(0, g.key === "sent" ? 8 : 12).map(x => <OutboxRow key={x.id} i={x} />)}</ol>
      </div>)}</div>}
    </State>
  </Reveal>;
}
