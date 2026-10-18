#!/usr/bin/env node
/**
 * Steward eval runner. Replays the suites in evals/ (mission-workflow, demo-workflow,
 * factory-workflow, safety, efficiency, vision, tool-forge) against any Steward MCP URL (tool steps, via
 * @mcp-use/client) and a backend URL (http steps, which play the technician through
 * POST /api/inbound/local or an agent through its own routes). Prints a pass/fail table per suite and exits non-zero on any failure.
 *
 *   node evals/run.mjs [--suite evals/demo-workflow.json] [--suite mission-workflow] \
 *                      [--mcp http://127.0.0.1:8002/mcp] [--backend http://127.0.0.1:8001] [--json]
 *
 * --suite takes a file path or a bare suite name (resolved to evals/<name>.json) and may repeat;
 * with no --suite every suite runs (DEFAULT_SUITES order). --workflow is kept as an alias of --suite.
 * --json prints one EvalRun-shaped object {suite, passed, failed, steps:[{name,target,result,ms,detail}], ...}
 * for a single suite, or {suites:[...], passed, failed, steps} for several.
 *
 * Environment: STEWARD_MCP_TOKEN (bearer for the MCP endpoint), STEWARD_BACKEND_TOKEN
 * (bearer for the backend's inbound route), MCP_USE_ANONYMIZED_TELEMETRY=false is set here.
 *
 * Step options (see the suite files' notes): kind tool|http|tools (tools: list the MCP's tools as {tools: [...]},
 * e.g. to wait for a forged tool to appear), tool and args/body with ${var} substitution,
 * expect (dotted paths, [n] / [-1] indexes, [key=value] array filters, operators $in $exists
 * $contains $jsonContains $matches $gte $lte $not, and a top-level $any list of alternative expectation
 * maps), capture {var: path}, until (poll a tool step until these expectations hold; timeoutMs,
 * intervalMs; carry {arg: resultPath} feeds a result value into the next call, e.g. wait_for's waitId),
 * skipIf {var: expected} (skip the step when a captured variable matches),
 * expectStatus (http), headers (http), stopOnFailure (default true), expectError (tool: the isError
 * payload {code, message, recovery} is matched by expect), actor (tool: the step runs as that agent
 * through the X-Steward-Act-As header, honoured only by an MCP started with STEWARD_MCP_ALLOW_ACT_AS=true
 * on loopback; used by the safety and efficiency suites). Every connection carries X-Steward-Harness: evals, so an
 * MCP started with STEWARD_MCP_HARNESS_TOOLS=true (loopback only) serves this runner the scenario tools
 * (list_scenarios, start_scenario) it hides from every other client. Paths: [key=value] selects the first matching
 * element, [?key=value] all of them (an array), so 'assets[?kind=valve][1].assetTag' works.
 */
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve as resolvePath } from 'node:path';
import { parseArgs } from 'node:util';
import { setTimeout as sleep } from 'node:timers/promises';

process.env.MCP_USE_ANONYMIZED_TELEMETRY ??= 'false';
const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolvePath(here, '../mcp-runtime/package.json'));
/** Default order: the mission first, so on a fresh database the agents' dispatch path runs; the demo suite then replays with a stale fact; then the addendum-3 suites. */
export const DEFAULT_SUITES = ['mission-workflow', 'demo-workflow', 'factory-workflow', 'safety', 'efficiency', 'vision', 'tool-forge'];
export const ACT_AS_HEADER = 'X-Steward-Act-As';
/** Sent on every connection: an MCP started with STEWARD_MCP_HARNESS_TOOLS=true (loopback only) then lists and serves list_scenarios / start_scenario to this runner, and to nobody else. */
export const HARNESS_HEADER = 'X-Steward-Harness';

async function loadClient() {
  // @mcp-use/client lives in mcp-runtime/node_modules; its exports map has no CommonJS condition,
  // so resolve the ESM entry from its package.json instead of require.resolve.
  const pkgDir = resolvePath(here, '../mcp-runtime/node_modules/@mcp-use/client');
  const pkg = require(resolvePath(pkgDir, 'package.json'));
  const entry = pkg.exports?.['.']?.node?.import ?? pkg.exports?.['.']?.import ?? pkg.module ?? pkg.main;
  const mod = await import(pathToFileURL(resolvePath(pkgDir, entry)).href);
  return mod.MCPClient;
}

