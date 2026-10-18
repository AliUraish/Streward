/**
 * Tool Forge (REALITY-CONTRACT-6.md): tools Steward's own agents build when no existing tool answers a task. The
 * backend owns the lifecycle (request → draft → validate → test → approve → publish → retire) and runs every call
 * declaratively (POST /api/tools/{id}/call) with the tool's validated recipe and the caller's authority; no generated
 * code runs anywhere. This module turns the published ones into MCP tools.
 *
 * Why not server.tool(): mcp-use 2.10.1 refuses registrations after start ("Cannot register tool ... after the server
 * has started: registrations are replayed per request from the registry, so register everything before
 * listen()/server.fetch."), and its `tools/call` middleware runs inside each registered tool's handler, after the SDK
 * has resolved the name, so an unregistered name never reaches it. A published forged tool is therefore served by
 * three pieces, all registered before start:
 *  1. a `mcp:tools/list` middleware appends one descriptor per published, in-scope forged tool: `forge_<name>`, a
 *     description that starts "Built by <agent> on <date> because <why.gap>", its JSON Schema input (plus the Armature
 *     telemetry block when analytics is on), annotations from `readOnly`;
 *  2. a /mcp HTTP middleware re-dispatches `tools/call forge_<name>` into the app as `call_forged_tool {toolId, args}`
 *     (the same re-entry the analytics wrapper uses), marked with a header so the result keeps the forged tool's own
 *     output shape;
 *  3. the stable tools `request_tool`, `list_forged_tools` and `call_forged_tool`, for clients that never re-list.
 * A poller reads GET /api/tools?status=published every 5 s, from the first /mcp request on (server.ts builds a default
 * instance at import that never serves, so construction must not touch the network); when the published set changes it emits
 * `notifications/tools/list_changed`: server.notifyToolsChanged() for 2026-07-28 `subscriptions/listen` streams
 * (toolsListChanged) and the legacy session streams of src/subscriptions.ts for 2025-era clients. Both eras already
 * advertise `tools.listChanged: true`.
 */
import type { MCPServer } from 'mcp-use';
import { z } from 'zod';
import { AGENT_DISPLAY, agentOf, siteOfAgent, type PropertyId, type RuntimeConfig } from './config.js';
import { AdapterError, type Backend } from './upstream.js';
import { LOCAL_WRITE, READ_ONLY, WithText, type ToolFn } from './tooling.js';
import { list } from './factory.js';
import type { SubscriptionHub } from './subscriptions.js';

type Json = Record<string, unknown>;
const ANY = z.unknown();
const obj = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {};
const str = (value: unknown): string | null => typeof value === 'string' && value.length ? value : typeof value === 'number' ? String(value) : null;
const num = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const clip = (value: string, max: number) => value.length > max ? `${value.slice(0, max - 1)}…` : value;
const enc = encodeURIComponent;

export const FORGE_PREFIX = 'forge_';
export const CALL_FORGED_TOOL = 'call_forged_tool';
/** Set on the re-dispatched request: the forged tool the client called by name. */
export const FORGE_CALL_HEADER = 'x-steward-forged-tool';
/** Marks the registry's background reads, so request logs (and the fixture) can tell them from tool calls. */
export const BACKGROUND_HEADER = 'X-Steward-Background';
export const FORGE_STATUSES = ['draft', 'validated', 'tested', 'approved', 'published', 'rejected', 'retired'] as const;
/** snake_case, and the whole MCP name (forge_ included) within the 64-character tool-name limit. */
const FORGE_NAME = /^forge_[a-z][a-z0-9_]{0,57}$/;
export const FORGE_POLL_MS = 5000;

export interface ForgedTool {
  id: string; name: string; mcpName: string; version: number; status: string; siteId: string | null;
  createdBy: string | null; createdAt: string | null; approvedBy: string | null; approvedAt: string | null;
  why: { task: string | null; requestedBy: string | null; gap: string | null; consideredTools: { name: string; whyNot: string }[] };
  description: string; inputSchema: Json; steps: Json[]; output: Json; readOnly: boolean; test: Json | null;
  usage: { calls: number; lastCalledAt: string | null; tokensSavedEstimate: number };
  generator: string | null; synthetic: boolean | null;
}

