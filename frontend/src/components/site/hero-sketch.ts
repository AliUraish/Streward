/* A factory elevation in three line weights: equipment outlines, mechanical detail and the supporting pipe rack.
   R3F and the reduced-motion SVG share these segments. Gas interior bounds stay independent of the outer fittings. */
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
  hex(c: V2, r: number) { this.poly(Array.from({ length: 6 }, (_, i): V2 => [c[0] + r * Math.cos(TAU * i / 6), c[1] + r * Math.sin(TAU * i / 6)]), true); }
  tube(a: V2, b: V2, r: number) { if (a[1] === b[1]) { this.line([a[0], a[1] - r], [b[0], b[1] - r]); this.line([a[0], a[1] + r], [b[0], b[1] + r]); } else { this.line([a[0] - r, a[1]], [b[0] - r, b[1]]); this.line([a[0] + r, a[1]], [b[0] + r, b[1]]); } }
  flangeV(x: number, y: number, r: number) {
    for (const s of [-1, 1]) {
      this.rect(x + s * 0.035, y - r, x + s * 0.095, y + r);
      const by = y + s * (r - 0.035);
      this.line([x - 0.16, by], [x + 0.16, by]);
      this.rect(x - 0.145, by - 0.028, x - 0.10, by + 0.028);
      this.rect(x + 0.10, by - 0.028, x + 0.145, by + 0.028);
    }
  }
  flangeH(x: number, y: number, r: number) {
    const local = new Draw(); local.flangeV(0, 0, r);
    for (const [x0, y0, x1, y1] of local.segs) this.line([x - y0, y + x0], [x - y1, y + x1]);
  }
}

export const PUMP_BASE_Y = -1.65;
export function pump(d: Draw, cx: number) {
  const vy = VOLUTE_Y;
  d.rect(cx - 1.55, PUMP_BASE_Y, cx + 0.75, PUMP_BASE_Y + 0.14);                /* base plate */
  d.poly([[cx - 1.62, vy - 0.30], [cx - 1.49, vy - 0.40], [cx - 0.67, vy - 0.40], [cx - 0.56, vy - 0.30], [cx - 0.56, vy + 0.30], [cx - 0.67, vy + 0.40], [cx - 1.49, vy + 0.40], [cx - 1.62, vy + 0.30]], true);
  d.rect(cx - 1.76, vy - 0.30, cx - 1.63, vy + 0.30);                           /* fan cover */
  d.rect(cx - 1.30, vy + 0.40, cx - 0.96, vy + 0.58);                           /* motor terminal box */
  d.rect(cx - 0.57, vy - 0.14, cx - 0.42, vy + 0.14);                           /* shaft coupling */
  for (const fx of [-1.43, -0.84]) d.rect(cx + fx, PUMP_BASE_Y + 0.14, cx + fx + 0.22, vy - 0.40);
  d.circle([cx, vy], VOLUTE_R); d.circle([cx, vy], VOLUTE_R + 0.065); d.circle([cx, vy], 0.16);
  d.rect(cx - 0.22, PUMP_BASE_Y + 0.14, cx + 0.22, vy - VOLUTE_R);              /* pedestal */
  d.tube([cx, vy + VOLUTE_R], [cx, PIPE_Y - PIPE_R], 0.09);                     /* discharge riser */
  d.flangeH(cx, vy + VOLUTE_R + 0.23, 0.21); d.flangeH(cx, PIPE_Y - PIPE_R - 0.23, 0.21);
  d.tube([cx + VOLUTE_R, vy], [cx + 0.90, vy], 0.09); d.flangeV(cx + 0.75, vy, 0.21);
}
export function valve(d: Draw, vx: number) {
  const y = PIPE_Y;
  d.poly([[vx - 0.40, y - 0.13], [vx - 0.30, y - 0.13], [vx - 0.21, y - 0.27], [vx + 0.21, y - 0.27], [vx + 0.30, y - 0.13], [vx + 0.40, y - 0.13], [vx + 0.40, y + 0.13], [vx + 0.28, y + 0.13], [vx + 0.16, y + 0.34], [vx - 0.16, y + 0.34], [vx - 0.28, y + 0.13], [vx - 0.40, y + 0.13]], true);
  d.flangeV(vx - 0.42, y, 0.25); d.flangeV(vx + 0.42, y, 0.25);
  d.rect(vx - 0.23, y + 0.34, vx + 0.23, y + 0.43);                              /* bolted bonnet */
  d.rect(vx - 0.11, y + 0.43, vx + 0.11, y + 0.58);                              /* packing gland */
  d.poly([[vx - 0.18, y + 0.43], [vx - 0.18, y + 0.78], [vx - 0.08, y + 0.91], [vx + 0.08, y + 0.91], [vx + 0.18, y + 0.78], [vx + 0.18, y + 0.43]]); /* yoke */
  d.tube([vx, y + 0.50], [vx, y + 1.02], 0.025);
}
export const WHEEL_Y = PIPE_Y + 1.1, WHEEL_R = 0.26;
export function wheel(d: Draw, c: V2 = [0, 0], rot = 0) {
  d.circle(c, WHEEL_R, 36); d.circle(c, WHEEL_R - 0.035, 36); d.hex(c, 0.05);
  for (let i = 0; i < 5; i++) { const th = rot + (TAU * i) / 5; d.line([c[0] + 0.05 * Math.cos(th), c[1] + 0.05 * Math.sin(th)], [c[0] + (WHEEL_R - 0.035) * Math.cos(th), c[1] + (WHEEL_R - 0.035) * Math.sin(th)]); }
}
export const GAUGE_R = 0.5;
export function gauge(d: Draw, g: V2, riserX: number) {
  d.tube([riserX - 0.09, g[1]], [g[0] + GAUGE_R, g[1]], 0.07);                     /* branch to the riser */
  d.circle(g, GAUGE_R, 36); d.circle(g, GAUGE_R - 0.08, 36);
  for (let i = 0; i <= 20; i++) { const th = Math.PI * 1.25 - (Math.PI * 1.5 * i) / 20; const r0 = GAUGE_R - 0.12, r1 = i % 5 === 0 ? GAUGE_R - 0.26 : i % 2 === 0 ? GAUGE_R - 0.19 : GAUGE_R - 0.16; d.line([g[0] + r0 * Math.cos(th), g[1] + r0 * Math.sin(th)], [g[0] + r1 * Math.cos(th), g[1] + r1 * Math.sin(th)]); }
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
  d.tube([cx, top + r], [cx, PIPE_Y - PIPE_R], 0.09); d.flangeH(cx, top + r + 0.12, 0.20);
  for (const dx of [-0.5, 0.5]) {                                               /* anchored support legs */
    d.rect(cx + dx - 0.055, bottom - 0.30, cx + dx + 0.055, bottom - 0.72);
    d.rect(cx + dx - 0.15, bottom - 0.72, cx + dx + 0.15, bottom - 0.78);
  }
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
  for (const fx of [-7.5, -6.6, -3.45, -0.5, 2.15, 5.45, 7.75]) d.flangeV(fx, PIPE_Y, PIPE_R + 0.14);
  pump(d, X.p101); pump(d, X.p102);
  valve(d, X.v501); valve(d, X.v504);
  gauge(d, GAUGE, X.p101);
  tank(d, X.tank);
  return d.segs;
}

