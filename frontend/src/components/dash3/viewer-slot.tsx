"use client";

/* The seam to the VIEWER stream (REALITY-CONTRACT-3.md section 12, contract 4 section 2). SplatViewer lives in
   components/splat/index.tsx, is client-only and fills its parent; the dashboard mounts it through these props and
   never edits it. eye runs it as a renderer for the agent eye; fill and safeArea are the mission view's.
   A site the viewer does not list yet (the mill, while the VIEWER stream adds its streamed LOD scan) gets the capture's
   thumbnail and a line saying so, instead of a viewer with no scene. */
import dynamic from "next/dynamic";
import type { SplatEyeConfig, SplatFocus, SplatPin, SplatViewerProps } from "@/components/splat";
import { getSplatSite } from "@/components/splat/sites";
import { site3 } from "@/lib/sites-3";

export type ViewerPin = SplatPin;
export type ViewerFocus = SplatFocus;
export type EyeConfig = SplatEyeConfig;
export type { SplatViewerProps };
export type ViewerSlotProps = Omit<SplatViewerProps, "siteId"> & { siteId: string };

export function ViewerLoading() { return <div className="vw-loading"><span className="pulse" aria-hidden="true" />Loading the scan</div>; }

const SplatViewer = dynamic(() => import("@/components/splat").then(m => m.SplatViewer), { ssr: false, loading: () => <ViewerLoading /> });

function ViewerPending({ siteId }: { siteId: string }) {
  const site = site3(siteId);
  return <div className="vw-pending" role="status">
    <img src={site.thumbnailUrl} alt={`${site.name}, the hosted capture's thumbnail`} />
    <p><strong>The scan of {site.name} is not in the viewer yet.</strong> <span>The viewer is adding its streamed capture; until then this is the capture&apos;s thumbnail, and the agent eye cannot render here.</span></p>
  </div>;
}

export default function ViewerSlot(props: ViewerSlotProps) {
  if (!getSplatSite(props.siteId)) return <ViewerPending siteId={props.siteId} />;
  return <SplatViewer {...props} siteId={props.siteId as SplatViewerProps["siteId"]} />;
}
