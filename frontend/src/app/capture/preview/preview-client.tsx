'use client';

import { useMemo, useState } from 'react';
import { SplatViewer, type SplatFocus, type SplatPin, type SplatSiteId } from '@/components/splat';
import styles from '../capture.module.css';

/** Three fake pins per site, placed on dense parts of each scan in front of the start camera. */
const FAKE_PINS: Record<SplatSiteId, SplatPin[]> = {
  'myer-plant': [
    { assetTag: 'MY-V-101', label: 'Isolation valve, primary loop', position: [-4.95, -0.15, -1.95], severity: 'high', issueIds: ['ISS-1'] },
    { assetTag: 'MY-P-201', label: 'Circulation pump P-201', position: [-3.75, -0.15, -0.45], severity: 'medium' },
    { assetTag: 'MY-G-301', label: 'Pressure gauge, header', position: [-6.45, -0.15, -2.55], severity: 'low', estimated: true },
  ],
  'bristol-pumps': [
    { assetTag: 'BR-P-1907A', label: '1907 steam pump A', position: [0.15, 1.05, -1.95], severity: 'high', issueIds: ['ISS-7', 'ISS-8'] },
    { assetTag: 'BR-V-112', label: 'Gate valve, sump line', position: [1.35, 1.05, -3.15], severity: 'none' },
    { assetTag: 'BR-PV-01', label: 'Pressure vessel', position: [-0.45, 1.05, -3.75], severity: 'medium', estimated: true },
  ],
};

export default function PreviewClient({ initialSite }: { initialSite: SplatSiteId }) {
  const [site, setSite] = useState<SplatSiteId>(initialSite);
  const [focus, setFocus] = useState<SplatFocus | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [log, setLog] = useState('events appear here');
  const pins = FAKE_PINS[site];
  const byTag = useMemo(() => new Map(pins.map((p) => [p.assetTag, p])), [pins]);
  const run = (action: SplatFocus['action'], assetTag?: string) => setFocus({ action, assetTag, nonce: `${Date.now()}` });

  return (
    <div className={styles.preview}>
      <div className={styles.bar}>
        <strong>Splat viewer preview</strong>
        {(['myer-plant', 'bristol-pumps'] as const).map((id) => (
          <button key={id} type="button" className={styles.tab} aria-pressed={site === id} onClick={() => { setSite(id); setFocus(null); }}>{id}</button>
        ))}
        <span className={styles.spacer} />
        <button type="button" className={styles.tab} data-action="focus" onClick={() => run('focus', pins[0].assetTag)}>Focus {pins[0].assetTag}</button>
        <button type="button" className={styles.tab} data-action="orbit" onClick={() => run('orbit', pins[1].assetTag)}>Orbit {pins[1].assetTag}</button>
        <button type="button" className={styles.tab} data-action="highlight" onClick={() => run('highlight', pins[2].assetTag)}>Highlight {pins[2].assetTag}</button>
        <button type="button" className={styles.tab} data-action="reset" onClick={() => run('reset')}>Reset</button>
        <button type="button" className={styles.tab} data-action="edit" aria-pressed={editMode} onClick={() => setEditMode((v) => !v)}>Place pins</button>
      </div>
      <div className={styles.stage}>
        <SplatViewer
          key={site}
          siteId={site}
          pins={pins}
          focus={focus}
          editMode={editMode}
          onPinHover={(tag) => tag && setLog(`hover ${tag}`)}
          onPinClick={(tag) => setLog(`click ${tag}`)}
          onPlacePin={(p) => setLog(`place pin at ${p.map((n) => n.toFixed(3)).join(', ')}`)}
          renderCard={(tag) => {
            const pin = byTag.get(tag);
            return (
              <div className={styles.card}>
                <strong>{pin?.label}</strong>
                <span>{tag} · severity {pin?.severity ?? 'none'}</span>
              </div>
            );
          }}
        />
      </div>
      <div className={styles.log} data-testid="preview-log">{log}</div>
    </div>
  );
}
