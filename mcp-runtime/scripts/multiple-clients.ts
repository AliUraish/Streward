import { parseArgs } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import { MCPClient } from '@mcp-use/client';
import { Client, StreamableHTTPClientTransport, type CallToolResult } from '@modelcontextprotocol/client';
import { z } from 'zod';
import { localUrl } from '../src/config.js';
import { JobSchema, PropertyIdSchema, PropertySchema, StatsSchema } from '../src/schemas.js';

const { values } = parseArgs({ options: {
  'run-inspection': { type: 'boolean', default: false }, property: { type: 'string' }, scope: { type: 'string', default: 'pump-01' },
  url: { type: 'string', default: 'http://127.0.0.1:8002/mcp' }, 'timeout-ms': { type: 'string', default: '60000' }, help: { type: 'boolean', default: false },
} });

if (values.help) {
  console.log('STEWARD two-client smoke demo\n\nnpm --prefix mcp-runtime run demo\nnpm --prefix mcp-runtime run demo -- --run-inspection --property myer-plant --scope pump-01\n\nDefault: read-only discovery, property/context reads and invalid-property recovery.\n--run-inspection: explicitly queues ONE local inspection, polls its persisted job through the other client, and exports the report.\nOptional: --url http://127.0.0.1:8002/mcp --timeout-ms 60000.\nAuthentication: optional STEWARD_MCP_TOKEN environment variable.');
  process.exit(0);
}

const endpoint = localUrl(values.url!, '--url');
if (endpoint.pathname !== '/mcp') throw new Error('--url must point to the local /mcp endpoint.');
const timeout = Number(values['timeout-ms']);
if (!Number.isInteger(timeout) || timeout < 1000 || timeout > 300000) throw new Error('--timeout-ms must be 1000 through 300000.');
const token = process.env.STEWARD_MCP_TOKEN;
const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
const propertiesOutput = z.object({ properties: z.array(PropertySchema), mode: z.literal('local') });
const contextOutput = z.object({ property: PropertySchema, stats: StatsSchema, agents: z.array(z.unknown()), activeJob: JobSchema.nullable(), mode: z.literal('local') });
const jobOutput = z.object({ job: JobSchema });

function text(result: CallToolResult) { return result.content.filter(block => block.type === 'text').map(block => block.text).join('\n'); }
function output<S extends z.ZodType>(result: CallToolResult, schema: S): z.output<S> {
  if (result.isError) throw new Error(text(result));
  return schema.parse(result.structuredContent ?? JSON.parse(text(result)));
}
function isExpectedInvalid(error: unknown) { return error instanceof Error && /invalid|property|enum|scope|myer-plant|bristol-pumps/i.test(error.message); }

const mcpUse = new MCPClient({
  clientInfo: { name: 'steward-mcp-use-smoke', version: '0.1.0' },
  mcpServers: { steward: { url: endpoint.href, headers, timeout: 15000, oauth: false, detectMixedAuth: false } },
});
const official = new Client({ name: 'steward-official-smoke', version: '0.1.0' }, { capabilities: {} });
const transport = new StreamableHTTPClientTransport(endpoint, { requestInit: { headers, redirect: 'error' } });

try {
  const connection = await mcpUse.connect('steward');
  await official.connect(transport);
  const [mcpUseTools, officialTools] = await Promise.all([connection.listTools(), official.listTools()]);
  const required = ['list_properties', 'get_property_context', 'list_components', 'run_inspection', 'get_job', 'export_report'];
  for (const name of required) {
    if (!mcpUseTools.some(tool => tool.name === name) || !officialTools.tools.some(tool => tool.name === name)) throw new Error(`Tool discovery failed: ${name} was not visible to both clients.`);
  }

  const [useProperties, sdkProperties] = await Promise.all([
    connection.callTool('list_properties', {}).then(result => output(result, propertiesOutput)),
    official.callTool({ name: 'list_properties', arguments: {} }).then(result => output(result, propertiesOutput)),
  ]);
  const propertyId = values.property ? PropertyIdSchema.parse(values.property) : useProperties.properties[0]?.id;
  if (!propertyId || !useProperties.properties.some(property => property.id === propertyId)) throw new Error('The requested property is not permitted by this endpoint. Choose an ID returned by list_properties.');
  const [useContext, sdkContext] = await Promise.all([
    connection.callTool('get_property_context', { propertyId }).then(result => output(result, contextOutput)),
    official.callTool({ name: 'get_property_context', arguments: { propertyId } }).then(result => output(result, contextOutput)),
  ]);

  // Exercise a bad READ argument and then recover with another valid read. No write is attempted by default.
  let invalidPropertyRejected = false;
  try {
    const invalid = await official.callTool({ name: 'get_property_context', arguments: { propertyId: 'not-a-property' } });
    invalidPropertyRejected = invalid.isError === true;
  } catch (error) { if (!isExpectedInvalid(error)) throw error; invalidPropertyRejected = true; }
  if (!invalidPropertyRejected) throw new Error('Invalid property was unexpectedly accepted.');
  const recoveryContext = output(await official.callTool({ name: 'get_property_context', arguments: { propertyId } }), contextOutput);

  let inspection: unknown = undefined;
  if (values['run-inspection']) {
    const started = output(await connection.callTool('run_inspection', { propertyId, scope: values.scope }), jobOutput);
    let current = started.job;
    const deadline = Date.now() + timeout;
    while (current.status === 'queued' || current.status === 'running') {
      if (Date.now() >= deadline) throw new Error(`Job ${current.id} is still ${current.status}; deadline reached. It remains in the backend. Use get_job to continue; do not claim completion.`);
      await delay(500);
      current = output(await official.callTool({ name: 'get_job', arguments: { propertyId, jobId: current.id } }), jobOutput).job;
    }
    if (current.status !== 'completed') throw new Error(`Inspection ${current.id} failed: ${current.message}`);
    const report = await official.callTool({ name: 'export_report', arguments: { propertyId } });
    if (report.isError) throw new Error(text(report));
    inspection = { requestedScope: values.scope, startedVia: '@mcp-use/client', verifiedVia: '@modelcontextprotocol/client', job: current, report: report.structuredContent ?? JSON.parse(text(report)) };
  }

  console.log(JSON.stringify({
    application: 'STEWARD', endpoint: endpoint.href, mode: values['run-inspection'] ? 'explicit-local-inspection' : 'read-only',
    clients: [
      { library: '@mcp-use/client', version: '2.4.4', tools: mcpUseTools.map(tool => tool.name), properties: useProperties, context: useContext },
      { library: '@modelcontextprotocol/client', version: '2.3.1', tools: officialTools.tools.map(tool => tool.name), properties: sdkProperties, context: sdkContext },
    ],
    validation: { invalidPropertyRejected, recoveredPropertyId: recoveryContext.property.id },
    ...(inspection ? { inspection } : {}),
    disclosure: 'Actual local API/MCP results. This is a two-library interoperability demo, not an LLM conversation, physical inspection, statutory certification or external action.',
  }, null, 2));
} catch (error) {
  console.error(`STEWARD client demo failed: ${error instanceof Error ? error.message : 'unknown client error'}`);
  process.exitCode = 1;
} finally {
  await Promise.allSettled([mcpUse.close(), official.close()]);
}
