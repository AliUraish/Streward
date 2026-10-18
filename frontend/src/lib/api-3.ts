/* API client for REALITY-CONTRACT-3.md. Every path goes through /api/* (proxied to FastAPI on 8001).
   Paths the contract fixes are used verbatim (pin, viewer, waits, vision, send-document, agent memory). The rest follow
   the MCP tool names of section 10 and are listed in DESIGN-DECISION.md so the backend stream can confirm them.
   Responses are normalised: an array or { items | <name> : [...] } both work. */
import { ApiError, actorHeaders, request, type Actor } from "./api";
import type {
  AgentActivity, AgentConfig, AgentMemory, Asset3, BoardMeeting, CrewMember, Document3, DocumentEmail, EvalFindings,
  Issue3, Notice, Obligation, Overview, PinInput, Responsible, Scenario, ScenarioRun, Scene3, SendDocumentInput,
  ValveResult, ViewerCommand, ViewerCommandInput, ViewerFeed, VisionInspection, WaitInput, WaitResult,
} from "./types-3";
import type { AgentInfo, EvalRun, TranscriptEntry } from "./types-2";
import type { AgentNow, Conversation, EvalMetrics3, EyeFeed, FixRun, MaintenanceWindow, MetricsResponse, MetricsSummary, Notification3, Regulation, SiteOverview, SiteSummary } from "./types-3";
import { SCENARIOS3, SITE3_IDS, agentName, canonicalId, legacyOf, rn } from "./sites-3";

const enc = encodeURIComponent;
const site = (id: string) => `/api/properties/${enc(id)}`;
const qs = (values: Record<string, string | number | undefined | null>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  return q.size ? `?${q}` : "";
};
const send = <T>(method: "POST" | "PUT", path: string, body: unknown, actor: Actor = "operator") =>
  request<T>(path, { method, body: JSON.stringify(body), headers: actorHeaders(actor) });

/* Accept T[] or { items: T[] } or { <key>: T[] }. */
export function list<T>(value: unknown, ...keys: string[]): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    for (const k of [...keys, "items", "results", "data"]) if (Array.isArray(o[k])) return o[k] as T[];
  }
  return [];
}
const many = async <T>(path: string, ...keys: string[]) => list<T>(await request<unknown>(path), ...keys);

/* Try paths in order; the first that is not "not ready" (404/405/501) wins. Used only where the contract names no path. */
async function first<T>(...loaders: (() => Promise<T>)[]): Promise<T> {
  let last: unknown;
  for (const load of loaders) {
    try { return await load(); } catch (e) { last = e; if (!(e instanceof ApiError && e.notReady)) throw e; }
  }
  throw last;
}

/* Normalisers: the backend stream's field names (ops.py, boards.py, people.py, viewer.py, vision.py, memory_store.py)
   mapped onto the dashboard's shapes, so a rename on either side is one line here. */
