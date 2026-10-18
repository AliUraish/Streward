"use client";

/* /app/conversations: every chat, meeting and message between agents, and the phone calls to you. Agents talk to each
   other in text, so a chat opens on its summary (what they did: headline, points, decisions, actions), then its
   messages. Phone calls (phone-calls.tsx) are real calls on your phone: the transcript, what was agreed and what
   followed. ?id=<conversation> opens a chat, ?call=<call> a phone call. */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { Remote } from "@/lib/reality";
import { meetingAsConversation } from "@/lib/api-3";
import { useBoardMeetings, useConversations } from "@/lib/hooks-3";
import { SITES3, agentName, siteList } from "@/lib/sites-3";
import type { Conversation } from "@/lib/types-3";
import { PhoneCallsPanel } from "./phone-calls";
import { PageHead, Reveal, State, SynthTag, ago, when } from "./ui3";
import "./dash10.css";

const KIND: Record<string, string> = { call: "Chat", meeting: "Meeting", message: "Message" };
/* A message has no summary; its title is who wrote to whom. */
export const convTitle = (c: Conversation) => c.summary?.headline || (c.kind === "message" ? `${agentName(c.participants[0])} to ${c.participants.slice(1).map(agentName).join(", ") || "the team"}` : c.title) || "Conversation";
type Tab = "chats" | "messages" | "phone";

export default function ConversationsPage() {
  const remote = useConversations();
  const meetings = useBoardMeetings();
  const [site, setSite] = useState<string>("all");
  const [tab, setTab] = useState<Tab>("chats");
  const [open, setOpen] = useState<string | null>(null);
  const [call, setCall] = useState<string | null>(null);
  /* Until /api/conversations lands, board meetings stand in as meetings. */
  const fallback = remote.readiness === "not_ready" && meetings.data ? meetings.data.map(meetingAsConversation) : null;
  const list = useMemo(() => [...(remote.data ?? fallback ?? [])].sort((a, b) => b.startedAt.localeCompare(a.startedAt)), [remote.data, fallback]);
  const shown = list.filter(c => (site === "all" || c.siteIds.includes(site)) && (tab === "messages" || c.kind !== "message"));
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const id = q.get("id"); const callId = q.get("call");
    if (callId) { setTab("phone"); setCall(callId); } else if (id) setOpen(id);
  }, []);
  useEffect(() => { if (tab !== "phone" && !open && shown.length) setOpen(shown[0].id); }, [shown, open, tab]);
  const current = shown.find(c => c.id === open) ?? list.find(c => c.id === open) ?? null;
  const source: Remote<Conversation[]> = fallback ? { ...remote, data: fallback, readiness: "ready" } : remote;
  const openCall = useCallback((id: string) => setCall(id), []);
  const tabBtn = (id: Tab, label: string) => <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{label}</button>;
  return <div className="page3">
    <PageHead id="conversations" title="Conversations">
      <div className="tabs3" role="tablist" aria-label="Kinds">{tabBtn("chats", "Chats and meetings")}{tabBtn("messages", "With messages")}{tabBtn("phone", "Phone calls")}</div>
      <div className="tabs3" role="tablist" aria-label="Site">{[{ id: "all", short: "All sites" }, ...SITES3].map(s => <button key={s.id} type="button" role="tab" aria-selected={site === s.id} className={site === s.id ? "on" : ""} onClick={() => setSite(s.id)}>{s.short}</button>)}</div>
    </PageHead>
    {tab === "phone" ? <PhoneCallsPanel siteId={site === "all" ? undefined : site} openId={call} onOpen={openCall} />
      : <State remote={source} what="conversations" isEmpty={() => shown.length === 0} empty="No chats or meetings yet.">
        {() => <div className="conv3">
          <Reveal as="nav" className="conv-list" aria-label="Conversations">
            <ul className="rows3">{shown.map(c => <li key={c.id} className={c.id === current?.id ? "sel" : ""}><button type="button" className="row-btn" aria-pressed={c.id === current?.id} onClick={() => setOpen(c.id)}>
              <span className="r1"><span className="tg">{KIND[c.kind] ?? c.kind}</span><strong>{convTitle(c)}</strong><SynthTag rec={c} /></span>
              <span className="r2">{c.participants.map(agentName).join(", ")}</span>
              <span className="r3">{siteList(c.siteIds) || "All sites"}, {c.transcript.length} message{c.transcript.length === 1 ? "" : "s"}, {ago(c.startedAt)}</span>
            </button></li>)}</ul>
          </Reveal>
          {current ? <ConversationView key={current.id} c={current} /> : null}
        </div>}
      </State>}
  </div>;
}

function ConversationView({ c }: { c: Conversation }) {
  const s = c.summary;
  const live = !c.endedAt && c.status !== "ended" && c.kind !== "message";
  return <Reveal as="article" className="p3 conv-view" i={1} aria-labelledby="cv-h">
    <header className="cv-head">
      <div><span className="tg">{KIND[c.kind] ?? c.kind}</span>{live ? <span className="tg live10"><span className="dot10 live" aria-hidden="true" />in progress</span> : null}<SynthTag rec={c} /><h2 id="cv-h">{convTitle(c)}</h2>
        <p className="r3">{c.participants.map(agentName).join(", ")}; {when(c.startedAt)}{c.endedAt ? ` to ${new Date(c.endedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}; {c.transcript.length} message{c.transcript.length === 1 ? "" : "s"}</p></div>
    </header>
    <section className="cv-sum" aria-label="What they did">
      <h3>What they did</h3>
      {s ? <>
        {s.points.length ? <ul>{s.points.map((p, i) => <li key={i}>{p}</li>)}</ul> : null}
        {s.decisions.length ? <><h3>Decisions</h3><ul>{s.decisions.map((p, i) => <li key={i}>{p}</li>)}</ul></> : null}
        {s.actions.length ? <><h3>Actions</h3><ul className="actions">{s.actions.map((a, i) => <li key={i}><strong>{agentName(a.owner)}</strong> {a.task}{a.due ? <span className="r3">, due {when(a.due)}</span> : null}</li>)}</ul></> : null}
        {!s.points.length && !s.decisions.length && !s.actions.length ? <p className="r2">{s.headline}</p> : null}
      </> : <p className="st3 empty">{live ? "The summary is written when the chat ends." : c.kind === "message" ? "No summary." : "No summary for this conversation yet."}</p>}
    </section>
    <section className="cv-tr" aria-label="Messages">
      <h3>Messages</h3>
      <ol className="thread3">{c.transcript.map((t, i) => <li key={i}><strong>{agentName(t.speaker)}</strong><span>{t.text}</span></li>)}</ol>
    </section>
  </Reveal>;
}
