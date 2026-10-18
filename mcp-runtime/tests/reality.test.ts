import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { createPublicKey, verify } from 'node:crypto';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer, AGENTS_URI, GUIDE_URI, SCHEMA_URI } from '../src/server.js';
import { loadConfig, backendUrl, type RuntimeConfig } from '../src/config.js';
import { loadAnalytics, noopAnalytics, type Analytics, type ToolCallEvent } from '../src/analytics.js';
import { fakeRealityBackend } from './fake-reality.js';
import { parseErrorBody } from '../src/upstream.js';
// The eval runner is plain ESM JavaScript shared with `npm run demo:mcp`; the test replays the same workflow against the fixture.
// @ts-expect-error untyped .mjs module
import { runWorkflow, checkExpectations, substitute, getPath, resolveSuite, evalSteps } from '../../evals/run.mjs';

function data(result: CallToolResult): Record<string, unknown> {
  const text = result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
  return (result.structuredContent ?? JSON.parse(text)) as Record<string, unknown>;
}
function config(url: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl: url, port: 0, host: '127.0.0.1', allowedProperties: ['myer-plant', 'bristol-pumps'], actor: 'operator', requestTimeoutMs: 2000, remoteBackend: false, hosted: false, ...patch };
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value as object).sort().map(key => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

test('config: STEWARD_ALLOW_REMOTE_BACKEND permits only a non-loopback https origin, default stays loopback-only', () => {
  assert.equal(loadConfig({}).remoteBackend, false);
  assert.equal(loadConfig({}).host, '127.0.0.1');
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'https://steward.example.com' }), /STEWARD_ALLOW_REMOTE_BACKEND/);
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'https://steward.example.com', STEWARD_ALLOW_REMOTE_BACKEND: 'false' }), /STEWARD_ALLOW_REMOTE_BACKEND/);
  const remote = loadConfig({ STEWARD_BACKEND_URL: 'https://steward-tunnel.example.com', STEWARD_ALLOW_REMOTE_BACKEND: 'true' });
  assert.equal(remote.backendUrl, 'https://steward-tunnel.example.com');
  assert.equal(remote.remoteBackend, true);
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'http://steward.example.com', STEWARD_ALLOW_REMOTE_BACKEND: 'true' }), /https/);
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'https://user:pw@steward.example.com', STEWARD_ALLOW_REMOTE_BACKEND: 'true' }), /credentials/);
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'https://steward.example.com/api', STEWARD_ALLOW_REMOTE_BACKEND: 'true' }), /origin/);
  assert.throws(() => loadConfig({ STEWARD_BACKEND_URL: 'https://127.0.0.1:8001', STEWARD_ALLOW_REMOTE_BACKEND: 'true' }), /loopback/);
  assert.equal(loadConfig({ STEWARD_BACKEND_URL: 'http://127.0.0.1:8012', STEWARD_ALLOW_REMOTE_BACKEND: 'true' }).remoteBackend, false, 'flag does not change loopback handling');
  assert.equal(backendUrl('http://localhost:8001', false).remote, false);
  assert.equal(loadConfig({ STEWARD_MCP_HOST: '0.0.0.0' }).host, '0.0.0.0');
  assert.equal(loadConfig({}).hosted, false);
  const hosted = loadConfig({ PORT: '3000' });
  assert.equal(hosted.hosted, true); assert.equal(hosted.port, 3000); assert.equal(hosted.host, '0.0.0.0', 'PORT set: bind all interfaces for the platform gateway');
  assert.equal(loadConfig({ PORT: '3000', STEWARD_MCP_PORT: '8013' }).port, 8013);
  assert.equal(loadConfig({ PORT: '3000', STEWARD_MCP_HOST: '127.0.0.1' }).host, '127.0.0.1', 'explicit host override wins');
  assert.equal(remote.host, '127.0.0.1', 'a remote backend alone does not change the bind address');
  assert.throws(() => loadConfig({ STEWARD_MCP_HOST: 'bad host' }), /STEWARD_MCP_HOST/);
});

test('upstream error bodies: flat {detail, code, recovery}, FastAPI-nested, and 422 validation arrays', () => {
  assert.deepEqual(parseErrorBody({ detail: 'Unsupported attribute colour.', code: 'UNSUPPORTED_ATTRIBUTE', recovery: 'Read specs.' }), { detail: 'Unsupported attribute colour.', code: 'UNSUPPORTED_ATTRIBUTE', recovery: 'Read specs.' });
  assert.deepEqual(parseErrorBody({ detail: { detail: 'Not found.', code: 'NOT_FOUND', recovery: 'get_changes' } }), { detail: 'Not found.', code: 'NOT_FOUND', recovery: 'get_changes' });
  const validation = parseErrorBody({ detail: [{ type: 'greater_than', loc: ['body', 'maxAgeHours'], msg: 'Input should be greater than 0', input: 0 }] });
  assert.equal(validation.code, 'INVALID_REQUEST'); assert.match(validation.detail!, /maxAgeHours: Input should be greater than 0/);
  assert.deepEqual(parseErrorBody('garbage'), {});
});

test('analytics: no-op without a key; identity instrument; never throws', async () => {
  assert.equal((await loadAnalytics({})).provider, 'none');
  noopAnalytics.toolCall({ tool: 'x', requester: 'y', ok: true, durationMs: 1, mutates: false });
  const handler = async () => ({ content: [] });
  assert.equal(noopAnalytics.instrument('x', 'd', handler), handler);
  await noopAnalytics.close();
});

