/**
 * Resource subscriptions for steward://sites/{siteId}/overview (REALITY-CONTRACT-3.md §10).
 *
 * One shared poller per site inside this MCP process reads GET /api/properties/{id}/changes every 2 s, only while
 * that site has at least one subscriber, and on every new Change emits `notifications/resources/updated` for the
 * site's overview URI. Two delivery paths, because mcp-use 2.10.1 serves both protocol eras statelessly:
 *
 *  - 2026-07-28 clients subscribe with `subscriptions/listen` {notifications: {resourceSubscriptions: [uri]}}. The
 *    SDK owns that stream; we publish with server.notifyResourceUpdated(uri) and count open listen streams per URI
 *    here by watching the request and its response body (so the poller starts and stops with them).
 *  - 2025-era clients send `resources/subscribe`, which the stateless legacy path answers "Method not found", and
 *    have no standalone GET stream (mcp-use answers GET with 204). This middleware fills that gap: it answers
 *    resources/subscribe / unsubscribe itself, keyed by Mcp-Session-Id (minted on the legacy initialize response
 *    when nothing upstream minted one), and serves the session's GET /mcp event stream, on which the
 *    notifications are written.
 *
 * Single-process state: a multi-replica deployment would need a shared bus (not needed for this build).
 */
import { randomUUID } from 'node:crypto';
import type { MCPServer } from 'mcp-use';
import { z } from 'zod';
import type { RuntimeConfig, PropertyId } from './config.js';
import type { Backend } from './upstream.js';

export const OVERVIEW_TEMPLATE = 'steward://sites/{siteId}/overview';
export const overviewUri = (siteId: string) => `steward://sites/${siteId}/overview`;
const OVERVIEW_RE = /^steward:\/\/sites\/([a-z][a-z0-9-]{2,30})\/overview$/;
const ENVELOPE_KEY = 'io.modelcontextprotocol/protocolVersion';
/** Same marker as src/analytics.ts: a request re-entering the app from the analytics wrapper was already handled. */
const REENTRY_HEADER = 'x-steward-analytics-reentry';
const KEEPALIVE_MS = 15_000;

interface LegacyStream { write(chunk: string): void; close(): void }
interface SitePoller { timer: NodeJS.Timeout | null; version: number | null; busy: boolean }

export class SubscriptionHub {
  /** Open modern listen streams per overview URI. */
  readonly modern = new Map<string, number>();
  /** Legacy session id → subscribed overview URIs. */
  readonly legacy = new Map<string, Set<string>>();
  /** Legacy session id → its open GET event stream. */
  readonly streams = new Map<string, LegacyStream>();
  readonly pollers = new Map<string, SitePoller>();
  /** Emissions per site, for tests and the /health line. */
  readonly emitted = new Map<string, number>();
  private readonly pollMs: number;

  constructor(private readonly server: MCPServer, private readonly backend: Backend, private readonly config: RuntimeConfig) {
    this.pollMs = config.subscriptionPollMs ?? 2000;
  }

  siteOf(uri: string): PropertyId | null {
    const match = uri.match(OVERVIEW_RE);
    const site = match?.[1];
    return site && (this.config.allowedProperties as readonly string[]).includes(site) ? site as PropertyId : null;
  }

  subscribers(site: string): number {
    const uri = overviewUri(site);
    let count = this.modern.get(uri) ?? 0;
    for (const uris of this.legacy.values()) if (uris.has(uri)) count += 1;
    return count;
  }

  /** Start or stop the site's poller to match its subscriber count. */
  private sync(site: string) {
    const count = this.subscribers(site);
    let poller = this.pollers.get(site);
    if (count > 0 && !poller?.timer) {
      poller = poller ?? { timer: null, version: null, busy: false };
      this.pollers.set(site, poller);
      const tick = () => { void this.poll(site); };
      poller.timer = setInterval(tick, this.pollMs);
      poller.timer.unref?.();
      tick();
    } else if (count === 0 && poller?.timer) {
      clearInterval(poller.timer); poller.timer = null; poller.version = null;
    }
  }

  private async poll(site: string) {
    const poller = this.pollers.get(site);
    if (!poller || poller.busy) return;
    poller.busy = true;
    try {
      const result = await this.backend.json(`${this.backend.propertyPath(site as PropertyId, 'changes')}?${new URLSearchParams({ since: String(poller.version ?? 0), limit: '1' })}`, z.looseObject({ version: z.number() }));
      if (poller.version === null) poller.version = result.version; // first read: baseline, no event
      else if (result.version > poller.version) { poller.version = result.version; await this.emit(site); }
    } catch { /* backend down: keep the poller, try again next tick */ } finally { poller.busy = false; }
  }

  /** Publish notifications/resources/updated for the site's overview to every subscriber. */
  async emit(site: string) {
    const uri = overviewUri(site);
    this.emitted.set(site, (this.emitted.get(site) ?? 0) + 1);
    try { await this.server.notifyResourceUpdated(uri); } catch { /* no modern listeners */ }
    const frame = `event: message\ndata: ${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/resources/updated', params: { uri } })}\n\n`;
    for (const [session, uris] of this.legacy) if (uris.has(uri)) this.streams.get(session)?.write(frame);
  }