/** The backend's ForgedTool (contract 6), read leniently; null without an id and a name. */
export function normaliseForgedTool(raw: Json): ForgedTool | null {
  const id = str(raw.id) ?? str(raw.toolId); const name = str(raw.name);
  if (!id || !name) return null;
  const bare = name.startsWith(FORGE_PREFIX) ? name.slice(FORGE_PREFIX.length) : name;
  const why = obj(raw.why); const usage = obj(raw.usage);
  return {
    id, name: bare, mcpName: `${FORGE_PREFIX}${bare}`, version: num(raw.version) ?? 1, status: str(raw.status) ?? 'draft', siteId: str(raw.siteId) ?? str(raw.propertyId),
    createdBy: str(raw.createdBy), createdAt: str(raw.createdAt), approvedBy: str(raw.approvedBy), approvedAt: str(raw.approvedAt),
    why: { task: str(why.task), requestedBy: str(why.requestedBy), gap: str(why.gap), consideredTools: list(why.consideredTools).map(tool => ({ name: str(tool.name) ?? 'tool', whyNot: str(tool.whyNot) ?? '' })) },
    description: str(raw.description) ?? '', inputSchema: obj(raw.inputSchema), steps: list(raw.steps), output: obj(raw.output),
    // A tool is read-only only when the backend says so; anything else is treated as able to write.
    readOnly: raw.readOnly === true, test: raw.test && typeof raw.test === 'object' ? obj(raw.test) : null,
    usage: { calls: num(usage.calls) ?? 0, lastCalledAt: str(usage.lastCalledAt), tokensSavedEstimate: num(usage.tokensSavedEstimate) ?? 0 },
    generator: str(raw.generator), synthetic: typeof raw.synthetic === 'boolean' ? raw.synthetic : null,
  };
}

const display = (id: string | null) => id ? (AGENT_DISPLAY as Record<string, string>)[id] ?? id : null;
const titleOf = (name: string) => { const words = name.replace(/_/g, ' '); return words.charAt(0).toUpperCase() + words.slice(1); };

/** "Built by <agent> on <date> because <why.gap>", then what the tool does, its scope, cost and the task behind it. */
export function forgedDescription(tool: ForgedTool): string {
  const gap = (tool.why.gap ?? 'no existing tool answered the task in one call').trim().replace(/[.\s]+$/, '');
  const head = `Built by ${display(tool.createdBy) ?? 'a Steward agent'} on ${tool.createdAt?.slice(0, 10) || 'an unrecorded date'} because ${gap}.`;
  const approval = tool.approvedBy ? `; approved by ${display(tool.approvedBy)}${tool.approvedAt ? ` on ${tool.approvedAt.slice(0, 10)}` : ''}` : '';
  const scope = `Forged tool ${tool.id} v${tool.version}, ${tool.siteId ?? 'its site'} only, ${tool.readOnly ? 'read-only' : 'writes records'}${approval}.`;
  const run = 'Runs on the Steward backend with your authority and the recipe Steward validated and tested (no generated code); usage is counted; it costs only the reads it makes.';
  const asked = tool.why.task ? ` Built for: "${clip(tool.why.task, 200)}"` : '';
  return clip(`${head} ${tool.description.trim()} ${scope} ${run}${asked}`.replace(/\s+/g, ' ').trim(), 2000);
}

/** The advertised output schema: an object schema as is, an array schema wrapped as {rows}; anything else is not advertised. */
export function forgedOutputSchema(tool: ForgedTool): Json | null {
  const schema = obj(tool.output.schema);
  if (schema.type === 'object') return schema;
  if (schema.type === 'array') return { type: 'object', properties: { rows: schema }, required: ['rows'] };
  return null;
}

/** structuredContent must be an object: an array output becomes {rows}, a scalar {value}. */
export function structuredOutput(output: unknown): Json {
  if (output && typeof output === 'object' && !Array.isArray(output)) return output as Json;
  if (Array.isArray(output)) return { rows: output };
  return { value: output ?? null };
}

