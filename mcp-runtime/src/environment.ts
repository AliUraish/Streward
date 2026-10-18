/**
 * The agent environment and site tours (owner, Oct 18 2026: "make these agent environments for MCPs, so MCP servers can see
 * them, and add for that agent how they are seeing the environment; a site inspector can give an MCP agent a site tour and then
 * send it pics of what is wrong"):
 *
 * - get_environment(siteId): GET /api/agent-environment/{siteId}: the site as the agents see it (the walk in progress, the latest
 *   eye frames with what the agents marked in them, labels, readings, obligations, open issues, the latest inspection, tours,
 *   the recent log) as markdown, with the latest frames as images.
 * - request_site_tour(siteId, focus?, maxStops?): POST /api/site-tours, then waits for the Site Inspector (polling the tour, with
 *   progress notifications) and returns every stop and the pictures of what is wrong; still running → the progress and tourId.
 * - get_site_tour(tourId): GET /api/site-tours/{id}, the same result later.
 */
import { z } from 'zod';
import type { PropertyId, RuntimeConfig } from './config.js';
import { fetchFrameImage, frameUrlOnBackend } from './eye.js';
import { AdapterError, type Backend } from './upstream.js';
import { LOCAL_WRITE, READ_ONLY, WithContent, type ContentBlock, type RequestContextLike, type ToolFn } from './tooling.js';

type Json = Record<string, unknown>;
const ANY = z.unknown();
const obj = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {};
const arr = (value: unknown): Json[] => Array.isArray(value) ? value.map(item => obj(item)) : [];
const str = (value: unknown): string | null => typeof value === 'string' && value.length ? value : typeof value === 'number' ? String(value) : null;
const num = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const MAX_ENVIRONMENT_IMAGES = 3;
const MAX_TOUR_IMAGES = 4;
/** The tour waits about as long as one cold eye call (eye tools allow 105 s); progress notifications keep the call alive. */
const TOUR_WAIT_MS = 100_000;
const TOUR_POLL_MS = 2_000;
/** STEWARD_MCP_TOUR_WAIT_MS shortens the wait (tests); it never exceeds the default. */
const tourWaitMs = () => { const value = Number(process.env.STEWARD_MCP_TOUR_WAIT_MS); return Number.isFinite(value) && value > 0 ? Math.min(value, TOUR_WAIT_MS) : TOUR_WAIT_MS; };

