import type { SplatSiteId, Vec3Tuple } from './types';

/**
 * Streaming level-of-detail settings for a `lod-meta.json` capture (PlayCanvas GSplatParams and
 * GSplatComponent LOD fields). The engine shows the coarsest level first, then streams finer chunk
 * files around the camera until the splat budget is filled.
 */
export interface SplatLodSettings {
  /** Splats on screen in the interactive viewer (GSplatParams#splatBudget, target mode). */
  budget: number;
  /** Budget for headless eye renderers and the capture route: fewer chunk files to stream per move. */
  headlessBudget: number;
  /** Distance of the first LOD transition in metres, before the field-of-view compensation (component). */
  lodBaseDistance: number;
  /** Ratio between successive LOD transition distances (component). */
  lodMultiplier: number;
  /** Effective-distance multiplier for nodes behind the camera; the view ahead streams first. */
  lodBehindPenalty: number;
  /** Camera rotation in degrees that re-evaluates the LOD choice (through the behind penalty). */
  lodUpdateAngle: number;
  /** Camera travel in metres that re-evaluates the LOD choice. */
  lodUpdateDistance: number;
  /** Sort by distance from the camera instead of along the view axis: turning needs no new sort. */
  radialSorting: boolean;
  /** Chunk files downloaded at once (PlayCanvas defaults to 2). */
  concurrentLoads: number;
  /** Levels in the capture (level 0 is the finest) and the gaussians in each. */
  levels: number;
  levelCounts: number[];
  /** Chunk files in the capture. */
  files: number;
}

/**
 * LOD settings measured on a 23.6 M-gaussian streamed SuperSplat capture (5 levels, 44 chunk files of
 * ~6.4 MB) on an Apple M4 in Chrome (WebGL2 through ANGLE Metal): coarse first view in about 3 s, full
 * detail around the start camera in about 10 s, about 15 to 18 chunk files resident. Spread these into
 * a new streamed site and add the capture's `levels`, `levelCounts` and `files` from its lod-meta.json.
 */
export const LOD_DEFAULTS = {
  // the published SuperSplat viewer streams 4 M on desktop and 2 M in its performance mode
  budget: 3_000_000,
  headlessBudget: 2_000_000,
  lodBaseDistance: 5,
  lodMultiplier: 3,
  lodBehindPenalty: 5,
  lodUpdateAngle: 90,
  lodUpdateDistance: 1,
  radialSorting: true,
  concurrentLoads: 4,
} satisfies Omit<SplatLodSettings, 'levels' | 'levelCounts' | 'files'>;

export interface SplatSite {
  id: SplatSiteId;
  name: string;
  sceneId: string;
  sceneTitle: string;
  author: string;
  /** All gaussians in the capture (for a streamed capture, summed over its LOD levels). */
  gaussians: number;
  /** `sog`: one SOG file set (meta.json). `lod`: a streamed LOD octree (lod-meta.json plus chunk files). */
  format: 'sog' | 'lod';
  lod?: SplatLodSettings;
  /** Clear colour (0..1, as the scene's published viewer settings give it) where no splat covers the canvas. Defaults to black. */
  background?: Vec3Tuple;
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

type SiteInput = Omit<SplatSite, 'metaUrl' | 'thumbnailUrl' | 'sceneUrl' | 'format'> & { format?: SplatSite['format'] };

function site(s: SiteInput): SplatSite {
  const format = s.format ?? 'sog';
  return {
    ...s,
    format,
    metaUrl: `${CDN}/${s.sceneId}/v1/${format === 'lod' ? 'lod-meta.json' : 'meta.json'}`,
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
  'tomioka-mill': site({
    id: 'tomioka-mill',
    name: 'Tomioka Silk Mill',
    sceneId: '849bce2a',
    sceneTitle: '富岡製糸場',
    author: 'acrylagitt',
    // lod-meta.json v1: 23,564,860 across 5 levels (12,162,508 at the finest), 44 chunk files of ~6.4 MB
    gaussians: 23_564_860,
    format: 'lod',
    lod: {
      ...LOD_DEFAULTS,
      levels: 5,
      levelCounts: [12_162_508, 6_081_254, 3_040_627, 1_520_314, 760_157],
      files: 44,
    },
    // settings-849bce2a.json background (sky blue): the capture is outdoors
    background: [0.23529411764705882, 0.7137254901960784, 1],
    // settings-849bce2a.json cameras[0].initial
    camera: {
      position: [-32.413875579833984, 0.28660866618156433, -43.35091018676758],
      target: [-33.55777999104079, 0.0013603378359726692, -44.49481318087853],
      fov: 75,
    },
    pivotDistance: 4,
    // octree leaf centres weighted by finest-level counts, 5th to 95th percentile (viewer frame)
    extent: { min: [-39.81, -2.61, -56.04], max: [2.47, 7.7, 8.58] },
  }),
};

export const SPLAT_SITE_IDS = Object.keys(SPLAT_SITES) as SplatSiteId[];

export function getSplatSite(id: string): SplatSite | null {
  return (SPLAT_SITES as Record<string, SplatSite>)[id] ?? null;
}

export function isSplatSiteId(id: unknown): id is SplatSiteId {
  return typeof id === 'string' && Object.prototype.hasOwnProperty.call(SPLAT_SITES, id);
}