/** The tools/list descriptor of a published forged tool. */
export function forgedDescriptor(tool: ForgedTool, telemetry: Json | null) {
  const outputSchema = forgedOutputSchema(tool);
  const properties = { ...obj(tool.inputSchema.properties), ...(telemetry ? { telemetry } : {}) };
  return {
    name: tool.mcpName, title: titleOf(tool.name), description: forgedDescription(tool),
    inputSchema: { ...tool.inputSchema, type: 'object' as const, properties },
    ...(outputSchema ? { outputSchema: { ...outputSchema, type: 'object' as const } } : {}),
    annotations: { title: titleOf(tool.name), readOnlyHint: tool.readOnly, destructiveHint: false, idempotentHint: tool.readOnly, openWorldHint: false },
    _meta: { 'io.steward/forgedTool': { id: tool.id, version: tool.version, siteId: tool.siteId, createdBy: tool.createdBy, approvedBy: tool.approvedBy } },
  };
}

/** Top-level argument check against the tool's JSON Schema (required, unknown keys, types, enum, ranges); the backend validates fully. */
export function checkArgs(schema: Json, args: Json): string | null {
  const properties = obj(schema.properties);
  for (const key of Array.isArray(schema.required) ? schema.required.filter((k): k is string => typeof k === 'string') : []) if (!(key in args)) return `${key} is required`;
  if (schema.additionalProperties === false) { const unknown = Object.keys(args).find(key => !(key in properties)); if (unknown) return `unknown argument ${unknown} (expected ${Object.keys(properties).join(', ') || 'no arguments'})`; }
  for (const [key, value] of Object.entries(args)) {
    const property = obj(properties[key]);
    const types = (Array.isArray(property.type) ? property.type : [property.type]).filter((type): type is string => typeof type === 'string');
    if (types.length && !types.some(type => type === 'null' ? value === null : type === 'integer' ? Number.isInteger(value) : type === 'number' ? typeof value === 'number' && Number.isFinite(value)
      : type === 'array' ? Array.isArray(value) : type === 'object' ? Boolean(value) && typeof value === 'object' && !Array.isArray(value) : typeof value === type)) return `${key} must be ${types.join(' or ')}`;
    if (Array.isArray(property.enum) && !property.enum.some(option => option === value)) return `${key} must be one of ${property.enum.map(String).join(', ')}`;
    if (typeof value === 'number') {
      if (typeof property.minimum === 'number' && value < property.minimum) return `${key} must be >= ${property.minimum}`;
      if (typeof property.maximum === 'number' && value > property.maximum) return `${key} must be <= ${property.maximum}`;
    }
    if (typeof value === 'string' && typeof property.maxLength === 'number' && value.length > property.maxLength) return `${key} is longer than ${property.maxLength} characters`;
  }
  return null;
}

/**
 * The published, in-scope forged tools this MCP serves, refreshed from GET /api/tools?status=published. The latest
 * version wins per name. A backend without the route (404/405/501) pauses the poller for a minute.
 */
export class ForgeRegistry {
  private tools = new Map<string, ForgedTool>();
  private signature = '[]';
  private timer: NodeJS.Timeout | null = null;
  private pending: Promise<boolean> | null = null;
  private pausedUntil = 0;
  lastSyncAt: string | null = null;
  lastError: string | null = null;
  /** Reads attempted, successful reads, and published-set changes seen. */
  attempts = 0;
  syncs = 0;
  changes = 0;

  constructor(private readonly backend: Backend, private readonly config: RuntimeConfig, private readonly onChange: () => Promise<void>) {}

  get size() { return this.tools.size; }
  get pollMs() { return this.config.forgePollMs ?? FORGE_POLL_MS; }
  list() { return [...this.tools.values()].sort((a, b) => a.mcpName.localeCompare(b.mcpName)); }
  get(mcpName: string) { return this.tools.get(mcpName); }
  byId(id: string) { return [...this.tools.values()].find(tool => tool.id === id); }

  /** One read of the published set; resolves true when it changed (and list_changed went out). Concurrent calls share one read. */
  sync(): Promise<boolean> {
    if (this.pending) return this.pending;
    if (Date.now() < this.pausedUntil) return Promise.resolve(false);
    this.attempts += 1;
    this.pending = this.load().finally(() => { this.pending = null; });
    return this.pending;
  }