/** A suite argument is a file path or a bare name resolved to evals/<name>.json. */
export function resolveSuite(value) {
  if (/^[A-Za-z0-9_-]+$/.test(value)) return resolvePath(here, `${value}.json`);
  return resolvePath(value);
}

// ---------------------------------------------------------------------------
// Expectation matching
// ---------------------------------------------------------------------------

export function getPath(value, path) {
  if (path === '$' || path === '') return value;
  let current = value;
  for (const token of path.match(/[^.[\]]+|\[[^\]]*\]/g) ?? []) {
    if (current === undefined || current === null) return undefined;
    if (token.startsWith('[')) {
      const inner = token.slice(1, -1);
      if (/^-?\d+$/.test(inner)) current = Array.isArray(current) ? current.at(Number(inner)) : undefined;
      else if (inner.startsWith('?')) {
        // [?key=value,...]: every matching element (an array).
        const conditions = inner.slice(1).split(',').map(part => part.split('=').map(s => s.trim()));
        current = Array.isArray(current) ? current.filter(item => item && typeof item === 'object' && conditions.every(([key, expected]) => String(item[key]) === expected)) : undefined;
      } else {
        // [key=value,key2=value2]: first array element whose fields equal the given strings.
        const conditions = inner.split(',').map(part => part.split('=').map(s => s.trim()));
        current = Array.isArray(current) ? current.find(item => item && typeof item === 'object' && conditions.every(([key, expected]) => String(item[key]) === expected)) : undefined;
      }
    } else current = current[token];
  }
  return current;
}

function deepEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

