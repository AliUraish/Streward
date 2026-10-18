/**
 * PlayCanvas wrapper for one hosted SOG capture. Owns the device, the app, the gsplat entity, the camera
 * rig, picking and the synthetic-defect hook. React code talks to it through this class only.
 */
import {
  AppBase,
  AppOptions,
  Asset,
  CameraComponentSystem,
  Color,
  createGraphicsDevice,
  DEVICETYPE_WEBGL2,
  DEVICETYPE_WEBGPU,
  Entity,
  FILLMODE_NONE,
  GSplatComponentSystem,
  GSplatHandler,
  Picker,
  RESOLUTION_AUTO,
  TextureHandler,
  TONEMAP_NONE,
  Vec3,
  type GraphicsDevice,
  type Layer,
} from 'playcanvas';
import { CameraRig, poseLookingAt, positionOf, forwardOf, type MoveDone, type RigPose } from './camera-rig';
import { defectShader, type DefectKind } from './defects';
import type { SplatSite } from './sites';
import type { Vec3Tuple } from './types';

export interface EngineStats {
  gaussians: number;
  bytesLoaded: number;
  bytesTotal: number;
  downloadMs: number | null;
  firstFrameMs: number | null;
  lastSortMs: number | null;
  fps: number | null;
  pixelRatio: number;
  renderer: string;
}

export interface EngineConfig {
  canvas: HTMLCanvasElement;
  site: SplatSite;
  /** Attach mouse, touch and keyboard input. */
  interactive: boolean;
  /** Element that receives fly keys (WASD). Defaults to the canvas. */
  keyTarget?: HTMLElement;
  maxPixelRatio?: number;
  /** Fixed canvas size in CSS px (capture route). Without it the canvas fills its parent. */
  size?: { width: number; height: number };
  fov?: number;
  reducedMotion?: boolean;
  /** Try WebGPU first (GPU sort and culling), falling back to WebGL2. */
  preferWebGPU?: boolean;
  /** Render only when something changes once the first frame is up (default true). */
  onDemand?: boolean;
  onProgress?(loaded: number, total: number): void;
  onLoaded?(): void;
  onFirstFrame?(): void;
  onError?(error: Error): void;
  /** Called after any frame where the camera or the canvas changed; reproject overlays here. */
  onCamera?(): void;
  onClick?(x: number, y: number): void;
  onInteract?(): void;
}

export interface Projection { x: number; y: number; depth: number; distance: number; visible: boolean }

/** Region of the canvas (CSS px) that a captured frame covers, centre-cropped to the frame aspect. */
export interface FrameCrop { sx: number; sy: number; sw: number; sh: number; width: number; height: number }

export interface VisiblePin { assetTag: string; x: number; y: number; distance: number; occluded: boolean }

export interface CameraInfo { position: Vec3Tuple; target: Vec3Tuple; fov: number; yaw: number; pitch: number }

export type MoveDirection = 'forward' | 'back' | 'left' | 'right' | 'up' | 'down';

const tmpA = new Vec3();
const tmpB = new Vec3();

export function hasWebGL2(): boolean {
  try {
    const c = document.createElement('canvas');
    return !!c.getContext('webgl2');
  } catch {
    return false;
  }
}

export class SplatEngine {
  readonly app: AppBase;
  readonly device: GraphicsDevice;
  readonly camera: Entity;
  readonly rig: CameraRig;
  readonly site: SplatSite;
  readonly stats: EngineStats;
  splat: Entity | null = null;
  fov: number;
  initialPose: RigPose;

  private cfg: EngineConfig;
  private asset: Asset | null = null;
  private picker: Picker | null = null;
  private layer: Layer | null = null;
  private destroyed = false;
  private loadStart = performance.now();
  private resizeObserver: ResizeObserver | null = null;
  private frameTimes: number[] = [];
  private renderedThisFrame = false;
  private sortCount = 0;
  private lastMoveAt = 0;
  private lastSortAt = 0;
  /** Camera forward when the last sort result arrived (the CPU sort is directional, so only rotation needs a new sort). */
  private fwdAtSort = new Vec3(0, 0, 0);
  private framesSinceLoad = 0;
  private lastRequest = 0;
  private overlayDirty = true;
  private frameListeners = new Set<(rendered: boolean) => void>();
  private firstFrameFired = false;
  private defect: { kind: DefectKind; center: Vec3Tuple; radius: number } | null = null;

