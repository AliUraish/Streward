import { MCPServer } from 'mcp-use';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';
import { z } from 'zod';
import { inputRequired, acceptedContent, inputResponse } from '@modelcontextprotocol/server';

const server = new MCPServer({ name: 'probe', version: '0.0.1', host: '127.0.0.1', port: 0, basePath: '/mcp', legacy: 'stateless', logging: { enabled: false } } as never);
server.tool({ name: 'slow', description: 'slow tool', inputSchema: z.object({}), annotations: { readOnlyHint: true } }, async (_i, ctx) => {
  const sent: boolean[] = [];
  for (let i = 0; i < 3; i++) { await new Promise(r => setTimeout(r, 150)); sent.push(await ctx.reportProgress(i + 1, 3, `tick ${i}`)); }
  return { content: [{ type: 'text', text: JSON.stringify({ sent, canElicit: ctx.client.can('elicitation'), caps: ctx.client.capabilities(), info: ctx.client.info(), views: ctx.client.supportsViews() }) }] };
});
server.tool({ name: 'ask', description: 'ask tool', inputSchema: z.object({ q: z.string() }) }, async ({ q }, ctx) => {
  const resp = inputResponse(ctx.inputResponses as never, 'choice');
  if (resp.kind === 'elicit') return { content: [{ type: 'text', text: JSON.stringify({ got: resp }) }] };
  if (!ctx.client.can('elicitation')) return { content: [{ type: 'text', text: JSON.stringify({ noElicit: true }) }] };
  return inputRequired({ inputRequests: { choice: inputRequired.elicit({ message: q, requestedSchema: { type: 'object', properties: { option: { type: 'string', enum: ['a', 'b'] } }, required: ['option'] } as never }) } }) as never;
});
server.resource({ name: 'r', uri: 'steward://x', mimeType: 'application/json', description: 'x' }, async uri => ({ contents: [{ uri: uri.href, mimeType: 'application/json', text: '{}' }] }));
server.resourceTemplate({ name: 'ov', uriTemplate: 'steward://sites/{siteId}/overview', mimeType: 'application/json', description: 'ov' }, async (uri) => ({ contents: [{ uri: uri.href, mimeType: 'application/json', text: '{"a":1}' }] }));
server.resource({ name: 'ui', uri: 'ui://steward/factory.html', mimeType: 'text/html;profile=mcp-app', description: 'ui', _meta: { ui: { csp: { resourceDomains: ['https://cdn.jsdelivr.net'] } } } } as never, async uri => ({ contents: [{ uri: uri.href, mimeType: 'text/html;profile=mcp-app', text: '<html></html>' }] }));
server.tool({ name: 'show', description: 'show', inputSchema: z.object({}), _meta: { ui: { resourceUri: 'ui://steward/factory.html' }, 'ui/resourceUri': 'ui://steward/factory.html' } }, async () => ({ content: [{ type: 'text', text: 'shown' }] }));

const listener = await server.listen(0, { host: '127.0.0.1' });
console.log('url', listener.url);
// 1. legacy official client
const official = new Client({ name: 'legacy-probe', version: '1' }, { capabilities: { elicitation: { form: {} } } });
official.setRequestHandler?.('elicitation/create' as never, (async () => ({ action: 'accept', content: { option: 'b' } })) as never);
await official.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
console.log('official negotiated', (official as any).getNegotiatedProtocolVersion?.() ?? (official as any)._negotiatedProtocolVersion, 'serverCaps', JSON.stringify(official.getServerCapabilities()));
const progressSeen: unknown[] = [];
const r1 = await official.callTool({ name: 'slow', arguments: {} }, { onprogress: (p: unknown) => progressSeen.push(p) } as never);
console.log('official slow', JSON.stringify(r1.content), 'progress', JSON.stringify(progressSeen));
try { const r2 = await official.callTool({ name: 'ask', arguments: { q: 'pick' } }); console.log('official ask', JSON.stringify(r2)); } catch (e) { console.log('official ask err', (e as Error).message); }
try { await official.subscribeResource({ uri: 'steward://sites/myer-plant/overview' }); console.log('official subscribe ok'); } catch (e) { console.log('official subscribe err', (e as Error).message); }
const tools = await official.listTools();
console.log('show tool meta', JSON.stringify(tools.tools.find(t => t.name === 'show')?._meta));
const res = await official.listResources();
console.log('resources', JSON.stringify(res.resources));
const ui = await official.readResource({ uri: 'ui://steward/factory.html' });
console.log('ui read', JSON.stringify(ui).slice(0, 400));
await official.close();
// 2. modern mcp-use client
const progress2: unknown[] = [];
const notes: unknown[] = [];
const mc = new MCPClient({ clientInfo: { name: 'modern-probe', version: '1' }, mcpServers: { s: { url: listener.url, oauth: false, detectMixedAuth: false, onElicitation: async (p: unknown) => { notes.push(['elicit', p]); return { action: 'accept', content: { option: 'a' } }; }, onNotification: (n: unknown) => { notes.push(['note', n]); } } } } as never);
const conn = await mc.connect('s');
console.log('modern negotiated', (conn as any).negotiatedProtocolVersion);
const m1 = await conn.callTool('slow', {}, { onprogress: (p: unknown) => progress2.push(p) } as never);
console.log('modern slow', JSON.stringify(m1.content), 'progress', JSON.stringify(progress2));
const m2 = await conn.callTool('ask', { q: 'pick one' });
console.log('modern ask', JSON.stringify(m2.content));
try { const sub = await conn.subscribeToResource('steward://sites/myer-plant/overview'); console.log('modern subscribe', JSON.stringify(sub)); } catch (e) { console.log('modern subscribe err', (e as Error).message); }
await new Promise(r => setTimeout(r, 300));
await server.notifyResourceUpdated('steward://sites/myer-plant/overview');
await new Promise(r => setTimeout(r, 500));
console.log('notes', JSON.stringify(notes).slice(0, 1500));
await mc.close();
await server.close();
process.exit(0);
