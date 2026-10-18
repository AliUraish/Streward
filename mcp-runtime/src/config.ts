export const PROPERTY_IDS = ['cedar', 'harbor', 'juniper'] as const;
export type PropertyId = typeof PROPERTY_IDS[number];

export interface RuntimeConfig {
  backendUrl: string;
  port: number;
  allowedProperties: [PropertyId, ...PropertyId[]];
  backendToken?: string;
  clientToken?: string;
  requestTimeoutMs: number;
}

/** Configuration can select local ports, never an external server or arbitrary API path. */
export function localUrl(value: string, label: string): URL {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash) {
    throw new Error(`${label} must be an HTTP loopback URL without credentials, query, or fragment.`);
  }
  return url;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): RuntimeConfig {
  const backend = localUrl(env.STEWARD_BACKEND_URL || 'http://127.0.0.1:8001', 'STEWARD_BACKEND_URL');
  if (backend.pathname !== '/') throw new Error('STEWARD_BACKEND_URL must contain only the backend origin.');
  const port = Number(env.STEWARD_MCP_PORT || '8002');
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('STEWARD_MCP_PORT must be an integer from 0 to 65535.');
  const requested = [...new Set((env.STEWARD_MCP_PROPERTY_IDS || PROPERTY_IDS.join(',')).split(',').map(value => value.trim()).filter(Boolean))];
  if (!requested.length || requested.some(value => !PROPERTY_IDS.includes(value as PropertyId))) {
    throw new Error(`STEWARD_MCP_PROPERTY_IDS must be a nonempty CSV subset of ${PROPERTY_IDS.join(', ')}.`);
  }
  return {
    backendUrl: backend.origin,
    port,
    allowedProperties: requested as [PropertyId, ...PropertyId[]],
    backendToken: env.STEWARD_BACKEND_TOKEN || undefined,
    clientToken: env.STEWARD_MCP_TOKEN || undefined,
    requestTimeoutMs: 15_000,
  };
}
