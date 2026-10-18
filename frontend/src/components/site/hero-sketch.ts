/* The hero drawing as a list of 2D segments: one pipe run, two pumps (P-101 and P-102), two valves with handwheels,
   one gauge with a dial, one tank. Clean line work, generous spacing. The R3F scene and the static SVG both draw it. */
import { GAUGE, PIPE_R, PIPE_Y, VOLUTE_R, VOLUTE_Y, X, type V2 } from "./story";

export type Seg = [number, number, number, number];
const TAU = Math.PI * 2;

export class Draw {
  segs: Seg[] = [];
  line(a: V2, b: V2) { this.segs.push([a[0], a[1], b[0], b[1]]); }
  poly(pts: V2[], closed = false) { for (let i = 1; i < pts.length; i++) this.line(pts[i - 1], pts[i]); if (closed) this.line(pts[pts.length - 1], pts[0]); }
  rect(x0: number, y0: number, x1: number, y1: number) { this.poly([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], true); }
  arc(c: V2, r: number, from: number, to: number, n = 24) { const pts: V2[] = []; for (let i = 0; i <= n; i++) { const th = from + ((to - from) * i) / n; pts.push([c[0] + r * Math.cos(th), c[1] + r * Math.sin(th)]); } this.poly(pts); }
  circle(c: V2, r: number, n = 32) { this.arc(c, r, 0, TAU, n); }
  tube(a: V2, b: V2, r: number) { if (a[1] === b[1]) { this.line([a[0], a[1] - r], [b[0], b[1] - r]); this.line([a[0], a[1] + r], [b[0], b[1] + r]); } else { this.line([a[0] - r, a[1]], [b[0] - r, b[1]]); this.line([a[0] + r, a[1]], [b[0] + r, b[1]]); } }
  flangeV(x: number, y: number, r: number) { for (const d of [-0.07, 0.07]) this.line([x + d, y - r], [x + d, y + r]); }
  flangeH(x: number, y: number, r: number) { for (const d of [-0.07, 0.07]) this.line([x - r, y + d], [x + r, y + d]); }
}

export const PUMP_BASE_Y = -1.65;
export function pump(d: Draw, cx: number) {
  const vy = VOLUTE_Y;
  d.rect(cx - 1.55, PUMP_BASE_Y, cx + 0.75, PUMP_BASE_Y + 0.14);                /* base plate */
  d.rect(cx - 1.5, vy - 0.42, cx - 0.55, vy + 0.42);                          /* motor */
  for (let i = 1; i <= 3; i++) d.line([cx - 1.5 + i * 0.24, vy - 0.42], [cx - 1.5 + i * 0.24, vy + 0.42]); /* fins */
  d.line([cx - 1.5, vy], [cx - 1.75, vy]); d.rect(cx - 1.85, vy - 0.18, cx - 1.75, vy + 0.18);       /* fan cowl */
  d.line([cx - 0.55, vy], [cx - VOLUTE_R, vy]);                                  /* shaft */
  d.rect(cx - 0.9, PUMP_BASE_Y + 0.14, cx - 0.55, vy - 0.42);                   /* motor foot */
  d.circle([cx, vy], VOLUTE_R); d.circle([cx, vy], 0.16);                        /* volute and eye */
  d.rect(cx - 0.22, PUMP_BASE_Y + 0.14, cx + 0.22, vy - VOLUTE_R);              /* pedestal */
  d.tube([cx, vy + VOLUTE_R], [cx, PIPE_Y - PIPE_R], 0.09);                     /* discharge riser */
  d.flangeV(cx, vy + VOLUTE_R + 0.2, 0.18); d.flangeV(cx, PIPE_Y - PIPE_R - 0.2, 0.18);
  d.tube([cx + VOLUTE_R, vy], [cx + 0.75, vy], 0.09); d.flangeH(cx + 0.68, vy, 0.18);  /* suction stub */
}
export function valve(d: Draw, vx: number) {
  d.poly([[vx - 0.36, PIPE_Y + 0.3], [vx - 0.36, PIPE_Y - 0.3], [vx, PIPE_Y]], true);   /* body */
  d.poly([[vx + 0.36, PIPE_Y + 0.3], [vx + 0.36, PIPE_Y - 0.3], [vx, PIPE_Y]], true);
  d.line([vx, PIPE_Y + 0.3], [vx, PIPE_Y + 0.85]);                                 /* stem */
  d.rect(vx - 0.12, PIPE_Y + 0.3, vx + 0.12, PIPE_Y + 0.5);                        /* bonnet */
}
export const WHEEL_Y = PIPE_Y + 1.1, WHEEL_R = 0.26;
export function wheel(d: Draw, c: V2 = [0, 0], rot = 0) {
  d.circle(c, WHEEL_R, 24); d.circle(c, 0.05, 8);
  for (let i = 0; i < 4; i++) { const th = rot + (TAU * i) / 4; d.line([c[0] + 0.05 * Math.cos(th), c[1] + 0.05 * Math.sin(th)], [c[0] + WHEEL_R * Math.cos(th), c[1] + WHEEL_R * Math.sin(th)]); }
}
export const GAUGE_R = 0.5;
export function gauge(d: Draw, g: V2, riserX: number) {
  d.tube([riserX - 0.09, g[1]], [g[0] + GAUGE_R, g[1]], 0.07);                     /* branch to the riser */
  d.circle(g, GAUGE_R, 36); d.circle(g, GAUGE_R - 0.08, 36);
  for (let i = 0; i <= 8; i++) { const th = Math.PI * 1.25 - (Math.PI * 1.5 * i) / 8; const r0 = GAUGE_R - 0.12, r1 = i % 4 === 0 ? GAUGE_R - 0.24 : GAUGE_R - 0.18; d.line([g[0] + r0 * Math.cos(th), g[1] + r0 * Math.sin(th)], [g[0] + r1 * Math.cos(th), g[1] + r1 * Math.sin(th)]); }
  d.circle(g, 0.04, 8);
}
export const NEEDLE_LEN = GAUGE_R - 0.16;
export const barAngle = (bar: number) => Math.PI * 1.25 - (bar / 4) * Math.PI * 1.5;
export function needle(d: Draw, g: V2, bar: number) { const th = barAngle(bar); d.line([g[0] - 0.08 * Math.cos(th), g[1] - 0.08 * Math.sin(th)], [g[0] + NEEDLE_LEN * Math.cos(th), g[1] + NEEDLE_LEN * Math.sin(th)]); }

