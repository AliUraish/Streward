/**
 * REALITY-CONTRACT-6.md, Tool Forge, against the fake upstream: request_tool files a request and the builder's draft;
 * the backend lifecycle (validate, test, approve, publish) enforces who may do what; the MCP's poller turns the
 * published tool into a first-class forge_<name> (tools/list + tools/call) and emits notifications/tools/list_changed
 * on both protocol eras; calls go through POST /api/tools/{id}/call with the actor header, count usage and write
 * telemetry under the forged name; scope, argument checks and retirement; the tool-forge eval suite replays.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer, ACT_AS_HEADER } from '../src/server.js';
import { PROPERTY_IDS, type RuntimeConfig } from '../src/config.js';
import { checkArgs, forgedDescription, normaliseForgedTool, structuredOutput } from '../src/forge.js';
import { loadAnalytics } from '../src/analytics.js';
import { HARNESS_HEADER, HARNESS_HEADER_VALUE } from '../src/harness.js';
import { fakeRealityBackend } from './fake-reality.js';
// @ts-expect-error untyped .mjs module
import { runWorkflow, resolveSuite } from '../../evals/run.mjs';

type Data = Record<string, any>;
function data(result: CallToolResult): Data {
  const text = result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
  if (result.structuredContent) return result.structuredContent as Data;
  try { return JSON.parse(text) as Data; } catch { return { text }; }
}
function config(url: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl: url, port: 0, host: '127.0.0.1', allowedProperties: [...PROPERTY_IDS], actor: 'operator', requestTimeoutMs: 3000, remoteBackend: false, hosted: false, waitDefaultSeconds: 50, subscriptionPollMs: 100, waitProgressMs: 250, forgePollMs: 150, harnessTools: true, ...patch };
}
const post = async (url: string, path: string, actor: string, body: Record<string, unknown> = {}) => {
  const response = await fetch(`${url}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Steward-Actor': actor }, body: JSON.stringify(body) });
  return { status: response.status, body: await response.json() as Data };
};
const until = async <T>(read: () => Promise<T | undefined>, what: string, ms = 5000): Promise<T> => {
  const deadline = Date.now() + ms;
  for (;;) { const value = await read(); if (value !== undefined) return value; if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`); await delay(50); }
};
const MYER_TASK = 'Which pumps went over their pressure spec more than three times in the last 7 days, and who is responsible for each?';

test('contract 6: request_tool, the lifecycle authority, forge_<name> as a first-class tool with list_changed, calls, scope, retirement', async () => {
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  // ServerOptions ({config}) so the Steward telemetry sink is on (a bare RuntimeConfig selects the no-op sink).
  const server = createStewardServer({ config: config(upstream.url, { allowActAs: true }) });
  const scoped = createStewardServer(config(upstream.url, { allowedProperties: ['bristol-pumps'] }));
  const [listener, scopedListener] = await Promise.all([server.listen(0, { host: '127.0.0.1' }), scoped.listen(0, { host: '127.0.0.1' })]);
  const client = new Client({ name: 'forge-probe', version: '1' }, { capabilities: {} });
  const modern = new Client({ name: 'forge-listener', version: '1' }, { capabilities: {}, versionNegotiation: { mode: 'auto' } } as never);
  const bristolOnly = new Client({ name: 'bristol-only', version: '1' }, { capabilities: {} });
  const bristolEngineer = new Client({ name: 'as-bristol-engineer', version: '1' }, { capabilities: {} });
  const mcpUse = new MCPClient({ clientInfo: { name: 'forge-mcp-use', version: '1' }, mcpServers: { steward: { url: listener.url, oauth: false, detectMixedAuth: false } } });
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    await Promise.all([
      // client counts the tools: it carries the eval harness's header, so list_scenarios and start_scenario are among them.
      client.connect(new StreamableHTTPClientTransport(new URL(listener.url), { requestInit: { headers: { [HARNESS_HEADER]: HARNESS_HEADER_VALUE } } })), modern.connect(new StreamableHTTPClientTransport(new URL(listener.url))),
      bristolOnly.connect(new StreamableHTTPClientTransport(new URL(scopedListener.url))),
      bristolEngineer.connect(new StreamableHTTPClientTransport(new URL(listener.url), { requestInit: { headers: { [ACT_AS_HEADER]: 'bristol-engineer' } } })),
    ]);
    const call = async (name: string, args: Record<string, unknown> = {}) => client.callTool({ name, arguments: args }) as Promise<CallToolResult>;

    // the three stable tools; nothing forged is published yet
    const tools = (await client.listTools()).tools;
    assert.equal(tools.length, 73);
    for (const name of ['request_tool', 'list_forged_tools', 'call_forged_tool']) {
      const tool = tools.find(t => t.name === name)!;
      assert(tool && tool.outputSchema && /NEXT/.test(tool.description!) && /cost|free/i.test(tool.description!), name);
    }
    assert(!tools.some(t => t.name.startsWith('forge_')));
    assert.equal(tools.find(t => t.name === 'list_forged_tools')!.annotations?.readOnlyHint, true);

    // request: the Owner's agent asks Myer's Site Engineer; dry-run uses the prepared draft
    const request = data(await call('request_tool', { siteId: 'myer-plant', task: MYER_TASK, agentId: 'myer-engineer' }));
    assert.equal(request.status, 'draft'); assert.equal(request.mcpName, 'forge_pump_spec_breaches'); assert.equal(request.agentId, 'myer-engineer'); assert.equal(request.requestedBy, 'operator');
    assert.match(request.gap, /get_metrics/); assert(request.consideredTools.length >= 2 && request.consideredTools.every((t: Data) => t.name && t.whyNot)); assert.equal(request.generator, 'hand-seed');
    assert.match(request.nextStep, /wait_for\(event="any", siteId="myer-plant", filter=\{type:"tool", toolId:"[^"]+", status:"published"\}\)/);
    const toolId = request.toolId as string;
    assert(upstream.state.transcripts.some(entry => entry.agentId === 'myer-engineer' && /I don't have a tool for this; drafting forge_pump_spec_breaches/.test(entry.text)));
    const wrongTeam = await call('request_tool', { siteId: 'myer-plant', task: 'Count the breaches for me, please', agentId: 'bristol-engineer' });
    assert.equal(wrongTeam.isError, true); assert.equal(data(wrongTeam).code, 'INVALID_ARGUMENT');
    assert.equal(data(await call('request_tool', { siteId: 'myer-plant', task: 'Count the open issues, please' })).agentId, 'myer-engineer', 'the site engineer builds by default');

    // the lifecycle on the backend, in order, with its authority: the builder validates and tests, the Plant Manager approves
    assert.equal((await post(upstream.url, `/api/tools/${toolId}/approve`, 'myer-manager', { approve: true })).status, 409, 'not tested yet');
    assert.equal((await post(upstream.url, `/api/tools/${toolId}/validate`, 'myer-engineer')).body.status, 'validated');
    const tested = await post(upstream.url, `/api/tools/${toolId}/test`, 'myer-engineer');
    assert.equal(tested.body.status, 'tested'); assert.equal(tested.body.test.passed, true); assert(tested.body.test.output.rows.length >= 1);
    for (const actor of ['myer-technician', 'bristol-manager']) assert.equal((await post(upstream.url, `/api/tools/${toolId}/approve`, actor, { approve: true })).status, 403, `${actor} may not approve`);
    const waiting = (data(await call('list_forged_tools', { siteId: 'myer-plant', status: 'tested' })).tools as Data[]).find(t => t.id === toolId)!;
    assert.equal(waiting.firstClass, false); assert.equal(waiting.createdByName, 'Site Engineer · Myer');

    // listen for tools/list_changed on both eras before publishing
    const changed: string[] = [];
    modern.setNotificationHandler('notifications/tools/list_changed' as never, (() => { changed.push('modern'); }) as never);
    await (modern as unknown as { listen(filter: unknown): Promise<unknown> }).listen({ toolsListChanged: true });
    const rpc = (body: unknown, session?: string) => fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...(session ? { 'Mcp-Session-Id': session } : {}) }, body: JSON.stringify(body) });
    const init = await rpc({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'legacy-forge', version: '1' } } });
    const session = init.headers.get('mcp-session-id')!; await init.text();
    assert(session);
    const stream = await fetch(listener.url, { method: 'GET', headers: { Accept: 'text/event-stream', 'Mcp-Session-Id': session } });
    reader = stream.body!.getReader();
    let legacyText = '';
    const legacyRead = (async () => { const decoder = new TextDecoder(); for (;;) { const { value, done } = await reader!.read(); if (done) return; legacyText += decoder.decode(value); } })().catch(() => {});

    assert.equal((await post(upstream.url, `/api/tools/${toolId}/approve`, 'myer-manager', { approve: true, reason: 'read-only; tested on local data' })).body.status, 'approved');
    assert.equal((await post(upstream.url, `/api/tools/${toolId}/publish`, 'myer-manager')).body.status, 'published');

    // the poller (150 ms here, 5 s by default) turns it into a first-class tool and tells both eras
    const forged = await until(async () => (await client.listTools()).tools.find(t => t.name === 'forge_pump_spec_breaches'), 'forge_pump_spec_breaches in tools/list');
    assert.match(forged.description!, /^Built by Site Engineer · Myer on \d{4}-\d{2}-\d{2} because `get_metrics` returns raw series and `who_is_responsible` takes one issue kind; nothing counts breaches per asset or joins owners\./);
    assert.match(forged.description!, /approved by Plant Manager · Myer/); assert.match(forged.description!, /read-only/);
    assert.deepEqual((forged.inputSchema as Data).required, ['days', 'minBreaches']); assert.equal((forged.inputSchema as Data).additionalProperties, false);
    assert.equal(forged.annotations?.readOnlyHint, true); assert.equal((forged.outputSchema as Data).properties.rows.type, 'array');
    assert.equal(((forged._meta as Data)['io.steward/forgedTool'] as Data).id, toolId);
    await until(async () => changed.length ? true : undefined, 'notifications/tools/list_changed on the subscriptions/listen stream');
    await until(async () => legacyText.includes('notifications/tools/list_changed') ? true : undefined, 'notifications/tools/list_changed on the legacy session stream');
    const health = await (await fetch(new URL('/health', listener.url))).json() as Data;
    assert.deepEqual(health.forged.tools, ['forge_pump_spec_breaches']); assert.equal(health.forged.pollMs, 150);

    // call it by its own name (official and mcp-use clients) and through call_forged_tool
    const direct = await call('forge_pump_spec_breaches', { days: 7, minBreaches: 4 });
    assert(!direct.isError, JSON.stringify(direct.content));
    const rows = (direct.structuredContent as Data).rows as Data[];
    assert.deepEqual(rows.map(row => row.assetTag), ['P-102', 'P-103']); assert.equal(rows[0]!.unit, 'bar'); assert.equal(rows[0]!.owner.name, 'Duty engineer (you)');
    assert.match(direct.content.filter(block => block.type === 'text').map(block => block.text).join(''), /2 pumps over their pressure spec/);
    const viaMcpUse = await (await mcpUse.connect('steward')).callTool('forge_pump_spec_breaches', { days: 7, minBreaches: 6 }) as CallToolResult;
    assert.deepEqual(((viaMcpUse.structuredContent as Data).rows as Data[]).map(row => row.assetTag), ['P-102']);
    const stable = data(await call('call_forged_tool', { toolId, args: { days: 7, minBreaches: 4 } }));
    assert.equal(stable.name, 'forge_pump_spec_breaches'); assert.equal(stable.siteId, 'myer-plant'); assert.equal(stable.output.rows.length, 2); assert.equal(stable.usage.calls, 3);
    assert(upstream.state.paths.filter(path => path === `POST /api/tools/${toolId}/call`).length === 3);
    assert.equal(upstream.state.actors.at(-1), 'operator', 'the caller\'s actor header reaches the backend');

    // arguments are checked against the tool's schema before the backend; unknown forged names answer a tool error
    const before = upstream.state.paths.length;
    const missing = await call('forge_pump_spec_breaches', { days: 7 });
    assert.equal(missing.isError, true); assert.equal(data(missing).code, 'INVALID_ARGUMENT'); assert.match(data(missing).message, /minBreaches is required/);
    assert.match(data(await call('forge_pump_spec_breaches', { days: 7, minBreaches: 4, colour: 'red' })).message, /unknown argument colour/);
    assert.match(data(await call('forge_pump_spec_breaches', { days: 0, minBreaches: 4 })).message, /days must be >= 1/);
    assert(!upstream.state.paths.slice(before).some(path => path.endsWith('/call')), 'invalid arguments never reach the backend');
    const unknownTool = await call('forge_nothing_here', {});
    assert.equal(unknownTool.isError, true); assert.equal(data(unknownTool).code, 'UNKNOWN_TOOL'); assert.match(data(unknownTool).recovery, /list_forged_tools/);

    // telemetry: forged calls are recorded under the forged name and its site
    await delay(150);
    assert(upstream.state.telemetry.some(event => event.kind === 'mcp' && event.tool === 'forge_pump_spec_breaches' && event.siteId === 'myer-plant' && event.agentId === 'operator'));
    const listed = data(await call('list_forged_tools', { siteId: 'myer-plant' }));
    const row = (listed.tools as Data[]).find(t => t.id === toolId)!;
    assert.equal(row.status, 'published'); assert.equal(row.firstClass, true); assert.equal(row.approvedBy, 'myer-manager'); assert.equal(row.usage.calls, 3);
    assert(row.steps.length >= 4 && row.steps.every((step: Data) => step.op)); assert.equal(row.why.requestedBy, 'operator'); assert.equal(row.test.passed, true);
    assert.deepEqual(listed.firstClass, ['forge_pump_spec_breaches']);

    // scope: a Bristol-only endpoint never lists or runs the Myer tool; a Bristol agent calling it is refused by the backend
    assert(!(await bristolOnly.listTools()).tools.some(t => t.name === 'forge_pump_spec_breaches'));
    assert.equal(data(await bristolOnly.callTool({ name: 'forge_pump_spec_breaches', arguments: { days: 7, minBreaches: 4 } }) as CallToolResult).code, 'UNKNOWN_TOOL');
    assert.equal(data(await bristolOnly.callTool({ name: 'call_forged_tool', arguments: { toolId, args: { days: 7, minBreaches: 4 } } }) as CallToolResult).code, 'PROPERTY_SCOPE');
    assert.equal((data(await bristolOnly.callTool({ name: 'list_forged_tools', arguments: {} }) as CallToolResult).tools as Data[]).length, 0);
    const crossSite = data(await bristolEngineer.callTool({ name: 'forge_pump_spec_breaches', arguments: { days: 7, minBreaches: 4 } }) as CallToolResult);
    assert.equal(crossSite.code, 'AUTHORITY_DENIED'); assert.match(crossSite.message, /bristol-engineer/);

    // every site can forge: Tomioka's compliance officer drafts a tool for the mill
    const tomioka = data(await call('request_tool', { siteId: 'tomioka-mill', task: 'List the open issues at the mill with their severity', agentId: 'tomioka-compliance' }));
    assert.equal(tomioka.status, 'draft'); assert.equal(tomioka.mcpName, 'forge_tomioka_open_issue_digest'); assert.equal(tomioka.agentId, 'tomioka-compliance');

    // retire: it leaves tools/list, list_changed fires again, and calls say why
    const notified = changed.length;
    assert.equal((await post(upstream.url, `/api/tools/${toolId}/retire`, 'myer-manager')).body.status, 'retired');
    await until(async () => (await client.listTools()).tools.some(t => t.name === 'forge_pump_spec_breaches') ? undefined : true, 'forge_pump_spec_breaches gone from tools/list');
    await until(async () => changed.length > notified ? true : undefined, 'a second list_changed');
    assert.equal(data(await call('forge_pump_spec_breaches', { days: 7, minBreaches: 4 })).code, 'UNKNOWN_TOOL');
    const retired = data(await call('call_forged_tool', { toolId, args: { days: 7, minBreaches: 4 } }));
    assert.equal(retired.code, 'TOOL_NOT_PUBLISHED'); assert.equal(retired.httpStatus, 409);
    void legacyRead;
  } finally {
    await reader?.cancel().catch(() => {});
    await Promise.allSettled([client.close(), modern.close(), bristolOnly.close(), bristolEngineer.close(), mcpUse.close()]);
    await Promise.all([server.close(), scoped.close()]); await upstream.close();
  }
});

test('contract 6: with Armature analytics on, forge_<name> advertises the telemetry block and its call carries it (Bristol visitor route readiness)', async () => {
  const batches: { events: Record<string, unknown>[] }[] = [];
  const analytics = await loadAnalytics({ ARMATURE_API_KEY: 'ami_test_key' }, 'steward-test', { emit: batch => { batches.push(batch as typeof batches[number]); }, delivery: 'await' });
  assert.equal(analytics.provider, 'armature');
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  const server = createStewardServer({ config: config(upstream.url), analytics });
  analytics.attach(server);
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const named = new MCPClient({ clientInfo: { name: 'armature-forge-probe', version: '1' }, mcpServers: { steward: { url: listener.url, oauth: false, detectMixedAuth: false } } });
  try {
    const connection = await named.connect('steward');
    const request = data(await connection.callTool('request_tool', { siteId: 'bristol-pumps', agentId: 'bristol-compliance', task: 'List every asset on the visitor route that has an open issue or an overdue obligation, the regulation involved, and who must act.' }) as CallToolResult);
    assert.equal(request.mcpName, 'forge_visitor_route_readiness'); assert.equal(request.agentId, 'bristol-compliance');
    const toolId = request.toolId as string;
    for (const [step, actor] of [['validate', 'bristol-compliance'], ['test', 'bristol-compliance'], ['approve', 'bristol-manager'], ['publish', 'bristol-manager']] as const) {
      const out = await post(upstream.url, `/api/tools/${toolId}/${step}`, actor, step === 'approve' ? { approve: true, reason: 'read-only' } : {});
      assert.equal(out.status, 200, `${step}: ${JSON.stringify(out.body)}`);
    }
    const forged = await until(async () => (await connection.listTools()).find(t => t.name === 'forge_visitor_route_readiness'), 'forge_visitor_route_readiness listed');
    assert.match(forged.description ?? '', /^Built by Compliance Officer · Bristol on .+ because Issues and obligations are separate tools/);
    assert((forged.inputSchema as Data).properties.telemetry, 'the Armature telemetry block is advertised on the forged tool');
    const result = await connection.callTool('forge_visitor_route_readiness', { telemetry: { user_intent: 'Check whether the visitor route can open.', call_purpose: 'Check the visitor route readiness.' } }) as CallToolResult;
    assert(!result.isError, JSON.stringify(result.content));
    const ready = result.structuredContent as Data;
    assert.equal(typeof ready.ready, 'boolean'); assert(ready.rows.some((row: Data) => row.assetTag === 'L-901'), 'the flickering walkway luminaire is on the route');
    await analytics.close();
    const calls = batches.flatMap(batch => batch.events).filter(event => event.kind === 'tool_call');
    const forgedCall = calls.find(event => (event.metadata as Data)?.tool_name === 'call_forged_tool');
    assert(forgedCall, 'tool_call recorded for the re-dispatched forged call'); assert.equal(forgedCall.ok, true);
    assert.match(JSON.stringify(forgedCall), /Check the visitor route readiness/, 'the telemetry block reached Armature');
  } finally { await named.close(); await server.close(); await upstream.close(); }
});

test('contract 6: forged-tool helpers: normalisation, the description, the argument check, structured output', () => {
  const tool = normaliseForgedTool({ id: 'tool-1', name: 'forge_visitor_route_readiness', version: 2, status: 'published', siteId: 'bristol-pumps', createdBy: 'bristol-compliance', createdAt: '2026-10-18T07:00:00Z', approvedBy: 'bristol-manager', why: { task: 'List every asset on the visitor route…', requestedBy: 'bristol-manager', gap: 'Issues and obligations are separate tools without route membership or the regulation link.', consideredTools: [{ name: 'list_issues', whyNot: 'no route' }] }, description: 'Visitor route readiness.', inputSchema: { type: 'object', additionalProperties: false, properties: {} }, readOnly: true })!;
  assert.equal(tool.name, 'visitor_route_readiness'); assert.equal(tool.mcpName, 'forge_visitor_route_readiness', 'an already-prefixed name is not prefixed twice');
  assert.match(forgedDescription(tool), /^Built by Compliance Officer · Bristol on 2026-10-18 because Issues and obligations are separate tools without route membership or the regulation link\. Visitor route readiness\./);
  assert.equal(normaliseForgedTool({ id: 'x' }), null);
  assert.equal(normaliseForgedTool({ id: 'w', name: 'writer', status: 'published' })!.readOnly, false, 'read-only only when the backend says so');
  const schema = { type: 'object', additionalProperties: false, properties: { days: { type: 'integer', minimum: 1, maximum: 30 }, mode: { type: 'string', enum: ['a', 'b'] }, note: { type: ['string', 'null'] } }, required: ['days'] };
  assert.equal(checkArgs(schema, { days: 7 }), null);
  assert.equal(checkArgs(schema, { days: 7, note: null }), null);
  assert.match(checkArgs(schema, {})!, /days is required/);
  assert.match(checkArgs(schema, { days: 1.5 })!, /days must be integer/);
  assert.match(checkArgs(schema, { days: 31 })!, /<= 30/);
  assert.match(checkArgs(schema, { days: 7, mode: 'c' })!, /one of a, b/);
  assert.match(checkArgs(schema, { days: 7, extra: 1 })!, /unknown argument extra/);
  assert.deepEqual(structuredOutput([1, 2]), { rows: [1, 2] }); assert.deepEqual(structuredOutput({ ready: true }), { ready: true }); assert.deepEqual(structuredOutput(3), { value: 3 });
});

test('contract 6: the tool-forge eval suite replays against the fake upstream (request → draft → test → approve → published → call)', async () => {
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  try {
    for (const round of [1, 2]) {
      const workflow = JSON.parse(await readFile(resolveSuite('tool-forge'), 'utf8')) as { steps: { id: string }[] };
      const report = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as { passed: number; failed: number; rows: { id: string; ok: boolean; detail: string }[] };
      assert.equal(report.failed, 0, `round ${round}\n${report.rows.filter(row => !row.ok).map(row => `${row.id}: ${row.detail}`).join('\n')}`);
      assert.equal(report.passed, workflow.steps.length);
    }
    const published = [...upstream.state.tools.values()].filter(tool => tool.status === 'published');
    assert.deepEqual(published.map(tool => [tool.name, tool.version]), [['pump_spec_breaches', 2]], 'the second round published v2 and retired v1');
  } finally { await server.close(); await upstream.close(); }
});
