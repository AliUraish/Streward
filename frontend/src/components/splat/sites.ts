import type { SplatSiteId, Vec3Tuple } from './types';

export interface SplatSite {
  id: SplatSiteId;
  name: string;
  sceneId: string;
  sceneTitle: string;
  author: string;
  gaussians: number;
  metaUrl: string;
  thumbnailUrl: string;
  sceneUrl: string;
  /** Initial camera from the scene's published viewer settings (viewer frame). */
  camera: { position: Vec3Tuple; target: Vec3Tuple; fov: number };
  /** Orbit pivot distance in front of the initial camera, in metres. */
  pivotDistance: number;
  /** Rough extent of the dense part of the capture (5th to 95th percentile of splat centres). */
  extent: { min: Vec3Tuple; max: Vec3Tuple };
}

const CDN = 'https://d28zzqy0iyovbz.cloudfront.net';
const THUMBS = 'https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat';

function site(s: Omit<SplatSite, 'metaUrl' | 'thumbnailUrl' | 'sceneUrl'>): SplatSite {
  return {
    ...s,
    metaUrl: `${CDN}/${s.sceneId}/v1/meta.json`,
    thumbnailUrl: `${THUMBS}/${s.sceneId}/v1/xl.webp`,
    sceneUrl: `https://superspl.at/scene/${s.sceneId}`,
  };
}

export const SPLAT_SITES: Record<SplatSiteId, SplatSite> = {
  'myer-plant': site({
    id: 'myer-plant',
    name: 'Myer Plant Room',
    sceneId: '66b655d3',
    sceneTitle: 'merged_room_v2',
    author: 'azha007',
    gaussians: 14_158_102,
    // settings-66b655d3.json (v1 settings): position plus a far target that only gives a direction.
    camera: { position: [-8.4004, -0.4771, 0.5886], target: [88.5429, 2.1959, -82.384], fov: 75 },
    pivotDistance: 3.5,
    extent: { min: [-14.98, -1.56, -9.13], max: [-1.8, 3.54, 6.54] },
  }),
  'bristol-pumps': site({
    id: 'bristol-pumps',
    name: 'Bristol Dock Pump House',
    sceneId: '8a8ce192',
    sceneTitle: 'Machine_Room_PortalCam',
    author: 'scanomatic_labs',
    gaussians: 6_934_105,
    // settings-8a8ce192.json cameras[0].initial (published fov 120; we use 75).
    camera: { position: [-0.0713, 2.8039, -0.5236], target: [-0.0221, 2.7469, -0.6373], fov: 75 },
    pivotDistance: 3,
    extent: { min: [-3.02, -0.04, -8.77], max: [6.15, 5.14, 1.63] },
  }),
};

export function getSplatSite(id: string): SplatSite | null {
  return (SPLAT_SITES as Record<string, SplatSite>)[id] ?? null;
}