const MarkSchema = z.object({ x: z.number().nullable(), y: z.number().nullable(), note: z.string().nullable() });
const FrameLabelSchema = z.object({ assetTag: z.string(), verdict: z.string().nullable(), color: z.string().nullable(), title: z.string().nullable(), reasons: z.array(z.string()), mark: MarkSchema.nullable() });
const EnvFrameSchema = z.object({ id: z.string(), url: z.string().nullable(), assetTag: z.string().nullable(), at: z.string().nullable(), actorName: z.string().nullable(), labels: z.array(FrameLabelSchema), image: z.enum(['included', 'unavailable']) });
const LabelSchema = z.object({ assetTag: z.string(), assetName: z.string().nullable(), verdict: z.string().nullable(), color: z.string().nullable(), title: z.string().nullable(), reasons: z.array(z.string()), regulationIds: z.array(z.string()), frameUrl: z.string().nullable(), at: z.string().nullable() });
const ReadingSchema = z.object({ key: z.string().nullable(), label: z.string().nullable(), assetTag: z.string().nullable(), unit: z.string().nullable(), value: z.number().nullable(), trend: z.string().nullable(), state: z.string().nullable() });
const ObligationSchema = z.object({ id: z.string(), title: z.string().nullable(), assetTag: z.string().nullable(), status: z.string().nullable(), dueAt: z.string().nullable(), daysOverdue: z.number().nullable(), dueInDays: z.number().nullable(), blockedReason: z.string().nullable(), regulationIds: z.array(z.string()) });
const IssueSchema = z.object({ id: z.string(), kind: z.string().nullable(), severity: z.string().nullable(), assetTag: z.string().nullable(), summary: z.string().nullable(), at: z.string().nullable() });
const TourShortSchema = z.object({ id: z.string(), state: z.string().nullable(), requesterName: z.string().nullable(), stops: z.number().nullable(), findings: z.number().nullable(), summary: z.string().nullable() });
export const EnvironmentSchema = z.object({
  siteId: z.string(), siteName: z.string().nullable(), at: z.string().nullable(),
  summary: z.object({ compliancePercent: z.number().nullable(), openIssues: z.number().nullable(), overdue: z.number().nullable(), blocked: z.number().nullable(), employeesCheckedIn: z.number().nullable(), crewOnShift: z.number().nullable() }),
  walk: z.object({ state: z.string().nullable(), agentId: z.string().nullable(), agentName: z.string().nullable(), stopIndex: z.number().nullable(), stops: z.number().nullable(), assetTag: z.string().nullable(), assetName: z.string().nullable(), moving: z.boolean(), startedAt: z.string().nullable() }).nullable(),
  frames: z.array(EnvFrameSchema), labels: z.array(LabelSchema), readings: z.array(ReadingSchema), obligations: z.array(ObligationSchema), issues: z.array(IssueSchema),
  inspection: z.object({ id: z.string(), state: z.string().nullable(), primary: z.string().nullable(), steps: z.array(z.string()), summary: z.string().nullable() }).nullable(),
  tours: z.array(TourShortSchema), logs: z.array(z.object({ at: z.string().nullable(), type: z.string().nullable(), summary: z.string() })),
  tools: z.array(z.object({ name: z.string(), purpose: z.string() })), imagesReturned: z.number(), nextStep: z.string(),
});
const StopSchema = z.object({ n: z.number(), assetTag: z.string(), assetName: z.string().nullable(), verdict: z.string(), color: z.string().nullable(), title: z.string().nullable(), reasons: z.array(z.string()), observation: z.string().nullable(), frameUrl: z.string().nullable(), eyeNote: z.string().nullable(), image: z.enum(['included', 'not_included', 'unavailable', 'none']) });
export const TourSchema = z.object({
  tourId: z.string(), siteId: z.string(), siteName: z.string().nullable(), state: z.string(), guideName: z.string().nullable(), requesterName: z.string().nullable(),
  route: z.array(z.string()), stops: z.array(StopSchema), findings: z.number(), summary: z.string().nullable(), startedAt: z.string().nullable(), finishedAt: z.string().nullable(),
  imagesReturned: z.number(), nextStep: z.string(),
});

export interface EnvironmentDeps { tool: ToolFn; backend: Backend; config: RuntimeConfig; siteId: z.ZodType<PropertyId> }

function nullableNumber(value: unknown): number | null { return num(value); }

