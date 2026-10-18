/**
 * Site IDs: two scanned factories (REALITY-CONTRACT-3.md §1), myer-plant (MY) and bristol-pumps (BR), and the heritage
 * silk mill tomioka-mill (TM, REALITY-CONTRACT-5.md §1). harbor-works is retired.
 */
export const PROPERTY_IDS = ['myer-plant', 'bristol-pumps', 'tomioka-mill'] as const;
export type PropertyId = typeof PROPERTY_IDS[number];
/** Site IDs removed from the product. A config that still names them (an older deploy script) drops them with a warning instead of failing. */
export const RETIRED_SITE_IDS = ['harbor-works'] as const;
/** Reference prefix per site, as the backend builds work item references ({PREFIX}-{TAG}-{ATTR}-{seq}). */
export const REFERENCE_PREFIX: Record<PropertyId, string> = { 'myer-plant': 'MY', 'bristol-pumps': 'BR', 'tomioka-mill': 'TM' };
/**
 * Scan facts per site (REALITY-CONTRACT-3.md §1, REALITY-CONTRACT-5.md §1), loaded at runtime from the CloudFront origin,
 * never rehosted. format `sog`: one SOG meta.json. format `lod`: a streamed level-of-detail octree (lod-meta.json) whose
 * SOG chunks load as the camera moves; that capture has no single meta.json.
 */
export const SITE_SCANS: Record<PropertyId, { name: string; splatId: string; sogUrl: string; format: 'sog' | 'lod'; gaussians: string; author: string; sceneTitle: string; sceneUrl: string; thumbnailUrl: string }> = {
  'myer-plant': { name: 'Myer Plant Room', splatId: '66b655d3', sogUrl: 'https://d28zzqy0iyovbz.cloudfront.net/66b655d3/v1/meta.json', format: 'sog', gaussians: '14.16 M', author: 'azha007', sceneTitle: 'industrial plant room within Kenneth Myer building', sceneUrl: 'https://superspl.at/scene/66b655d3', thumbnailUrl: 'https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/66b655d3/v1/xl.webp' },
  'bristol-pumps': { name: 'Bristol Dock Pump House', splatId: '8a8ce192', sogUrl: 'https://d28zzqy0iyovbz.cloudfront.net/8a8ce192/v1/meta.json', format: 'sog', gaussians: '6.93 M', author: 'scanomatic_labs', sceneTitle: '1907 pumps being restored', sceneUrl: 'https://superspl.at/scene/8a8ce192', thumbnailUrl: 'https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/8a8ce192/v1/xl.webp' },
  // LOD v1: 23,564,860 gaussians stored across 5 levels (12.16 M at full detail), 44 chunk files.
  'tomioka-mill': { name: 'Tomioka Silk Mill', splatId: '849bce2a', sogUrl: 'https://d28zzqy0iyovbz.cloudfront.net/849bce2a/v1/lod-meta.json', format: 'lod', gaussians: '23.56 M across 5 LOD levels', author: 'acrylagitt', sceneTitle: '富岡製糸場', sceneUrl: 'https://superspl.at/scene/849bce2a', thumbnailUrl: 'https://s3-eu-west-1.amazonaws.com/images.playcanvas.com/splat/849bce2a/v1/xl.webp' },
};
/** A streamed level-of-detail scan URL (PlayCanvas picks its octree parser by this file name). */
export const LOD_META_URL = /\/lod-meta\.json$/i;
/**
 * The agents (REALITY-CONTRACT-4.md §1, REALITY-CONTRACT-5.md §2): the owner's agent, an operations director and one
 * four-role team per site. Each site-scoped id starts with the site's short name (myer- / bristol- / tomioka-).
 */