type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const obj = (v: unknown): Raw => (v && typeof v === "object" ? v as Raw : {});
function countOf(v: unknown): number | null {
  if (typeof v === "number") return v;
  if (Array.isArray(v)) return v.length;
  const o = obj(v); for (const k of ["sessions", "issues", "items", "results", "data"]) if (Array.isArray(o[k])) return o[k].length;
  return typeof o.count === "number" ? o.count : typeof o.total === "number" ? o.total : null;
}
function normaliseScene(raw: unknown, siteId: string): Scene3 {
  if (Array.isArray(raw)) return { siteId, assets: raw as Asset3[] };
  const o = obj(raw);
  return { ...o, siteId: o.siteId ?? siteId, sogUrl: o.sogUrl ?? o.sogMetaUrl ?? null, assets: list<Asset3>(o, "assets", "components") };
}
function normaliseViewer(raw: unknown): ViewerFeed {
  if (Array.isArray(raw)) return { commands: raw as ViewerCommand[], cursor: null };
  const o = obj(raw);
  return { commands: list<ViewerCommand>(o, "commands"), cursor: o.cursor ?? o.latest ?? o.since ?? o.version ?? null };
}
function normaliseVision(raw: unknown, siteId: string): VisionInspection {
  if (Array.isArray(raw)) return { siteId, results: raw as ValveResult[] };
  const o = obj(raw);
  const results = list<ValveResult>(o, "results", "findings", "valves");
  const ranAt = o.ranAt ?? o.generatedAt ?? results.map(r => r.ingestedAt ?? "").sort().at(-1) ?? null;
  return { siteId: o.siteId ?? siteId, ranAt: ranAt || null, model: o.model ?? results.find(r => r.model)?.model ?? null, note: o.note ?? o.scoreNote ?? null, results };
}
function normaliseScenarioRun(raw: unknown): ScenarioRun | null {
  if (!raw) return null; const a = obj(raw);
  const scenarioId = a.scenarioId ?? a.id;
  return { ...a, id: a.runId ?? a.id, scenarioId, siteId: a.siteId ?? SCENARIOS3.find(s => s.id === scenarioId)?.siteId ?? null,
    state: a.state ?? a.status ?? "running", step: a.step ?? a.stepIndex, steps: a.steps ?? a.of ?? a.stepCount, startedAt: a.startedAt ?? a.at ?? "" } as ScenarioRun;
}
function normaliseOverview(raw: unknown): Overview {
  const o = obj(raw);
  return {
    sites: list<Raw>(o, "sites").map(x => ({ ...x, siteId: x.siteId ?? x.id, issues: { high: 0, medium: 0, low: 0, ...obj(x.issues) }, compliance: { ok: 0, due_soon: 0, overdue: 0, blocked: 0, ...obj(x.compliance) }, crewOnShift: x.crewOnShift ?? 0 })) as SiteOverview[],
    agents: list<Raw>(o, "agents").map(a => ({ ...a, agentId: canonicalId(a.agentId ?? a.id), currentTask: rn(a.currentTask ?? a.task ?? null), why: rn(a.why ?? null), waitingOn: rn(a.waitingOn ?? null) })) as AgentNow[],
    activeScenario: normaliseScenarioRun(o.activeScenario),
    changes: list(o, "changes", "lastChanges"),
  };
}
function normaliseMeeting(raw: unknown): BoardMeeting {
  const m = obj(raw);
  return { ...m, title: rn(m.title ?? m.topic), at: m.at ?? m.startedAt ?? "", state: m.state ?? m.status, participants: list<string>(m, "participants").map(canonicalId),
    convenedBy: canonicalId(m.convenedBy ?? "director"),
    transcript: list<Raw>(m, "transcript").map(t => ({ ...t, agentId: canonicalId(t.agentId ?? ""), text: rn(String(t.text ?? "")), id: t.id ?? (t.seq !== undefined ? String(t.seq) : undefined) })) as BoardMeeting["transcript"],
    resolution: rn(m.resolution ?? null), contact: m.contact ?? null } as BoardMeeting;
}
function normaliseDocument(raw: unknown): Document3 {
  const d = obj(raw); const flags = list<Raw>(d, "flags");
  return { ...d, kind: d.kind ?? d.docType ?? d.category, fileUrl: d.fileUrl ?? d.url ?? null, flagged: d.flagged ?? flags.length > 0,
    flagReason: d.flagReason ?? (flags[0]?.excerpt ? `Instruction-shaped text treated as data, not followed: “${String(flags[0].excerpt).slice(0, 140)}”` : null) } as Document3;
}
function normaliseNotice(raw: unknown): Notice {
  const n = obj(raw);
  return { ...n, text: rn(n.text ?? null), to: n.to ?? ([n.toName, n.toRole].filter(Boolean).join(", ") || "nobody"), sentAt: n.sentAt ?? n.at ?? "",
    subject: n.subject ?? (n.noticeKind ? String(n.noticeKind).replace(/_/g, " ") : null), dryRun: n.dryRun ?? (n.mode ? n.mode !== "sent" : undefined) } as Notice;
}
function normaliseEmail(raw: unknown): DocumentEmail {
  const e = obj(raw);
  return { ...e, note: rn(e.note ?? null), from: canonicalId(e.from ?? e.sender ?? ""), to: canonicalId(e.to ?? e.recipient ?? ""), documentTitle: rn(e.documentTitle ?? e.subject ?? null),
    dryRun: e.dryRun ?? (e.mode ? e.mode !== "sent" : undefined), status: e.status ?? e.mode ?? null } as DocumentEmail;
}
function normaliseResponsible(raw: unknown): Responsible {
  const r = obj(raw); const plan = obj(r.contactPlan);
  return { ...r, crewMember: r.crewMember ?? r.owner ?? null, via: r.via ?? plan.via ?? null, channel: r.channel ?? plan.channel ?? null, reason: r.reason ?? plan.reason ?? null } as Responsible;
}
function normaliseActivity(raw: unknown, agentId: string): AgentActivity {
  const a = obj(raw);
  return { ...a, agentId, currentTask: rn(a.currentTask ?? null), why: rn(a.why ?? null), waitingOn: rn(a.waitingOn ?? null),
    lastActions: list<Raw>(a, "lastActions", "actions").map(c => ({ ...c, target: rn(c.target ?? c.detail ?? null) })) as AgentActivity["lastActions"],
    memoryHighlights: list<unknown>(a, "memoryHighlights").map(m => rn(typeof m === "string" ? m : String(obj(m).content ?? obj(m).text ?? ""))) } as AgentActivity;
}
function normaliseMemory(raw: unknown, agentId: string): AgentMemory {
  const m = obj(raw); const sm = obj(m.supermemory);
  const local = list<Raw>(m, "items", "local").map(x => ({ id: x.id, at: x.at, text: rn(String(x.text ?? x.content ?? "")), kind: x.kind ?? null, refs: x.refs ?? null, synthetic: x.synthetic }));
  const remote = list<Raw>(sm, "results").map((x, i) => ({ id: x.id ?? `sm-${i}`, at: x.updatedAt ?? x.createdAt, text: String(x.content ?? x.memory ?? x.chunk ?? x.text ?? ""), kind: "supermemory recall" }));
  return { agentId, source: m.source ?? (sm.live ? "supermemory" : "local"), container: m.container ?? null, items: [...remote, ...local], detail: sm.detail ?? null };
}
function normaliseConfig(raw: unknown, agentId: string): AgentConfig {
  const c = obj(raw);
  return { ...c, agentId, config: obj(c.config ?? c.settings), history: list<Raw>(c, "history").map(h => ({ ...h, by: canonicalId(h.by ?? ""), why: rn(h.why ?? h.reason ?? null) })) as AgentConfig["history"] };
}
function normaliseFindings(raw: unknown): EvalFindings {
  const f = obj(raw); const a = obj(f.armature);
  const configs = Object.fromEntries(Object.entries(obj(f.configs)).map(([k, v]) => [canonicalId(k), v]));
  return { ...f, agents: list<Raw>(f, "agents").map(a => ({ ...a, agentId: canonicalId(a.agentId ?? "") })) as EvalFindings["agents"], flags: list<Raw>(f, "flags").map(x => ({ ...x, agentId: canonicalId(x.agentId ?? ""), finding: rn(String(x.finding ?? "")) })) as EvalFindings["flags"], configs: configs as EvalFindings["configs"], loop: f.loop ?? null, at: f.at ?? f.generatedAt ?? null,
    armature: f.armature ? { source: a.source ?? (a.live ? "armature" : "local"), sessions: countOf(a.sessions), issues: countOf(a.issues), url: a.url ?? null, live: Boolean(a.live), detail: a.detail ?? null, error: a.error ?? null } : null };
}


