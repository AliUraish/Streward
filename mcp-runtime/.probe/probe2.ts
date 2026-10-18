import { MCPServer } from 'mcp-use';
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';
import { z } from 'zod';

const server = new MCPServer({ name: 'probe', version: '0.0.1', host: '127.0.0.1', port: 0, basePath: '/mcp', legacy: 'stateless', logging: { enabled: false } } as never);
const seen: string[] = [];
server.app.use('/mcp', async (c, next) => {
  if (c.req.method === 'POST') { const body = await c.req.raw.clone().text(); seen.push(body.slice(0, 300)); }
  await next();
  if (c.req.method === 'POST' && seen.at(-1)?.includes('subscriptions/listen')) {
    const res = c.res; const reader = res.body!.getReader();
    const stream = new ReadableStream({ async pull(ctrl) { const { done, value } = await reader.read(); if (done) { console.log('listen stream ended'); ctrl.close(); return; } ctrl.enqueue(value); }, cancel(reason) { console.log('listen stream cancelled', String(reason)); return reader.cancel(reason); } });
    c.res = new Response(stream, { status: res.status, headers: res.headers });
  }
});
server.tool({ name: 'noop', description: 'noop tool', inputSchema: z.object({}) }, async () => ({ content: [{ type: 'text', text: 'ok' }] }));
server.resourceTemplate({ name: 'ov', uriTemplate: 'steward://sites/{siteId}/overview', mimeType: 'application/json', description: 'ov' }, async (uri) => ({ contents: [{ uri: uri.href, mimeType: 'application/json', text: '{"a":1}' }] }));
const listener = await server.listen(0, { host: '127.0.0.1' });
const client = new Client({ name: 'modern-official', version: '1' }, { capabilities: {}, versionNegotiation: { mode: 'auto' } } as never);
const got: unknown[] = [];
client.setNotificationHandler('notifications/resources/updated' as never, ((n: unknown) => { got.push(n); }) as never);
await client.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
console.log('negotiated', (client as any).getNegotiatedProtocolVersion?.());
const sub = await client.listen({ resourceSubscriptions: ['steward://sites/myer-plant/overview'] } as never);
console.log('listening');
await new Promise(r => setTimeout(r, 200));
await server.notifyResourceUpdated('steward://sites/myer-plant/overview');
await server.notifyResourceUpdated('steward://sites/bristol-pumps/overview');
await new Promise(r => setTimeout(r, 300));
console.log('got', JSON.stringify(got));
await sub.close();
await new Promise(r => setTimeout(r, 300));
console.log('seen', seen.map(s => s.slice(0, 200)).join('\n'));
// legacy GET probe
const g = await fetch(listener.url, { method: 'GET', headers: { Accept: 'text/event-stream' } });
console.log('legacy GET', g.status);
const init = await fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: { elicitation: {} }, clientInfo: { name: 'x', version: '1' } } }) });
console.log('legacy init', init.status, init.headers.get('content-type'), init.headers.get('mcp-session-id'), (await init.text()).slice(0, 300));
await client.close(); await server.close(); process.exit(0);
