/* What happened, across the three sites: each site's newest changes (GET /api/properties/{id}/changes?latest=true),
   merged newest first. Raw sensor readings and their signatures are left out unless asked for: the live figures show
   them. Shared by the Logs page and the Agent view. */
import { usePoll } from "./hooks-3";
import { SITES3, rn } from "./sites-3";

export interface LogEntry { id: string; at: string; siteId: string; type: string; summary: string; refId: string | null; assetTag: string | null }
export const READING_TYPES = new Set(["fact", "attestation"]);
const HIDDEN_TYPES = new Set(["scenario"]);
export const TYPE_WORD: Record<string, string> = {
  issue: "Issue", conversation: "Chat", work_item: "Work order", eye: "Agent eye", patrol: "Walkthrough",
  compliance_alert: "Compliance", maintenance: "Maintenance", tool: "Tool", eval: "Eval", agent_config: "Agent setting",
  fix: "Fix", event: "Event", sim_event: "Event", notice: "Notice", fact: "Reading", attestation: "Signed reading",
  reply: "Reply", a2a: "Message", dispatch: "Dispatch", board_meeting: "Meeting", obligation: "Compliance", document: "Document", owner_alert: "Alert to you",
  /* Contract 8 */
  phone_call: "Phone call", outbox: "Outbox", attendance: "Attendance", inspection: "Inspection",
};
export const typeWord = (t: string) => TYPE_WORD[t] ?? t.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());

async function siteLog(siteId: string, limit: number): Promise<LogEntry[]> {
  const res = await fetch(`/api/properties/${encodeURIComponent(siteId)}/changes?latest=true&limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`changes ${res.status}`);
  const body = await res.json() as { changes?: Record<string, unknown>[] };
  return (body.changes ?? []).filter(c => !HIDDEN_TYPES.has(String(c.type ?? ""))).map(c => ({
    id: `${siteId}:${String(c.version ?? c.at ?? Math.random())}`, at: String(c.at ?? ""), siteId, type: String(c.type ?? "change"),
    summary: rn(String(c.summary ?? "")), refId: c.refId ? String(c.refId) : null, assetTag: c.assetTag ? String(c.assetTag) : null,
  }));
}

/* Every site's newest `perSite` changes, newest first; polls every `intervalMs`. */
export function useLogs(perSite = 150, intervalMs = 5_000) {
  return usePoll(async () => {
    const lists = await Promise.all(SITES3.map(s => siteLog(s.id, perSite).catch(() => [] as LogEntry[])));
    return lists.flat().filter(e => e.at).sort((a, b) => b.at.localeCompare(a.at));
  }, [perSite], intervalMs);
}

/* Where a log line leads, using the pages that exist. */
export function logHref(e: LogEntry): string | null {
  switch (e.type) {
    case "conversation": case "board_meeting": case "reply": return e.refId ? `/app/conversations?id=${encodeURIComponent(e.refId)}` : "/app/conversations";
    case "issue": case "fact": case "attestation": case "eye": case "patrol": return `/app/${e.siteId}/environment${e.assetTag ? `?asset=${encodeURIComponent(e.assetTag)}` : ""}`;
    case "maintenance": return `/app/${e.siteId}/maintenance`;
    case "compliance_alert": case "obligation": case "document": case "notice": return `/app/${e.siteId}/compliance`;
    case "tool": return `/app/${e.siteId}/tools`;
    case "phone_call": return e.refId ? `/app/conversations?call=${encodeURIComponent(e.refId)}` : "/app/conversations";
    case "outbox": return e.refId ? `/app/notifications#ob-${encodeURIComponent(e.refId)}` : "/app/notifications#outbox";
    case "attendance": return `/app/${e.siteId}/employees`;
    case "inspection": return `/app/${e.siteId}/compliance#insp-${e.siteId}-h`;
    case "eval": return "/app/evals";
    default: return `/app/${e.siteId}`;
  }
}