  static async create(cfg: EngineConfig): Promise<SplatEngine> {
    const webgpu = !!cfg.preferWebGPU && typeof navigator !== 'undefined' && 'gpu' in navigator;
    const device = await createGraphicsDevice(cfg.canvas, {
      deviceTypes: webgpu ? [DEVICETYPE_WEBGPU, DEVICETYPE_WEBGL2] : [DEVICETYPE_WEBGL2],
      antialias: false,
      alpha: false,
      depth: true,
      stencil: false,
      powerPreference: 'high-performance',
      xrCompatible: false,
    });
    return new SplatEngine(cfg, device);
  }

  private constructor(cfg: EngineConfig, device: GraphicsDevice) {
    this.cfg = cfg;
    this.device = device;
    this.site = cfg.site;
    this.fov = cfg.fov ?? cfg.site.camera.fov;
    const ratioCap = cfg.maxPixelRatio ?? 1.5;
    device.maxPixelRatio = Math.max(0.5, Math.min(window.devicePixelRatio || 1, ratioCap));

    const options = new AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [CameraComponentSystem, GSplatComponentSystem];
    options.resourceHandlers = [TextureHandler, GSplatHandler];
    const app = new AppBase(cfg.canvas);
    app.init(options);
    this.app = app;
    app.setCanvasFillMode(FILLMODE_NONE);
    app.setCanvasResolution(RESOLUTION_AUTO);
    const texHandler = app.loader.getHandler('texture') as unknown as { imgParser?: { crossOrigin?: string } } | undefined;
    if (texHandler?.imgParser) texHandler.imgParser.crossOrigin = 'anonymous';

    // the scan is large: keep the defaults that cull tiny and transparent splats
    const gs = app.scene.gsplat;
    gs.minPixelSize = 2;

    this.stats = {
      gaussians: cfg.site.gaussians,
      bytesLoaded: 0,
      bytesTotal: 0,
      downloadMs: null,
      firstFrameMs: null,
      lastSortMs: null,
      fps: null,
      pixelRatio: device.maxPixelRatio,
      renderer: device.deviceType,
    };

    const camera = new Entity('camera', app);
    camera.addComponent('camera', {
      clearColor: new Color(0, 0, 0, 1),
      fov: this.fov,
      nearClip: 0.03,
      farClip: 400,
      toneMapping: TONEMAP_NONE,
    });
    app.root.addChild(camera);
    this.camera = camera;
    this.layer = app.scene.layers.getLayerByName('World') ?? null;

    const { position, target } = cfg.site.camera;
    this.initialPose = poseLookingAt(position, target, cfg.site.pivotDistance);
    this.rig = new CameraRig(this.initialPose);
    this.applyPose();

    if (cfg.interactive) {
      this.rig.attach(cfg.canvas, cfg.keyTarget ?? cfg.canvas, {
        fov: this.fov,
        onClick: (x, y) => cfg.onClick?.(x, y),
        onDoubleClick: (x, y) => { void this.pivotTo(x, y); },
        onInteract: () => { this.requestRender(); cfg.onInteract?.(); },
      });
    }

    app.on('update', this.onUpdate);
    app.on('framerender', this.onFrameRender);
    app.on('frameend', this.onFrameEnd);
    app.scene.on('gsplat:sorted', (ms: number) => {
      this.sortCount++;
      this.lastSortAt = performance.now();
      this.fwdAtSort.copy(this.camera.forward);
      this.stats.lastSortMs = ms;
      this.requestRender();
    });
    app.systems.gsplat?.on('frame:request', () => this.requestRender());

    const parent = cfg.canvas.parentElement;
    if (!cfg.size && parent && typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(parent);
    }
    this.resize();
    app.autoRender = true;
    app.start();
    this.load();
  }

