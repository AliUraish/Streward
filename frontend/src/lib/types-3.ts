/* Addendum 3 types (REALITY-CONTRACT-3.md), mirrored locally because shared/types.ts belongs to the orchestrator.
   camelCase JSON, ISO UTC timestamps. Fields the contract leaves open are optional so a partial backend still renders;
   the API client (api-3.ts) normalises the obvious alternatives (arrays vs { items }). Keep in step with shared/types.ts. */
import type { Environment } from "./types-2";

export type SiteId3 = "myer-plant" | "bristol-pumps" | "tomioka-mill";
export type Severity3 = "low" | "medium" | "high";
export type PinSeverity = "none" | Severity3;
export type AgentId3 = "operator" | "atlas" | "warden:myer-plant" | "warden:bristol-pumps" | "counsel" | "runner";
export type Generator = "hand-seed" | "claude-opus-5-5" | string;

/* Every seeded or generated record carries these (section 9). */
export interface SyntheticMark { synthetic?: boolean; simulated?: boolean; generator?: Generator }

/* Section 1 and 2: the per-site register with 3-D pins in the scan's world coordinates. */
export interface Vec3 { x: number; y: number; z: number }
export type PinSource = "placed" | "estimated";
export interface Asset3 extends SyntheticMark {
  tag: string; assetTag?: string; name: string; kind: string;
  pin?: Vec3 | [number, number, number] | null; pinSource?: PinSource;
  location?: string | null; spec?: Record<string, unknown> | null;
  openIssues?: number; issueIds?: string[];
}
export interface CameraPreset { name: string; position: [number, number, number]; target: [number, number, number] }
export interface SceneCredit { scene?: string; author?: string; url?: string; text?: string }
export interface Scene3 {
  siteId: string; environment?: Environment | null; sogUrl?: string | null;
  credit?: SceneCredit | string | null; cameraPresets?: CameraPreset[];
  assets: Asset3[];
}
export interface PinInput { x: number; y: number; z: number; source: "placed" }

/* Issues on the new register; severity drives the pin colour. */
export interface Issue3 extends SyntheticMark {
  id: string; siteId?: string; assetTag: string; kind: string; severity: Severity3; summary: string;
  status?: "open" | "assigned" | "acknowledged" | "resolved" | string; at: string;
  assignedTo?: string | null; assigneeId?: string | null; ownerId?: string | null; scenarioId?: string | null; refId?: string | null; source?: string | null;
  obligationId?: string | null; documentId?: string | null; regulationIds?: string[] | null; regulationId?: string | null;
  why?: WhyRef[] | WhyRef | null; responsible?: { owner?: { id?: string; name?: string; role?: string } | null; agentName?: string | null } | null;
  fix?: unknown; disclaimer?: string | null;
  /* California (US-CA) records shown as a comparison, never as the law that binds the site. */
  comparisonRegulationIds?: string[] | null;
}
/* Why an issue matters: the regulation, its provision and our summary (contract 4 section 5). */
export interface WhyRef { regulationId?: string | null; instrument?: string | null; provision?: string | null; title?: string | null; summary?: string | null; officialUrl?: string | null; servePdf?: boolean; pageHint?: number | null; readUrl?: string | null; fileUrl?: string | null }

/* Section 10 get_overview: every site at a glance. */
export interface SeverityCounts { high: number; medium: number; low: number }
export interface ComplianceCounts { ok: number; due_soon: number; overdue: number; blocked: number }
export interface CrewOnShift { count: number; names?: string[] }
export interface SiteOverview {
  siteId: string; name?: string;
  issues: SeverityCounts; compliance: ComplianceCounts;
  crewOnShift: CrewOnShift | number;
  activeScenario?: string | null;
}
export interface AgentNow {
  agentId: string; name?: string; level?: number;
  status?: "idle" | "working" | "waiting" | string;
  currentTask?: string | null; why?: string | null; waitingOn?: string | null; since?: string | null;
}
export interface ChangeLite { version?: number; at?: string; siteId?: string; type?: string; summary?: string; actor?: string }
export interface Overview { sites: SiteOverview[]; agents: AgentNow[]; activeScenario?: ScenarioRun | null; changes?: ChangeLite[] }

