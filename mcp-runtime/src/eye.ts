/**
 * The agent eye (REALITY-CONTRACT-4.md §2): the 3-D scan is an interface for agents. Each tool posts one camera
 * action to POST /api/eye/{siteId}/act {action, params}; a renderer (an open dashboard viewer in eye mode, or the
 * headless worker the backend starts) moves the camera, renders the scan and returns a frame with the pose and the
 * pins it can see. The tool returns the JPEG as MCP image content plus a short text (pose, visible tags), so a vision
 * model literally sees the plant; humans watching the Environment page see the camera move.
 *
 * Authority (backend): engineer, manager, director or operator. Every act is a Change of type `eye` and a telemetry row.
 */
import { z } from 'zod';
import type { PropertyId, RuntimeConfig } from './config.js';
import { AdapterError, type Backend } from './upstream.js';
import { LOCAL_WRITE, READ_ONLY, WithContent, type ContentBlock, type RequestContextLike, type ToolFn } from './tooling.js';

type Json = Record<string, unknown>;
const ANY = z.unknown();
const obj = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {};
const str = (value: unknown): string | null => typeof value === 'string' && value.length ? value : typeof value === 'number' ? String(value) : null;
const num = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const vec = (value: unknown): [number, number, number] | null => {
  if (Array.isArray(value) && value.length === 3 && value.every(n => typeof n === 'number')) return value as [number, number, number];
  const record = obj(value);
  return [record.x, record.y, record.z].every(n => typeof n === 'number') ? [record.x as number, record.y as number, record.z as number] : null;
};

/** At most this many images go into one tool result; the rest are listed by URL. */
export const MAX_IMAGES_PER_RESULT = 8;
const MAX_IMAGE_BYTES = 2_500_000;

const VisiblePinSchema = z.object({ assetTag: z.string(), x: z.number().nullable(), y: z.number().nullable(), distance: z.number().nullable(), occluded: z.boolean() });
const CameraSchema = z.object({ position: z.tuple([z.number(), z.number(), z.number()]).nullable(), target: z.tuple([z.number(), z.number(), z.number()]).nullable(), fov: z.number().nullable() });
const FrameSchema = z.object({ frameId: z.string(), frameUrl: z.string().nullable(), camera: CameraSchema, visiblePins: z.array(VisiblePinSchema), actor: z.string().nullable(), at: z.string().nullable(), image: z.enum(['included', 'omitted', 'unavailable']) });
export const EyeResultSchema = z.object({
  siteId: z.string(), action: z.string(), frames: z.array(FrameSchema), visibleTags: z.array(z.string()), imagesReturned: z.number(), imagesOmitted: z.number(),
  annotation: z.record(z.string(), z.unknown()).nullable(), nextStep: z.string(),
});
type Frame = z.infer<typeof FrameSchema>;

function normaliseFrame(raw: Json): Frame & { inline: string | null } {
  const camera = obj(raw.camera);
  return {
    frameId: str(raw.frameId) ?? str(raw.id) ?? 'frame', frameUrl: str(raw.frameUrl) ?? str(raw.url),
    camera: { position: vec(camera.position), target: vec(camera.target), fov: num(camera.fov) },
    visiblePins: (Array.isArray(raw.visiblePins) ? raw.visiblePins : []).map(pin => obj(pin)).filter(pin => str(pin.assetTag)).map(pin => ({
      assetTag: str(pin.assetTag)!, x: num(pin.x), y: num(pin.y), distance: num(pin.distance), occluded: pin.occluded === true,
    })),
    actor: str(raw.actor), at: str(raw.at), image: 'omitted', inline: str(raw.jpegBase64),
  };
}

const fmt = (v: [number, number, number] | null) => v ? `[${v.map(n => n.toFixed(2)).join(', ')}]` : '?';
function describe(frame: Frame, index?: number): string {
  const visible = frame.visiblePins.filter(pin => !pin.occluded).sort((a, b) => (a.distance ?? 99) - (b.distance ?? 99));
  const hidden = frame.visiblePins.filter(pin => pin.occluded);
  return `${index !== undefined ? `Frame ${index + 1} ` : ''}${frame.frameId}: camera at ${fmt(frame.camera.position)} looking at ${fmt(frame.camera.target)}${frame.camera.fov ? `, fov ${Math.round(frame.camera.fov)}°` : ''}. `
    + `Visible: ${visible.length ? visible.map(pin => `${pin.assetTag}${pin.distance !== null ? ` ${pin.distance.toFixed(1)} m` : ''}${pin.x !== null && pin.y !== null ? ` at (${pin.x.toFixed(2)}, ${pin.y.toFixed(2)})` : ''}`).join(', ') : 'no tagged assets'}.`
    + `${hidden.length ? ` Behind something: ${hidden.map(pin => pin.assetTag).join(', ')}.` : ''}${frame.image === 'included' ? '' : frame.image === 'unavailable' ? ' (image unavailable)' : ` (image not included: ${frame.frameUrl ?? 'no URL'})`}`;
}