  // ---- loading ---------------------------------------------------------------------------------

  private load() {
    const { site } = this;
    const asset = new Asset(`${site.sceneId}/meta.json`, 'gsplat', { url: site.metaUrl, filename: 'meta.json' });
    this.asset = asset;
    asset.on('progress', (loaded: number, total: number) => {
      this.stats.bytesLoaded = loaded;
      this.stats.bytesTotal = total;
      this.cfg.onProgress?.(loaded, total);
    });
    asset.on('error', (err: unknown) => {
      if (this.destroyed) return;
      this.cfg.onError?.(err instanceof Error ? err : new Error(String(err)));
    });
    asset.ready(() => {
      if (this.destroyed || !asset.resource) return;
      this.stats.downloadMs = Math.round(performance.now() - this.loadStart);
      const entity = new Entity('splat', this.app);
      // the SuperSplat viewer frame: scan data is rotated 180 degrees about Z
      entity.setLocalEulerAngles(0, 0, 180);
      entity.addComponent('gsplat', { asset, unified: true });
      this.app.root.addChild(entity);
      this.splat = entity;
      if (this.defect) this.applyDefect();
      this.cfg.onLoaded?.();
      this.requestRender();
    });
    this.app.assets.add(asset);
    this.app.assets.load(asset);
  }

  get loaded() { return !!this.splat; }

  // ---- frame loop ------------------------------------------------------------------------------

  private onUpdate = (dt: number) => {
    if (this.rig.update(dt)) {
      this.applyPose();
      this.requestRender();
      this.lastMoveAt = performance.now();
    }
    if (this.overlayDirty) {
      this.overlayDirty = false;
      this.cfg.onCamera?.();
    }
  };

  private onFrameRender = () => {
    this.renderedThisFrame = this.app.autoRender || this.app.renderNextFrame;
  };

  private onFrameEnd = () => {
    const rendered = this.renderedThisFrame;
    this.renderedThisFrame = false;
    if (rendered) {
      const now = performance.now();
      this.frameTimes.push(now);
      while (this.frameTimes.length > 2 && now - this.frameTimes[0] > 2000) this.frameTimes.shift();
      if (this.frameTimes.length > 4) {
        const span = this.frameTimes[this.frameTimes.length - 1] - this.frameTimes[0];
        if (span > 0) this.stats.fps = Math.round(((this.frameTimes.length - 1) * 1000) / span);
      }
      if (this.splat) this.framesSinceLoad++;
      // the CPU-sort renderer is ready after its first sort; the GPU-sort one after a few frames
      if (this.splat && !this.firstFrameFired && (this.usesCpuSort ? this.sortCount > 0 : this.framesSinceLoad > 3)) {
        this.firstFrameFired = true;
        this.stats.firstFrameMs = Math.round(now - this.loadStart);
        this.cfg.onFirstFrame?.();
        // after the first full frame, render on demand only
        if (this.cfg.onDemand !== false) {
          window.setTimeout(() => { if (!this.destroyed) this.app.autoRender = false; this.requestRender(); }, 800);
        }
      }
    }
    this.frameListeners.forEach((fn) => fn(rendered));
  };

  /** Subscribe to the end of every engine tick. Returns an unsubscribe function. */
  onTick(fn: (rendered: boolean) => void) {
    this.frameListeners.add(fn);
    return () => { this.frameListeners.delete(fn); };
  }

  get sorts() { return this.sortCount; }

  /** WebGL2 renders with a CPU sort in a worker; WebGPU sorts on the GPU and fires no sort events. */
  get usesCpuSort() { return !this.device.isWebGPU; }

  /** Resolves at the end of the next engine tick (after a rendered one when `rendered` is true). */
  nextTick(rendered = false) {
    return new Promise<void>((resolve) => {
      const off = this.onTick((r) => {
        if (rendered && !r) { this.requestRender(); return; }
        off();
        resolve();
      });
      this.requestRender();
    });
  }