export const AGENT_IDS = [
  'operator', 'director',
  'myer-manager', 'myer-engineer', 'myer-compliance', 'myer-technician',
  'bristol-manager', 'bristol-engineer', 'bristol-compliance', 'bristol-technician',
  'tomioka-manager', 'tomioka-engineer', 'tomioka-compliance', 'tomioka-technician',
] as const;
export type AgentId = typeof AGENT_IDS[number];
export const AGENT_ID_PATTERN = /^(operator|director|(myer|bristol|tomioka)-(manager|engineer|compliance|technician))$/;
/** The team prefix of each site's agent ids. */
export const SITE_AGENT_PREFIX: Record<PropertyId, string> = { 'myer-plant': 'myer', 'bristol-pumps': 'bristol', 'tomioka-mill': 'tomioka' };
export const SITE_OF_AGENT_PREFIX: Record<string, PropertyId> = Object.fromEntries(Object.entries(SITE_AGENT_PREFIX).map(([site, prefix]) => [prefix, site as PropertyId]));
/** The site a site-scoped agent belongs to (null for the operator and the director). */
export function siteOfAgent(agentId: string): PropertyId | null {
  const prefix = agentId.split('-')[0] ?? '';
  return /^(myer|bristol|tomioka)-/.test(agentId) ? SITE_OF_AGENT_PREFIX[prefix] ?? null : null;
}
/** One of a site's own agents, e.g. agentOf('tomioka-mill', 'engineer') is tomioka-engineer. */
export const agentOf = (site: PropertyId, role: 'manager' | 'engineer' | 'compliance' | 'technician') => `${SITE_AGENT_PREFIX[site]}-${role}` as AgentId;
export const AGENT_LEVEL: Record<AgentId, number> = {
  operator: 1, director: 2, 'myer-manager': 3, 'bristol-manager': 3, 'tomioka-manager': 3,
  'myer-engineer': 4, 'myer-compliance': 4, 'bristol-engineer': 4, 'bristol-compliance': 4, 'tomioka-engineer': 4, 'tomioka-compliance': 4,
  'myer-technician': 5, 'bristol-technician': 5, 'tomioka-technician': 5,
};
export const AGENT_DISPLAY: Record<AgentId, string> = {
  operator: "Owner's agent", director: 'Operations Director',
  'myer-manager': 'Plant Manager · Myer', 'myer-engineer': 'Site Engineer · Myer', 'myer-compliance': 'Compliance Officer · Myer', 'myer-technician': 'Field Technician · Myer',
  'bristol-manager': 'Plant Manager · Bristol', 'bristol-engineer': 'Site Engineer · Bristol', 'bristol-compliance': 'Compliance Officer · Bristol', 'bristol-technician': 'Field Technician · Bristol',
  'tomioka-manager': 'Site Manager · Tomioka', 'tomioka-engineer': 'Conservation Engineer · Tomioka', 'tomioka-compliance': 'Compliance Officer · Tomioka', 'tomioka-technician': 'Field Technician · Tomioka',
};
/** Contract-3 actor ids that map to exactly one contract-4 agent (counsel and runner split by site, so they must be named). */
export const LEGACY_ACTORS: Record<string, AgentId> = { atlas: 'director', 'warden:myer-plant': 'myer-engineer', 'warden:bristol-pumps': 'bristol-engineer' };
/** The acting agent sent as X-Steward-Actor on every backend call. The MCP is the operator's agent unless STEWARD_MCP_ACTOR says otherwise. */
export const DEFAULT_ACTOR = 'operator';

export interface RuntimeConfig {
  backendUrl: string;
  port: number;
  /** Listener host. 127.0.0.1 unless hosted (PORT set), then 0.0.0.0. STEWARD_MCP_HOST overrides. */
  host: string;
  allowedProperties: [PropertyId, ...PropertyId[]];
  backendToken?: string;
  clientToken?: string;
  /** Agent id sent as X-Steward-Actor on every backend request (STEWARD_MCP_ACTOR, default operator). The backend enforces the authority table. */
  actor: string;
  requestTimeoutMs: number;
  /** True only when STEWARD_ALLOW_REMOTE_BACKEND=true permitted a non-loopback https backend (Manufact hosting through a tunnel). */
  remoteBackend: boolean;
  /** True when the platform injected PORT (Manufact): listen on the platform port, bind 0.0.0.0, no localhost-only Origin list. */
  hosted: boolean;
  /** Eval harness only (STEWARD_MCP_ALLOW_ACT_AS=true, never honoured when hosted): a request header X-Steward-Act-As picks the actor for that request. */
  allowActAs?: boolean;
  /** Eval harness only (STEWARD_MCP_HARNESS_TOOLS=true, never honoured when hosted): list_scenarios and start_scenario are listed and served, and only on requests that carry X-Steward-Harness: evals (src/harness.ts). */
  harnessTools?: boolean;
  /** Default hold window for wait_for, in seconds (STEWARD_WAIT_DEFAULT_SECONDS, default 50). See README "Waiting: client limits". */
  waitDefaultSeconds?: number;
  /** Shared /changes poller interval for resource subscriptions, ms (default 2000). */
  subscriptionPollMs?: number;
  /** wait_for progress-notification interval, ms (default 15000; tests shorten it). */
  waitProgressMs?: number;
  /** Tool Forge: how often the published forged tools are re-read, ms (default 5000; 0 turns the poller off). */
  forgePollMs?: number;
}

/** Configuration can select local ports, never an external server or arbitrary API path. */
export function localUrl(value: string, label: string): URL {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash) {
    throw new Error(`${label} must be an HTTP loopback URL without credentials, query, or fragment.`);
  }
  return url;
}

/**
 * Backend origin parser. Default: loopback http only. With STEWARD_ALLOW_REMOTE_BACKEND=true an https
 * non-loopback origin (a tunnel URL in front of the FastAPI backend) is also accepted. Plain http to a
 * remote host is never accepted, and neither are credentials, query strings, fragments or paths.
 */
