/* Web Speech API wrapper for the Agents transcript. A voice per agent, chosen deterministically from whatever the
   browser offers, so Atlas always sounds like Atlas on a given machine. Graceful when speechSynthesis is missing. */
export const speechAvailable = () => typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";

function hash(s: string) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

let cache: SpeechSynthesisVoice[] = [];
export function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (!speechAvailable()) return Promise.resolve([]);
  const have = window.speechSynthesis.getVoices();
  if (have.length) { cache = have; return Promise.resolve(have); }
  return new Promise(resolve => {
    const done = () => { cache = window.speechSynthesis.getVoices(); resolve(cache); };
    window.speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 1200);
  });
}
/* English voices preferred; the agent's id picks a stable index. The ten agents of contract 4 are spread across the
   list so each lands on its own voice when ten or more exist (fewer voices are shared in a fixed order); retired ids
   speak with the voice of the agent they map to. */
const ROSTER = ["operator", "director", "myer-manager", "myer-engineer", "myer-compliance", "myer-technician", "bristol-manager", "bristol-engineer", "bristol-compliance", "bristol-technician"];
const RETIRED: Record<string, string> = { atlas: "director", "warden:myer-plant": "myer-engineer", "warden:bristol-pumps": "bristol-engineer", counsel: "bristol-compliance", runner: "myer-technician" };
export function voiceFor(agentId: string, voices = cache): SpeechSynthesisVoice | null {
  const pool = voices.filter(v => /^en/i.test(v.lang));
  const list = pool.length ? pool : voices;
  if (!list.length) return null;
  const idx = ROSTER.indexOf(RETIRED[agentId] ?? agentId);
  if (idx >= 0) return list[(list.length >= ROSTER.length ? idx * Math.floor(list.length / ROSTER.length) : idx) % list.length];
  return list[hash(agentId) % list.length];
}
export interface SpeakHandle { stop: () => void; done: Promise<void> }
export function speak(lines: { agentId: string; text: string }[], onLine?: (index: number) => void): SpeakHandle {
  const synth = window.speechSynthesis;
  synth.cancel();
  let cancelled = false;
  const done = (async () => {
    const voices = await loadVoices();
    for (let i = 0; i < lines.length; i++) {
      if (cancelled) break;
      onLine?.(i);
      await new Promise<void>(resolve => {
        const u = new SpeechSynthesisUtterance(lines[i].text.slice(0, 1200));
        const v = voiceFor(lines[i].agentId, voices); if (v) u.voice = v;
        u.rate = 1.02; u.onend = () => resolve(); u.onerror = () => resolve();
        synth.speak(u);
      });
    }
    onLine?.(-1);
  })();
  return { stop: () => { cancelled = true; synth.cancel(); onLine?.(-1); }, done };
}
