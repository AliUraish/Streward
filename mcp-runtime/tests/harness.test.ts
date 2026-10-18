/**
 * The eval harness's scenario tools (src/harness.ts). The backend plays the demo scenarios on its own, so list_scenarios
 * and start_scenario are left out of tools/list and refused on tools/call (UNKNOWN_TOOL; nothing reaches the backend)
 * unless the MCP runs with STEWARD_MCP_HARNESS_TOOLS=true (never honoured when hosted) AND the request carries
 * X-Steward-Harness: evals. An ordinary client sees no scenario or simulation machinery in tool descriptions, input
 * schemas, the guide, the resources or the prompts, and get_overview reports no active scenario.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer, AGENTS_URI, GUIDE_URI } from '../src/server.js';
import { loadConfig, PROPERTY_IDS, type RuntimeConfig } from '../src/config.js';
import { HARNESS_HEADER, HARNESS_HEADER_VALUE, HARNESS_TOOLS } from '../src/harness.js';
import { WAIT_EVENTS } from '../src/waits.js';
import { fakeRealityBackend } from './fake-reality.js';

type Data = Record<string, any>;
const textOf = (result: CallToolResult) => result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
const data = (result: CallToolResult): Data => (result.structuredContent ?? JSON.parse(textOf(result))) as Data;
function config(url: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl: url, port: 0, host: '127.0.0.1', allowedProperties: [...PROPERTY_IDS], actor: 'operator', requestTimeoutMs: 3000, remoteBackend: false, hosted: false, waitDefaultSeconds: 50, waitProgressMs: 250, ...patch };
}
const HARNESS = { [HARNESS_HEADER]: HARNESS_HEADER_VALUE };
/** A 2025-era client by default; modern negotiates 2026-07-28 (per-request envelope, resultType). */
const connect = async (url: string, headers: Record<string, string>, modern = false) => {
  const client = new Client({ name: 'harness-probe', version: '1' }, { capabilities: {}, ...(modern ? { versionNegotiation: { mode: 'auto' } } : {}) } as never);
  await client.connect(new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers } }));
  return client;
};
const scenarioRequests = (paths: string[]) => paths.filter(path => path.includes('/api/scenarios')).length;
const MACHINERY = /scenario|simulat/i;

test('config: STEWARD_MCP_HARNESS_TOOLS is off by default and never honoured when hosted', () => {
  assert.equal(loadConfig({}).harnessTools, false);
  assert.equal(loadConfig({ STEWARD_MCP_HARNESS_TOOLS: 'true' }).harnessTools, true);
  assert.equal(loadConfig({ STEWARD_MCP_HARNESS_TOOLS: 'true', PORT: '3000' }).harnessTools, false, 'never on a hosted endpoint');
  assert(!(WAIT_EVENTS as readonly string[]).includes('scenario.step'), 'wait_for does not offer scenario.step');
});