/* Section 5: scenarios, started from the dashboard (demo control) or start_scenario over MCP. */
export type ScenarioId = "my-overpressure" | "my-extinguisher" | "br-sump" | "br-vessel-cert" | "ops-counsel-tokens" | "ops-injection" | "tm-humidity" | "tm-alteration-permit" | "x-heritage" | string;
export interface Scenario extends SyntheticMark {
  id: ScenarioId; siteId?: string | null; siteIds?: string[] | null; title: string; summary: string; owners: string[];
  headline?: boolean; steps?: number | unknown[]; scope?: string | null; issueKind?: string | null;
}
export interface ScenarioRun extends SyntheticMark {
  id: string; scenarioId: ScenarioId; siteId?: string | null; siteIds?: string[] | null;
  state: "running" | "completed" | "failed" | string;
  step?: number; steps?: number; startedAt: string; finishedAt?: string | null; summary?: string | null;
  origin?: "autoplay" | "manual" | string | null;
}

/* Board meetings: an ordered transcript with the resolution and the decided contact. */
export interface BoardTurn { id?: string; seq?: number; agentId: string; name?: string; text: string; at?: string; kind?: "statement" | "question" | "proposal" | "resolution" | string; transport?: string | null }
export interface BoardContact { crewMemberId?: string; name: string; role?: string; channel?: string | null; via?: string | null; contactable?: boolean; reason?: string | null; fallback?: boolean }
export interface BoardMeeting extends SyntheticMark {
  id: string; siteId?: string | null; issueId?: string | null; scenarioId?: string | null;
  title?: string; topic?: string; convenedBy?: string; participants: string[]; issueKind?: string | null;
  transcript: BoardTurn[]; resolution: string | null; contact: BoardContact | null;
  state?: "convened" | "resolved" | string; status?: string; at: string; startedAt?: string; resolvedAt?: string | null;
}

/* Section 6: people and compliance. */
export interface Certification { name: string; expiresAt: string | null; status?: "ok" | "expiring" | "expired" | string }
export interface CrewMember extends SyntheticMark {
  id: string; siteId: string; name: string; role: string;
  shift: string | { label?: string; start?: string; end?: string };
  onShift?: boolean; phone?: string | null; email?: string | null; contactable?: boolean;
  certifications: Certification[]; owns: string[];
}
export interface ContactPlan { via?: string | null; channel?: string | null; reachable?: boolean; reason?: string | null }
export interface Responsible { siteId: string; issueKind: string; crewMember: CrewMember | null; via?: string | null; reason?: string | null; channel?: string | null; fallback?: boolean; agentName?: string | null }
export type ObligationStatus = "ok" | "due_soon" | "overdue" | "blocked";
export interface Obligation extends SyntheticMark {
  id: string; siteId: string; assetTag?: string | null; title: string; ruleRef: string; frequency: string;
  lastDoneAt: string | null; dueAt: string | null; status: ObligationStatus; documentId?: string | null; ownerId: string;
  blockedBy?: string | null; blockedReason?: string | null; regulationIds?: string[] | null; regulationId?: string | null;
}
export interface Document3 extends SyntheticMark {
  id: string; siteId?: string; title: string; kind?: string; obligationId?: string | null; assetTag?: string | null;
  issuedAt?: string | null; expiresAt?: string | null; fileUrl?: string | null; mime?: string | null;
  flagged?: boolean; flagReason?: string | null; text?: string | null; reference?: string | null; issuer?: string | null;
}
export interface Notice extends SyntheticMark {
  id: string; siteId?: string; to: string; channel?: string | null; subject?: string | null; text?: string | null;
  obligationId?: string | null; sentAt: string; acknowledgedAt?: string | null; dryRun?: boolean; mode?: string | null; reason?: string | null; sender?: string | null;
}
export interface DocumentEmail extends SyntheticMark {
  id: string; from: string; to: string; documentId: string; documentTitle?: string | null; note?: string | null;
  at: string; dryRun?: boolean; status?: string | null; siteId?: string | null; reason?: string | null;
}
export interface SendDocumentInput { to: string; documentId: string; note?: string }

/* Section 2: the per-site viewer command stream (how "MCP moves the 3D view" works). */
export type ViewerAction = "focus" | "orbit" | "reset" | "highlight";
export interface ViewerCommand {
  id: string; seq?: number; siteId?: string; action: ViewerAction; assetTag?: string | null; issueId?: string | null;
  actor?: string | null; agentId?: string | null; by?: string | null; issuedBy?: string | null; issuedByName?: string | null; at?: string;
}
export interface ViewerFeed { commands: ViewerCommand[]; cursor?: number | string | null }
export interface ViewerCommandInput { action: ViewerAction; assetTag?: string; issueId?: string }

