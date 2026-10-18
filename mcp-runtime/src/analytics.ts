/**
 * Analytics hook. Default is a no-op. The Armature SDK (`@armature-tech/mcp-analytics`
 * 0.6.47, documented in armature/README.md) is imported only when an ingest key is set
 * (ANALYTICS_INGEST_API_KEY, or ARMATURE_API_KEY which maps to it) and the package is
 * installed. Only the `/v2` subpath is importable next to mcp-use 2.10.1 (the package
 * root imports the v1 SDK). A missing package or a failing import logs one line and
 * degrades to the no-op; analytics never fail a tool call.
 *
 * Two attachments, both through the vendor's public v2 API:
 *  1. `wrapMcpHandler` around the Hono app's fetch (armature/README.md §3 option A):
 *     mints an `Mcp-Session-Id` on legacy-handshake `initialize` requests and records
 *     `session_init`, so 2025-era clients (Claude Code, Cursor) get session attribution.
 *     Installed as `/mcp` middleware that re-enters the app with a marker header, because
 *     mcp-use mounts its own `/mcp` route and does not expose the inner handler.
 *  2. `withMcpAnalytics` on a tiny registry shim: mcp-use builds a fresh SDK McpServer per
 *     request and never exposes it, so there is no documented per-tool hook. The SDK only
 *     needs "anything with registerTool"; we register each Steward tool on the shim, the
 *     SDK wraps the callback, and server.ts's `tool()` helper invokes the wrapped callback
 *     with a handler context shaped like the SDK's (`mcpReq.envelope`, `http.req.headers`,
 *     `sessionId`). Result: real `tool_call` events with client name, user agent, session
 *     id and Steward's requester/site metadata. Verified in tests with an injected emitter.
 */
import type { MCPServer } from 'mcp-use';

export interface ToolCallEvent {
  tool: string;
  requester: string;
  ok: boolean;
  durationMs: number;
  siteId?: string;
  code?: string;
  mutates: boolean;
}

/** Minimal CallToolResult shape; the SDK snapshots `content`, `structuredContent`, `isError` and `_meta`. */
export interface ToolResultLike { content: unknown[]; structuredContent?: unknown; isError?: boolean; _meta?: Record<string, unknown> }

/** What the MCP request exposes about the caller, extracted in server.ts from mcp-use's RequestContext. */
export interface CallerContext {
  requester: string;
  siteId?: string;
  clientName?: string;
  clientVersion?: string;
  capabilities?: Record<string, unknown>;
  headers?: Headers;
  sessionId?: string;
  /** The mcp-use RequestContext for this call (progress, elicitation, signal); opaque to the analytics layer. */
  ctx?: unknown;
}

export type ToolHandler = (args: Record<string, unknown>, caller: CallerContext) => Promise<ToolResultLike>;

export interface Analytics {
  readonly provider: 'none' | 'armature';
  /** Local hook, called by server.ts for every tool call (tests and logs). */
  toolCall(event: ToolCallEvent): void;
  /** Wrap a tool handler so the provider records the call. Identity for the no-op provider. */
  instrument(name: string, description: string, handler: ToolHandler): ToolHandler;
  /** Attach request-level hooks (session attribution) to the server. Call before listen. */
  attach(server: MCPServer): void;
  /** Flush background delivery. Call on SIGTERM before exit. */
  close(): Promise<void>;
}

export const noopAnalytics: Analytics = {
  provider: 'none',
  toolCall() { /* no-op */ },
  instrument: (_name, _description, handler) => handler,
  attach() { /* no-op */ },
  close: async () => { /* no-op */ },
};

/** Test seam: inject the SDK's `emit` so batches can be captured without the network. */
export interface AnalyticsOverrides { emit?: (batch: unknown) => void | Promise<void>; delivery?: 'background' | 'await' }

const CLIENT_INFO_KEY = 'io.modelcontextprotocol/clientInfo';
const CLIENT_CAPABILITIES_KEY = 'io.modelcontextprotocol/clientCapabilities';
/** Marks a request already passed through wrapMcpHandler so the middleware does not loop. Spoofing it only skips analytics. */
export const REENTRY_HEADER = 'x-steward-analytics-reentry';

