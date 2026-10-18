import { z } from 'zod';
import type { RuntimeConfig, PropertyId } from './config.js';

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
    'ADAPTER_ERROR', 'The local adapter could not complete this request.', 'Check the local runtime log and retry the same read tool.', true,
  );
  return { isError: true as const, content: [{ type: 'text' as const, text: JSON.stringify({
    code: known.code, message: known.message, recovery: known.recovery, retryable: known.retryable,
    ...(known.httpStatus ? { httpStatus: known.httpStatus } : {}),
  }) }] };
}

/** Thin HTTP adapter. FastAPI owns all persistence and executes all inspection jobs. */
export class Backend {
  constructor(readonly config: RuntimeConfig) {}

  assertProperty(propertyId: PropertyId) {
    if (!this.config.allowedProperties.includes(propertyId)) {
      throw new AdapterError('PROPERTY_SCOPE', 'This property is outside this endpoint’s permitted scope.', 'Call list_properties and use one of the returned IDs.');
    }
  }

  async json<T extends z.ZodType>(path: string, schema: T, options: { method?: 'GET' | 'POST'; body?: unknown } = {}): Promise<z.output<T>> {
    let response: Response;
    try {
      response = await fetch(`${this.config.backendUrl}${path}`, {
        method: options.method || 'GET', redirect: 'error', signal: AbortSignal.timeout(this.config.requestTimeoutMs),
        headers: {
          Accept: 'application/json', ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...(this.config.backendToken ? { Authorization: `Bearer ${this.config.backendToken}` } : {}),
        },
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      });
    } catch {
      throw new AdapterError('BACKEND_UNAVAILABLE', `The local backend at ${this.config.backendUrl} did not respond.`, 'Start the local backend, check its /health endpoint, then retry. No alternate or external server was contacted.', true);
    }
    if (!response.ok) {
      let detail = '';
      try { const parsed: unknown = await response.json(); if (parsed && typeof parsed === 'object' && 'detail' in parsed && typeof parsed.detail === 'string') detail = ` ${parsed.detail.slice(0, 400)}`; } catch { /* Status is sufficient for a non-JSON upstream failure. */ }
      const recovery = response.status === 401 || response.status === 403
        ? 'Set STEWARD_BACKEND_TOKEN to the backend’s configured API token; never put credentials in tool arguments.'
        : response.status === 404 ? 'Use list_properties and list_components to rediscover the current property and asset IDs.'
          : response.status >= 500 ? 'Check the local backend log and retry after it recovers.' : 'Check the tool arguments against the returned schema and retry with a valid ID or query.';
      throw new AdapterError('UPSTREAM_HTTP_ERROR', `Backend returned HTTP ${response.status}.${detail}`, recovery, response.status >= 500 || response.status === 429, response.status);
    }
    let data: unknown;
    try { data = await response.json(); } catch {
      throw new AdapterError('UPSTREAM_RESPONSE_INVALID', 'Backend returned a non-JSON response.', 'Check that STEWARD_BACKEND_URL targets the local API, then retry.', true);
    }
    const parsed = schema.safeParse(data);
    if (!parsed.success) {
      const first = parsed.error.issues[0];
      throw new AdapterError('UPSTREAM_RESPONSE_INVALID', `Backend response does not match the application contract at ${first?.path.join('.') || 'root'}.`, 'Restart matching versions of the local backend and MCP adapter, then retry.', false);
    }
    return parsed.data;
  }

  propertyPath(propertyId: PropertyId, suffix: string) {
    this.assertProperty(propertyId);
    return `/api/properties/${propertyId}/${suffix}`;
  }
}
