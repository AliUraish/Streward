/**
 * The owner's notifications page in agent mode (src/owner.ts): get_owner_notifications returns what the owner was last sent
 * or prepared and what last happened (structured content, newest first, scoped to this endpoint's sites, never the owner's
 * address or phone), and get_compliance_snapshot returns the snapshot as data with an absolute PDF URL. Both are listed
 * for ordinary clients, read-only, and say what they cost and what to do next.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { createStewardServer } from '../src/server.js';
import { PROPERTY_IDS, type RuntimeConfig } from '../src/config.js';
import { fakeRealityBackend } from './fake-reality.js';

type Data = Record<string, any>;
const textOf = (result: CallToolResult) => result.content.filter(block => block.type === 'text').map(block => block.text).join('\n');
const data = (result: CallToolResult): Data => (result.structuredContent ?? JSON.parse(textOf(result))) as Data;
function config(url: string, patch: Partial<RuntimeConfig> = {}): RuntimeConfig {
  return { backendUrl: url, port: 0, host: '127.0.0.1', allowedProperties: [...PROPERTY_IDS], actor: 'operator', requestTimeoutMs: 3000, remoteBackend: false, hosted: false, waitDefaultSeconds: 50, waitProgressMs: 250, ...patch };
}

test('owner tools: the feed of what the owner got and the compliance snapshot, for ordinary clients', async () => {
  const upstream = await fakeRealityBackend();
  const everything = createStewardServer(config(upstream.url));
  const scoped = createStewardServer(config(upstream.url, { allowedProperties: ['myer-plant', 'bristol-pumps'] }));
  const [allUrl, scopedUrl] = (await Promise.all([everything, scoped].map(server => server.listen(0, { host: '127.0.0.1' })))).map(listener => listener.url);
  const client = new Client({ name: 'owner-probe', version: '1' }, { capabilities: {} });
  const narrow = new Client({ name: 'owner-probe-scoped', version: '1' }, { capabilities: {} });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(allUrl!)));
    await narrow.connect(new StreamableHTTPClientTransport(new URL(scopedUrl!)));
    const tools = (await client.listTools()).tools;
    assert.equal(tools.length, 73, 'an ordinary client sees the owner tools (75 less the two harness tools)');
    for (const name of ['get_owner_notifications', 'get_compliance_snapshot']) {
      const tool = tools.find(t => t.name === name)!;
      assert(tool && tool.outputSchema, name);
      assert.equal(tool.annotations?.readOnlyHint, true, name); assert.equal(tool.annotations?.openWorldHint, false, name);
      assert(/NEXT/.test(tool.description!) && /free/i.test(tool.description!) && /tokens/.test(tool.description!), `${name} says what it returns, costs and what next`);
      assert(!/scenario|simulat|synthetic/i.test(tool.description! + JSON.stringify(tool.inputSchema)), `${name} names no machinery`);
    }

    const feed = data(await client.callTool({ name: 'get_owner_notifications', arguments: { limit: 10 } }) as CallToolResult);
    assert.equal(upstream.state.paths.filter(path => path === 'GET /api/owner/notifications').length, 1);
    assert.deepEqual(feed.notifications.map((n: Data) => n.kind), ['agent_report', 'owner_digest', 'owner_alert', 'owner_alert', 'walkthrough', 'maintenance', 'issue']);
    assert.equal(feed.latestAt, feed.notifications[0].at); assert.equal(feed.total, 7); assert.equal(feed.schedule.live, false); assert.equal(feed.schedule.digestEveryHours, 4);
    const report = feed.notifications[0];
    assert.equal(report.from, 'Compliance Officer · Bristol'); assert.equal(report.fromAddress, 'steward-bristol-compliance@inkboxmail.com'); assert.equal(report.mode, 'dry_run');
    assert.equal(report.links.reportId, 'arp-1'); assert.equal(report.attachments[0].url, `${upstream.url}/api/owner/reports/arp-1.pdf`);
    const digest = feed.notifications.find((n: Data) => n.kind === 'owner_digest');
    assert.equal(digest.siteId, null); assert.match(digest.title, /Myer 83 %, Bristol 71 %, Tomioka 71 %/); assert.equal(digest.attachments[0].contentType, 'application/pdf');
    const raw = JSON.stringify(feed);
    assert(!raw.includes('•') && !raw.includes('"to"'), 'the owner\'s address and phone (even masked) never leave the MCP');
    const text = textOf(await client.callTool({ name: 'get_owner_notifications', arguments: { limit: 2 } }) as CallToolResult);
    assert.match(text, /^2 of 7 owner notifications, newest first\. Owner email is prepared only \(not sent\)\./); assert.match(text, /NEXT: get_compliance_snapshot/);

    const bristol = data(await client.callTool({ name: 'get_owner_notifications', arguments: { siteId: 'bristol-pumps' } }) as CallToolResult);
    assert(bristol.notifications.every((n: Data) => n.siteId === 'bristol-pumps' || n.siteId === null));
    const limited = data(await narrow.callTool({ name: 'get_owner_notifications', arguments: {} }) as CallToolResult);
    assert(!limited.notifications.some((n: Data) => n.siteId === 'tomioka-mill'), 'items of a site outside the endpoint are dropped');
    const outside = await narrow.callTool({ name: 'get_owner_notifications', arguments: { siteId: 'tomioka-mill' } }) as CallToolResult;
    assert.equal(outside.isError, true);

    const snapshot = data(await client.callTool({ name: 'get_compliance_snapshot', arguments: {} }) as CallToolResult);
    assert.deepEqual(snapshot.sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps', 'tomioka-mill']);
    assert.equal(snapshot.complianceLine, 'Myer 83 %, Bristol 71 %, Tomioka 71 %'); assert.equal(snapshot.pdfUrl, `${upstream.url}/api/compliance/snapshot.pdf`);
    const myer = snapshot.sites[0];
    assert.equal(myer.compliancePct, 83.3); assert.equal(myer.overdue[0].regulations[0].linkOnly, true); assert.equal(myer.overdue[0].owner, 'Alasdair Pennock (Restoration lead)');
    assert.equal(myer.walkthrough.bad[0].frameUrl, `${upstream.url}/api/eye/frames/eyf-1.jpg`); assert.equal(myer.agents.length, 4); assert.equal(myer.maintenance[0].coordinatedWith, 'Myer Plant Room');
    assert.equal(snapshot.sites[1].blocked[0].blockedReason, 'The contractor has no free slot for three weeks.');
    assert.equal(snapshot.decisions.length, 1); assert.match(snapshot.nextStep, /explain_compliance_issue/);
    const one = data(await client.callTool({ name: 'get_compliance_snapshot', arguments: { siteId: 'tomioka-mill' } }) as CallToolResult);
    assert.deepEqual(one.sites.map((s: Data) => s.siteId), ['tomioka-mill']); assert.equal(one.pdfUrl, `${upstream.url}/api/compliance/snapshot.pdf?siteId=tomioka-mill`);
    const twoSites = data(await narrow.callTool({ name: 'get_compliance_snapshot', arguments: {} }) as CallToolResult);
    assert.deepEqual(twoSites.sites.map((s: Data) => s.siteId), ['myer-plant', 'bristol-pumps']);
    assert.equal(twoSites.pdfUrl, `${upstream.url}/api/compliance/snapshot.pdf?siteId=myer-plant,bristol-pumps`);
  } finally {
    await Promise.allSettled([client.close(), narrow.close()]);
    await Promise.all([everything.close(), scoped.close()]); await upstream.close();
  }
});
