/**
 * The eval harness's scenario tools. The backend plays the demo scenarios on its own (autoplay), so an agent connected
 * to this MCP never sees the scenario machinery: list_scenarios and start_scenario are left out of tools/list and
 * refused on tools/call (UNKNOWN_TOOL, as for a name this endpoint does not serve) unless BOTH
 *  - the MCP runs with STEWARD_MCP_HARNESS_TOOLS=true (config.harnessTools; never honoured when hosted), AND
 *  - the request carries X-Steward-Harness: evals (evals/run.mjs sends it on every connection, act-as ones included).
 *
 * Three gates: a `mcp:tools/list` typed middleware filters the list; a /mcp HTTP middleware refuses a hidden tool's call
 * before mcp-use sees it, whatever its arguments (the SDK checks arguments before any `mcp:tools/call` middleware runs, and
 * its validation error would name the tool and its scenario ids); the `mcp:tools/call` typed middleware refuses whatever
 * reaches the handler another way. The backend is never asked. Register after every tool (server.ts does).
 *
 * The same request test decides what else a harness request sees: scenario Change rows (type "scenario", the scripts'
 * own steps) in get_changes and get_overview, and the operator's scenario and simulation authority entries.
 */
import type { MCPServer } from 'mcp-use';
import type { RuntimeConfig } from './config.js';
import { isModernRequest, toolErrorResponse } from './tooling.js';

export const HARNESS_TOOLS = ['list_scenarios', 'start_scenario'] as const;
/** Request header the eval harness sends (case-insensitive) with the value below. */
export const HARNESS_HEADER = 'x-steward-harness';
export const HARNESS_HEADER_VALUE = 'evals';
/** Authority entries that name the scenario machinery (the operator's start_scenario and simulation): harness requests only. */
export const HARNESS_AUTHORITY = /scenario|simulat/i;

interface RequestLike { request?: { header(name: string): string | undefined } }

/** True only when this MCP allows the harness tools and this request is the eval harness's. */
export function harnessAllowed(config: RuntimeConfig, ctx: RequestLike | undefined): boolean {
  if (!config.harnessTools || config.hosted) return false;
  try { return (ctx?.request?.header(HARNESS_HEADER) ?? '').trim().toLowerCase() === HARNESS_HEADER_VALUE; } catch { return false; }
}

/** A Change row of a scenario script's own step (the step's issue, fact and conversation Changes say what happened). */
export const isScenarioRow = (row: { type?: unknown } | null | undefined) => row?.type === 'scenario';

/** An agent's authority list without the scenario machinery's entries. */
export const publicAuthority = (authority: string[]) => authority.filter(entry => !HARNESS_AUTHORITY.test(entry));

/** The refusal of a hidden tool: the same {code, message, recovery, retryable} shape as forge.ts's unknown forged tool. */
export function unknownTool(name: string) {
  return { code: 'UNKNOWN_TOOL', message: `No tool named ${name} on this endpoint.`, recovery: 'Call tools/list for the tools this endpoint serves.', retryable: false };
}

export function registerHarnessGate(server: MCPServer, config: RuntimeConfig): void {
  const gated = new Set<string>(HARNESS_TOOLS);
  server.use('mcp:tools/list', async (ctx, next) => {
    const tools = await next();
    return harnessAllowed(config, ctx) ? tools : tools.filter(tool => !gated.has(tool.name));
  });
  server.app.use('/mcp', async (context, next) => {
    const raw = context.req.raw;
    if (raw.method !== 'POST' || !(context.req.header('content-type') || '').includes('json') || harnessAllowed(config, { request: context.req })) { await next(); return; }
    let message: Record<string, unknown> | null = null;
    try { const parsed = JSON.parse(await raw.clone().text()) as unknown; if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) message = parsed as Record<string, unknown>; } catch { /* not JSON-RPC: mcp-use answers */ }
    const params = message?.params && typeof message.params === 'object' && !Array.isArray(message.params) ? message.params as Record<string, unknown> : {};
    const name = message?.method === 'tools/call' && typeof params.name === 'string' ? params.name : null;
    if (!message || !name || !gated.has(name)) { await next(); return; }
    return toolErrorResponse(message.id, unknownTool(name), isModernRequest(context.req.header('mcp-protocol-version'), params));
  });
  server.use('mcp:tools/call', async (ctx, next) => {
    const name = String(ctx.params.name);
    if (!gated.has(name) || harnessAllowed(config, ctx)) return next();
    return { isError: true, content: [{ type: 'text' as const, text: JSON.stringify(unknownTool(name)) }] };
  });
}
