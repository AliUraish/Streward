"use client";

/* Calls, dashboard-wide (REALITY-CONTRACT-7.md section 7), mounted once by the shell. Every 3 s it reads the latest
   calls; when a new one starts it says so ("Compliance Officer · Bristol started a call with Compliance Officer ·
   Myer") with Listen. The live call panel reveals the transcript line by line as it is spoken, each agent in its own
   voice (lib/speech.ts). "Play calls aloud", remembered on this device, plays new calls as they start. Browsers make
   no sound before a click on the page, so that switch's click unlocks it (as does any click); until then, or with no
   voices at all, the lines appear on a timer. In fullscreen (the mission view) the toasts and the panel move into the
   fullscreen element so they stay in sight. */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { api7 } from "@/lib/api-7";
import { useCalls } from "@/lib/hooks-7";
import { useHudEvents } from "@/lib/live-3";
import { loadVoices, speakOne, speechAvailable, stopSpeech, unlockSpeech } from "@/lib/speech";
import { agentName, siteList } from "@/lib/sites-3";
import type { Conversation } from "@/lib/types-3";
import { JaText, ago } from "./ui3";
import "./dash7.css";

/* ---- "Play calls aloud": one small store, so the sidebar switch and the notifier agree ------------------------- */
const ALOUD_KEY = "steward.callsAloud";
const SEEN_KEY = "steward.callsSeen";
interface Sound { aloud: boolean; unlocked: boolean }
const SERVER: Sound = { aloud: false, unlocked: false };
let sound: Sound = SERVER;
let hydrated = false;
const subs = new Set<() => void>();
const emit = (next: Partial<Sound>) => { sound = { ...sound, ...next }; subs.forEach(f => f()); };
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
function hydrate() {
  if (hydrated || typeof window === "undefined") return;
  hydrated = true;
  let aloud = false; try { aloud = window.localStorage.getItem(ALOUD_KEY) === "1"; } catch { /* storage blocked */ }
  let unlocked = false; try { unlocked = Boolean((navigator as Navigator & { userActivation?: { hasBeenActive?: boolean } }).userActivation?.hasBeenActive); } catch { /* no such API */ }
  emit({ aloud, unlocked: unlocked || sound.unlocked });
}
function unlock() { if (!sound.unlocked) { unlockSpeech(); emit({ unlocked: true }); } }
export function useSound(): Sound { return useSyncExternalStore(subscribe, () => sound, () => SERVER); }
export function setAloud(on: boolean) {
  if (on) { unlockSpeech(); emit({ aloud: true, unlocked: true }); } else { emit({ aloud: false }); stopSpeech(); }
  try { window.localStorage.setItem(ALOUD_KEY, on ? "1" : "0"); } catch { /* storage blocked */ }
}

/* The sidebar switch. Remembered on this device; while it is on but this page has not had a click yet, its click
   allows sound instead of turning it off. */
export function CallsToggle() {
  const s = useSound();
  useEffect(() => { hydrate(); }, []);
  const waiting = s.aloud && !s.unlocked;
  return <button type="button" role="switch" aria-checked={s.aloud} className="aloud7" data-calls-toggle="" onClick={() => (waiting ? unlock() : setAloud(!s.aloud))}>
    <span className="track" aria-hidden="true"><span className="knob" /></span>
    <span className="say"><span>Play calls aloud</span>{waiting ? <span className="hint">Click once to allow sound</span> : null}</span>
  </button>;
}

