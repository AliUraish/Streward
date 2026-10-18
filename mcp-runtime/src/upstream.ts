import { AsyncLocalStorage } from 'node:async_hooks';
import { z } from 'zod';
import type { RuntimeConfig, PropertyId } from './config.js';

/** The actor for the request being served (eval harness act-as); falls back to config.actor. */
export const actorStore = new AsyncLocalStorage<string>();

export class AdapterError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly recovery: string,
    public readonly retryable = false,
    public readonly httpStatus?: number,
  ) { super(message); this.name = 'AdapterError'; }
}

export function errorResult(error: unknown) {
  const known = error instanceof AdapterError ? error : new AdapterError(
    'ADAPTER_ERROR', 'The adapter could not complete this request.', 'Check the MCP runtime log and retry the same read tool.', true,
  );
  return { isError: true as const, content: [{ type: 'text' as const, text: JSON.stringify({
    code: known.code, message: known.message, recovery: known.recovery, retryable: known.retryable,
    ...(known.httpStatus ? { httpStatus: known.httpStatus } : {}),
  }) }] };
}

interface UpstreamErrorBody { detail?: string; code?: string; recovery?: string }

export function parseErrorBody(parsed: unknown): UpstreamErrorBody {
  if (!parsed || typeof parsed !== 'object') return {};
  const body = parsed as Record<string, unknown>;
  const out: UpstreamErrorBody = {};
  // FastAPI HTTPException(detail=...) may carry a string or a structured object {detail, code, recovery}.
  const detail = body.detail;
  if (typeof detail === 'string') out.detail = detail;
  else if (Array.isArray(detail)) {
    // FastAPI 422 validation errors: [{loc, msg, type}]
    out.detail = detail.map(item => (item && typeof item === 'object' && 'msg' in item ? `${((item as { loc?: unknown[] }).loc ?? []).filter(part => part !== 'body').join('.')}: ${String((item as { msg: unknown }).msg)}` : String(item))).join('; ');
    out.code = 'INVALID_REQUEST';
    out.recovery = 'Fix the named argument and retry; the backend validated the request body, nothing was written.';
  } else if (detail && typeof detail === 'object') {
    const inner = detail as Record<string, unknown>;
    if (typeof inner.detail === 'string') out.detail = inner.detail;
    else if (typeof inner.message === 'string') out.detail = inner.message;
    if (typeof inner.code === 'string') out.code = inner.code;
    if (typeof inner.recovery === 'string') out.recovery = inner.recovery;
  }
  if (typeof body.code === 'string') out.code = body.code;
  if (typeof body.recovery === 'string') out.recovery = body.recovery;
  if (!out.detail && typeof body.message === 'string') out.detail = body.message;
  return out;
}

/** Thin HTTP adapter. FastAPI owns all persistence, verification, signing and dispatch. */
export class Backend {
  constructor(readonly config: RuntimeConfig) {}

  assertProperty(propertyId: PropertyId) {
    if (!this.config.allowedProperties.includes(propertyId)) {
      throw new AdapterError('PROPERTY_SCOPE', 'This site is outside this endpoint’s permitted scope.', 'Call list_sites and use one of the returned siteId values.');
    }
  }

  /** The agent this request acts as (X-Steward-Actor). */
  get actor(): string { return actorStore.getStore() ?? this.config.actor; }

