'use client';

import { useEffect, useRef, useState } from 'react';
import { SPLAT_SITE_IDS, getSplatSite } from '@/components/splat/sites';
import { parseDefect, type DefectKind } from '@/components/splat/defects';
import type { Vec3Tuple } from '@/components/splat/types';
import type { SplatEngine } from '@/components/splat/engine';
import styles from './capture.module.css';

export interface CaptureParams {
  site: string;
  asset: string;
  frames: number;
  defect: string;
  pos: string | null;
  arc: number;
  radius: number;
  elev: number;
  fov: number;
  size: number;
  defectRadius: number;
  /** Probe lines of sight and centre the arc on the clearest side. */
  smart: boolean;
  /**
   * Burn "synthetic defect: <kind>" into the bottom-left of defected frames (default, for people).
   * With `label=0` the pixels stay clean and window.__frames holds {dataUrl, synthetic, defect, index}.
   */
  label: boolean;
}

/** One frame when `label=0`: the label travels as metadata instead of pixels. */
export interface CaptureFrame { index: number; dataUrl: string; synthetic: boolean; defect: DefectKind }

export interface CaptureResult {
  site: string;
  asset: string;
  pin: Vec3Tuple | null;
  pinSource: 'scene' | 'components' | 'query' | null;
  pinKind: string | null;
  frames: number;
  size: number;
  fov: number;
  radius: number;
  arc: number;
  elev: number;
  defect: DefectKind;
  defectRadius: number;
  synthetic: boolean;
  source: string;
  timings: Record<string, number>;
  /** Line-of-sight probe: which of 12 directions see the pin, and the chosen centre index. */
  probe?: { method: 'centres' | 'depth'; clear: boolean[]; counts?: number[]; centre: number };
  /** Whether the defect label is burned into the pixels (false with `label=0`). */
  labelled: boolean;
  error?: string;
}

declare global {
  interface Window {
    /** JPEG data URLs; with `label=0`, {dataUrl, synthetic, defect, index} objects. */
    __frames?: (string | CaptureFrame)[];
    /** Per-frame metadata in both modes. */
    __frameMeta?: { index: number; synthetic: boolean; defect: DefectKind; labelled: boolean }[];
    __done?: boolean;
    __capture?: CaptureResult;
    __error?: string;
  }
}

type Json = unknown;

const isObj = (v: Json): v is Record<string, Json> => !!v && typeof v === 'object' && !Array.isArray(v);
const vec = (v: Json): Vec3Tuple | null => {
  if (isObj(v) && [v.x, v.y, v.z].every((n) => typeof n === 'number' && Number.isFinite(n))) return [v.x as number, v.y as number, v.z as number];
  if (Array.isArray(v) && v.length === 3 && v.every((n) => typeof n === 'number' && Number.isFinite(n))) return v as Vec3Tuple;
  return null;
};

/** Find the asset record anywhere in a JSON payload, matched by tag, assetTag or id. */
function findAsset(payload: Json, tag: string): Record<string, Json> | null {
  const want = tag.trim().toLowerCase();
  const seen = new Set<Json>();
  const walk = (node: Json, depth: number): Record<string, Json> | null => {
    if (depth > 6 || !node || typeof node !== 'object' || seen.has(node)) return null;
    seen.add(node);
    if (Array.isArray(node)) {
      for (const item of node) { const hit = walk(item, depth + 1); if (hit) return hit; }
      return null;
    }
    const rec = node as Record<string, Json>;
    const keys = ['assetTag', 'tag', 'id'];
    if (keys.some((k) => typeof rec[k] === 'string' && (rec[k] as string).toLowerCase() === want)) return rec;
    for (const v of Object.values(rec)) { const hit = walk(v, depth + 1); if (hit) return hit; }
    return null;
  };
  return walk(payload, 0);
}

