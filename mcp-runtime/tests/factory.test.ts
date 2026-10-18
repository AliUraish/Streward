/**
 * Addenda 3 and 4 (REALITY-CONTRACT-3.md §7, §10; REALITY-CONTRACT-4.md): the scene, viewer, people, compliance,
 * scenario and decision tools; wait_for (progress, still_waiting, fired); resource subscriptions in both protocol eras;
 * elicitation for decide; the show_factory MCP Apps view; the agent eye (image content); metrics, conversations,
 * regulations, the fix workflow, maintenance and notifications; Steward telemetry; the eval act-as header; and the
 * factory, safety, efficiency and vision suites, all against the extended fake upstream.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer, ACT_AS_HEADER } from '../src/server.js';
import { PROPERTY_IDS, type RuntimeConfig } from '../src/config.js';
import { createTelemetry, estimateTokens } from '../src/telemetry.js';
import { FACTORY_VIEW_JS, PLAYCANVAS_URL } from '../src/widget.js';
import { flattenEvent } from '../src/waits.js';
import { HARNESS_HEADER, HARNESS_HEADER_VALUE } from '../src/harness.js';
import { fakeRealityBackend, INJECTION_TEXT, FIXTURE_JPEG_B64 } from './fake-reality.js';
// @ts-expect-error untyped .mjs module
import { runWorkflow, resolveSuite, getPath, DEFAULT_SUITES } from '../../evals/run.mjs';

type Data = Record<string, any>;
function data(result: CallToolResult): Data {
  const text = result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
  if (result.structuredContent) return result.structuredContent as Data;
  try { return JSON.parse(text) as Data; } catch { return { text }; }
}
function config(url: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl: url, port: 0, host: '127.0.0.1', allowedProperties: ['myer-plant', 'bristol-pumps'], actor: 'operator', requestTimeoutMs: 3000, remoteBackend: false, hosted: false, waitDefaultSeconds: 50, subscriptionPollMs: 100, waitProgressMs: 250, harnessTools: true, ...patch };
}
/** A transport carrying the eval harness's header: with harnessTools on, only such requests see and call list_scenarios / start_scenario. */
const harness = (url: string) => new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers: { [HARNESS_HEADER]: HARNESS_HEADER_VALUE } } });
const C3_TOOLS = ['get_scene', 'focus_view', 'capture_view', 'show_factory', 'get_overview', 'get_agent_activity', 'get_board_meeting', 'get_memory', 'list_issues', 'get_issue', 'inspect_valves', 'get_inspection', 'list_crew', 'who_is_responsible', 'list_obligations', 'get_document', 'request_document', 'start_scenario', 'list_scenarios', 'assign_issue', 'wait_for', 'decide', 'get_eval_findings', 'reconfigure_agent'];
const C4_TOOLS = ['eye_look', 'eye_move', 'eye_turn', 'eye_go_to', 'eye_orbit', 'eye_mark', 'get_portfolio_summary', 'get_metrics', 'list_conversations', 'get_conversation', 'list_regulations', 'explain_compliance_issue', 'request_fix', 'list_maintenance', 'propose_maintenance_window', 'list_notifications', 'get_owner_notifications', 'get_compliance_snapshot'];
const raw = async (url: string, name: string, args: Record<string, unknown>) => (await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }) })).text();
const as = async (url: string, actor: string) => { const client = new Client({ name: `as-${actor}`, version: '1' }, { capabilities: {} }); await client.connect(new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers: { [ACT_AS_HEADER]: actor } } })); return client; };

