import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, type Server } from 'node:http';
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer, GUIDE_URI } from '../src/server.js';
import { loadConfig, type PropertyId, type RuntimeConfig } from '../src/config.js';

function data(result: CallToolResult): Record<string, unknown> {
  const text = result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
  return (result.structuredContent ?? JSON.parse(text)) as Record<string, unknown>;
}

async function closeHttp(server: Server) { server.closeAllConnections(); await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }

async function stubBackend() {
  const scene = JSON.parse(await readFile(new URL('../../shared/scene.json', import.meta.url), 'utf8')) as { components: unknown[] };
  const timestamp = '2026-10-17T12:00:00Z';
  const names: Record<PropertyId, string> = { 'myer-plant': 'Myer Plant Room', 'bristol-pumps': 'Bristol Dock Pump House' };
  // Pre-addendum field names (address, jurisdiction, phase): the lenient PropertySchema must accept both spellings.
  const property = (id: PropertyId) => ({ id, name: names[id], address: 'Local test property', jurisdiction: 'Local demonstration', phase: 'Inspection', readiness: 0, componentCount: scene.components.length, openIssues: 0, updatedAt: timestamp });
  const properties = (['myer-plant', 'bristol-pumps'] as const).map(property);
  const stats = { verified: 0, pending: 0, issue: 0, unknown: 0, total: 0 };
  const agents = ['portfolio', 'agent-myer-plant', 'agent-bristol-pumps'].map(id => ({ id, name: id, role: 'Local worker', status: 'idle', identity: id, lastAction: `Private ${id} history`, tools: [] }));
  const state = { inspections: 0, unavailable: false, lastScope: '', token: undefined as string | undefined };
  const job = { id: 'job-test', propertyId: 'myer-plant', kind: 'inspection', status: 'completed', progress: 100, message: 'Local fixture worker finished.', result: { modelUsed: false, mode: 'local_deterministic' }, createdAt: timestamp, updatedAt: timestamp };
  const server = createServer(async (request, response) => {
    const url = new URL(request.url || '/', 'http://127.0.0.1');
    response.setHeader('Content-Type', 'application/json');
    if (state.token && request.headers.authorization !== `Bearer ${state.token}`) { response.statusCode = 401; response.end(JSON.stringify({ detail: 'A local API token is required.' })); return; }
    if (state.unavailable) { response.statusCode = 503; response.end(JSON.stringify({ detail: 'Local backend temporarily unavailable.' })); return; }
    let result: unknown;
    const match = url.pathname.match(/^\/api\/properties\/(myer-plant|bristol-pumps)\/(.+)$/);
    if (url.pathname === '/health') result = { status: 'ok', database: 'connected', mode: 'local' };
    else if (url.pathname === '/api/properties') result = properties;
    else if (url.pathname === '/api/integrations') result = [];
    else if (url.pathname === '/api/jobs/job-test') result = job;
    else if (url.pathname === '/api/jobs/job-bristol') result = { ...job, id: 'job-bristol', propertyId: 'bristol-pumps' };
    else if (match) {
      const id = match[1] as PropertyId;
      if (match[2] === 'workspace') result = { property: property(id), components: scene.components, requirements: [], agents, events: [], activeJob: null, stats };
      else if (match[2] === 'components') result = scene.components;
      else if (match[2] === 'inspections' && request.method === 'POST') {
        let body = ''; for await (const chunk of request) body += chunk;
        state.lastScope = (JSON.parse(body) as { scope: string }).scope;
        state.inspections += 1; result = { ...job, propertyId: id };
      } else if (match[2] === 'requirements' || match[2] === 'documents' || match[2] === 'events' || match[2] === 'memory') result = [];
      else if (match[2] === 'report') result = { property: property(id), generatedAt: timestamp, disclosure: 'Local test records, not physical certification.', stats, components: scene.components, requirements: [], documents: [], evidence: [] };
    }
    if (result === undefined) { response.statusCode = 404; result = { detail: 'Resource not found.' }; }
    response.end(JSON.stringify(result));
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); assert(address && typeof address !== 'string');
  return { server, state, url: `http://127.0.0.1:${address.port}` };
}

function config(backendUrl: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl, port: 0, host: '127.0.0.1', allowedProperties: ['myer-plant', 'bristol-pumps'], actor: 'operator', requestTimeoutMs: 1000, remoteBackend: false, hosted: false, ...patch };
}