test('analytics: Armature v2 SDK records tool_call with client identity and session_init on legacy initialize (injected emitter, no network)', async () => {
  const batches: { events: { kind: string; ok: boolean; metadata: Record<string, unknown>; session_id_hint: string | null }[] }[] = [];
  const analytics = await loadAnalytics({ ARMATURE_API_KEY: 'ami_test_key' }, 'steward-test', { emit: batch => { batches.push(batch as typeof batches[number]); }, delivery: 'await' });
  assert.equal(analytics.provider, 'armature');
  const upstream = await fakeRealityBackend();
  const server = createStewardServer({ config: config(upstream.url), analytics });
  analytics.attach(server);
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const named = new MCPClient({ clientInfo: { name: 'armature-probe', version: '2.0.0' }, mcpServers: { steward: { url: listener.url, oauth: false, detectMixedAuth: false } } });
  try {
    // Legacy-era initialize (no _meta envelope): wrapMcpHandler mints an Mcp-Session-Id and records session_init.
    const init = await fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'legacy-cursor', version: '0.1' } } }) });
    assert.equal(init.status, 200);
    const minted = init.headers.get('mcp-session-id');
    assert(minted && minted.includes('legacy-cursor'), `Mcp-Session-Id minted for legacy client, got ${minted}`);
    // Modern client: tool_call events carry the client name and Steward metadata.
    const connection = await named.connect('steward');
    const ok = data(await connection.callTool('resolve', { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'commissioning_certificate' }) as CallToolResult);
    assert.equal(ok.status, 'known');
    const failed = await connection.callTool('check', { attestationId: 'att-missing' }) as CallToolResult;
    assert.equal(failed.isError, true);
    await analytics.close();
    const events = batches.flatMap(batch => batch.events);
    const inits = events.filter(event => event.kind === 'session_init');
    assert(inits.length >= 1, 'session_init recorded');
    const calls = events.filter(event => event.kind === 'tool_call');
    const resolveEvent = calls.find(event => event.metadata.tool_name === 'resolve');
    assert(resolveEvent, 'tool_call for resolve recorded');
    assert.equal(resolveEvent.ok, true);
    assert.equal(resolveEvent.metadata.client_name, 'armature-probe');
    assert.equal(resolveEvent.metadata.steward_requester, 'armature-probe');
    assert.equal(resolveEvent.metadata.steward_site, 'myer-plant');
    assert.equal(resolveEvent.metadata.steward_server, 'steward-test');
    assert.equal(resolveEvent.metadata.protocol_era, 'modern');
    const checkEvent = calls.find(event => event.metadata.tool_name === 'check');
    assert(checkEvent, 'tool_call for check recorded');
    assert.equal(checkEvent.ok, false, 'isError results are recorded as failed calls');
    assert.equal((await server.app.request('/health')).status, 200, 'non-/mcp routes are untouched by the wrapper');
  } finally { await named.close(); await server.close(); await upstream.close(); }
});