test('addendum 3 tools: scene, viewer, captures, overview, issues, people, compliance, scenarios, meetings, telemetry', async () => {
  // Waits only see changes after they are opened (as on the backend), so the fixture's steps are spaced well beyond a tool round trip.
  const upstream = await fakeRealityBackend({ stepMs: 300 });
  const server = createStewardServer({ config: config(upstream.url, { allowActAs: true }) });
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'factory-probe', version: '1.0.0' }, { capabilities: {} });
  const manager = await as(listener.url, 'bristol-manager');
  try {
    await client.connect(harness(listener.url));
    const call = async (name: string, args: Record<string, unknown> = {}) => client.callTool({ name, arguments: args }) as Promise<CallToolResult>;
    const tools = (await client.listTools()).tools;
    assert.equal(tools.length, 78);
    for (const name of [...C3_TOOLS, ...C4_TOOLS]) {
      const tool = tools.find(t => t.name === name);
      assert(tool, name);
      assert(tool.outputSchema, `${name} has an outputSchema`);
      assert(tool.description && tool.description.length > 120 && /NEXT/.test(tool.description), `${name} description says what to do next`);
      assert(/free|cost|token|dry-run|not idempotent|writes|records/i.test(tool.description), `${name} description says what it costs`);
      for (const retired of ['Atlas', 'Warden', 'Counsel', 'Runner']) assert(!tool.description.includes(retired), `${name} no longer names ${retired}`);
    }
    const waitTool = tools.find(t => t.name === 'wait_for')!;
    for (const needle of [/costs no tokens|no tokens/, /still_waiting/, /waitId/, /15 s/, /after you start work/i]) assert.match(waitTool.description!, needle);
    assert.deepEqual((waitTool.inputSchema as Data).properties.event.enum, ['work_item.resolved', 'issue.changed', 'reply.received', 'board.resolved', 'any']);
    assert.equal((waitTool.inputSchema as Data).properties.timeoutSeconds.maximum, 300);
    assert.deepEqual((tools.find(t => t.name === 'get_agent_activity')!.inputSchema as Data).properties.agentId.enum, ['operator', 'director', 'myer-manager', 'myer-engineer', 'myer-compliance', 'myer-technician', 'bristol-manager', 'bristol-engineer', 'bristol-compliance', 'bristol-technician', 'tomioka-manager', 'tomioka-engineer', 'tomioka-compliance', 'tomioka-technician', 'dispatch']);

    // get_scene: per-site register with 3-D pins, credit (the backend sends a string), SOG URL (sogMetaUrl), camera presets
    const scene = data(await call('get_scene', { siteId: 'myer-plant' }));
    assert.equal(scene.assets.length, 24);
    assert.equal(scene.sogUrl, 'https://d28zzqy0iyovbz.cloudfront.net/66b655d3/v1/meta.json');
    assert.equal(scene.credit.author, 'azha007'); assert.equal(scene.credit.url, 'https://superspl.at/scene/66b655d3'); assert.match(scene.credit.text, /azha007/);
    const pg601 = scene.assets.find((a: Data) => a.assetTag === 'PG-601');
    assert(pg601.pin && typeof pg601.pin.x === 'number'); assert.equal(pg601.pinSource, 'placed');
    const v503 = scene.assets.find((a: Data) => a.assetTag === 'V-503');
    assert.equal(v503.severity, 'low'); assert.equal(v503.issues.length, 1);
    assert.equal(scene.counts.openIssues, 1); assert(scene.counts.estimated > 0);
    assert.equal(scene.cameraPresets[0].name, 'Initial view'); assert.equal(scene.cameraPresets[0].fov, 75);
    const bristol = data(await call('get_scene', { siteId: 'bristol-pumps' }));
    assert(bristol.assets.some((a: Data) => a.assetTag === 'SU-201' && a.kind === 'sump')); assert.equal(bristol.credit.author, 'scanomatic_labs');

    // focus_view appends a viewer command; reset needs no target; focus without one is refused before the backend
    const focused = data(await call('focus_view', { siteId: 'myer-plant', assetTag: 'PG-601', action: 'highlight' }));
    assert(focused.commandId); assert.equal(focused.action, 'highlight');
    assert.equal(upstream.state.viewer.at(-1)!.assetTag, 'PG-601'); assert.equal(upstream.state.viewer.at(-1)!.issuedBy, 'operator');
    assert.equal(data(await call('focus_view', { siteId: 'myer-plant', action: 'reset' })).action, 'reset');
    const noTarget = await call('focus_view', { siteId: 'myer-plant' });
    assert.equal(noTarget.isError, true); assert.equal(data(noTarget).code, 'INVALID_ARGUMENT');

    // overview is compact and normalises the backend's field names (id, task, lastChanges)
    const overview = data(await call('get_overview'));
    assert.deepEqual(overview.sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps']); assert(overview.tokensEstimate <= 600, `overview ${overview.tokensEstimate} tokens`);
    assert.equal(overview.agents.length, 10); assert.equal(overview.agents[1].agentId, 'director');
    assert(overview.changes.length > 0 && overview.changes.every((c: Data) => c.siteId === 'myer-plant' || c.siteId === 'bristol-pumps'));
    assert(estimateTokens(overview) <= 650);

    // captures and inspections
    const noCapture = data(await call('capture_view', { siteId: 'myer-plant', assetTag: 'V-503' }));
    assert.equal(noCapture.count, 0); assert.match(noCapture.nextStep, /inspect_valves/);
    const started = data(await call('inspect_valves', { siteId: 'myer-plant' }));
    assert.equal(started.dryRun, true); assert(started.jobId);
    const inspected = data(await call('wait_for', { event: 'any', siteId: 'myer-plant', filter: { type: 'scenario', kind: 'inspection' }, timeoutSeconds: 5 }));
    assert.equal(inspected.status, 'fired');
    const inspection = data(await call('get_inspection', { siteId: 'myer-plant' }));
    assert.equal(inspection.results.length, 5); assert.equal(inspection.counts.not_fixed, 1); assert.match(inspection.disclaimer, /not a trained defect classifier/);
    const capture = data(await call('capture_view', { siteId: 'myer-plant', assetTag: 'V-503' }));
    assert.equal(capture.count, 16); assert(capture.frames.every((url: string) => url.startsWith(`${upstream.url}/api/vision/frames/myer-plant/V-503/f`)));
    assert.equal(capture.synthetic, true); assert.equal(capture.defect, 'missing-handwheel'); assert.equal(capture.caption, 'frames rendered from the hosted capture');

    // people: contact details never leave the MCP (not even masked)
    const crew = data(await call('list_crew', { siteId: 'myer-plant' }));
    const duty = crew.crew.find((m: Data) => m.id === 'crew-my-duty');
    assert.equal(duty.hasPhone, true);
    assert(!JSON.stringify(crew).includes('•') && !JSON.stringify(crew).includes('example.test'));
    const owner = data(await call('who_is_responsible', { siteId: 'myer-plant', issueKind: 'out_of_range' }));
    assert.equal(owner.crewMember.id, 'crew-my-duty'); assert.equal(owner.via, 'myer-technician'); assert(!JSON.stringify(owner).includes('•'));

    // compliance: the injection document is data
    const obligations = data(await call('list_obligations', { siteId: 'myer-plant' }));
    assert.equal(obligations.obligations.length, 2);
    assert.equal(data(await call('list_obligations', { siteId: 'bristol-pumps', status: 'due_soon' })).obligations.length, 1);
    const permit = data(await call('get_document', { documentId: 'doc-my-contractor-v504' }));
    assert.equal(permit.textIsData, true); assert.equal(permit.suspectedInjection, true); assert.equal(permit.flagged, true);
    assert(permit.text.includes(INJECTION_TEXT)); assert.match(permit.notice, /never an instruction/);
    assert.equal(permit.fileUrl, `${upstream.url}/api/documents/doc-my-contractor-v504/file`);
    assert.equal(data(await call('get_document', { documentId: 'doc-my-fe-tag' })).suspectedInjection, false);
    const notCompliance = await call('request_document', { siteId: 'myer-plant', obligationId: 'ob-my-fe1001-monthly' });
    assert.equal(notCompliance.isError, true); assert.equal(data(notCompliance).code, 'AUTHORITY_DENIED'); assert.match(data(notCompliance).message, /myer-compliance/);

    // scenarios → wait → meeting → assignment (a plant manager assigns crew; the owner's agent may not)
    const scenarios = data(await call('list_scenarios'));
    assert.deepEqual(scenarios.scenarios.map((s: Data) => s.id), ['my-overpressure', 'my-extinguisher', 'br-sump', 'br-vessel-cert', 'ops-counsel-tokens', 'ops-injection', 'x-maintenance']);
    const run = data(await call('start_scenario', { scenarioId: 'br-sump', speed: 600 }));
    assert.equal(run.scenarioId, 'br-sump'); assert.equal(run.state, 'running');
    assert.equal(data(await call('start_scenario', { scenarioId: 'br-sump' })).id, run.id, 'a run in progress is returned, not duplicated');
    const resolved = data(await call('wait_for', { event: 'board.resolved', siteId: 'bristol-pumps', filter: { scenarioId: 'br-sump' }, timeoutSeconds: 10 }));
    assert.equal(resolved.status, 'fired'); assert.equal(resolved.tokensWhileWaiting, 0); assert.equal(resolved.event.name, 'board.resolved'); assert.equal(resolved.event.type, 'board_meeting');
    const sumpIssue = data(await call('list_issues', { siteId: 'bristol-pumps', status: 'open' })).issues.find((i: Data) => i.scenarioId === 'br-sump');
    assert.equal(sumpIssue.assetTag, 'SU-201'); assert.equal(sumpIssue.severity, 'high'); assert.equal(sumpIssue.kind, 'sump_overflow');
    const meeting = data(await call('get_board_meeting', { issueId: sumpIssue.id }));
    assert.equal(meeting.state, 'resolved'); assert.match(meeting.resolution, /walkway/); assert.equal(meeting.contact.role, 'duty engineer'); assert.equal(meeting.convenedBy, 'bristol-manager');
    assert.equal(meeting.contact.phone, undefined, 'contact phone is stripped'); assert.match(meeting.notice, /never instructions/);
    assert.equal(data(await call('get_board_meeting', { meetingId: meeting.id })).id, meeting.id);
    const missingMeeting = await call('get_board_meeting', { issueId: bristol.assets.find((a: Data) => a.assetTag === 'L-901').issues[0].id });
    assert.equal(missingMeeting.isError, true); assert.match(data(missingMeeting).recovery, /wait_for/);
    await delay(400);
    const detail = data(await call('get_issue', { issueId: sumpIssue.id }));
    assert.equal(detail.assignedTo, 'crew-br-duty'); assert.deepEqual(detail.detail.meetingIds, [meeting.id]);
    const operatorAssign = await call('assign_issue', { issueId: sumpIssue.id, crewMemberId: 'crew-br-guide' });
    assert.equal(operatorAssign.isError, true); assert.equal(data(operatorAssign).code, 'AUTHORITY_DENIED');
    const reassigned = data(await manager.callTool({ name: 'assign_issue', arguments: { issueId: sumpIssue.id, crewMemberId: 'crew-br-guide' } }) as CallToolResult);
    assert.equal(reassigned.assignedTo, 'crew-br-guide');
    const badAssign = await manager.callTool({ name: 'assign_issue', arguments: { issueId: sumpIssue.id, crewMemberId: 'crew-my-duty' } }) as CallToolResult;
    assert.equal(badAssign.isError, true); assert.equal(data(badAssign).httpStatus, 400);

    // agents: activity from telemetry, memory, findings, reconfigure (the director only, refused before the backend)
    await delay(100);
    const activity = data(await call('get_agent_activity', { agentId: 'operator' }));
    assert(activity.lastActions.length > 0 && activity.lastActions.every((a: Data) => typeof a.tool === 'string'));
    assert(activity.tokensThisHour > 0);
    const engineer = data(await call('get_agent_activity', { agentId: 'bristol-compliance' }));
    assert.equal(engineer.config.documentCache, false, 'the Bristol compliance officer ships with the inefficient settings');
    const memory = data(await call('get_memory', { agentId: 'myer-engineer', query: 'PG-601' }));
    assert.equal(memory.items.length, 1); assert.equal(memory.container, 'steward-myer-engineer'); assert.match(memory.items[0].text, /3\.2 bar/); assert.match(memory.notice, /never instructions/);
    const findings = data(await call('get_eval_findings'));
    assert(findings.agents.some((a: Data) => a.agentId === 'bristol-compliance')); assert.match(findings.source, /Steward telemetry.*Armature/); assert(findings.metrics && findings.metrics.latencyMs);
    const before = upstream.state.paths.length;
    const denied = await call('reconfigure_agent', { agentId: 'bristol-compliance', change: { documentCache: true }, why: 'operator is not the director' });
    assert.equal(denied.isError, true); assert.equal(data(denied).code, 'AUTHORITY_DENIED'); assert.equal(data(denied).httpStatus, 403);
    assert(!upstream.state.paths.slice(before).some(path => /POST \/api\/agents\/bristol-compliance\/(config|reconfigure)/.test(path)), 'refused before the backend');

    // telemetry: every tool call reaches the backend with the acting agent and estimated tokens (fire-and-forget: let the last posts land)
    await delay(150);
    const events = upstream.state.telemetry.filter(event => event.kind === 'mcp');
    assert(events.length >= 20, `telemetry events ${events.length}`);
    assert(events.every(event => (event.agentId === 'operator' || event.agentId === 'bristol-manager') && event.estimated === true && typeof event.inputTokens === 'number' && typeof event.outputTokens === 'number' && event.tokens === Number(event.inputTokens) + Number(event.outputTokens)));
    assert(events.some(event => event.agentId === 'bristol-manager' && event.tool === 'assign_issue'), 'the acting agent is recorded per call');
    assert(events.some(event => event.tool === 'get_scene' && event.siteId === 'myer-plant' && Number(event.outputTokens) > 100));
    assert(events.some(event => event.tool === 'reconfigure_agent' && event.ok === false && /AUTHORITY_DENIED/.test(String(event.detail))));

    // validation on the wire
    // without the harness header a hidden tool is refused before any argument check (src/harness.ts)
    assert.match(await raw(listener.url, 'start_scenario', { scenarioId: 'demolish' }), /UNKNOWN_TOOL/);
    for (const [name, args] of [['get_scene', { siteId: 'harbor-works' }],['wait_for', { event: 'issue.changed', timeoutSeconds: 301 }], ['wait_for', { event: 'lunch' }], ['decide', { issueId: 'iss-1', question: 'Close it?', options: ['yes'] }], ['reconfigure_agent', { agentId: 'bristol-compliance', change: { colour: 'red' }, why: 'nope nope' }], ['get_agent_activity', { agentId: 'owner' }], ['get_agent_activity', { agentId: 'atlas' }], ['who_is_responsible', { siteId: 'myer-plant', issueKind: 'Over-Pressure' }]] as const) {
      assert.match(await raw(listener.url, name, args as Record<string, unknown>), /invalid|enum|too|>=|<=|unrecognized|regex|pattern|option/i, `${name} rejects ${JSON.stringify(args)}`);
    }
  } finally { await Promise.allSettled([client.close(), manager.close()]); await server.close(); await upstream.close(); }
});