/* Fittings and surface detail stay outside the transparent gas core. */
export function buildFactoryDetails(): Seg[] {
  const d = new Draw();
  d.tube([-8.5, PIPE_Y], [8.5, PIPE_Y], PIPE_R + 0.055);                         /* outer pipe wall */
  for (const x of [-8.1, -5.95, -4.02, -2.65, 0.55, 1.3, 4.7, 7.2, 8.2]) {     /* welded spool seams */
    for (const dx of [-0.018, 0.018]) d.line([x + dx, PIPE_Y - 0.145], [x + dx, PIPE_Y + 0.145]);
  }
  for (const x of [X.p101, X.p102]) {
    d.tube([x, VOLUTE_Y + VOLUTE_R + 0.065], [x, PIPE_Y - 0.14], 0.13);
    d.arc([x - 0.19, PIPE_Y - 0.20], 0.065, 0, Math.PI / 2, 8);                /* reinforced tee */
    d.arc([x + 0.19, PIPE_Y - 0.20], 0.065, Math.PI / 2, Math.PI, 8);
    for (let i = 0; i < 8; i++) {                                              /* casing studs */
      const th = TAU * (i + 0.5) / 8;
      d.hex([x + 0.532 * Math.cos(th), VOLUTE_Y + 0.532 * Math.sin(th)], 0.025);
    }
    for (let i = 0; i < 8; i++) {                                              /* cast motor cooling fins */
      const mx = x - 1.46 + i * 0.108;
      d.line([mx, VOLUTE_Y - 0.36], [mx, VOLUTE_Y + 0.36]);
    }
    for (let i = 0; i < 5; i++) {
      const my = VOLUTE_Y - 0.23 + i * 0.115;
      d.line([x - 1.75, my], [x - 1.65, my]);                                  /* fan-cover vents */
    }
    d.rect(x - 1.23, VOLUTE_Y - 0.13, x - 0.94, VOLUTE_Y + 0.035);             /* motor rating plate */
    for (const mx of [-1.43, -0.72, 0.25, 0.59]) {
      d.hex([x + mx, PUMP_BASE_Y + 0.075], 0.032);
      d.rect(x + mx - 0.055, PUMP_BASE_Y - 0.08, x + mx + 0.055, PUMP_BASE_Y);
    }
    d.line([x - 1.49, PUMP_BASE_Y - 0.10], [x + 0.71, PUMP_BASE_Y - 0.10]);     /* grouted skid */
    d.poly([[x - 1.02, VOLUTE_Y + 0.58], [x - 1.02, VOLUTE_Y + 0.69], [x - 0.76, VOLUTE_Y + 0.69], [x - 0.76, PUMP_BASE_Y - 0.10]]); /* cable gland */
  }
  for (const x of [X.v501, X.v504]) {
    for (const dx of [-0.175, 0.175]) d.hex([x + dx, PIPE_Y + 0.385], 0.035);
    for (let i = 0; i < 7; i++) {
      const y = PIPE_Y + 0.59 + i * 0.05;
      d.line([x - 0.035, y], [x + 0.035, y + 0.025]);                           /* exposed stem threads */
    }
    d.line([x - 0.16, PIPE_Y - 0.21], [x + 0.16, PIPE_Y + 0.21]);              /* gate inside the casting */
  }
  d.flangeV(GAUGE[0] + 0.72, GAUGE[1], 0.13);                                /* instrument isolation union */
  d.rect(GAUGE[0] + 0.92, GAUGE[1] - 0.12, GAUGE[0] + 1.08, GAUGE[1] + 0.12);
  d.line([GAUGE[0] + 1, GAUGE[1] + 0.12], [GAUGE[0] + 1, GAUGE[1] + 0.26]);
  d.line([GAUGE[0] + 0.90, GAUGE[1] + 0.26], [GAUGE[0] + 1.10, GAUGE[1] + 0.26]);
  for (const a of [Math.PI * 0.2, Math.PI * 0.8, Math.PI * 1.5]) d.circle([GAUGE[0] + 0.46 * Math.cos(a), GAUGE[1] + 0.46 * Math.sin(a)], 0.018, 8);

  const { r, top, bottom } = TANK;
  for (const y of [top - 0.12, bottom + 0.12]) {                               /* circumferential vessel bands */
    d.rect(X.tank - r - 0.035, y - 0.045, X.tank + r + 0.035, y + 0.045);
    for (const dx of [-r - 0.025, r + 0.025]) d.hex([X.tank + dx, y], 0.022);
  }
  d.arc([X.tank, top], r - 0.045, 0, Math.PI, 32);                              /* formed head seam */
  d.arc([X.tank, bottom], r - 0.045, Math.PI, TAU, 32);
  d.rect(X.tank - 0.30, -0.92, X.tank + 0.30, -0.76);                         /* vessel data plate */
  for (const dx of [-0.26, 0.26]) d.circle([X.tank + dx, -0.84], 0.015, 8);
  for (let i = 0; i < 6; i++) {
    const y = bottom + 0.48 + i * 0.15;
    d.line([X.tank + r + 0.12, y], [X.tank + r + 0.18, y]);                     /* sight-glass graduations */
  }
  d.poly([[X.tank - 0.53, bottom - 0.65], [X.tank, bottom - 0.30], [X.tank + 0.53, bottom - 0.65]]); /* leg bracing */
  return d.segs;
}