/* Section 7: waiting without tokens. */
export type WaitEvent = "work_item.resolved" | "issue.changed" | "reply.received" | "board.resolved" | "scenario.step" | "any";
export interface WaitInput { siteId?: string; event: WaitEvent; filter?: Record<string, unknown> }
export interface WaitResult { waitId: string; status: "fired" | "still_waiting" | "waiting" | string; event?: Record<string, unknown> | null }

/* Section 3: the valve inspection pipeline's results, ingested by the backend. */
export interface VisionExplanation { finding: string; evidence: string; confidence: string | number; recommendedAction: string }
export interface ValveResult extends SyntheticMark {
  assetTag: string; status: "fixed" | "not_fixed" | "uncertain"; score: number | null; threshold: number | null; model?: string | null; issueId?: string | null; ingestedAt?: string | null;
  frames?: string[]; defect?: string | null; explanation?: VisionExplanation | null; explainDryRun?: boolean;
}
export interface VisionInspection { siteId: string; ranAt?: string | null; model?: string | null; note?: string | null; results: ValveResult[] }

/* Section 8 and 10: agent activity, memory and runtime configuration. */
export interface ToolCall { id?: string; at: string; tool: string; kind?: string | null; target?: string | null; tokens?: number | null; inputTokens?: number | null; outputTokens?: number | null; ok?: boolean; ms?: number | null; synthetic?: boolean }
export interface AgentActivity {
  agentId: string; currentTask?: string | null; why?: string | null; waitingOn?: string | null;
  lastActions: ToolCall[]; tokensThisHour?: number | null; callsThisHour?: number | null; memoryHighlights?: string[]; telemetrySource?: string | null;
}
export interface MemoryItem { id: string; at?: string; text: string; kind?: string | null; refs?: Record<string, string> | null; synthetic?: boolean }
export interface AgentMemory { agentId: string; source: "supermemory" | "local" | string; container?: string | null; items: MemoryItem[]; detail?: string | null }
/* GET /api/memory: one remembered item from any agent's persistent memory (a decision, outcome, reconfiguration or
   finding), newest first. refs name the records it is about; issueId and conversationId are lifted out of them. */
export interface MemoryEntry {
  id: string; agentId: string; agentName: string; siteId: string | null; kind: string; text: string; at: string;
  refs: Record<string, string>; issueId: string | null; conversationId: string | null; origin?: string | null;
}
export interface MemoryFilters { siteId?: string; agentId?: string; query?: string; limit?: number }
export interface ConfigChange { at: string; by: string; change: Record<string, unknown>; why?: string | null; via?: string | null; version?: number }
export interface AgentConfig { agentId: string; config: Record<string, unknown>; history?: ConfigChange[]; version?: number; updatedAt?: string | null; updatedBy?: string | null }

/* Section 10 get_eval_findings and the optimisation loop (ops-counsel-tokens). */
export interface AgentFinding { agentId: string; name?: string; tokensPerMission: number | null; polls?: number | null; failures?: number | null; sessions?: number | null; missions?: number | null; tokens?: number | null; calls?: number | null; tokensThisHour?: number | null; peerMedianTokensPerMission?: number | null; ratioToPeers?: number | null }
export interface FindingFlag { agentId: string; severity: string; finding: string }
export interface LoopStep { at: string; kind: "detect" | "call" | "reconfigure" | "rerun" | string; agentId: string; summary: string; refs?: Record<string, string> | null }
export interface TokenPoint { agentId: string; before: number | null; after: number | null }
export interface OptimisationLoop { steps: LoopStep[]; tokens: TokenPoint[]; budget?: number | null; state?: string | null }
export interface ArmatureSummary { source: "armature" | "local" | string; sessions: number | null; issues?: number | null; url?: string | null; live?: boolean; detail?: string | null; error?: string | null }
export interface EvalFindings { agents: AgentFinding[]; armature?: ArmatureSummary | null; loop?: OptimisationLoop | null; at?: string | null; source?: string | null; flags?: FindingFlag[]; configs?: Record<string, Record<string, unknown>>; note?: string | null }