  async json<T extends z.ZodType>(path: string, schema: T, options: { method?: 'GET' | 'POST' | 'PUT'; body?: unknown; timeoutMs?: number; signal?: AbortSignal; headers?: Record<string, string> } = {}): Promise<z.output<T>> {
    let response: Response;
    const actor = this.actor;
    const timeout = AbortSignal.timeout(options.timeoutMs ?? this.config.requestTimeoutMs);
    try {
      response = await fetch(`${this.config.backendUrl}${path}`, {
        method: options.method || 'GET', redirect: 'error', signal: options.signal ? AbortSignal.any([timeout, options.signal]) : timeout,
        headers: {
          Accept: 'application/json', ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
          // The acting agent on every call (reads included, so the backend can log operator MCP activity in the transcript).
          'X-Steward-Actor': actor,
          ...(this.config.backendToken ? { Authorization: `Bearer ${this.config.backendToken}` } : {}),
          ...(options.headers ?? {}),
        },
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      });
    } catch (error) {
      if (options.signal?.aborted) throw new AdapterError('CANCELLED', 'The client cancelled this request.', 'Call the tool again if you still need the result.', true);
      void error;
      throw new AdapterError('BACKEND_UNAVAILABLE', `The Steward backend at ${this.config.backendUrl} did not respond.`, 'Start the backend, check its /health endpoint, then retry. No alternate server was contacted. If a write (resolve with budget, attest, escalate) may have reached the backend, call get_changes before repeating it.', true);
    }
    if (!response.ok) {
      let upstream: UpstreamErrorBody = {};
      try { upstream = parseErrorBody(await response.json()); } catch { /* Status is sufficient for a non-JSON upstream failure. */ }
      const detail = upstream.detail ? ` ${upstream.detail.slice(0, 600)}` : '';
      if (upstream.code === 'AUTHORITY_DENIED') {
        // The authority table (REALITY-CONTRACT-2.md) refused this actor. Not retryable as the same actor; the backend names who may do it.
        throw new AdapterError('AUTHORITY_DENIED', `Backend refused actor "${actor}" (HTTP ${response.status}).${detail}`,
          upstream.recovery || `Agent "${actor}" may not perform this action. Only the agent the backend names may; the operator starts missions and reads, Atlas delegates, a Warden attests for its own site, the Runner dispatches. Start a mission instead of acting directly, or run this MCP with STEWARD_MCP_ACTOR set to the permitted agent.`, false, response.status);
      }
      const fallbackRecovery = response.status === 401 || response.status === 403
        ? 'Set STEWARD_BACKEND_TOKEN to the backend’s configured API token; never put credentials in tool arguments.'
        : response.status === 404 ? 'Use list_sites and list_components to rediscover the current siteId, asset tags and work item IDs.'
          : response.status >= 500 ? 'Check the backend log and retry after it recovers.' : 'Check the tool arguments against the returned schema and retry with a valid ID or query.';
      throw new AdapterError(upstream.code || 'UPSTREAM_HTTP_ERROR', `Backend returned HTTP ${response.status}.${detail}`, upstream.recovery || fallbackRecovery, response.status >= 500 || response.status === 429, response.status);
    }
    let data: unknown;
    try { data = await response.json(); } catch {
      throw new AdapterError('UPSTREAM_RESPONSE_INVALID', 'Backend returned a non-JSON response.', 'Check that STEWARD_BACKEND_URL targets the Steward API, then retry.', true);
    }
    const parsed = schema.safeParse(data);
    if (!parsed.success) {
      const first = parsed.error.issues[0];
      throw new AdapterError('UPSTREAM_RESPONSE_INVALID', `Backend response does not match the application contract at ${first?.path.join('.') || 'root'}: ${first?.message ?? 'invalid'}.`, 'Restart matching versions of the backend and MCP adapter (see REALITY-CONTRACT.md), then retry.', false);
    }
    return parsed.data;
  }

  /**
   * Try candidate paths in order; a 404/405/501 ("route not there yet") moves to the next one. Used only where
   * REALITY-CONTRACT-3.md names no path, with the same candidates the dashboard client (frontend/src/lib/api-3.ts) uses.
   */
  async first<T>(...loaders: (() => Promise<T>)[]): Promise<T> {
    let last: unknown;
    for (const load of loaders) {
      try { return await load(); } catch (error) {
        last = error;
        if (!(error instanceof AdapterError && [404, 405, 501].includes(error.httpStatus ?? 0))) throw error;
      }
    }
    throw last;
  }

  propertyPath(propertyId: PropertyId, suffix: string) {
    this.assertProperty(propertyId);
    return `/api/properties/${propertyId}/${suffix}`;
  }
}