test('reality tools against a fake upstream: resolve/attest/check, requester, error mapping, resources, prompt', async () => {
  const upstream = await fakeRealityBackend();
  const events: ToolCallEvent[] = [];
  const analytics: Analytics = { provider: 'armature', toolCall: event => { events.push(event); }, instrument: (_n, _d, handler) => handler, attach() { /* noop */ }, close: async () => { /* noop */ } };
  const server = createStewardServer({ config: config(upstream.url), analytics });
  const listener = await server.listen(0, { host: '127.0.0.1' });
  // The official SDK client (stateless, no per-request _meta envelope) is anonymous to the server;
  // the mcp-use client sends io.modelcontextprotocol/clientInfo on every request, so its name becomes `requester`.
  const client = new Client({ name: 'official-anonymous', version: '1.0.0' }, { capabilities: {} });
  const named = new MCPClient({ clientInfo: { name: 'restart-planner', version: '1.0.0' }, mcpServers: { steward: { url: listener.url, oauth: false, detectMixedAuth: false } } });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const namedConnection = await named.connect('steward');
    const tools = await client.listTools();
    const names = tools.tools.map(tool => tool.name);
    for (const name of ['resolve', 'attest', 'check', 'get_changes', 'subscribe', 'get_receipt', 'escalate', 'query_clearance', 'patrol', 'list_sites', 'start_mission', 'get_mission', 'list_missions', 'list_agents', 'get_transcript', 'get_issues', 'list_evals', 'get_eval']) assert(names.includes(name), name);
    const resolveTool = tools.tools.find(tool => tool.name === 'resolve')!;
    assert.equal(resolveTool.annotations?.readOnlyHint, false);
    assert.match(resolveTool.description!, /budget/i);
    assert.match(resolveTool.description!, /dispatch/i);
    assert.deepEqual((resolveTool.inputSchema as unknown as { properties: { siteId: { enum: string[] } } }).properties.siteId.enum, ['myer-plant', 'bristol-pumps']);

    // list_sites
    const sites = data(await client.callTool({ name: 'list_sites', arguments: {} })).sites as { siteId: string; name: string }[];
    assert.deepEqual(sites.map(site => site.siteId), ['myer-plant', 'bristol-pumps']);
    assert.equal(sites.find(site => site.siteId === 'myer-plant')!.name, 'Myer Plant Room');

    // known
    const certificate = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'commissioning_certificate' } }));
    assert.equal(certificate.status, 'known');
    assert.equal(typeof certificate.attestationId, 'string');
    assert.equal(upstream.state.lastRequester, 'mcp-client', 'anonymous session falls back to mcp-client');
    const viaNamed = data(await namedConnection.callTool('resolve', { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'commissioning_certificate' }) as CallToolResult);
    assert.equal(viaNamed.status, 'known');
    assert.equal(upstream.state.lastRequester, 'restart-planner', 'requester is the MCP client name when the session exposes it');
    const valve = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'V-501', attribute: 'position' } }));
    assert.equal(valve.status, 'known'); assert.equal(valve.value, 'open');

    // unknown without budget: no work item
    const dry = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar' } }));
    assert.equal(dry.status, 'unknown'); assert.equal(dry.workItemId, undefined); assert.match(String(dry.nextStep), /budget/);
    assert.equal(upstream.state.workItems.size, 0);
    assert.equal(upstream.state.lastResolveBody?.budget, undefined, 'omitted budget is not sent as 0');

    // unknown with budget: dispatch
    const dispatched = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', budget: 5 } }));
    assert.equal(dispatched.status, 'unknown');
    assert.equal(typeof dispatched.workItemId, 'string');
    assert.match(String(dispatched.reference), /^MY-P101-PRESSURE_BAR-\d{4}$/);
    assert.equal(dispatched.dispatchedVia, 'local');
    assert.equal(upstream.state.lastResolveBody?.budget, 5);
    const workItemId = dispatched.workItemId as string;
    const again = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', budget: 5 } }));
    assert.equal(again.workItemId, workItemId, 'open work item is reused');

    // attest wrong tag -> rejected with direction, nothing written
    const factsBefore = upstream.state.facts.length;
    const wrong = data(await client.callTool({ name: 'attest', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', value: 2.4, unit: 'bar', source: { kind: 'human', ref: 'tech-1' }, statedTag: 'P-102', workItemId } }));
    assert.equal(wrong.verdict, 'rejected');
    assert.match((wrong.reasons as string[]).join(' '), /P-102/);
    assert.match((wrong.reasons as string[]).join(' '), /m (east|west|north|south) of/);
    assert.equal(upstream.state.facts.length, factsBefore);
    // out of spec -> needs_clarification
    const high = data(await client.callTool({ name: 'attest', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', value: 9.8, unit: 'bar', source: { kind: 'human', ref: 'tech-1' }, statedTag: 'P-101', workItemId } }));
    assert.equal(high.verdict, 'needs_clarification');
    assert.match((high.reasons as string[]).join(' '), /spec/);
    // right -> accepted, signed
    const right = data(await client.callTool({ name: 'attest', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', value: 2.4, unit: 'bar', source: { kind: 'human', ref: 'tech-1' }, statedTag: 'P-101', workItemId } }));
    assert.equal(right.verdict, 'accepted');
    assert.equal(typeof right.attestationId, 'string'); assert.equal(typeof right.factId, 'string');
    assert.equal(upstream.state.facts.length, factsBefore + 1);

    // receipt
    const receipt = data(await client.callTool({ name: 'get_receipt', arguments: { workItemId } }));
    assert.equal(receipt.state, 'resolved');
    assert.equal(receipt.attestationId, right.attestationId);
    assert.equal((receipt.receipt as { tokensWhileWaiting: number }).tokensWhileWaiting, 0);
    assert.equal((receipt.verdicts as unknown[]).length, 3);

    // check: valid, and the signature verifies offline with node:crypto
    const checked = data(await client.callTool({ name: 'check', arguments: { attestationId: right.attestationId as string } }));
    assert.equal(checked.valid, true); assert.equal(checked.verdict, 'accepted'); assert.equal(checked.value, 2.4);
    const { signature, valid: _valid, ...payload } = checked as Record<string, unknown> & { signature: string; valid: boolean };
    const publicKey = createPublicKey({ key: Buffer.from(String(checked.publicKey), 'base64'), type: 'spki', format: 'der' });
    assert.equal(verify(null, Buffer.from(canonical(payload)), publicKey, Buffer.from(signature, 'base64')), true, 'offline Ed25519 verification');
    assert.equal(verify(null, Buffer.from(canonical({ ...payload, value: 9.8 })), publicKey, Buffer.from(signature, 'base64')), false, 'tampered payload fails');

    // now known
    const known = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar' } }));
    assert.equal(known.status, 'known'); assert.equal(known.attestationId, right.attestationId);
    await delay(20);
    const stale = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', maxAgeHours: 1e-9 } }));
    assert.equal(stale.status, 'stale'); assert.equal(stale.value, 2.4); assert.equal(stale.workItemId, undefined);

    // changes, subscribe, escalate, clearance, patrol
    const changes = data(await client.callTool({ name: 'get_changes', arguments: { siteId: 'myer-plant', since: 0 } }));
    const types = new Set((changes.changes as { type: string }[]).map(change => change.type));
    assert(types.has('fact') && types.has('work_item') && types.has('attestation') && types.has('dispatch'));
    assert.deepEqual(changes.waiting, []);
    const later = data(await client.callTool({ name: 'get_changes', arguments: { siteId: 'myer-plant', since: changes.version as number } }));
    assert.deepEqual(later.changes, []);
    const bristolChanges = data(await client.callTool({ name: 'get_changes', arguments: { siteId: 'bristol-pumps', since: 0 } }));
    assert(!(bristolChanges.changes as { assetTag?: string; summary: string }[]).some(change => change.summary.includes('pressure_bar')), 'changes are per site (bristol-pumps has only seeded identity facts)');
    const subscription = data(await namedConnection.callTool('subscribe', { siteId: 'myer-plant', callbackUrl: 'http://127.0.0.1:9/hook' }) as CallToolResult);
    assert.equal(subscription.requester, 'restart-planner'); assert.equal(subscription.propertyId, 'myer-plant');
    const badCallback = await client.callTool({ name: 'subscribe', arguments: { siteId: 'myer-plant', callbackUrl: 'ftp://example/hook' } }).catch(error => error as Error);
    assert(badCallback instanceof Error || (badCallback as CallToolResult).isError, 'non-http callback is rejected before reaching the backend');
    const stale2 = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', maxAgeHours: 1e-9, budget: 1 } }));
    assert.equal(stale2.status, 'stale'); assert.equal(typeof stale2.workItemId, 'string');
    const escalated = data(await client.callTool({ name: 'escalate', arguments: { workItemId: stale2.workItemId as string, level: 2, note: 'deadline near' } }));
    assert.equal(escalated.state, 'escalated');
    assert.deepEqual(upstream.state.lastEscalate, { level: 2, note: 'deadline near' });
    const clearance = data(await client.callTool({ name: 'query_clearance', arguments: { siteId: 'myer-plant', from: [-50, -50], to: [-49, -50], widthM: 0.5 } }));
    assert.equal(clearance.clear, true); assert.equal(clearance.widthM, 0.5);
    const patrol = data(await client.callTool({ name: 'patrol', arguments: { siteId: 'myer-plant', scope: 'P-101' } }));
    assert.equal((patrol.job as { kind: string }).kind, 'patrol'); assert.match(String(patrol.nextStep), /get_changes/);
    const badPatrol = await client.callTool({ name: 'patrol', arguments: { siteId: 'myer-plant', scope: 'nope' } });
    assert.equal(badPatrol.isError, true); assert.equal(data(badPatrol).code, 'INVALID_INSPECTION_SCOPE'); assert.equal(upstream.state.patrols, 1);

    // error mapping: backend {detail, code, recovery} is passed through, flat and FastAPI-nested
    const unsupported = await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'colour' } });
    assert.equal(unsupported.isError, true);
    const unsupportedError = data(unsupported);
    assert.equal(unsupportedError.code, 'UNSUPPORTED_ATTRIBUTE'); assert.equal(unsupportedError.httpStatus, 400);
    assert.match(String(unsupportedError.message), /pressure_bar/); assert.match(String(unsupportedError.recovery), /specs/);
    upstream.state.errorStyle = 'nested';
    const nested = data(await client.callTool({ name: 'get_receipt', arguments: { workItemId: 'wi-missing' } }));
    assert.equal(nested.code, 'NOT_FOUND'); assert.equal(nested.httpStatus, 404); assert.match(String(nested.recovery), /get_changes/);
    upstream.state.errorStyle = 'flat';
    const missingAttestation = data(await client.callTool({ name: 'check', arguments: { attestationId: 'att-missing' } }));
    assert.equal(missingAttestation.code, 'NOT_FOUND');
    upstream.state.unavailable = true;
    const down = data(await client.callTool({ name: 'resolve', arguments: { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar' } }));
    assert.equal(down.httpStatus, 503); assert.equal(down.retryable, true);
    upstream.state.unavailable = false;

    // input validation on the server (raw request, no client-side schema): bad siteId, bad tag, bad level
    const raw = async (name: string, args: Record<string, unknown>) => (await fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }) })).text();
    assert.match(await raw('resolve', { siteId: 'atlantis', assetTag: 'P-101', attribute: 'pressure_bar' }), /invalid|enum|myer-plant/i);
    assert.match(await raw('resolve', { siteId: 'harbor', assetTag: 'P-101', attribute: 'pressure_bar' }), /invalid|enum|myer-plant/i, 'the pre-addendum id is rejected');
    assert.match(await raw('resolve', { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar' }), /invalid|enum|myer-plant/i, 'the retired addendum-2 site is rejected');
    assert.match(await raw('resolve', { siteId: 'myer-plant', assetTag: 'pump 101', attribute: 'pressure_bar' }), /invalid|regex|pattern/i);
    assert.match(await raw('escalate', { workItemId: 'wi-1', level: 9 }), /invalid|literal|union/i);
    assert.match(await raw('resolve', { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', budget: -1 }), /invalid|>=|small|minimum/i);
    assert.match(await raw('resolve', { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', maxAgeHours: 0 }), /invalid|>0|positive|small/i);
    assert.match(await raw('attest', { siteId: 'myer-plant', assetTag: 'P-101', attribute: 'pressure_bar', value: 2.4, source: { kind: 'telepathy', ref: 'x' } }), /invalid|enum|option/i);

    // resources and prompt
    const guide = await client.readResource({ uri: GUIDE_URI });
    const guideText = guide.contents.map(item => ('text' in item ? item.text : '')).join('');
    for (const needle of ['known', 'stale', 'unknown', 'conflict', 'budget', 'zero tokens', 'subscribe', 'get_changes', 'offline', 'myer-plant', 'bristol-pumps', "Owner's agent", 'Operations Director', 'Plant Manager', 'Site Engineer', 'Compliance Officer', 'Field Technician', 'Steward Dispatch Line', 'AUTHORITY_DENIED', 'start_mission', 'get_mission', 'every 5 s', 'get_transcript', 'X-Steward-Actor', 'wait_for', 'still_waiting', 'decide', 'show_factory', 'focus_view', 'get_overview', 'steward://sites/{siteId}/overview', 'eye_look', 'eye_go_to', 'eye_move', 'eye_mark', 'request_fix', 'list_regulations', 'get_metrics', 'list_conversations', 'not legal advice']) assert(guideText.includes(needle), `guide mentions ${needle}`);
    for (const retired of ['Atlas', 'Warden', 'Counsel', 'Runner']) assert(!guideText.includes(retired), `guide no longer names ${retired}`);
    for (const stale of ['cedar', 'juniper', ' harbor ', 'residen']) assert(!guideText.includes(stale), `guide no longer mentions ${stale}`);
    const schema = await client.readResource({ uri: SCHEMA_URI });
    const schemaText = schema.contents.map(item => ('text' in item ? item.text : '')).join('');
    for (const needle of ['interface Fact', 'interface Attestation', 'interface WorkItem', 'interface Change', 'interface ResolveResult', 'interface AttestResult', 'interface Subscription', 'interface ClearanceResult', 'interface ContextMin', 'interface Receipt', 'interface Dispatch', 'interface Check', 'interface Source', 'interface Mission', 'interface MissionStep', 'interface AgentInfo', 'interface TranscriptEntry', 'interface Issue', 'interface EvalRun', 'type SiteId =']) assert(schemaText.includes(needle), needle);
    const sharedTypes = await readFile(new URL('../../shared/types.ts', import.meta.url), 'utf8');
    for (const line of schemaText.trim().split('\n')) assert(sharedTypes.includes(line), `schema line is verbatim from shared/types.ts: ${line.slice(0, 60)}`);
    const resources = await client.listResources();
    assert.deepEqual(resources.resources.map(resource => resource.uri).sort(), [AGENTS_URI, GUIDE_URI, SCHEMA_URI, 'ui://views/steward-factory.html'].sort());
    const templates = await client.listResourceTemplates();
    assert.deepEqual(templates.resourceTemplates.map(t => t.uriTemplate).sort(), ['steward://sites/{siteId}/context.min', 'steward://sites/{siteId}/environment', 'steward://sites/{siteId}/overview', 'steward://sites/{siteId}/specs']);
    const contextMin = JSON.parse((await client.readResource({ uri: 'steward://sites/myer-plant/context.min' })).contents.map(item => ('text' in item ? item.text : '')).join('')) as { propertyId: string; blockers: unknown[]; sensors: unknown[] };
    assert.equal(contextMin.propertyId, 'myer-plant'); assert.equal(contextMin.blockers.length, 1); assert.equal(contextMin.sensors.length, 2);
    const specs = JSON.parse((await client.readResource({ uri: 'steward://sites/myer-plant/specs' })).contents.map(item => ('text' in item ? item.text : '')).join('')) as Record<string, Record<string, unknown>>;
    assert(specs.pump && 'pressure_bar' in specs.pump);
    const badSite = await client.readResource({ uri: 'steward://sites/atlantis/specs' }).catch(error => error as Error);
    assert(badSite instanceof Error); assert.match(badSite.message, /PROPERTY_SCOPE|list_sites/);
    const prompt = await client.getPrompt({ name: 'prove-before-signing', arguments: { siteId: 'myer-plant', task: 'Clear the Myer Plant Room for restart. Budget $5.' } });
    const promptText = (prompt.messages[0]!.content as { text: string }).text;
    assert.match(promptText, /resolve/); assert.match(promptText, /never poll/i); assert.match(promptText, /attestationId/);

    // analytics hook saw every call with the client name
    assert(events.length > 10);
    assert(events.some(event => event.requester === 'restart-planner') && events.some(event => event.requester === 'mcp-client'));
    assert(events.some(event => event.tool === 'resolve' && event.ok && event.siteId === 'myer-plant' && event.mutates));
    assert(events.some(event => event.tool === 'check' && !event.ok && event.code === 'NOT_FOUND'));
  } finally {
    await Promise.allSettled([client.close(), named.close()]); await server.close(); await upstream.close();
  }
});

test('site scope: a restricted endpoint refuses other sites in tools, templates, work items and attestations', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url, { allowedProperties: ['myer-plant'] }));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'scoped', version: '1' }, { capabilities: {} });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const sites = data(await client.callTool({ name: 'list_sites', arguments: {} })).sites as { siteId: string }[];
    assert.deepEqual(sites.map(site => site.siteId), ['myer-plant']);
    const bristolAttestation = [...upstream.state.attestations.values()].find(record => record.propertyId === 'bristol-pumps')!.id;
    const checked = await client.callTool({ name: 'check', arguments: { attestationId: bristolAttestation } });
    assert.equal(checked.isError, true); assert.equal(data(checked).code, 'PROPERTY_SCOPE');
    assert(!JSON.stringify(checked).includes('SP-101'));
    const resource = await client.readResource({ uri: 'steward://sites/bristol-pumps/context.min' }).catch(error => error as Error);
    assert(resource instanceof Error);
  } finally { await client.close(); await server.close(); await upstream.close(); }
});

test('addendum 2: missions, agents, transcripts, issues, evals; actor header on every request; validation on the wire', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'mission-test', version: '1.0.0' }, { capabilities: {} });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const tools = (await client.listTools()).tools;
    const startTool = tools.find(tool => tool.name === 'start_mission')!;
    assert.equal(startTool.annotations?.readOnlyHint, false); assert.equal(startTool.annotations?.openWorldHint, true); assert.equal(startTool.annotations?.idempotentHint, false);
    assert.match(startTool.description!, /budget/i); assert.match(startTool.description!, /AUTHORITY_DENIED/); assert.match(startTool.description!, /every 5 s/);
    for (const name of ['get_mission', 'list_missions', 'list_agents', 'get_transcript', 'get_issues', 'list_evals', 'get_eval']) assert.equal(tools.find(tool => tool.name === name)!.annotations?.readOnlyHint, true, name);

    // agents
    const agents = data(await client.callTool({ name: 'list_agents', arguments: {} })).agents as { id: string; level: number; status: string; authority: string[] }[];
    assert.deepEqual(agents.map(agent => agent.id), ['operator', 'director', 'myer-manager', 'myer-engineer', 'myer-compliance', 'myer-technician', 'bristol-manager', 'bristol-engineer', 'bristol-compliance', 'bristol-technician']);
    assert.deepEqual(agents.map(agent => agent.level), [1, 2, 3, 4, 4, 5, 3, 4, 4, 5]);
    assert(agents.every(agent => agent.status === 'idle' && agent.authority.length > 0));
    const agentsResource = (await client.readResource({ uri: AGENTS_URI })).contents.map(item => ('text' in item ? item.text : '')).join('');
    for (const needle of ["Owner's agent", 'Operations Director', 'Plant Manager', 'Site Engineer', 'Compliance Officer', 'Field Technician', 'Live status', '"id":"myer-engineer"', '"id":"bristol-compliance"', 'X-Steward-Actor', 'operator']) assert(agentsResource.includes(needle), `agents resource mentions ${needle}`);

    // evals (seeded run)
    const runs = data(await client.callTool({ name: 'list_evals', arguments: {} })).runs as { id: string; suite: string; passed: number }[];
    assert.equal(runs.length, 1); assert.equal(runs[0]!.suite, 'demo-workflow');
    const run = data(await client.callTool({ name: 'get_eval', arguments: { evalId: runs[0]!.id } }));
    assert.equal(run.passed, 12); assert.equal((run.steps as { result: string }[])[0]!.result, 'PASS');
    const missingRun = await client.callTool({ name: 'get_eval', arguments: { evalId: 'eval-nope' } });
    assert.equal(missingRun.isError, true); assert.equal(data(missingRun).code, 'NOT_FOUND');

    // mission: start → Atlas → Warden → Runner dispatch for the one unknown restart attribute
    assert.deepEqual(data(await client.callTool({ name: 'list_missions', arguments: {} })).missions, []);
    const mission = data(await client.callTool({ name: 'start_mission', arguments: { siteId: 'myer-plant', goal: 'clear_for_restart', budget: 5 } }));
    assert.equal(mission.state, 'running'); assert.equal(mission.siteId, 'myer-plant'); assert.equal(mission.budget, 5); assert.equal(mission.requester, 'mcp-client');
    assert.equal(typeof mission.contextId, 'string');
    assert.deepEqual(upstream.state.lastMissionBody, { siteId: 'myer-plant', goal: 'clear_for_restart', budget: 5, requester: 'mcp-client', actor: 'operator' });
    const missionId = mission.id as string;
    const steps = mission.steps as { agentId: string; summary: string; workItemId?: string | null; attestationId?: string | null; taskId?: string | null }[];
    assert.equal(steps[0]!.agentId, 'director');
    assert(steps.some(step => step.agentId === 'myer-engineer' && step.attestationId), 'known attributes are cited by the site engineer');
    const runnerStep = steps.find(step => step.agentId === 'myer-technician')!;
    assert(runnerStep.workItemId, 'the field technician dispatched a human for P-101.pressure_bar');
    assert.equal(steps.filter(step => step.workItemId).length >= 1, true);
    const same = data(await client.callTool({ name: 'get_mission', arguments: { missionId } }));
    assert.equal(same.id, missionId); assert.equal(same.state, 'running');
    assert.equal((data(await client.callTool({ name: 'list_missions', arguments: { siteId: 'myer-plant' } })).missions as unknown[]).length, 1);
    assert.equal((data(await client.callTool({ name: 'list_missions', arguments: { siteId: 'bristol-pumps' } })).missions as unknown[]).length, 0);
    const working = data(await client.callTool({ name: 'list_agents', arguments: {} })).agents as { id: string; status: string; currentTask: string | null }[];
    assert.equal(working.find(agent => agent.id === 'director')!.status, 'working'); assert.equal(working.find(agent => agent.id === 'director')!.currentTask, missionId);
    assert.equal(working.find(agent => agent.id === 'myer-technician')!.status, 'waiting');
    const changes = data(await client.callTool({ name: 'get_changes', arguments: { siteId: 'myer-plant', since: 0, limit: 500 } }));
    const waiting = (changes.waiting as { assetTag: string; attribute: string; reference: string; id: string; requester: string }[]).find(item => item.assetTag === 'P-101' && item.attribute === 'pressure_bar')!;
    assert.match(waiting.reference, /^MY-P101-PRESSURE_BAR-\d{4}$/); assert.equal(waiting.id, runnerStep.workItemId); assert.equal(waiting.requester, 'myer-engineer');
    assert((changes.changes as { type: string }[]).some(change => change.type === 'a2a'), 'every agent message emits an a2a change');

    // transcripts
    const runnerLog = data(await client.callTool({ name: 'get_transcript', arguments: { agentId: 'myer-technician' } }));
    assert.equal(runnerLog.agentId, 'myer-technician');
    const runnerEntries = runnerLog.entries as { kind: string; direction: string; counterpart: string; text: string; refs: { missionId?: string; workItemId?: string; taskId?: string } }[];
    assert(runnerEntries.some(entry => entry.kind === 'a2a' && entry.direction === 'in' && entry.counterpart === 'myer-engineer'), 'the technician received the field task');
    const dispatchEntry = runnerEntries.find(entry => entry.direction === 'out' && /dispatch/i.test(entry.text))!;
    assert.equal(dispatchEntry.refs.workItemId, waiting.id); assert.equal(dispatchEntry.refs.missionId, missionId);
    const atlasLog = data(await client.callTool({ name: 'get_transcript', arguments: { agentId: 'director', since: 0, limit: 10 } })).entries as { kind: string; parts?: unknown[]; refs: { missionId?: string } }[];
    assert(atlasLog.length >= 2 && atlasLog.length <= 10);
    assert(atlasLog.every(entry => entry.kind === 'a2a' && entry.refs.missionId === missionId && Array.isArray(entry.parts)));
    assert.equal((data(await client.callTool({ name: 'get_transcript', arguments: { agentId: 'director', since: 1, limit: 1 } })).entries as unknown[]).length, 1, 'since is a cursor');

    // the technician replies: wrong tag rejected, mission still running; right tag accepted, mission completed with a valid checklist
    const inbound = async (statedTag: string, value: number) => (await fetch(`${upstream.url}/api/inbound/local`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reference: waiting.reference, body: `Gauge on ${statedTag} reads ${value} bar`, statedTag, value }) })).json() as Promise<{ verdict: string }>;
    assert.equal((await inbound('P-102', 2.4)).verdict, 'rejected');
    const afterReject = data(await client.callTool({ name: 'get_mission', arguments: { missionId } }));
    assert.equal(afterReject.state, 'running');
    assert.match((afterReject.steps as { summary: string }[]).at(-1)!.summary, /rejected/);
    assert.equal((await inbound('P-101', 2.4)).verdict, 'accepted');
    const done = data(await client.callTool({ name: 'get_mission', arguments: { missionId } }));
    assert.equal(done.state, 'completed');
    const checklist = done.checklist as { assetTag: string; attribute: string; value: unknown; attestationId: string; valid: boolean }[];
    assert.equal(checklist.length, 6); assert(checklist.every(line => line.valid));
    const pressure = checklist.find(line => line.assetTag === 'P-101' && line.attribute === 'pressure_bar')!;
    assert.equal(pressure.value, 2.4);
    assert.equal(data(await client.callTool({ name: 'check', arguments: { attestationId: pressure.attestationId } })).valid, true);
    const atlasAfter = data(await client.callTool({ name: 'get_transcript', arguments: { agentId: 'director' } })).entries as { direction: string; counterpart: string; text: string }[];
    assert(atlasAfter.some(entry => entry.direction === 'out' && entry.counterpart === 'operator' && /completed/.test(entry.text)));
    const wardenAfter = data(await client.callTool({ name: 'get_transcript', arguments: { agentId: 'myer-engineer' } })).entries as { refs: { attestationId?: string } }[];
    assert(wardenAfter.some(entry => entry.refs.attestationId === pressure.attestationId), 'the engineer reported the attestation to the director');
    assert.equal((data(await client.callTool({ name: 'list_agents', arguments: {} })).agents as { id: string; status: string }[]).find(agent => agent.id === 'director')!.status, 'idle');

    // issues: the rejected reply is a rejected_evidence issue; both registers are seeded with identity facts; the register issue passes through
    const issues = data(await client.callTool({ name: 'get_issues', arguments: { siteId: 'myer-plant' } })).issues as { kind: string; assetTag: string; pin: { x: number; y: number } | null; refId: string }[];
    assert(issues.some(issue => issue.kind === 'rejected_evidence' && issue.assetTag === 'P-101'));
    assert(!issues.some(issue => issue.kind === 'unknown_identity'));
    assert(issues.some(issue => issue.assetTag === 'V-503' && issue.kind === 'valve_condition'), 'addendum-3 register issues pass through get_issues');
    assert(issues.every(issue => !issue.pin || (issue.pin.x >= 0 && issue.pin.x <= 1 && issue.pin.y >= 0 && issue.pin.y <= 1)));
    const bristolIssues = data(await client.callTool({ name: 'get_issues', arguments: { siteId: 'bristol-pumps' } })).issues as { kind: string }[];
    assert(!bristolIssues.some(issue => issue.kind === 'unknown_identity'), 'both registers are seeded with identity facts');

    // every request the MCP made carried X-Steward-Actor: operator; the only header-less requests are the two technician replies this test POSTed itself
    assert(upstream.state.actors.filter(actor => actor === 'operator').length > 20);
    assert.deepEqual(upstream.state.actors.filter(actor => actor !== 'operator'), ['', ''], `all MCP requests as operator, got ${[...new Set(upstream.state.actors)].join(',')}`);

    // validation on the wire: new tools reject bad input before anything reaches the backend
    const requestsBefore = upstream.state.actors.length;
    const raw = async (name: string, args: Record<string, unknown>) => (await fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }) })).text();
    assert.match(await raw('start_mission', { siteId: 'myer-plant', goal: 'demolish', budget: 5 }), /invalid|literal|clear_for_restart/i);
    assert.match(await raw('start_mission', { siteId: 'myer-plant', budget: 5000 }), /invalid|<=|big|maximum/i);
    assert.match(await raw('start_mission', { siteId: 'harbor', budget: 5 }), /invalid|enum|myer-plant/i);
    assert.match(await raw('get_transcript', { agentId: 'owner' }), /invalid|enum|option/i);
    assert.match(await raw('get_transcript', { agentId: 'warden:myer-plant' }), /invalid|enum|option/i, 'contract-3 agent ids are gone');
    assert.match(await raw('get_transcript', { agentId: 'atlas' }), /invalid|enum|option/i);
    assert.match(await raw('get_mission', { missionId: 'bad id!' }), /invalid|regex|pattern/i);
    assert.match(await raw('get_eval', { evalId: '' }), /invalid|small|minimum|>=1/i);
    assert.match(await raw('get_issues', { siteId: 'cedar' }), /invalid|enum/i);
    assert.equal(upstream.state.actors.length, requestsBefore, 'nothing reached the backend');
    const missingMission = await client.callTool({ name: 'get_mission', arguments: { missionId: 'msn-missing' } });
    assert.equal(missingMission.isError, true); assert.equal(data(missingMission).code, 'NOT_FOUND'); assert.match(String(data(missingMission).recovery), /list_missions/);


    // prompt
    const prompt = await client.getPrompt({ name: 'clear-site-for-restart', arguments: { siteId: 'myer-plant', budget: '5' } });
    const promptText = (prompt.messages[0]!.content as { text: string }).text;
    for (const needle of ['start_mission', 'never faster than every 5 s', 'get_transcript("director")', 'get_transcript("myer-engineer")', 'get_transcript("myer-technician")', 'check(attestationId)', 'budget=5', 'list_missions', 'wait_for']) assert(promptText.includes(needle), `prompt mentions ${needle}`);
  } finally { await client.close(); await server.close(); await upstream.close(); }
});