test('harness gate: hidden by default, with the flag but no header, and when hosted; listed and callable with the flag and the header', async () => {
  const upstream = await fakeRealityBackend({ stepMs: 120 });
  const plain = createStewardServer(config(upstream.url));
  const flagged = createStewardServer(config(upstream.url, { harnessTools: true }));
  // A hosted endpoint never serves them, even when its config and the request both ask (loadConfig already forces the flag off).
  const hosted = createStewardServer(config(upstream.url, { harnessTools: true, hosted: true }));
  const [plainUrl, flaggedUrl, hostedUrl] = (await Promise.all([plain, flagged, hosted].map(server => server.listen(0, { host: '127.0.0.1' })))).map(listener => listener.url);
  const clients: Client[] = [];
  const mcpUse = new MCPClient({ clientInfo: { name: 'harness-mcp-use', version: '1' }, mcpServers: { steward: { url: flaggedUrl, headers: HARNESS, oauth: false, detectMixedAuth: false } } });
  try {
    const hidden: [string, string, Record<string, string>, boolean?][] = [
      ['hidden by default', plainUrl!, {}],
      ['hidden without the flag even with the header', plainUrl!, HARNESS],
      ['hidden with the flag but no header', flaggedUrl!, {}],
      ['hidden with the flag but no header (2026-07-28 client)', flaggedUrl!, {}, true],
      ['hidden with the flag and another header value', flaggedUrl!, { [HARNESS_HEADER]: 'agent' }],
      ['hidden when hosted even with the flag and the header', hostedUrl!, HARNESS],
      ['hidden when hosted even with the flag and the header (2026-07-28 client)', hostedUrl!, HARNESS, true],
    ];
    for (const [label, url, headers, modern] of hidden) {
      const client = await connect(url, headers, modern); clients.push(client);
      const tools = (await client.listTools()).tools;
      assert.equal(tools.length, 73, `${label}: 75 tools less the two scenario tools`);
      for (const name of HARNESS_TOOLS) assert(!tools.some(tool => tool.name === name), `${label}: ${name} is not listed`);
      const before = scenarioRequests(upstream.state.paths);
      for (const [name, args] of [['list_scenarios', {}], ['start_scenario', { scenarioId: 'br-sump' }]] as const) {
        const refused = await client.callTool({ name, arguments: args }) as CallToolResult;
        assert.equal(refused.isError, true, `${label}: ${name} is refused`);
        assert.deepEqual(JSON.parse(textOf(refused)), { code: 'UNKNOWN_TOOL', message: `No tool named ${name} on this endpoint.`, recovery: 'Call tools/list for the tools this endpoint serves.', retryable: false }, `${label}: ${name}`);
      }
      assert.equal(scenarioRequests(upstream.state.paths), before, `${label}: a refused call never reaches the backend`);
    }
    assert(!upstream.state.scenarioRuns.length, 'no run was started');

    // An ordinary client: no scenario or simulation machinery in what it reads.
    const ordinary = clients[0]!;
    for (const tool of (await ordinary.listTools()).tools) {
      assert(!MACHINERY.test(tool.description ?? ''), `${tool.name} description: ${(tool.description ?? '').match(MACHINERY)?.[0]}`);
      assert(!MACHINERY.test(JSON.stringify(tool.inputSchema)), `${tool.name} input schema`);
    }
    const waitFor = (await ordinary.listTools()).tools.find(tool => tool.name === 'wait_for')!;
    assert.deepEqual((waitFor.inputSchema as Data).properties.event.enum, ['work_item.resolved', 'issue.changed', 'reply.received', 'board.resolved', 'any']);
    assert(!MACHINERY.test(ordinary.getInstructions() ?? ''), 'server instructions');
    const guide = (await ordinary.readResource({ uri: GUIDE_URI })).contents.map(item => ('text' in item ? item.text : '')).join('');
    assert(guide.includes('wait_for') && !MACHINERY.test(guide), `guide: ${guide.match(MACHINERY)?.[0]}`);
    assert(guide.includes('checked_in') && !guide.includes('visitor_count'), 'guide names the checked_in series');
    for (const item of [...(await ordinary.listResources()).resources, ...(await ordinary.listResourceTemplates()).resourceTemplates]) assert(!MACHINERY.test(item.description ?? ''), `resource ${item.name}`);
    const prompts = (await ordinary.listPrompts()).prompts;
    assert(prompts.every(prompt => !MACHINERY.test(prompt.description ?? '')), 'prompt descriptions');
    for (const [name, args] of [['investigate-issue', { issueId: 'iss-1' }], ['optimise-agents', {}], ['prove-before-signing', { siteId: 'myer-plant', task: 'Clear the plant room for restart, budget $5.' }], ['clear-site-for-restart', { siteId: 'myer-plant', budget: '5' }]] as const) {
      const prompt = await ordinary.getPrompt({ name, arguments: args });
      const text = prompt.messages.map(message => (message.content as { text?: string }).text ?? '').join('');
      assert(text.length > 100 && !MACHINERY.test(text), `prompt ${name}: ${text.match(MACHINERY)?.[0]}`);
    }

    // The eval harness: the flag and the header. Every client era sees 75 tools and can list and start a scenario.
    const harness = await connect(flaggedUrl!, HARNESS); clients.push(harness);
    const tools = (await harness.listTools()).tools;
    assert.equal(tools.length, 75);
    for (const name of HARNESS_TOOLS) assert.match(tools.find(tool => tool.name === name)?.description ?? '', /^Eval harness only\./, name);
    const modernHarness = await connect(flaggedUrl!, HARNESS, true); clients.push(modernHarness);
    assert.equal((await modernHarness.listTools()).tools.length, 75);
    assert.equal(data(await modernHarness.callTool({ name: 'list_scenarios', arguments: {} }) as CallToolResult).scenarios.length, 10);
    const viaMcpUse = await mcpUse.connect('steward');
    assert.deepEqual((await viaMcpUse.listTools()).map(tool => tool.name).sort(), tools.map(tool => tool.name).sort());
    const listed = data(await harness.callTool({ name: 'list_scenarios', arguments: {} }) as CallToolResult);
    assert(['br-sump', 'tm-humidity', 'x-heritage'].every(id => listed.scenarios.some((row: Data) => row.id === id)));
    const run = data(await viaMcpUse.callTool('start_scenario', { scenarioId: 'br-sump' }) as CallToolResult);
    assert.equal(run.scenarioId, 'br-sump'); assert.equal(run.state, 'running');
    // a running scenario is not advertised: get_overview says null at the top and per site
    const overview = data(await ordinary.callTool({ name: 'get_overview', arguments: {} }) as CallToolResult);
    assert.equal(overview.activeScenario, null); assert(overview.sites.length === 3 && overview.sites.every((site: Data) => site.activeScenario === null));
    // the harness waits for a scenario with event any and type scenario (the backend's filter matches Change fields and extras)
    const done = data(await harness.callTool({ name: 'wait_for', arguments: { event: 'any', siteId: 'bristol-pumps', filter: { type: 'scenario', scenarioId: 'br-sump', runId: run.id, status: 'completed' }, timeoutSeconds: 10 } }) as CallToolResult);
    assert.equal(done.status, 'fired'); assert.equal(done.event.type, 'scenario'); assert.equal(done.event.runId, run.id);
    assert.equal(upstream.state.scenarioRuns.length, 1);

    // Scenario step rows reach only the harness: get_changes, get_overview and the overview resource drop them for everyone else.
    const rowsFor = async (client: Client) => data(await client.callTool({ name: 'get_changes', arguments: { siteId: 'bristol-pumps', since: 0, limit: 500 } }) as CallToolResult).changes as Data[];
    assert((await rowsFor(harness)).some(row => row.type === 'scenario'), 'the harness sees the step rows');
    const agentRows = await rowsFor(ordinary);
    assert(agentRows.some(row => row.type === 'issue') && !agentRows.some(row => row.type === 'scenario'), 'an agent sees the issue and meeting Changes a step emits, not the step rows');
    assert(!(data(await ordinary.callTool({ name: 'get_overview', arguments: {} }) as CallToolResult).changes as Data[]).some(row => row.type === 'scenario'));
    const overviewResource = JSON.parse((await ordinary.readResource({ uri: 'steward://sites/bristol-pumps/overview' })).contents.map(item => ('text' in item ? item.text : '')).join('')) as Data;
    assert(!(overviewResource.changes as Data[]).some(row => row.type === 'scenario'));

    // The operator's authority: start_scenario and simulation only for the harness, in list_agents and steward://agents.
    const operatorOf = async (client: Client) => (data(await client.callTool({ name: 'list_agents', arguments: {} }) as CallToolResult).agents as Data[]).find(agent => agent.id === 'operator')!;
    const publicOperator = await operatorOf(ordinary);
    assert(publicOperator.authority.includes('start_mission') && !publicOperator.authority.some((entry: string) => MACHINERY.test(entry)), JSON.stringify(publicOperator.authority));
    const harnessOperator = await operatorOf(harness);
    assert(harnessOperator.authority.includes('start_scenario') && harnessOperator.authority.includes('simulation'));
    const agentsText = (await ordinary.readResource({ uri: AGENTS_URI })).contents.map(item => ('text' in item ? item.text : '')).join('');
    assert(agentsText.includes('"id":"operator"') && agentsText.includes('start_mission') && !MACHINERY.test(agentsText), `steward://agents: ${agentsText.match(MACHINERY)?.[0]}`);

    // An agent's `any` wait never fires on a scenario's own step row: it fires on the issue Change the step emits.
    setTimeout(() => {
      upstream.change('scenario', 'myer-plant', 'srun-x', 'Scenario started: Overpressure on PG-601 (synthetic).', undefined, { scenarioId: 'my-overpressure', runId: 'srun-x', status: 'started' });
      upstream.change('issue', 'myer-plant', 'iss-pg', 'PG-601 reads 4.1 bar on a 3.5 bar circuit', 'PG-601', { issueId: 'iss-pg', status: 'open' });
    }, 300);
    const heard = data(await ordinary.callTool({ name: 'wait_for', arguments: { event: 'any', siteId: 'myer-plant', timeoutSeconds: 5 } }) as CallToolResult);
    assert.equal(heard.status, 'fired'); assert.equal(heard.event.type, 'issue'); assert.equal(heard.event.issueId, 'iss-pg'); assert.notEqual(heard.event.name, 'scenario.step');
    const asked = await ordinary.callTool({ name: 'wait_for', arguments: { event: 'any', filter: { type: 'scenario' }, timeoutSeconds: 2 } }) as CallToolResult;
    assert.equal(asked.isError, true); assert.equal(data(asked).code, 'INVALID_ARGUMENT');

    // Bad arguments to a hidden tool get the same refusal (answered before the SDK's input validation), on both eras.
    for (const [label, client] of [['2025', clients[2]!], ['2026-07-28', clients[3]!]] as const) {
      const refused = await client.callTool({ name: 'start_scenario', arguments: { scenarioId: 'demolish', speed: -1 } }) as CallToolResult;
      assert.equal(refused.isError, true, label); assert.equal(data(refused).code, 'UNKNOWN_TOOL', label);
      assert(!/my-overpressure|br-sump|Invalid option/.test(textOf(refused)), `${label}: the refusal names no scenario`);
    }
  } finally {
    await Promise.allSettled([...clients.map(client => client.close()), mcpUse.close()]);
    await Promise.all([plain.close(), flagged.close(), hosted.close()]); await upstream.close();
  }
});