test('configuration rejects external backends and invalid property scope', () => {
  assert.equal(loadConfig({}).backendUrl, 'http://127.0.0.1:8001');
  assert.deepEqual(loadConfig({ STEWARD_MCP_PROPERTY_IDS: 'myer-plant' }).allowedProperties, ['myer-plant']);
  assert.deepEqual(loadConfig({}).allowedProperties, ['myer-plant', 'bristol-pumps']);
  assert.equal(loadConfig({}).actor, 'operator');
  assert.equal(loadConfig({ STEWARD_MCP_ACTOR: 'warden:myer-plant' }).actor, 'warden:myer-plant');
  assert.equal(loadConfig({ STEWARD_MCP_ACTOR: 'counsel' }).actor, 'counsel');
  // An older deploy script still lists harbor-works: it is dropped with a warning, not fatal; alone it leaves nothing valid.
  assert.deepEqual(loadConfig({ STEWARD_MCP_PROPERTY_IDS: 'harbor-works,myer-plant,bristol-pumps' }).allowedProperties, ['myer-plant', 'bristol-pumps']);
  assert.throws(() => loadConfig({ STEWARD_MCP_PROPERTY_IDS: 'harbor-works' }), /subset/);
  assert.equal(loadConfig({}).waitDefaultSeconds, 50);
  assert.equal(loadConfig({ STEWARD_MCP_ALLOW_ACT_AS: 'true' }).allowActAs, true);
  assert.equal(loadConfig({ STEWARD_MCP_ALLOW_ACT_AS: 'true', PORT: '3000' }).allowActAs, false, 'never honoured on a hosted endpoint');
  assert.throws(() => loadConfig({ STEWARD_WAIT_DEFAULT_SECONDS: '400' }), /STEWARD_WAIT_DEFAULT_SECONDS/);
  assert.throws(() => loadConfig({ STEWARD_MCP_ACTOR: 'owner' }), /STEWARD_MCP_ACTOR/);
  assert.throws(() => loadConfig({ STEWARD_MCP_PROPERTY_IDS: 'harbor' }), /subset/, 'pre-addendum ids are gone');
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'https://example.com' }), /loopback/);
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'http://127.0.0.1:8001/api' }), /origin/);
  assert.throws(() => loadConfig({ STEWARD_MCP_PROPERTY_IDS: 'myer-plant,unknown' }), /subset/);
  assert.throws(() => loadConfig({ STEWARD_MCP_PORT: '-1' }), /integer/);
});