test('contract 5: Tomioka Silk Mill is the third site: agents, the streamed level-of-detail scene, overview budget, specs, metrics, regulations, scoping', async () => {
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  const server = createStewardServer(config(upstream.url, { allowedProperties: [...PROPERTY_IDS] }));
  const scoped = createStewardServer(config(upstream.url));
  const [listener, scopedListener] = await Promise.all([server.listen(0, { host: '127.0.0.1' }), scoped.listen(0, { host: '127.0.0.1' })]);
  const client = new Client({ name: 'tomioka-probe', version: '1' }, { capabilities: {} });
  const twoSites = new Client({ name: 'two-site-probe', version: '1' }, { capabilities: {} });
  try {
    await Promise.all([client.connect(new StreamableHTTPClientTransport(new URL(listener.url))), twoSites.connect(harness(scopedListener.url))]);
    const call = async (name: string, args: Record<string, unknown> = {}) => data(await client.callTool({ name, arguments: args }) as CallToolResult);
    assert.deepEqual((await call('list_sites')).sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps', 'tomioka-mill']);
    const agents = (await call('list_agents')).agents as Data[];
    assert.equal(agents.length, 14);
    assert.deepEqual(agents.filter(a => String(a.id).startsWith('tomioka-')).map(a => [a.id, a.level, a.name]), [
      ['tomioka-manager', 3, 'Site Manager · Tomioka'], ['tomioka-engineer', 4, 'Conservation Engineer · Tomioka'],
      ['tomioka-compliance', 4, 'Compliance Officer · Tomioka'], ['tomioka-technician', 5, 'Field Technician · Tomioka'],
    ]);

    // three sites and fourteen agents still fit the overview budget
    const overview = await call('get_overview');
    assert.deepEqual(overview.sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps', 'tomioka-mill']);
    assert.equal(overview.agents.length, 14); assert(overview.tokensEstimate <= 600 && estimateTokens(overview) <= 650, `overview ${overview.tokensEstimate} tokens`);

    // the scene: the streamed LOD capture, the register's new kinds, the SuperSplat camera
    const scene = await call('get_scene', { siteId: 'tomioka-mill' });
    assert.equal(scene.sogUrl, 'https://d28zzqy0iyovbz.cloudfront.net/849bce2a/v1/lod-meta.json'); assert.equal(scene.scanFormat, 'lod');
    assert.equal(scene.credit.author, 'acrylagitt'); assert.equal(scene.credit.url, 'https://superspl.at/scene/849bce2a'); assert.equal(scene.splatId, '849bce2a');
    assert.equal(scene.assets.length, 25, 'the contract table lists 25 tags');
    for (const kind of ['machine', 'structure', 'sensor', 'fire', 'hydrant', 'door', 'walkway', 'panel', 'camera', 'dehumidifier']) assert(scene.assets.some((a: Data) => a.kind === kind), kind);
    assert.deepEqual(scene.cameraPresets[0].position, [-32.414, 0.287, -43.351]); assert.equal(scene.cameraPresets[0].fov, 75);
    assert.equal((await call('get_scene', { siteId: 'myer-plant' })).scanFormat, 'sog');
    // a stale single meta.json from upstream never replaces a streamed-LOD capture (that object answers 403)
    const stale = 'https://d28zzqy0iyovbz.cloudfront.net/849bce2a/v1/meta.json';
    upstream.state.sceneOverride.set('tomioka-mill', { sogMetaUrl: stale, environment: { kind: 'splat', splatId: '849bce2a', sogMetaUrl: stale } });
    assert.equal((await call('get_scene', { siteId: 'tomioka-mill' })).sogUrl, 'https://d28zzqy0iyovbz.cloudfront.net/849bce2a/v1/lod-meta.json');
    upstream.state.sceneOverride.delete('tomioka-mill');
    const shown = await client.callTool({ name: 'show_factory', arguments: { siteId: 'tomioka-mill' } }) as CallToolResult;
    const text = shown.content.filter(block => block.type === 'text').map(block => block.text).join('');
    assert.match(text, /^Tomioka Silk Mill \(tomioka-mill\): 25 assets/); assert.match(text, /Streamed at runtime in levels of detail/); assert.match(text, /acrylagitt/);
    for (const needle of ['lod-meta.json', 'unified: true', 'setLocalEulerAngles(0, 0, 180)', 'splatBudget', 'lodRangeMin', 'frame:ready']) assert(FACTORY_VIEW_JS.includes(needle), `widget handles ${needle}`);

    // specs, metrics, regulations and crew for the site
    const specs = JSON.parse((await client.readResource({ uri: 'steward://sites/tomioka-mill/specs' })).contents.map(item => ('text' in item ? item.text : '')).join('')) as Data;
    assert.deepEqual(specs.sensor.humidity_pct.range, [40, 65]); assert.deepEqual(specs.sensor.temperature_c.range, [5, 30]); assert.deepEqual(specs.sensor.seismic_gal.range, [0, 80]);
    assert.deepEqual(specs.machine.status.enum, ['running', 'stopped', 'fault']); assert.deepEqual(specs.structure.crack_width_mm.range, [0, 0.3]);
    assert.deepEqual(specs.dehumidifier.running.enum, ['yes', 'no']);
    const metrics = await call('get_metrics', { siteId: 'tomioka-mill', hours: 24 });
    assert.deepEqual(metrics.series.map((s: Data) => s.key), ['humidity_pct', 'temperature_c', 'vibration_mms', 'crack_width_mm', 'power_kw', 'checked_in']);
    const checkedIn = metrics.series.find((s: Data) => s.key === 'checked_in');
    assert.equal(checkedIn.unit, 'people'); assert.equal(checkedIn.assetTag, 'SITE'); assert(checkedIn.points.every(([, value]: [string, number]) => Number.isInteger(value)));
    const regulations = await call('list_regulations', { siteId: 'tomioka-mill' });
    assert(regulations.regulations.length >= 3 && regulations.regulations.every((r: Data) => r.jurisdiction === 'JP' && r.officialUrl.startsWith('https://laws.e-gov.go.jp/')));
    assert.equal((await call('who_is_responsible', { siteId: 'tomioka-mill', issueKind: 'visitor_route' })).crewMember.role, 'visitor safety lead');
    const portfolio = await call('get_portfolio_summary');
    assert.deepEqual(portfolio.sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps', 'tomioka-mill']); assert(typeof portfolio.average.avgPressureBar === 'number');
    assert(portfolio.sites.every((s: Data) => typeof s.employeesCheckedIn === 'number' && !('visitorsToday' in s)), 'every site reports the employees checked in');

    // a two-site endpoint never shows Tomioka
    const call2 = async (name: string, args: Record<string, unknown> = {}) => data(await twoSites.callTool({ name, arguments: args }) as CallToolResult);
    assert.deepEqual((await call2('list_sites')).sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps']);
    const scopedOverview = await call2('get_overview');
    assert(!JSON.stringify(scopedOverview).includes('tomioka'), 'no Tomioka site, agent or change on a two-site endpoint');
    assert(!(await call2('list_scenarios')).scenarios.some((s: Data) => String(s.id).startsWith('tm-')));
    assert.match(await raw(scopedListener.url, 'get_scene', { siteId: 'tomioka-mill' }), /invalid|enum|option/i);
  } finally { await Promise.allSettled([client.close(), twoSites.close()]); await Promise.all([server.close(), scoped.close()]); await upstream.close(); }
});

test('addendum 4: the agent eye returns frames as image content with the pose and visible tags', async () => {
  const upstream = await fakeRealityBackend();
  const server = createStewardServer({ config: config(upstream.url, { allowActAs: true }) });
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'vision-model', version: '1' }, { capabilities: {} });
  const compliance = await as(listener.url, 'myer-compliance');
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(listener.url)));
    const tools = (await client.listTools()).tools;
    const look = tools.find(t => t.name === 'eye_look')!;
    assert.match(look.description!, /START HERE/); assert.equal(look.annotations?.readOnlyHint, true);
    for (const name of ['eye_move', 'eye_turn']) assert.match(tools.find(t => t.name === name)!.description!, /small/i);
    assert.match(tools.find(t => t.name === 'eye_go_to')!.description!, /visibleTags/);
    assert.match(tools.find(t => t.name === 'eye_orbit')!.description!, /At most 8 images/);
    assert.match(tools.find(t => t.name === 'eye_mark')!.description!, /0 to 1/);

    const first = await client.callTool({ name: 'eye_look', arguments: { siteId: 'myer-plant' } }) as CallToolResult;
    const image = first.content.find(block => block.type === 'image') as { type: 'image'; data: string; mimeType: string };
    assert(image, 'image content'); assert.equal(image.mimeType, 'image/jpeg'); assert.equal(image.data, FIXTURE_JPEG_B64);
    const text = first.content.filter(block => block.type === 'text').map(block => (block as { text: string }).text).join('');
    assert.match(text, /camera at \[/); assert.match(text, /NEXT: eye_go_to/);
    assert.equal(data(first).imagesReturned, 1); assert.equal(data(first).frames[0].image, 'included');

    const goTo = await client.callTool({ name: 'eye_go_to', arguments: { siteId: 'myer-plant', assetTag: 'PG-601' } }) as CallToolResult;
    const at = data(goTo);
    assert(at.visibleTags.includes('PG-601')); assert.equal(at.frames[0].visiblePins.find((p: Data) => p.assetTag === 'PG-601').occluded, false);
    const pin = at.frames[0].visiblePins.find((p: Data) => p.assetTag === 'PG-601');
    assert(Math.abs(pin.x - 0.5) < 0.05 && Math.abs(pin.y - 0.5) < 0.05, 'go_to centres the asset');
    assert.match(goTo.content.map(block => (block as { text?: string }).text ?? '').join(''), /Visible: .*PG-601/);
    const moved = data(await client.callTool({ name: 'eye_move', arguments: { siteId: 'myer-plant', direction: 'back', meters: 0.5 } }) as CallToolResult);
    assert(moved.visibleTags.includes('PG-601')); assert.notDeepEqual(moved.frames[0].camera.position, at.frames[0].camera.position);
    const turned = data(await client.callTool({ name: 'eye_turn', arguments: { siteId: 'myer-plant', yawDeg: 20 } }) as CallToolResult);
    assert.equal(turned.action, 'turn');

    // orbit: up to 8 images in one result, the rest listed
    const orbit = await client.callTool({ name: 'eye_orbit', arguments: { siteId: 'myer-plant', assetTag: 'V-503', frames: 12 } }) as CallToolResult;
    assert.equal(orbit.content.filter(block => block.type === 'image').length, 8);
    const ring = data(orbit);
    assert.equal(ring.frames.length, 12); assert.equal(ring.imagesReturned, 8); assert.equal(ring.imagesOmitted, 4);
    assert(ring.frames.slice(8).every((frame: Data) => frame.image === 'omitted' && frame.frameUrl.startsWith(upstream.url)));
    assert.match(orbit.content.map(block => (block as { text?: string }).text ?? '').join(''), /4 more frame\(s\) not included/);

    // mark: an annotation and an issue candidate
    const marked = data(await client.callTool({ name: 'eye_mark', arguments: { siteId: 'myer-plant', x: 0.5, y: 0.5, note: 'Handwheel looks stiff on V-503' } }) as CallToolResult);
    assert(marked.annotation && marked.annotation.issueId); assert.equal(upstream.state.annotations.length, 1);
    assert((data(await client.callTool({ name: 'list_issues', arguments: { siteId: 'myer-plant' } }) as CallToolResult).issues as Data[]).some(issue => issue.kind === 'eye_observation'));

    // authority: a compliance officer does not drive the eye; validation stays on the wire
    const deniedEye = data(await compliance.callTool({ name: 'eye_look', arguments: { siteId: 'myer-plant' } }) as CallToolResult);
    assert.equal(deniedEye.code, 'AUTHORITY_DENIED');
    for (const args of [{ siteId: 'myer-plant', direction: 'forward', meters: 6 }, { siteId: 'myer-plant', direction: 'sideways', meters: 1 }]) assert.match(await raw(listener.url, 'eye_move', args), /invalid|<=|too|option|enum/i);
    assert.match(await raw(listener.url, 'eye_orbit', { siteId: 'myer-plant', assetTag: 'V-503', frames: 20 }), /invalid|<=|too/i);
    assert.match(await raw(listener.url, 'eye_mark', { siteId: 'myer-plant', x: 1.5, y: 0, note: 'off screen' }), /invalid|<=|too/i);
    const unknown = data(await client.callTool({ name: 'eye_go_to', arguments: { siteId: 'myer-plant', assetTag: 'ZZ-999' } }) as CallToolResult);
    assert.equal(unknown.code, 'UNKNOWN_ASSET');
    // every act is a Change of type eye and a telemetry row on the backend
    assert(upstream.state.changes.filter(change => change.type === 'eye').length >= 5);
    assert(upstream.state.telemetry.some(row => row.tool === 'eye_go_to' && row.agentId === 'operator'));
  } finally { await Promise.allSettled([client.close(), compliance.close()]); await server.close(); await upstream.close(); }
});