/** Report progress immediately and every interval while slow work runs (renderers can take ~20 s per frame). */
async function withProgress<T>(ctx: RequestContextLike, label: string, work: () => Promise<T>, intervalMs = 15_000): Promise<T> {
  const started = Date.now();
  const tick = () => { void ctx.reportProgress?.(Math.round((Date.now() - started) / 1000), undefined, `${label}: ${Math.round((Date.now() - started) / 1000)} s`).catch(() => false); };
  tick();
  const timer = setInterval(tick, intervalMs);
  try { return await work(); } finally { clearInterval(timer); }
}

/** A frame URL from the backend as an absolute URL on the backend's own origin (null for anything else). */
export function frameUrlOnBackend(config: RuntimeConfig, url: string | null): string | null {
  if (!url) return null;
  const absolute = /^https?:\/\//.test(url) ? url : `${config.backendUrl}${url.startsWith('/') ? '' : '/'}${url}`;
  return absolute.startsWith(config.backendUrl) ? absolute : null;
}

/** The labelled copy of a backend frame URL (/api/eye/frames/<id>.jpg → /api/eye/frames/<id>/labelled.jpg): the same picture
 *  with the asset tags in view and every judgement on it (ring, verdict, reason) burned in. Null for any other URL. */
export function labelledFrameUrl(url: string): string | null {
  const match = url.match(/^(.*\/api\/eye\/frames\/)(eyf-[A-Za-z0-9-]+)\.jpg(?:\?.*)?$/);
  return match ? `${match[1]}${match[2]}/labelled.jpg` : null;
}

/** Fetch one eye frame as MCP image content, labelled when the backend can label it (owner, Oct 18: "the image provided to MCP
 *  can also be labelled so it's known what the issue is"), else the plain frame; only the backend's own origin is fetched (frame
 *  URLs from the backend are relative to it). Null when the frame cannot be had (missing, not an image, too large, unreachable). */
export async function fetchFrameImage(config: RuntimeConfig, backend: Backend, frameUrl: string | null): Promise<ContentBlock | null> {
  const url = frameUrlOnBackend(config, frameUrl);
  if (!url) return null;
  for (const candidate of [labelledFrameUrl(url), url]) {
    if (!candidate) continue;
    try {
      const response = await fetch(candidate, { redirect: 'error', signal: AbortSignal.timeout(15_000), headers: { Accept: 'image/jpeg,image/*', 'X-Steward-Actor': backend.actor, ...(config.backendToken ? { Authorization: `Bearer ${config.backendToken}` } : {}) } });
      if (!response.ok) continue;
      const type = (response.headers.get('content-type') || 'image/jpeg').split(';')[0]!.trim();
      if (!type.startsWith('image/')) continue;
      const bytes = Buffer.from(await response.arrayBuffer());
      if (!bytes.length || bytes.length > MAX_IMAGE_BYTES) continue;
      return { type: 'image', data: bytes.toString('base64'), mimeType: type === 'image/jpg' ? 'image/jpeg' : type };
    } catch { continue; }
  }
  return null;
}

export interface EyeDeps { tool: ToolFn; backend: Backend; config: RuntimeConfig; siteId: z.ZodType<PropertyId> }

