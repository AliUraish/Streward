/**
 * Orbit + fly camera with damping, independent of the engine.
 *
 * The rig keeps a pivot (target), yaw, pitch and distance. User input moves the desired pose and the
 * current pose follows it with exponential damping. Programmatic moves (focus, reset, orbit) run as
 * eased tweens on the current pose; any user input interrupts them.
 */
import type { Vec3Tuple } from './types';

export interface RigPose { target: Vec3Tuple; yaw: number; pitch: number; distance: number }

/**
 * How a tween moves the camera:
 * - `path`: the camera position and the pivot move in straight lines (focus, reset, translate);
 * - `look`: the camera stays put and turns (first-person turn);
 * - `orbit`: the pivot stays put and the camera swings around it at the interpolated distance.
 */
export type TweenKind = 'path' | 'look' | 'orbit';
/** `done(true)` when a move completes, `done(false)` when it is interrupted or replaced. */
export type MoveDone = (completed: boolean) => void;
interface Tween { from: RigPose; to: RigPose; start: number; duration: number; kind: TweenKind; done?: MoveDone }
interface Orbit { remaining: number; speed: number; done?: MoveDone }

const DEG = Math.PI / 180;
const PITCH_LIMIT = 85;
const MIN_DISTANCE = 0.25;
const MAX_DISTANCE = 80;

export const clone = (p: RigPose): RigPose => ({ target: [...p.target] as Vec3Tuple, yaw: p.yaw, pitch: p.pitch, distance: p.distance });
const wrap = (a: number) => ((a + 180) % 360 + 360) % 360 - 180;
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function forwardOf(yaw: number, pitch: number): Vec3Tuple {
  const cy = Math.cos(yaw * DEG), sy = Math.sin(yaw * DEG), cp = Math.cos(pitch * DEG), sp = Math.sin(pitch * DEG);
  return [-sy * cp, sp, -cy * cp];
}

/** Pose that looks from `position` at `target`. */
export function poseLookingAt(position: Vec3Tuple, target: Vec3Tuple, distance?: number): RigPose {
  const d: Vec3Tuple = [target[0] - position[0], target[1] - position[1], target[2] - position[2]];
  const len = Math.hypot(d[0], d[1], d[2]) || 1;
  const n: Vec3Tuple = [d[0] / len, d[1] / len, d[2] / len];
  const pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, Math.asin(Math.max(-1, Math.min(1, n[1]))) / DEG));
  const yaw = Math.atan2(-n[0], -n[2]) / DEG;
  const dist = distance ?? len;
  // keep the camera where it is: move the pivot along the view direction when a distance is given
  const f = forwardOf(yaw, pitch);
  const pivot: Vec3Tuple = [position[0] + f[0] * dist, position[1] + f[1] * dist, position[2] + f[2] * dist];
  return { target: pivot, yaw, pitch, distance: dist };
}

export function positionOf(p: RigPose): Vec3Tuple {
  const f = forwardOf(p.yaw, p.pitch);
  return [p.target[0] - f[0] * p.distance, p.target[1] - f[1] * p.distance, p.target[2] - f[2] * p.distance];
}

export interface RigInputOptions {
  /** Vertical field of view, used to scale panning to the pivot distance. */
  fov: number;
  onClick?(x: number, y: number, event: PointerEvent): void;
  onDoubleClick?(x: number, y: number): void;
  onInteract?(): void;
}

export class CameraRig {
  current: RigPose;
  desired: RigPose;
  moveSpeed = 2.2;
  /** Damping rate for user input, per second. Higher is snappier. */
  rate = 9;
  /** While locked (an agent is driving), pointer, wheel and key input are ignored. */
  locked = false;
  private tween: Tween | null = null;
  private orbit: Orbit | null = null;
  private keys = new Set<string>();
  private dirty = true;
  private disposers: (() => void)[] = [];

  constructor(pose: RigPose) {
    this.current = clone(pose);
    this.desired = clone(pose);
  }

  get animating() { return !!this.tween || !!this.orbit; }

  /** Jump without animation. */
  set(pose: RigPose) {
    const prev = this.tween, prevOrbit = this.orbit;
    this.tween = null; this.orbit = null;
    prev?.done?.(false);
    prevOrbit?.done?.(false);
    this.current = clone(pose); this.desired = clone(pose);
    this.dirty = true;
  }