export function match(actual, expected) {
  if (expected && typeof expected === 'object' && !Array.isArray(expected)) {
    const ops = Object.keys(expected).filter(key => key.startsWith('$'));
    if (ops.length) {
      for (const op of ops) {
        const arg = expected[op];
        switch (op) {
          case '$exists': if ((actual !== undefined && actual !== null) !== Boolean(arg)) return `expected ${arg ? 'present' : 'absent'}, got ${JSON.stringify(actual)}`; break;
          case '$in': if (!arg.some(option => deepEqual(option, actual))) return `expected one of ${JSON.stringify(arg)}, got ${JSON.stringify(actual)}`; break;
          case '$contains':
            if (typeof actual === 'string') { if (!actual.includes(String(arg))) return `expected string containing ${JSON.stringify(arg)}, got ${JSON.stringify(actual)}`; }
            else if (Array.isArray(actual)) { if (!actual.some(item => deepEqual(item, arg) || (typeof item === 'string' && item.includes(String(arg))))) return `expected array containing ${JSON.stringify(arg)}, got ${JSON.stringify(actual)}`; }
            else return `expected string or array for $contains, got ${JSON.stringify(actual)}`;
            break;
          case '$jsonContains': if (!JSON.stringify(actual ?? null).includes(String(arg))) return `expected JSON containing ${JSON.stringify(arg)}, got ${JSON.stringify(actual).slice(0, 200)}`; break;
          case '$matches': {
            // "/pattern/flags" or a bare pattern, tested against the string or the JSON-serialised value.
            const parts = String(arg).match(/^\/(.*)\/([a-z]*)$/);
            const regex = new RegExp(parts ? parts[1] : String(arg), parts ? parts[2] : '');
            const haystack = typeof actual === 'string' ? actual : JSON.stringify(actual ?? null);
            if (!regex.test(haystack)) return `expected match for ${String(arg)}, got ${haystack.slice(0, 200)}`;
            break;
          }
          case '$gte': if (!(typeof actual === 'number' && actual >= arg)) return `expected >= ${arg}, got ${JSON.stringify(actual)}`; break;
          case '$lte': if (!(typeof actual === 'number' && actual <= arg)) return `expected <= ${arg}, got ${JSON.stringify(actual)}`; break;
          case '$not': { const inner = match(actual, arg); if (inner === null) return `expected NOT ${JSON.stringify(arg)}, got ${JSON.stringify(actual)}`; break; }
          default: return `unknown operator ${op}`;
        }
      }
      return null;
    }
  }
  return deepEqual(actual, expected) ? null : `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;
}

/** Returns the list of failed expectations (empty when everything holds). `$any` passes when one alternative map has no failures. */
export function checkExpectations(result, expect) {
  const failures = [];
  for (const [path, expected] of Object.entries(expect ?? {})) {
    if (path === '$any') {
      const alternatives = expected.map(alternative => checkExpectations(result, alternative));
      if (!alternatives.some(list => list.length === 0)) failures.push(`none of ${alternatives.length} alternatives held: ${alternatives.map(list => list.join(', ')).join(' | ')}`);
      continue;
    }
    const problem = match(getPath(result, path), expected);
    if (problem) failures.push(`${path}: ${problem}`);
  }
  return failures;
}

export function substitute(value, vars) {
  if (typeof value === 'string') {
    const whole = value.match(/^\$\{([A-Za-z0-9_]+)\}$/);
    if (whole) { if (!(whole[1] in vars)) throw new Error(`Unbound variable ${whole[1]}`); return vars[whole[1]]; }
    return value.replace(/\$\{([A-Za-z0-9_]+)\}/g, (_, name) => { if (!(name in vars)) throw new Error(`Unbound variable ${name}`); return String(vars[name]); });
  }
  if (Array.isArray(value)) return value.map(item => substitute(item, vars));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, substitute(item, vars)]));
  return value;
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

function toolResultData(result) {
  const text = (result.content ?? []).filter(block => block.type === 'text').map(block => block.text).join('\n');
  if (result.structuredContent) return result.structuredContent;
  try { return JSON.parse(text); } catch { return { text }; }
}

function targetOf(step) { return step.kind === 'tool' ? step.tool : step.kind === 'tools' ? 'tools/list' : `${step.method ?? 'POST'} ${step.path}`; }

export async function runWorkflow({ mcpUrl, backendUrl, workflow, mcpToken, backendToken, onStep } = {}) {
  const MCPClient = await loadClient();
  // Every connection (act-as ones included) is the eval harness's: the scenario tools are served only to it.
  const headers = { [HARNESS_HEADER]: 'evals', ...(mcpToken ? { Authorization: `Bearer ${mcpToken}` } : {}) };
  // One connection per acting agent: the default (the MCP's own STEWARD_MCP_ACTOR) plus any step.actor.
  const actors = [...new Set(workflow.steps.map(step => step.actor).filter(Boolean))];
  const servers = { steward: { url: mcpUrl, headers, timeout: 330000, oauth: false, detectMixedAuth: false } };
  for (const actor of actors) servers[`as-${actor.replace(/[^a-z0-9-]/g, '-')}`] = { url: mcpUrl, headers: { ...headers, [ACT_AS_HEADER]: actor }, timeout: 330000, oauth: false, detectMixedAuth: false };
  const client = new MCPClient({ clientInfo: { name: 'steward-eval', version: '0.4.0' }, mcpServers: servers });
  const connections = new Map();
  const connectionFor = async actor => {
    const key = actor ? `as-${actor.replace(/[^a-z0-9-]/g, '-')}` : 'steward';
    if (!connections.has(key)) connections.set(key, await client.connect(key));
    return connections.get(key);
  };
  const vars = {};
  const rows = [];
  const startedAt = new Date().toISOString();
  // Actor steps must never run as the wrong agent (as the operator, an attest meant to be refused would be accepted).
  // They run only when the MCP reports actAs: true on /health (STEWARD_MCP_ALLOW_ACT_AS=true, loopback only).
  let actAs = actors.length === 0;
  if (actors.length) {
    try { const health = await (await fetch(new URL('/health', mcpUrl), { signal: AbortSignal.timeout(5000) })).json(); actAs = health?.actAs === true; } catch { actAs = false; }
  }
  try {
    await connectionFor(undefined);
    for (const step of workflow.steps) {
      const started = Date.now();
      let data; let failures = []; let error; let skipped = false; let polls = 0; let progress = 0;
      try {
        const skipReason = Object.entries(step.skipIf ?? {}).find(([name, expected]) => name in vars && match(vars[name], expected) === null);
        if (step.actor && !actAs) { skipped = true; data = undefined; failures = [`not run: this MCP does not honour X-Steward-Act-As, so the step would run as the wrong agent; start the MCP with STEWARD_MCP_ALLOW_ACT_AS=true (loopback only)`]; }
        else if (skipReason) { skipped = true; failures = []; data = undefined; }
        else if (step.kind === 'tool' || step.kind === 'tools') {
          const args = substitute(step.args ?? {}, vars);
          // The tool name may come from an earlier step (a forged tool's forge_<name>).
          const toolName = step.kind === 'tool' ? substitute(step.tool, vars) : null;
          const until = step.until ? substitute(step.until, vars) : null;
          const deadline = Date.now() + (step.timeoutMs ?? 30000);
          const interval = step.intervalMs ?? 2000;
          const connection = await connectionFor(step.actor);
          for (;;) {
            polls += 1;
            // A progress handler makes the client send a progressToken (wait_for reports progress every 15 s), and progress resets the timeout.
            if (step.kind === 'tools') {
              data = { tools: (await connection.listTools()).map(tool => ({ name: tool.name, description: tool.description, inputSchema: tool.inputSchema, annotations: tool.annotations })) };
              if (!until) break;
              const pendingList = checkExpectations(data, until);
              if (!pendingList.length) break;
              if (Date.now() + interval > deadline) { failures.push(`timed out after ${step.timeoutMs ?? 30000} ms (${polls} polls) waiting for ${pendingList.join('; ')}`); break; }
              if (interval > 0) await sleep(interval);
              continue;
            }
            const result = await connection.callTool(toolName, args, { timeout: 330000, resetTimeoutOnProgress: true, onprogress: () => { progress += 1; } });
            data = toolResultData(result);
            if (result.isError && !step.expectError) { failures.push(`tool returned isError: ${JSON.stringify(data).slice(0, 300)}`); break; }
            if (!result.isError && step.expectError) { failures.push(`expected an error result, got ${JSON.stringify(data).slice(0, 200)}`); break; }
            if (!until) break;
            const pending = checkExpectations(data, until);
            if (!pending.length) break;
            if (Date.now() + interval > deadline) { failures.push(`timed out after ${step.timeoutMs ?? 30000} ms (${polls} polls) waiting for ${pending.join('; ')}`); break; }
            // carry {arg: path}: feed a value from this result into the next call (wait_for's waitId on still_waiting).
            for (const [arg, path] of Object.entries(step.carry ?? {})) { const value = getPath(data, path); if (value !== undefined) args[arg] = value; }
            if (interval > 0) await sleep(interval);
          }
        } else if (step.kind === 'http') {
          const body = substitute(step.body ?? {}, vars);
          const method = step.method ?? 'POST';
          const response = await fetch(`${backendUrl}${substitute(step.path, vars)}`, { method, headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(backendToken ? { Authorization: `Bearer ${backendToken}` } : {}), ...(step.headers ?? {}) }, ...(method === 'GET' ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(30000) });
          const text = await response.text();
          try { data = JSON.parse(text); } catch { data = { text }; }
          if (!response.ok && !step.expectStatus) failures.push(`HTTP ${response.status}: ${text.slice(0, 300)}`);
          if (step.expectStatus && response.status !== step.expectStatus) failures.push(`expected HTTP ${step.expectStatus}, got ${response.status}`);
        } else failures.push(`unknown step kind ${step.kind}`);
        if (!skipped && !failures.length) failures = checkExpectations(data, substitute(step.expect ?? {}, vars));
        if (!skipped && !failures.length) for (const [name, path] of Object.entries(step.capture ?? {})) {
          const captured = getPath(data, path);
          if (captured === undefined) failures.push(`capture ${name}: path ${path} is undefined`); else vars[name] = captured;
        }
      } catch (caught) { error = caught instanceof Error ? caught.message : String(caught); }
      const detail = error ?? (skipped && failures.length ? failures.join('; ') : skipped ? `skipped: ${Object.entries(step.skipIf).map(([name, expected]) => `${name} is ${JSON.stringify(vars[name])} (${JSON.stringify(expected)})`).join(', ')}` : failures.join('; ')) + (polls > 1 && !error && !failures.length ? ` (${polls} polls)` : '') + (progress ? ` (${progress} progress notifications)` : '');
      const row = { id: step.id, kind: step.kind, target: targetOf(step) + (step.actor ? ` (as ${step.actor})` : ''), ok: !error && failures.length === 0, ms: Date.now() - started, at: new Date(started).toISOString(), detail, data, ...(skipped ? { skipped: true } : {}) };
      rows.push(row);
      onStep?.(row);
      if (!row.ok && step.stopOnFailure !== false && !(step.actor && !actAs)) {
        // Later steps depend on captured values; stop to avoid cascading noise.
        for (const rest of workflow.steps.slice(workflow.steps.indexOf(step) + 1)) rows.push({ id: rest.id, kind: rest.kind, target: targetOf(rest), ok: false, ms: 0, detail: 'skipped after failure', data: undefined, skipped: true });
        break;
      }
    }
  } finally { await client.close().catch(() => {}); }
  return { name: workflow.name, suite: workflow.suite ?? workflow.name, startedAt, finishedAt: new Date().toISOString(), passed: rows.filter(row => row.ok).length, failed: rows.filter(row => !row.ok).length, rows, vars };
}

/** EvalRun-shaped step rows (REALITY-CONTRACT-2.md Evals) for the backend's eval store. */
export function evalSteps(report) {
  return report.rows.map(row => ({ name: row.id, target: row.target, result: row.ok ? 'PASS' : 'FAIL', ms: row.ms, detail: row.detail || '' }));
}

export function formatTable(report) {
  const width = Math.max(4, ...report.rows.map(row => row.id.length));
  const target = Math.max(6, ...report.rows.map(row => row.target.length));
  const lines = [`${'step'.padEnd(width)}  ${'target'.padEnd(target)}  result  ms     detail`, `${'-'.repeat(width)}  ${'-'.repeat(target)}  ------  -----  ------`];
  for (const row of report.rows) lines.push(`${row.id.padEnd(width)}  ${row.target.padEnd(target)}  ${row.ok ? (row.skipped ? 'SKIP  ' : 'PASS  ') : row.skipped ? 'SKIP  ' : 'FAIL  '}  ${String(row.ms).padStart(5)}  ${row.detail || ''}`);
  lines.push('', `${report.name}: ${report.passed} passed, ${report.failed} failed`);
  return lines.join('\n');
}

const invokedDirectly = process.argv[1] && resolvePath(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) {
  const { values } = parseArgs({ options: {
    mcp: { type: 'string', default: process.env.STEWARD_MCP_URL || 'http://127.0.0.1:8002/mcp' },
    backend: { type: 'string', default: process.env.STEWARD_BACKEND_URL || 'http://127.0.0.1:8001' },
    suite: { type: 'string', multiple: true, default: [] },
    workflow: { type: 'string', multiple: true, default: [] },
    json: { type: 'boolean', default: false }, help: { type: 'boolean', default: false },
  } });
  if (values.help) { console.log('node evals/run.mjs [--suite FILE|name]... [--mcp URL] [--backend URL] [--json]\nDefault suites: ' + DEFAULT_SUITES.join(', ')); process.exit(0); }
  const suites = [...values.suite, ...values.workflow];
  const files = (suites.length ? suites : DEFAULT_SUITES).map(resolveSuite);
  const reports = [];
  for (const file of files) {
    const workflow = JSON.parse(await readFile(file, 'utf8'));
    const report = await runWorkflow({ mcpUrl: values.mcp, backendUrl: values.backend.replace(/\/$/, ''), workflow, mcpToken: process.env.STEWARD_MCP_TOKEN, backendToken: process.env.STEWARD_BACKEND_TOKEN });
    reports.push({ ...report, file });
    if (!values.json) console.log(formatTable(report) + (files.length > 1 ? '\n' : ''));
  }
  const failed = reports.reduce((sum, report) => sum + report.failed, 0);
  const passed = reports.reduce((sum, report) => sum + report.passed, 0);
  let output = '';
  if (values.json) {
    const shaped = reports.map(report => ({ ...report, steps: evalSteps(report), mcpUrl: values.mcp, backendUrl: values.backend }));
    output = JSON.stringify(shaped.length === 1 ? { ...shaped[0], at: new Date().toISOString() } : { suites: shaped, passed, failed, startedAt: shaped[0]?.startedAt, finishedAt: new Date().toISOString(), steps: shaped.flatMap(report => report.steps.map(step => ({ ...step, name: `${report.suite}/${step.name}` }))), at: new Date().toISOString() }, null, 2) + '\n';
  } else if (files.length > 1) output = `all suites: ${passed} passed, ${failed} failed\n`;
  // Flush stdout before exiting: process.exit() can truncate a large JSON report written to a pipe.
  process.stdout.write(output, () => process.exit(failed ? 1 : 0));
}
