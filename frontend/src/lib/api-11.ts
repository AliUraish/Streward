/* What an agent sees of a site (GET /api/agent-environment/{siteId}, JSON and ?format=md) and the Site Inspector's site
   tours for MCP agents (GET /api/site-tours). Field names follow the backend; obvious alternatives are accepted so a
   partial answer still renders, and every loader throws the ApiError of api.ts so a 404 reads as "not available yet". */
import { ApiError, request } from "./api";
import { list } from "./api-3";
import { agentName, rn } from "./sites-3";

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const obj = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? v as Raw : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => typeof v === "string" && v.trim() ? v.trim() : typeof v === "number" && Number.isFinite(v) ? String(v) : null;
const num = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v)) ? Number(v) : null;
const enc = encodeURIComponent;

export interface EnvMark { x: number; y: number; note: string | null }
export interface EnvLabel { assetTag: string; assetName: string | null; verdict: "good" | "bad" | string; color: string | null; title: string; reasons: string[]; regulationIds: string[]; frameUrl: string | null; at: string | null; mark: EnvMark | null }
export interface EnvFrame { id: string; url: string; assetTag: string | null; at: string | null; actorName: string | null; labels: EnvLabel[] }
export interface EnvWalk { state: string | null; agentId: string | null; agentName: string | null; stopIndex: number | null; stops: number | null; assetTag: string | null; assetName: string | null; moving: boolean; startedAt: string | null }
export interface EnvTool { name: string; purpose: string }
export interface AgentEnvironment {
  siteId: string; siteName: string | null; at: string | null;
  summary: { compliancePercent: number | null; openIssues: number | null; overdue: number | null; blocked: number | null; employeesCheckedIn: number | null; crewOnShift: number | null };
  walk: EnvWalk | null; frames: EnvFrame[]; labels: EnvLabel[]; tools: EnvTool[]; raw: Raw;
}
function mark(v: unknown): EnvMark | null {
  const m = obj(v); const x = num(m.x), y = num(m.y);
  return x === null || y === null ? null : { x, y, note: str(m.note) };
}
function label(v: unknown): EnvLabel {
  const l = obj(v);
  return { assetTag: str(l.assetTag ?? l.tag) ?? "", assetName: str(l.assetName ?? l.name), verdict: str(l.verdict) ?? "good", color: str(l.color),
    title: rn(str(l.title)) ?? (str(l.verdict) === "bad" ? "Looks bad" : "Looks good"), reasons: arr(l.reasons).map(r => rn(str(r)) ?? "").filter(Boolean),
    regulationIds: arr(l.regulationIds).map(r => str(r) ?? "").filter(Boolean), frameUrl: str(l.frameUrl), at: str(l.at), mark: mark(l.mark) };
}
export function normaliseEnvironment(raw: unknown, siteId: string): AgentEnvironment {
  const e = obj(raw); const s = obj(e.summary); const w = e.walk && typeof e.walk === "object" ? obj(e.walk) : null; const eye = obj(e.eye);
  return {
    siteId: str(e.siteId) ?? siteId, siteName: str(e.siteName), at: str(e.at),
    summary: { compliancePercent: num(s.compliancePercent ?? s.compliancePct), openIssues: num(s.openIssues), overdue: num(s.overdue), blocked: num(s.blocked),
      employeesCheckedIn: num(s.employeesCheckedIn ?? s.checkedIn), crewOnShift: num(s.crewOnShift) },
    walk: w ? { state: str(w.state), agentId: str(w.agentId), agentName: rn(str(w.agentName)) ?? (str(w.agentId) ? agentName(str(w.agentId)) : null), stopIndex: num(w.stopIndex ?? w.stop),
      stops: num(w.stops ?? w.of), assetTag: str(w.assetTag), assetName: str(w.assetName), moving: Boolean(w.moving ?? w.walking), startedAt: str(w.startedAt) } : null,
    frames: arr(eye.frames ?? e.frames).map(f => { const x = obj(f); return { id: str(x.id) ?? "", url: str(x.url ?? x.frameUrl) ?? "", assetTag: str(x.assetTag), at: str(x.at), actorName: rn(str(x.actorName)), labels: arr(x.labels).map(label) }; }).filter(f => f.url),
    labels: arr(e.labels).map(label).filter(l => l.assetTag),
    tools: arr(e.tools).map(t => { const x = obj(t); return { name: str(x.name) ?? "", purpose: str(x.purpose ?? x.description) ?? "" }; }).filter(t => t.name),
    raw: e,
  };
}

export interface TourStop { n: number; assetTag: string; assetName: string | null; verdict: string; color: string | null; title: string; reasons: string[]; frameId: string | null; frameUrl: string | null; at: string | null }
export interface SiteTour { id: string; siteId: string; siteName: string | null; requester: string | null; requesterName: string | null; guideName: string; state: string; stops: TourStop[]; findings: TourStop[]; summary: string | null; startedAt: string | null; finishedAt: string | null }
function stop(v: unknown, i: number): TourStop {
  const s = obj(v);
  return { n: num(s.n) ?? i + 1, assetTag: str(s.assetTag ?? s.tag) ?? "", assetName: str(s.assetName ?? s.name), verdict: str(s.verdict) ?? "good", color: str(s.color),
    title: rn(str(s.title)) ?? (str(s.verdict) === "bad" ? "Looks bad" : "Looks good"), reasons: arr(s.reasons).map(r => rn(str(r)) ?? "").filter(Boolean),
    frameId: str(s.frameId), frameUrl: str(s.frameUrl ?? s.url), at: str(s.at) };
}
export function normaliseTour(raw: unknown): SiteTour {
  const t = obj(raw);
  const stops = arr(t.stops).map(stop);
  const findings = t.findings ? arr(t.findings).map(stop) : stops.filter(s => s.verdict === "bad");
  return { id: str(t.id) ?? "", siteId: str(t.siteId) ?? "", siteName: str(t.siteName), requester: str(t.requester), requesterName: rn(str(t.requesterName)) ?? str(t.requester),
    guideName: rn(str(t.guideName)) ?? "Site Inspector", state: str(t.state ?? t.status) ?? "running", stops, findings, summary: rn(str(t.summary)), startedAt: str(t.startedAt), finishedAt: str(t.finishedAt) };
}

export const environmentPath = (siteId: string, md = false) => `/api/agent-environment/${enc(siteId)}${md ? "?format=md" : ""}`;
export const toursPath = (siteId?: string, limit = 5) => `/api/site-tours?${new URLSearchParams({ ...(siteId ? { siteId } : {}), limit: String(limit) })}`;

async function requestText(path: string): Promise<string> {
  const response = await fetch(path, { cache: "no-store", headers: { Accept: "text/markdown, text/plain, */*" } });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); detail = typeof body.detail === "string" ? body.detail : detail; } catch { /* not JSON */ }
    throw new ApiError(detail, response.status);
  }
  const type = response.headers.get("content-type") ?? "";
  if (type.includes("json")) { const body = obj(await response.json()); return str(body.markdown ?? body.text) ?? ""; }
  return response.text();
}

export const api11 = {
  environment: async (siteId: string) => normaliseEnvironment(await request<unknown>(environmentPath(siteId)), siteId),
  environmentText: (siteId: string) => requestText(environmentPath(siteId, true)),
  tours: async (siteId?: string, limit = 5) => list<unknown>(await request<unknown>(toursPath(siteId, limit)), "tours", "items").map(normaliseTour)
    .sort((a, b) => (b.startedAt ?? "").localeCompare(a.startedAt ?? "")),
};
