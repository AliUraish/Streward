"use client";

/* One agent in detail: who it is, what it is doing and why, its transcript (Listen, voiced by the browser's
   text-to-speech), recent tool calls with tokens, memory and runtime config. Used by Team and the Agents map. */
import { useEffect, useMemo, useRef, useState } from "react";
import type { Remote } from "@/lib/reality";
import { useAgentActivity, useAgentConfig, useAgentMemory, useTranscript3 } from "@/lib/hooks-3";
import { AGENTS3, agentName, site3, type AgentIdentity } from "@/lib/sites-3";
import { speak, speechAvailable, type SpeakHandle } from "@/lib/speech";
import type { AgentInfo, TranscriptEntry } from "@/lib/types-2";
import type { AgentMemory } from "@/lib/types-3";
import { AgentTools } from "./tools";
import { Btn, NotYet, Reveal, State, SynthTag, ago, n, when, words } from "./ui3";

export const LISTEN_NOTE = "voiced by your browser's text-to-speech";

/* One speaker at a time across the page: starting a new Listen stops the last. */
export function useSpeaker() {
  const handle = useRef<SpeakHandle | null>(null);
  const [owner, setOwner] = useState<string | null>(null);
  const [line, setLine] = useState(-1);
  const [available, setAvailable] = useState<boolean | null>(null);
  useEffect(() => { setAvailable(speechAvailable()); return () => handle.current?.stop(); }, []);
  function play(id: string, lines: { agentId: string; text: string }[]) {
    handle.current?.stop();
    if (!lines.length) return;
    setOwner(id);
    const h = speak(lines, i => { setLine(i); if (i < 0) setOwner(o => (o === id ? null : o)); });
    handle.current = h;
  }
  function stop() { handle.current?.stop(); handle.current = null; setOwner(null); setLine(-1); }
  return { available, owner, line, play, stop };
}
export type Speaker = ReturnType<typeof useSpeaker>;

export function AgentDetail({ me, info, speaker }: { me: AgentIdentity; info?: AgentInfo; speaker: Speaker }) {
  const activity = useAgentActivity(me.id);
  const transcript = useTranscript3(me.id);
  const memory = useAgentMemory(me.id);
  const config = useAgentConfig(me.id);
  const a = activity.data;
  return <div className="ag-detail">
    <Reveal className="p3 ag-head">
      <div className="who"><h2 className="ag-name">{me.name}</h2><p>{me.role}</p>
        <p className="ids">{me.inbox ? `${me.inbox}@inkboxmail.com` : "The customer's own agent, over MCP."}{me.team === "technician" ? "; SMS and calls to people through the Steward Dispatch Line" : ""}{me.siteId ? `; ${site3(me.siteId).name}` : ""}</p></div>
      <dl className="kv3 now">
        <dt>Status</dt><dd>{info?.status ?? "not available yet"}{info?.lastActivityAt ? `, ${ago(info.lastActivityAt)}` : ""}</dd>
        <dt>Task</dt><dd>{a?.currentTask ?? info?.currentTask ?? "None"}</dd>
        {a?.why ? <><dt>Why</dt><dd>{a.why}</dd></> : null}
        {a?.waitingOn ? <><dt>Waiting on</dt><dd>{a.waitingOn}</dd></> : null}
        <dt>Tokens this hour</dt><dd>{a ? n(a.tokensThisHour ?? null) : <NotYet remote={activity as Remote<unknown>} what="tokens" />}</dd>
      </dl>
    </Reveal>
    <div className="ag-grid">
      <Reveal className="p3 tr3" i={1}><Transcript id={me.id} remote={transcript} speaker={speaker} /></Reveal>
      <Reveal className="p3 calls3" i={2}>
        <div className="p-head"><h3>Recent tool calls</h3><span className="meta">{a ? `${n(a.tokensThisHour ?? null)} tokens this hour` : ""}</span></div>
        <State remote={activity} what="agent activity" isEmpty={x => x.lastActions.length === 0} empty="No tool calls yet.">
          {x => <div className="tbl3 calls-tbl" role="table" aria-label="Recent tool calls">
            <div className="tr head" role="row"><span role="columnheader">Tool</span><span role="columnheader">Target</span><span role="columnheader">Tokens</span><span role="columnheader">When</span></div>
            {x.lastActions.slice(0, 12).map((c, i) => <div className="tr" role="row" key={c.id ?? `${c.at}-${i}`}>
              <span role="cell" className={c.ok === false ? "bad" : ""}><strong>{c.tool}</strong>{c.ok === false ? <small>failed</small> : null}</span>
              <span role="cell">{c.target ?? ""}</span>
              <span role="cell" className="num">{n(c.tokens ?? ((c.inputTokens ?? 0) + (c.outputTokens ?? 0) || null))}</span>
              <span role="cell">{ago(c.at)}</span>
            </div>)}
          </div>}
        </State>
      </Reveal>
      <Reveal className="p3 mem3" i={3}><Memory remote={memory} /></Reveal>
      <Reveal className="p3 cfg3" i={4}>
        <div className="p-head"><h3>Runtime config</h3></div>
        <State remote={config} what="agent config">
          {c => <>
            <dl className="kv3">{Object.entries(c.config).map(([k, v]) => <div key={k} className="kv-pair"><dt>{words(k)}</dt><dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>)}</dl>
            {c.history?.length ? <ul className="rows3 plain">{c.history.map((h, i) => <li key={`${h.at}-${i}`}><span className="r1"><strong>{agentName(h.by)}</strong><span className="sev">changed {Object.keys(h.change).map(words).join(", ")}</span></span>{h.why ? <span className="r2">{h.why}</span> : null}<span className="r3">{when(h.at)}</span></li>)}</ul> : <p className="st3 empty">No changes yet.</p>}
          </>}
        </State>
      </Reveal>
      {me.id !== "operator" ? <Reveal className="p3 agtools3" i={5}><AgentTools agentId={me.id} siteId={me.siteId} /></Reveal> : null}
    </div>
  </div>;
}

