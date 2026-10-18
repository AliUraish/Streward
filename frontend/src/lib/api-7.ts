/* Contract 7 (REALITY-CONTRACT-7.md): walkthroughs (patrols), the green and blue labels they leave on assets, the
   owner alerts that email and call the owner, and the latest calls for the dashboard-wide call notifier. Field names
   follow the contract; obvious alternatives are accepted so a partial backend still renders. Every loader throws the
   ApiError of api.ts, so a 404 reads as "not available yet" through useRemote's readiness. */
import { actorHeaders, request } from "./api";
import { api3, list } from "./api-3";
import { agentName, canonicalId, rn } from "./sites-3";
import type { Conversation } from "./types-3";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const obj = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? v as Raw : {});
const str = (v: unknown): string | null => typeof v === "string" && v.trim() ? v : typeof v === "number" && Number.isFinite(v) ? String(v) : null;
const num = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) ? Number(v) : null;
const enc = encodeURIComponent;
const qs = (values: Record<string, string | number | undefined | null>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  return q.size ? `?${q}` : "";
};
/* Strings from a string, a list of strings, or a list of records that carry one under a usual key. */
export function strings(v: unknown, ...keys: string[]): string[] {
  const one = (x: unknown) => { if (typeof x !== "object" || x === null) return str(x); const o = obj(x); for (const k of [...keys, "assetTag", "tag", "id", "text", "name"]) { const s = str(o[k]); if (s) return s; } return null; };
  if (Array.isArray(v)) return v.map(one).filter((x): x is string => Boolean(x));
  const s = one(v); return s ? [s] : [];
}
const vec = (v: unknown): [number, number, number] | null => {
  if (Array.isArray(v) && v.length === 3 && v.every(n => typeof n === "number" && Number.isFinite(n))) return v as [number, number, number];
  const o = obj(v); const x = num(o.x), y = num(o.y), z = num(o.z);
  return x !== null && y !== null && z !== null ? [x, y, z] : null;
};
const byNewest = <T extends { at: string }>(a: T, b: T) => b.at.localeCompare(a.at);

/* ---- section 1: labels ----------------------------------------------------------------------------------- */
export type Verdict = "good" | "bad";
export interface WalkLabel {
  id: string; patrolId: string | null; siteId: string; assetTag: string; assetName: string | null;
  /* Green means looks good, blue means looks bad; the words always say which. */
  verdict: Verdict; title: string; reasons: string[]; compliance: boolean; regulationIds: string[];
  obligationId: string | null; issueId: string | null; frameId: string | null; frameUrl: string | null;
  world: [number, number, number] | null; agentId: string | null; agentName: string; at: string;
}
export function normaliseLabel(raw: unknown, siteId: string): WalkLabel {
  const l = obj(raw);
  const v = (str(l.verdict) ?? "").toLowerCase(); const color = (str(l.color) ?? "").toLowerCase();
  const verdict: Verdict = v === "bad" || v === "good" ? v : color === "blue" ? "bad" : "good";
  const frameId = str(l.frameId ?? l.evidenceFrameId);
  const agentId = str(l.agentId ?? l.by ?? l.actor);
  return {
    id: str(l.id) ?? `${siteId}:${str(l.assetTag) ?? ""}`, patrolId: str(l.patrolId), siteId: str(l.siteId) ?? siteId,
    assetTag: str(l.assetTag ?? l.tag) ?? "", assetName: rn(str(l.assetName ?? l.name)),
    verdict, title: str(l.title) ?? (verdict === "good" ? "Looks good" : "Looks bad"),
    reasons: strings(l.reasons ?? l.reason).map(r => rn(r)), compliance: Boolean(l.compliance),
    regulationIds: strings(l.regulationIds ?? l.regulationId), obligationId: str(l.obligationId), issueId: str(l.issueId),
    frameId, frameUrl: str(l.frameUrl ?? l.frame_url) ?? (frameId ? `/api/eye/frames/${enc(frameId)}.jpg` : null),
    world: vec(l.world ?? l.pin), agentId: agentId ? canonicalId(agentId) : null,
    agentName: rn(str(l.agentName)) ?? agentName(agentId ? canonicalId(agentId) : null), at: str(l.at ?? l.createdAt) ?? "",
  };
}

/* ---- section 1: walkthroughs ----------------------------------------------------------------------------- */
export interface PatrolStop { assetTag: string; labelId: string | null; verdict: Verdict | null; frameId: string | null; at: string | null }
export interface Patrol {
  id: string; siteId: string; agentId: string | null; agentName: string | null;
  state: "running" | "completed" | "canceled" | "failed" | string; origin: string | null;
  route: string[]; stopIndex: number; stops: PatrolStop[]; startedAt: string; finishedAt: string | null; summary: string | null; alertIds: string[];
}
export function normalisePatrol(raw: unknown): Patrol {
  const o = obj(raw); const p = o.patrol && typeof o.patrol === "object" ? obj(o.patrol) : o;
  const stops = list<Raw>(p, "stops").map(s => {
    const v = (str(s.verdict) ?? "").toLowerCase();
    return { assetTag: str(s.assetTag ?? s.tag) ?? "", labelId: str(s.labelId), verdict: v === "good" || v === "bad" ? v as Verdict : null, frameId: str(s.frameId), at: str(s.at) };
  });
  const agentId = str(p.agentId ?? p.agent ?? p.actor);
  return {
    id: str(p.id ?? p.patrolId) ?? "", siteId: str(p.siteId) ?? "", agentId: agentId ? canonicalId(agentId) : null,
    agentName: rn(str(p.agentName)) ?? (agentId ? agentName(canonicalId(agentId)) : null),
    state: (str(p.state ?? p.status) ?? "running").toLowerCase(), origin: str(p.origin),
    route: strings(p.route), stopIndex: num(p.stopIndex ?? p.stop ?? p.index) ?? stops.length, stops,
    startedAt: str(p.startedAt ?? p.at ?? p.createdAt) ?? "", finishedAt: str(p.finishedAt ?? p.endedAt), summary: rn(str(p.summary)),
    alertIds: strings(p.alertIds),
  };
}