export type EvalSuite3 = "factory-workflow" | "safety" | "efficiency" | string;

/* ---- REALITY-CONTRACT-4.md ---------------------------------------------------------------------------------- */

/* Section 3: metrics. Points are [isoTime, value]. */
export type MetricKey = "pressure_bar" | "flow_m3h" | "temperature_c" | "level_pct" | "vibration_mms" | "power_kw" | "humidity_pct" | "checked_in" | "crack_width_mm" | string;
export interface MetricSeries extends SyntheticMark { key: MetricKey; unit?: string | null; assetTag?: string | null; label?: string | null; points: [string, number][]; spec?: { min?: number | null; max?: number | null } | null }
export interface MetricsResponse extends SyntheticMark { siteId?: string; series: MetricSeries[]; from?: string | null; to?: string | null; step?: number | string | null }
export interface SiteSummary {
  siteId: string; name?: string; avgPressure: number | null; avgFlow: number | null; uptimePct: number | null; openIssues: number | null; compliancePct: number | null; crewOnShift: number | null; agentActionsToday: number | null;
  /* The mill's figures (contract 5): relative humidity and the widest crack, absent on the pumped sites; on every site the
     employees checked in now at the badge readers (contract 7). */
  avgHumidity?: number | null; maxCrackWidth?: number | null; employeesCheckedIn?: number | null;
}
export interface MetricsSummary extends SyntheticMark { sites: SiteSummary[]; average: SiteSummary | null; at?: string | null }

/* GET /api/metrics/live[?siteId=] (contract 7 §5): every series' current 5-second reading with the one before it, the
   direction and the band state, and per site the KPIs by kind (the mean of that kind's readings; high or low when any
   reading of the kind is out of its band), plus the same across the sites. */
export type LiveTrend = "up" | "down" | "flat";
export type LiveState = "high" | "low" | "normal";
export interface LiveFigure { value: number | null; previous: number | null; delta: number | null; trend: LiveTrend; state: LiveState; unit: string | null }
export interface LiveReading extends LiveFigure { key: string; label: string | null; assetTag: string | null; spec: { min?: number | null; max?: number | null } | null }
/* pressure, flow, humidity, checkedIn, crackWidth, temperature, vibration, power, level: present when the site has that kind. */
export type LiveKpis = Partial<Record<string, LiveFigure>>;
export interface LiveSite { siteId: string; kpis: LiveKpis; readings: LiveReading[] }
export interface LiveMetrics { at: string | null; intervalSeconds: number; sites: LiveSite[]; average: LiveKpis }

/* Eval metrics (GET /api/evals/metrics), normalised to the charts the Evals page draws. */
export interface EvalMetrics3 {
  passRate: { suite: string; points: [string, number][] }[];
  passRateBars: { suite: string; value: number; runs: number | null }[];
  tokensPerMission: { agentId: string; value: number }[];
  toolCallsPerMission: { label: string; value: number }[];
  wait: { heldSeconds: number | null; tokensAvoided: number | null; waits: number | null };
  latency: { p50: number | null; p95: number | null; unit: string };
  a2aPerDay: [string, number][];
  cost: { value: number | null; currency: string; note?: string | null };
  source?: string | null; synthetic?: boolean;
}

/* Section 4: every agent-to-agent exchange is a conversation. A "call" is an Inkbox A2A conversation, never a phone call. */
export interface ConversationTurn { speaker: string; text: string; at?: string | null }
export interface ConversationAction { owner: string; task: string; due?: string | null }
export interface ConversationSummary { headline: string; points: string[]; decisions: string[]; actions: ConversationAction[] }
export interface Conversation extends SyntheticMark {
  id: string; kind: "call" | "meeting" | "message" | string; participants: string[]; siteIds: string[];
  transport?: "inkbox" | "local" | string; providerTaskIds?: string[]; transcript: ConversationTurn[];
  summary: ConversationSummary | null; summaryBy?: string | null; startedAt: string; endedAt?: string | null;
  title?: string | null; scenarioId?: string | null; issueId?: string | null; convener?: string | null; status?: string | null;
}

