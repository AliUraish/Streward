import type { Metadata } from 'next';
import { isSplatSiteId } from '@/components/splat/sites';
import EyeView, { type EyeViewParams } from './eye-view';

export const metadata: Metadata = {
  title: 'Steward agent eye',
  robots: { index: false, follow: false },
};

type Search = { [key: string]: string | string[] | undefined };
const one = (sp: Search, key: string) => {
  const v = sp[key];
  return Array.isArray(v) ? v[0] : v;
};

/**
 * `/eye?site=<a SPLAT_SITES id>&renderer=<rendererId>` mounts the splat viewer in agent eye
 * mode (REALITY-CONTRACT-4.md section 2). Optional: `overlay=0` hides the HUD, `size=full|WxH` sets the
 * stage (headless renderers default to 640x400, the frame size), `motion=instant|eased` (headless
 * defaults to instant), `api=<origin>` points the eye at another backend.
 */
export default async function EyePage({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const requested = one(sp, 'site');
  const site = isSplatSiteId(requested) ? requested : 'myer-plant';
  const renderer = (one(sp, 'renderer') ?? '').replace(/[^\w.:-]/g, '').slice(0, 64);
  const headless = renderer.startsWith('headless');
  const sizeParam = one(sp, 'size') ?? (headless ? '640x400' : 'full');
  const m = /^(\d{2,4})x(\d{2,4})$/.exec(sizeParam);
  const params: EyeViewParams = {
    site,
    renderer: renderer || null,
    apiBase: one(sp, 'api') ?? '',
    overlay: one(sp, 'overlay') !== '0',
    size: m ? { width: Number(m[1]), height: Number(m[2]) } : null,
    instant: (one(sp, 'motion') ?? (headless ? 'instant' : 'eased')) === 'instant',
  };
  return <EyeView {...params} />;
}