test('addendum 2: AUTHORITY_DENIED is mapped through for a non-operator actor; input_required on an out-of-range reading; warden scope', async () => {
  const upstream = await fakeRealityBackend();
  const asAtlas = createStewardServer(config(upstream.url, { actor: 'director' }));
  const asOperator = createStewardServer(config(upstream.url));
  const scoped = createStewardServer(config(upstream.url, { allowedProperties: ['bristol-pumps'] }));
  const [atlasListener, operatorListener, scopedListener] = await Promise.all([asAtlas.listen(0, { host: '127.0.0.1' }), asOperator.listen(0, { host: '127.0.0.1' }), scoped.listen(0, { host: '127.0.0.1' })]);
  const atlas = new Client({ name: 'director-probe', version: '1' }, { capabilities: {} });
  const operator = new Client({ name: 'operator-probe', version: '1' }, { capabilities: {} });
  const scopedClient = new Client({ name: 'scoped-probe', version: '1' }, { capabilities: {} });
  try {
    await Promise.all([atlas.connect(new StreamableHTTPClientTransport(new URL(atlasListener.url))), operator.connect(new StreamableHTTPClientTransport(new URL(operatorListener.url))), scopedClient.connect(new StreamableHTTPClientTransport(new URL(scopedListener.url)))]);
    const denied = await atlas.callTool({ name: 'start_mission', arguments: { siteId: 'myer-plant', budget: 5 } });
    assert.equal(denied.isError, true);
    const deniedError = data(denied);
    assert.equal(deniedError.code, 'AUTHORITY_DENIED'); assert.equal(deniedError.httpStatus, 403); assert.equal(deniedError.retryable, false);
    assert.match(String(deniedError.message), /director/); assert.match(String(deniedError.recovery), /operator/);
    assert.equal(upstream.state.actors.at(-1), 'director', 'the configured actor is sent');
    assert.equal(upstream.state.missions.size, 0);
    const deniedAttest = data(await atlas.callTool({ name: 'attest', arguments: { siteId: 'myer-plant', assetTag: 'V-502', attribute: 'position', value: 'open', source: { kind: 'agent', ref: 'director' }, statedTag: 'V-502' } }));
    assert.equal(deniedAttest.code, 'AUTHORITY_DENIED'); assert.match(String(deniedAttest.message), /myer-engineer/);
    assert.equal((await atlas.readResource({ uri: AGENTS_URI })).contents.map(item => ('text' in item ? item.text : '')).join('').includes('acts as agent "director"'), true);

    // out-of-range evidence: the mission goes input_required, Atlas asks the owner and the other wardens
    const mission = data(await operator.callTool({ name: 'start_mission', arguments: { siteId: 'myer-plant', budget: 5 } }));
    const workItemId = (mission.steps as { agentId: string; workItemId?: string | null }[]).find(step => step.agentId === 'myer-technician')!.workItemId as string;
    const reference = (await (await fetch(`${upstream.url}/api/work-items/${workItemId}`)).json() as { reference: string }).reference;
    const reply = await (await fetch(`${upstream.url}/api/inbound/local`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reference, body: 'Gauge on P-101 reads 9.8 bar', statedTag: 'P-101', value: 9.8 }) })).json() as { verdict: string };
    assert.equal(reply.verdict, 'needs_clarification');
    const asked = data(await operator.callTool({ name: 'get_mission', arguments: { missionId: mission.id as string } }));
    assert.equal(asked.state, 'input_required');
    assert.match((asked.steps as { summary: string }[]).at(-1)!.summary, /owner/i);
    const atlasLog = data(await operator.callTool({ name: 'get_transcript', arguments: { agentId: 'director' } })).entries as { kind: string; counterpart: string; direction: string }[];
    assert(atlasLog.some(entry => entry.kind === 'sms' && entry.counterpart === 'owner' && entry.direction === 'out'));
    assert(atlasLog.some(entry => entry.kind === 'a2a' && entry.counterpart === 'bristol-manager'), 'cross-site check, director to the other plant manager');
    const issues = data(await operator.callTool({ name: 'get_issues', arguments: { siteId: 'myer-plant' } })).issues as { kind: string }[];
    assert(issues.some(issue => issue.kind === 'overdue'), 'a needs_clarification work item is an issue');

    // a bristol-pumps-only endpoint hides the other Warden and its missions
    const agents = data(await scopedClient.callTool({ name: 'list_agents', arguments: {} })).agents as { id: string }[];
    assert.deepEqual(agents.map(agent => agent.id), ['operator', 'director', 'bristol-manager', 'bristol-engineer', 'bristol-compliance', 'bristol-technician']);
    assert.equal(data(await scopedClient.callTool({ name: 'get_transcript', arguments: { agentId: 'myer-engineer' } })).code, 'PROPERTY_SCOPE');
    assert.equal(data(await scopedClient.callTool({ name: 'get_mission', arguments: { missionId: mission.id as string } })).code, 'PROPERTY_SCOPE');
    assert.deepEqual(data(await scopedClient.callTool({ name: 'list_missions', arguments: {} })).missions, []);
    assert.equal(data(await scopedClient.callTool({ name: 'start_mission', arguments: { siteId: 'bristol-pumps', budget: 0 } })).state, 'failed', 'no budget and unknown restart facts: the mission fails and says what is missing');
  } finally { await Promise.allSettled([atlas.close(), operator.close(), scopedClient.close()]); await Promise.all([asAtlas.close(), asOperator.close(), scoped.close()]); await upstream.close(); }
});

