import type { Metadata } from 'next';
import CaptureClient, { type CaptureParams } from './capture-client';

export const metadata: Metadata = {
  title: 'Steward capture',
  robots: { index: false, follow: false },
};

type Search = { [key: string]: string | string[] | undefined };

const one = (sp: Search, key: string) => {
  const v = sp[key];
  return Array.isArray(v) ? v[0] : v;
};
const num = (v: string | undefined, fallback: number, min: number, max: number) => {
  const n = v === undefined || v === '' ? NaN : Number(v);
  return Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : fallback;
};

/**
 * `/capture?site=<id>&asset=<tag>&frames=16&defect=<none|leak|corrosion|missing-handwheel>`
 * Optional: `pos=x,y,z` (used when the backend has no 3-D pin), `arc` (degrees, 360 = full orbit),
 * `radius` (m), `elev` (degrees), `fov`, `size` (px), `radiusDefect` (m), `smart=0` (skip the
 * line-of-sight probe that centres the arc on the clearest side of the pin).
 * Renders the frames headlessly and exposes `window.__frames` (JPEG data URLs) and `window.__done`.
 */
export default async function CapturePage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const params: CaptureParams = {
    site: one(sp, 'site') ?? '',
    asset: one(sp, 'asset') ?? '',
    frames: Math.round(num(one(sp, 'frames'), 16, 1, 64)),
    defect: one(sp, 'defect') ?? 'none',
    pos: one(sp, 'pos') ?? null,
    arc: num(one(sp, 'arc'), 120, 1, 360),
    radius: num(one(sp, 'radius'), 1.1, 0.2, 10),
    elev: num(one(sp, 'elev'), 18, -60, 80),
    fov: num(one(sp, 'fov'), 60, 20, 110),
    size: Math.round(num(one(sp, 'size'), 256, 64, 1024)),
    defectRadius: num(one(sp, 'radiusDefect'), 0.25, 0.05, 1),
    smart: one(sp, 'smart') !== '0',
  };
  return <CaptureClient {...params} />;
}