test('real mcp-use and official clients interoperate, preserve scope, reject bad input and propagate errors', async () => {
  const upstream = await stubBackend();
  const server = createStewardServer(config(upstream.url, { allowedProperties: ['myer-plant'] }));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const official = new Client({ name: 'steward-official-test', version: '0.1.0' }, { capabilities: {} });
  const mcpUse = new MCPClient({ mcpServers: { steward: { url: listener.url, oauth: false, detectMixedAuth: false } } });
  try {
    await official.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const connection = await mcpUse.connect('steward');
    const [officialTools, useTools] = await Promise.all([official.listTools(), connection.listTools()]);
    assert.equal(officialTools.tools.length, 54);
    assert.deepEqual(officialTools.tools.map(tool => tool.name).sort(), useTools.map(tool => tool.name).sort());
    for (const tool of officialTools.tools) {
      assert(tool.description && tool.description.length > 40);
      assert(tool.inputSchema && tool.outputSchema);
      const mutating = ['run_inspection', 'patrol', 'resolve', 'attest', 'subscribe', 'escalate', 'start_mission', 'focus_view', 'inspect_valves', 'request_document', 'start_scenario', 'assign_issue', 'decide', 'reconfigure_agent'];
      const leavesSystem = ['resolve', 'escalate', 'start_mission', 'request_document', 'start_scenario', 'decide'];
      assert.equal(tool.annotations?.openWorldHint, leavesSystem.includes(tool.name), tool.name);
      assert.equal(tool.annotations?.readOnlyHint, !mutating.includes(tool.name), tool.name);
    }
    const properties = data(await connection.callTool('list_properties', {})).properties as { id: string }[];
    assert.deepEqual(properties.map(property => property.id), ['myer-plant']);
    const context = data(await official.callTool({ name: 'get_property_context', arguments: { propertyId: 'myer-plant' } }));
    assert.equal((context.property as { id: string }).id, 'myer-plant');
    assert.deepEqual((context.agents as { id: string }[]).map(agent => agent.id), ['agent-myer-plant']);

    // Send a raw invalid request so input rejection is verified on the server, not only in client-side cached schemas.
    const invalidResponse = await fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28' }, body: JSON.stringify({ jsonrpc: '2.0', id: 100, method: 'tools/call', params: { name: 'get_property_context', arguments: { propertyId: 'bristol-pumps' } } }) });
    const invalidText = await invalidResponse.text();
    assert.match(invalidText, /invalid|myer-plant|scope|enum/i);
    assert(!invalidText.includes('Bristol Dock'));
    assert.equal(upstream.state.inspections, 0);

    const badScope = await official.callTool({ name: 'run_inspection', arguments: { propertyId: 'myer-plant', scope: 'does-not-exist' } });
    assert.equal(badScope.isError, true);
    assert.equal(data(badScope).code, 'INVALID_INSPECTION_SCOPE');
    assert.equal(upstream.state.inspections, 0, 'Invalid scope must never enqueue a backend job');

    // One library starts the local job; the other reads the same backend job and report.
    const started = data(await connection.callTool('run_inspection', { propertyId: 'myer-plant', scope: 'P-101' }));
    assert.equal(upstream.state.inspections, 1);
    assert.equal(upstream.state.lastScope, 'P-101');
    const current = data(await official.callTool({ name: 'get_job', arguments: { propertyId: 'myer-plant', jobId: (started.job as { id: string }).id } }));
    assert.equal((current.job as { status: string }).status, 'completed');
    const crossProperty = await official.callTool({ name: 'get_job', arguments: { propertyId: 'myer-plant', jobId: 'job-bristol' } });
    assert.equal(crossProperty.isError, true);
    assert.equal(data(crossProperty).code, 'PROPERTY_SCOPE');
    assert(!JSON.stringify(crossProperty).includes('Bristol Dock'));
    const report = data(await official.callTool({ name: 'export_report', arguments: { propertyId: 'myer-plant' } }));
    assert.equal(report.componentCount, 24);
    assert.match(String(report.jsonUrl), /\/api\/properties\/myer-plant\/report\?format=json$/);
    const resource = await official.readResource({ uri: GUIDE_URI });
    assert(resource.contents.some(item => 'text' in item && item.text.includes('BACKEND_UNAVAILABLE')));
    const prompt = await official.getPrompt({ name: 'inspect-property', arguments: { propertyId: 'myer-plant', scope: 'pump-01' } });
    assert.equal(prompt.messages[0]?.role, 'user');

    upstream.state.unavailable = true;
    const failed = await official.callTool({ name: 'list_properties', arguments: {} });
    assert.equal(failed.isError, true);
    assert.equal(data(failed).httpStatus, 503);
    assert.equal(data(failed).retryable, true);
    upstream.state.unavailable = false;
    assert.equal((data(await official.callTool({ name: 'list_properties', arguments: {} })).properties as unknown[]).length, 1);

    const unknown = await official.callTool({ name: 'inspect_component', arguments: { propertyId: 'myer-plant', componentId: 'missing-asset' } });
    assert.equal(unknown.isError, true);
    assert.equal(data(unknown).httpStatus, 404);
  } finally {
    await Promise.allSettled([official.close(), mcpUse.close()]);
    await server.close(); await closeHttp(upstream.server);
  }
});

test('optional MCP bearer auth is separate from backend auth and refuses untrusted browser origins', async () => {
  const upstream = await stubBackend(); upstream.state.token = 'backend-test-token';
  const server = createStewardServer(config(upstream.url, { clientToken: 'mcp-test-token', backendToken: 'backend-test-token' }));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'steward-auth-test', version: '0.1.0' }, { capabilities: {} });
  try {
    const unauthorized = await fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }) });
    assert.equal(unauthorized.status, 401);
    await client.connect(new StreamableHTTPClientTransport(new URL(listener.url), { requestInit: { headers: { Authorization: 'Bearer mcp-test-token' } } }));
    const properties = data(await client.callTool({ name: 'list_properties', arguments: {} }));
    assert.equal((properties.properties as unknown[]).length, 2);
    const badOrigin = await fetch(listener.url, { method: 'POST', headers: { Origin: 'https://untrusted.example', Authorization: 'Bearer mcp-test-token', 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }) });
    assert.equal(badOrigin.status, 403);
  } finally {
    await client.close(); await server.close(); await closeHttp(upstream.server);
  }
});
