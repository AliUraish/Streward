/**
 * PlayCanvas wrapper for one hosted capture: a SOG file set, or a streamed LOD octree (lod-meta.json),
 * which shows its coarsest level first and then streams finer chunk files around the camera up to a
 * splat budget. Owns the device, the app, the gsplat entity, the camera rig, picking and the
 * synthetic-defect hook. React code talks to it through this class only.
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
  Vec2,
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
  /** Streamed LOD captures only. */
  lod: LodStats | null;
}

/** Streaming state of a LOD capture. Chunk files are the unit (CloudFront sends no timing headers for byte counts). */
export interface LodStats {
  /** Splat budget the LOD choice fills. */
  budget: number;
  /** Splats in the sorted, displayed set. */
  activeSplats: number;
  /** Chunk files downloading or queued for the current view. */
  pendingFiles: number;
  /** Chunk files resident in memory (loaded and not yet released after their cooldown). */
  residentFiles: number;
  /** True once the full LOD range is in use (after the coarse first view). */
  refining: boolean;
  /** True when the displayed set is sorted and nothing is loading for the current view. */
  complete: boolean;
  /** Milliseconds from creation until the full-detail view first completed. */
  detailMs: number | null;
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
  /** Streamed LOD captures: splat budget instead of the site's interactive budget. */
  splatBudget?: number;
  /** Bytes of the scene file, then (streamed LOD captures) chunk files loaded of those needed so far. */
  onProgress?(loaded: number, total: number, unit: 'bytes' | 'files'): void;
  /** Streamed LOD captures: called when the streaming state changes. */
  onStream?(lod: LodStats): void;
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

/** Insets in CSS px where HUD panels cover the canvas; the camera frames its target between them. */
export interface SafeArea { top?: number; right?: number; bottom?: number; left?: number }

const tmpA = new Vec3();
const tmpB = new Vec3();

/**
 * The parts of PlayCanvas 2.23's GSplatOctree the engine reads. The frame:ready loading count also
 * counts prefetch requests (each pending file twice), so file counts come from the octree's resident
 * map and its asset loader's in-flight and queued sets instead.
 */
interface OctreeLike {
  lodLevels?: number;
  fileResources?: Map<number, unknown>;
  assetLoader?: { maxConcurrentLoads: number; _currentlyLoading?: Set<string>; _loadQueue?: Map<string, number> } | null;
}

/** Rendered ticks with nothing loading and the latest set sorted before a streamed view counts as settled (a LOD update runs every 10 ticks). */
const STREAM_CALM_TICKS = 12;

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
  /** Field of view the engine started with (the site's, or the capture route's). */
  readonly baseFov: number;
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
  /**
   * Camera forward and position when the last sort result arrived. The directional CPU sort only needs
   * a new sort after a rotation; the radial one (streamed sites) only after a translation.
   */
  private fwdAtSort = new Vec3(0, 0, 0);
  private posAtSort = new Vec3(Infinity, Infinity, Infinity);
  /** Streamed LOD state, from the gsplat system's frame:ready event. */
  private stream = { ready: false, pending: 0, done: 0, total: 0, calm: 0, refining: false, complete: false, key: '' };
  /** The streamed capture's octree (lod-meta.json resource), for exact chunk-file counts. */
  private octree: OctreeLike | null = null;
  private framesSinceLoad = 0;
  private lastRequest = 0;
  private overlayDirty = true;
  private frameListeners = new Set<(rendered: boolean) => void>();
  private firstFrameFired = false;
  private defect: { kind: DefectKind; center: Vec3Tuple; radius: number } | null = null;
  private safe = { top: 0, right: 0, bottom: 0, left: 0 };

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
    this.baseFov = this.fov;
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
    const lod = cfg.site.lod;
    if (lod) {
      // target mode: LOD detail rises around the camera until the budget is used
      gs.splatBudget = cfg.splatBudget ?? lod.budget;
      gs.lodBehindPenalty = lod.lodBehindPenalty;
      gs.lodUpdateAngle = lod.lodUpdateAngle;
      gs.lodUpdateDistance = lod.lodUpdateDistance;
      gs.radialSorting = lod.radialSorting;
    }

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
      lod: lod ? { budget: gs.splatBudget, activeSplats: 0, pendingFiles: 0, residentFiles: 0, refining: false, complete: false, detailMs: null } : null,
    };

    const camera = new Entity('camera', app);
    // black until the first frame (the loading overlay is light text), then the site's background
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
      this.posAtSort.copy(this.camera.getPosition());
      this.stats.lastSortMs = ms;
      this.requestRender();
    });
    app.systems.gsplat?.on('frame:request', () => this.requestRender());
    if (lod) app.systems.gsplat?.on('frame:ready', this.onStreamFrame);

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
    // the gsplat handler picks its parser by file name: lod-meta.json is the streamed octree
    const filename = site.format === 'lod' ? 'lod-meta.json' : 'meta.json';
    const asset = new Asset(`${site.sceneId}/${filename}`, 'gsplat', { url: site.metaUrl, filename });
    this.asset = asset;
    asset.on('progress', (loaded: number, total: number) => {
      this.stats.bytesLoaded = loaded;
      this.stats.bytesTotal = total;
      this.cfg.onProgress?.(loaded, total, 'bytes');
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
      const lod = site.lod;
      if (lod) {
        const octree = (asset.resource as { octree?: OctreeLike }).octree ?? null;
        this.octree = octree;
        const coarsest = Math.max(0, (octree?.lodLevels ?? lod.levels) - 1);
        if (octree?.assetLoader) octree.assetLoader.maxConcurrentLoads = lod.concurrentLoads;
        // coarsest level only until the first frame is up (two chunk files), then the full range
        entity.addComponent('gsplat', {
          asset,
          unified: true,
          lodBaseDistance: lod.lodBaseDistance,
          lodMultiplier: lod.lodMultiplier,
          lodRangeMin: coarsest,
          lodRangeMax: coarsest,
        });
      } else {
        entity.addComponent('gsplat', { asset, unified: true });
      }
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

  // ---- LOD streaming ---------------------------------------------------------------------------

  /** frame:ready (camera component, layer, ready, loadingCount) from the unified gsplat manager. */
  private onStreamFrame = (cam: unknown, _layer: unknown, ready: boolean, loading: number) => {
    if (this.destroyed || cam !== this.camera.camera) return;
    const s = this.stream;
    const loader = this.octree?.assetLoader;
    const pending = loader?._currentlyLoading && loader._loadQueue ? loader._currentlyLoading.size + loader._loadQueue.size : loading;
    const resident = this.octree?.fileResources?.size ?? 0;
    s.ready = ready;
    s.pending = Math.max(pending, loading > 0 ? 1 : 0);
    s.calm = ready && loading === 0 ? s.calm + 1 : 0;
    // progress through the files asked for since streaming last went quiet
    if (s.pending === 0) s.total = 0;
    else s.total = Math.max(s.total, s.done + s.pending);
    s.done = s.pending === 0 ? 0 : Math.max(0, s.total - s.pending);
    const lod = this.stats.lod;
    if (!lod) return;
    lod.activeSplats = (this.app.stats as unknown as { frame?: { gsplats?: number } }).frame?.gsplats ?? 0;
    lod.pendingFiles = s.pending;
    lod.residentFiles = resident;
    lod.refining = s.refining;
    const complete = s.refining && s.calm >= STREAM_CALM_TICKS;
    if (complete && lod.detailMs === null) lod.detailMs = Math.round(performance.now() - this.loadStart);
    s.complete = complete;
    lod.complete = complete;
    if (s.pending > 0) this.cfg.onProgress?.(s.done, s.total, 'files');
    const key = `${s.pending}|${resident}|${s.refining}|${complete}`;
    if (key !== s.key) {
      s.key = key;
      this.cfg.onStream?.({ ...lod });
    }
  };

  /** Streamed LOD: after the coarse first view, open the full LOD range so finer chunks stream in. */
  private beginRefine() {
    const gs = this.splat?.gsplat;
    const lod = this.site.lod;
    if (!gs || !lod || this.stream.refining) return;
    this.stream.refining = true;
    this.stream.calm = 0;
    gs.lodRangeMin = 0;
    gs.lodRangeMax = Math.max(0, (this.octree?.lodLevels ?? lod.levels) - 1);
    if (this.stats.lod) this.stats.lod.refining = true;
    this.requestRender();
  }

  /** Streamed LOD: true when the full-detail set for the current view is loaded, sorted and displayed. */
  get streamComplete() { return !this.site.lod || this.stream.complete; }

  /**
   * Streamed LOD: resolve when the view has streamed (nothing loading, the latest set sorted) for a
   * stretch of rendered ticks long enough for a LOD update to have run, or when `late()` says stop.
   */
  private async waitForStream(late: () => boolean) {
    if (!this.site.lod) return;
    this.stream.calm = 0;
    while (this.stream.calm < STREAM_CALM_TICKS && !late()) await this.nextTick(true);
  }

  // ---- frame loop ------------------------------------------------------------------------------

  private onUpdate = (dt: number) => {
    if (this.rig.update(dt)) {
      this.applyPose();
      this.requestRender();
      this.lastMoveAt = performance.now();
      // streamed captures: count the quiet stretch again once the camera stops (a LOD update follows)
      this.stream.calm = 0;
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
      // the CPU-sort renderer is ready after its first sort; the GPU-sort one after a few frames; a
      // streamed capture once its coarse level has loaded and sorted
      const sorted = this.usesCpuSort ? this.sortCount > 0 : this.framesSinceLoad > 3;
      const streamed = !this.site.lod || (this.stream.calm >= 2 && (this.stats.lod?.activeSplats ?? 0) > 0);
      if (this.splat && !this.firstFrameFired && sorted && streamed) {
        this.firstFrameFired = true;
        this.stats.firstFrameMs = Math.round(now - this.loadStart);
        const bg = this.site.background;
        if (bg && this.camera.camera) this.camera.camera.clearColor = new Color(bg[0], bg[1], bg[2], 1);
        this.beginRefine();
        this.cfg.onFirstFrame?.();
        // after the first full frame, render on demand only
        if (this.cfg.onDemand !== false) {
          window.setTimeout(() => { if (!this.destroyed) this.app.autoRender = false; this.requestRender(); }, 800);
        }
      }
    }
    // streamed captures go idle only after a quiet stretch long enough for a LOD update to have run;
    // while files download, their arrival requests the next frame (frame:request), so no polling
    if (this.site.lod && this.firstFrameFired && this.stream.pending === 0 && this.stream.calm < STREAM_CALM_TICKS) this.requestRender();
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
    // streamed captures: the chunk files for the final pose, and the sort of the set they make
    await this.waitForStream(late);
    if (this.usesCpuSort) {
      const start = this.sortCount;
      // a directional sort key (depth along the view axis) needs no new sort for a pure translation,
      // a radial one (distance from the camera) none for a pure rotation
      const stale = this.app.scene.gsplat.radialSorting
        ? this.posAtSort.distance(this.camera.getPosition()) > 1e-3
        : Math.acos(Math.max(-1, Math.min(1, this.fwdAtSort.dot(this.camera.forward)))) > 1e-3;
      if (stale && this.lastSortAt <= this.lastMoveAt) {
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

  /**
   * Crop of the canvas with the aspect of a `width`×`height` frame, centred on the view axis (the
   * canvas centre, or the centre of the safe area when HUD insets shift the projection).
   */
  frameCrop(width: number, height: number): FrameCrop {
    const cw = this.width, ch = this.height;
    const { x: px, y: py } = this.principalPoint();
    let hw = Math.max(1, Math.min(px, cw - px)), hh = Math.max(1, Math.min(py, ch - py));
    const aspect = width / height;
    if (hw / hh > aspect) hw = hh * aspect; else hh = hw / aspect;
    return { sx: px - hw, sy: py - hh, sw: hw * 2, sh: hh * 2, width, height };
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
    this.applySafeArea();
    this.requestRender();
  }

  // ---- safe area (HUD panels over the canvas) ----------------------------------------------------

  /**
   * Keep the orbit pivot (and so every focus, orbit and the start view) at the centre of the area
   * between HUD panels. Uses an off-centre projection (lens shift), so the scan still fills the
   * whole canvas and nothing is letterboxed.
   */
  setSafeArea(area: SafeArea | null | undefined) {
    const v = (n: number | undefined) => (typeof n === 'number' && Number.isFinite(n) ? Math.max(0, n) : 0);
    this.safe = { top: v(area?.top), right: v(area?.right), bottom: v(area?.bottom), left: v(area?.left) };
    this.applySafeArea();
    this.requestRender();
  }

  private applySafeArea() {
    const cam = this.camera?.camera;
    const W = this.width, H = this.height;
    if (!cam || W < 2 || H < 2) return;
    const s = this.safe;
    // keep at least a fifth of the canvas usable whatever the insets say
    const l = Math.min(s.left, W * 0.8), r = Math.min(s.right, W * 0.8 - l);
    const t = Math.min(s.top, H * 0.8), b = Math.min(s.bottom, H * 0.8 - t);
    const cx = (l + (W - r)) / 2, cy = (t + (H - b)) / 2;
    const ndcX = (cx - W / 2) / (W / 2), ndcY = (H / 2 - cy) / (H / 2);
    cam.projectionOffset = new Vec2(-ndcX, -ndcY);
  }

  /** Canvas point (CSS px) the view axis passes through: the centre of the safe area. */
  principalPoint() {
    const off = this.camera.camera?.projectionOffset ?? Vec2.ZERO;
    return { x: (this.width / 2) * (1 - off.x), y: (this.height / 2) * (1 + off.y) };
  }

  /** How much of the canvas the safe area spans (0.55..1): focus distances grow as it shrinks. */
  get safeFit() {
    const W = this.width, H = this.height;
    if (W < 2 || H < 2) return 1;
    const s = this.safe;
    return Math.max(0.55, Math.min(1, (W - s.left - s.right) / W, (H - s.top - s.bottom) / H));
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
    // a narrow safe area between HUD panels needs a little more distance to show the asset whole
    distance /= this.safeFit;
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

  /** Vertical field of view in degrees (10 to 120). */
  setFov(fov: number) {
    const f = Math.max(10, Math.min(120, fov));
    if (f === this.fov) return;
    this.fov = f;
    if (this.camera.camera) this.camera.camera.fov = f;
    this.requestRender();
  }

  /** Ease (or jump, in instant mode) to look from `position` at `target`; resolves when the camera is there. */
  lookFrom(position: Vec3Tuple, target: Vec3Tuple, seconds?: number) {
    const pose = poseLookingAt(position, target);
    const cam = positionOf(this.rig.current);
    const travel = Math.hypot(position[0] - cam[0], position[1] - cam[1], position[2] - cam[2]);
    this.requestRender();
    return this.rig.animate(pose, this.duration(seconds ?? Math.min(2.2, 0.8 + travel * 0.12)), 'path');
  }

  /**
   * A camera position `distance` from `point` that depends only on the point and the site: on the side
   * the site's start camera sees it from, with a gentle downward look (never straight above or below).
   * Agent go_to and orbit start here, so the same command always gives the same frames.
   */
  approachPose(point: Vec3Tuple, distance: number): { position: Vec3Tuple; target: Vec3Tuple } {
    const { position: start, target: startTarget } = this.site.camera;
    let dir: Vec3Tuple = [start[0] - point[0], start[1] - point[1], start[2] - point[2]];
    let horiz = Math.hypot(dir[0], dir[2]);
    if (horiz < 1e-3) {
      // the point is straight above or below the start camera: approach along the start view direction
      dir = [start[0] - startTarget[0], 0, start[2] - startTarget[2]];
      horiz = Math.hypot(dir[0], dir[2]);
      if (horiz < 1e-3) { dir = [0, 0, 1]; horiz = 1; }
    }
    const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
    const elev = Math.max(-0.2, Math.min(0.55, dir[1] / len));
    const h = Math.sqrt(1 - elev * elev);
    const d: Vec3Tuple = [(dir[0] / horiz) * h, elev, (dir[2] / horiz) * h];
    return { position: [point[0] + d[0] * distance, point[1] + d[1] * distance, point[2] + d[2] * distance], target: [...point] as Vec3Tuple };
  }

  reset(animate = true) {
    this.setFov(this.baseFov);
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
      // one pick render, then all the 1x1 depth readbacks in flight together
      const hits = await Promise.all(points.map((pt) => picker.getWorldPointAsync((pt.x / this.width) * w, (pt.y / this.height) * h)));
      return hits.map((p) => (p && Number.isFinite(p.x) ? p.distance(cam) : null));
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
    this.app.systems.gsplat?.off('frame:ready', this.onStreamFrame);
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