type Report = { passed: number; failed: number; rows: { id: string; ok: boolean; detail: string; skipped?: boolean; data: Record<string, unknown> }[] };
const failures = (report: Report) => report.rows.filter(row => !row.ok).map(row => `${row.id}: ${row.detail}`).join('\n');

test('eval runner: the demo workflow replays end to end against the fake upstream, twice', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  try {
    const workflow = JSON.parse(await readFile(resolveSuite('demo-workflow'), 'utf8')) as { steps: { id: string }[] };
    const first = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as Report;
    assert.equal(first.failed, 0, failures(first));
    assert.equal(first.passed, workflow.steps.length);
    assert.equal(first.rows.find(row => row.id === 'resolve_pressure_dispatch')!.data.status, 'unknown');
    assert.match(String(first.rows.find(row => row.id === 'resolve_pressure_dispatch')!.data.reference), /^MY-P101-/);
    const second = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as Report;
    assert.equal(second.failed, 0, failures(second));
    assert.equal(second.rows.find(row => row.id === 'resolve_pressure_dispatch')!.data.status, 'stale', 'replay treats the earlier fact as stale');
    // MCP tool steps carry the operator header; the runner's http steps play the technician and carry none (two inbound replies per run)
    assert.equal(upstream.state.actors.filter(actor => actor === '').length, 4);
    assert(upstream.state.actors.filter(actor => actor === 'operator').length >= 20);
    // matcher sanity
    assert.deepEqual(checkExpectations({ a: { b: [1, { c: 'xyz' }] } }, { 'a.b[-1].c': { $contains: 'y' }, 'a.b[0]': 1, missing: { $exists: false } }), []);
    assert.equal((checkExpectations({ a: 1 }, { a: 2 }) as string[]).length, 1);
    assert.deepEqual(substitute({ x: '${id}', y: 'ref ${id}' }, { id: 7 }), { x: 7, y: 'ref 7' });
    assert.equal(getPath({ waiting: [{ assetTag: 'P-101', attribute: 'serial', id: 'a' }, { assetTag: 'P-101', attribute: 'pressure_bar', id: 'b' }] }, 'waiting[assetTag=P-101,attribute=pressure_bar].id'), 'b');
    assert.equal(getPath({ waiting: [] }, 'waiting[assetTag=P-101].id'), undefined);
    assert.deepEqual(checkExpectations({ state: 'running', steps: [{ agentId: 'runner' }] }, { $any: [{ state: 'input_required' }, { steps: { $jsonContains: '"agentId":"runner"' } }] }), []);
    assert.equal((checkExpectations({ state: 'running', steps: [] }, { $any: [{ state: 'input_required' }, { steps: { $jsonContains: '"agentId":"runner"' } }] }) as string[]).length, 1);
    assert.deepEqual(checkExpectations({ entries: [{ text: 'Dispatch: card sent' }] }, { entries: { $matches: '/dispatch/i' }, 'entries[0].text': { $matches: '^Dispatch' } }), []);
    assert.equal((checkExpectations({ entries: [] }, { entries: { $matches: '/dispatch/i' } }) as string[]).length, 1);
    assert.match(resolveSuite('mission-workflow'), /evals\/mission-workflow\.json$/);
    assert.deepEqual(evalSteps({ rows: [{ id: 'a', target: 'get_mission', ok: true, ms: 3, detail: '' }] } as never), [{ name: 'a', target: 'get_mission', result: 'PASS', ms: 3, detail: '' }]);
  } finally { await server.close(); await upstream.close(); }
});