  /**
   * Wait until the camera has stopped, the sort has caught up with the final pose and `frames` more
   * frames have rendered. With the CPU sort a move issues one sort job (a job already in flight can
   * land first, so a short quiet window follows the first result).
   */
  async settle({ timeoutMs = 20000, frames = 2 }: { timeoutMs?: number; frames?: number } = {}) {
    const t0 = performance.now();
    const late = () => performance.now() - t0 > timeoutMs;
    while (!this.rig.settled && !late()) await this.nextTick();
    if (this.usesCpuSort) {
      const start = this.sortCount;
      // the sort key is the depth along the view direction: a pure translation needs no new sort
      const rotated = Math.acos(Math.max(-1, Math.min(1, this.fwdAtSort.dot(this.camera.forward)))) > 1e-3;
      if (rotated && this.lastSortAt <= this.lastMoveAt) {
        while (this.sortCount === start && !late()) await this.nextTick();
      }
      let last = this.sortCount;
      let quiet = performance.now();
      const quietMs = () => Math.max(200, (this.stats.lastSortMs ?? 120) * 1.5);
      while (performance.now() - quiet < quietMs() && !late()) {
        await this.nextTick();
        if (this.sortCount !== last) { last = this.sortCount; quiet = performance.now(); }
      }
    }
    for (let i = 0; i < frames && !late(); i++) await this.nextTick(true);
  }

  /** Centre crop of the canvas with the aspect of a `width`×`height` frame. */
  frameCrop(width: number, height: number): FrameCrop {
    const cw = this.width, ch = this.height;
    const aspect = width / height;
    if (cw / ch > aspect) {
      const sw = ch * aspect;
      return { sx: (cw - sw) / 2, sy: 0, sw, sh: ch, width, height };
    }
    const sh = cw / aspect;
    return { sx: 0, sy: (ch - sh) / 2, sw: cw, sh, width, height };
  }

  /**
   * Copy the next rendered frame into a JPEG of `width`×`height` (centre crop, then scale). Runs in
   * the same task as the render, so the drawing buffer does not need to be preserved.
   */
  captureJpeg(opts: {
    width: number;
    height: number;
    quality?: number;
    label?: string | null;
    draw?(ctx: CanvasRenderingContext2D, crop: FrameCrop): void;
  }): Promise<{ dataUrl: string; crop: FrameCrop }> {
    const { width, height } = opts;
    const crop = this.frameCrop(width, height);
    const canvas = this.cfg.canvas;
    return new Promise((resolve) => {
      const off = this.onTick((rendered) => {
        if (!rendered) { this.requestRender(); return; }
        off();
        const out = document.createElement('canvas');
        out.width = width; out.height = height;
        const ctx = out.getContext('2d')!;
        const k = canvas.width / Math.max(1, this.width);
        ctx.drawImage(canvas, crop.sx * k, crop.sy * k, crop.sw * k, crop.sh * k, 0, 0, width, height);
        opts.draw?.(ctx, crop);
        if (opts.label) {
          ctx.font = '500 11px Geist, system-ui, sans-serif';
          const w = Math.ceil(ctx.measureText(opts.label).width) + 10;
          ctx.fillStyle = '#000';
          ctx.fillRect(0, height - 19, w, 19);
          ctx.fillStyle = '#fff';
          ctx.textBaseline = 'middle';
          ctx.fillText(opts.label, 5, height - 9.5);
        }
        resolve({ dataUrl: out.toDataURL('image/jpeg', opts.quality ?? 0.88), crop });
      });
      this.requestRender();
    });
  }