/* Section 5: regulations, real sources cached locally with attribution, explained in our own words. */
export interface Regulation {
  id: string; jurisdiction: "ENG-UK" | "VIC-AU" | "JP" | string; instrument: string; provision?: string | null; title: string;
  officialUrl?: string | null; pdfPath?: string | null; licence?: string | null; retrievedAt?: string | null; summary?: string | null;
  appliesTo?: string[] | string | null;
  /* Additive fields of backend/seed/regulations: servePdf says whether the licence lets us serve the cached copy. */
  siteIds?: string[]; sourceType?: "legislation" | "guidance" | string; pdfUrl?: string | null; pageHint?: number | null;
  version?: string | null; licenceUrl?: string | null; servePdf?: boolean; synthetic?: boolean;
  /* Japan (contract 5): the English translation beside the Japanese text, and the article number as written (第43条). */
  translationUrl?: string | null; englishUrl?: string | null; provisionJa?: string | null; titleJa?: string | null; instrumentJa?: string | null;
  /* A comparison record (California, US-CA): what the rule would be if the site were there; not binding here. */
  comparison?: boolean; binding?: boolean; comparisonFor?: string[] | null;
}
export interface FixStep { key: string; title: string; state: "pending" | "running" | "done" | "failed" | string; at?: string | null; summary?: string | null }
export interface FixRun { id?: string | null; issueId: string; state: string; steps: FixStep[]; startedAt?: string | null }

/* Section 6 and 7: notifications and maintenance windows. */
export interface Notification3 extends SyntheticMark { id: string; siteId?: string | null; to: string; role?: string | null; channel?: string | null; text: string; at: string; mode?: string | null }
export interface MaintenanceWindow extends SyntheticMark { id: string; siteIds: string[]; date: string; scope: string; examiner?: string | null; status: "proposed" | "approved" | "done" | string; conversationId?: string | null; title?: string | null }

/* Section 2: the agent eye. */
export interface VisiblePin { assetTag: string; x: number; y: number; distance?: number | null; occluded?: boolean }
export interface EyeFrame { id: string; seq?: number; siteId?: string; frameUrl: string; action?: string | null; params?: Record<string, unknown> | null; actor?: string | null; at: string; camera?: { position?: number[]; target?: number[]; fov?: number } | null; visiblePins: VisiblePin[] }
export interface EyeFeed { siteId: string; frames: EyeFrame[]; operating?: { actor?: string | null; action?: string | null; at?: string | null } | null; renderers?: { rendererId: string; lastSeenAt?: string | null; stale?: boolean }[] }

/* ---- REALITY-CONTRACT-6.md: the Tool Forge. An agent that lacks a tool drafts one; Steward validates and tests it, a
   manager or the Director approves it, and it is published to MCP as forge_<name>. Declarative only: steps are
   allow-listed, authority-checked Steward operations and pure transforms; no generated code ever runs. */
export type ToolStatus = "draft" | "validated" | "tested" | "approved" | "published" | "rejected" | "retired" | string;
export interface ToolStep { id: string; op: string; args: Record<string, string> }
export interface ToolTest { input: unknown; output: unknown; passed: boolean; ms: number | null; at: string | null; notes: string[] }
export interface ToolWhy { task: string; requestedBy: string; gap: string; consideredTools: { name: string; whyNot: string }[] }
export interface ToolUsage { calls: number; lastCalledAt?: string | null; tokensSavedEstimate: number | null; history: [string, number][] }
export interface ToolEvent { at: string; status: string; by?: string | null; note?: string | null }
export interface ForgedTool extends SyntheticMark {
  id: string; name: string; version: number; status: ToolStatus; siteId: string;
  createdBy: string; createdAt: string; approvedBy?: string | null; approvedAt?: string | null;
  rejectedBy?: string | null; rejectedReason?: string | null; retiredAt?: string | null;
  why: ToolWhy; description: string; inputSchema: Record<string, unknown>; steps: ToolStep[];
  output: { template: string; schema: Record<string, unknown> } | null;
  readOnly: boolean | null; test: ToolTest | null; usage: ToolUsage;
  history?: ToolEvent[]; previousVersionId?: string | null;
  /* Dashboard only: one of the contract's two demo tools, shown before the backend serves any. */
  placeholder?: boolean;
}
export interface ToolRequestInput { agentId: string; siteId: string; task: string }
export interface ToolRequestResult { tool: ForgedTool | null; toolId: string | null; requestId: string | null; gap: string | null; consideredTools: { name: string; whyNot: string }[] }