test('eval runner: the mission workflow replays against the fake upstream (dispatch on a fresh database, skipped inbound steps on replay)', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  try {
    const workflow = JSON.parse(await readFile(resolveSuite('mission-workflow'), 'utf8')) as { steps: { id: string }[] };
    const first = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as Report;
    assert.equal(first.failed, 0, failures(first));
    assert.equal(first.passed, workflow.steps.length);
    assert(!first.rows.some(row => row.skipped), 'a fresh database exercises every step');
    assert.equal(first.rows.find(row => row.id === 'mission_reaches_technician')!.data.state, 'running');
    assert.equal(first.rows.find(row => row.id === 'inbound_wrong_tag_rejected')!.data.verdict, 'rejected');
    assert.equal(first.rows.find(row => row.id === 'mission_completed')!.data.state, 'completed');
    assert.equal(upstream.state.missions.size, 1);
    const second = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as Report;
    assert.equal(second.failed, 0, failures(second));
    assert.equal(second.rows.find(row => row.id === 'mission_reaches_technician')!.data.state, 'completed', 'inside the reading TTL the mission completes without a dispatch');
    assert.deepEqual(second.rows.filter(row => row.skipped).map(row => row.id), ['find_pressure_work_item', 'inbound_wrong_tag_rejected', 'inbound_right_tag_accepted']);
    assert.equal(upstream.state.missions.size, 2);
  } finally { await server.close(); await upstream.close(); }
});
