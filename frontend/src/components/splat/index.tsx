'use client';

import dynamic from 'next/dynamic';
import type { SplatViewerProps } from './types';
import styles from './viewer.module.css';

export type { PinSeverity, SplatCameraPose, SplatFocus, SplatPin, SplatSafeArea, SplatSiteId, SplatViewerProps, Vec3Tuple } from './types';
export { SPLAT_SITES, SPLAT_SITE_IDS, getSplatSite, isSplatSiteId, type SplatSite, type SplatLodSettings } from './sites';
export type { SplatEyeConfig, SplatEyeFrameMeta, EyeAction, EyeFramePost, EyeMark, EyeViewPose } from './eye';
export type { LodStats } from './engine';

const SplatViewerImpl = dynamic(() => import('./viewer'), {
  ssr: false,
  loading: () => <div className={styles.root} aria-busy="true" />,
});

/**
 * PlayCanvas viewer for a hosted SuperSplat capture with 3-D anchored pins. Client only; fills its
 * parent. See REALITY-CONTRACT-3.md section 12 for the prop contract.
 */
export function SplatViewer(props: SplatViewerProps) {
  return <SplatViewerImpl {...props} />;
}

export default SplatViewer;
