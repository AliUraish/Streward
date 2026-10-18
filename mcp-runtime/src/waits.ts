/**
 * wait_for (REALITY-CONTRACT-3.md §7): hold one MCP tool call open while the backend long-polls a wait, so the
 * calling model generates nothing until the event fires.
 *
 *  - Opens a wait with POST /api/waits {siteId?, event, filter?} unless a waitId is passed back in.
 *  - Long-polls GET /api/waits/{waitId}?timeout=<s> in chunks of at most 15 s (the backend caps one long-poll at
 *    300 s; short chunks keep every hop, tunnels included, well inside its idle timeout) and returns the moment a
 *    chunk answers `fired`.
 *  - Sends an MCP progress notification immediately (the response's first byte, for clients that time the first
 *    byte) and then every 15 s, so clients that reset their timeout on progress keep the request alive.
 *  - At the end of the window returns `still_waiting` with the same waitId and the instruction to call again.
 *
 * Window defaults and the client limits behind them are in README "Waiting: client limits".
 */
import { AdapterError, type Backend } from './upstream.js';
import { UpWaitCreatedSchema, UpWaitResultSchema } from './schemas3.js';

/** The backend also accepts scenario.step; it is not offered here (the eval harness waits with event any, filter {type: "scenario"}). */
export const WAIT_EVENTS = ['work_item.resolved', 'issue.changed', 'reply.received', 'board.resolved', 'any'] as const;
export type WaitEvent = typeof WAIT_EVENTS[number];
export const PROGRESS_INTERVAL_MS = 15_000;
export const MAX_WAIT_SECONDS = 300;

export interface WaitInput { event: WaitEvent; siteId?: string; filter?: Record<string, unknown>; waitId?: string; timeoutSeconds: number }
export interface WaitDeps {
  backend: Backend;
  /** ctx.reportProgress: resolves true when a notification was sent (the client supplied a progress token). */
  report(progress: number, total: number, message: string): Promise<boolean>;
  signal?: AbortSignal;
  progressIntervalMs?: number;
  /** Upper bound for one long-poll chunk, seconds. */
  chunkSeconds?: number;
}
export interface WaitOutput {
  status: string; waitId: string; event: Record<string, unknown> | null; waitedSeconds: number; windowSeconds: number;
  progressNotifications: number; tokensWhileWaiting: 0; nextStep: string;
}

/**
 * One flat event for the caller: the backend fires {name, change: {type, propertyId, refId, summary, at, ...}, extra: {...}};
 * a flat event (the fixture's) passes through. name is the wait event (issue.changed, ...), type the Change type.
 */
export function flattenEvent(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { value: raw ?? null };
  const event = raw as Record<string, unknown>;
  const change = event.change && typeof event.change === 'object' ? event.change as Record<string, unknown> : null;
  const extra = event.extra && typeof event.extra === 'object' ? event.extra as Record<string, unknown> : {};
  if (!change) return { ...event, name: event.name ?? event.type, siteId: event.siteId ?? event.propertyId ?? null };
  const { change: _change, extra: _extra, ...rest } = event;
  void _change; void _extra;
  return { ...rest, ...change, ...extra, name: event.name ?? change.type, type: change.type, siteId: change.propertyId ?? extra.siteId ?? null, change };
}

const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>(resolve => {
  const timer = setTimeout(resolve, ms);
  signal?.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
});

export async function holdWait(input: WaitInput, deps: WaitDeps): Promise<WaitOutput> {
  const { backend, signal } = deps;
  const windowSeconds = Math.max(1, Math.min(MAX_WAIT_SECONDS, input.timeoutSeconds));
  const chunkMax = Math.max(1, Math.min(15, deps.chunkSeconds ?? 15));
  let waitId = input.waitId;
  if (!waitId) {
    const created = await backend.json('/api/waits', UpWaitCreatedSchema, { method: 'POST', body: { event: input.event, ...(input.siteId ? { siteId: input.siteId } : {}), ...(input.filter ? { filter: input.filter } : {}) } });
    // The backend answers with the wait record ({id, event, status, ...}); a {waitId} body is accepted too.
    waitId = created.waitId ?? created.id;
    if (!waitId) throw new AdapterError('UPSTREAM_RESPONSE_INVALID', 'The backend created a wait without an id.', 'Check POST /api/waits against REALITY-CONTRACT-3.md §7.');
  }
  const started = Date.now();
  const elapsed = () => Math.round((Date.now() - started) / 1000);
  let notifications = 0;
  const progress = async () => {
    try {
      if (await deps.report(Math.min(elapsed(), windowSeconds), windowSeconds, `Waiting for ${input.event}${input.siteId ? ` on ${input.siteId}` : ''} (waitId ${waitId}): ${elapsed()} s of ${windowSeconds} s. The model is idle; no tokens are spent while this call is held.`)) notifications += 1;
    } catch { /* the client went away; the long-poll loop sees the abort */ }
  };
  await progress();
  const timer = setInterval(() => { void progress(); }, deps.progressIntervalMs ?? PROGRESS_INTERVAL_MS);
  const done = (status: string, event: Record<string, unknown> | null, nextStep: string): WaitOutput => ({
    status, waitId: waitId!, event, waitedSeconds: elapsed(), windowSeconds, progressNotifications: notifications, tokensWhileWaiting: 0, nextStep,
  });
  try {
    for (;;) {
      if (signal?.aborted) throw new AdapterError('CANCELLED', 'The client cancelled wait_for.', `The wait is still open on the backend; call wait_for with waitId="${waitId}" to resume.`, true);
      const remainingMs = windowSeconds * 1000 - (Date.now() - started);
      if (remainingMs <= 250) break;
      const chunk = Math.max(1, Math.min(chunkMax, Math.floor(remainingMs / 1000)));
      const asked = Date.now();
      let result;
      try {
        result = await backend.json(`/api/waits/${encodeURIComponent(waitId)}?${new URLSearchParams({ timeout: String(chunk) })}`, UpWaitResultSchema, { timeoutMs: (chunk + 15) * 1000, signal });
      } catch (error) {
        if (error instanceof AdapterError && error.httpStatus === 404) throw new AdapterError('WAIT_NOT_FOUND', `Wait ${waitId} is unknown or expired on the backend.`, 'Call wait_for again without waitId to open a new wait for the same event.', false, 404);
        throw error;
      }
      const status = result.status;
      if (status === 'fired') {
        return done('fired', flattenEvent(result.event), 'The event fired. Read it (event.name, event.type, event.issueId / workItemId / refId) and act: get_issue, get_board_meeting, get_conversation or get_receipt for the record it names.');
      }
      if (status !== 'still_waiting' && status !== 'waiting') {
        return done(status, null, `The backend ended this wait with status "${status}". Open a new wait with wait_for (no waitId) if you still need the event.`);
      }
      // A backend that answers a long-poll early (no long-poll support yet) is re-asked at most every 2 s, still inside this one held call.
      const took = Date.now() - asked;
      if (took < 2000) await sleep(Math.min(2000 - took, Math.max(0, windowSeconds * 1000 - (Date.now() - started))), signal);
    }
  } finally { clearInterval(timer); }
  return done('still_waiting', null, `Nothing yet. Call wait_for again with waitId="${waitId}" (same event); it holds again without spending tokens. Do not switch to polling.`);
}
