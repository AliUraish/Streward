"use client";

/* Real phone calls (REALITY-CONTRACT-8.md section 3). An agent calls you on your one phone (as the owner, the contractor
   or an employee) from the Steward line, and the conversation is held on the call itself. While a call is on the line a
   banner, mounted once by the shell, says who is calling whom, how long it has run and shows the transcript as it
   arrives; when it ends, what was agreed and what followed: the email that goes out next and when, the booking. The
   conversations page lists every call with its transcript and outcome. People are named by role; numbers and addresses
   are never shown. */
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  callStatusWord, clock, duration, goesOutAt, isLiveCall, isOverCall, isQueuedCall, optionLabel, outboxStatusWord, purposeWord, recipientWord,
  resultWord, roleNoun, roleWord, type CallFollowUp, type OutboxItem, type PhoneCall,
} from "@/lib/api-10";
import { useActivePhoneCalls, useOutbox, usePhoneCall, usePhoneCalls } from "@/lib/hooks-10";
import type { Remote } from "@/lib/reality";
import { isSite3, site3 } from "@/lib/sites-3";
import { JaText, Reveal, State, ago, when } from "./ui3";
import "./dash10.css";

const SHOW_OUTCOME_MS = 45_000;
const WAIT_OUTCOME_MS = 120_000;
const t = (iso: string | null | undefined) => { const x = iso ? Date.parse(iso) : NaN; return Number.isNaN(x) ? 0 : x; };
const siteShort = (id: string | null) => (id && isSite3(id) ? site3(id).short : null);
/* "04:12": how long the call has run, from its start (or its queue time while it rings). */
function elapsed(c: PhoneCall, now: number): string {
  const from = t(c.startedAt) || t(c.queuedAt); if (!from) return "";
  const until = isOverCall(c) ? (t(c.endedAt) || now) : now;
  const s = Math.max(0, Math.round((until - from) / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
function useNow(on: boolean, ms = 1_000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { if (!on) return; const id = window.setInterval(() => setNow(Date.now()), ms); return () => window.clearInterval(id); }, [on, ms]);
  return now;
}
const resultTone = (r: string) => (r === "agreed" ? "ok" : r === "failed" || r === "declined" ? "bad" : "held");
/* "the contractor (Avon Pump & Valve)": the role, and who you are on this call. */
const calleeText = (c: PhoneCall) => `${roleNoun(c.calleeRole)}${c.calleeName ? ` (${c.calleeName})` : ""}`;

/* ---- what followed a call ------------------------------------------------------------------------------- */
function followWords(f: CallFollowUp, c: PhoneCall): { text: string; href: string | null; label: string | null } {
  const who = roleWord(c.calleeRole);
  const cc = f.cc.length ? `, copying ${f.cc.map(recipientWord).join(", ")}` : "";
  switch (f.type) {
    case "email_file": return { text: `Email to ${who}${cc}${f.topic ? `: ${f.topic}` : ""}`, href: "/app/notifications#outbox", label: "Outbox" };
    case "book_slot": {
      const slot = optionLabel(c, c.outcome?.chosenOptionId) ?? f.details;
      return { text: `Booked${slot ? `: ${slot}` : ""}`, href: c.siteId && isSite3(c.siteId) ? `/app/${c.siteId}/maintenance` : null, label: "Maintenance" };
    }
    case "counsel_call": return { text: `Compliance Counsel calls ${who}${f.topic ? ` about ${f.topic}` : ""}`, href: f.ref ? `/app/conversations?call=${encodeURIComponent(f.ref)}` : null, label: f.ref ? "The call" : null };
    case "callback": return { text: `Calls ${who} back${f.details ? `, ${f.details}` : ""}`, href: null, label: null };
    case "note": return { text: `Noted: ${f.details ?? f.topic ?? ""}`.trim(), href: null, label: null };
    default: return { text: [f.type.replace(/_/g, " "), f.topic, f.details].filter(Boolean).join(": "), href: null, label: null };
  }
}
/* An email follow-up's state comes from its outbox item when the item is known ("goes out at 14:32", "sent at 14:30"). */
function followState(f: CallFollowUp, item: OutboxItem | undefined): { text: string; tone: "ok" | "held" | "bad" } {
  if (item) {
    if (item.status === "sent") return { text: item.sentAt ? `sent at ${clock(item.sentAt)}` : "sent", tone: "ok" };
    if (item.status === "queued" || item.status === "sending") { const at = goesOutAt(item); return { text: at ? `goes out at ${clock(at)}` : "waiting to go out", tone: "held" }; }
    return { text: outboxStatusWord(item.status).toLowerCase(), tone: item.status === "failed" ? "bad" : "held" };
  }
  const s = f.status;
  if (s === "done" || s === "sent") return { text: "done", tone: "ok" };
  if (s === "failed") return { text: "failed", tone: "bad" };
  if (s === "skipped") return { text: "skipped", tone: "held" };
  return { text: "queued", tone: "held" };
}

export function CallOutcome({ c }: { c: PhoneCall }) {
  const o = c.outcome;
  const refs = useMemo(() => (o?.followUps ?? []).map(f => f.ref).filter((x): x is string => Boolean(x)), [o]);
  /* The outbox is read only when a follow-up names one of its items. */
  const outbox = useOutbox({ limit: refs.length ? 80 : 1 }, refs.length ? 10_000 : 600_000);
  const byId = useMemo(() => new Map((outbox.data ?? []).map(i => [i.id, i])), [outbox.data]);
  if (!o) {
    const note = c.status === "voicemail" ? "Nobody picked up; a message was left." : c.status === "no_answer" ? "Nobody answered." : c.status === "failed" ? "The call did not go through."
      : c.status === "dry_run" ? "Not placed: live calling is off." : c.status === "capped" ? "Held: today's call limit was reached." : "Reading what was agreed.";
    return <p className="pc-note">{note}</p>;
  }
  const chosen = optionLabel(c, o.chosenOptionId);
  return <div className="pc-out">
    <p className="pc-result">{o.result ? <span className={`chip10 ${resultTone(o.result)}`}>{resultWord(o.result)}</span> : null}{o.decision ? <span className="pc-decision"><JaText text={o.decision} /></span> : null}</p>
    {chosen ? <p className="pc-agreed"><span className="k">Agreed</span>{chosen}</p> : null}
    {o.summary && o.summary !== o.decision ? <p className="pc-sum"><JaText text={o.summary} /></p> : null}
    {o.followUps.length ? <ul className="pc-follow" aria-label="What followed">{o.followUps.map((f, i) => { const w = followWords(f, c); const st = followState(f, f.ref ? byId.get(f.ref) : undefined);
      return <li key={`${f.type}-${i}`}><span className="pc-ftext">{w.text}</span><span className={`chip10 ${st.tone}`}>{st.text}</span>{w.href && w.label ? <Link className="lnk" href={w.href}>{w.label}</Link> : null}</li>; })}</ul> : null}
  </div>;
}

/* ---- the transcript ------------------------------------------------------------------------------------- */
export function CallLines({ c, live, max }: { c: PhoneCall; live: boolean; max?: number }) {
  const ref = useRef<HTMLOListElement>(null);
  const lines = max ? c.transcript.slice(-max) : c.transcript;
  useEffect(() => { const el = ref.current; if (el) el.scrollTop = el.scrollHeight; }, [lines.length]);
  if (!lines.length) return <p className="pc-note">{live ? (c.status === "dialing" ? "Ringing." : "Listening for the first words.") : "No transcript was kept for this call."}</p>;
  return <ol className="pc-lines" ref={ref} aria-live={live ? "polite" : "off"} aria-label="Transcript">{lines.map(l => <li key={`${l.seq}-${l.party}`} className={l.party}>
    <span className="who">{l.party === "person" ? roleWord(c.calleeRole) : l.name}</span><span className="txt"><JaText text={l.text} /></span>
  </li>)}</ol>;
}

/* ---- the banner ----------------------------------------------------------------------------------------- */
export function PhoneCallBanner() {
  const active = useActivePhoneCalls();
  const [shownId, setShownId] = useState<string | null>(null);
  const [closed, setClosed] = useState<ReadonlySet<string>>(() => new Set());
  const [over, setOver] = useState<{ id: string; at: number } | null>(null);
  const hold = useRef(false);
  const liveNow = (active.data ?? []).find(c => isLiveCall(c) && !closed.has(c.id)) ?? null;
  /* A new call on the line takes the banner; the last one stays to show its outcome until it is done with. */
  useEffect(() => { if (liveNow && liveNow.id !== shownId) { setShownId(liveNow.id); setOver(null); } }, [liveNow, shownId]);
  const fromList = (active.data ?? []).find(c => c.id === shownId) ?? null;
  const [last, setLast] = useState<PhoneCall | null>(null);
  const one = usePhoneCall(shownId, true);
  const c = (one.data && one.data.id === shownId ? one.data : null) ?? fromList ?? (last && last.id === shownId ? last : null);
  useEffect(() => { if (c) setLast(c); }, [c]);
  const live = Boolean(c && (isLiveCall(c) || isQueuedCall(c)));
  const now = useNow(Boolean(c));
  useEffect(() => { if (c && !live && (!over || over.id !== c.id)) setOver({ id: c.id, at: Date.now() }); }, [c, live, over]);
  const close = () => { if (shownId) setClosed(s => new Set([...s, shownId])); setShownId(null); setOver(null); };
  /* Ended: the outcome stays up for a while (longer while the pointer is on it); without an outcome it waits up to 2 min. */
  useEffect(() => {
    if (!c || live || !over || over.id !== c.id) return;
    const wait = c.outcome ? SHOW_OUTCOME_MS : WAIT_OUTCOME_MS;
    const tick = () => { if (hold.current) { timer = window.setTimeout(tick, 5_000); return; } close(); };
    let timer = window.setTimeout(tick, Math.max(1_000, wait - (Date.now() - over.at)));
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c?.id, c?.outcome ? 1 : 0, live, over]);
  if (!c || closed.has(c.id)) return null;
  const site = siteShort(c.siteId);
  const ringing = c.status === "dialing" || c.status === "ringing";
  return <section className={`pc10 ${live ? "on" : "done"}`} aria-label={live ? "Phone call on the line" : "Phone call ended"}
    onPointerEnter={() => { hold.current = true; }} onPointerLeave={() => { hold.current = false; }} onFocus={() => { hold.current = true; }} onBlur={() => { hold.current = false; }}>
    <header className="pc-head">
      <span className="pc-state"><span className={`dot10 ${live ? "live" : ""}`} aria-hidden="true" />{live ? (ringing ? "Ringing" : "Live call") : "Call ended"}</span>
      <span className="pc-time" aria-label="Call time">{elapsed(c, now)}</span>
      {site ? <span className="pc-site">{site}</span> : null}
      <button type="button" className="cl-btn" onClick={close} aria-label="Close the call banner">Close</button>
    </header>
    <p className="pc-who"><strong>{c.callerName}</strong> {live ? "is calling" : "called"} {calleeText(c)}</p>
    <p className="pc-sub">{live ? (ringing ? `Ringing ${roleWord(c.calleeRole)}` : `On the line with ${roleWord(c.calleeRole)}`) : `${callStatusWord(c.status)}${c.durationSeconds ? `, ${duration(c.durationSeconds)}` : ""}`}<span aria-hidden="true"> · </span>{purposeWord(c.purpose)}<span aria-hidden="true"> · </span>Transcribed</p>
    {c.goal ? <p className="pc-goal"><JaText text={c.goal} /></p> : null}
    <CallLines c={c} live={live} />
    {!live ? <CallOutcome c={c} /> : null}
    <footer className="pc-foot"><Link className="lnk" href={`/app/conversations?call=${encodeURIComponent(c.id)}`}>Open the call</Link></footer>
  </section>;
}

/* ---- the list (the conversations page) ------------------------------------------------------------------ */
export function PhoneCallsPanel({ siteId, openId, onOpen }: { siteId?: string; openId: string | null; onOpen: (id: string) => void }) {
  const calls = usePhoneCalls({ siteId, limit: 20 });
  const list = calls.data ?? [];
  useEffect(() => { if (!openId && list.length) onOpen(list[0].id); }, [openId, list, onOpen]);
  const current = list.find(c => c.id === openId) ?? null;
  return <State remote={calls} what="phone calls" isEmpty={() => list.length === 0 && !openId} empty="No phone calls yet.">
    {() => <div className="conv3">
      <Reveal as="nav" className="conv-list" aria-label="Phone calls">
        <ul className="rows3">{list.map(c => <li key={c.id} className={c.id === openId ? "sel" : ""}><button type="button" className="row-btn" aria-pressed={c.id === openId} onClick={() => onOpen(c.id)}>
          <span className="r1">{isLiveCall(c) ? <span className="dot10 live" aria-hidden="true" /> : null}<span className="tg">Phone</span><strong>{purposeWord(c.purpose)}</strong></span>
          <span className="r2">{c.callerName} called {roleWord(c.calleeRole)}</span>
          <span className="r3">{callStatusWord(c.status)}{siteShort(c.siteId) ? `, ${siteShort(c.siteId)}` : ""}, {ago(c.at)}</span>
        </button></li>)}</ul>
      </Reveal>
      {openId ? <PhoneCallView key={openId} id={openId} initial={current} /> : null}
    </div>}
  </State>;
}

export function PhoneCallView({ id, initial }: { id: string; initial: PhoneCall | null }) {
  const [fast, setFast] = useState(true);
  const one = usePhoneCall(id, fast);
  const c = one.data ?? initial;
  const live = Boolean(c && (isLiveCall(c) || isQueuedCall(c)));
  const now = useNow(live);
  useEffect(() => { setFast(!c || live || (!c.outcome && Date.now() - t(c.endedAt) < WAIT_OUTCOME_MS)); }, [c, live]);
  if (!c) return <Reveal as="article" className="p3 conv-view" i={1}><State remote={one as Remote<PhoneCall | null>} what="the call">{() => <p className="st3 empty">This call is not in the list.</p>}</State></Reveal>;
  return <Reveal as="article" className="p3 conv-view pcv10" i={1} aria-labelledby="pcv-h">
    <header className="cv-head">
      <div><span className="tg">Phone call</span>{live ? <span className="tg live10"><span className="dot10 live" aria-hidden="true" />{elapsed(c, now)}</span> : null}
        <h2 id="pcv-h">{c.callerName} {live ? "is calling" : "called"} {calleeText(c)}</h2>
        <p className="r3">{purposeWord(c.purpose)}; {callStatusWord(c.status)}{c.durationSeconds ? `, ${duration(c.durationSeconds)}` : ""}; {when(c.startedAt ?? c.queuedAt)}{c.attempt && c.attempt > 1 ? `; attempt ${c.attempt}` : ""}</p></div>
    </header>
    {c.goal || c.facts.length || c.options.length ? <section className="cv-sum" aria-label="What the call was for">
      {c.goal ? <><h3>Goal</h3><p className="pc-goal big"><JaText text={c.goal} /></p></> : null}
      {c.facts.length ? <><h3>Facts</h3><ul>{c.facts.map((f, i) => <li key={i}><JaText text={f} /></li>)}</ul></> : null}
      {c.options.length ? <><h3>Options offered</h3><ul>{c.options.map(o => <li key={o.id} className={c.outcome?.chosenOptionId === o.id ? "chosen10" : ""}>{o.label}{c.outcome?.chosenOptionId === o.id ? <span className="chip10 ok">agreed</span> : null}</li>)}</ul></> : null}
    </section> : null}
    {!live ? <section className="cv-sum" aria-label="Summary"><h3>Summary</h3><CallOutcome c={c} /></section> : null}
    <section className="cv-tr" aria-label="Transcript">
      <h3>Transcript</h3>
      <p className="pc-note">Transcribed live; the person on the call is told at the start.</p>
      <CallLines c={c} live={live} />
    </section>
  </Reveal>;
}