  /** Pins in front of the camera and inside the frame, in frame coordinates 0..1, with occlusion. */
  async visiblePins(pins: { assetTag: string; position: Vec3Tuple }[], crop: FrameCrop, occlusion = true): Promise<VisiblePin[]> {
    const pr: Projection = { x: 0, y: 0, depth: 0, distance: 0, visible: false };
    const hits: { assetTag: string; px: number; py: number; x: number; y: number; distance: number }[] = [];
    for (const pin of pins) {
      this.project(pin.position, pr);
      if (pr.depth <= (this.camera.camera?.nearClip ?? 0.03)) continue;
      const x = (pr.x - crop.sx) / crop.sw, y = (pr.y - crop.sy) / crop.sh;
      if (x < 0 || y < 0 || x > 1 || y > 1) continue;
      hits.push({ assetTag: pin.assetTag, px: pr.x, py: pr.y, x, y, distance: pr.distance });
    }
    const surf = occlusion ? await this.surfaceDistances(hits.map((h) => ({ x: h.px, y: h.py }))) : hits.map(() => null);
    return hits.map((h, i) => {
      const s = surf[i];
      const occluded = s !== null && s < h.distance - Math.max(0.35, h.distance * 0.12);
      return { assetTag: h.assetTag, x: +h.x.toFixed(4), y: +h.y.toFixed(4), distance: +h.distance.toFixed(3), occluded };
    });
  }

  cameraInfo(): CameraInfo {
    const p = this.camera.getPosition();
    const r = (n: number) => +n.toFixed(4);
    return {
      position: [r(p.x), r(p.y), r(p.z)],
      target: this.rig.current.target.map(r) as Vec3Tuple,
      fov: this.fov,
      yaw: r(this.rig.current.yaw),
      pitch: r(this.rig.current.pitch),
    };
  }

  requestRender() {
    if (this.destroyed) return;
    this.app.renderNextFrame = true;
    this.overlayDirty = true;
    this.lastRequest = performance.now();
  }

  get idleMs() { return performance.now() - this.lastRequest; }

  setAutoRender(on: boolean) { this.app.autoRender = on; if (!on) this.requestRender(); }

  resize(width?: number, height?: number) {
    if (this.destroyed) return;
    const parent = this.cfg.canvas.parentElement;
    const fixed = this.cfg.size;
    const w = Math.max(1, Math.round(width ?? fixed?.width ?? parent?.clientWidth ?? this.cfg.canvas.clientWidth));
    const h = Math.max(1, Math.round(height ?? fixed?.height ?? parent?.clientHeight ?? this.cfg.canvas.clientHeight));
    this.app.resizeCanvas(w, h);
    this.requestRender();
  }

  setPixelRatio(ratio: number) {
    this.device.maxPixelRatio = ratio;
    this.stats.pixelRatio = ratio;
    this.resize();
  }

  private applyPose() {
    const p = positionOf(this.rig.current);
    this.camera.setPosition(p[0], p[1], p[2]);
    const t = this.rig.current.target;
    // look at a point along the forward vector so pitch limits hold exactly
    const f = forwardOf(this.rig.current.yaw, this.rig.current.pitch);
    tmpA.set(p[0] + f[0], p[1] + f[1], p[2] + f[2]);
    if (!Number.isFinite(t[0])) return;
    this.camera.lookAt(tmpA, Vec3.UP);
  }

  /** Apply a pose immediately (no damping), e.g. for the capture route. */
  setPose(pose: RigPose) {
    this.rig.set(pose);
    this.applyPose();
    this.requestRender();
    this.lastMoveAt = performance.now();
  }

  // ---- camera actions --------------------------------------------------------------------------

  setReducedMotion(on: boolean) { this.cfg.reducedMotion = on; }

  /** Instant mode jumps instead of easing (headless renderers, where frames take seconds). */
  instant = false;

  private duration(seconds: number) { return this.cfg.reducedMotion || this.instant ? 0 : seconds; }