  /** Tween to `pose` over `duration` seconds of wall-clock time (frame-rate independent). */
  animateTo(pose: RigPose, duration: number, done?: MoveDone, kind: TweenKind = 'path') {
    const prev = this.tween, prevOrbit = this.orbit;
    this.tween = null; this.orbit = null;
    prev?.done?.(false);
    prevOrbit?.done?.(false);
    if (duration <= 0) { this.set(pose); done?.(true); return; }
    const to = clone(pose);
    to.yaw = this.current.yaw + wrap(to.yaw - this.current.yaw);
    this.tween = { from: clone(this.current), to, start: performance.now(), duration, kind, done };
    this.dirty = true;
  }

  /** Promise form of animateTo; resolves when the tween ends or is replaced. */
  animate(pose: RigPose, duration: number, kind: TweenKind = 'path') {
    return new Promise<boolean>((resolve) => this.animateTo(pose, duration, resolve, kind));
  }

  /** Orbit the current pivot by `degrees` at `speed` degrees per second. */
  orbitBy(degrees: number, speed: number, done?: MoveDone) {
    const prev = this.tween, prevOrbit = this.orbit;
    this.tween = null; this.orbit = null;
    prev?.done?.(false);
    prevOrbit?.done?.(false);
    this.desired = clone(this.current);
    this.orbit = { remaining: degrees, speed, done };
    this.dirty = true;
  }

  stopAnimation() {
    if (this.tween || this.orbit) {
      const tw = this.tween, o = this.orbit;
      this.tween = null; this.orbit = null;
      this.desired = clone(this.current);
      tw?.done?.(false);
      o?.done?.(false);
    }
  }

  /** True when the camera has stopped: no tween, no orbit and the damped pose has caught up. */
  get settled() {
    if (this.tween || this.orbit || this.keys.size) return false;
    const c = this.current, d = this.desired;
    return Math.abs(c.yaw - d.yaw) + Math.abs(c.pitch - d.pitch) + Math.abs(c.distance - d.distance)
      + Math.abs(c.target[0] - d.target[0]) + Math.abs(c.target[1] - d.target[1]) + Math.abs(c.target[2] - d.target[2]) < 1e-4;
  }

  /** Pose shifted by a world-space vector (camera and pivot together). */
  translated(v: Vec3Tuple): RigPose {
    const p = clone(this.current);
    for (let i = 0; i < 3; i++) p.target[i] += v[i];
    return p;
  }

