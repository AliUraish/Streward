"use client";

/* /app/memory: what the agents remember. Each agent keeps a persistent memory of its decisions, outcomes,
   reconfigurations and findings (GET /api/memory, or every agent's own memory merged until that route answers; see
   api3.memory). Newest first, filtered by site and agent, searched with a debounced query, polled every 15 s so new
   memories appear while the agents work. An entry links to its issue (the asset on the site's environment page, as the
   factory overview does) and to its conversation. */
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { api3 } from "@/lib/api-3";
import { usePoll } from "@/lib/hooks-3";
import { AGENTS3, SITES3, agentById, isSite3, site3, teamOf } from "@/lib/sites-3";
import type { MemoryEntry } from "@/lib/types-3";
import { Btn, LinkedText, PageHead, Reveal, State, ago, when, words } from "./ui3";
import s from "./memory.module.css";

const POLL_MS = 15_000;
const PAGE = 100;
const DEBOUNCE_MS = 350;

const KIND_WORD: Record<string, string> = {
  decision: "Decision", outcome: "Outcome", scenario_outcome: "Outcome", reconfigure: "Reconfiguration", reconfiguration: "Reconfiguration",
  finding: "Finding", document_review: "Finding", board_meeting: "Meeting", meeting: "Meeting", call: "Chat", message: "Message",
  conversation: "Chat", chat: "Chat", note: "Note",
};
const RECORD_WORDS = /\b(?:synthetic|simulated|seeded|seed|generated|demo|scenario)\b/gi;
/* The kind as a word; a note a call or meeting left says which it was. */
function kindWord(e: MemoryEntry): string {
  const k = e.kind.toLowerCase();
  if ((k === "note" || k === "conversation") && e.conversationId) return /^(Call|Meeting|Message)\b/.exec(e.text)?.[1] ?? "Conversation";
  const w = KIND_WORD[k] ?? words(k).replace(RECORD_WORDS, "").replace(/\s{2,}/g, " ").trim();
  return w ? w.charAt(0).toUpperCase() + w.slice(1) : "Note";
}
/* "Outcome: tokens per sweep 8608 -> 1116" under an Outcome tag reads once. */
function bodyOf(text: string, kind: string): string {
  const m = /^([^:]{1,40}):\s*/.exec(text);
  const t = m && m[1].trim().toLowerCase() === kind.toLowerCase() ? text.slice(m[0].length) : text;
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/* Where an issue lives (its site and asset), read once per issue and kept while the dashboard is open. */
interface IssueAt { siteId: string | null; assetTag: string | null }
const issueAt = new Map<string, IssueAt | null>();
const issueAsked = new Set<string>();
const issueListeners = new Set<() => void>();
function useIssueTargets(ids: string[]): ReadonlyMap<string, IssueAt | null> {
  const [, setTick] = useState(0);
  useEffect(() => { const f = () => setTick(t => t + 1); issueListeners.add(f); return () => { issueListeners.delete(f); }; }, []);
  const key = [...new Set(ids)].sort().join("\n");
  useEffect(() => {
    const todo = key ? key.split("\n").filter(id => !issueAt.has(id) && !issueAsked.has(id)) : [];
    if (!todo.length) return;
    todo.forEach(id => issueAsked.add(id));
    void Promise.allSettled(todo.map(id => api3.issue(id))).then(got => {
      got.forEach((r, i) => {
        issueAsked.delete(todo[i]);
        if (r.status === "fulfilled") issueAt.set(todo[i], { siteId: r.value.siteId ?? null, assetTag: r.value.assetTag || null });
        else if ((r.reason as { notReady?: boolean } | undefined)?.notReady) issueAt.set(todo[i], null);
      });
      issueListeners.forEach(f => f());
    });
  }, [key]);
  return issueAt;
}
function issueHref(e: MemoryEntry, at: IssueAt | null | undefined, tag: string | null): string | null {
  const siteId = at?.siteId ?? e.siteId;
  if (!siteId || !isSite3(siteId)) return null;
  return `/app/${siteId}/environment${tag ? `?asset=${encodeURIComponent(tag)}` : ""}`;
}
const count = (n: number) => `${n} ${n === 1 ? "memory" : "memories"}`;

export default function MemoryPage() {
  const [site, setSite] = useState("");
  const [agent, setAgent] = useState("");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);
  useEffect(() => { const t = window.setTimeout(() => { setQuery(text.trim()); setLimit(PAGE); }, DEBOUNCE_MS); return () => window.clearTimeout(t); }, [text]);
  /* ?site=, ?agent= and ?q= open the page filtered. */
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const s0 = p.get("site"); const a0 = p.get("agent"); const q0 = p.get("q");
    if (isSite3(s0)) setSite(s0);
    if (a0 && agentById(a0)) setAgent(a0);
    if (q0) { setText(q0); setQuery(q0.trim()); }
  }, []);

  const key = JSON.stringify([site, agent, query, limit]);
  const remote = usePoll(async () => ({ key, entries: await api3.memory({ siteId: site || undefined, agentId: agent || undefined, query: query || undefined, limit }) }), [key], POLL_MS);
  const data = remote.data;
  const current = data?.key === key;
  /* Narrowed here too, so a new site or agent shows at once while its own answer loads. */
  const entries = useMemo(() => (data?.entries ?? []).filter(e => (!site || !e.siteId || e.siteId === site) && (!agent || e.agentId === agent)), [data, site, agent]);
  const issues = useIssueTargets(useMemo(() => entries.flatMap(e => e.issueId && !e.refs.assetTag ? [e.issueId] : []), [entries]));

  /* Memories that arrive while the page is open rise once; a new filter starts afresh. */
  const seen = useRef<{ key: string; ids: Set<string> } | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set());
  useEffect(() => {
    if (!data || data.key !== key) return;
    const ids = data.entries.map(e => e.id);
    if (seen.current?.key !== data.key) { seen.current = { key: data.key, ids: new Set(ids) }; return; }
    const known = seen.current.ids;
    const added = ids.filter(id => !known.has(id));
    if (!added.length) return;
    added.forEach(id => known.add(id));
    setFresh(new Set(added));
  }, [data, key]);
  useEffect(() => { if (!fresh.size) return; const t = window.setTimeout(() => setFresh(new Set()), 2400); return () => window.clearTimeout(t); }, [fresh]);

  const empty = query ? `Nothing remembered matches “${query}”.` : "Nothing remembered yet.";
  /* One announcement per filter, when its answer lands; polling stays quiet. */
  const [said, setSaid] = useState("");
  const announced = useRef("");
  useEffect(() => {
    if (!current || announced.current === key) return;
    announced.current = key;
    setSaid(entries.length ? count(entries.length) : empty);
  }, [current, key, entries.length, empty]);

  function pickSite(id: string) {
    setSite(id); setLimit(PAGE);
    const a = agentById(agent);
    if (id && a?.siteId && a.siteId !== id) setAgent("");
  }
  const across = AGENTS3.filter(a => !a.siteId);
  const heading = agent ? agentById(agent)?.name ?? "Agent" : site ? site3(site).name : "All sites";
  const pending = text.trim() !== query || (data !== null && !current);

  return <div className="page3">
    <PageHead id="memory" title="Memory">
      <div className="tabs3" role="group" aria-label="Filter by site">{[{ id: "", short: "All sites" }, ...SITES3].map(x => <button key={x.id || "all"} type="button" aria-pressed={site === x.id} className={site === x.id ? "on" : ""} onClick={() => pickSite(x.id)}>{x.short}</button>)}</div>
    </PageHead>
    <Reveal as="section" className="p3" i={1} aria-labelledby="mem-list-h">
      <form className={s.bar} role="search" aria-label="Search memories" onSubmit={ev => { ev.preventDefault(); setQuery(text.trim()); setLimit(PAGE); }}>
        <label className="fld">Agent
          <select value={agent} onChange={ev => { setAgent(ev.target.value); setLimit(PAGE); }}>
            <option value="">All agents</option>
            <optgroup label="Across sites">{across.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</optgroup>
            {SITES3.filter(x => !site || x.id === site).map(x => <optgroup key={x.id} label={x.name}>{teamOf(x.id).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</optgroup>)}
          </select>
        </label>
        <label className="fld">Search
          <input type="search" value={text} onChange={ev => setText(ev.target.value)} placeholder="Words in what the agents remember" autoComplete="off" spellCheck={false} enterKeyHint="search" />
        </label>
      </form>
      <div className="p-head"><h2 id="mem-list-h">{heading}</h2><span className="meta">{!data ? "" : pending ? "Loading" : count(entries.length)}</span></div>
      <p className="sr-only" aria-live="polite" aria-atomic="true">{said}</p>
      <State remote={remote} what="memories" isEmpty={() => entries.length === 0} empty={empty}>
        {() => <>
          <ol className={`rows3 plain ${s.list}`} aria-labelledby="mem-list-h">{entries.map(e => {
            const kind = kindWord(e);
            const at = e.issueId ? issues.get(e.issueId) : undefined;
            const tag = at?.assetTag ?? e.refs.assetTag ?? null;
            const issue = e.issueId ? issueHref(e, at, tag) : null;
            const time = ago(e.at);
            return <li key={e.id} className={fresh.has(e.id) ? s.fresh : undefined}>
              <span className="r1"><span className="tg">{kind}</span><strong>{e.agentName}</strong></span>
              <p className={`r2 ${s.text}`}><LinkedText text={bodyOf(e.text, kind)} /></p>
              <span className="r3">{e.siteId && isSite3(e.siteId) ? site3(e.siteId).short : "All sites"}{time ? <>, <time dateTime={e.at} title={when(e.at)}>{time}</time></> : null}</span>
              {issue || e.conversationId ? <span className={`r3 ${s.links}`}>
                {issue ? <Link className="lnk" href={issue}>Open the issue{tag ? ` on ${tag}` : ""}</Link> : null}
                {e.conversationId ? <Link className="lnk" href={`/app/conversations?id=${encodeURIComponent(e.conversationId)}`}>Read the conversation</Link> : null}
              </span> : null}
            </li>;
          })}</ol>
          {current && data && data.entries.length >= limit ? <div className={s.more}><Btn quiet small onClick={() => setLimit(l => l + PAGE)}>Show more</Btn></div> : null}
        </>}
      </State>
    </Reveal>
  </div>;
}
