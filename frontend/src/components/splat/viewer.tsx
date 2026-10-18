'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { SplatEngine, hasWebGL2, type LodStats, type MoveDirection, type Projection } from './engine';
import { EyeClient, describeCommand, parseViewPose, type EyeCommand, type EyeFramePost, type EyeMark, type EyeStatus } from './eye';
import { DEFECT_RADIUS, parseDefect, type DefectKind } from './defects';
import { SPLAT_SITES } from './sites';
import type { SplatPin, SplatViewerProps, Vec3Tuple } from './types';
import styles from './viewer.module.css';

type Phase = 'init' | 'loading' | 'preparing' | 'ready' | 'error' | 'nowebgl';

const SEVERITY_TEXT: Record<string, string> = { high: 'High severity', medium: 'Medium severity', low: 'Low severity', none: 'No open issue' };

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);
  return reduced;
}

const mb = (bytes: number) => `${(bytes / 1e6).toFixed(0)} MB`;
const num = (v: unknown, d: number) => (typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)) ? Number(v) : d);
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const DIRECTIONS: MoveDirection[] = ['forward', 'back', 'left', 'right', 'up', 'down'];

interface EyeHud { actor: string; label: string; busy: boolean; error: string | null; ms: number | null }
interface EyeDebug { status: EyeStatus; detail: string | null; executed: number; last: { id: string; action: string; ms: number; error: string | null; frames: number } | null }
const fmt = (n: number) => (Math.abs(n) < 1e-4 ? 0 : n).toFixed(3);

