import { readFile } from "node:fs/promises";
import path from "node:path";

/* Serves docs/llms.txt (owned by the integrations stream) as text/plain, read at request time so edits show without a rebuild. */
export const dynamic = "force-dynamic";

const FALLBACK = `# Steward
Agents ask the plant. The plant answers with proof, or sends someone to get it.
MCP: http://127.0.0.1:8002/mcp (tools: resolve, attest, check, get_changes, subscribe, get_receipt, escalate, query_clearance, patrol, list_sites)
docs/llms.txt has not been written yet; this is the fallback served by frontend/src/app/llms.txt/route.ts.
`;

export async function GET() {
  const candidates = [path.join(process.cwd(), "docs", "llms.txt"), path.join(process.cwd(), "..", "docs", "llms.txt")];
  let body = FALLBACK;
  for (const file of candidates) { try { body = await readFile(file, "utf8"); break; } catch { /* try the next location */ } }
  return new Response(body, { status: 200, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
}