export const TANK = { r: 0.72, bottom: -1.65, top: 0.0 };
// Shared by the volume shader and the SVG fallback so every pipe interior has the same bounds.
export const GAS_TUBES: { a: V2; b: V2; r: number }[] = [
  { a: [-8.5, PIPE_Y], b: [8.5, PIPE_Y], r: PIPE_R },
  ...[X.p101, X.p102].flatMap(x => [
    { a: [x, VOLUTE_Y] as V2, b: [x, PIPE_Y] as V2, r: 0.09 },
    { a: [x, VOLUTE_Y] as V2, b: [x + 0.75, VOLUTE_Y] as V2, r: 0.09 },
  ]),
  { a: [X.tank, TANK.top], b: [X.tank, PIPE_Y], r: 0.09 },
  { a: [GAUGE[0] + 0.5, GAUGE[1]], b: [X.p101, GAUGE[1]], r: 0.07 },
  ...[X.v501, X.v504].map(x => ({ a: [x, PIPE_Y] as V2, b: [x, PIPE_Y + 0.5] as V2, r: 0.06 })),
];
export function tank(d: Draw, cx: number) {
  const { r, bottom, top } = TANK;
  d.line([cx - r, bottom], [cx - r, top]); d.line([cx + r, bottom], [cx + r, top]);
  d.line([cx - r, bottom], [cx + r, bottom]);
  d.arc([cx, top], r, 0, Math.PI, 24);                                            /* dome */
  d.arc([cx, bottom], r, Math.PI, TAU, 24);                                       /* dished bottom */
  d.tube([cx, top + r], [cx, PIPE_Y - PIPE_R], 0.09); d.flangeV(cx, top + r + 0.12, 0.18);  /* top nozzle */
  for (const dx of [-0.5, 0.5]) d.line([cx + dx, bottom - 0.3], [cx + dx, bottom - 0.72]);  /* legs */
  d.line([cx - 0.62, bottom - 0.72], [cx + 0.62, bottom - 0.72]);
  d.rect(cx + r + 0.12, bottom + 0.4, cx + r + 0.22, top - 0.3);                 /* level glass */
  d.line([cx + r, bottom + 0.4], [cx + r + 0.12, bottom + 0.4]); d.line([cx + r, top - 0.3], [cx + r + 0.12, top - 0.3]);
}
export const LEVEL = { min: TANK.bottom + 0.5, max: TANK.top - 0.35 };
export function level(d: Draw, cx: number, y: number) { d.line([cx - TANK.r + 0.08, y], [cx + TANK.r - 0.08, y]); }

export function tick(d: Draw, c: V2, s = 0.17) { d.line([c[0] - s, c[1]], [c[0] - s * 0.3, c[1] - s * 0.75]); d.line([c[0] - s * 0.3, c[1] - s * 0.75], [c[0] + s, c[1] + s * 0.7]); }
export function cross(d: Draw, c: V2, s = 0.16) { d.line([c[0] - s, c[1] - s], [c[0] + s, c[1] + s]); d.line([c[0] - s, c[1] + s], [c[0] + s, c[1] - s]); }
export function packet(d: Draw, c: V2) { d.rect(c[0] - 0.19, c[1] - 0.13, c[0] + 0.19, c[1] + 0.13); d.line([c[0] - 0.19, c[1] + 0.13], [c[0], c[1] - 0.02]); d.line([c[0] + 0.19, c[1] + 0.13], [c[0], c[1] - 0.02]); }

/* Where the six ticks sit: an arc over P-101. */
export const TICKS: V2[] = [0.93, 0.78, 0.64, 0.36, 0.22, 0.07].map(k => { const th = Math.PI * k; return [X.p101 + 1.25 * Math.cos(th), VOLUTE_Y + 0.1 + 1.0 * Math.sin(th)]; });
export const CROSS_AT: V2 = [X.p102 + 0.55, VOLUTE_Y + 0.75];

/* The still part of the drawing. */
export function buildStatic(): Seg[] {
  const d = new Draw();
  d.tube([-8.5, PIPE_Y], [8.5, PIPE_Y], PIPE_R);                                  /* the pipe run */
  for (const fx of [-6.6, 6.0]) d.flangeV(fx, PIPE_Y, PIPE_R + 0.1);
  pump(d, X.p101); pump(d, X.p102);
  valve(d, X.v501); valve(d, X.v504);
  gauge(d, GAUGE, X.p101);
  tank(d, X.tank);
  return d.segs;
}
export function toArray(segs: Seg[]): Float32Array {
  const arr = new Float32Array(segs.length * 6);
  segs.forEach((s, i) => { arr[i * 6] = s[0]; arr[i * 6 + 1] = s[1]; arr[i * 6 + 2] = 0; arr[i * 6 + 3] = s[2]; arr[i * 6 + 4] = s[3]; arr[i * 6 + 5] = 0; });
  return arr;
}
