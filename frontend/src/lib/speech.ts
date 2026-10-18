/* Web Speech API wrapper for transcripts and calls. A voice per agent, chosen deterministically from whatever the
   browser offers, so each agent always sounds like itself on a given machine. Graceful when speechSynthesis is missing. */
export const speechAvailable = () => typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";

function hash(s: string) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

let cache: SpeechSynthesisVoice[] = [];
let watching = false;
export function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (!speechAvailable()) return Promise.resolve([]);
  /* Some browsers add their network voices a moment after the local ones; keep the list current. */
  if (!watching) { watching = true; window.speechSynthesis.addEventListener("voiceschanged", () => { cache = window.speechSynthesis.getVoices(); }); }
  const have = window.speechSynthesis.getVoices();
  if (have.length) { cache = have; return Promise.resolve(have); }
  return new Promise(resolve => {
    const done = () => { cache = window.speechSynthesis.getVoices(); resolve(cache); };
    window.speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1200);
  });
}
/* Voices (REALITY-CONTRACT-7.md section 7): a distinct voice per agent from the best the browser offers (names with
   Natural, Neural, Premium, Enhanced or Google first; novelty voices never), in the accent of the agent's site (Myer
   en-AU, Bristol en-GB, Tomioka en-US; the Director and anyone else en-US), ja-JP for a line with Japanese in it, and a
   slight pitch and rate per role. Agents pick in a fixed order, so the compliance officers and engineers, who talk
   most on calls, get first choice; when a site's accent runs out of unused voices the nearest accent is used, and
   only when every voice is taken is one shared, with a pitch offset so the two still sound apart. Retired ids speak
   with the voice of the agent they map to. */
const RETIRED: Record<string, string> = { atlas: "director", "warden:myer-plant": "myer-engineer", "warden:bristol-pumps": "bristol-engineer", counsel: "bristol-compliance", runner: "myer-technician" };
const NOVELTY = /\b(albert|bad news|bahh|bells|boing|bubbles|cellos|deranged|good news|hysterical|jester|organ|superstar|trinoids|whisper|wobble|zarvox|junior|ralph|kathy|princess|fred)\b/i;
const ROBOTIC = /\b(eddy|flo|grandma|grandpa|reed|rocko|sandy|shelley)\b/i;
const JAPANESE = /[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]/;
export const hasJapanese = (text: string) => JAPANESE.test(text);
const langOf = (v: SpeechSynthesisVoice) => v.lang.replace(/_/g, "-").toLowerCase();
const keyOf = (v: SpeechSynthesisVoice) => v.voiceURI || `${v.name}|${v.lang}`;
/* Robotic voices rank below any other English voice, accent or not: they are used only when nothing better is free. */
const quality = (v: SpeechSynthesisVoice) => (/natural|neural/i.test(v.name) ? 6 : 0) + (/premium/i.test(v.name) ? 5 : 0) + (/enhanced/i.test(v.name) ? 4 : 0)
  + (/google/i.test(v.name) ? 3 : 0) + (v.localService === false ? 1 : 0) - (ROBOTIC.test(v.name) ? 9 : 0);
const localeOf = (id: string) => id.startsWith("myer-") ? "en-au" : id.startsWith("bristol-") ? "en-gb" : "en-us";
const NEAR: Record<string, string[]> = { "en-au": ["en-nz", "en-gb", "en-ie", "en-za"], "en-gb": ["en-ie", "en-au", "en-nz", "en-za"], "en-us": ["en-ca", "en-gb", "en-au", "en-ie"] };
/* How well a voice suits a locale: its own accent first, then the nearest, then any English. */
const fit = (locale: string, v: SpeechSynthesisVoice) => { const l = langOf(v); if (l === locale) return 8; const i = (NEAR[locale] ?? []).indexOf(l); return i >= 0 ? 3 - i * 0.5 : l.startsWith("en") ? 1 : -100; };
const ROLE_TUNE: Record<string, { pitch: number; rate: number }> = {
  director: { pitch: 0.9, rate: 0.96 }, manager: { pitch: 0.95, rate: 0.98 }, engineer: { pitch: 1, rate: 1.04 },
  compliance: { pitch: 1.05, rate: 0.99 }, technician: { pitch: 1.1, rate: 1.06 },
};
const roleOfId = (id: string) => id === "director" ? "director" : id.match(/-(manager|engineer|compliance|technician)$/)?.[1] ?? "";
const ORDER = ["director", ...["compliance", "engineer", "manager"].flatMap(r => ["myer", "bristol", "tomioka"].map(s => `${s}-${r}`)),
  "myer-technician", "bristol-technician", "tomioka-technician", "operator", "dispatch"];