  private async load(): Promise<boolean> {
    let raw: unknown;
    try {
      raw = await this.backend.json(`/api/tools?${new URLSearchParams({ status: 'published' })}`, ANY, { headers: { [BACKGROUND_HEADER]: 'forge-sync' } });
    } catch (error) {
      const known = error instanceof AdapterError ? error : null;
      if (known?.httpStatus && [404, 405, 501].includes(known.httpStatus)) this.pausedUntil = Date.now() + 60_000;
      this.lastError = known ? `${known.code}: ${known.message}` : 'the backend did not answer';
      return false; // keep the last known set
    }
    const next = new Map<string, ForgedTool>();
    for (const tool of list(raw, 'tools').map(normaliseForgedTool)) {
      if (!tool || tool.status !== 'published' || !tool.siteId || !(this.config.allowedProperties as readonly string[]).includes(tool.siteId) || !FORGE_NAME.test(tool.mcpName)) continue;
      const current = next.get(tool.mcpName);
      if (!current || tool.version > current.version) next.set(tool.mcpName, tool);
    }
    const signature = JSON.stringify([...next.values()].map(tool => [tool.mcpName, tool.id, tool.version, forgedDescription(tool), tool.inputSchema, tool.output, tool.readOnly]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))));
    this.tools = next; this.syncs += 1; this.lastSyncAt = new Date().toISOString(); this.lastError = null;
    if (signature === this.signature) return false;
    this.signature = signature; this.changes += 1;
    await this.onChange().catch(() => { /* a notification failure never breaks the sync */ });
    return true;
  }

  start() {
    if (this.timer || this.pollMs <= 0) return;
    this.timer = setInterval(() => { void this.sync(); }, this.pollMs);
    this.timer.unref?.();
    void this.sync();
  }

  stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } }
}

// ---- output schemas of the stable tools ----

const ConsideredSchema = z.object({ name: z.string(), whyNot: z.string() });
const WhySchema = z.object({ task: z.string().nullable(), requestedBy: z.string().nullable(), gap: z.string().nullable(), consideredTools: z.array(ConsideredSchema) });
export const ForgedToolOutSchema = z.object({
  id: z.string(), name: z.string(), mcpName: z.string(), version: z.number(), status: z.string(), siteId: z.string().nullable(),
  createdBy: z.string().nullable(), createdByName: z.string().nullable(), createdAt: z.string().nullable(), approvedBy: z.string().nullable(), approvedAt: z.string().nullable(),
  why: WhySchema, description: z.string(), readOnly: z.boolean(), inputSchema: z.record(z.string(), z.unknown()),
  steps: z.array(z.looseObject({ id: z.string().nullable().optional(), op: z.string().nullable().optional() })), test: z.record(z.string(), z.unknown()).nullable(),
  usage: z.object({ calls: z.number(), lastCalledAt: z.string().nullable(), tokensSavedEstimate: z.number() }), generator: z.string().nullable(), synthetic: z.boolean().nullable(),
  firstClass: z.boolean().describe('true when this MCP lists it in tools/list right now (published and in scope).'),
});
const RequestOutSchema = z.object({
  requestId: z.string().nullable(), toolId: z.string().nullable(), name: z.string().nullable(), mcpName: z.string().nullable(), status: z.string(),
  siteId: z.string(), agentId: z.string(), requestedBy: z.string(), gap: z.string().nullable(), consideredTools: z.array(ConsideredSchema), generator: z.string().nullable(), nextStep: z.string(),
});

export interface ForgeDeps {
  tool: ToolFn; backend: Backend; config: RuntimeConfig; server: MCPServer; hub: SubscriptionHub;
  siteId: z.ZodType<PropertyId>; agentId: z.ZodType<string>; inScope(site: string): boolean;
  /** JSON Schema of the Armature telemetry block, when analytics advertises it on every tool; null otherwise. */
  telemetry: Json | null;
}

