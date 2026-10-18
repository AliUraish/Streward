'use client';

import { useEffect, useMemo, useState } from 'react';
import { SplatViewer, type SplatPin, type SplatSiteId } from '@/components/splat';
import styles from './eye.module.css';

export interface EyeViewParams {
  site: SplatSiteId;
  renderer: string | null;
  apiBase: string;
  overlay: boolean;
  size: { width: number; height: number } | null;
  instant: boolean;
}

type Json = unknown;
const isObj = (v: Json): v is Record<string, Json> => !!v && typeof v === 'object' && !Array.isArray(v);
const SEVERITIES = new Set(['none', 'low', 'medium', 'high']);

/** Pins from GET /api/properties/<site>/scene (assets[].pin), falling back to /components. */
function toPins(payload: Json): SplatPin[] {
  const list: Json[] = isObj(payload) && Array.isArray(payload.assets) ? payload.assets : Array.isArray(payload) ? payload : [];
  const out: SplatPin[] = [];
  for (const a of list) {
    if (!isObj(a)) continue;
    const tag = typeof a.assetTag === 'string' ? a.assetTag : typeof a.tag === 'string' ? a.tag : null;
    const pin = a.pin;
    if (!tag || !isObj(pin) || ![pin.x, pin.y, pin.z].every((n) => typeof n === 'number' && Number.isFinite(n))) continue;
    out.push({
      assetTag: tag,
      position: [pin.x as number, pin.y as number, pin.z as number],
      label: typeof a.name === 'string' ? a.name : tag,
      severity: typeof a.severity === 'string' && SEVERITIES.has(a.severity) ? (a.severity as SplatPin['severity']) : 'none',
      estimated: a.pinSource !== 'placed',
      issueIds: Array.isArray(a.issueIds) ? a.issueIds.filter((x): x is string => typeof x === 'string') : undefined,
    });
  }
  return out;
}

export default function EyeView(params: EyeViewParams) {
  const [pins, setPins] = useState<SplatPin[]>([]);
  const [rendererId, setRendererId] = useState<string | null>(params.renderer);

  useEffect(() => {
    if (params.renderer) return;
    // one id per tab, kept across reloads
    const key = `steward-eye-renderer-${params.site}`;
    let id: string | null = null;
    try { id = window.sessionStorage.getItem(key); } catch { /* storage blocked */ }
    if (!id) {
      id = `browser-${Math.random().toString(36).slice(2, 8)}`;
      try { window.sessionStorage.setItem(key, id); } catch { /* storage blocked */ }
    }
    setRendererId(id);
  }, [params.renderer, params.site]);

  useEffect(() => {
    let stop = false;
    const base = params.apiBase.replace(/\/+$/, '');
    const load = async () => {
      for (const path of ['scene', 'components']) {
        try {
          const res = await fetch(`${base}/api/properties/${params.site}/${path}`, { cache: 'no-store' });
          if (!res.ok) continue;
          const next = toPins(await res.json());
          if (next.length && !stop) { setPins(next); return; }
        } catch { /* backend not up yet */ }
      }
    };
    void load();
    const t = window.setInterval(load, 20000);
    return () => { stop = true; window.clearInterval(t); };
  }, [params.apiBase, params.site]);

  const eye = useMemo(() => (rendererId ? {
    siteId: params.site,
    rendererId,
    apiBase: params.apiBase || undefined,
    showOverlay: params.overlay,
    instant: params.instant,
  } : undefined), [rendererId, params.site, params.apiBase, params.overlay, params.instant]);

  const stage = params.size ? { width: params.size.width, height: params.size.height } : undefined;
  return (
    <main className={params.size ? styles.fixed : styles.full}>
      <div className={styles.stage} style={stage}>
        <SplatViewer siteId={params.site} pins={pins} eye={eye} />
      </div>
    </main>
  );
}