  /** Ease to look at `point` from `distance`, keeping the current viewing side. */
  focusOn(point: Vec3Tuple, distance = 1.8, done?: MoveDone, seconds?: number) {
    const cam = positionOf(this.rig.current);
    let dir: Vec3Tuple = [cam[0] - point[0], cam[1] - point[1], cam[2] - point[2]];
    const len = Math.hypot(dir[0], dir[1], dir[2]);
    if (len < 1e-3) dir = [0, 0.4, 1];
    else dir = [dir[0] / len, dir[1] / len, dir[2] / len];
    // keep a gentle downward look, never from straight above or below
    const horiz = Math.hypot(dir[0], dir[2]) || 1;
    const elev = Math.max(-0.2, Math.min(0.55, dir[1]));
    const h = Math.sqrt(1 - elev * elev);
    const d: Vec3Tuple = [(dir[0] / horiz) * h, elev, (dir[2] / horiz) * h];
    const from: Vec3Tuple = [point[0] + d[0] * distance, point[1] + d[1] * distance, point[2] + d[2] * distance];
    const pose = poseLookingAt(from, point);
    const travel = Math.hypot(from[0] - cam[0], from[1] - cam[1], from[2] - cam[2]);
    this.rig.animateTo(pose, this.duration(seconds ?? Math.min(2.2, 0.8 + travel * 0.12)), done);
    this.requestRender();
  }

  orbitAround(point: Vec3Tuple, distance = 1.8, seconds = 24) {
    if (this.cfg.reducedMotion) { this.focusOn(point, distance); return; }
    this.focusOn(point, distance, (ok) => { if (ok) this.rig.orbitBy(360, 360 / seconds); });
  }

  // ---- agent moves (eye mode): eased, awaitable, in the scan's world frame ----------------------

  /** Move along the camera's own axes by `meters`. */
  moveBy(direction: MoveDirection, meters: number, seconds?: number) {
    const { forward, right, up } = this.rig.axes();
    const axis = { forward, back: forward, right, left: right, up, down: up }[direction];
    const sign = direction === 'back' || direction === 'left' || direction === 'down' ? -1 : 1;
    const v: Vec3Tuple = [axis[0] * meters * sign, axis[1] * meters * sign, axis[2] * meters * sign];
    this.requestRender();
    return this.rig.animate(this.rig.translated(v), this.duration(seconds ?? Math.min(1.6, 0.5 + meters * 0.25)), 'path');
  }

  /** Turn in place. Positive yaw turns right, positive pitch looks up. */
  turnBy(yawDeg: number, pitchDeg: number, seconds?: number) {
    this.requestRender();
    const amount = Math.abs(yawDeg) + Math.abs(pitchDeg);
    return this.rig.animate(this.rig.turned(yawDeg, pitchDeg), this.duration(seconds ?? Math.min(1.6, 0.4 + amount / 120)), 'look');
  }

  /** Frame a point from `distance`, keeping the current viewing side (awaitable focusOn). */
  frame(point: Vec3Tuple, distance = 1.8, seconds?: number) {
    return new Promise<boolean>((resolve) => this.focusOn(point, distance, resolve, seconds));
  }

  /** Swing around `pivot` to an absolute yaw, keeping pitch and distance. */
  orbitTo(pivot: Vec3Tuple, yaw: number, seconds?: number) {
    const c = this.rig.current;
    const pose: RigPose = { target: [...pivot] as Vec3Tuple, yaw, pitch: c.pitch, distance: c.distance };
    this.requestRender();
    return this.rig.animate(pose, this.duration(seconds ?? 0.9), 'orbit');
  }

  reset(animate = true) {
    this.rig.animateTo(this.initialPose, animate ? this.duration(1.4) : 0);
    this.requestRender();
  }

  /** Double click: move the orbit pivot to the picked surface point. */
  private async pivotTo(x: number, y: number) {
    const p = await this.pick(x, y);
    if (!p) return;
    const cam = positionOf(this.rig.current);
    const pose = poseLookingAt(cam, p);
    this.rig.animateTo(pose, this.duration(0.6));
    this.requestRender();
  }

  // ---- projection and picking ------------------------------------------------------------------

  get width() { return this.cfg.canvas.clientWidth; }
  get height() { return this.cfg.canvas.clientHeight; }

