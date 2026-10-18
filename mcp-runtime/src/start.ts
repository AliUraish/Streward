import { createStewardServer } from './server.js';
import { loadConfig } from './config.js';
import { loadAnalytics } from './analytics.js';

const config = loadConfig();
const analytics = await loadAnalytics(process.env, 'steward');
const server = createStewardServer({ config, analytics });
try {
  // Hosted (Manufact injects PORT): mcp-use port precedence is argument > PORT > config, so pass no port and bind all
  // interfaces; locally keep the explicit loopback port. See manufact/README.md "Required code change".
  analytics.attach(server);
  const listener = await server.listen(config.hosted ? undefined : config.port, { host: config.host });
  console.log(`Steward MCP listening at ${listener.url}; backend ${config.backendUrl}${config.remoteBackend ? ' (remote https, STEWARD_ALLOW_REMOTE_BACKEND=true)' : ' (loopback)'}; sites ${config.allowedProperties.join(', ')}; analytics ${analytics.provider}.`);
  if (config.hosted) console.log(`Hosted mode: PORT=${process.env.PORT}, host ${config.host}, browser Origin validation off (gateway-fronted).`);
  if (!config.remoteBackend && config.host === '127.0.0.1') console.log('Local only. No tunnel, cloud deployment or model calls from this process. resolve with budget > 0 and escalate may dispatch a human through the backend.');
  let stopping = false;
  const stop = async () => { if (stopping) return; stopping = true; await analytics.close(); await server.close(); process.exit(0); };
  process.once('SIGINT', () => { void stop(); });
  process.once('SIGTERM', () => { void stop(); });
} catch (error) {
  console.error(`Steward MCP failed to start: ${error instanceof Error ? error.message : 'unknown listener error'}`);
  process.exitCode = 1;
}
