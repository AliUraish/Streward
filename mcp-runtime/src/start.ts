import server from './server.js';
import { loadConfig } from './config.js';

const config = loadConfig();
try {
  const listener = await server.listen(config.port, { host: '127.0.0.1' });
  console.log(`STEWARD MCP listening at ${listener.url}; backend ${config.backendUrl}; properties ${config.allowedProperties.join(', ')}.`);
  console.log('Local only. No tunnel, cloud deployment, model calls, external communication or payment tools.');
  let stopping = false;
  const stop = async () => { if (stopping) return; stopping = true; await server.close(); process.exit(0); };
  process.once('SIGINT', () => { void stop(); });
  process.once('SIGTERM', () => { void stop(); });
} catch (error) {
  console.error(`STEWARD MCP failed to start: ${error instanceof Error ? error.message : 'unknown listener error'}`);
  process.exitCode = 1;
}