/** Register the Tool Forge tools and the tools/list and tools/call plumbing for forge_<name>; the poller starts with the first /mcp request. Call before start. */
export function registerForgeTools({ tool, backend, config, server, hub, siteId, agentId, inScope, telemetry }: ForgeDeps): ForgeRegistry {
  let started = false;
  const registry = new ForgeRegistry(backend, config, async () => {
    // Before the first request nobody can be listening, and mounting early would freeze the registry.
    if (started) { try { await server.notifyToolsChanged(); } catch { /* no 2026-07-28 listeners */ } }
    hub.broadcast('notifications/tools/list_changed');
  });
  const idString = z.string().min(1).max(120).regex(/^[A-Za-z0-9][A-Za-z0-9:._-]*$/);
  const summary = (forged: ForgedTool): z.infer<typeof ForgedToolOutSchema> => ({
    id: forged.id, name: forged.name, mcpName: forged.mcpName, version: forged.version, status: forged.status, siteId: forged.siteId,
    createdBy: forged.createdBy, createdByName: display(forged.createdBy), createdAt: forged.createdAt, approvedBy: forged.approvedBy, approvedAt: forged.approvedAt,
    why: forged.why, description: forged.description, readOnly: forged.readOnly, inputSchema: forged.inputSchema, steps: forged.steps, test: forged.test, usage: forged.usage,
    generator: forged.generator, synthetic: forged.synthetic, firstClass: registry.get(forged.mcpName)?.id === forged.id,
  });
  const waitFor = (site: string, toolId: string) => `wait_for(event="any", siteId="${site}", filter={type:"tool", toolId:"${toolId}", status:"published"})`;

  // 1. forge_<name> in tools/list, on the first page (the very first list waits up to 2 s for the first read of the published set).
  server.use('mcp:tools/list', async (ctx, next) => {
    if (registry.attempts === 0) await Promise.race([registry.sync(), new Promise(resolve => setTimeout(resolve, 2000).unref?.())]);
    const tools = await next();
    if ((ctx.params as { cursor?: unknown } | undefined)?.cursor) return tools;
    const names = new Set(tools.map(item => item.name));
    return [...tools, ...registry.list().filter(forged => !names.has(forged.mcpName)).map(forged => forgedDescriptor(forged, telemetry) as unknown as typeof tools[number])];
  });

  // 2. tools/call forge_<name> → call_forged_tool {toolId, args}, re-dispatched into the app with the marker header.
  const toolError = (id: unknown, code: string, message: string, recovery: string) => new Response(JSON.stringify({ jsonrpc: '2.0', id: id ?? null, result: { isError: true, content: [{ type: 'text', text: JSON.stringify({ code, message, recovery, retryable: false }) }] } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  server.app.use('/mcp', async (context, next) => {
    if (!started) { started = true; registry.start(); }
    const raw = context.req.raw;
    if (raw.method !== 'POST' || context.req.header(FORGE_CALL_HEADER) || !(context.req.header('content-type') || '').includes('json')) { await next(); return; }
    let message: Json | null = null;
    try { const parsed = JSON.parse(await raw.clone().text()) as unknown; if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) message = parsed as Json; } catch { /* not JSON-RPC: mcp-use answers */ }
    const params = obj(message?.params);
    const name = message?.method === 'tools/call' ? str(params.name) : null;
    if (!message || !name || !name.startsWith(FORGE_PREFIX)) { await next(); return; }
    let forged = registry.get(name);
    if (!forged) { await registry.sync(); forged = registry.get(name); } // published a moment ago?
    if (!forged) return toolError(message.id, 'UNKNOWN_TOOL', `No published forged tool named ${name} on this endpoint.`, 'Call list_forged_tools: the tool may be retired, not yet published, or for a site outside this endpoint’s scope.');
    const { telemetry: block, ...args } = obj(params.arguments);
    const rewritten = { ...message, params: { ...params, name: CALL_FORGED_TOOL, arguments: { toolId: forged.id, args, ...(telemetry && block !== undefined ? { telemetry: block } : {}) } } };
    const headers = new Headers(raw.headers); headers.set(FORGE_CALL_HEADER, forged.mcpName); headers.delete('content-length');
    // 2026-07-28 requests mirror params.name in Mcp-Name and the SDK checks the pair (SEP-2243): rename both.
    if (headers.has('mcp-name')) headers.set('mcp-name', CALL_FORGED_TOOL);
    return server.app.fetch(new Request(raw.url, { method: 'POST', headers, body: JSON.stringify(rewritten), signal: raw.signal }));
  });

  // 3. the stable tools
  tool('request_tool', 'Ask a site\'s agent team to build a tool you need when no existing tool answers your task (Tool Forge). The builder (agentId, default the site engineer) records the gap and the tools it considered, drafts a declarative tool from allow-listed Steward operations (no generated code), Steward validates it and tests it on local data, the site\'s manager (read-only tools) or the Operations Director (any write) approves it, and it is published as forge_<name> for every connected client (notifications/tools/list_changed). Costs nothing to ask; drafting uses prepared drafts unless live generation is on. Not idempotent: each call files a request and a draft. NEXT: wait_for(event "any", siteId, filter {type: "tool", toolId, status: "published"}) without polling; then call forge_<name>, or call_forged_tool(toolId, args) from a client that does not re-list tools.',
    z.strictObject({
      siteId, task: z.string().min(10).max(1000).describe('The question the tool must answer, in plain words, e.g. "Which pumps went over their pressure spec more than three times in the last 7 days, and who is responsible for each?"'),
      agentId: agentId.optional().describe('Who builds it: one of the site\'s own agents (manager, engineer, compliance, technician). Omit for the site engineer.'),
    }), RequestOutSchema, async ({ siteId: site, task, agentId: builderArg }, call) => {
      const builder = builderArg ?? agentOf(site, 'engineer');
      if (siteOfAgent(builder) !== site) throw new AdapterError('INVALID_ARGUMENT', `${builder} is not on ${site}'s team; a tool for ${site} is built by one of its own agents.`, `Pass agentId ${(['manager', 'engineer', 'compliance', 'technician'] as const).map(role => agentOf(site, role)).join(', ')}, or omit it for the site engineer.`);
      const raw = obj(await backend.json('/api/tools/requests', ANY, { method: 'POST', body: { agentId: builder, siteId: site, task, requestedBy: call.actor, requester: call.requester } }));
      const forged = normaliseForgedTool(obj(raw.tool)) ?? (raw.name ? normaliseForgedTool(raw) : null);
      if (forged?.siteId && !inScope(forged.siteId)) throw new AdapterError('PROPERTY_SCOPE', 'The backend drafted the tool for a site outside this endpoint’s scope.', 'Check backend scope isolation; call list_forged_tools.');
      const toolId = str(raw.toolId) ?? forged?.id ?? null;
      const why = obj(raw.why);
      const considered = list(raw.consideredTools ?? why.consideredTools).map(item => ({ name: str(item.name) ?? 'tool', whyNot: str(item.whyNot) ?? '' }));
      return {
        requestId: str(raw.requestId) ?? (forged ? str(raw.id) : null), toolId, name: forged?.name ?? null, mcpName: forged?.mcpName ?? null, status: str(raw.status) ?? forged?.status ?? 'requested',
        siteId: site, agentId: builder, requestedBy: call.actor, gap: str(raw.gap) ?? str(why.gap) ?? forged?.why.gap ?? null,
        consideredTools: considered.length ? considered : forged?.why.consideredTools ?? [], generator: forged?.generator ?? str(raw.generator),
        nextStep: toolId ? `${waitFor(site, toolId)} holds without tokens while ${display(builder)} validates and tests it and the approver decides; then call ${forged?.mcpName ?? 'forge_<name>'} (or call_forged_tool(toolId="${toolId}", args)).` : `wait_for(event="any", siteId="${site}", filter={type:"tool"}) for the draft; list_forged_tools(siteId="${site}") shows it.`,
      };
    }, LOCAL_WRITE);

  tool('list_forged_tools', 'The tools Steward\'s agents built for themselves (Tool Forge): forge_<name>, status (draft, validated, tested, approved, published, rejected, retired), site, who built it and when, why (the task, the gap, the tools it considered and why not), the recipe as allow-listed steps, the test result, who approved it, usage (calls, tokens saved) and firstClass (listed in tools/list here right now). Free, read-only. NEXT: call forge_<name>, or call_forged_tool(toolId, args) from a client that does not re-list tools; request_tool to ask for a new one.',
    z.strictObject({ siteId: siteId.optional().describe('Only this site\'s tools. Omit for every permitted site.'), status: z.enum([...FORGE_STATUSES, 'all']).default('all').describe('Lifecycle status, or all (default).') }),
    z.object({ tools: z.array(ForgedToolOutSchema), counts: z.record(z.string(), z.number()), firstClass: z.array(z.string()), notice: z.string(), nextStep: z.string() }), async ({ siteId: site, status }) => {
      const query = new URLSearchParams({ ...(site ? { siteId: site } : {}), ...(status !== 'all' ? { status } : {}) });
      const tools = list(await backend.json(`/api/tools${query.size ? `?${query}` : ''}`, ANY), 'tools').map(normaliseForgedTool)
        .filter((forged): forged is ForgedTool => Boolean(forged?.siteId && inScope(forged.siteId) && (!site || forged.siteId === site) && (status === 'all' || forged.status === status)));
      if (tools.some(forged => forged.status === 'published' && registry.get(forged.mcpName)?.id !== forged.id)) await registry.sync();
      const counts: Record<string, number> = {};
      for (const forged of tools) counts[forged.status] = (counts[forged.status] ?? 0) + 1;
      const out = tools.map(summary);
      return {
        tools: out, counts, firstClass: out.filter(row => row.firstClass).map(row => row.mcpName),
        notice: 'Forged tools are declarative recipes over Steward\'s own authority-checked operations; no generated code runs. Read-only tools are approved by the site\'s manager, any write by the Operations Director.',
        nextStep: out.some(row => row.firstClass) ? `Call ${out.find(row => row.firstClass)!.mcpName} directly, or call_forged_tool(toolId, args).` : 'Nothing published yet: request_tool(siteId, task) asks a site\'s team to build one.',
      };
    }, READ_ONLY);

  tool(CALL_FORGED_TOOL, 'Call a published forged tool by toolId (from list_forged_tools) with its arguments; the same as calling forge_<name> directly, for clients that do not re-list tools. The backend runs the tool\'s validated recipe inside its one site with your actor\'s authority (POST /api/tools/{id}/call), counts the call and writes telemetry. Cost: the reads the tool makes; a tool with write steps writes records (see readOnly). NEXT: act on the output; list_forged_tools for the recipe and usage.',
    z.strictObject({ toolId: idString.describe('id from list_forged_tools or request_tool.'), args: z.record(z.string(), z.unknown()).default({}).describe('Arguments for the tool, matching its inputSchema.') }),
    z.looseObject({}), async ({ toolId, args }, call) => {
      let forged = registry.byId(toolId);
      if (!forged) {
        const read = normaliseForgedTool(obj(await backend.json(`/api/tools/${enc(toolId)}`, ANY)));
        if (!read) throw new AdapterError('UPSTREAM_RESPONSE_INVALID', `The backend returned no forged tool for ${toolId}.`, 'Call list_forged_tools.', false);
        if (!read.siteId || !inScope(read.siteId)) throw new AdapterError('PROPERTY_SCOPE', 'That forged tool belongs to a site outside this endpoint’s scope.', 'Call list_forged_tools; only tools for the permitted sites run here.');
        if (read.status !== 'published') throw new AdapterError('TOOL_NOT_PUBLISHED', `${read.mcpName} is ${read.status}; only published forged tools run.`, read.status === 'retired' ? 'It was retired; list_forged_tools shows any newer version.' : `Wait for approval and publication: ${waitFor(read.siteId, read.id)}.`, false, 409);
        forged = read;
      }
      const problem = checkArgs(forged.inputSchema, args);
      if (problem) throw new AdapterError('INVALID_ARGUMENT', `${forged.mcpName}: ${problem}.`, 'Pass arguments matching the tool\'s inputSchema (list_forged_tools or tools/list shows it).');
      const raw = obj(await backend.json(`/api/tools/${enc(forged.id)}/call`, ANY, { method: 'POST', body: { args, requester: call.requester } }));
      const output = structuredOutput('output' in raw ? raw.output : 'result' in raw ? raw.result : raw);
      const text = str(raw.text) ?? JSON.stringify(output);
      // Called by its own name (re-dispatched from forge_<name>): the forged tool's own output shape.
      if (call.ctx.request?.header(FORGE_CALL_HEADER) === forged.mcpName) return new WithText(output, text);
      const usage = obj(raw.usage);
      return new WithText({
        toolId: forged.id, name: forged.mcpName, siteId: forged.siteId, version: forged.version, output,
        usage: { calls: num(usage.calls) ?? forged.usage.calls + 1, tokensSavedEstimate: num(usage.tokensSavedEstimate) ?? forged.usage.tokensSavedEstimate },
        nextStep: `Act on the output. ${forged.mcpName} is also callable directly once your client re-lists tools.`,
      }, text);
    }, LOCAL_WRITE, { describeCall: input => { const forged = registry.byId(String(input.toolId ?? '')); return forged ? { name: forged.mcpName, siteId: forged.siteId ?? undefined } : {}; } });

  return registry;
}