/** Build the handler context the Armature v2 adapter reads (`captureV2Request` in its v2.js). */
function armatureContext(caller: CallerContext) {
  const envelope = caller.clientName || caller.capabilities
    ? { ...(caller.clientName ? { [CLIENT_INFO_KEY]: { name: caller.clientName, ...(caller.clientVersion ? { version: caller.clientVersion } : {}) } } : {}), ...(caller.capabilities ? { [CLIENT_CAPABILITIES_KEY]: caller.capabilities } : {}) }
    : undefined;
  return {
    ...(envelope ? { mcpReq: { envelope } } : {}),
    ...(caller.headers ? { http: { req: { headers: caller.headers } } } : {}),
    ...(caller.sessionId ? { sessionId: caller.sessionId } : {}),
    steward: { requester: caller.requester, ...(caller.siteId ? { siteId: caller.siteId } : {}) },
    stewardCaller: caller,
  };
}

interface ShimRegistration { handler: (...args: unknown[]) => unknown; inputSchema?: unknown; description?: string; update(patch: { callback?: unknown }): void }

export async function loadAnalytics(env: NodeJS.ProcessEnv = process.env, serverName = 'steward', overrides: AnalyticsOverrides = {}): Promise<Analytics> {
  const apiKey = env.ANALYTICS_INGEST_API_KEY || env.ARMATURE_API_KEY;
  if (!apiKey) return noopAnalytics;
  let v2: typeof import('@armature-tech/mcp-analytics/v2');
  try { v2 = await import('@armature-tech/mcp-analytics/v2'); } catch (error) {
    console.warn(`Armature SDK (@armature-tech/mcp-analytics) is not installed or failed to import: ${error instanceof Error ? error.message : 'unknown'}. Analytics stay off.`);
    return noopAnalytics;
  }
  // Hoisted config object: the SDK keys its recorder (delivery queue + session_init dedupe) on it; pass the SAME object everywhere.
  const analyticsConfig = { armature: {
    apiKey,
    ...(env.ANALYTICS_INGEST_URL ? { endpointUrl: env.ANALYTICS_INGEST_URL } : {}), // US default when unset; EU must set it
    delivery: overrides.delivery ?? 'background' as const,
    sendFeedback: false, // keep Steward's advertised tool list exact
    ...(overrides.emit ? { emit: overrides.emit } : {}),
    onError: (error: unknown) => { console.warn(`[armature] delivery failed: ${error instanceof Error ? error.message : String(error)}`); },
  } };
  // Registry shim: withMcpAnalytics replaces `registerTool` on it and wraps every callback via `update({callback})`.
  const shim = {
    registerTool(_name: string, config: { inputSchema?: unknown; description?: string }, cb: (...args: unknown[]) => unknown): ShimRegistration {
      const registration: ShimRegistration = { handler: cb, inputSchema: config.inputSchema, description: config.description, update(patch) { if (typeof patch.callback === 'function') registration.handler = patch.callback as ShimRegistration['handler']; } };
      return registration;
    },
  };
  try {
    v2.withMcpAnalytics(shim as unknown as Parameters<typeof v2.withMcpAnalytics>[0], analyticsConfig, {
      metadata: ctx => { const steward = (ctx as { steward?: Record<string, unknown> })?.steward; return { steward_server: serverName, ...(steward ? { steward_requester: steward.requester, ...(steward.siteId ? { steward_site: steward.siteId } : {}) } : {}) }; },
    });
  } catch (error) {
    console.warn(`Armature SDK could not be initialised: ${error instanceof Error ? error.message : 'unknown'}. Analytics stay off.`);
    return noopAnalytics;
  }
  return {
    provider: 'armature',
    toolCall() { /* the SDK wrapper records the call */ },
    instrument(name, description, handler) {
      const registration = shim.registerTool(name, { description, inputSchema: { type: 'object' } }, (args, ctx) => handler(args as Record<string, unknown>, (ctx as { stewardCaller: CallerContext }).stewardCaller));
      return async (args, caller) => await registration.handler(args, armatureContext(caller)) as ToolResultLike;
    },
    attach(server) {
      // armature/README.md §3 option A: wrapMcpHandler mints Mcp-Session-Id on legacy initialize and records session_init.
      const wrapped = v2.wrapMcpHandler({ fetch: (request: Request) => Promise.resolve(server.app.fetch(request)) }, analyticsConfig);
      server.app.use('/mcp', async (context, next) => {
        if (context.req.header(REENTRY_HEADER)) { await next(); return; }
        const raw = context.req.raw;
        const headers = new Headers(raw.headers); headers.set(REENTRY_HEADER, '1');
        const body = raw.method === 'GET' || raw.method === 'HEAD' ? undefined : await raw.arrayBuffer();
        return wrapped.fetch(new Request(raw.url, { method: raw.method, headers, ...(body ? { body } : {}) }));
      });
    },
    async close() { try { await v2.flushMcpAnalytics(analyticsConfig); } catch { /* ignore */ } },
  };
}
