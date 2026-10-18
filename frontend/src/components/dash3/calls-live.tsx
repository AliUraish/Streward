"use client";

/* What is happening now, dashboard-wide, mounted once by the shell (bottom right; in fullscreen, inside the fullscreen
   element so it stays in sight). Two things: a real phone call to you while it is on the line (phone-calls.tsx), and
   the agents' chats. Agents talk to each other in text, over A2A: when a chat starts, a notice says so ("Compliance
   Officer · Bristol started a chat with Site Inspector"); Follow opens the chat as it is written, its messages arriving
   as they are sent and its summary (what they did, what they decided) when it ends. */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api7 } from "@/lib/api-7";
import { useCalls } from "@/lib/hooks-7";
import { useHudEvents } from "@/lib/live-3";
import { agentName, siteList } from "@/lib/sites-3";
import type { Conversation } from "@/lib/types-3";
import { PhoneCallBanner } from "./phone-calls";
import { JaText, ago } from "./ui3";
import "./dash7.css";
import "./dash10.css";

const SEEN_KEY = "steward.chatsSeen";
const callerOf = (c: Conversation) => c.convener ?? c.participants[0] ?? "";
const othersOf = (c: Conversation) => c.participants.filter(p => p !== callerOf(c));
const names = (ids: string[]) => { const n = ids.map(agentName); return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n.at(-1)}` : n[0] ?? "the team"; };
/* Each name carries its site ("Compliance Officer · Myer"), so a chat across sites names both. */
export const startedText = (c: Conversation) => `${agentName(callerOf(c))} started a chat with ${names(othersOf(c))}`;
const topicOf = (c: Conversation) => c.title || c.summary?.headline || null;
const isOver = (c: Conversation) => Boolean(c.endedAt) || c.status === "ended";
function loadSeen(): Set<string> {
  try { const v: unknown = JSON.parse(window.sessionStorage.getItem(SEEN_KEY) ?? "[]"); return new Set(Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []); }
  catch { return new Set(); }
}
function saveSeen(s: Set<string>) { try { window.sessionStorage.setItem(SEEN_KEY, JSON.stringify([...s].slice(-80))); } catch { /* storage blocked */ } }

interface Toast { id: string; chat: Conversation; text: string }

export default function LiveNotifier() {
  const chats = useCalls();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [following, setFollowing] = useState<Conversation | null>(null);
  const [announce, setAnnounce] = useState("");
  const [fs, setFs] = useState<Element | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const primed = useRef(false);
  const toastHold = useRef(false);

  useEffect(() => { const h = () => setFs(document.fullscreenElement); h(); document.addEventListener("fullscreenchange", h); return () => document.removeEventListener("fullscreenchange", h); }, []);
  /* Realtime, when the shell's bridge has a channel: a conversation line is a nudge to read the chats now. */
  useHudEvents("all", { conversation_line: () => chats.reload() });

  const dismiss = useCallback((id: string) => setToasts(t => t.filter(x => x.id !== id)), []);
  const scheduleDismiss = useCallback((id: string) => {
    const tick = () => { if (toastHold.current) { window.setTimeout(tick, 3_000); return; } dismiss(id); };
    window.setTimeout(tick, 12_000);
  }, [dismiss]);

  /* New chats since the last read: a notice each. Chats that started before this page opened (more than 45 s ago) are
     history, not news. */
  useEffect(() => {
    const list = chats.data; if (!list) return;
    if (!seen.current) seen.current = loadSeen();
    const now = Date.now(); const fresh: Conversation[] = [];
    for (const c of [...list].reverse()) {
      if (seen.current.has(c.id)) continue;
      seen.current.add(c.id);
      if (!primed.current && !(now - Date.parse(c.startedAt) < 45_000)) continue;
      fresh.push(c);
    }
    primed.current = true;
    if (!fresh.length) return;
    saveSeen(seen.current);
    const items = fresh.map(c => ({ id: c.id, chat: c, text: startedText(c) }));
    setToasts(t => [...t, ...items].slice(-3));
    items.forEach(x => scheduleDismiss(x.id));
    setAnnounce(items.map(x => x.text).join(". "));
  }, [chats.data, scheduleDismiss]);

  const follow = (t: Toast) => { dismiss(t.id); setFollowing(t.chat); };

  const ui = <div className="calls7">
    <p className="sr-only" aria-live="polite">{announce}</p>
    <PhoneCallBanner />
    {toasts.map(t => <div key={t.id} className="ct7" role="group" aria-label="New chat" onPointerEnter={() => { toastHold.current = true; }} onPointerLeave={() => { toastHold.current = false; }} onFocus={() => { toastHold.current = true; }} onBlur={() => { toastHold.current = false; }}>
      <p className="ct-kind"><span className="sig" aria-hidden="true" />Chat{t.chat.siteIds.length ? ` · ${siteList(t.chat.siteIds)}` : ""}<span className="ct-when">{ago(t.chat.startedAt)}</span></p>
      <p className="ct-text">{t.text}</p>
      {topicOf(t.chat) ? <p className="ct-topic"><JaText text={topicOf(t.chat)} /></p> : null}
      <div className="ct-actions">
        <button type="button" className="ct-btn" onClick={() => follow(t)} aria-label={`Follow: ${t.text}`}>Follow</button>
        <button type="button" className="ct-btn quiet" onClick={() => dismiss(t.id)}>Dismiss</button>
      </div>
    </div>)}
    {following ? <ChatPanel key={following.id} first={following} onClose={() => setFollowing(null)} /> : null}
  </div>;
  return fs ? createPortal(ui, fs) : ui;
}

/* A chat as it is written: messages arrive as they are sent (read every 2 s while it is going), then the summary. */
function ChatPanel({ first, onClose }: { first: Conversation; onClose: () => void }) {
  const [chat, setChat] = useState(first);
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    let alive = true; let timer = 0; let idle = 0;
    const read = async () => {
      try { const fresh = await api7.call(first.id); if (!alive) return; setChat(prev => ({ ...fresh, convener: prev.convener ?? fresh.convener })); idle = isOver(fresh) ? idle + 1 : 0; }
      catch { idle += 1; }
      /* Once it has ended (or cannot be read), two more reads and the panel stops asking. */
      if (alive && idle < 3) timer = window.setTimeout(read, 2_000);
    };
    void read();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [first.id]);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [chat.transcript.length]);
  const live = !isOver(chat);
  const s = chat.summary;
  const sites = siteList(chat.siteIds);
  return <section className={`cl7 ${live ? "playing" : "done"}`} aria-label={live ? "Chat in progress" : "Chat ended"}>
    <header className="cl-head">
      <span className="cl-state"><span className={`dot10 ${live ? "live" : ""}`} aria-hidden="true" />{live ? "Chat in progress" : "Chat ended"}</span>
      {sites ? <span className="cl-sites">{sites}</span> : null}
      <span className="cl-tools"><button type="button" className="cl-btn" onClick={onClose} aria-label="Close the chat panel">Close</button></span>
    </header>
    <p className="cl-who"><strong>{agentName(callerOf(chat))}</strong> with <strong>{names(othersOf(chat))}</strong></p>
    {topicOf(chat) ? <p className="cl-topic"><JaText text={topicOf(chat)} /></p> : null}
    {!live && s ? <div className="cl-sum10">
      <p className="h">{s.headline}</p>
      {s.decisions.length ? <ul>{s.decisions.slice(0, 3).map((d, i) => <li key={i}>{d}</li>)}</ul> : null}
      {s.actions.length ? <ul className="acts">{s.actions.slice(0, 3).map((a, i) => <li key={i}><strong>{agentName(a.owner)}</strong> {a.task}</li>)}</ul> : null}
    </div> : null}
    <ol className="cl-lines" ref={listRef} aria-live="polite">{chat.transcript.map((t, i) => <li key={i}>
      <span className="who">{agentName(t.speaker)}</span><span className="txt"><JaText text={t.text} /></span>
    </li>)}</ol>
    <footer className="cl-foot">
      <span>{chat.transcript.length} message{chat.transcript.length === 1 ? "" : "s"}</span>
      <Link className="lnk" href={`/app/conversations?id=${encodeURIComponent(chat.id)}`}>Open in Conversations</Link>
    </footer>
  </section>;
}
