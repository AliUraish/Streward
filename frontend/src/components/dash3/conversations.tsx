"use client";

/* /app/conversations: every call, meeting and message between agents. Summary first (headline, points, decisions,
   actions), then the transcript, then Listen. A call is an Inkbox A2A conversation presented as a call; the voices
   are the browser's text-to-speech, and there are no phone calls between agents on the current plan. */
import { useEffect, useMemo, useState } from "react";
import type { Remote } from "@/lib/reality";
import { meetingAsConversation } from "@/lib/api-3";
import { useBoardMeetings, useConversations } from "@/lib/hooks-3";
import { SITES3, agentName, scenarioTitle, site3 } from "@/lib/sites-3";
import type { Conversation } from "@/lib/types-3";
import { LISTEN_NOTE, useSpeaker } from "./agent-detail";
import { Btn, PageHead, Reveal, State, SynthTag, ago, when } from "./ui3";

const KIND: Record<string, string> = { call: "Call", meeting: "Meeting", message: "Message" };

export default function ConversationsPage() {
  const remote = useConversations();
  const meetings = useBoardMeetings();
  const [site, setSite] = useState<string>("all");
  const [open, setOpen] = useState<string | null>(null);
  const speaker = useSpeaker();
  /* Until /api/conversations lands, board meetings stand in as meetings. */
  const fallback = remote.readiness === "not_ready" && meetings.data ? meetings.data.map(meetingAsConversation) : null;
  const list = useMemo(() => [...(remote.data ?? fallback ?? [])].sort((a, b) => b.startedAt.localeCompare(a.startedAt)), [remote.data, fallback]);
  const shown = list.filter(c => site === "all" || c.siteIds.includes(site));
  useEffect(() => { const q = new URLSearchParams(window.location.search).get("id"); if (q) setOpen(q); }, []);
  useEffect(() => { if (!open && shown.length) setOpen(shown[0].id); }, [shown, open]);
  const current = shown.find(c => c.id === open) ?? list.find(c => c.id === open) ?? null;
  const source: Remote<Conversation[]> = fallback ? { ...remote, data: fallback, readiness: "ready" } : remote;
  return <div className="page3">
    <PageHead id="conversations" title="Conversations" sub="Every call and meeting between the agents, newest first. Calls are Inkbox A2A conversations between the agents' identities, presented as calls; there are no phone calls between agents.">
      <div className="tabs3" role="tablist" aria-label="Factory">{[{ id: "all", short: "Both" }, ...SITES3].map(s => <button key={s.id} type="button" role="tab" aria-selected={site === s.id} className={site === s.id ? "on" : ""} onClick={() => setSite(s.id)}>{s.short}</button>)}</div>
    </PageHead>
    {fallback ? <p className="note3">The conversations endpoint is not available yet; showing the board meetings recorded so far.</p> : null}
    <State remote={source} what="conversations" isEmpty={() => shown.length === 0} empty="No calls or meetings yet. Start a scenario on the portfolio page and the agents will talk.">
      {() => <div className="conv3">
        <Reveal as="nav" className="conv-list" aria-label="Conversations">
          <ul className="rows3">{shown.map(c => <li key={c.id} className={c.id === current?.id ? "sel" : ""}><button type="button" className="row-btn" aria-pressed={c.id === current?.id} onClick={() => setOpen(c.id)}>
            <span className="r1"><span className="tg">{KIND[c.kind] ?? c.kind}</span><strong>{c.summary?.headline || c.title || "Conversation"}</strong><SynthTag rec={c} /></span>
            <span className="r2">{c.participants.map(agentName).join(", ")}</span>
            <span className="r3">{c.siteIds.map(id => site3(id).short).join(" and ") || "Both"}, {ago(c.startedAt)}{c.transport === "inkbox" ? ", Inkbox A2A" : c.transport ? `, ${c.transport}` : ""}</span>
          </button></li>)}</ul>
        </Reveal>
        {current ? <ConversationView key={current.id} c={current} speaker={speaker} /> : null}
      </div>}
    </State>
  </div>;
}

function ConversationView({ c, speaker }: { c: Conversation; speaker: ReturnType<typeof useSpeaker> }) {
  const key = `c:${c.id}`;
  const playing = speaker.owner === key;
  const s = c.summary;
  const lines = [...(s ? [{ agentId: c.participants[0] ?? "director", text: s.headline }] : []), ...c.transcript.map(t => ({ agentId: t.speaker, text: t.text }))];
  const offset = s ? 1 : 0;
  return <Reveal as="article" className="p3 conv-view" i={1} aria-labelledby="cv-h">
    <header className="cv-head">
      <div><span className="tg">{KIND[c.kind] ?? c.kind}</span><SynthTag rec={c} /><h2 id="cv-h">{s?.headline || c.title || "Conversation"}</h2>
        <p className="r3">{c.participants.map(agentName).join(", ")}; {when(c.startedAt)}{c.endedAt ? ` to ${new Date(c.endedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}{c.scenarioId ? `; scenario: ${scenarioTitle(c.scenarioId)}` : ""}</p></div>
    </header>
    <section className="cv-sum" aria-label="Summary">
      {s ? <>
        {s.points.length ? <><h3>Points</h3><ul>{s.points.map((p, i) => <li key={i}>{p}</li>)}</ul></> : null}
        {s.decisions.length ? <><h3>Decisions</h3><ul>{s.decisions.map((p, i) => <li key={i}>{p}</li>)}</ul></> : null}
        {s.actions.length ? <><h3>Actions</h3><ul className="actions">{s.actions.map((a, i) => <li key={i}><strong>{agentName(a.owner)}</strong> {a.task}{a.due ? <span className="r3">, due {when(a.due)}</span> : null}</li>)}</ul></> : null}
        <p className="r3">Summary by {c.summaryBy === "claude-opus-5-5" ? "Claude (claude-opus-5-5)" : c.summaryBy ?? "the record"}.</p>
      </> : <p className="st3 empty">No summary for this conversation yet.</p>}
    </section>
    <section className="cv-tr" aria-label="Transcript">
      <h3>Transcript</h3>
      <ol className="thread3">{c.transcript.map((t, i) => <li key={i} className={playing && speaker.line === i + offset ? "speaking" : ""}><strong>{agentName(t.speaker)}</strong><span>{t.text}</span></li>)}</ol>
    </section>
    <div className="cv-listen">
      {speaker.available === false ? <span className="meta">This browser has no speech synthesis, so there is nothing to listen to.</span>
        : <>{playing ? <Btn quiet small onClick={speaker.stop}>Stop</Btn> : <Btn small arrow disabled={!lines.length} onClick={() => speaker.play(key, lines)}>Listen</Btn>}<span className="meta">{LISTEN_NOTE}, one voice per agent</span></>}
    </div>
  </Reveal>;
}
