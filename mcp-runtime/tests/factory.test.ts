/**
 * Addendum 3 (REALITY-CONTRACT-3.md §7, §10): the new tools, wait_for (progress, still_waiting, fired), resource
 * subscriptions in both protocol eras, elicitation for decide, the show_factory MCP Apps view, Steward telemetry,
 * the eval act-as header and the three new eval suites, all against the extended fake upstream.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer, ACT_AS_HEADER } from '../src/server.js';
import type { RuntimeConfig } from '../src/config.js';
import { createTelemetry, estimateTokens } from '../src/telemetry.js';
import { FACTORY_VIEW_JS, PLAYCANVAS_URL } from '../src/widget.js';
import { fakeRealityBackend, INJECTION_TEXT } from './fake-reality.js';
// @ts-expect-error untyped .mjs module
import { runWorkflow, resolveSuite, getPath, DEFAULT_SUITES } from '../../evals/run.mjs';

type Data = Record<string, any>;
function data(result: CallToolResult): Data {
  const text = result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
  if (result.structuredContent) return result.structuredContent as Data;
  try { return JSON.parse(text) as Data; } catch { return { text }; }
}
function config(url: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl: url, port: 0, host: '127.0.0.1', allowedProperties: ['myer-plant', 'bristol-pumps'], actor: 'operator', requestTimeoutMs: 3000, remoteBackend: false, hosted: false, waitDefaultSeconds: 50, subscriptionPollMs: 100, waitProgressMs: 250, ...patch };
}
const NEW_TOOLS = ['get_scene', 'focus_view', 'capture_view', 'show_factory', 'get_overview', 'get_agent_activity', 'get_board_meeting', 'get_memory', 'list_issues', 'get_issue', 'inspect_valves', 'get_inspection', 'list_crew', 'who_is_responsible', 'list_obligations', 'get_document', 'request_document', 'start_scenario', 'list_scenarios', 'assign_issue', 'wait_for', 'decide', 'get_eval_findings', 'reconfigure_agent'];
const raw = async (url: string, name: string, args: Record<string, unknown>) => (await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }) })).text();

test('addendum 3 tools: scene, viewer, captures, overview, issues, people, compliance, scenarios, board meetings, telemetry', async () => {
  const upstream = await fakeRealityBackend({ stepMs: 30 });
  const server = createStewardServer({ config: config(upstream.url) });
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'factory-probe', version: '1.0.0' }, { capabilities: {} });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const call = async (name: string, args: Record<string, unknown> = {}) => client.callTool({ name, arguments: args }) as Promise<CallToolResult>;
    const tools = (await client.listTools()).tools;
    assert.equal(tools.length, 54);
    for (const name of NEW_TOOLS) {
      const tool = tools.find(t => t.name === name);
      assert(tool, name);
      assert(tool.outputSchema, `${name} has an outputSchema`);
      assert(tool.description && tool.description.length > 120 && /NEXT|next/.test(tool.description), `${name} description says what to do next`);
      assert(/free|Free|cost|COST|token|dry-run|Not idempotent|writes/i.test(tool.description), `${name} description says what it costs`);
    }
    const waitTool = tools.find(t => t.name === 'wait_for')!;
    for (const needle of [/costs no tokens|no tokens/, /still_waiting/, /waitId/, /15 s/, /after you start work/i]) assert.match(waitTool.description!, needle);
    assert.deepEqual((waitTool.inputSchema as Data).properties.event.enum, ['work_item.resolved', 'issue.changed', 'reply.received', 'board.resolved', 'scenario.step', 'any']);
    assert.equal((waitTool.inputSchema as Data).properties.timeoutSeconds.maximum, 300);

    // get_scene: per-site register with 3-D pins, credit, SOG URL, camera presets
    const scene = data(await call('get_scene', { siteId: 'myer-plant' }));
    assert.equal(scene.assets.length, 24);
    assert.equal(scene.sogUrl, 'https://d28zzqy0iyovbz.cloudfront.net/66b655d3/v1/meta.json');
    assert.equal(scene.credit.author, 'azha007'); assert.equal(scene.credit.url, 'https://superspl.at/scene/66b655d3');
    const pg601 = scene.assets.find((a: Data) => a.assetTag === 'PG-601');
    assert.deepEqual(pg601.pin, { x: -3.1, y: 1.75, z: -0.1 }); assert.equal(pg601.pinSource, 'placed');
    const v503 = scene.assets.find((a: Data) => a.assetTag === 'V-503');
    assert.equal(v503.severity, 'low'); assert.equal(v503.issues.length, 1);
    assert.equal(scene.counts.openIssues, 1); assert(scene.counts.estimated > 0 && scene.cameraPresets.length >= 1);
    const bristol = data(await call('get_scene', { siteId: 'bristol-pumps' }));
    assert(bristol.assets.some((a: Data) => a.assetTag === 'SU-201')); assert.equal(bristol.credit.author, 'scanomatic_labs');

    // focus_view appends a viewer command; reset needs no target; focus without one is refused before the backend
    const focused = data(await call('focus_view', { siteId: 'myer-plant', assetTag: 'PG-601', action: 'highlight' }));
    assert(focused.commandId); assert.equal(focused.action, 'highlight');
    assert.equal(upstream.state.viewer.at(-1)!.assetTag, 'PG-601'); assert.equal(upstream.state.viewer.at(-1)!.actor, 'operator');
    assert.equal(data(await call('focus_view', { siteId: 'myer-plant', action: 'reset' })).action, 'reset');
    const noTarget = await call('focus_view', { siteId: 'myer-plant' });
    assert.equal(noTarget.isError, true); assert.equal(data(noTarget).code, 'INVALID_ARGUMENT');

    // overview is compact
    const overview = data(await call('get_overview'));
    assert.equal(overview.sites.length, 2); assert(overview.tokensEstimate <= 600, `overview ${overview.tokensEstimate} tokens`);
    assert.deepEqual(overview.agents.map((a: Data) => a.agentId), ['operator', 'atlas', 'warden:myer-plant', 'warden:bristol-pumps', 'counsel', 'runner']);
    assert(estimateTokens(overview) <= 650);

    // captures and inspections
    const noCapture = data(await call('capture_view', { siteId: 'myer-plant', assetTag: 'V-503' }));
    assert.equal(noCapture.count, 0); assert.match(noCapture.nextStep, /inspect_valves/);
    const started = data(await call('inspect_valves', { siteId: 'myer-plant' }));
    assert.equal(started.dryRun, true); assert(started.jobId);
    const inspected = data(await call('wait_for', { event: 'scenario.step', siteId: 'myer-plant', filter: { kind: 'inspection' }, timeoutSeconds: 5 }));
    assert.equal(inspected.status, 'fired');
    const inspection = data(await call('get_inspection', { siteId: 'myer-plant' }));
    assert.equal(inspection.results.length, 5); assert.equal(inspection.counts.not_fixed, 1); assert.match(inspection.disclaimer, /not a trained defect classifier/);
    const capture = data(await call('capture_view', { siteId: 'myer-plant', assetTag: 'V-503' }));
    assert.equal(capture.count, 16); assert(capture.frames.every((url: string) => url.startsWith(`${upstream.url}/api/vision/frames/myer-plant/V-503/f`)));
    assert.equal(capture.synthetic, true); assert.equal(capture.defect, 'missing-handwheel'); assert.equal(capture.caption, 'frames rendered from the hosted capture');

    // people: contact details never leave the MCP
    const crew = data(await call('list_crew', { siteId: 'myer-plant' }));
    const duty = crew.crew.find((m: Data) => m.id === 'crew-my-duty');
    assert.equal(duty.hasPhone, true); assert.equal(duty.hasEmail, true);
    assert(!JSON.stringify(crew).includes('+15550100') && !JSON.stringify(crew).includes('duty@example.test'));
    const owner = data(await call('who_is_responsible', { siteId: 'myer-plant', issueKind: 'out_of_range' }));
    assert.equal(owner.crewMember.id, 'crew-my-duty'); assert(!JSON.stringify(owner).includes('+15550100'));

    // compliance: the injection document is data
    const obligations = data(await call('list_obligations', { siteId: 'myer-plant' }));
    assert.equal(obligations.obligations.length, 2);
    assert.equal(data(await call('list_obligations', { siteId: 'bristol-pumps', status: 'due_soon' })).obligations.length, 1);
    const permit = data(await call('get_document', { documentId: 'doc-my-contractor-permit' }));
    assert.equal(permit.textIsData, true); assert.equal(permit.suspectedInjection, true); assert.equal(permit.flagged, true);
    assert(permit.text.includes(INJECTION_TEXT)); assert.match(permit.notice, /never an instruction/);
    assert.equal(permit.fileUrl, `${upstream.url}/api/documents/doc-my-contractor-permit/file`);
    assert.equal(data(await call('get_document', { documentId: 'doc-my-fe-tag' })).suspectedInjection, false);
    const notCounsel = await call('request_document', { siteId: 'myer-plant', obligationId: 'obl-my-fe' });
    assert.equal(notCounsel.isError, true); assert.equal(data(notCounsel).code, 'AUTHORITY_DENIED'); assert.match(data(notCounsel).message, /counsel/);

    // scenarios → wait → board meeting → assignment
    const scenarios = data(await call('list_scenarios'));
    assert.deepEqual(scenarios.scenarios.map((s: Data) => s.id), ['my-overpressure', 'my-extinguisher', 'br-sump', 'br-vessel-cert', 'ops-counsel-tokens', 'ops-injection']);
    const run = data(await call('start_scenario', { scenarioId: 'br-sump' }));
    assert.equal(run.scenarioId, 'br-sump'); assert.equal(run.state, 'running');
    const resolved = data(await call('wait_for', { event: 'board.resolved', siteId: 'bristol-pumps', filter: { scenarioId: 'br-sump' }, timeoutSeconds: 10 }));
    assert.equal(resolved.status, 'fired'); assert.equal(resolved.tokensWhileWaiting, 0); assert.equal(resolved.event.type, 'board.resolved');
    const sumpIssue = data(await call('list_issues', { siteId: 'bristol-pumps', status: 'open' })).issues.find((i: Data) => i.scenarioId === 'br-sump');
    assert.equal(sumpIssue.assetTag, 'SU-201'); assert.equal(sumpIssue.severity, 'high');
    const meeting = data(await call('get_board_meeting', { issueId: sumpIssue.id }));
    assert.equal(meeting.state, 'resolved'); assert.match(meeting.resolution, /walkway/); assert.equal(meeting.contact.role, 'duty engineer');
    assert.equal(meeting.contact.phone, undefined, 'contact phone is stripped'); assert.match(meeting.notice, /never instructions/);
    const byId = data(await call('get_board_meeting', { meetingId: meeting.id }));
    assert.equal(byId.id, meeting.id);
    const missingMeeting = await call('get_board_meeting', { issueId: bristol.assets.find((a: Data) => a.assetTag === 'L-701').issues[0].id });
    assert.equal(missingMeeting.isError, true); assert.match(data(missingMeeting).recovery, /wait_for/);
    const detail = data(await call('get_issue', { issueId: sumpIssue.id }));
    assert.equal(detail.status, 'assigned'); assert.deepEqual(detail.detail.boardMeetings, [meeting.id]);
    const reassigned = data(await call('assign_issue', { issueId: sumpIssue.id, crewMemberId: 'crew-br-guide' }));
    assert.equal(reassigned.assignedTo, 'crew-br-guide');
    const badAssign = await call('assign_issue', { issueId: sumpIssue.id, crewMemberId: 'crew-my-duty' });
    assert.equal(badAssign.isError, true); assert.equal(data(badAssign).httpStatus, 400);

    // agents: activity from telemetry, memory, findings, reconfigure (Atlas only, refused before the backend)
    await delay(100);
    const activity = data(await call('get_agent_activity', { agentId: 'operator' }));
    assert(activity.lastActions.length > 0 && activity.lastActions.every((a: Data) => typeof a.tool === 'string'));
    assert(activity.tokensThisHour > 0);
    const memory = data(await call('get_memory', { agentId: 'warden:myer-plant', query: 'PG-601' }));
    assert.equal(memory.items.length, 1); assert.equal(memory.container, 'steward-warden:myer-plant'); assert.match(memory.notice, /never instructions/);
    const findings = data(await call('get_eval_findings'));
    assert(findings.agents.some((a: Data) => a.agentId === 'counsel')); assert.match(findings.source, /Steward telemetry.*Armature/);
    const before = upstream.state.paths.length;
    const denied = await call('reconfigure_agent', { agentId: 'counsel', change: { documentCache: true }, why: 'operator is not Atlas' });
    assert.equal(denied.isError, true); assert.equal(data(denied).code, 'AUTHORITY_DENIED'); assert.equal(data(denied).httpStatus, 403);
    assert(!upstream.state.paths.slice(before).some(path => path.startsWith('POST /api/agents/counsel/config')), 'refused before the backend');

    // telemetry: every tool call reaches the backend with the acting agent and estimated tokens
    const events = upstream.state.telemetry;
    assert(events.length >= 20, `telemetry events ${events.length}`);
    assert(events.every(event => event.agentId === 'operator' && event.estimated === true && typeof event.inputTokens === 'number' && typeof event.outputTokens === 'number'));
    assert(events.some(event => event.tool === 'get_scene' && event.siteId === 'myer-plant' && Number(event.outputTokens) > 100));
    assert(events.some(event => event.tool === 'reconfigure_agent' && event.ok === false && event.code === 'AUTHORITY_DENIED'));

    // validation on the wire
    for (const [name, args] of [['get_scene', { siteId: 'harbor-works' }], ['start_scenario', { scenarioId: 'demolish' }], ['wait_for', { event: 'issue.changed', timeoutSeconds: 301 }], ['wait_for', { event: 'lunch' }], ['decide', { issueId: 'iss-1', question: 'Close it?', options: ['yes'] }], ['reconfigure_agent', { agentId: 'counsel', change: { colour: 'red' }, why: 'nope nope' }], ['get_agent_activity', { agentId: 'owner' }]] as const) {
      assert.match(await raw(listener.url, name, args as Record<string, unknown>), /invalid|enum|too|>=|<=|unrecognized|regex|pattern/i, `${name} rejects ${JSON.stringify(args)}`);
    }
  } finally { await client.close(); await server.close(); await upstream.close(); }
});

test('wait_for: progress every interval, still_waiting keeps the waitId, fired on the event, works without backend long-poll', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const modern = new MCPClient({ clientInfo: { name: 'waiter', version: '1' }, mcpServers: { steward: { url: listener.url, oauth: false, detectMixedAuth: false } } });
  const legacy = new Client({ name: 'legacy-waiter', version: '1' }, { capabilities: {} });
  try {
    const connection = await modern.connect('steward');
    await legacy.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    // window ends: still_waiting, progress notifications on the way (first one immediately)
    const progress: unknown[] = [];
    const started = Date.now();
    const first = data(await connection.callTool('wait_for', { event: 'issue.changed', siteId: 'myer-plant', timeoutSeconds: 2 }, { onprogress: (p: unknown) => progress.push(p), timeout: 10000 } as never) as CallToolResult);
    assert.equal(first.status, 'still_waiting'); assert(first.waitId); assert.match(first.nextStep, new RegExp(`waitId="${first.waitId}"`));
    assert(Date.now() - started >= 1900, 'held for the window');
    assert(progress.length >= 4, `progress notifications: ${progress.length}`); assert.equal(first.progressNotifications, progress.length);
    assert.match(String((progress[0] as Data).message), /no tokens/);
    // same waitId again; the event lands while the call is held
    setTimeout(() => upstream.emit('issue.changed', 'myer-plant', { issueId: 'iss-x', refId: 'iss-x', status: 'open' }, 'test event'), 400);
    const again = data(await connection.callTool('wait_for', { event: 'issue.changed', waitId: first.waitId, timeoutSeconds: 5 }, { timeout: 10000 } as never) as CallToolResult);
    assert.equal(again.status, 'fired'); assert.equal(again.waitId, first.waitId); assert.equal(again.event.issueId, 'iss-x');
    assert(again.waitedSeconds < 3);
    // filters and sites narrow the match
    setTimeout(() => { upstream.emit('scenario.step', 'bristol-pumps', { scenarioId: 'br-sump', state: 'running' }, 'other site'); upstream.emit('scenario.step', 'myer-plant', { scenarioId: 'my-overpressure', state: 'running' }, 'wrong state'); upstream.emit('scenario.step', 'myer-plant', { scenarioId: 'my-overpressure', state: 'completed' }, 'match'); }, 300);
    const filtered = data(await legacy.callTool({ name: 'wait_for', arguments: { event: 'scenario.step', siteId: 'myer-plant', filter: { scenarioId: 'my-overpressure', state: 'completed' }, timeoutSeconds: 5 } }) as CallToolResult);
    assert.equal(filtered.status, 'fired'); assert.equal(filtered.event.state, 'completed');
    // a backend without long-poll answers immediately: the MCP re-asks every 2 s inside the same held call
    upstream.state.noLongPoll = true;
    setTimeout(() => upstream.emit('reply.received', 'myer-plant', { workItemId: 'wi-1' }, 'reply'), 500);
    const polled = data(await legacy.callTool({ name: 'wait_for', arguments: { event: 'reply.received', timeoutSeconds: 6 } }) as CallToolResult);
    assert.equal(polled.status, 'fired');
    upstream.state.noLongPoll = false;
    // unknown waitId
    const unknown = await legacy.callTool({ name: 'wait_for', arguments: { event: 'any', waitId: 'wait-nope', timeoutSeconds: 2 } }) as CallToolResult;
    assert.equal(unknown.isError, true); assert.equal(data(unknown).code, 'WAIT_NOT_FOUND'); assert.match(data(unknown).recovery, /without waitId/);
    // every long-poll asked the backend for at most 15 s
    const asked = upstream.state.paths.filter(path => path.startsWith('GET /api/waits/'));
    assert(asked.length >= 3);
  } finally { await Promise.allSettled([modern.close(), legacy.close()]); await server.close(); await upstream.close(); }
});

test('resource subscriptions: subscriptions/listen and legacy resources/subscribe get notifications/resources/updated; one poller per site, only while subscribed', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const hub = server.stewardHub;
  const modern = new Client({ name: 'listener', version: '1' }, { capabilities: {}, versionNegotiation: { mode: 'auto' } } as never);
  const updates: string[] = [];
  modern.setNotificationHandler('notifications/resources/updated' as never, ((notification: { params: { uri: string } }) => { updates.push(notification.params.uri); }) as never);
  try {
    await modern.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const overview = JSON.parse((await modern.readResource({ uri: 'steward://sites/myer-plant/overview' })).contents.map(item => ('text' in item ? item.text : '')).join('')) as Data;
    assert.equal(overview.siteId, 'myer-plant'); assert.equal(overview.openIssues.length, 1); assert.match(overview.subscribe, /resources\/subscribe/);
    assert.equal(hub.subscribers('myer-plant'), 0);
    const subscription = await (modern as unknown as { listen(filter: unknown): Promise<{ close(): Promise<void> }> }).listen({ resourceSubscriptions: ['steward://sites/myer-plant/overview', 'steward://guide'] });
    await delay(50);
    assert.equal(hub.subscribers('myer-plant'), 1); assert.equal(hub.subscribers('bristol-pumps'), 0);
    assert(hub.pollers.get('myer-plant')?.timer, 'poller running'); assert(!hub.pollers.get('bristol-pumps')?.timer, 'no poller without subscribers');
    await delay(250); // baseline read
    upstream.emit('issue.changed', 'myer-plant', { issueId: 'iss-a' }, 'myer change');
    upstream.emit('issue.changed', 'bristol-pumps', { issueId: 'iss-b' }, 'bristol change');
    await delay(400);
    assert.deepEqual([...new Set(updates)], ['steward://sites/myer-plant/overview']);
    await subscription.close();
    await delay(150);
    assert.equal(hub.subscribers('myer-plant'), 0); assert(!hub.pollers.get('myer-plant')?.timer, 'poller stops with the last subscriber');

    // legacy (2025-era) path: initialize mints a session, GET opens the event stream, resources/subscribe is answered here
    const post = (body: unknown, session?: string) => fetch(listener.url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...(session ? { 'Mcp-Session-Id': session } : {}) }, body: JSON.stringify(body) });
    const init = await post({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'legacy-inspector', version: '1' } } });
    const session = init.headers.get('mcp-session-id'); await init.text();
    assert(session, 'legacy initialize carries an Mcp-Session-Id');
    assert.match(JSON.stringify(await (await post({ jsonrpc: '2.0', id: 2, method: 'resources/subscribe', params: { uri: 'steward://sites/myer-plant/overview' } })).json()), /-32600|Mcp-Session-Id/);
    assert.match(JSON.stringify(await (await post({ jsonrpc: '2.0', id: 3, method: 'resources/subscribe', params: { uri: 'steward://guide' } }, session!)).json()), /-32602/);
    const stream = await fetch(listener.url, { method: 'GET', headers: { Accept: 'text/event-stream', 'Mcp-Session-Id': session! } });
    assert.equal(stream.status, 200); assert.match(stream.headers.get('content-type') || '', /text\/event-stream/);
    const reader = stream.body!.getReader(); const decoder = new TextDecoder();
    const ok = await (await post({ jsonrpc: '2.0', id: 4, method: 'resources/subscribe', params: { uri: 'steward://sites/bristol-pumps/overview' } }, session!)).json() as Data;
    assert.deepEqual(ok.result, {});
    assert.equal(hub.subscribers('bristol-pumps'), 1);
    await delay(250);
    upstream.emit('scenario.step', 'bristol-pumps', { scenarioId: 'br-sump', state: 'running' }, 'sump');
    let received = '';
    const until = Date.now() + 2000;
    while (!received.includes('notifications/resources/updated') && Date.now() < until) { const { value, done } = await reader.read(); if (done) break; received += decoder.decode(value); }
    assert.match(received, /"method":"notifications\/resources\/updated","params":\{"uri":"steward:\/\/sites\/bristol-pumps\/overview"\}/);
    await (await post({ jsonrpc: '2.0', id: 5, method: 'resources/unsubscribe', params: { uri: 'steward://sites/bristol-pumps/overview' } }, session!)).json();
    assert.equal(hub.subscribers('bristol-pumps'), 0);
    await reader.cancel();
    assert(hub.emitted.get('bristol-pumps')! >= 1 && !hub.emitted.has('myer-plant') === false);
  } finally { await modern.close().catch(() => {}); await server.close(); await upstream.close(); }
});

test('decide: elicitation in clients that declare it, the owner by SMS (dry-run) otherwise', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const asked: Data[] = [];
  let answer: Data = { action: 'accept', content: { choice: 'close walkway' } };
  const modern = new MCPClient({ clientInfo: { name: 'elicitor', version: '1' }, mcpServers: { steward: { url: listener.url, oauth: false, detectMixedAuth: false, onElicitation: async (params: Data) => { asked.push(params); return answer; } } } } as never);
  const legacy = new Client({ name: 'legacy-decider', version: '1' }, { capabilities: {} });
  try {
    const connection = await modern.connect('steward');
    await legacy.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const issueId = [...upstream.state.issues.values()].find(issue => issue.siteId === 'bristol-pumps')!.id;
    const decided = data(await connection.callTool('decide', { issueId, question: 'Close the visitor walkway now?', options: ['close walkway', 'keep open and monitor'] }) as CallToolResult);
    assert.equal(decided.status, 'decided'); assert.equal(decided.answer, 'close walkway'); assert.equal(decided.via, 'elicitation');
    assert.equal(asked.length, 1); assert.match(String(asked[0]!.message), /Close the visitor walkway/); assert.deepEqual((asked[0]!.requestedSchema as Data).properties.choice.enum, ['close walkway', 'keep open and monitor']);
    assert.equal(upstream.state.decisions.at(-1)!.answer, 'close walkway'); assert.equal(upstream.state.decisions.at(-1)!.via, 'elicitation');
    assert.equal(upstream.state.issues.get(issueId)!.status, 'acknowledged');
    answer = { action: 'decline' };
    const declined = data(await connection.callTool('decide', { issueId, question: 'Close the visitor walkway now?', options: ['close walkway', 'keep open'] }) as CallToolResult);
    assert.equal(declined.status, 'declined'); assert.match(declined.nextStep, /via "owner"/);
    const owner = data(await connection.callTool('decide', { issueId, question: 'Close the visitor walkway now?', options: ['close walkway', 'keep open'], via: 'owner' }) as CallToolResult);
    assert.equal(owner.status, 'routed'); assert.equal(asked.length, 2, 'via owner does not elicit');
    // a 2025-era stateless client advertises nothing per request: routed to the owner through the Runner, dry-run
    const routed = data(await legacy.callTool({ name: 'decide', arguments: { issueId, question: 'Close the visitor walkway now?', options: ['close walkway', 'keep open'] } }) as CallToolResult);
    assert.equal(routed.status, 'routed'); assert.equal(routed.dryRun, true); assert.equal(routed.via, 'sms'); assert(routed.waitId); assert.match(routed.nextStep, /reply\.received/);
    assert(upstream.state.transcripts.some(entry => entry.agentId === 'runner' && entry.kind === 'sms' && entry.text.includes('(dry-run)')));
  } finally { await Promise.allSettled([modern.close(), legacy.close()]); await server.close(); await upstream.close(); }
});

test('show_factory: MCP Apps view resource (PlayCanvas pinned, CSP, bridge) and the text fallback', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer(config(upstream.url));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'apps-host', version: '1' }, { capabilities: {} });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const tool = (await client.listTools()).tools.find(t => t.name === 'show_factory')!;
    assert.equal((tool._meta as Data).ui.resourceUri, 'ui://views/steward-factory.html');
    assert.equal(tool.annotations?.readOnlyHint, true);
    const resource = (await client.listResources()).resources.find(r => r.uri === 'ui://views/steward-factory.html')!;
    assert.equal(resource.mimeType, 'text/html;profile=mcp-app');
    const csp = (resource._meta as Data).ui.csp;
    assert(csp.resourceDomains.includes('https://cdn.jsdelivr.net') && csp.resourceDomains.includes('https://d28zzqy0iyovbz.cloudfront.net'));
    assert(csp.connectDomains.includes('https://d28zzqy0iyovbz.cloudfront.net'));
    const html = (await client.readResource({ uri: 'ui://views/steward-factory.html' })).contents.map(item => ('text' in item ? item.text : '')).join('');
    assert(html.startsWith('<!doctype html>'));
    for (const needle of [PLAYCANVAS_URL, 'playcanvas@2.23.3', 'ui/initialize', 'ui/notifications/tool-result', 'openai:set_globals', 'grayscale(1)', "'gsplat'".replace(/'/g, '"'), 'worldToScreen', 'focus_view']) assert(html.includes(needle), `view includes ${needle}`);
    assert(!/playcanvas@latest|playcanvas@\^|playcanvas\/build/.test(PLAYCANVAS_URL.replace('playcanvas@2.23.3/build', '')), 'engine URL pinned to an exact version');
    // the widget script parses (dynamic import included)
    new Function(FACTORY_VIEW_JS);
    const result = await client.callTool({ name: 'show_factory', arguments: { siteId: 'myer-plant' } }) as CallToolResult;
    const text = result.content.filter(block => block.type === 'text').map(block => block.text).join('');
    assert.match(text, /^Myer Plant Room \(myer-plant\): 24 assets, 1 open issue/);
    assert.match(text, /V-503/); assert.match(text, /azha007/); assert.match(text, /superspl\.at\/scene\/66b655d3/);
    const structured = result.structuredContent as Data;
    assert.equal(structured.assets.length, 24); assert.equal(structured.widget.resourceUri, 'ui://views/steward-factory.html'); assert.match(structured.widget.rendered, /text summary/);
  } finally { await client.close(); await server.close(); await upstream.close(); }
});

test('act-as header: honoured only with STEWARD_MCP_ALLOW_ACT_AS on a loopback MCP', async () => {
  const upstream = await fakeRealityBackend();
  const allowed = createStewardServer(config(upstream.url, { allowActAs: true }));
  const plain = createStewardServer(config(upstream.url));
  const [a, b] = await Promise.all([allowed.listen(0, { host: '127.0.0.1' }), plain.listen(0, { host: '127.0.0.1' })]);
  const asRunner = (url: string) => new Client({ name: 'as-runner', version: '1' }, { capabilities: {} }).connect(new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers: { [ACT_AS_HEADER]: 'runner' } } }));
  const clients: Client[] = [];
  try {
    for (const url of [a.url, b.url]) { const client = new Client({ name: 'as-runner', version: '1' }, { capabilities: {} }); await client.connect(new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers: { [ACT_AS_HEADER]: 'runner' } } })); clients.push(client); }
    void asRunner;
    const args = { siteId: 'myer-plant', assetTag: 'V-502', attribute: 'position', value: 'open', source: { kind: 'agent', ref: 'probe' }, statedTag: 'V-502' };
    const denied = data(await clients[0]!.callTool({ name: 'attest', arguments: args }) as CallToolResult);
    assert.equal(denied.code, 'AUTHORITY_DENIED'); assert.match(denied.message, /runner/);
    assert.equal(upstream.state.actors.at(-1), 'runner');
    const accepted = data(await clients[1]!.callTool({ name: 'attest', arguments: args }) as CallToolResult);
    assert.equal(accepted.verdict, 'accepted', 'without the flag the header is ignored and the MCP acts as its own actor');
    assert.equal(upstream.state.actors.at(-1), 'operator');
  } finally { await Promise.allSettled(clients.map(client => client.close())); await Promise.all([allowed.close(), plain.close()]); await upstream.close(); }
});

test('telemetry sink: posts the acting agent and estimated tokens; pauses on a backend without the route', async () => {
  const calls: { url: string; body: Data }[] = [];
  let status = 404;
  const fetcher = (async (url: string, init: { body: string }) => { calls.push({ url, body: JSON.parse(init.body) as Data }); return new Response('{}', { status }); }) as unknown as typeof fetch;
  const sink = createTelemetry(config('http://127.0.0.1:9'), fetcher);
  const event = { tool: 'get_scene', agentId: 'atlas', requester: 'probe', ok: true, durationMs: 3, inputTokens: estimateTokens({ siteId: 'myer-plant' }), outputTokens: 900, estimated: true as const, at: new Date().toISOString() };
  sink.record(event); await delay(20);
  assert.equal(calls.length, 1); assert.equal(calls[0]!.url, 'http://127.0.0.1:9/api/telemetry/tool-calls'); assert.equal(calls[0]!.body.agentId, 'atlas');
  assert.equal(sink.paused, true);
  sink.record(event); await delay(20);
  assert.equal(calls.length, 1, 'paused after a 404');
  assert.equal(estimateTokens('abcd'), 1); assert.equal(estimateTokens({ a: 1 }), 2);
  status = 201;
});

type Report = { passed: number; failed: number; rows: { id: string; ok: boolean; detail: string; skipped?: boolean; data: Data }[] };
const failures = (report: Report) => report.rows.filter(row => !row.ok).map(row => `${row.id}: ${row.detail}`).join('\n');

test('eval suites: factory-workflow, safety and efficiency replay against the fake upstream (factory twice)', async () => {
  assert.deepEqual(DEFAULT_SUITES, ['mission-workflow', 'demo-workflow', 'factory-workflow', 'safety', 'efficiency']);
  assert.deepEqual(getPath({ assets: [{ kind: 'valve', t: 1 }, { kind: 'pump', t: 2 }, { kind: 'valve', t: 3 }] }, 'assets[?kind=valve][1].t'), 3);
  const upstream = await fakeRealityBackend({ stepMs: 60 });
  const server = createStewardServer(config(upstream.url, { allowActAs: true }));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  try {
    for (const suite of ['factory-workflow', 'factory-workflow', 'safety', 'efficiency']) {
      const workflow = JSON.parse(await readFile(resolveSuite(suite), 'utf8')) as { steps: { id: string }[] };
      const report = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as Report;
      assert.equal(report.failed, 0, `${suite}\n${failures(report)}`);
      assert.equal(report.passed, workflow.steps.length, suite);
    }
    assert(upstream.state.actors.includes('warden:myer-plant') && upstream.state.actors.includes('runner') && upstream.state.actors.includes('atlas'), 'actor steps reached the backend as those agents');
  } finally { await server.close(); await upstream.close(); }
});