  /**
   * Pose turned in place: the camera keeps its position. Positive yaw turns right (clockwise seen
   * from above), positive pitch looks up.
   */
  turned(yawDeg: number, pitchDeg: number): RigPose {
    const pos = positionOf(this.current);
    const yaw = this.current.yaw - yawDeg;
    const pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, this.current.pitch + pitchDeg));
    const f = forwardOf(yaw, pitch);
    const d = this.current.distance;
    return { target: [pos[0] + f[0] * d, pos[1] + f[1] * d, pos[2] + f[2] * d], yaw, pitch, distance: d };
  }

  /** Camera axes for the current pose: forward, right and up (unit vectors, world frame). */
  axes(): { forward: Vec3Tuple; right: Vec3Tuple; up: Vec3Tuple } {
    const y = this.current.yaw * DEG, p = this.current.pitch * DEG;
    return {
      forward: forwardOf(this.current.yaw, this.current.pitch),
      right: [Math.cos(y), 0, -Math.sin(y)],
      up: [Math.sin(y) * Math.sin(p), Math.cos(p), Math.cos(y) * Math.sin(p)],
    };
  }

  /** Advance one frame. Returns true when the camera moved. */
  update(dt: number): boolean {
    let moved = this.dirty;
    this.dirty = false;
    dt = Math.min(dt, 0.1);

    if (this.keys.size) {
      const f = forwardOf(this.current.yaw, this.current.pitch);
      const r: Vec3Tuple = [Math.cos(this.current.yaw * DEG), 0, -Math.sin(this.current.yaw * DEG)];
      const k = this.keys;
      const ax = (+k.has('d') + +k.has('arrowright')) - (+k.has('a') + +k.has('arrowleft'));
      const az = (+k.has('w') + +k.has('arrowup')) - (+k.has('s') + +k.has('arrowdown'));
      const ay = +k.has('e') - +k.has('q');
      const speed = this.moveSpeed * (k.has('shift') ? 3 : 1) * dt;
      if (ax || ay || az) {
        this.stopAnimation();
        for (let i = 0; i < 3; i++) this.desired.target[i] += (f[i] * az + r[i] * ax + (i === 1 ? ay : 0)) * speed;
      }
    }

    if (this.tween) {
      const tw = this.tween;
      const t = Math.min(1, (performance.now() - tw.start) / (tw.duration * 1000));
      const e = easeInOut(t);
      const lerp = (a: number, b: number) => a + (b - a) * e;
      if (tw.kind === 'path') {
        // interpolate the camera position and the pivot so the path does not swing through walls
        const pa = positionOf(tw.from), pb = positionOf(tw.to);
        const pos: Vec3Tuple = [lerp(pa[0], pb[0]), lerp(pa[1], pb[1]), lerp(pa[2], pb[2])];
        const tgt: Vec3Tuple = [lerp(tw.from.target[0], tw.to.target[0]), lerp(tw.from.target[1], tw.to.target[1]), lerp(tw.from.target[2], tw.to.target[2])];
        const look = poseLookingAt(pos, tgt);
        this.current = { target: tgt, yaw: look.yaw, pitch: look.pitch, distance: look.distance };
      } else if (tw.kind === 'look') {
        const pa = positionOf(tw.from), pb = positionOf(tw.to);
        const pos: Vec3Tuple = [lerp(pa[0], pb[0]), lerp(pa[1], pb[1]), lerp(pa[2], pb[2])];
        const yaw = lerp(tw.from.yaw, tw.to.yaw), pitch = lerp(tw.from.pitch, tw.to.pitch), distance = lerp(tw.from.distance, tw.to.distance);
        const f = forwardOf(yaw, pitch);
        this.current = { target: [pos[0] + f[0] * distance, pos[1] + f[1] * distance, pos[2] + f[2] * distance], yaw, pitch, distance };
      } else {
        const tgt: Vec3Tuple = [lerp(tw.from.target[0], tw.to.target[0]), lerp(tw.from.target[1], tw.to.target[1]), lerp(tw.from.target[2], tw.to.target[2])];
        this.current = { target: tgt, yaw: lerp(tw.from.yaw, tw.to.yaw), pitch: lerp(tw.from.pitch, tw.to.pitch), distance: lerp(tw.from.distance, tw.to.distance) };
      }
      this.desired = clone(this.current);
      if (t >= 1) {
        this.current = clone(tw.to); this.desired = clone(tw.to);
        this.tween = null;
        tw.done?.(true);
      }
      return true;
    }

    if (this.orbit) {
      const o = this.orbit;
      const step = Math.min(o.remaining, o.speed * dt);
      this.current.yaw += step; this.desired.yaw = this.current.yaw;
      o.remaining -= step;
      if (o.remaining <= 1e-6) { this.orbit = null; o.done?.(true); }
      return true;
    }

    const a = 1 - Math.exp(-this.rate * dt);
    const c = this.current, d = this.desired;
    const before = c.yaw + c.pitch + c.distance + c.target[0] + c.target[1] + c.target[2];
    c.yaw += (d.yaw - c.yaw) * a;
    c.pitch += (d.pitch - c.pitch) * a;
    c.distance += (d.distance - c.distance) * a;
    for (let i = 0; i < 3; i++) c.target[i] += (d.target[i] - c.target[i]) * a;
    const after = c.yaw + c.pitch + c.distance + c.target[0] + c.target[1] + c.target[2];
    if (Math.abs(after - before) > 1e-5) moved = true;
    else if (Math.abs(d.yaw - c.yaw) + Math.abs(d.pitch - c.pitch) + Math.abs(d.distance - c.distance) < 1e-4) {
      // settle exactly so the render loop can go idle
      this.current = clone(d);
    }
    return moved;
  }

  // ---- input ---------------------------------------------------------------------------------

  private rotate(dx: number, dy: number) {
    this.stopAnimation();
    this.desired.yaw -= dx * 0.22;
    this.desired.pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, this.desired.pitch - dy * 0.22));
  }

  private pan(dx: number, dy: number, height: number, fov: number) {
    this.stopAnimation();
    const scale = (2 * this.desired.distance * Math.tan((fov * DEG) / 2)) / Math.max(1, height);
    const yaw = this.desired.yaw * DEG, pitch = this.desired.pitch * DEG;
    const right: Vec3Tuple = [Math.cos(yaw), 0, -Math.sin(yaw)];
    const up: Vec3Tuple = [Math.sin(yaw) * Math.sin(pitch), Math.cos(pitch), Math.cos(yaw) * Math.sin(pitch)];
    for (let i = 0; i < 3; i++) this.desired.target[i] += (-right[i] * dx + up[i] * dy) * scale;
  }

  private zoom(factor: number) {
    this.stopAnimation();
    const next = this.desired.distance * factor;
    if (factor < 1 && next < MIN_DISTANCE) {
      // dolly through: push the pivot forward instead of collapsing onto it
      const f = forwardOf(this.desired.yaw, this.desired.pitch);
      const step = Math.max(0.05, this.desired.distance * (1 - factor));
      for (let i = 0; i < 3; i++) this.desired.target[i] += f[i] * step;
      this.desired.distance = MIN_DISTANCE;
      return;
    }
    this.desired.distance = Math.max(MIN_DISTANCE, Math.min(MAX_DISTANCE, next));
  }

  attach(el: HTMLElement, keyTarget: HTMLElement, opts: RigInputOptions) {
    const pointers = new Map<number, { x: number; y: number }>();
    let down: { x: number; y: number; t: number; moved: boolean; button: number } | null = null;
    let pinch = 0;
    const local = (e: { clientX: number; clientY: number }) => {
      const r = el.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };

    const onDown = (e: PointerEvent) => {
      if (this.locked) return;
      if (e.pointerType === 'mouse' && e.button > 2) return;
      el.setPointerCapture?.(e.pointerId);
      pointers.set(e.pointerId, local(e));
      const p = local(e);
      down = pointers.size === 1 ? { x: p.x, y: p.y, t: performance.now(), moved: false, button: e.button } : null;
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = Math.hypot(a.x - b.x, a.y - b.y);
      }
      opts.onInteract?.();
    };
    const onMove = (e: PointerEvent) => {
      const prev = pointers.get(e.pointerId);
      if (!prev) return;
      if (this.locked) { pointers.set(e.pointerId, local(e)); return; }
      const p = local(e);
      const dx = p.x - prev.x, dy = p.y - prev.y;
      pointers.set(e.pointerId, p);
      if (down && Math.hypot(p.x - down.x, p.y - down.y) > 4) down.moved = true;
      const h = el.clientHeight;
      if (pointers.size === 1) {
        const panning = e.shiftKey || (e.pointerType === 'mouse' && (e.buttons & 6) !== 0);
        if (panning) this.pan(dx, dy, h, opts.fov); else this.rotate(dx, dy);
      } else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch > 0 && dist > 0) this.zoom(pinch / dist);
        pinch = dist;
        this.pan(dx / 2, dy / 2, h, opts.fov);
      }
    };
    const onUp = (e: PointerEvent) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.delete(e.pointerId);
      if (down && !down.moved && performance.now() - down.t < 600 && down.button === 0) {
        const p = local(e);
        opts.onClick?.(p.x, p.y, e);
      }
      down = null;
      if (pointers.size < 2) pinch = 0;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (this.locked) return;
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      this.zoom(Math.exp(Math.max(-60, Math.min(60, e.deltaY * unit)) * 0.0025));
      opts.onInteract?.();
    };
    const onDbl = (e: MouseEvent) => { if (this.locked) return; const p = local(e); opts.onDoubleClick?.(p.x, p.y); };
    const onContext = (e: Event) => e.preventDefault();
    const keyName = (e: KeyboardEvent) => e.key.toLowerCase();
    const flyKeys = new Set(['w', 'a', 's', 'd', 'q', 'e', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'shift']);
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || this.locked) return;
      const k = keyName(e);
      if (!flyKeys.has(k)) return;
      if (k.startsWith('arrow')) e.preventDefault();
      this.keys.add(k);
      opts.onInteract?.();
    };
    const onKeyUp = (e: KeyboardEvent) => { this.keys.delete(keyName(e)); };
    const onBlur = () => this.keys.clear();

    el.addEventListener('pointerdown', onDown);
    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerup', onUp);
    el.addEventListener('pointercancel', onUp);
    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('dblclick', onDbl);
    el.addEventListener('contextmenu', onContext);
    keyTarget.addEventListener('keydown', onKeyDown);
    keyTarget.addEventListener('keyup', onKeyUp);
    keyTarget.addEventListener('blur', onBlur);
    this.disposers.push(() => {
      el.removeEventListener('pointerdown', onDown);
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerup', onUp);
      el.removeEventListener('pointercancel', onUp);
      el.removeEventListener('wheel', onWheel);
      el.removeEventListener('dblclick', onDbl);
      el.removeEventListener('contextmenu', onContext);
      keyTarget.removeEventListener('keydown', onKeyDown);
      keyTarget.removeEventListener('keyup', onKeyUp);
      keyTarget.removeEventListener('blur', onBlur);
    });
  }

  dispose() { this.disposers.forEach((d) => d()); this.disposers = []; this.keys.clear(); }
}