export function registerEnvironmentTools({ tool, backend, config, siteId }: EnvironmentDeps) {
  const assetTag = z.string().regex(/^[A-Z]{1,4}-\d{3,4}$/).describe('Tag plate ID from get_scene, list_issues or get_environment, e.g. V-504.');
  const tourId = z.string().min(1).max(120).regex(/^[A-Za-z0-9][A-Za-z0-9:._-]*$/).describe('tourId returned by request_site_tour.');

  function environmentData(raw: Json, frames: z.infer<typeof EnvFrameSchema>[], images: number): z.infer<typeof EnvironmentSchema> {
    const summary = obj(raw.summary); const walk = raw.walk ? obj(raw.walk) : null; const inspection = raw.inspection ? obj(raw.inspection) : null;
    return {
      siteId: str(raw.siteId) ?? '', siteName: str(raw.siteName), at: str(raw.at),
      summary: { compliancePercent: num(summary.compliancePercent), openIssues: num(summary.openIssues), overdue: num(summary.overdue), blocked: num(summary.blocked), employeesCheckedIn: num(summary.employeesCheckedIn), crewOnShift: num(summary.crewOnShift) },
      walk: walk ? { state: str(walk.state), agentId: str(walk.agentId), agentName: str(walk.agentName), stopIndex: num(walk.stopIndex), stops: num(walk.stops), assetTag: str(walk.assetTag), assetName: str(walk.assetName), moving: walk.moving === true, startedAt: str(walk.startedAt) } : null,
      frames,
      labels: arr(raw.labels).filter(l => str(l.assetTag)).map(l => ({ assetTag: str(l.assetTag)!, assetName: str(l.assetName), verdict: str(l.verdict), color: str(l.color), title: str(l.title), reasons: strings(l.reasons), regulationIds: strings(l.regulationIds), frameUrl: frameUrlOnBackend(config, str(l.frameUrl)), at: str(l.at) })),
      readings: arr(raw.readings).map(r => ({ key: str(r.key), label: str(r.label), assetTag: str(r.assetTag), unit: str(r.unit), value: nullableNumber(r.value), trend: str(r.trend), state: str(r.state) })),
      obligations: arr(raw.obligations).filter(o => str(o.id)).map(o => ({ id: str(o.id)!, title: str(o.title), assetTag: str(o.assetTag), status: str(o.status), dueAt: str(o.dueAt), daysOverdue: num(o.daysOverdue), dueInDays: num(o.dueInDays), blockedReason: str(o.blockedReason), regulationIds: strings(o.regulationIds) })),
      issues: arr(raw.issues).filter(i => str(i.id)).map(i => ({ id: str(i.id)!, kind: str(i.kind), severity: str(i.severity), assetTag: str(i.assetTag), summary: str(i.summary), at: str(i.at) })),
      inspection: inspection && str(inspection.id) ? { id: str(inspection.id)!, state: str(inspection.state), primary: str(inspection.primary), steps: strings(inspection.steps), summary: str(inspection.summary) } : null,
      tours: arr(raw.tours).filter(t => str(t.id)).map(t => ({ id: str(t.id)!, state: str(t.state), requesterName: str(t.requesterName), stops: num(t.stops), findings: num(t.findings), summary: str(t.summary) })),
      logs: arr(raw.logs).map(l => ({ at: str(l.at), type: str(l.type), summary: str(l.summary) ?? '' })),
      tools: arr(raw.tools).filter(t => str(t.name)).map(t => ({ name: str(t.name)!, purpose: str(t.purpose) ?? '' })),
      imagesReturned: images,
      nextStep: 'request_site_tour(siteId) for the Site Inspector to walk the site and send you pictures of what is wrong; eye_go_to(assetTag) to look closer; list_issues / request_fix to act.',
    };
  }

  tool('get_environment', `See a site the way its agents see it: the walk in progress (who is walking, which stop, which asset), the latest agent-eye frames as images with what the agents marked in them (green looks good, blue looks bad, with the reasons and the point marked), the labels per asset, live readings with their trend, obligations that are blocked, overdue or due soon, open issues, the latest inspection, site tours and the recent log, as compact markdown. Free and read-only (no paid model call); up to ${MAX_ENVIRONMENT_IMAGES} images, ~350 tokens each. NEXT: request_site_tour(siteId) for a guided tour with pictures of what is wrong, or eye_go_to(assetTag) to look closer yourself.`,
    z.strictObject({ siteId }), EnvironmentSchema, async ({ siteId: id }) => {
      backend.assertProperty(id);
      const raw = obj(await backend.json(`/api/agent-environment/${encodeURIComponent(id)}`, ANY));
      const blocks: ContentBlock[] = [];
      const frames: z.infer<typeof EnvFrameSchema>[] = [];
      for (const frame of arr(obj(raw.eye).frames).slice(0, MAX_ENVIRONMENT_IMAGES)) {
        const url = str(frame.url);
        const block = await fetchFrameImage(config, backend, url);
        if (block) blocks.push(block);
        frames.push({ id: str(frame.id) ?? 'frame', url: frameUrlOnBackend(config, url), assetTag: str(frame.assetTag), at: str(frame.at), actorName: str(frame.actorName),
                      labels: arr(frame.labels).filter(l => str(l.assetTag)).map(l => { const mark = l.mark ? obj(l.mark) : null; return { assetTag: str(l.assetTag)!, verdict: str(l.verdict), color: str(l.color), title: str(l.title), reasons: strings(l.reasons), mark: mark ? { x: num(mark.x), y: num(mark.y), note: str(mark.note) } : null }; }),
                      image: block ? 'included' : 'unavailable' });
      }
      const data = environmentData(raw, frames, blocks.length);
      const markdown = str(raw.markdown) ?? `# ${data.siteName ?? id}`;
      const pictures = frames.length ? `Images: ${frames.map((f, index) => `${index + 1}. ${f.id} (${f.assetTag ?? 'no asset'}${f.image === 'included' ? '' : ', image unavailable'})`).join('; ')}.` : 'No eye frames yet.';
      blocks.push({ type: 'text', text: `${markdown}\n\n${pictures}\nNEXT: ${data.nextStep}` });
      return new WithContent(data, blocks);
    }, READ_ONLY);

  async function tourResult(raw: Json, nextWhenRunning: string): Promise<WithContent<z.infer<typeof TourSchema>>> {
    const id = str(raw.id) ?? '';
    const site = str(raw.siteId) ?? '';
    if (site && !config.allowedProperties.includes(site as PropertyId)) throw new AdapterError('PROPERTY_SCOPE', 'This tour belongs to a site outside this endpoint’s scope.', 'Call list_sites; only tours of the returned sites are readable here.');
    const state = str(raw.state) ?? 'running';
    const blocks: ContentBlock[] = [];
    const stops: z.infer<typeof StopSchema>[] = [];
    let images = 0;
    for (const stop of arr(raw.stops)) {
      const url = str(stop.frameUrl);
      const bad = str(stop.verdict) === 'bad';
      let image: z.infer<typeof StopSchema>['image'] = url ? 'not_included' : 'none';
      if (bad && url && images < MAX_TOUR_IMAGES) {
        const block = await fetchFrameImage(config, backend, url);
        if (block) { blocks.push(block); images += 1; image = 'included'; } else image = 'unavailable';
      }
      stops.push({ n: num(stop.n) ?? stops.length + 1, assetTag: str(stop.assetTag) ?? '?', assetName: str(stop.assetName), verdict: str(stop.verdict) ?? 'good', color: str(stop.color), title: str(stop.title), reasons: strings(stop.reasons), observation: str(stop.observation), frameUrl: frameUrlOnBackend(config, url), eyeNote: str(stop.eyeNote), image });
    }
    const route = strings(raw.route);
    const findings = stops.filter(s => s.verdict === 'bad').length;
    const done = state !== 'running';
    const nextStep = !done ? nextWhenRunning
      : findings ? 'get_issue / list_issues for the open issues behind what looks bad, request_fix(issueId) to have the agents fix one, eye_go_to(assetTag) to look again.'
      : 'Nothing looks bad on this route; get_environment(siteId) for the whole site.';
    const data = { tourId: id, siteId: site, siteName: str(raw.siteName), state, guideName: str(raw.guideName), requesterName: str(raw.requesterName), route, stops, findings,
                   summary: str(raw.summary), startedAt: str(raw.startedAt), finishedAt: str(raw.finishedAt), imagesReturned: images, nextStep };
    const lines = [
      done ? (data.summary ?? `Tour ${id} ${state}.`) : `${data.guideName ?? 'The Site Inspector'} is still touring ${data.siteName ?? site}: ${stops.length} of ${route.length} stops done (tourId ${id}).`,
      ...stops.map(s => `${s.n}. ${s.assetTag}${s.assetName ? ` ${s.assetName}` : ''}: ${s.title ?? s.verdict}${s.reasons.length && s.verdict === 'bad' ? `: ${s.reasons.slice(0, 2).join('; ')}` : ''}${s.observation ? ` Seen: ${s.observation}` : ''}${s.image === 'included' ? ' [picture attached]' : s.verdict === 'bad' && !s.frameUrl ? ` [no picture${s.eyeNote ? `: ${s.eyeNote}` : ''}]` : ''}`),
      ...(images ? [`${images} picture(s) of what is wrong are attached in stop order.`] : []),
      `NEXT: ${nextStep}`,
    ];
    blocks.push({ type: 'text', text: lines.join('\n') });
    return new WithContent(data, blocks);
  }

  async function waitForTour(id: string, ctx: RequestContextLike): Promise<Json> {
    const started = Date.now();
    const limit = tourWaitMs();
    let raw = obj(await backend.json(`/api/site-tours/${encodeURIComponent(id)}`, ANY));
    while (str(raw.state) === 'running' && Date.now() - started < limit) {
      const done = arr(raw.stops).length; const total = strings(raw.route).length;
      void ctx.reportProgress?.(done, total || undefined, `Site Inspector: stop ${Math.min(done + 1, total || done + 1)} of ${total || '?'}`).catch(() => false);
      await new Promise(resolve => setTimeout(resolve, Math.min(TOUR_POLL_MS, limit)));
      if (ctx.signal?.aborted) break;
      raw = obj(await backend.json(`/api/site-tours/${encodeURIComponent(id)}`, ANY));
    }
    return raw;
  }

  tool('request_site_tour', `Ask the Site Inspector to give you a tour of a site: it walks up to maxStops assets with the agent eye (your focus assets first, then blocked and overdue obligations, open issues and out-of-band readings), judges each from the records (and the latest walk's observation), and sends you the pictures of what is wrong as images, with every stop as a line. People watching the dashboard see the camera move. Waits up to about 100 s with progress notifications; if the tour is still going, returns the progress and the tourId for get_site_tour. One tour per site at a time (asking again returns the running one). Free (no paid model call); up to ${MAX_TOUR_IMAGES} images, ~350 tokens each; each stop takes a few seconds while the renderer draws it. NEXT: request_fix(issueId) for something that looks bad, or get_environment(siteId) for the whole site.`,
    z.strictObject({ siteId, focus: z.array(assetTag).max(8).optional().describe('Assets to see first, e.g. ["V-504"]. Omit to let the inspector pick the worst.'),
                     maxStops: z.number().int().min(1).max(8).default(5).describe('Stops on the tour, 1 to 8.') }),
    TourSchema, async ({ siteId: id, focus, maxStops }, call) => {
      backend.assertProperty(id);
      const started = obj(await backend.json('/api/site-tours', ANY, { method: 'POST', body: { siteId: id, ...(focus?.length ? { focus } : {}), maxStops, requester: `mcp:${call.requester}`.slice(0, 80) } }));
      const tour = str(started.id);
      if (!tour) throw new AdapterError('UPSTREAM_RESPONSE_INVALID', 'The backend did not return a tour.', 'Retry request_site_tour.', true);
      const raw = str(started.state) === 'running' ? await waitForTour(tour, call.ctx) : started;
      return tourResult(raw, `get_site_tour(tourId="${tour}") in a minute for the rest of the tour and its pictures.`);
    }, LOCAL_WRITE);

  tool('get_site_tour', `Read a site tour by tourId: every stop (looks good or looks bad, with the reasons), the inspector's summary and the pictures of what is wrong as images (at most ${MAX_TOUR_IMAGES}). Free and read-only; ~350 tokens per image. NEXT: request_fix(issueId) or eye_go_to(assetTag) for anything that looks bad.`,
    z.strictObject({ tourId }), TourSchema, async ({ tourId: id }) => {
      const raw = obj(await backend.json(`/api/site-tours/${encodeURIComponent(id)}`, ANY));
      return tourResult(raw, `get_site_tour(tourId="${id}") again in a minute; the tour is still going.`);
    }, READ_ONLY);
}