/* ---- contract 4 normalisers ---- */
const NUM = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  const o = obj(v); return typeof o.value === "number" ? o.value : null;
};
function pick(o: Raw, re: RegExp): number | null { for (const [k, v] of Object.entries(o)) if (re.test(k)) { const x = NUM(v); if (x !== null) return x; } return null; }
const pointOf = (p: unknown, ...valueKeys: string[]): [string, number] => {
  if (Array.isArray(p)) return [String(p[0]), Number(p[1])];
  const o = obj(p); let v: unknown = undefined; for (const k of [...valueKeys, "value", "v", "y"]) if (o[k] !== undefined) { v = o[k]; break; }
  return [String(o.at ?? o.t ?? o.time ?? o.day ?? o.date ?? o.startedAt ?? o.x ?? ""), Number(v)];
};
function normSiteSummary(o: Raw, siteId: string): SiteSummary {
  return { siteId: o.siteId ?? o.id ?? siteId, name: o.name, avgPressure: pick(o, /pressure/i), avgFlow: pick(o, /flow/i), uptimePct: pick(o, /uptime/i), openIssues: pick(o, /issue/i),
    compliancePct: pick(o, /complian/i), crewOnShift: pick(o, /crew/i), agentActionsToday: pick(o, /action/i) };
}
function normaliseSummary(raw: unknown): MetricsSummary {
  const o = obj(raw); let sites: SiteSummary[] = [];
  if (Array.isArray(o.sites)) sites = (o.sites as Raw[]).map(x => normSiteSummary(obj(x), x?.siteId ?? x?.id));
  else if (o.sites && typeof o.sites === "object") sites = Object.entries(o.sites as Raw).map(([k, v]) => normSiteSummary(obj(v), k));
  else for (const id of SITE3_IDS) if (o[id]) sites.push(normSiteSummary(obj(o[id]), id));
  const avgKey = Object.keys(o).find(k => /average|avg|portfolio|combined|both|two/i.test(k) && o[k] && typeof o[k] === "object");
  return { sites, average: avgKey ? normSiteSummary(obj(o[avgKey]), "average") : null, at: o.at ?? o.generatedAt ?? null, synthetic: o.synthetic };
}
function normaliseMetrics(raw: unknown, siteId: string): MetricsResponse {
  const o = obj(raw);
  const series = list<Raw>(o, "series").map(x => ({ ...x, key: x.key ?? x.id ?? x.name ?? "series", unit: x.unit ?? null,
    points: list<unknown>(x, "points", "values", "data").map(p => pointOf(p)).filter(p => p[0] && Number.isFinite(p[1])),
    spec: x.spec ?? (x.min !== undefined || x.max !== undefined ? { min: x.min ?? null, max: x.max ?? null } : null) }));
  return { ...o, siteId: o.siteId ?? siteId, series } as MetricsResponse;
}
function normaliseEvalMetrics(raw: unknown): EvalMetrics3 {
  const o = obj(raw); const key = (re: RegExp) => Object.keys(o).find(k => re.test(k));
  const asPercent = (pts: [string, number][]) => pts.every(p => p[1] <= 1) ? pts.map(p => [p[0], p[1] * 100] as [string, number]) : pts;
  const pr = o[key(/pass/i) ?? ""];
  let passRate: EvalMetrics3["passRate"] = [];
  if (Array.isArray(pr)) passRate = (pr as Raw[]).map(x => ({ suite: String(x.suite ?? x.name ?? "suite"), points: asPercent(list<unknown>(x, "points", "runs", "series").map(p => pointOf(p, "passRate", "rate", "pct"))) }));
  else if (pr && typeof pr === "object") passRate = Object.entries(pr as Raw).map(([suite, v]) => ({ suite, points: asPercent((Array.isArray(v) ? v : list<unknown>(v, "points", "runs")).map(p => pointOf(p, "passRate", "rate", "pct"))) }));
  const perAgent = (v: unknown, ...vk: string[]) => Array.isArray(v) ? (v as Raw[]).map(x => ({ agentId: canonicalId(String(x.agentId ?? x.agent ?? x.id ?? "")), value: NUM(vk.map(k => x[k]).find(y => y !== undefined) ?? x.value) ?? 0 }))
    : v && typeof v === "object" ? Object.entries(v as Raw).map(([k, x]) => ({ agentId: canonicalId(k), value: NUM(x) ?? 0 })) : [];
  const tc = o[key(/tool.?call/i) ?? ""];
  const w = o[key(/wait/i) ?? ""]; const wo = obj(w);
  const l = obj(o[key(/latency/i) ?? ""]);
  const a2a = o[key(/a2a|message/i) ?? ""];
  const c = o[key(/cost/i) ?? ""];
  return {
    passRate: passRate.filter(x => x.points.length),
    tokensPerMission: perAgent(o[key(/token.*mission|mission.*token|tokensper/i) ?? ""], "tokensPerMission", "tokens"),
    toolCallsPerMission: typeof tc === "number" ? [{ label: "All agents", value: tc }] : perAgent(tc, "toolCallsPerMission", "calls").map(x => ({ label: agentName(x.agentId), value: x.value })),
    wait: { heldSeconds: typeof w === "number" ? w : pick(wo, /held|second|time|duration/i), tokensAvoided: pick(wo, /avoid|saved/i), waits: pick(wo, /count|^waits$|number/i) },
    latency: { p50: pick(l, /p50|median/i), p95: pick(l, /p95/i), unit: typeof l.unit === "string" ? l.unit : "ms" },
    a2aPerDay: (Array.isArray(a2a) ? a2a : list<unknown>(a2a, "points", "days", "series")).map(p => pointOf(p, "count", "messages")).filter(p => p[0] && Number.isFinite(p[1])),
    cost: { value: NUM(c) ?? pick(obj(c), /usd|value|total|amount|estimate/i), currency: typeof obj(c).currency === "string" ? obj(c).currency : "USD", note: obj(c).note ?? null },
    source: o.source ?? null, synthetic: o.synthetic,
  };
}
function normaliseConversation(raw: unknown): Conversation {
  const c = obj(raw); const s = c.summary ? obj(c.summary) : null;
  return { ...c, id: String(c.id), kind: c.kind ?? "message", participants: list<string>(c, "participants").map(canonicalId),
    siteIds: list<string>(c, "siteIds").length ? list<string>(c, "siteIds") : c.siteId ? [c.siteId] : [],
    transcript: list<Raw>(c, "transcript", "turns", "messages").map(t => ({ speaker: canonicalId(String(t.speaker ?? t.agentId ?? t.from ?? "")), text: rn(String(t.text ?? "")), at: t.at ?? null })),
    summary: s ? { headline: rn(String(s.headline ?? "")), points: list<string>(s, "points").map(x => rn(String(x))), decisions: list<string>(s, "decisions").map(x => rn(String(x))),
      actions: list<Raw>(s, "actions").map(a => ({ owner: canonicalId(String(a.owner ?? "")), task: rn(String(a.task ?? "")), due: a.due ?? null })) } : null,
    startedAt: c.startedAt ?? c.at ?? "", title: rn(c.title ?? c.topic ?? null) } as Conversation;
}
/* Before /api/conversations lands, board meetings are shown as conversations of kind meeting. */
export function meetingAsConversation(m: BoardMeeting): Conversation {
  return { id: m.id, kind: "meeting", participants: m.participants, siteIds: m.siteId ? [m.siteId] : [], transport: "local", transcript: m.transcript.map(t => ({ speaker: t.agentId, text: t.text, at: t.at ?? null })),
    summary: { headline: m.title ?? "Board meeting", points: [], decisions: m.resolution ? [m.resolution] : [], actions: m.contact ? [{ owner: "director", task: `Contact ${m.contact.name}${m.contact.role ? `, ${m.contact.role}` : ""}`, due: null }] : [] },
    summaryBy: "board meeting record", startedAt: m.at, endedAt: m.resolvedAt ?? null, title: m.title ?? null, scenarioId: m.scenarioId ?? null, issueId: m.issueId ?? null, synthetic: m.synthetic };
}
const FIX_STEPS: [string, string][] = [["evidence", "Evidence"], ["call", "Call"], ["contact", "Contact"], ["fix", "Fix"], ["verify", "Verify"], ["inform", "Inform"]];
export function normaliseFix(raw: unknown, issueId: string): FixRun {
  const o = obj(raw); const f = o.fix ? obj(o.fix) : o; const steps = list<Raw>(f, "steps");
  const index = NUM(f.step ?? f.stepIndex);
  return { id: f.runId ?? f.id ?? null, issueId, state: String(f.state ?? f.status ?? (steps.length || index !== null ? "running" : "pending")), startedAt: f.startedAt ?? null,
    steps: FIX_STEPS.map(([key, title], i) => {
      const hit = steps.find(x => x.key === key || x.name === key || String(x.title ?? "").toLowerCase().startsWith(key)) ?? steps[i];
      const state = hit ? String(hit.state ?? hit.status ?? "pending") : index !== null ? (i < index ? "done" : i === index ? "running" : "pending") : "pending";
      return { key, title, state, at: hit?.at ?? null, summary: rn(hit?.summary ?? hit?.text ?? null) };
    }) };
}
function normaliseMaintenance(raw: unknown): MaintenanceWindow {
  const m = obj(raw);
  return { ...m, id: String(m.id), siteIds: list<string>(m, "siteIds").length ? list<string>(m, "siteIds") : m.siteId ? [m.siteId] : [], date: m.date ?? m.start ?? m.scheduledFor ?? "",
    scope: rn(String(m.scope ?? m.title ?? "")), status: m.status ?? "proposed" } as MaintenanceWindow;
}
function normaliseNotification(raw: unknown): Notification3 {
  const n = obj(raw);
  return { ...n, id: String(n.id), to: n.to ?? n.toName ?? n.recipient ?? "", role: n.role ?? n.toRole ?? null, text: rn(String(n.text ?? n.body ?? "")), at: n.at ?? n.sentAt ?? "" } as Notification3;
}
function normaliseEye(raw: unknown, siteId: string): EyeFeed {
  const o = obj(raw);
  const frames = list<Raw>(o, "frames", "items", "feed").map(f => {
    const id = String(f.id ?? f.frameId ?? "");
    return { ...f, id, frameUrl: f.frameUrl ?? f.url ?? (id ? `/api/eye/frames/${encodeURIComponent(id)}.jpg` : ""), actor: f.actor ? canonicalId(String(f.actor)) : null, at: f.at ?? f.createdAt ?? "",
      visiblePins: list<Raw>(f, "visiblePins", "pins").map(p => ({ assetTag: String(p.assetTag ?? p.tag ?? ""), x: Number(p.x), y: Number(p.y), distance: NUM(p.distance), occluded: Boolean(p.occluded) })) };
  }).filter(f => f.frameUrl);
  return { siteId: o.siteId ?? siteId, frames: frames as EyeFeed["frames"], renderers: list(o, "renderers") };
}
/* While the backend still stores the retired ids, read a new agent's record under its one-to-one old id. */
async function viaLegacy<T>(agentId: string, load: (id: string) => Promise<T>): Promise<T> {
  try { return await load(agentId); }
  catch (e) { const old = legacyOf(agentId); if (old && e instanceof ApiError && e.notReady) return await load(old); throw e; }
}

