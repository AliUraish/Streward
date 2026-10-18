/**
 * The site as its agents see it (src/environment.ts): get_environment returns the agent environment as markdown with the latest
 * eye frames as images; request_site_tour asks the Site Inspector for a tour, waits for it and returns every stop with the
 * pictures of what is wrong; get_site_tour reads a tour later. All three are listed for ordinary clients, scoped to this
 * endpoint's sites, and say what they cost and what to do next.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer } from '../src/server.js';
import { PROPERTY_IDS, type RuntimeConfig } from '../src/config.js';
import { fakeRealityBackend } from './fake-reality.js';

type Data = Record<string, any>;
const textOf = (result: CallToolResult) => result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
const imagesOf = (result: CallToolResult) => result.content.filter(block => block.type === 'image');
const data = (result: CallToolResult): Data => (result.structuredContent ?? JSON.parse(textOf(result))) as Data;
function config(url: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl: url, port: 0, host: '127.0.0.1', allowedProperties: [...PROPERTY_IDS], actor: 'operator', requestTimeoutMs: 3000, remoteBackend: false, hosted: false, waitDefaultSeconds: 50, waitProgressMs: 250, ...patch };
}

test('environment tools: the site as its agents see it, and a site tour with pictures of what is wrong', async () => {
  const upstream = await fakeRealityBackend();
  const everything = createStewardServer(config(upstream.url));
  const scoped = createStewardServer(config(upstream.url, { allowedProperties: ['myer-plant'] }));
  const [allUrl, scopedUrl] = (await Promise.all([everything, scoped].map(server => server.listen(0, { host: '127.0.0.1' })))).map(listener => listener.url);
  const client = new Client({ name: 'env-probe', version: '1' }, { capabilities: {} });
  const narrow = new Client({ name: 'env-probe-scoped', version: '1' }, { capabilities: {} });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(allUrl!)));
    await narrow.connect(new StreamableHTTPClientTransport(new URL(scopedUrl!)));
    const tools = (await client.listTools()).tools;
    assert.equal(tools.length, 76, 'an ordinary client sees the three environment tools (78 less the two harness tools)');
    for (const name of ['get_environment', 'request_site_tour', 'get_site_tour']) {
      const tool = tools.find(t => t.name === name)!;
      assert(tool && tool.outputSchema, name);
      assert(/NEXT/.test(tool.description!) && /free/i.test(tool.description!) && /tokens/.test(tool.description!), `${name} says what it returns, costs and what next`);
      assert(!/scenario|simulat|synthetic/i.test(tool.description! + JSON.stringify(tool.inputSchema)), `${name} names no machinery`);
    }
    assert.equal(tools.find(t => t.name === 'get_environment')!.annotations?.readOnlyHint, true);
    assert.equal(tools.find(t => t.name === 'get_site_tour')!.annotations?.readOnlyHint, true);
    assert.equal(tools.find(t => t.name === 'request_site_tour')!.annotations?.readOnlyHint, false);

    const env = await client.callTool({ name: 'get_environment', arguments: { siteId: 'bristol-pumps' } }) as CallToolResult;
    assert.notEqual(env.isError, true, textOf(env));
    assert.equal(imagesOf(env).length, 2, 'the latest frames come back as images');
    assert((imagesOf(env)[0] as { mimeType: string }).mimeType === 'image/jpeg');
    const view = data(env);
    assert.equal(view.siteId, 'bristol-pumps'); assert.equal(view.imagesReturned, 2);
    assert.equal(view.frames[0].image, 'included'); assert.equal(view.frames[0].labels[0].mark.note, 'drain valve');
    assert(view.frames[0].url.startsWith(upstream.url), 'frame URLs are absolute on the backend');
    assert.equal(view.walk.agentName, 'Site Engineer · Bristol'); assert.equal(view.walk.moving, true);
    assert.equal(view.labels[0].verdict, 'bad'); assert.equal(view.obligations[0].daysOverdue, 6); assert.equal(view.summary.compliancePercent, 71.4);
    assert.match(textOf(env), /^# Bristol Dock Pump House \(bristol-pumps\): what the agents see/);
    assert.match(textOf(env), /NEXT: request_site_tour/);

    const resource = await client.readResource({ uri: 'steward://sites/bristol-pumps/environment' });
    assert.equal(resource.contents[0]!.mimeType, 'text/markdown');
    assert.match(String((resource.contents[0] as { text: string }).text), /^# Bristol Dock Pump House \(bristol-pumps\): what the agents see/);

    const tour = await client.callTool({ name: 'request_site_tour', arguments: { siteId: 'bristol-pumps', focus: ['P-103'], maxStops: 2 } }) as CallToolResult;
    assert.notEqual(tour.isError, true, textOf(tour));
    const done = data(tour);
    assert.equal(done.state, 'completed', 'the tool waited for the inspector');
    assert.deepEqual(done.route, ['P-103', 'SP-101']); assert.equal(done.stops.length, 2); assert.equal(done.findings, 1);
    assert.equal(done.stops[0].image, 'included'); assert.equal(done.stops[1].image, 'not_included');
    assert.equal(imagesOf(tour).length, 1, 'only the pictures of what is wrong come back');
    assert.match(textOf(tour), /1\. P-103 Electric drainage pump \(duty\): Looks bad: Steam pipework examination overdue by 6 days \[picture attached\]/);
    assert.match(textOf(tour), /2\. SP-101 .*: Looks good/);
    assert.match(done.requesterName, / over MCP$/, 'the backend hears which MCP client asked (mcp:<client name>)');
    assert(upstream.state.paths.includes('POST /api/site-tours'));

    const again = await client.callTool({ name: 'get_site_tour', arguments: { tourId: done.tourId } }) as CallToolResult;
    assert.equal(data(again).tourId, done.tourId); assert.equal(imagesOf(again).length, 1);
    const missing = await client.callTool({ name: 'get_site_tour', arguments: { tourId: 'tour-missing' } }) as CallToolResult;
    assert.equal(missing.isError, true); assert.match(textOf(missing), /NOT_FOUND/);

    // A tour still going when the wait ends returns the progress and the tourId for get_site_tour.
    upstream.state.tourMs = 60_000;
    process.env.STEWARD_MCP_TOUR_WAIT_MS = '500';
    try {
      const slow = await client.callTool({ name: 'request_site_tour', arguments: { siteId: 'tomioka-mill', maxStops: 3 } }) as CallToolResult;
      const progress = data(slow);
      assert.equal(progress.state, 'running'); assert.equal(progress.stops.length, 0); assert.equal(imagesOf(slow).length, 0);
      assert.match(textOf(slow), /is still touring Tomioka Silk Mill: 0 of 3 stops done \(tourId tour-/);
      assert.match(progress.nextStep, /get_site_tour\(tourId="tour-/);
    } finally { delete process.env.STEWARD_MCP_TOUR_WAIT_MS; }

    const outside = await narrow.callTool({ name: 'get_environment', arguments: { siteId: 'bristol-pumps' } }) as CallToolResult;
    assert.equal(outside.isError, true, 'a site outside the endpoint is refused');
    const outsideTour = await narrow.callTool({ name: 'get_site_tour', arguments: { tourId: done.tourId } }) as CallToolResult;
    assert.equal(outsideTour.isError, true); assert.match(textOf(outsideTour), /PROPERTY_SCOPE/);
  } finally {
    await Promise.allSettled([client.close(), narrow.close()]);
    await Promise.all([everything.close(), scoped.close()]); await upstream.close();
  }
});