/* ---- words ------------------------------------------------------------------------------------------------- */
const callerOf = (c: Conversation) => c.convener ?? c.participants[0] ?? "";
const calleesOf = (c: Conversation) => c.participants.filter(p => p !== callerOf(c));
const names = (ids: string[]) => { const n = ids.map(agentName); return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n.at(-1)}` : n[0] ?? "the team"; };
/* Each name carries its site ("Compliance Officer · Myer"), so a call across sites names both. */
export const startedText = (c: Conversation) => `${agentName(callerOf(c))} started a call with ${names(calleesOf(c))}`;
const topicOf = (c: Conversation) => c.title || c.summary?.headline || null;
const readMs = (text: string) => Math.min(7_000, Math.max(1_800, 600 + text.length * 48));
const sleep = (ms: number) => new Promise<void>(r => window.setTimeout(r, ms));
function loadSeen(): Set<string> {
  try { const v: unknown = JSON.parse(window.sessionStorage.getItem(SEEN_KEY) ?? "[]"); return new Set(Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []); }
  catch { return new Set(); }
}
function saveSeen(s: Set<string>) { try { window.sessionStorage.setItem(SEEN_KEY, JSON.stringify([...s].slice(-80))); } catch { /* storage blocked */ } }

interface Toast { id: string; call: Conversation; text: string }
interface Play { call: Conversation; shown: number; now: number; done: boolean; voices: boolean | null; voiced: boolean }

export default function CallNotifier() {
  const calls = useCalls();
  const s = useSound();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [playing, setPlaying] = useState<Play | null>(null);
  const [announce, setAnnounce] = useState("");
  const [fs, setFs] = useState<Element | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const primed = useRef(false);
  const queue = useRef<Conversation[]>([]);
  const token = useRef(0);
  const busy = useRef(false);
  const voiced = useRef(false);
  const hold = useRef(false);
  const toastHold = useRef(false);
  const closeTimer = useRef(0);
  const playRef = useRef<(c: Conversation, speak: boolean) => void>(() => {});

  useEffect(() => { hydrate(); }, []);
  /* Any click or key on the page allows sound from then on (the switch handles its own click). */
  useEffect(() => {
    const onInput = (e: Event) => { if (sound.unlocked) return; const t = e.target as Element | null; if (t?.closest?.("[data-calls-toggle]")) return; unlock(); };
    window.addEventListener("click", onInput, true); window.addEventListener("keydown", onInput, true);
    return () => { window.removeEventListener("click", onInput, true); window.removeEventListener("keydown", onInput, true); };
  }, []);
  useEffect(() => { const h = () => setFs(document.fullscreenElement); h(); document.addEventListener("fullscreenchange", h); return () => document.removeEventListener("fullscreenchange", h); }, []);
  /* Realtime, when the shell's bridge has a channel: a conversation line is a nudge to read the calls now. */
  useHudEvents("all", { conversation_line: () => calls.reload() });
  /* Turning "Play calls aloud" off quiets the call being played; its lines go on appearing. */
  useEffect(() => { if (!s.aloud && voiced.current) { voiced.current = false; stopSpeech(); setPlaying(p => (p ? { ...p, voiced: false } : p)); } }, [s.aloud]);
  useEffect(() => () => { token.current++; stopSpeech(); window.clearTimeout(closeTimer.current); }, []);

  const dismiss = useCallback((id: string) => setToasts(t => t.filter(x => x.id !== id)), []);
  const scheduleDismiss = useCallback((id: string) => {
    const tick = () => { if (toastHold.current) { window.setTimeout(tick, 3_000); return; } dismiss(id); };
    window.setTimeout(tick, 12_000);
  }, [dismiss]);

  /* Play one call: reveal each line as it is spoken (or after a reading time without sound), then the next queued. */
  const play = useCallback(async (first: Conversation, speak: boolean) => {
    const my = ++token.current;
    const alive = () => my === token.current;
    busy.current = true; voiced.current = speak;
    window.clearTimeout(closeTimer.current);
    stopSpeech();
    let call = first;
    setPlaying({ call, shown: 0, now: -1, done: false, voices: null, voiced: speak });
    const voices = speechAvailable() ? await loadVoices() : [];
    if (!alive()) return;
    setPlaying(p => (p && alive() ? { ...p, voices: voices.length > 0 } : p));
    await sleep(150);
    let i = 0; let waited = 0;
    while (alive()) {
      if (i >= call.transcript.length) {
        /* A call still under way may add turns: read it again for a while. */
        if (!call.endedAt && call.status !== "ended" && waited < 20_000) {
          await sleep(1_500); waited += 1_500;
          try { const fresh = await api7.call(call.id); if (alive()) { call = { ...fresh, convener: call.convener }; setPlaying(p => (p && alive() ? { ...p, call } : p)); } } catch { /* keep what we have */ }
          continue;
        }
        break;
      }
      const line = call.transcript[i];
      setPlaying(p => (p && alive() ? { ...p, call, shown: i + 1, now: i } : p));
      const t0 = Date.now();
      const spoken = voiced.current && sound.unlocked && voices.length > 0 ? await speakOne(line.speaker, line.text, () => !alive() || !voiced.current) : false;
      if (!alive()) return;
      const rest = spoken ? 250 : readMs(line.text) - (Date.now() - t0);
      if (rest > 0) await sleep(rest);
      i++;
    }
    if (!alive()) return;
    setPlaying(p => (p ? { ...p, call, shown: call.transcript.length, now: -1, done: true } : p));
    busy.current = false;
    await sleep(1_500);
    if (!alive()) return;
    const next = queue.current.shift();
    if (next) { playRef.current(next, sound.aloud); return; }
    const close = () => { if (!alive()) return; if (hold.current) { closeTimer.current = window.setTimeout(close, 3_000); return; } setPlaying(null); };
    closeTimer.current = window.setTimeout(close, 9_000);
  }, []);
  playRef.current = play;

  /* New calls since the last read: a toast each, and with "Play calls aloud" on, a place in the queue. Calls that
     started before this page opened (more than 45 s ago) are history, not news. */
  useEffect(() => {
    const list = calls.data; if (!list) return;
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
    const items = fresh.map(c => ({ id: c.id, call: c, text: startedText(c) }));
    setToasts(t => [...t, ...items].slice(-3));
    items.forEach(x => scheduleDismiss(x.id));
    setAnnounce(items.map(x => x.text).join(". "));
    if (sound.aloud) {
      queue.current = [...queue.current, ...fresh].slice(-3);
      if (!busy.current) { const next = queue.current.shift(); if (next) playRef.current(next, true); }
    }
  }, [calls.data, scheduleDismiss]);

  const listen = (t: Toast) => { dismiss(t.id); if (playing && !playing.done && playing.call.id === t.call.id) return; unlock(); queue.current = queue.current.filter(c => c.id !== t.call.id); play(t.call, true); };
  const stop = () => { token.current++; busy.current = false; voiced.current = false; queue.current = []; stopSpeech(); setPlaying(p => (p ? { ...p, shown: p.call.transcript.length, now: -1, done: true } : p)); };
  const close = () => { stop(); window.clearTimeout(closeTimer.current); setPlaying(null); };

  const ui = <div className="calls7">
    <p className="sr-only" aria-live="polite">{announce}</p>
    {toasts.map(t => <div key={t.id} className="ct7" role="group" aria-label="New call" onPointerEnter={() => { toastHold.current = true; }} onPointerLeave={() => { toastHold.current = false; }} onFocus={() => { toastHold.current = true; }} onBlur={() => { toastHold.current = false; }}>
      <p className="ct-kind"><span className="sig" aria-hidden="true" />Call{t.call.siteIds.length ? ` · ${siteList(t.call.siteIds)}` : ""}<span className="ct-when">{ago(t.call.startedAt)}</span></p>
      <p className="ct-text">{t.text}</p>
      {topicOf(t.call) ? <p className="ct-topic"><JaText text={topicOf(t.call)} /></p> : null}
      <div className="ct-actions">
        <button type="button" className="ct-btn" onClick={() => listen(t)} aria-label={`Listen: ${t.text}`}>Listen</button>
        <button type="button" className="ct-btn quiet" onClick={() => dismiss(t.id)}>Dismiss</button>
      </div>
    </div>)}
    {playing ? <CallPanel p={playing} unlocked={s.unlocked} onStop={stop} onClose={close} onHold={v => { hold.current = v; }} /> : null}
  </div>;
  return fs ? createPortal(ui, fs) : ui;
}

function CallPanel({ p, unlocked, onStop, onClose, onHold }: { p: Play; unlocked: boolean; onStop: () => void; onClose: () => void; onHold: (on: boolean) => void }) {
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [p.shown]);
  const c = p.call;
  const sites = siteList(c.siteIds);
  const topic = topicOf(c);
  const live = !p.done;
  const note = !live ? "" : p.voices === false ? "No voices in this browser, so the lines appear on their own." : !p.voiced ? "Sound is off; the lines appear on their own." : !unlocked ? "Click anywhere on the page to hear the voices." : "";
  return <section className={`cl7 ${live ? "playing" : "done"}`} aria-label={live ? "Live call" : "Call ended"} onPointerEnter={() => onHold(true)} onPointerLeave={() => onHold(false)} onFocus={() => onHold(true)} onBlur={() => onHold(false)}>
    <header className="cl-head">
      <span className="cl-state"><span className="bars7" aria-hidden="true"><i /><i /><i /></span>{live ? "Live call" : "Call ended"}</span>
      {sites ? <span className="cl-sites">{sites}</span> : null}
      <span className="cl-tools">
        {live ? <button type="button" className="cl-btn" onClick={onStop}>Stop</button> : null}
        <button type="button" className="cl-btn" onClick={onClose} aria-label="Close the call panel">Close</button>
      </span>
    </header>
    <p className="cl-who"><strong>{agentName(callerOf(c))}</strong> with <strong>{names(calleesOf(c))}</strong></p>
    {topic ? <p className="cl-topic"><JaText text={topic} /></p> : null}
    <ol className="cl-lines" ref={listRef} aria-live="polite">{c.transcript.slice(0, p.shown).map((t, i) => <li key={i} className={i === p.now ? "now" : ""}>
      <span className="who">{agentName(t.speaker)}</span><span className="txt"><JaText text={t.text} /></span>
    </li>)}</ol>
    <footer className="cl-foot">
      <span>{p.shown} of {c.transcript.length} line{c.transcript.length === 1 ? "" : "s"}</span>
      <Link className="lnk" href={`/app/conversations?id=${encodeURIComponent(c.id)}`}>Open in Conversations</Link>
      {note ? <span className="cl-note">{note}</span> : null}
    </footer>
  </section>;
}