export const api3 = {
  /* What is going on */
  overview: async () => normaliseOverview(await request<unknown>("/api/overview")),
  agents: async () => (await many<AgentInfo>("/api/agents", "agents")).map(a => ({ ...a, id: canonicalId(a.id), currentTask: rn(a.currentTask ?? null), why: rn(a.why ?? null), waitingOn: rn(a.waitingOn ?? null) })),
  agentActivity: async (agentId: string) => normaliseActivity(await viaLegacy(agentId, id => request<unknown>(`/api/agents/${enc(id)}/activity`)), agentId),
  agentMemory: async (agentId: string, query?: string) => normaliseMemory(await viaLegacy(agentId, id => request<unknown>(`/api/agents/${enc(id)}/memory${qs({ query })}`)), agentId),
  agentConfig: async (agentId: string) => normaliseConfig(await viaLegacy(agentId, id => request<unknown>(`/api/agents/${enc(id)}/config`)), agentId),
  transcript: async (agentId: string, since = 0, limit = 200) => (await viaLegacy(agentId, id => many<TranscriptEntry>(`/api/agents/${enc(id)}/transcript${qs({ since, limit })}`, "entries")))
    .map(e => ({ ...e, agentId: canonicalId(e.agentId), counterpart: canonicalId(e.counterpart), text: rn(e.text) })),
  sendDocument: (agentId: string, body: SendDocumentInput) => send<DocumentEmail>("POST", `/api/agents/${enc(agentId)}/send-document`, body, agentId as Actor),

  /* Scenarios (demo control: the dashboard starts them as the operator) */
  scenarios: async () => (await many<Scenario>("/api/scenarios", "scenarios")).map(x => ({ ...x, title: rn(x.title), summary: rn(x.summary), owners: (x.owners ?? []).map(canonicalId) })),
  scenarioRun: async (runId: string) => normaliseScenarioRun(await request<unknown>(`/api/scenario-runs/${enc(runId)}`)),
  startScenario: async (scenarioId: string) => normaliseScenarioRun(await first<unknown>(
    () => send<unknown>("POST", `/api/scenarios/${enc(scenarioId)}/start`, {}),
    () => send<unknown>("POST", "/api/scenarios/start", { scenarioId }),
  )),

  /* Board meetings */
  boardMeetings: async (filters: { siteId?: string; issueId?: string } = {}) => (await many<unknown>(`/api/board-meetings${qs(filters)}`, "meetings", "boardMeetings")).map(normaliseMeeting),
  boardMeeting: async (meetingId: string) => normaliseMeeting(await request<unknown>(`/api/board-meetings/${enc(meetingId)}`)),

  /* 3-D scene, pins and the viewer command stream */
  scene: (siteId: string) => first<Scene3>(
    async () => normaliseScene(await request<unknown>(`${site(siteId)}/scene`), siteId),
    async () => normaliseScene(await request<unknown>(`${site(siteId)}/assets`), siteId),
  ),
  placePin: (siteId: string, assetTag: string, pin: PinInput) => send<Asset3>("PUT", `${site(siteId)}/assets/${enc(assetTag)}/pin`, pin),
  viewer: async (siteId: string, since?: number | string | null) => normaliseViewer(await request<unknown>(`${site(siteId)}/viewer${qs({ since: since ?? undefined })}`)),
  viewerCommand: (siteId: string, body: ViewerCommandInput) => send<ViewerCommand>("POST", `${site(siteId)}/viewer`, body),

  /* Issues */
  issues: async (siteId: string, status?: string) => (await many<Issue3>(`${site(siteId)}/issues${qs({ status })}`, "issues")).map(i => ({ ...i, summary: rn(i.summary) })),
  issue: async (issueId: string) => { const i = await request<Issue3>(`/api/issues/${enc(issueId)}`); return { ...i, summary: rn(i.summary) }; },
  fixIssue: async (issueId: string) => normaliseFix(await send<unknown>("POST", `/api/issues/${enc(issueId)}/fix`, {}), issueId),
  assignIssue: (issueId: string, crewMemberId: string) => send<Issue3>("POST", `/api/issues/${enc(issueId)}/assign`, { crewMemberId }),

  /* Valve inspection (vision/ results ingested by the backend) */
  vision: async (siteId: string) => normaliseVision(await request<unknown>(`${site(siteId)}/inspections/vision`), siteId),
  ingestVision: (siteId: string) => send<VisionInspection>("POST", `${site(siteId)}/inspections/vision`, {}),
  /* Frames: a URL the backend gives is used as is; a bare file name is looked up under the vision frames route. */
  frameUrl: (siteId: string, assetTag: string, frame: string) => /^(https?:|data:|\/)/.test(frame) ? frame : `/api/vision/frames/${enc(siteId)}/${enc(assetTag)}/${enc(frame.split("/").pop() ?? frame)}`,

  /* People and compliance */
  crew: (siteId: string) => many<CrewMember>(`${site(siteId)}/crew`, "crew"),
  responsible: async (siteId: string, issueKind: string) => normaliseResponsible(await request<unknown>(`${site(siteId)}/responsible${qs({ issueKind })}`)),
  obligations: (siteId: string, status?: string) => many<Obligation>(`${site(siteId)}/obligations${qs({ status })}`, "obligations"),
  requestDocument: (siteId: string, obligationId: string) => send<Notice>("POST", `${site(siteId)}/obligations/${enc(obligationId)}/request-document`, {}, "counsel"),
  documents: async (siteId: string) => (await many<unknown>(`${site(siteId)}/documents`, "documents")).map(normaliseDocument),
  document: async (documentId: string) => normaliseDocument(await request<unknown>(`/api/documents/${enc(documentId)}`)),
  documentFileUrl: (documentId: string) => `/api/documents/${enc(documentId)}/file`,
  notices: async (siteId: string) => (await many<unknown>(`${site(siteId)}/notices`, "notices")).map(normaliseNotice),
  documentEmails: async (siteId?: string) => (await many<unknown>(`/api/document-emails${qs({ siteId })}`, "emails", "documentEmails")).map(normaliseEmail),

  /* Contract 4: metrics, conversations, regulations, maintenance, notifications, the agent eye */
  metricsSummary: async () => normaliseSummary(await request<unknown>("/api/metrics/summary")),
  metrics: async (siteId: string, range: { series?: string; from?: string; to?: string; step?: string | number } = {}) => normaliseMetrics(await request<unknown>(`${site(siteId)}/metrics${qs(range)}`), siteId),
  conversations: async (filters: { siteId?: string; agentId?: string } = {}) => (await many<unknown>(`/api/conversations${qs(filters)}`, "conversations")).map(normaliseConversation),
  conversation: async (id: string) => normaliseConversation(await request<unknown>(`/api/conversations/${enc(id)}`)),
  regulations: async (siteId?: string) => (await many<Regulation>(`/api/regulations${qs({ siteId })}`, "regulations")),
  regulationFileUrl: (id: string) => `/api/regulations/${enc(id)}/file`,
  maintenance: async (siteId?: string) => (await many<unknown>(`/api/maintenance${qs({ siteId })}`, "windows", "maintenance")).map(normaliseMaintenance),
  notifications: async (siteId?: string) => (await many<unknown>(`/api/notifications${qs({ siteId })}`, "notifications")).map(normaliseNotification),
  a2aTasks: async (siteId?: string) => (await many<Raw>(`/api/a2a/tasks${qs({ siteId })}`, "tasks")).map(t => ({ id: String(t.id), caller: canonicalId(String(t.caller ?? "")), target: canonicalId(String(t.target ?? "")), state: String(t.state ?? ""), at: String(t.updatedAt ?? t.createdAt ?? ""), siteId: t.siteId ?? null })),
  eyeFeed: async (siteId: string, since?: string | null) => normaliseEye(await request<unknown>(`/api/eye/${enc(siteId)}/feed${qs({ since })}`), siteId),

  /* Waiting without tokens */
  createWait: (body: WaitInput) => send<{ waitId: string }>("POST", "/api/waits", body),
  wait: (waitId: string, timeout = 30) => request<WaitResult>(`/api/waits/${enc(waitId)}${qs({ timeout })}`),

  /* Evals and self-optimisation */
  evals: () => many<EvalRun>("/api/evals", "runs"),
  evalRun: (runId: string) => request<EvalRun>(`/api/evals/${enc(runId)}`),
  runEval: (suite: string) => send<EvalRun>("POST", "/api/evals/run", { suite }),
  evalMetrics: async () => normaliseEvalMetrics(await request<unknown>("/api/evals/metrics")),
  evalFindings: async (since?: string | null) => normaliseFindings(await request<unknown>(`/api/evals/findings${qs({ since })}`)),
};