/* ---- section 2: owner alerts ----------------------------------------------------------------------------- */
export interface AlertStep { name: string; at: string | null; summary: string | null; status: string | null }
export interface AlertAttachment { filename: string; contentType: string | null; size: number | null }
export type DeliveryMode = "sent" | "dry_run" | "capped" | "failed" | string;
export interface AlertEmail { mode: DeliveryMode; subject: string | null; attachments: AlertAttachment[]; reason: string | null; at: string | null }
export interface AlertCall { mode: DeliveryMode; brief: string | null; reason: string | null; at: string | null }
export interface OwnerAlert {
  id: string; siteId: string; obligationId: string | null; issueId: string | null; labelId: string | null; patrolId: string | null;
  title: string; severity: string | null; steps: AlertStep[]; conversationIds: string[]; email: AlertEmail | null; call: AlertCall | null; at: string;
}
/* The owner's address and number stay out of the record the dashboard keeps: "Emailed you" says who. */
export function normaliseAlert(raw: unknown): OwnerAlert {
  const a = obj(raw); const e = a.email ? obj(a.email) : null; const c = a.call ? obj(a.call) : null;
  const mode = (o: Raw) => (str(o.mode ?? o.status) ?? "").toLowerCase().replace(/[\s-]+/g, "_");
  return {
    id: str(a.id) ?? "", siteId: str(a.siteId) ?? "", obligationId: str(a.obligationId), issueId: str(a.issueId), labelId: str(a.labelId), patrolId: str(a.patrolId),
    title: rn(str(a.title ?? a.subject)) ?? "Compliance alert", severity: str(a.severity),
    steps: list<Raw>(a, "steps").map(s => ({ name: str(s.name ?? s.step ?? s.key) ?? "", at: str(s.at), summary: rn(str(s.summary ?? s.text)), status: str(s.status) })),
    conversationIds: strings(a.conversationIds),
    email: e ? { mode: mode(e), subject: rn(str(e.subject)), reason: rn(str(e.reason)), at: str(e.at),
      attachments: list<Raw>(e, "attachments").map(x => ({ filename: str(x.filename ?? x.name) ?? "attachment", contentType: str(x.contentType ?? x.content_type), size: num(x.size) })) } : null,
    call: c ? { mode: mode(c), brief: rn(str(c.brief)), reason: rn(str(c.reason)), at: str(c.at) } : null,
    at: str(a.at ?? a.createdAt) ?? "",
  };
}

export const api7 = {
  /* The latest label per asset: GET /api/properties/{siteId}/labels. */
  labels: async (siteId: string) => {
    const all = list<unknown>(await request<unknown>(`/api/properties/${enc(siteId)}/labels`), "labels").map(x => normaliseLabel(x, siteId)).filter(l => l.assetTag);
    const latest = new Map<string, WalkLabel>();
    for (const l of all) { const prev = latest.get(l.assetTag); if (!prev || l.at > prev.at) latest.set(l.assetTag, l); }
    return [...latest.values()].sort(byNewest);
  },
  patrols: async (siteId: string, limit = 1) => list<unknown>(await request<unknown>(`/api/patrols${qs({ siteId, limit })}`), "patrols").map(normalisePatrol)
    .sort((a, b) => b.startedAt.localeCompare(a.startedAt)),
  /* "Walk the site now": the operator's action; a patrol already running for the site comes back instead of a second. */
  startPatrol: async (siteId: string) => normalisePatrol(await request<unknown>("/api/patrols", { method: "POST", body: JSON.stringify({ siteId }), headers: actorHeaders("operator") })),
  ownerAlerts: async (siteId?: string, limit = 6) => list<unknown>(await request<unknown>(`/api/owner-alerts${qs({ siteId, limit })}`), "alerts", "ownerAlerts", "owner_alerts")
    .map(normaliseAlert).sort(byNewest),
  /* Calls, newest first (GET /api/conversations?kind=call): agent-to-agent calls at a site or across sites. */
  calls: async (limit = 12): Promise<Conversation[]> => (await api3.conversations({ kind: "call", limit })).filter(c => c.kind === "call")
    .map(c => ({ ...c, convener: c.convener ? canonicalId(String(c.convener)) : c.participants[0] ?? null }))
    .sort((a, b) => b.startedAt.localeCompare(a.startedAt)),
  call: (id: string) => api3.conversation(id),
};