  project(point: Vec3Tuple, out: Projection): Projection {
    const cam = this.camera.camera!;
    const pos = this.camera.getPosition();
    const fwd = this.camera.forward;
    tmpA.set(point[0], point[1], point[2]);
    tmpB.sub2(tmpA, pos);
    out.depth = tmpB.dot(fwd);
    out.distance = tmpB.length();
    if (out.depth <= cam.nearClip) {
      out.visible = false;
      return out;
    }
    const s = cam.worldToScreen(tmpA, tmpB);
    out.x = s.x;
    out.y = s.y;
    out.visible = s.x > -40 && s.y > -40 && s.x < this.width + 40 && s.y < this.height + 40;
    return out;
  }

  private ensurePicker(scale: number) {
    const w = Math.max(1, Math.round(this.width * scale));
    const h = Math.max(1, Math.round(this.height * scale));
    if (!this.picker) this.picker = new Picker(this.app, w, h, true);
    else this.picker.resize(w, h);
    return { w, h };
  }

  /** World point of the splat surface under a canvas pixel (CSS px), or null if nothing is there. */
  async pick(x: number, y: number, scale = 0.5): Promise<Vec3Tuple | null> {
    if (!this.splat || this.destroyed) return null;
    const { w, h } = this.ensurePicker(scale);
    const picker = this.picker!;
    try {
      picker.prepare(this.camera.camera!, this.app.scene, this.layer ? [this.layer] : undefined);
      const p = await picker.getWorldPointAsync((x / this.width) * w, (y / this.height) * h);
      if (!p || !Number.isFinite(p.x)) return null;
      return [p.x, p.y, p.z];
    } catch {
      return null;
    }
  }

  /**
   * Distances from the camera to the splat surface at several canvas pixels, from one pick render.
   * Null entries mean nothing was rendered there.
   */
  async surfaceDistances(points: { x: number; y: number }[], scale = 0.25): Promise<(number | null)[]> {
    if (!this.splat || this.destroyed || points.length === 0) return points.map(() => null);
    const { w, h } = this.ensurePicker(scale);
    const picker = this.picker!;
    try {
      picker.prepare(this.camera.camera!, this.app.scene, this.layer ? [this.layer] : undefined);
      const cam = this.camera.getPosition().clone();
      const out: (number | null)[] = [];
      for (const pt of points) {
        const p = await picker.getWorldPointAsync((pt.x / this.width) * w, (pt.y / this.height) * h);
        out.push(p && Number.isFinite(p.x) ? p.distance(cam) : null);
      }
      return out;
    } catch {
      return points.map(() => null);
    }
  }

  /** A point along the view ray through a canvas pixel at a fixed distance. */
  rayPoint(x: number, y: number, distance: number): Vec3Tuple {
    const cam = this.camera.camera!;
    const far = cam.screenToWorld(x, y, cam.farClip, new Vec3());
    const pos = this.camera.getPosition();
    const dir = far.sub(pos).normalize();
    return [pos.x + dir.x * distance, pos.y + dir.y * distance, pos.z + dir.z * distance];
  }

  // ---- synthetic defects -----------------------------------------------------------------------

  setDefect(kind: DefectKind, center: Vec3Tuple, radius: number) {
    this.defect = kind === 'none' ? null : { kind, center, radius };
    this.applyDefect();
  }

  private applyDefect() {
    const gs = this.splat?.gsplat;
    if (!gs) return;
    const glsl = this.defect ? defectShader(this.defect.kind, this.defect.center, this.defect.radius) : null;
    gs.setWorkBufferModifier(glsl ? { glsl } : null);
    this.requestRender();
  }

  // ---- teardown --------------------------------------------------------------------------------

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.resizeObserver?.disconnect();
    this.rig.dispose();
    this.frameListeners.clear();
    try { this.picker?.destroy(); } catch { /* device may already be gone */ }
    try {
      if (this.asset) { this.app.assets.remove(this.asset); this.asset.unload(); }
    } catch { /* ignore */ }
    try { this.app.destroy(); } catch { /* ignore */ }
  }
}