function Transcript({ id, remote, speaker }: { id: string; remote: Remote<TranscriptEntry[]>; speaker: Speaker }) {
  const [all, setAll] = useState(false);
  /* Newest first, ten at a time; Listen reads the shown entries in the order they were said. */
  const sorted = useMemo(() => [...(remote.data ?? [])].sort((a, b) => b.at.localeCompare(a.at)), [remote.data]);
  const entries = all ? sorted.slice(0, 60) : sorted.slice(0, 10);
  const key = `t:${id}`;
  const playing = speaker.owner === key;
  const voiceOf = (e: TranscriptEntry) => e.direction === "out" ? e.agentId : (AGENTS3.some(a => a.id === e.counterpart) ? e.counterpart : e.agentId);
  const spoken = [...entries].reverse();
  const lines = spoken.map(e => ({ agentId: voiceOf(e), text: e.text }));
  const speakingId = playing && speaker.line >= 0 ? spoken[speaker.line]?.id : null;
  return <>
    <div className="p-head"><h3>Transcript</h3>
      <span className="listen">{speaker.available === false ? <span className="meta">This browser has no speech synthesis.</span> : <>{playing ? <Btn quiet small onClick={speaker.stop}>Stop</Btn> : <Btn quiet small disabled={!entries.length} onClick={() => speaker.play(key, lines)}>Listen</Btn>}<span className="meta">{LISTEN_NOTE}</span></>}</span>
    </div>
    <State remote={remote} what="the transcript" isEmpty={() => entries.length === 0} empty="Nothing said yet.">
      {() => <>
        <ol className="chat3" aria-label="Newest first">{entries.map(e => <li key={e.id} className={`${e.direction} ${speakingId === e.id ? "speaking" : ""}`}>
          <span className="r1"><strong>{e.direction === "out" ? agentName(e.agentId) : agentName(e.counterpart)}</strong><span className="sev">{e.direction === "out" ? `to ${agentName(e.counterpart)}` : `to ${agentName(e.agentId)}`}, {e.kind}</span><SynthTag rec={e} /></span>
          <span className="r2">{e.text}</span>
          <span className="r3">{when(e.at)}{speaker.available ? <button type="button" className="retry" onClick={() => speaker.play(`${key}:${e.id}`, [{ agentId: voiceOf(e), text: e.text }])}>Listen</button> : null}</span>
        </li>)}</ol>
        {sorted.length > 10 ? <div className="row-actions"><Btn quiet small onClick={() => setAll(!all)}>{all ? "Show the latest ten" : `Show ${Math.min(sorted.length, 60) - 10} earlier`}</Btn></div> : null}
      </>}
    </State>
  </>;
}

function Memory({ remote }: { remote: Remote<AgentMemory> }) {
  return <>
    <div className="p-head"><h3>Memory</h3><span className="meta">{remote.data ? (remote.data.source === "supermemory" ? `Supermemory, ${remote.data.container ?? "namespace"}` : `local mirror${remote.data.container ? ` of ${remote.data.container}` : ""}`) : ""}</span></div>
    {remote.data?.detail ? <p className="note3">{remote.data.detail}</p> : null}
    <State remote={remote} what="memory" isEmpty={m => m.items.length === 0} empty="No memories written yet.">
      {m => <ul className="rows3 plain">{m.items.slice(0, 12).map(x => <li key={x.id}><span className="r2">{x.text}</span><span className="r3">{x.kind ? `${words(x.kind)}, ` : ""}{when(x.at)}</span></li>)}</ul>}
    </State>
  </>;
}

