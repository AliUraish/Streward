/**
 * The eval harness's scenario tools. The backend plays the demo scenarios on its own (autoplay), so an agent connected
 * to this MCP never sees the scenario machinery: list_scenarios and start_scenario are left out of tools/list and
 * refused on tools/call (UNKNOWN_TOOL, as for a name this endpoint does not serve) unless BOTH
 *  - the MCP runs with STEWARD_MCP_HARNESS_TOOLS=true (config.harnessTools; never honoured when hosted), AND
 *  - the request carries X-Steward-Harness: evals (evals/run.mjs sends it on every connection, act-as ones included).
 *
 * Both gates are mcp-use's typed middleware. `mcp:tools/call` runs inside the registered tool's handler, after the SDK
 * has resolved the name and validated the arguments (see src/forge.ts), so the refusal is an isError result like any
 * other Steward tool error (both protocol eras), and the backend is never asked. Known edge: a call whose arguments fail
 * the input schema gets the SDK's validation error, which names the tool, before this gate runs. A hand-built /mcp HTTP
 * answer would avoid that but 2026-07-28 clients reject results without resultType, so it is not done here.
 * Register after every tool (server.ts does).
 */
import type { MCPServer } from 'mcp-use';
import type { RuntimeConfig } from './config.js';

export const HARNESS_TOOLS = ['list_scenarios', 'start_scenario'] as const;
/** Request header the eval harness sends (case-insensitive) with the value below. */
export const HARNESS_HEADER = 'x-steward-harness';
export const HARNESS_HEADER_VALUE = 'evals';

interface RequestLike { request?: { header(name: string): string | undefined } }

/** True only when this MCP allows the harness tools and this request is the eval harness's. */
export function harnessAllowed(config: RuntimeConfig, ctx: RequestLike | undefined): boolean {
  if (!config.harnessTools || config.hosted) return false;
  try { return (ctx?.request?.header(HARNESS_HEADER) ?? '').trim().toLowerCase() === HARNESS_HEADER_VALUE; } catch { return false; }
}

/** The text block of a refused call: the same {code, message, recovery, retryable} shape as forge.ts's toolError. */
export function unknownToolText(name: string): string {
  return JSON.stringify({ code: 'UNKNOWN_TOOL', message: `No tool named ${name} on this endpoint.`, recovery: 'Call tools/list for the tools this endpoint serves.', retryable: false });
}

export function registerHarnessGate(server: MCPServer, config: RuntimeConfig): void {
  const gated = new Set<string>(HARNESS_TOOLS);
  server.use('mcp:tools/list', async (ctx, next) => {
    const tools = await next();
    return harnessAllowed(config, ctx) ? tools : tools.filter(tool => !gated.has(tool.name));
  });
  server.use('mcp:tools/call', async (ctx, next) => {
    const name = String(ctx.params.name);
    if (!gated.has(name) || harnessAllowed(config, ctx)) return next();
    return { isError: true, content: [{ type: 'text' as const, text: unknownToolText(name) }] };
  });
}