test('addendum 4: metrics, conversations, regulations, compliance explanations, the fix workflow, maintenance, notifications', async () => {
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  const server = createStewardServer({ config: config(upstream.url, { allowActAs: true }) });
  const listener = await server.listen(0, { host: '127.0.0.1' });
  const client = new Client({ name: 'owner-agent', version: '1' }, { capabilities: {} });
  const myerManager = await as(listener.url, 'myer-manager');
  try {
    await client.connect(harness(listener.url));
    const call = async (name: string, args: Record<string, unknown> = {}) => data(await client.callTool({ name, arguments: args }) as CallToolResult);

    const portfolio = await call('get_portfolio_summary');
    assert.deepEqual(portfolio.sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps']); assert(typeof portfolio.average.avgPressureBar === 'number'); assert.equal(portfolio.synthetic, true);
    const metrics = await call('get_metrics', { siteId: 'myer-plant', hours: 24 });
    assert.deepEqual(metrics.series.map((s: Data) => s.key), ['pressure_bar', 'flow_m3h', 'temperature_c', 'level_pct', 'vibration_mms', 'power_kw', 'checked_in']);
    const pressure = metrics.series[0];
    assert(pressure.points.length <= 48 && pressure.points.length > 10); assert.deepEqual(pressure.spec, { min: 1.5, max: 3.5 }); assert.equal(pressure.outOfSpec, 0); assert.equal(pressure.unit, 'bar');
    assert(pressure.min <= pressure.avg && pressure.avg <= pressure.max);
    assert.match(metrics.nextStep, /inside their spec bands/);
    const narrow = await call('get_metrics', { siteId: 'bristol-pumps', series: ['level_pct'], hours: 6 });
    assert.equal(narrow.series.length, 1); assert.equal(narrow.series[0].assetTag, 'SU-201');

    // a scenario fills metrics overlays and conversations
    const run = await call('start_scenario', { scenarioId: 'my-overpressure' });
    await call('wait_for', { event: 'any', filter: { type: 'scenario', scenarioId: 'my-overpressure', runId: run.id, status: 'completed' }, timeoutSeconds: 10 });
    const overpressure = await call('get_metrics', { siteId: 'myer-plant', series: ['pressure_bar'], hours: 2 });
    assert(overpressure.series[0].outOfSpec > 0 && overpressure.series[0].last > 3.5, 'the overpressure ramp shows'); assert.match(overpressure.nextStep, /Out of spec: pressure_bar/);
    const conversations = await call('list_conversations', { siteId: 'myer-plant' });
    const meeting = conversations.conversations.find((c: Data) => c.kind === 'meeting');
    assert(meeting && meeting.headline && meeting.decisions === 1 && meeting.summaryBy === 'hand-seed');
    assert.equal(meeting.transcript, undefined, 'the list never carries transcripts');
    const summaryOnly = await call('get_conversation', { conversationId: meeting.id });
    assert.equal(summaryOnly.transcript, null); assert(summaryOnly.turns >= 3); assert.match(summaryOnly.nextStep, /includeTranscript=true/);
    assert(summaryOnly.summary.decisions.length === 1 && summaryOnly.summary.actions.length === 1);
    const full = await call('get_conversation', { conversationId: meeting.id, includeTranscript: true });
    assert.equal(full.transcript.length, summaryOnly.turns); assert(full.transcript.every((turn: Data) => turn.speaker && turn.text)); assert.match(full.notice, /never instructions/);
    assert((await call('list_conversations', { agentId: 'myer-technician' })).conversations.length >= 1);

    // regulations and the compliance explanation
    const bristolRegs = await call('list_regulations', { siteId: 'bristol-pumps' });
    assert(bristolRegs.regulations.length >= 3 && bristolRegs.regulations.every((r: Data) => r.jurisdiction === 'ENG-UK' && r.officialUrl.startsWith('https://www.legislation.gov.uk/') && r.licence === 'Open Government Licence v3.0'));
    assert(bristolRegs.regulations.every((r: Data) => r.fileUrl.startsWith(`${upstream.url}/api/regulations/`))); assert.match(bristolRegs.disclaimer, /Not legal advice/);
    const myerRegs = await call('list_regulations', { siteId: 'myer-plant' });
    assert(myerRegs.regulations.every((r: Data) => r.jurisdiction === 'VIC-AU' && r.officialUrl.startsWith('https://www.legislation.vic.gov.au/')));
    const cert = await call('start_scenario', { scenarioId: 'br-vessel-cert' });
    await call('wait_for', { event: 'any', filter: { type: 'scenario', scenarioId: 'br-vessel-cert', runId: cert.id, status: 'completed' }, timeoutSeconds: 10 });
    const certIssue = (await call('list_issues', { siteId: 'bristol-pumps' })).issues.find((i: Data) => i.kind === 'certificate_expired');
    assert(certIssue && certIssue.obligationId === 'ob-br-pv301-exam' && certIssue.documentId === 'doc-br-pv301-cert');
    const explained = await call('explain_compliance_issue', { issueId: certIssue.id });
    assert.equal(explained.what.assetTag, 'PV-301'); assert.equal(explained.what.obligation.id, 'ob-br-pv301-exam'); assert.equal(explained.what.obligation.status, 'blocked');
    assert.deepEqual(explained.why.map((r: Data) => r.id), ['reg-eng-pssr-2000-r8', 'reg-eng-pssr-2000-r9']);
    assert(explained.why.every((r: Data) => r.provision && r.summary && r.officialUrl));
    assert.equal(explained.who.role, 'restoration lead'); assert.equal(explained.who.via, 'bristol-technician'); assert.match(explained.disclaimer, /Not legal advice/); assert.match(explained.nextStep, /request_fix/);

    // the fix workflow: request_fix (owner's agent) → wait_for → resolved, obligation closed, roster notified
    const fix = await call('request_fix', { issueId: certIssue.id });
    assert.equal(fix.issueId, certIssue.id); assert.equal(fix.state, 'running'); assert.equal(fix.steps, 6); assert.match(fix.nextStep, /wait_for/);
    const done = await call('wait_for', { event: 'issue.changed', filter: { issueId: certIssue.id, status: 'resolved' }, timeoutSeconds: 10 });
    assert.equal(done.status, 'fired'); assert.equal(done.event.status, 'resolved');
    const after = await call('get_issue', { issueId: certIssue.id });
    assert.equal(after.status, 'resolved'); assert.equal(after.detail.evidence.length, 1, 'the eye frame is attached as evidence');
    assert.equal((await call('list_obligations', { siteId: 'bristol-pumps' })).obligations.find((o: Data) => o.id === 'ob-br-pv301-exam').status, 'ok');
    const notifications = await call('list_notifications', { siteId: 'bristol-pumps' });
    assert(notifications.notifications.length >= 3 && notifications.notifications.every((n: Data) => n.issueId === certIssue.id));
    assert(notifications.notifications.some((n: Data) => n.recordOnly === true), 'synthetic crew get records only');
    const fixCall = (await call('list_conversations', { siteId: 'bristol-pumps' })).conversations.find((c: Data) => c.kind === 'call' && c.participants.includes('bristol-engineer'));
    assert(fixCall, 'the engineer called the manager');
    const managerFix = data(await myerManager.callTool({ name: 'request_fix', arguments: { issueId: certIssue.id } }) as CallToolResult);
    assert.equal(managerFix.code, 'AUTHORITY_DENIED', "only the owner's agent starts the fix workflow");

    // maintenance: the factories share an examiner visit; managers propose for their own site
    const shared = await call('start_scenario', { scenarioId: 'x-maintenance' });
    await call('wait_for', { event: 'any', filter: { type: 'scenario', scenarioId: 'x-maintenance', runId: shared.id, status: 'completed' }, timeoutSeconds: 10 });
    const windows = await call('list_maintenance', { siteId: 'bristol-pumps' });
    const visit = windows.windows.find((w: Data) => w.siteIds.length === 2);
    assert.equal(visit.status, 'approved'); assert(visit.conversationId); assert.match(visit.scope, /PV-301/);
    assert.equal((await call('get_conversation', { conversationId: visit.conversationId })).participants.includes('director'), true);
    assert((await call('list_maintenance', { siteId: 'myer-plant' })).windows.some((w: Data) => w.id === visit.id), 'a shared window shows on both factories');
    const proposed = data(await myerManager.callTool({ name: 'propose_maintenance_window', arguments: { siteIds: ['myer-plant'], date: '2026-11-10', scope: 'Expansion vessel TK-201 charge check' } }) as CallToolResult);
    assert.equal(proposed.status, 'proposed'); assert.deepEqual(proposed.siteIds, ['myer-plant']);
    const otherSite = data(await myerManager.callTool({ name: 'propose_maintenance_window', arguments: { siteIds: ['bristol-pumps'], date: '2026-11-10', scope: 'Not my site to schedule' } }) as CallToolResult);
    assert.equal(otherSite.code, 'AUTHORITY_DENIED');
    assert.match(await raw(listener.url, 'propose_maintenance_window', { siteIds: ['myer-plant'], date: '10/11/2026', scope: 'bad date format' }), /invalid|regex|pattern/i);
  } finally { await Promise.allSettled([client.close(), myerManager.close()]); await server.close(); await upstream.close(); }
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
    // window ends: still_waiting, progress notifications on the way (the first one immediately)
    const progress: unknown[] = [];
    const started = Date.now();
    const first = data(await connection.callTool('wait_for', { event: 'issue.changed', siteId: 'myer-plant', timeoutSeconds: 2 }, { onprogress: (p: unknown) => progress.push(p), timeout: 10000 } as never) as CallToolResult);
    assert.equal(first.status, 'still_waiting'); assert(first.waitId); assert.match(first.nextStep, new RegExp(`waitId="${first.waitId}"`));
    assert(Date.now() - started >= 1900, 'held for the window');
    assert(progress.length >= 4, `progress notifications: ${progress.length}`); assert.equal(first.progressNotifications, progress.length);
    assert.match(String((progress[0] as Data).message), /no tokens/);
    // the same waitId again; the event lands while the call is held
    setTimeout(() => upstream.change('issue', 'myer-plant', 'iss-x', 'test event', undefined, { issueId: 'iss-x', status: 'open' }), 400);
    const again = data(await connection.callTool('wait_for', { event: 'issue.changed', waitId: first.waitId, timeoutSeconds: 5 }, { timeout: 10000 } as never) as CallToolResult);
    assert.equal(again.status, 'fired'); assert.equal(again.waitId, first.waitId); assert.equal(again.event.issueId, 'iss-x'); assert.equal(again.event.name, 'issue.changed'); assert.equal(again.event.siteId, 'myer-plant');
    assert(again.waitedSeconds < 3);
    // filters and sites narrow the match (Change fields and the backend's extras: type, issueId, status)
    setTimeout(() => {
      upstream.change('issue', 'bristol-pumps', 'iss-m', 'other site', undefined, { issueId: 'iss-m', status: 'resolved' });
      upstream.change('issue', 'myer-plant', 'iss-m', 'wrong status', undefined, { issueId: 'iss-m', status: 'open' });
      upstream.change('issue', 'myer-plant', 'iss-m', 'match', undefined, { issueId: 'iss-m', status: 'resolved' });
    }, 300);
    const filtered = data(await legacy.callTool({ name: 'wait_for', arguments: { event: 'any', siteId: 'myer-plant', filter: { type: 'issue', issueId: 'iss-m', status: 'resolved' }, timeoutSeconds: 5 } }) as CallToolResult);
    assert.equal(filtered.status, 'fired'); assert.equal(filtered.event.status, 'resolved'); assert.equal(filtered.event.summary, 'match');
    // a backend without long-poll answers immediately: the MCP re-asks every 2 s inside the same held call
    upstream.state.noLongPoll = true;
    setTimeout(() => upstream.change('reply', 'myer-plant', 'wi-1', 'reply', undefined, { workItemId: 'wi-1' }), 500);
    const polled = data(await legacy.callTool({ name: 'wait_for', arguments: { event: 'reply.received', timeoutSeconds: 6 } }) as CallToolResult);
    assert.equal(polled.status, 'fired');
    upstream.state.noLongPoll = false;
    // unknown waitId
    const unknown = await legacy.callTool({ name: 'wait_for', arguments: { event: 'any', waitId: 'wait-nope', timeoutSeconds: 2 } }) as CallToolResult;
    assert.equal(unknown.isError, true); assert.equal(data(unknown).code, 'WAIT_NOT_FOUND'); assert.match(data(unknown).recovery, /without waitId/);
    // every long-poll asked the backend for at most 15 s
    assert(upstream.state.paths.filter(path => path.startsWith('GET /api/waits/')).length >= 3);
    // the backend's fired-event envelope is flattened; a flat event passes through
    assert.deepEqual(flattenEvent({ name: 'board.resolved', change: { type: 'board_meeting', propertyId: 'bristol-pumps', refId: 'c1' }, extra: { issueId: 'i1', status: 'resolved' } }).issueId, 'i1');
    assert.equal(flattenEvent({ type: 'issue.changed', siteId: 'myer-plant' }).name, 'issue.changed');
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
    assert.equal(overview.siteId, 'myer-plant'); assert.equal(overview.openIssues.length, 1); assert.equal(overview.overview.id, 'myer-plant'); assert.match(overview.subscribe, /resources\/subscribe/);
    assert.equal(hub.subscribers('myer-plant'), 0);
    const subscription = await (modern as unknown as { listen(filter: unknown): Promise<{ close(): Promise<void> }> }).listen({ resourceSubscriptions: ['steward://sites/myer-plant/overview', 'steward://guide'] });
    await delay(50);
    assert.equal(hub.subscribers('myer-plant'), 1); assert.equal(hub.subscribers('bristol-pumps'), 0);
    assert(hub.pollers.get('myer-plant')?.timer, 'poller running'); assert(!hub.pollers.get('bristol-pumps')?.timer, 'no poller without subscribers');
    await delay(250); // baseline read
    upstream.change('issue', 'myer-plant', 'iss-a', 'myer change', undefined, { issueId: 'iss-a' });
    upstream.change('issue', 'bristol-pumps', 'iss-b', 'bristol change', undefined, { issueId: 'iss-b' });
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
    // a scenario's own step row is not news (the backend leaves it out of /changes): no notification for it alone
    const quiet = hub.emitted.get('bristol-pumps') ?? 0;
    upstream.change('scenario', 'bristol-pumps', 'run-x', 'Scenario started: Sump rising (synthetic).', undefined, { scenarioId: 'br-sump', runId: 'run-x', status: 'started' });
    await delay(350);
    assert.equal(hub.emitted.get('bristol-pumps') ?? 0, quiet, 'a scenario step row alone does not notify subscribers');
    upstream.change('issue', 'bristol-pumps', 'iss-sump', 'Sump 96 % and rising', 'SU-201', { issueId: 'iss-sump', status: 'open' });
    let received = '';
    const until = Date.now() + 2000;
    while (!received.includes('notifications/resources/updated') && Date.now() < until) { const { value, done } = await reader.read(); if (done) break; received += decoder.decode(value); }
    assert.match(received, /"method":"notifications\/resources\/updated","params":\{"uri":"steward:\/\/sites\/bristol-pumps\/overview"\}/);
    await (await post({ jsonrpc: '2.0', id: 5, method: 'resources/unsubscribe', params: { uri: 'steward://sites/bristol-pumps/overview' } }, session!)).json();
    assert.equal(hub.subscribers('bristol-pumps'), 0);
    await reader.cancel();
    assert((hub.emitted.get('bristol-pumps') ?? 0) >= 1 && (hub.emitted.get('myer-plant') ?? 0) >= 1);
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
    assert.equal(upstream.state.issues.get(issueId)!.decisions.length, 1);
    answer = { action: 'decline' };
    const declined = data(await connection.callTool('decide', { issueId, question: 'Close the visitor walkway now?', options: ['close walkway', 'keep open'] }) as CallToolResult);
    assert.equal(declined.status, 'declined'); assert.match(declined.nextStep, /via "owner"/);
    const owner = data(await connection.callTool('decide', { issueId, question: 'Close the visitor walkway now?', options: ['close walkway', 'keep open'], via: 'owner' }) as CallToolResult);
    assert.equal(owner.status, 'routed'); assert.equal(asked.length, 2, 'via owner does not elicit');
    // a 2025-era stateless client advertises nothing per request: routed to the owner through the field technician, dry-run
    const routed = data(await legacy.callTool({ name: 'decide', arguments: { issueId, question: 'Close the visitor walkway now?', options: ['close walkway', 'keep open'] } }) as CallToolResult);
    assert.equal(routed.status, 'routed'); assert.equal(routed.dryRun, true); assert.equal(routed.via, 'sms'); assert(routed.waitId); assert.match(routed.nextStep, /reply\.received/);
    assert(upstream.state.transcripts.some(entry => entry.agentId === 'bristol-technician' && entry.kind === 'sms' && entry.text.includes('(dry-run)')));
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
    for (const needle of [PLAYCANVAS_URL, 'playcanvas@2.23.3', 'ui/initialize', 'ui/notifications/tool-result', 'openai:set_globals', 'grayscale(1)', '"gsplat"', 'worldToScreen', 'focus_view']) assert(html.includes(needle), `view includes ${needle}`);
    assert.match(PLAYCANVAS_URL, /^https:\/\/cdn\.jsdelivr\.net\/npm\/playcanvas@\d+\.\d+\.\d+\/build\/playcanvas\.min\.mjs$/, 'engine URL pinned to an exact version');
    new Function(FACTORY_VIEW_JS); // the widget script parses (dynamic import included)
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
  const clients = [await as(a.url, 'myer-technician'), await as(b.url, 'myer-technician'), await as(a.url, 'not-an-agent')];
  try {
    const args = { siteId: 'myer-plant', assetTag: 'V-502', attribute: 'position', value: 'open', source: { kind: 'agent', ref: 'probe' }, statedTag: 'V-502' };
    const denied = data(await clients[0]!.callTool({ name: 'attest', arguments: args }) as CallToolResult);
    assert.equal(denied.code, 'AUTHORITY_DENIED'); assert.match(denied.message, /myer-technician/);
    assert.equal(upstream.state.actors.at(-1), 'myer-technician');
    const accepted = data(await clients[1]!.callTool({ name: 'attest', arguments: args }) as CallToolResult);
    assert.equal(accepted.verdict, 'accepted', 'without the flag the header is ignored and the MCP acts as its own actor');
    assert.equal(upstream.state.actors.at(-1), 'operator');
    await clients[2]!.callTool({ name: 'list_sites', arguments: {} });
    assert.equal(upstream.state.actors.at(-1), 'operator', 'an unknown agent id in the header is ignored');
  } finally { await Promise.allSettled(clients.map(client => client.close())); await Promise.all([allowed.close(), plain.close()]); await upstream.close(); }
});

test('telemetry sink: posts the acting agent and estimated tokens; pauses on a backend without the route', async () => {
  const calls: { url: string; body: Data }[] = [];
  const fetcher = (async (url: string, init: { body: string }) => { calls.push({ url, body: JSON.parse(init.body) as Data }); return new Response('{}', { status: 404 }); }) as unknown as typeof fetch;
  const sink = createTelemetry(config('http://127.0.0.1:9'), fetcher);
  const event = { tool: 'get_scene', agentId: 'director', requester: 'probe', ok: true, durationMs: 3, inputTokens: estimateTokens({ siteId: 'myer-plant' }), outputTokens: 900, estimated: true as const, at: new Date().toISOString() };
  sink.record(event); await delay(20);
  assert.equal(calls.length, 1); assert.equal(calls[0]!.url, 'http://127.0.0.1:9/api/telemetry');
  assert.equal(calls[0]!.body.agentId, 'director'); assert.equal(calls[0]!.body.tokens, event.inputTokens + 900); assert.equal(calls[0]!.body.ms, 3); assert.match(calls[0]!.body.detail, /in \d+ out 900/);
  assert.equal(sink.paused, true);
  sink.record(event); await delay(20);
  assert.equal(calls.length, 1, 'paused after a 404');
  assert.equal(estimateTokens('abcd'), 1); assert.equal(estimateTokens({ a: 1 }), 2);
});

type Report = { passed: number; failed: number; rows: { id: string; ok: boolean; detail: string; skipped?: boolean; data: Data }[] };
const failures = (report: Report) => report.rows.filter(row => !row.ok).map(row => `${row.id}: ${row.detail}`).join('\n');

test('eval suites: factory-workflow (twice), safety, efficiency and vision replay against the fake upstream', async () => {
  assert.deepEqual(DEFAULT_SUITES, ['mission-workflow', 'demo-workflow', 'factory-workflow', 'safety', 'efficiency', 'vision', 'tool-forge']);
  assert.deepEqual(getPath({ assets: [{ kind: 'valve', t: 1 }, { kind: 'pump', t: 2 }, { kind: 'valve', t: 3 }] }, 'assets[?kind=valve][1].t'), 3);
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  const server = createStewardServer(config(upstream.url, { allowActAs: true, allowedProperties: [...PROPERTY_IDS] }));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  try {
    for (const suite of ['factory-workflow', 'factory-workflow', 'safety', 'efficiency', 'vision']) {
      const workflow = JSON.parse(await readFile(resolveSuite(suite), 'utf8')) as { steps: { id: string }[] };
      const report = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as Report;
      assert.equal(report.failed, 0, `${suite}\n${failures(report)}`);
      assert.equal(report.passed, workflow.steps.length, suite);
    }
    for (const agent of ['myer-engineer', 'myer-technician', 'director', 'tomioka-technician', 'bristol-manager', 'tomioka-compliance']) assert(upstream.state.actors.includes(agent), `actor steps reached the backend as ${agent}`);
    assert(upstream.state.documentEmails.some(email => email.sender === 'tomioka-compliance' && email.recipient === 'bristol-compliance' && email.a2aTaskId), 'compliance to compliance across sites carries an A2A message');
  } finally { await server.close(); await upstream.close(); }
});

test('eval runner: actor steps are never run against an MCP that does not honour act-as', async () => {
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  const server = createStewardServer(config(upstream.url, { allowedProperties: [...PROPERTY_IDS] }));
  const listener = await server.listen(0, { host: '127.0.0.1' });
  try {
    assert.equal((await (await fetch(new URL('/health', listener.url))).json() as Data).actAs, false);
    const workflow = JSON.parse(await readFile(resolveSuite('safety'), 'utf8')) as { steps: { id: string; actor?: string }[] };
    const actorSteps = workflow.steps.filter(step => step.actor).length;
    const factsBefore = upstream.state.facts.length;
    const report = await runWorkflow({ mcpUrl: listener.url, backendUrl: upstream.url, workflow }) as Report;
    const actorRows = report.rows.filter(row => workflow.steps.find(step => step.id === row.id)?.actor);
    assert.equal(actorRows.length, actorSteps); assert(actorSteps >= 5, `actor steps ${actorSteps}`);
    assert(actorRows.every(row => !row.ok && /not run: .*STEWARD_MCP_ALLOW_ACT_AS/.test(row.detail)), failures(report));
    assert.equal(upstream.state.facts.length, factsBefore, 'the attests meant to be refused were not sent as the operator');
    assert(!upstream.state.paths.some(path => path === 'POST /api/properties/bristol-pumps/attest' || path === 'POST /api/properties/tomioka-mill/attest'));
    assert(!upstream.state.paths.some(path => /^POST \/api\/issues\/[^/]+\/assign$/.test(path)), 'the cross-site assignment was not sent as the operator');
    assert.equal(report.failed, actorSteps, 'only the actor steps fail; the rest of the suite still runs');
  } finally { await server.close(); await upstream.close(); }
});