async function resolvePin(site: string, asset: string, pos: string | null): Promise<{ pin: Vec3Tuple; source: CaptureResult['pinSource']; kind: string | null }> {
  if (asset) {
    for (const [path, source] of [['scene', 'scene'], ['components', 'components']] as const) {
      try {
        const res = await fetch(`/api/properties/${encodeURIComponent(site)}/${path}`, { cache: 'no-store' });
        if (!res.ok) continue;
        const rec = findAsset(await res.json(), asset);
        if (!rec) continue;
        const pin = vec(rec.pin) ?? vec(rec.pin3d) ?? vec(rec.worldPosition);
        if (pin) return { pin, source, kind: typeof rec.kind === 'string' ? rec.kind : null };
      } catch { /* try the next source */ }
    }
  }
  if (pos) {
    const parts = pos.split(',').map(Number);
    if (parts.length === 3 && parts.every(Number.isFinite)) return { pin: parts as Vec3Tuple, source: 'query', kind: null };
  }
  throw new Error(`no 3-D pin for ${asset || '(no asset)'} on ${site}: the backend has none and no pos=x,y,z was given`);
}

export default function CaptureClient(params: CaptureParams) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState('starting');
  const [frames, setFrames] = useState<string[]>([]);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const canvas = canvasRef.current!;
    const site = getSplatSite(params.site);
    const defect = parseDefect(params.defect);
    const label = defect === 'none' || !params.label ? null : `synthetic defect: ${defect}`;
    const t0 = performance.now();
    const timings: Record<string, number> = {};
    const mark = (k: string) => { timings[k] = Math.round(performance.now() - t0); };
    const result: CaptureResult = {
      site: params.site, asset: params.asset, pin: null, pinSource: null, pinKind: null,
      frames: params.frames, size: params.size, fov: params.fov, radius: params.radius, arc: params.arc, elev: params.elev,
      defect, defectRadius: params.defectRadius, synthetic: defect !== 'none',
      source: site ? site.metaUrl : '', timings, labelled: !!label,
    };
    window.__frames = [];
    window.__frameMeta = [];
    window.__done = false;
    window.__capture = result;
    let engine: SplatEngine | null = null;

    const fail = (e: unknown) => {
      const msg = e instanceof Error ? e.message : String(e);
      result.error = msg;
      window.__error = msg;
      window.__done = true;
      setStatus(`error: ${msg}`);
    };

    (async () => {
      if (!site) throw new Error(`unknown site ${params.site}; expected one of ${SPLAT_SITE_IDS.join(', ')}`);
      setStatus('resolving pin');
      const { pin, source, kind } = await resolvePin(params.site, params.asset, params.pos);
      result.pin = pin; result.pinSource = source; result.pinKind = kind;
      mark('pin');
      setStatus('loading scan');
      const { SplatEngine } = await import('@/components/splat/engine');
      const firstFrame = new Promise<void>((resolve, reject) => {
        void SplatEngine.create({
          canvas,
          site,
          interactive: false,
          maxPixelRatio: 1,
          size: { width: params.size, height: params.size },
          fov: params.fov,
          onDemand: false,
          reducedMotion: true,
          // streamed captures: the headless budget (fewer chunk files per pose, frames are small)
          splatBudget: site.lod?.headlessBudget,
          onLoaded: () => { mark('downloaded'); setStatus('preparing'); },
          onFirstFrame: () => { mark('firstFrame'); resolve(); },
          onError: reject,
        }).then((e) => {
          engine = e;
          if (defect !== 'none') e.setDefect(defect, pin, params.defectRadius);
        }, reject);
      });
      await firstFrame;
      const eng = engine as SplatEngine | null;
      if (!eng) throw new Error('engine did not start');

      // orbit centred on the clearest side of the pin: probe 12 directions with a small depth pick
      // and centre the arc where the line of sight to the pin is open most often; ties go to the side
      // facing the site's start camera (the open side of the room)
      const { poseLookingAt } = await import('@/components/splat/camera-rig');
      const cam = site.camera.position;
      const elev = (params.elev * Math.PI) / 180;
      const fromAngle = (a: number): Vec3Tuple => [
        pin[0] + Math.cos(a) * Math.cos(elev) * params.radius,
        pin[1] + Math.sin(elev) * params.radius,
        pin[2] + Math.sin(a) * Math.cos(elev) * params.radius,
      ];
      let base = Math.atan2(cam[2] - pin[2], cam[0] - pin[0]);
      const full = params.arc >= 359.5;
      if (params.smart) {
        setStatus('probing lines of sight');
        const steps = 12;
        let clear: boolean[] = [];
        let counts: number[] | undefined;
        let method: 'centres' | 'depth' = 'centres';
        // a streamed (LOD) capture keeps no single centre array, and its coarse levels hold fewer, larger
        // gaussians that a centre count underrates as occluders: it takes the depth probe
        const centers = eng.splat?.gsplat?.resource?.centers;
        const cams = Array.from({ length: steps }, (_, k) => fromAngle(base + (k * 2 * Math.PI) / steps));
        if (centers && eng.splat) {
          // the splat centres live in the model frame: bring the pin and cameras into it
          const { Mat4, Vec3 } = await import('playcanvas');
          const inv = new Mat4().copy(eng.splat.getWorldTransform()).invert();
          const toModel = (p: Vec3Tuple): Vec3Tuple => { const v = inv.transformPoint(new Vec3(p[0], p[1], p[2])); return [v.x, v.y, v.z]; };
          const { sightlineCounts } = await import('@/components/splat/sightline');
          counts = sightlineCounts(centers, toModel(pin), cams.map(toModel));
          clear = counts.map((c) => c < 24);
        } else {
          method = 'depth';
          for (let k = 0; k < steps; k++) {
            eng.setPose(poseLookingAt(cams[k], pin));
            await eng.settle({ timeoutMs: 30000, frames: 1 });
            const [d] = await eng.surfaceDistances([{ x: params.size / 2, y: params.size / 2 }], 0.25);
            clear.push(d === null || d > params.radius - 0.15);
          }
        }
        const half = Math.max(0, Math.round((Math.min(params.arc, 360) / 360) * steps / 2));
        let best = 0, bestScore = -Infinity;
        for (let k = 0; k < steps; k++) {
          let score = 0;
          for (let j = -half; j <= half; j++) score += clear[(k + j + steps) % steps] ? 1 : 0;
          score -= Math.min(k, steps - k) * 0.01; // prefer the open side on ties
          if (score > bestScore) { bestScore = score; best = k; }
        }
        result.probe = { method, clear, counts, centre: best };
        base += (best * 2 * Math.PI) / steps;
        mark('probe');
      }
      const n = params.frames;
      const out: string[] = [];
      for (let i = 0; i < n; i++) {
        const t = full ? i / n : n === 1 ? 0.5 : i / (n - 1);
        const a = base + ((t - (full ? 0 : 0.5)) * params.arc * Math.PI) / 180;
        eng.setPose(poseLookingAt(fromAngle(a), pin));
        setStatus(`frame ${i + 1} of ${n}`);
        await eng.settle({ timeoutMs: 60000, frames: 1 });
        out.push((await eng.captureJpeg({ width: params.size, height: params.size, quality: 0.92, label })).dataUrl);
        window.__frameMeta = out.map((_, index) => ({ index, synthetic: defect !== 'none', defect, labelled: !!label }));
        window.__frames = params.label ? out.slice() : out.map((dataUrl, index) => ({ index, dataUrl, synthetic: defect !== 'none', defect }));
        setFrames(out.slice());
      }
      mark('done');
      timings.sortMs = eng.stats.lastSortMs ?? -1;
      window.__done = true;
      setStatus(`done: ${n} frames`);
    })().catch(fail);

    return () => { /* the capture page runs once; the engine lives until the tab closes */ };
  }, [params]);

  return (
    <main className={styles.page}>
      <canvas ref={canvasRef} className={styles.canvas} width={params.size} height={params.size} style={{ width: params.size, height: params.size }} />
      <div className={styles.meta}>
        <div className={styles.status} data-testid="capture-status">{status}</div>
        <div className={styles.note}>Frames rendered from the hosted capture{parseDefect(params.defect) !== 'none' ? ', with a labelled synthetic defect' : ''}.</div>
      </div>
      <div className={styles.strip}>
        {frames.map((src, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={i} src={src} width={96} height={96} alt={`frame ${i + 1}`} />
        ))}
      </div>
    </main>
  );
}
