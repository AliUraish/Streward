import type React from 'react';
import type { SplatEyeConfig } from './eye';

export type SplatSiteId = 'myer-plant' | 'bristol-pumps';
export type Vec3Tuple = [number, number, number];
export type PinSeverity = 'none' | 'low' | 'medium' | 'high';

export interface SplatPin {
  assetTag: string;
  /** World position in the viewer frame (the SuperSplat viewer frame: scan rotated 180 degrees about Z). */
  position: Vec3Tuple;
  severity?: PinSeverity;
  label: string;
  /** Estimated pins are drawn hollow and say so in their card until someone places them. */
  estimated?: boolean;
  issueIds?: string[];
}

export interface SplatFocus {
  assetTag?: string;
  action: 'focus' | 'orbit' | 'highlight' | 'reset';
  /** A new nonce runs the action again, even with the same asset and action. */
  nonce: string;
}

export interface SplatViewerProps {
  siteId: SplatSiteId;
  pins: SplatPin[];
  focus?: SplatFocus | null;
  editMode?: boolean;
  onPinHover?(assetTag: string | null): void;
  onPinClick?(assetTag: string): void;
  onPlacePin?(position: Vec3Tuple): void;
  renderCard?(assetTag: string): React.ReactNode;
  className?: string;
  /**
   * Agent eye mode (REALITY-CONTRACT-4.md section 2): register as a renderer, execute camera commands
   * from agents and post a 640×400 JPEG plus visible pins for each.
   */
  eye?: SplatEyeConfig;
}