export function registerEyeTools({ tool, backend, config, siteId }: EyeDeps) {
  const assetTag = z.string().regex(/^[A-Z]{1,4}-\d{3,4}$/).describe('Tag plate ID from get_scene or list_issues, e.g. PG-601.');
  const absolute = (url: string | null) => !url ? null : /^https?:\/\//.test(url) ? url : `${config.backendUrl}${url.startsWith('/') ? '' : '/'}${url}`;

  async function image(frame: Frame & { inline: string | null }): Promise<ContentBlock | null> {
    if (frame.inline) return { type: 'image', data: frame.inline.replace(/^data:image\/\w+;base64,/, ''), mimeType: 'image/jpeg' };
    return fetchFrameImage(config, backend, frame.frameUrl);
  }

  async function act(id: PropertyId, action: string, params: Json, ctx: RequestContextLike, nextStep: string, timeoutMs: number) {
    backend.assertProperty(id);
    const raw = await withProgress(ctx, `Agent eye ${action} on ${id}`, () => backend.json(`/api/eye/${encodeURIComponent(id)}/act`, ANY, { method: 'POST', body: { action, params }, timeoutMs, signal: ctx.signal }));
    const body = obj(raw);
    const rows = Array.isArray(raw) ? raw : Array.isArray(body.frames) ? body.frames : [raw];
    const frames = rows.map(row => normaliseFrame(obj(row)));
    if (!frames.length || (frames.length === 1 && frames[0]!.frameId === 'frame' && !frames[0]!.frameUrl && !frames[0]!.inline)) {
      throw new AdapterError('UPSTREAM_RESPONSE_INVALID', 'The eye answered without a frame.', 'Retry eye_look; if it persists, check that a renderer is registered (GET /api/eye/{siteId}/feed).', true);
    }
    const blocks: ContentBlock[] = [];
    for (const [index, frame] of frames.entries()) {
      if (index >= MAX_IMAGES_PER_RESULT) { frame.image = 'omitted'; continue; }
      const block = await image(frame);
      if (block) { blocks.push(block); frame.image = 'included'; } else frame.image = 'unavailable';
    }
    const visibleTags = [...new Set(frames.flatMap(frame => frame.visiblePins.filter(pin => !pin.occluded).map(pin => pin.assetTag)))];
    const omitted = frames.filter(frame => frame.image === 'omitted').length;
    const annotation = body.annotation && typeof body.annotation === 'object' ? obj(body.annotation) : action === 'mark' && (body.annotationId || body.mark) ? { ...obj(body.mark), id: body.annotationId ?? obj(body.mark).id } : null;
    const text = [
      ...frames.map((frame, index) => describe(frame, frames.length > 1 ? index : undefined)),
      ...(omitted ? [`${omitted} more frame(s) not included as images (at most ${MAX_IMAGES_PER_RESULT} per result); their URLs and pins are in structuredContent.`] : []),
      ...(annotation ? [`Marked: ${JSON.stringify(annotation).slice(0, 300)}`] : []),
      `NEXT: ${nextStep}`,
    ].join('\n');
    blocks.push({ type: 'text', text });
    const data = {
      siteId: id, action, frames: frames.map(({ inline: _inline, ...frame }) => { void _inline; return { ...frame, frameUrl: absolute(frame.frameUrl) }; }),
      visibleTags, imagesReturned: frames.filter(frame => frame.image === 'included').length, imagesOmitted: omitted, annotation, nextStep,
    };
    return new WithContent(data, blocks);
  }

  // The backend waits up to 20 s for a warm renderer, and up to 90 s (orbit 120 s) when the headless renderer has to start
  // first (the first eye call after a restart); these client windows sit above that so the backend's answer always arrives.
  const ACT_MS = 105_000;
  const ORBIT_MS = 135_000;
  const SHARED = 'The eye is shared: people watching the dashboard\'s Environment page see the camera move and your agent name. Cost: one rendered 640×400 frame (~350 image tokens) and up to ~20 s while a renderer draws it; the first eye call after a restart can take up to ~90 s while the headless renderer starts (progress notifications keep the call alive). Do not loop it to watch for change; use wait_for.';
  const NEXT = 'eye_go_to(assetTag) to fly to a tagged asset; eye_move / eye_turn in small steps to adjust; eye_orbit to see all sides; eye_mark(x, y, note) to flag what you see.';

  tool('eye_look', `Look at the plant through the agent eye: renders the site's 3-D scan from the eye's current pose and returns the frame as an image, plus the camera pose and the asset tags visible in it (screen position 0..1, distance in metres, occluded or not). START HERE whenever you need to see something on site. ${SHARED} NEXT: ${NEXT}`,
    z.strictObject({ siteId }), EyeResultSchema, async ({ siteId: id }, call) => act(id, 'look', {}, call.ctx, NEXT, ACT_MS), READ_ONLY);

  tool('eye_move', `Move the agent eye's camera without turning it: forward, back, left, right, up or down by meters (0.1 to 5). Explore in small steps: 0.3 to 1 m near equipment, up to 3 m to cross a room; check visibleTags after each step. Returns the new frame as an image with pose and visible tags. ${SHARED} NEXT: keep stepping toward what you are looking for, or eye_go_to(assetTag) when you know the tag.`,
    z.strictObject({ siteId, direction: z.enum(['forward', 'back', 'left', 'right', 'up', 'down']), meters: z.number().min(0.1).max(5).default(0.5).describe('Distance in metres (0.1 to 5). Small steps work best: 0.3 to 1.') }),
    EyeResultSchema, async ({ siteId: id, direction, meters }, call) => act(id, 'move', { direction, meters }, call.ctx, NEXT, ACT_MS), LOCAL_WRITE);

  tool('eye_turn', `Turn the agent eye's camera in place: yawDeg rotates around the vertical axis, pitchDeg tilts up or down (check the returned pose for the direction). Use 10 to 45° to scan a room, small angles to centre an asset. Returns the new frame as an image with pose and visible tags. ${SHARED} NEXT: eye_move toward what you see, or eye_mark to flag it.`,
    z.strictObject({ siteId, yawDeg: z.number().min(-180).max(180).default(0).describe('Degrees around the vertical axis, -180 to 180.'), pitchDeg: z.number().min(-89).max(89).default(0).describe('Degrees of tilt, -89 to 89.') }),
    EyeResultSchema, async ({ siteId: id, yawDeg, pitchDeg }, call) => act(id, 'turn', { yawDeg, pitchDeg }, call.ctx, NEXT, ACT_MS), LOCAL_WRITE);

  tool('eye_go_to', `Fly the agent eye to a tagged asset and frame it (the fastest way to look at something you know by tag). The asset's tag should then be in visibleTags and not occluded; if it is occluded or the pin is estimated, step around it with eye_move / eye_turn or use eye_orbit. Returns the frame as an image with pose and visible tags. ${SHARED} NEXT: eye_orbit(assetTag) for all sides, eye_mark to flag a defect, capture_view / get_inspection for the valve pipeline's frames.`,
    z.strictObject({ siteId, assetTag }), EyeResultSchema, async ({ siteId: id, assetTag: tag }, call) => {
      const result = await act(id, 'go_to', { assetTag: tag }, call.ctx, `Check that ${tag} is in visibleTags. Then eye_orbit(assetTag="${tag}") for all sides, eye_mark(x, y, note) to flag what you see, or eye_move / eye_turn in small steps.`, ACT_MS);
      return result;
    }, LOCAL_WRITE);

  tool('eye_orbit', `Circle a tagged asset with the agent eye and return a ring of frames (4 to 16) as images, so you can inspect every side: handwheels, gauges, leaks, corrosion, labels. At most ${MAX_IMAGES_PER_RESULT} images come back in one result; the rest are listed with their URLs and pins. Cost: one frame per position (~350 image tokens each) and up to ~20 s per frame while the renderer draws them. ${SHARED} NEXT: eye_mark(x, y, note) on the frame that shows the problem (eye_go_to first to return to that view), or get_inspection(siteId) for the valve pipeline's verdict.`,
    z.strictObject({ siteId, assetTag, frames: z.number().int().min(4).max(16).default(8).describe('Positions around the asset, 4 to 16.') }),
    EyeResultSchema, async ({ siteId: id, assetTag: tag, frames }, call) => act(id, 'orbit', { assetTag: tag, frames }, call.ctx, `Pick the frame that shows the problem; eye_mark it, or move on with eye_go_to.`, ORBIT_MS), LOCAL_WRITE);

  tool('eye_mark', `Flag what you see: a screen point (x, y from 0 to 1 on the latest eye frame, 0,0 top-left) and a short note. The backend projects it to a world point on the scan, stores an annotation, and may open an issue candidate for a person to confirm. Use it after eye_look / eye_go_to when you see a defect or something worth a second look. Marks are local records; nothing is dispatched. Synthetic defects stay labelled synthetic. NEXT: get_issue / list_issues for the candidate, decide or request_fix to act on it.`,
    z.strictObject({ siteId, x: z.number().min(0).max(1).describe('Horizontal screen position on the latest frame, 0 (left) to 1 (right).'), y: z.number().min(0).max(1).describe('Vertical screen position, 0 (top) to 1 (bottom).'), note: z.string().min(3).max(300).describe('What you see there, e.g. "Handwheel missing on V-503".') }),
    EyeResultSchema, async ({ siteId: id, x, y, note }, call) => act(id, 'mark', { x, y, note }, call.ctx, 'list_issues(siteId) shows any issue candidate the mark opened; decide or request_fix to act on it.', ACT_MS), LOCAL_WRITE);
}
