"use client";

/* The seam to the VIEWER stream (REALITY-CONTRACT-3.md section 12). SplatViewer lives in components/splat/index.tsx,
   is client-only and fills its parent; the dashboard mounts it through these props and never edits it. */
import dynamic from "next/dynamic";
import type { SplatFocus, SplatPin, SplatViewerProps } from "@/components/splat";

export type ViewerPin = SplatPin;
export type ViewerFocus = SplatFocus;
export type { SplatViewerProps };

/* Contract 4 section 2: the eye mode. The viewer registers as a renderer, long-polls camera commands and posts frames. */
export interface EyeConfig { siteId: string; rendererId: string; showOverlay?: boolean }

export function ViewerLoading() { return <div className="vw-loading"><span className="pulse" aria-hidden="true" />Loading the scan</div>; }

const SplatViewer = dynamic(() => import("@/components/splat").then(m => m.SplatViewer), { ssr: false, loading: () => <ViewerLoading /> });

/* eye is passed through as is; the viewer stream's props type gains it when eye mode lands. */
export default function ViewerSlot(props: SplatViewerProps & { eye?: EyeConfig }) { return <SplatViewer {...(props as SplatViewerProps)} />; }
