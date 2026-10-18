/**
 * Steward tool-call telemetry for the backend (the source of get_eval_findings). Every MCP tool call is reported
 * fire-and-forget as one event with the acting agent and estimated input/output tokens; the same calls are also
 * delivered to Armature by src/analytics.ts when an ingest key is set. Never blocks or fails a tool call.
 *
 * Route: POST /api/telemetry {agentId, tool, tokens, ms, ok, siteId?, detail?} (backend/src/main.py TelemetryRequest);
 * tokens = estimated input + output, detail spells out the split, and inputTokens / outputTokens / requester ride along
 * for a backend that keeps them. If the backend answers 404/405/501 the sink pauses for a minute, so a backend
 * without the route costs one request per minute, not one per tool call.
 */
import type { RuntimeConfig } from './config.js';

export interface ToolTelemetryEvent {
  tool: string;
  agentId: string;
  requester: string;
  siteId?: string;
  ok: boolean;
  code?: string;
  durationMs: number;
  inputTokens: number;
  outputTokens: number;
  estimated: true;
  at: string;
}

/** Rough token estimate (~4 characters per token for English and JSON). Labelled `estimated: true` on every event. */
export function estimateTokens(value: unknown): number {
  if (value === undefined || value === null) return 0;
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return Math.ceil((text?.length ?? 0) / 4);
}

export interface TelemetrySink { record(event: ToolTelemetryEvent): void; readonly sent: number; readonly paused: boolean }

export const TELEMETRY_PATH = '/api/telemetry';

export function createTelemetry(config: RuntimeConfig, fetcher: typeof fetch = fetch): TelemetrySink {
  let pausedUntil = 0;
  let sent = 0;
  return {
    get sent() { return sent; },
    get paused() { return Date.now() < pausedUntil; },
    record(event) {
      if (Date.now() < pausedUntil) return;
      void fetcher(`${config.backendUrl}${TELEMETRY_PATH}`, {
        method: 'POST', redirect: 'error', signal: AbortSignal.timeout(3000),
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Steward-Actor': event.agentId, ...(config.backendToken ? { Authorization: `Bearer ${config.backendToken}` } : {}) },
        body: JSON.stringify({
          agentId: event.agentId, tool: event.tool, tokens: event.inputTokens + event.outputTokens, ms: event.durationMs, ok: event.ok,
          ...(event.siteId ? { siteId: event.siteId } : {}),
          detail: `mcp ${event.ok ? 'ok' : `error ${event.code ?? ''}`.trim()}; est. tokens in ${event.inputTokens} out ${event.outputTokens}; requester ${event.requester}`.slice(0, 200),
          inputTokens: event.inputTokens, outputTokens: event.outputTokens, requester: event.requester, estimated: true, source: 'mcp', at: event.at,
        }),
      }).then(response => {
        if ([404, 405, 501].includes(response.status)) pausedUntil = Date.now() + 60_000;
        else if (response.ok) sent += 1;
        void response.body?.cancel().catch(() => {});
      }).catch(() => { pausedUntil = Date.now() + 10_000; });
    },
  };
}

export const noopTelemetry: TelemetrySink = { record() { /* no-op */ }, sent: 0, paused: false };