export default function SplatViewerImpl(props: SplatViewerProps) {
  const { siteId, pins, focus, editMode = false, className } = props;
  const site = SPLAT_SITES[siteId];
  const reducedMotion = usePrefersReducedMotion();

  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const markerRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<SplatEngine | null>(null);
  const dotEls = useRef(new Map<string, HTMLButtonElement>());
  const occluded = useRef(new Map<string, boolean>());
  const projections = useRef(new Map<string, Projection>());
  const pendingFocus = useRef<SplatViewerProps['focus']>(null);
  const hideTimer = useRef<number | null>(null);
  const eyeFrameRef = useRef<HTMLDivElement>(null);
  const eyeMarkRef = useRef<HTMLDivElement>(null);
  const eyeClient = useRef<EyeClient | null>(null);

  const [phase, setPhase] = useState<Phase>('init');
  const [progress, setProgress] = useState<{ loaded: number; total: number; unit: 'bytes' | 'files' }>({ loaded: 0, total: 0, unit: 'bytes' });
  const [stream, setStream] = useState<LodStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pulse, setPulse] = useState<{ tag: string; key: number } | null>(null);
  const [picked, setPicked] = useState<{ position: Vec3Tuple; source: 'surface' | 'ray' } | null>(null);
  const [rayDistance, setRayDistance] = useState(3);
  const [eyeStatus, setEyeStatus] = useState<{ status: EyeStatus; detail: string | null } | null>(null);
  const [eyeHud, setEyeHud] = useState<EyeHud | null>(null);
  const [eyeMark, setEyeMark] = useState<{ position: Vec3Tuple; note: string | null } | null>(null);
  const eye = props.eye;
  const fill = !!props.fill;
  const safe = props.safeArea;
  const st = safe?.top ?? 0, sr = safe?.right ?? 0, sb = safe?.bottom ?? 0, sl = safe?.left ?? 0;
  const poseEmit = useRef<{ key: string; at: number; timer: number | null }>({ key: '', at: 0, timer: null });
  const eyeOverlay = !!eye?.showOverlay;

  // latest props for engine callbacks
  const live = useRef({ pins, editMode, rayDistance, picked, hovered, props, reducedMotion, eyeMark, pulseTag: null as string | null });
  live.current = { pins, editMode, rayDistance, picked, hovered, props, reducedMotion, eyeMark, pulseTag: pulse?.tag ?? null };

  // ---- overlay layout (runs on camera change, imperatively) ------------------------------------

  const layout = useCallback(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const { pins: list, hovered: hov, picked: pick } = live.current;
    const w = engine.width, h = engine.height;
    for (const pin of list) {
      const el = dotEls.current.get(pin.assetTag);
      if (!el) continue;
      let pr = projections.current.get(pin.assetTag);
      if (!pr) { pr = { x: 0, y: 0, depth: 0, distance: 0, visible: false }; projections.current.set(pin.assetTag, pr); }
      engine.project(pin.position, pr);
      if (!pr.visible) {
        el.style.visibility = 'hidden';
        continue;
      }
      const hidden = occluded.current.get(pin.assetTag) === true;
      // fade with distance: full within 4 m, down to 35% at 20 m
      const fade = Math.max(0.35, Math.min(1, 1 - (pr.distance - 4) / 16));
      const target = pin.assetTag === live.current.pulseTag || pin.assetTag === hov;
      const opacity = hidden ? (target ? 0.6 : pin.estimated ? 0.22 : 0) : fade;
      el.style.visibility = opacity > 0 ? 'visible' : 'hidden';
      el.style.opacity = String(opacity);
      el.style.transform = `translate3d(${pr.x.toFixed(1)}px, ${pr.y.toFixed(1)}px, 0)`;
      el.dataset.occluded = hidden ? 'true' : 'false';
    }
    const card = cardRef.current;
    if (card && hov) {
      const pr = projections.current.get(hov);
      if (pr && pr.visible) {
        const cw = card.offsetWidth, ch = card.offsetHeight;
        let x = pr.x + 16;
        if (x + cw > w - 8) x = pr.x - 16 - cw;
        x = Math.max(8, x);
        const y = Math.max(8, Math.min(h - ch - 8, pr.y - ch / 2));
        card.style.transform = `translate3d(${x.toFixed(0)}px, ${y.toFixed(0)}px, 0)`;
        card.style.visibility = 'visible';
      } else {
        card.style.visibility = 'hidden';
      }
    }
    const marker = markerRef.current;
    if (marker && pick) {
      const pr = engine.project(pick.position, { x: 0, y: 0, depth: 0, distance: 0, visible: false });
      marker.style.visibility = pr.visible ? 'visible' : 'hidden';
      marker.style.transform = `translate3d(${pr.x.toFixed(1)}px, ${pr.y.toFixed(1)}px, 0)`;
    }
    // eye HUD: the region of the canvas the agent's frame covers, and the last mark
    const frameEl = eyeFrameRef.current;
    const eyeCfg = live.current.props.eye;
    if (frameEl && eyeCfg) {
      const c = engine.frameCrop(eyeCfg.frameWidth ?? 640, eyeCfg.frameHeight ?? 400);
      frameEl.style.transform = `translate3d(${c.sx.toFixed(0)}px, ${c.sy.toFixed(0)}px, 0)`;
      frameEl.style.width = `${c.sw.toFixed(0)}px`;
      frameEl.style.height = `${c.sh.toFixed(0)}px`;
    }
    const markEl = eyeMarkRef.current;
    const mark = live.current.eyeMark;
    if (markEl && mark) {
      const pr = engine.project(mark.position, { x: 0, y: 0, depth: 0, distance: 0, visible: false });
      markEl.style.visibility = pr.visible ? 'visible' : 'hidden';
      markEl.style.transform = `translate3d(${pr.x.toFixed(1)}px, ${pr.y.toFixed(1)}px, 0)`;
    }
    // camera pose for the HUD, at most ten times a second (leading and trailing)
    const onPose = live.current.props.onCameraChange;
    if (onPose) {
      const emit = poseEmit.current;
      const info = engine.cameraInfo();
      const key = `${info.position.join(',')}|${info.target.join(',')}|${w}x${h}`;
      if (key !== emit.key) {
        const fire = () => {
          const e = engineRef.current;
          if (!e) return;
          const cur = e.cameraInfo();
          emit.key = `${cur.position.join(',')}|${cur.target.join(',')}|${e.width}x${e.height}`;
          emit.at = performance.now();
          emit.timer = null;
          const pp = e.principalPoint();
          live.current.props.onCameraChange?.({ ...cur, principal: { x: Math.round(pp.x), y: Math.round(pp.y) } });
        };
        const wait = 100 - (performance.now() - emit.at);
        if (wait <= 0) fire();
        else if (emit.timer === null) emit.timer = window.setTimeout(fire, wait);
      }
    }
  }, []);

  // ---- engine lifecycle ------------------------------------------------------------------------

  useEffect(() => {
    const canvas = canvasRef.current;
    const root = rootRef.current;
    if (!canvas || !root) return;
    if (!hasWebGL2()) { setPhase('nowebgl'); return; }
    let cancelled = false;
    let engine: SplatEngine | null = null;
    setPhase('loading');
    setError(null);
    setProgress({ loaded: 0, total: 0, unit: 'bytes' });
    setStream(null);
    occluded.current.clear();

    const onClick = (x: number, y: number) => {
      const cur = live.current;
      if (!cur.editMode || !engine) return;
      void engine.pick(x, y).then((hit) => {
        if (!engine) return;
        const position = hit ?? engine.rayPoint(x, y, live.current.rayDistance);
        setPicked({ position, source: hit ? 'surface' : 'ray' });
        live.current.props.onPlacePin?.(position);
        engine.requestRender();
      });
    };

    SplatEngine.create({
      canvas,
      site,
      interactive: true,
      keyTarget: root,
      preferWebGPU: new URLSearchParams(window.location.search).get('splatRenderer') === 'webgpu',
      maxPixelRatio: live.current.props.fill ? 2 : 1.5,
      reducedMotion: live.current.reducedMotion,
      // a headless eye streams a smaller set: its frames are 640x400 and every move waits for the stream
      splatBudget: live.current.props.eye?.instant ? site.lod?.headlessBudget : undefined,
      onProgress: (loaded, total, unit) => { if (!cancelled) setProgress({ loaded, total, unit }); },
      onStream: (lod) => { if (!cancelled) setStream(lod); },
      onLoaded: () => { if (!cancelled) setPhase('preparing'); },
      onFirstFrame: () => {
        if (cancelled) return;
        setPhase('ready');
        const f = pendingFocus.current;
        pendingFocus.current = null;
        if (f) runFocus(f);
      },
      onError: (e) => { if (!cancelled) { setError(e.message); setPhase('error'); } },
      onCamera: () => layout(),
      onClick,
      onInteract: () => root.focus({ preventScroll: true }),
    }).then((e) => {
      if (cancelled) { e.destroy(); return; }
      engine = e;
      engineRef.current = e;
      if (process.env.NODE_ENV !== 'production') {
        (window as unknown as { __splat?: Record<string, SplatEngine> }).__splat = {
          ...((window as unknown as { __splat?: Record<string, SplatEngine> }).__splat ?? {}),
          [siteId]: e,
        };
      }
      const f = pendingFocus.current;
      if (f && f.action !== 'highlight') { pendingFocus.current = null; runFocus(f); }
    }).catch((err: unknown) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : String(err));
      setPhase('nowebgl');
    });

    return () => {
      cancelled = true;
      engine?.destroy();
      if (engineRef.current === engine) engineRef.current = null;
      engine = null;
    };
    // runFocus and layout are stable through refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId, attempt]);

  // fill mode renders at the device pixel ratio capped at 2 (1.5 otherwise)
  useEffect(() => {
    const e = engineRef.current;
    if (!e || phase !== 'ready') return;
    e.setPixelRatio(Math.max(0.5, Math.min(window.devicePixelRatio || 1, fill ? 2 : 1.5)));
  }, [fill, phase]);

  // HUD insets: shift the projection so targets sit between the panels
  useEffect(() => {
    const e = engineRef.current;
    if (!e) return;
    e.setSafeArea({ top: st, right: sr, bottom: sb, left: sl });
    layout();
  }, [st, sr, sb, sl, phase, layout]);

  // reduced motion can change while mounted
  useEffect(() => { engineRef.current?.setReducedMotion(reducedMotion); }, [reducedMotion]);

  // relayout when pins, hover or the pick marker change
  useEffect(() => {
    engineRef.current?.requestRender();
    layout();
  }, [pins, hovered, picked, pulse, phase, eyeMark, eyeOverlay, layout]);

  // ---- agent eye -------------------------------------------------------------------------------

  const runEye = useCallback(async (cmd: EyeCommand) => {
    const engine = engineRef.current;
    const client = eyeClient.current;
    const cfg = live.current.props.eye;
    if (!engine || !client || !cfg) return;
    const t0 = performance.now();
    const fw = cfg.frameWidth ?? 640, fh = cfg.frameHeight ?? 400;
    const actorName = cmd.actorName ?? cmd.actor ?? 'agent';
    const label = describeCommand(cmd);
    engine.instant = !!cfg.instant;
    engine.rig.locked = true;
    if (cmd.action !== 'mark') setEyeMark(null);
    setEyeHud({ actor: actorName, label, busy: true, error: null, ms: null });
    const pinsNow = live.current.pins;
    const p = cmd.params;
    const assetTag = typeof p.assetTag === 'string' ? p.assetTag : null;
    let posted = 0;
    let lastError: string | null = null;
    // orbit may carry a defect for the vision tests; it is removed when the command ends. The frame's `synthetic` and
    // `defect` fields say so; no words are drawn into the pixels (`labelled` stays false).
    const defect: DefectKind = cmd.action === 'orbit' ? parseDefect(typeof p.defect === 'string' ? p.defect : null) : 'none';
    const burnLabel: string | null = null;

    const pinOrNull = (): Vec3Tuple | null => {
      if (cmd.pin) return cmd.pin;
      const want = (assetTag ?? '').toLowerCase();
      return pinsNow.find((x) => x.assetTag.toLowerCase() === want)?.position ?? null;
    };
    const findPin = () => {
      const pin = pinOrNull();
      if (!pin) throw new Error(assetTag ? `no pin for ${assetTag} on ${cfg.siteId}` : 'assetTag is required');
      return pin;
    };
    // go_to and orbit never start from the current view: an exact viewPose when the command has one,
    // otherwise a pose from the pin and the site's fixed approach direction (same command, same frames)
    const viewPose = cmd.action === 'go_to' || cmd.action === 'orbit' ? parseViewPose(p.viewPose) : null;
    const startPose: EyeFramePost['startPose'] = cmd.action === 'go_to' || cmd.action === 'orbit' ? (viewPose ? 'viewPose' : 'approach') : undefined;

    const post = async (index: number, count: number, extra: Partial<EyeFramePost> = {}, draw?: (ctx: CanvasRenderingContext2D) => void) => {
      const s0 = performance.now();
      // two rendered frames after the camera settles; the second one is the frame we keep
      await engine.settle({ timeoutMs: 20000, frames: 1 });
      const s1 = performance.now();
      const shot = await engine.captureJpeg({ width: fw, height: fh, quality: 0.85, label: burnLabel, draw: draw ? (ctx) => draw(ctx) : undefined });
      const s2 = performance.now();
      const visiblePins = await engine.visiblePins(pinsNow, shot.crop);
      const s3 = performance.now();
      const timings = { moveMs: Math.round(s0 - t0), settleMs: Math.round(s1 - s0), captureMs: Math.round(s2 - s1), pinsMs: Math.round(s3 - s2) };
      const frame: EyeFramePost = {
        commandId: cmd.id,
        rendererId: cfg.rendererId,
        action: cmd.action,
        actor: cmd.actor,
        index,
        count,
        final: index === count - 1,
        jpegBase64: shot.dataUrl.slice(shot.dataUrl.indexOf(',') + 1),
        width: fw,
        height: fh,
        camera: engine.cameraInfo(),
        visiblePins,
        assetTag,
        renderMs: Math.round(performance.now() - t0),
        timings,
        ...(startPose ? { startPose } : {}),
        synthetic: defect !== 'none',
        defect,
        labelled: !!burnLabel,
        at: new Date().toISOString(),
        ...extra,
      };
      const res = await client.postFrame(frame);
      posted++;
      const { jpegBase64: _jpeg, ...meta } = frame;
      void _jpeg;
      live.current.props.onFrame?.({ ...meta, dataUrl: shot.dataUrl, actorName, posted: res.ok, frameId: res.frameId, frameUrl: res.frameUrl });
    };

    try {
      switch (cmd.action) {
        case 'look':
          await post(0, 1);
          break;
        case 'move': {
          const dir = String(p.direction ?? 'forward').toLowerCase() as MoveDirection;
          if (!DIRECTIONS.includes(dir)) throw new Error(`direction must be one of ${DIRECTIONS.join(', ')}`);
          await engine.moveBy(dir, clamp(num(p.meters, 1), 0.1, 5));
          await post(0, 1);
          break;
        }
        case 'turn':
          await engine.turnBy(clamp(num(p.yawDeg, 0), -180, 180), clamp(num(p.pitchDeg, 0), -85, 85));
          await post(0, 1);
          break;
        case 'go_to': {
          engine.setFov(viewPose?.fov ?? engine.baseFov);
          if (viewPose) {
            await engine.lookFrom(viewPose.position, viewPose.target);
          } else {
            const a = engine.approachPose(findPin(), clamp(num(p.distance, 1.8), 0.4, 8));
            await engine.lookFrom(a.position, a.target);
          }
          await post(0, 1);
          break;
        }
        case 'orbit': {
          // around the pin (or the viewPose target when the asset has no pin), starting at the viewPose position
          const pin = viewPose ? pinOrNull() ?? viewPose.target : findPin();
          const n = Math.round(clamp(num(p.frames, 8), 4, 16));
          if (defect !== 'none') engine.setDefect(defect, pin, clamp(num(p.defectRadius, DEFECT_RADIUS), 0.05, 1));
          engine.setFov(viewPose?.fov ?? engine.baseFov);
          const from = viewPose ? viewPose.position : engine.approachPose(pin, clamp(num(p.distance, 1.8), 0.4, 8)).position;
          await engine.lookFrom(from, pin);
          const start = engine.rig.current.yaw;
          for (let k = 0; k < n; k++) {
            if (k > 0) await engine.orbitTo(pin, start + (k * 360) / n);
            setEyeHud({ actor: actorName, label: `${label} · ${k + 1}/${n}`, busy: true, error: null, ms: null });
            await post(k, n);
          }
          break;
        }
        case 'mark': {
          const x = clamp(num(p.x, 0.5), 0, 1), y = clamp(num(p.y, 0.5), 0, 1);
          const note = typeof p.note === 'string' ? p.note : null;
          if (!engine.rig.settled) await engine.settle({ timeoutMs: 20000, frames: 1 });
          const crop = engine.frameCrop(fw, fh);
          const px = crop.sx + x * crop.sw, py = crop.sy + y * crop.sh;
          const hit = await engine.pick(px, py);
          const world = hit ?? engine.rayPoint(px, py, 3);
          setEyeMark({ position: world, note });
          const record: EyeMark = { x, y, world: world.map((v) => +v.toFixed(4)) as Vec3Tuple, hit: !!hit, note };
          // `mark` for the backends that read it, `annotation` (same record) for the newer ones
          await post(0, 1, { mark: record, annotation: { ...record } }, (ctx) => {
            const cx = x * fw, cy = y * fh;
            ctx.lineWidth = 4; ctx.strokeStyle = '#000';
            ctx.beginPath(); ctx.arc(cx, cy, 11, 0, Math.PI * 2); ctx.stroke();
            ctx.lineWidth = 2; ctx.strokeStyle = '#fff';
            ctx.beginPath(); ctx.arc(cx, cy, 11, 0, Math.PI * 2); ctx.stroke();
            ctx.fillStyle = '#fff'; ctx.fillRect(cx - 1, cy - 1, 2, 2);
          });
          break;
        }
        default:
          throw new Error(`unknown eye action ${String(cmd.action)}`);
      }
    } catch (e) {
      lastError = e instanceof Error ? e.message : String(e);
      // complete the command anyway: the current view plus the reason it failed
      if (posted === 0) { try { await post(0, 1, { error: lastError }); } catch { /* engine gone */ } }
    } finally {
      if (defect !== 'none') engine.setDefect('none', [0, 0, 0], 0);
      engine.rig.locked = false;
      const ms = Math.round(performance.now() - t0);
      setEyeHud({ actor: actorName, label, busy: false, error: lastError, ms });
      const dbg = (window as unknown as { __eye?: EyeDebug }).__eye;
      if (dbg) dbg.last = { id: cmd.id, action: cmd.action, ms, error: lastError, frames: posted };
    }
  }, []);

  // tell a headless worker that this page cannot render, so it can retry with other GPU flags
  useEffect(() => {
    if (!eye || (phase !== 'nowebgl' && phase !== 'error')) return;
    (window as unknown as { __eye?: unknown }).__eye = { status: 'unavailable', detail: error ?? (phase === 'nowebgl' ? 'WebGL2 unavailable' : 'scan failed to load'), executed: 0, last: null };
  }, [eye, phase, error]);

  useEffect(() => {
    if (!eye || phase !== 'ready') return;
    const debug: EyeDebug = { status: 'connecting', detail: null, executed: 0, last: null };
    (window as unknown as { __eye?: EyeDebug }).__eye = debug;
    const client = new EyeClient(eye, {
      onStatus: (status, detail) => { debug.status = status; debug.detail = detail; setEyeStatus({ status, detail }); },
      execute: async (cmd) => { await runEye(cmd); debug.executed++; },
    });
    eyeClient.current = client;
    setEyeStatus({ status: 'connecting', detail: null });
    client.start();
    return () => { client.stop(); if (eyeClient.current === client) eyeClient.current = null; };
    // restart only when the identity of the eye changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eye?.siteId, eye?.rendererId, eye?.apiBase, phase, runEye]);

  // ---- occlusion: one low-resolution pick render after the camera settles -----------------------

  const headlessEye = !!eye?.instant;
  useEffect(() => {
    // nobody watches a headless eye: skip the dot occlusion renders
    if (phase !== 'ready' || headlessEye) return;
    let busy = false;
    let lastKey = '';
    const timer = window.setInterval(() => {
      const engine = engineRef.current;
      if (!engine || busy || document.hidden) return;
      if (engine.idleMs < 400 || engine.rig.animating || engine.rig.locked) return;
      const pose = engine.rig.current;
      const key = [pose.yaw, pose.pitch, pose.distance, ...pose.target].map((n) => n.toFixed(3)).join(',') + `|${live.current.pins.length}|${engine.width}x${engine.height}`;
      if (key === lastKey) return;
      const list = live.current.pins;
      const candidates: { pin: SplatPin; pr: Projection }[] = [];
      for (const pin of list) {
        const pr = engine.project(pin.position, { x: 0, y: 0, depth: 0, distance: 0, visible: false });
        if (pr.visible && pr.x >= 0 && pr.y >= 0 && pr.x < engine.width && pr.y < engine.height) candidates.push({ pin, pr });
        else occluded.current.delete(pin.assetTag);
      }
      busy = true;
      lastKey = key;
      void engine.surfaceDistances(candidates.map((c) => ({ x: c.pr.x, y: c.pr.y }))).then((dists) => {
        busy = false;
        candidates.forEach((c, i) => {
          const surf = dists[i];
          const margin = Math.max(0.35, c.pr.distance * 0.12);
          occluded.current.set(c.pin.assetTag, surf !== null && surf < c.pr.distance - margin);
        });
        layout();
      });
    }, 500);
    return () => window.clearInterval(timer);
  }, [phase, layout, headlessEye]);

  // ---- adaptive resolution for slow GPUs -------------------------------------------------------

  useEffect(() => {
    // agents read the frames: a headless eye keeps full resolution however slow it renders
    if (phase !== 'ready' || headlessEye) return;
    let slow = 0;
    const timer = window.setInterval(() => {
      const engine = engineRef.current;
      if (!engine) return;
      const busy = engine.rig.animating || engine.idleMs < 150;
      const fps = engine.stats.fps;
      if (busy && fps !== null && fps < 22) slow++;
      else slow = 0;
      const floor = live.current.props.fill ? 1 : 0.75;
      if (slow >= 3 && engine.stats.pixelRatio > floor) {
        engine.setPixelRatio(Math.max(floor, +(engine.stats.pixelRatio - 0.25).toFixed(2)));
        slow = 0;
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phase, headlessEye]);

  // ---- focus commands --------------------------------------------------------------------------

  const runFocus = useCallback((f: NonNullable<SplatViewerProps['focus']>) => {
    const engine = engineRef.current;
    if (!engine) { pendingFocus.current = f; return; }
    const pin = f.assetTag ? live.current.pins.find((p) => p.assetTag === f.assetTag) : undefined;
    const pulseTag = (tag: string) => setPulse({ tag, key: Date.now() });
    switch (f.action) {
      case 'reset':
        engine.reset();
        break;
      case 'focus':
        if (pin) { engine.focusOn(pin.position); pulseTag(pin.assetTag); }
        break;
      case 'orbit':
        if (pin) { engine.orbitAround(pin.position); pulseTag(pin.assetTag); }
        break;
      case 'highlight':
        if (pin) pulseTag(pin.assetTag);
        break;
    }
  }, []);

  const nonce = focus?.nonce;
  useEffect(() => {
    if (!focus) return;
    runFocus(focus);
    // the nonce is the trigger; the rest of the object travels with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, runFocus]);

  // follow an agent's camera (humans watching a walkthrough); an eye command running here already owns the camera
  const followNonce = props.follow?.nonce;
  useEffect(() => {
    const f = live.current.props.follow;
    const engine = engineRef.current;
    if (!f || !engine || phase !== 'ready' || engine.rig.locked) return;
    if (typeof f.fov === 'number' && Number.isFinite(f.fov)) engine.setFov(f.fov);
    void engine.lookFrom(f.position, f.target);
  }, [followNonce, phase]);

  useEffect(() => {
    if (!pulse) return;
    // restart the ring animation when the same dot is pulsed again
    const el = dotEls.current.get(pulse.tag);
    if (el && el.dataset.pulse === 'true') { el.dataset.pulse = 'false'; void el.offsetWidth; el.dataset.pulse = 'true'; }
    const t = window.setTimeout(() => setPulse((p) => (p && p.key === pulse.key ? null : p)), 3800);
    return () => window.clearTimeout(t);
  }, [pulse]);

  useEffect(() => { if (!editMode) setPicked(null); }, [editMode]);

  // ---- hover -----------------------------------------------------------------------------------

  const showCard = (tag: string) => {
    if (hideTimer.current) { window.clearTimeout(hideTimer.current); hideTimer.current = null; }
    if (live.current.hovered !== tag) {
      setHovered(tag);
      live.current.props.onPinHover?.(tag);
    }
  };
  const hideCard = () => {
    if (hideTimer.current) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = null;
      setHovered(null);
      live.current.props.onPinHover?.(null);
    }, 140);
  };
  const clickPin = (pin: SplatPin) => {
    props.onPinClick?.(pin.assetTag);
    engineRef.current?.focusOn(pin.position);
    setPulse({ tag: pin.assetTag, key: Date.now() });
  };

  const hoveredPin = hovered ? pins.find((p) => p.assetTag === hovered) : undefined;
  const pct = progress.total > 0 ? Math.min(1, progress.loaded / progress.total) : 0;
  const chunkProgress = progress.unit === 'files' && progress.total > 0;
  const showPoster = phase !== 'ready';
  const streaming = phase === 'ready' && !!site.lod && !!stream && stream.refining && !stream.complete && stream.pendingFiles > 0;

  return (
    <div
      ref={rootRef}
      className={[styles.root, fill ? styles.fill : '', editMode ? styles.editing : '', className ?? ''].filter(Boolean).join(' ')}
      tabIndex={0}
      role="application"
      aria-label={`${site.name} 3D scan. Drag to orbit, right-drag to pan, scroll to zoom, W A S D to fly.`}
      data-phase={phase}
    >
      {showPoster && (
        // eslint-disable-next-line @next/next/no-img-element
        <img className={[styles.poster, phase === 'nowebgl' || phase === 'error' ? styles.posterFull : ''].join(' ')} src={site.thumbnailUrl} alt={`${site.name}, published still of the scan`} draggable={false} />
      )}
      <canvas ref={canvasRef} className={styles.canvas} style={{ visibility: phase === 'nowebgl' ? 'hidden' : 'visible' }} />

      <div className={styles.dots} aria-hidden={phase !== 'ready'}>
        {phase === 'ready' && pins.map((pin) => (
          <button
            key={pin.assetTag}
            type="button"
            ref={(el) => {
              if (!el) return;
              dotEls.current.set(pin.assetTag, el);
              return () => { if (dotEls.current.get(pin.assetTag) === el) dotEls.current.delete(pin.assetTag); };
            }}
            className={styles.dot}
            style={{ visibility: 'hidden' }}
            data-severity={pin.severity ?? 'none'}
            data-estimated={pin.estimated ? 'true' : 'false'}
            data-active={hovered === pin.assetTag ? 'true' : 'false'}
            data-pulse={pulse?.tag === pin.assetTag ? 'true' : 'false'}
            data-verdict={pin.assessment?.verdict ?? 'none'}
            data-tag={pin.assetTag}
            aria-label={`${pin.label}${pin.estimated ? ', estimated position' : ''}${pin.assessment ? `. ${pin.assessment.description ?? pin.assessment.text}` : ''}`}
            onPointerEnter={() => showCard(pin.assetTag)}
            onPointerLeave={hideCard}
            onFocus={() => showCard(pin.assetTag)}
            onBlur={hideCard}
            onClick={(e) => { e.stopPropagation(); clickPin(pin); }}
          >
            {pin.assessment
              ? <span className={styles.verdict} data-verdict={pin.assessment.verdict}>{eyeOverlay && <b>{pin.assetTag}</b>}{pin.assessment.text}</span>
              : eyeOverlay && <span className={styles.tag}>{pin.assetTag}</span>}
          </button>
        ))}
        {editMode && picked && <div ref={markerRef} className={styles.marker} />}
      </div>

      {phase === 'ready' && hoveredPin && (
        <div ref={cardRef} className={styles.card} style={{ visibility: 'hidden' }} onPointerEnter={() => showCard(hoveredPin.assetTag)} onPointerLeave={hideCard} role="tooltip">
          {props.renderCard ? props.renderCard(hoveredPin.assetTag) : (
            <>
              <div className={styles.cardTitle}>{hoveredPin.label}</div>
              <div className={styles.cardTag}>{hoveredPin.assetTag}</div>
              <div className={styles.cardLine}>{SEVERITY_TEXT[hoveredPin.severity ?? 'none']}{hoveredPin.issueIds?.length ? ` · ${hoveredPin.issueIds.length} open issue${hoveredPin.issueIds.length > 1 ? 's' : ''}` : ''}</div>
            </>
          )}
          {hoveredPin.estimated && (
            <div className={styles.cardEstimated}><strong>Estimated position.</strong> Not yet placed on the scan by an operator.</div>
          )}
        </div>
      )}

      {eye && phase === 'ready' && (
        <>
          {eyeOverlay && (
            <div ref={eyeFrameRef} className={styles.eyeFrame} aria-hidden="true">
              <span className={styles.eyeCross} />
            </div>
          )}
          {eyeOverlay && eyeMark && (
            <div ref={eyeMarkRef} className={styles.eyeMark} aria-hidden="true">
              {eyeMark.note && <span className={styles.tag}>{eyeMark.note}</span>}
            </div>
          )}
          <div className={styles.eyeHud} role="status" aria-live="polite" style={safe ? { top: 12 + st, left: 12 + sl } : undefined}>
            {/* without the overlay only the offline state is shown, so a host HUD can own the rest */}
            {(eyeOverlay || eyeStatus?.status === 'offline') && (
              <div className={styles.eyeChip} data-eye-status={eyeStatus?.status ?? 'connecting'}>
                {eyeStatus?.status === 'offline' ? 'Eye offline · retrying every 5 s'
                  : eyeStatus?.status === 'online' ? `Agent eye · ${eye.rendererId}` : 'Agent eye · connecting'}
              </div>
            )}
            {eyeOverlay && eyeHud && (
              <div className={styles.eyeAction} data-busy={eyeHud.busy ? 'true' : 'false'}>
                <strong>{eyeHud.actor}</strong> {eyeHud.label}
                {eyeHud.error ? <span className={styles.eyeError}> · {eyeHud.error}</span> : eyeHud.ms !== null ? <span className={styles.eyeMs}> · {(eyeHud.ms / 1000).toFixed(1)} s</span> : null}
              </div>
            )}
          </div>
        </>
      )}

      {editMode && phase === 'ready' && (
        <div className={styles.editPanel} style={{ top: 12 + st + (eye ? 84 : 0), left: 12 + sl }}>
          <div className={styles.editTitle}>Place pins · operator tool</div>
          <div className={styles.overlayText}>Click the scan to pick the point under the cursor.</div>
          {picked ? (
            <div className={styles.coords}>
              x {fmt(picked.position[0])} y {fmt(picked.position[1])} z {fmt(picked.position[2])}
              <div className={styles.overlayText}>{picked.source === 'surface' ? 'Picked on the splat surface' : `No surface under the cursor: ray at ${rayDistance.toFixed(1)} m`}</div>
            </div>
          ) : <div className={styles.coords}>No point picked yet</div>}
          <label className={styles.range}>
            Ray distance when nothing is hit: {rayDistance.toFixed(1)} m
            <input type="range" min={0.5} max={15} step={0.1} value={rayDistance} onChange={(e) => setRayDistance(Number(e.target.value))} />
          </label>
        </div>
      )}

      {(phase === 'loading' || phase === 'preparing' || phase === 'init') && (
        <div className={styles.overlay} role="status" aria-live="polite">
          <div className={styles.overlayInner}>
            <div className={styles.overlayTitle}>{phase === 'preparing' ? (site.lod ? 'Streaming the scan' : 'Preparing the scan') : `Loading ${site.name}`}</div>
            <div className={styles.track}>
              {(phase === 'preparing' && !chunkProgress) || progress.total === 0
                ? <div className={`${styles.trackFill} ${styles.indeterminate}`} />
                : <div className={styles.trackFill} style={{ transform: `scaleX(${pct})` }} />}
            </div>
            <div className={styles.numbers}>
              {phase === 'preparing'
                ? site.lod
                  ? `Coarsest level first${chunkProgress ? ` · ${progress.loaded} of ${progress.total} chunk files` : ''} · ${(site.gaussians / 1e6).toFixed(2)} M gaussians in ${site.lod.levels} levels`
                  : `${(site.gaussians / 1e6).toFixed(2)} M gaussians`
                : progress.total > 0 ? `${Math.round(pct * 100)}% · ${mb(progress.loaded)} of ${mb(progress.total)}` : 'Connecting'}
            </div>
          </div>
        </div>
      )}

      {(phase === 'nowebgl' || phase === 'error') && (
        <div className={styles.overlay}>
          <div className={styles.overlayInner}>
            <div className={styles.overlayTitle}>{phase === 'nowebgl' ? 'Showing the published still' : 'The scan did not load'}</div>
            <div className={styles.overlayText}>
              {phase === 'nowebgl' ? 'This browser cannot draw the 3D scan (WebGL2 is unavailable).' : error}
            </div>
            {phase === 'error' && <button type="button" className={styles.button} onClick={() => setAttempt((a) => a + 1)}>Try again</button>}
          </div>
        </div>
      )}

      {streaming && stream && (
        <div className={styles.streamChip} role="status" aria-live="polite" style={safe ? { top: 12 + st, right: 12 + sr } : undefined}>
          Streaming detail · {stream.pendingFiles} chunk file{stream.pendingFiles === 1 ? '' : 's'} to go
        </div>
      )}

      <div className={styles.credit} style={safe ? { left: 12 + sl, bottom: 12 + sb } : undefined}>
        Scan <a href={site.sceneUrl} target="_blank" rel="noreferrer">{site.sceneTitle}</a> by {site.author} on SuperSplat
      </div>
      {phase === 'ready' && !fill && (
        <div className={styles.tools} style={safe ? { right: 12 + sr, bottom: 12 + sb } : undefined}>
          <span className={styles.hint}>Drag to orbit · right-drag to pan · scroll to zoom · WASD to fly · double-click to pivot</span>
          <button type="button" className={styles.button} onClick={() => engineRef.current?.reset()}>Reset view</button>
        </div>
      )}
    </div>
  );
}
