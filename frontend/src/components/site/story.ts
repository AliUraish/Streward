/* The five beats of the hero loop, with the x positions taken from shared/scene.json (scaled 1.6× for the drawing)
   so P-101, P-102, the valves and the tank sit in the same order and spacing as the dashboard twin. */
import scene from "../../../../shared/scene.json";

export type V2 = [number, number];
interface SceneAsset { tag: string; position: number[] }
const assets = scene.components as SceneAsset[];
const xOf = (tag: string) => { const a = assets.find(c => c.tag === tag); if (!a) throw new Error(`no asset ${tag}`); return a.position[0] * 1.6; };

export const X = { p101: xOf("P-101"), p102: xOf("P-102"), v501: xOf("V-501"), v504: xOf("V-504"), tank: xOf("TK-201") };
export const METRES_WEST = Math.round(Math.abs(xOf("P-101") - xOf("P-102")) / 1.6 * 10) / 10;
export const CHECKS = ["scope", "identity", "geometry", "plausibility", "time", "integrity"] as const;

/* Drawing constants (world units; the orthographic camera fits WORLD_W × WORLD_H). */
export const WORLD_W = 17, WORLD_H = 6.2, WORLD_CY = 0.15;
export const PIPE_Y = 1.0, PIPE_R = 0.09, VOLUTE_Y = -0.9, VOLUTE_R = 0.5, EDGE_X = -8.5;
export const GAUGE: V2 = [X.p101 - 1.55, 0.3];

/* Paths the dots travel (2D). */
export const ASK: V2[] = [[EDGE_X, PIPE_Y], [X.p101, PIPE_Y], [X.p101, VOLUTE_Y + VOLUTE_R]];
export const DISPATCH: V2[] = [[EDGE_X, PIPE_Y], [X.p102, PIPE_Y], [X.p102, VOLUTE_Y + VOLUTE_R]];
export const CORRECT: V2[] = [[X.p102, VOLUTE_Y + VOLUTE_R], [X.p102, -0.25], [X.p101, -0.25], [X.p101, VOLUTE_Y + VOLUTE_R]];
export const RETURN: V2[] = [...ASK].reverse();

/* Seconds per beat, then a rest. One calm loop of about sixteen seconds. */
export const DUR = [2.8, 2.8, 3.0, 3.8, 2.8];
export const REST = 1.6;
export const START = DUR.reduce<number[]>((acc, _d, i) => { acc.push(i === 0 ? 0 : acc[i - 1] + DUR[i - 1]); return acc; }, []);
export const TOTAL = START[4] + DUR[4] + REST;
export function loopP(lt: number): number {
  for (let i = 0; i < 5; i++) if (lt < START[i] + DUR[i]) return i + (lt - START[i]) / DUR[i];
  return 5;
}

export const CAPTIONS = ["An agent asks the plant.", "Known. Signed proof returned.", "Unknown. A technician is sent.", `Wrong plate. Corrected ${METRES_WEST} m west.`, "Signed attestation sent back."];

export interface Beat { title: string; text: string }
export const BEATS: Beat[] = [
  { title: "An agent asks.", text: "The call enters the plant through the record, not through a person. It names the site, the tag and the attribute it needs, and whether it may spend money to get it." },
  { title: "Known, with proof.", text: "The record holds a commissioning certificate for P-101, four months old and inside its 365-day life. It comes back with the attestation that signed it, so the agent can cite it." },
  { title: "Unknown, so someone goes.", text: "No pressure reading was ever recorded for P-101. With a budget on the call, Steward opens a work item and sends a task card to a technician. The agent stops and waits, spending nothing." },
  { title: "Wrong plate, refused.", text: `The first photo shows the plate on P-102. Identity fails and the reply says where to look: ${METRES_WEST} m west. The second photo is checked six ways, and passes.` },
  { title: "Signed, and sent back.", text: "2.4 bar, inside 1.5 to 3.5. The fact is written, signed with the server's Ed25519 key, the technician is paid $0.50, and the agent is called back with a proof any other agent can check." },
];

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
export const ease = (t: number) => { const x = clamp01(t); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };

export function along(path: V2[], f: number): V2 {
  const t = clamp01(f);
  const lengths: number[] = []; let total = 0;
  for (let i = 1; i < path.length; i++) { const l = Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]); lengths.push(l); total += l; }
  let d = t * total;
  for (let i = 1; i < path.length; i++) {
    const l = lengths[i - 1];
    if (d <= l || i === path.length - 1) { const u = l === 0 ? 0 : clamp01(d / l); return [lerp(path[i - 1][0], path[i][0], u), lerp(path[i - 1][1], path[i][1], u)]; }
    d -= l;
  }
  return path[path.length - 1];
}