  private addModern(uris: string[]) { for (const uri of uris) this.modern.set(uri, (this.modern.get(uri) ?? 0) + 1); for (const uri of uris) this.sync(this.siteOf(uri)!); }
  private dropModern(uris: string[]) {
    for (const uri of uris) { const next = (this.modern.get(uri) ?? 1) - 1; if (next > 0) this.modern.set(uri, next); else this.modern.delete(uri); }
    for (const uri of uris) this.sync(this.siteOf(uri)!);
  }
  private dropSession(session: string) {
    const uris = this.legacy.get(session);
    this.legacy.delete(session);
    this.streams.get(session)?.close();
    this.streams.delete(session);
    for (const uri of uris ?? []) this.sync(this.siteOf(uri)!);
  }

  stop() {
    for (const poller of this.pollers.values()) if (poller.timer) clearInterval(poller.timer);
    for (const stream of this.streams.values()) stream.close();
    this.pollers.clear(); this.streams.clear();
  }

  /** Install the /mcp middleware. Call after any auth middleware and before analytics.attach(). */
  install() {
    const hub = this;
    const rpcError = (id: unknown, code: number, message: string) => new Response(JSON.stringify({ jsonrpc: '2.0', id: id ?? null, error: { code, message } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    this.server.app.use('/mcp', async (context, next) => {
      const raw = context.req.raw;
      if (context.req.header(REENTRY_HEADER)) { await next(); return; }
      const session = context.req.header('mcp-session-id') || '';

      // Legacy standalone event stream for a session that may hold resource subscriptions.
      if (raw.method === 'GET' && session && (context.req.header('accept') || '').includes('text/event-stream')) {
        let keepalive: NodeJS.Timeout | undefined;
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            let open = true;
            const stream: LegacyStream = {
              write(chunk) { if (open) { try { controller.enqueue(encoder.encode(chunk)); } catch { open = false; } } },
              close() { if (open) { open = false; clearInterval(keepalive); try { controller.close(); } catch { /* already closed */ } } },
            };
            hub.streams.get(session)?.close();
            hub.streams.set(session, stream);
            stream.write(': steward subscription stream\n\n');
            keepalive = setInterval(() => stream.write(': keepalive\n\n'), KEEPALIVE_MS);
            keepalive.unref?.();
            raw.signal?.addEventListener('abort', () => { stream.close(); if (hub.streams.get(session) === stream) hub.streams.delete(session); }, { once: true });
          },
          cancel() { clearInterval(keepalive); hub.streams.delete(session); },
        });
        return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache, no-transform', Connection: 'keep-alive', 'Mcp-Session-Id': session } });
      }
      if (raw.method === 'DELETE' && session) { hub.dropSession(session); await next(); return; }
      if (raw.method !== 'POST' || !(context.req.header('content-type') || '').includes('json')) { await next(); return; }

      let message: { id?: unknown; method?: unknown; params?: Record<string, unknown> } | undefined;
      try { const parsed = JSON.parse(await raw.clone().text()) as unknown; if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) message = parsed as typeof message; } catch { /* not JSON-RPC; let mcp-use answer */ }
      const method = typeof message?.method === 'string' ? message.method : '';
      const params = (message?.params ?? {}) as Record<string, unknown>;
      const modern = Boolean((params._meta as Record<string, unknown> | undefined)?.[ENVELOPE_KEY]);

      if (!modern && (method === 'resources/subscribe' || method === 'resources/unsubscribe')) {
        const uri = typeof params.uri === 'string' ? params.uri : '';
        const site = hub.siteOf(uri);
        if (!site) return rpcError(message?.id, -32602, `Only ${OVERVIEW_TEMPLATE} supports subscriptions here, for siteId ${hub.config.allowedProperties.join(' or ')}; got "${uri}".`);
        if (!session) return rpcError(message?.id, -32600, 'resources/subscribe needs an Mcp-Session-Id header. Re-run initialize: the response carries one; then open GET /mcp with it to receive notifications/resources/updated.');
        const uris = hub.legacy.get(session) ?? new Set<string>();
        if (method === 'resources/subscribe') uris.add(uri); else uris.delete(uri);
        if (uris.size) hub.legacy.set(session, uris); else hub.legacy.delete(session);
        hub.sync(site);
        return new Response(JSON.stringify({ jsonrpc: '2.0', id: message?.id ?? null, result: {} }), { status: 200, headers: { 'Content-Type': 'application/json', 'Mcp-Session-Id': session } });
      }

      const listenUris = modern && method === 'subscriptions/listen'
        ? [...new Set(((params.notifications as Record<string, unknown> | undefined)?.resourceSubscriptions as unknown[] | undefined ?? []).filter((uri): uri is string => typeof uri === 'string' && hub.siteOf(uri) !== null))]
        : [];

      await next();

      if (!modern && method === 'initialize' && context.res.ok && !context.res.headers.get('mcp-session-id')) {
        const headers = new Headers(context.res.headers); headers.set('Mcp-Session-Id', randomUUID());
        context.res = new Response(context.res.body, { status: context.res.status, statusText: context.res.statusText, headers });
      }
      if (listenUris.length && context.res.body && (context.res.headers.get('content-type') || '').includes('text/event-stream')) {
        hub.addModern(listenUris);
        let released = false;
        const release = () => { if (!released) { released = true; hub.dropModern(listenUris); } };
        const reader = context.res.body.getReader();
        const body = new ReadableStream<Uint8Array>({
          async pull(controller) {
            try { const { done, value } = await reader.read(); if (done) { release(); controller.close(); return; } controller.enqueue(value); } catch (error) { release(); controller.error(error); }
          },
          cancel(reason) { release(); return reader.cancel(reason); },
        });
        raw.signal?.addEventListener('abort', release, { once: true });
        context.res = new Response(body, { status: context.res.status, statusText: context.res.statusText, headers: context.res.headers });
      }
    });
  }
}
