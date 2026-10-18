import type React from 'react';
import type { SplatEyeConfig, SplatEyeFrameMeta } from './eye';

/** Camera pose in the viewer frame; `principal` is the canvas point (CSS px) the view axis crosses. */
export interface SplatCameraPose {
  position: Vec3Tuple;
  target: Vec3Tuple;
  fov: number;
  yaw: number;
  pitch: number;
  principal: { x: number; y: number };
}

export interface SplatSafeArea { top?: number; right?: number; bottom?: number; left?: number }

export type SplatSiteId = 'myer-plant' | 'bristol-pumps' | 'tomioka-mill';
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
  /**
   * The latest walkthrough label (REALITY-CONTRACT-7.md section 1), drawn as a chip beside the dot. Its words carry
   * the meaning ("Looks good", "Looks bad: <first reason>"); green and blue only repeat them. `description` is the
   * fuller sentence the dot's accessible name reads.
   */
  assessment?: { verdict: 'good' | 'bad'; text: string; description?: string };
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
  /**
   * Mission view: fill the container at any size (no letterboxing, no own controls) and render at
   * the device pixel ratio capped at 2.
   */
  fill?: boolean;
  /** Insets in CSS px covered by HUD panels; start, focus and orbit framing keep the target between them. */
  safeArea?: SplatSafeArea;
  /** Camera pose, throttled to 10 Hz. */
  onCameraChange?(pose: SplatCameraPose): void;
  /**
   * Follow an agent's camera (humans watching a walkthrough): ease to this pose whenever the nonce changes. Skipped
   * while an eye command drives the camera here, since this renderer is then producing that very view.
   */
  follow?: { position: Vec3Tuple; target: Vec3Tuple; fov?: number | null; nonce: string } | null;
  /** The latest eye frame (eye mode), for a HUD showing what the agent sees. */
  onFrame?(meta: SplatEyeFrameMeta): void;
}