export function backendUrl(value: string, allowRemote: boolean): { url: URL; remote: boolean } {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error('STEWARD_BACKEND_URL must be a valid absolute URL.'); }
  if (url.username || url.password || url.search || url.hash) throw new Error('STEWARD_BACKEND_URL must not contain credentials, query, or fragment.');
  if (url.pathname !== '/') throw new Error('STEWARD_BACKEND_URL must contain only the backend origin.');
  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if (url.protocol === 'http:' && loopback) return { url, remote: false };
  if (!allowRemote) throw new Error('STEWARD_BACKEND_URL must be an HTTP loopback URL without credentials, query, or fragment. Set STEWARD_ALLOW_REMOTE_BACKEND=true to permit an https tunnel URL.');
  if (url.protocol !== 'https:') throw new Error('STEWARD_ALLOW_REMOTE_BACKEND only permits an https backend origin; plain http is loopback-only.');
  if (loopback) throw new Error('STEWARD_ALLOW_REMOTE_BACKEND expects a non-loopback https origin; use plain http for a loopback backend.');
  return { url, remote: true };
}

function flag(value: string | undefined): boolean {
  return ['1', 'true', 'yes', 'on'].includes((value || '').trim().toLowerCase());
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): RuntimeConfig {
  const backend = backendUrl(env.STEWARD_BACKEND_URL || 'http://127.0.0.1:8001', flag(env.STEWARD_ALLOW_REMOTE_BACKEND));
  // PORT is the hosted-platform convention (Manufact injects it); STEWARD_MCP_PORT wins when both are set.
  const port = Number(env.STEWARD_MCP_PORT || env.PORT || '8002');
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('STEWARD_MCP_PORT must be an integer from 0 to 65535.');
  const listed = [...new Set((env.STEWARD_MCP_PROPERTY_IDS || PROPERTY_IDS.join(',')).split(',').map(value => value.trim()).filter(Boolean))];
  const retired = listed.filter(value => (RETIRED_SITE_IDS as readonly string[]).includes(value));
  if (retired.length) console.warn(`STEWARD_MCP_PROPERTY_IDS names retired site ${retired.join(', ')}; ignoring it (sites are ${PROPERTY_IDS.join(', ')}).`);
  const requested = listed.filter(value => !retired.includes(value));
  if (!requested.length || requested.some(value => !PROPERTY_IDS.includes(value as PropertyId))) {
    throw new Error(`STEWARD_MCP_PROPERTY_IDS must be a nonempty CSV subset of ${PROPERTY_IDS.join(', ')}.`);
  }
  // Loopback unless hosted (PORT injected by the platform): then bind 0.0.0.0 so the gateway can reach it.
  const hosted = Boolean(env.PORT);
  let actor = (env.STEWARD_MCP_ACTOR || DEFAULT_ACTOR).trim();
  if (LEGACY_ACTORS[actor]) { console.warn(`STEWARD_MCP_ACTOR=${actor} is a contract-3 id; acting as ${LEGACY_ACTORS[actor]}.`); actor = LEGACY_ACTORS[actor]!; }
  if (!AGENT_ID_PATTERN.test(actor)) throw new Error(`STEWARD_MCP_ACTOR must be one of ${AGENT_IDS.join(', ')}${actor === 'counsel' || actor === 'runner' ? ` (${actor} is now per site: ${actor === 'counsel' ? 'myer-compliance, bristol-compliance or tomioka-compliance' : 'myer-technician, bristol-technician or tomioka-technician'})` : ''}.`);
  const waitDefault = Number(env.STEWARD_WAIT_DEFAULT_SECONDS || '50');
  if (!Number.isFinite(waitDefault) || waitDefault < 1 || waitDefault > 300) throw new Error('STEWARD_WAIT_DEFAULT_SECONDS must be a number from 1 to 300.');
  const host = (env.STEWARD_MCP_HOST || (hosted ? '0.0.0.0' : '127.0.0.1')).trim();
  if (!/^[A-Za-z0-9.:\[\]-]+$/.test(host)) throw new Error('STEWARD_MCP_HOST must be a bare hostname or IP.');
  return {
    backendUrl: backend.url.origin,
    port,
    host,
    allowedProperties: requested as [PropertyId, ...PropertyId[]],
    backendToken: env.STEWARD_BACKEND_TOKEN || undefined,
    clientToken: env.STEWARD_MCP_TOKEN || undefined,
    actor,
    requestTimeoutMs: 15_000,
    remoteBackend: backend.remote,
    hosted,
    // Never on a hosted endpoint: the act-as header is an eval-harness convenience for one loopback MCP serving several actors.
    allowActAs: !hosted && flag(env.STEWARD_MCP_ALLOW_ACT_AS),
    // Never on a hosted endpoint either: the backend plays the scenarios itself; only the local eval harness drives them.
    harnessTools: !hosted && flag(env.STEWARD_MCP_HARNESS_TOOLS),
    waitDefaultSeconds: waitDefault,
    subscriptionPollMs: 2000,
    forgePollMs: 5000,
  };
}