const offsetOf = (id: string) => ((hash(id) % 5) - 2) * 0.07;
interface Assigned { voice: SpeechSynthesisVoice; shared: boolean }
let table: { sig: string; map: Map<string, Assigned>; ja: SpeechSynthesisVoice[] } | null = null;
function assignment(voices: SpeechSynthesisVoice[]) {
  const sig = voices.map(keyOf).join(",");
  if (table && table.sig === sig) return table;
  const pool = voices.filter(v => !NOVELTY.test(v.name));
  const ranked = (locale: string) => pool.filter(v => fit(locale, v) > 0).sort((a, b) => fit(locale, b) + quality(b) - (fit(locale, a) + quality(a)) || a.name.localeCompare(b.name));
  const used = new Set<string>(); const map = new Map<string, Assigned>();
  for (const id of ORDER) {
    const cands = ranked(localeOf(id));
    const free = cands.find(v => !used.has(keyOf(v)));
    if (free) { used.add(keyOf(free)); map.set(id, { voice: free, shared: false }); }
    else if (cands.length) map.set(id, { voice: cands[hash(id) % Math.min(cands.length, 3)], shared: true });
  }
  const ja = pool.filter(v => langOf(v).startsWith("ja")).sort((a, b) => quality(b) - quality(a) || a.name.localeCompare(b.name));
  table = { sig, map, ja };
  return table;
}
export interface VoicePick { voice: SpeechSynthesisVoice | null; lang: string; pitch: number; rate: number }
/* The voice, language, pitch and rate an agent speaks this text with. */
export function voicePick(agentId: string, text = "", voices = cache): VoicePick {
  const id = RETIRED[agentId] ?? agentId;
  const tune = ROLE_TUNE[roleOfId(id)] ?? { pitch: 1, rate: 1 };
  const t = assignment(voices);
  const clampP = (p: number) => Math.max(0.6, Math.min(1.5, p));
  if (hasJapanese(text) && t.ja.length) {
    const team = ["tomioka-compliance", "tomioka-engineer", "tomioka-manager", "tomioka-technician"];
    const i = team.indexOf(id); const k = (i >= 0 ? i : hash(id)) % t.ja.length;
    return { voice: t.ja[k], lang: t.ja[k].lang, pitch: clampP(tune.pitch + (t.ja.length < 4 ? offsetOf(id) : 0)), rate: tune.rate * 0.96 };
  }
  let hit = t.map.get(id) ?? null;
  if (!hit) { const cands = voices.filter(v => !NOVELTY.test(v.name) && fit(localeOf(id), v) > 0); if (cands.length) hit = { voice: cands[hash(id) % cands.length], shared: true }; }
  return { voice: hit?.voice ?? null, lang: hit?.voice.lang ?? (hasJapanese(text) ? "ja-JP" : localeOf(id).replace(/-(\w+)$/, (_m, c: string) => `-${c.toUpperCase()}`)), pitch: clampP(tune.pitch + (hit?.shared ? offsetOf(id) : 0)), rate: tune.rate };
}
export function voiceFor(agentId: string, voices = cache): SpeechSynthesisVoice | null { return voicePick(agentId, "", voices).voice; }

/* Sentences of at most about 220 characters: some browsers cut a long utterance off part-way. */
function chunks(text: string): string[] {
  const parts = text.slice(0, 1500).match(/[^.!?。！？]+[.!?。！？]*\s*/g) ?? [text];
  const out: string[] = [];
  for (const p of parts) { const last = out.at(-1); if (last !== undefined && last.length + p.length <= 220) out[out.length - 1] = last + p; else out.push(p); }
  return out.map(s => s.trim()).filter(Boolean);
}
/* Speak one line in the agent's voice. Resolves true when it was spoken through, false when it was cancelled, failed or
   the browser cannot speak; a watchdog moves on (and clears a stuck queue) if the browser never reports the end. The
   utterance being spoken is held here, since some browsers drop the end event of one that was garbage collected. */
let speaking: SpeechSynthesisUtterance | null = null;
export async function speakOne(agentId: string, text: string, cancelled: () => boolean = () => false): Promise<boolean> {
  if (!speechAvailable() || !text.trim()) return false;
  const synth = window.speechSynthesis;
  const voices = await loadVoices();
  const pick = voicePick(agentId, text, voices);
  for (const part of chunks(text)) {
    if (cancelled()) return false;
    const ok = await new Promise<boolean>(resolve => {
      const u = new SpeechSynthesisUtterance(part);
      if (pick.voice) u.voice = pick.voice;
      u.lang = pick.lang; u.pitch = pick.pitch; u.rate = pick.rate;
      let settled = false; let watch = 0;
      const finish = (v: boolean) => { if (settled) return; settled = true; window.clearTimeout(watch); if (speaking === u) speaking = null; resolve(v); };
      watch = window.setTimeout(() => { if (speaking === u) synth.cancel(); finish(false); }, 4_000 + part.length * 110);
      u.onend = () => finish(true); u.onerror = () => finish(false);
      speaking = u;
      synth.speak(u);
    });
    if (!ok) return false;
  }
  return !cancelled();
}
/* Browsers make no sound until the page has had a click; call this inside one (a silent utterance unlocks the
   browsers that need speak() itself to run in a gesture). */
export function unlockSpeech() {
  if (!speechAvailable()) return;
  try { const u = new SpeechSynthesisUtterance(" "); u.volume = 0; window.speechSynthesis.speak(u); } catch { /* nothing to unlock */ }
  void loadVoices();
}
export function stopSpeech() { if (speechAvailable()) window.speechSynthesis.cancel(); }
export interface SpeakHandle { stop: () => void; done: Promise<void> }
export function speak(lines: { agentId: string; text: string }[], onLine?: (index: number) => void): SpeakHandle {
  const synth = window.speechSynthesis;
  synth.cancel();
  let cancelled = false;
  const done = (async () => {
    await loadVoices();
    for (let i = 0; i < lines.length; i++) {
      if (cancelled) break;
      onLine?.(i);
      await speakOne(lines[i].agentId, lines[i].text.slice(0, 1200), () => cancelled);
    }
    if (!cancelled) onLine?.(-1);
  })();
  return { stop: () => { cancelled = true; synth.cancel(); onLine?.(-1); }, done };
}