/* Recessive factory structure: real pipe supports and service conduits, not a decorative grid. */
export function buildFactoryContext(): Seg[] {
  const d = new Draw();
  const beamY = 2.96, floorY = -2.78;
  d.rect(-8.5, beamY - 0.12, 8.5, beamY);
  for (const x of [-7.8, 0.35, 7.95]) {
    d.rect(x - 0.065, floorY, x + 0.065, beamY - 0.12);
    d.line([x - 0.11, floorY], [x - 0.11, beamY - 0.12]);
    d.rect(x - 0.22, floorY - 0.045, x + 0.22, floorY + 0.045);
    for (const s of [-1, 1]) d.line([x + s * 0.07, beamY - 0.52], [x + s * 0.42, beamY - 0.12]);
  }
  for (const x of [-7.0, -2.95, 1.35, 5.05]) {
    d.tube([x, PIPE_Y + 0.25], [x, beamY - 0.12], 0.018);                      /* threaded hanger rods */
    d.arc([x, PIPE_Y], 0.19, Math.PI, TAU, 16);
    d.line([x - 0.19, PIPE_Y], [x - 0.19, PIPE_Y + 0.20]);
    d.line([x + 0.19, PIPE_Y], [x + 0.19, PIPE_Y + 0.20]);
    d.line([x - 0.25, PIPE_Y + 0.20], [x + 0.25, PIPE_Y + 0.20]);
    d.hex([x, PIPE_Y + 0.25], 0.045);
  }
  for (const y of [2.48, 2.57]) d.line([-8.5, y], [8.5, y]);                   /* overhead electrical raceway */
  for (const x of [-6.25, -3.35, -0.45, 2.45, 5.35, 7.5]) d.line([x, 2.48], [x, 2.57]);
  d.poly([[-8.5, -2.35], [-0.7, -2.35], [-0.56, -2.21], [-0.56, -1.95]]);      /* cable tray behind the skids */
  d.poly([[-8.5, -2.43], [-0.65, -2.43], [-0.48, -2.26], [-0.48, -1.95]]);
  for (const x of [-7.0, -5.5, -4.0, -2.5, -1.0]) d.line([x, -2.35], [x, -2.43]);
  return d.segs;
}
export function toArray(segs: Seg[]): Float32Array {
  const arr = new Float32Array(segs.length * 6);
  segs.forEach((s, i) => { arr[i * 6] = s[0]; arr[i * 6 + 1] = s[1]; arr[i * 6 + 2] = 0; arr[i * 6 + 3] = s[2]; arr[i * 6 + 4] = s[3]; arr[i * 6 + 5] = 0; });
  return arr;
}
