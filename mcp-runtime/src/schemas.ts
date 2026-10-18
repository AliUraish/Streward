import { z } from 'zod';
import { PROPERTY_IDS } from './config.js';

export const PropertyIdSchema = z.enum(PROPERTY_IDS);
export const StatusSchema = z.enum(['verified', 'pending', 'issue', 'unknown']);
/** Site environment (addendum 2): the Three.js fixture twin or a third-party Gaussian splat hosted on SuperSplat. */
export const EnvironmentSchema = z.object({
  kind: z.enum(['fixture', 'splat']), splatId: z.string().optional(), embedUrl: z.string().optional(), thumbnailUrl: z.string().optional(),
  credit: z.string(), captureNote: z.string(),
});
/**
 * Property record. Addendum 2 renames address → site, jurisdiction → operator, phase → status and adds environment;
 * both spellings are accepted so the adapter works against a backend before and after the rename.
 */
export const PropertySchema = z.object({
  id: PropertyIdSchema, name: z.string(),
  site: z.string().optional(), operator: z.string().optional(), status: z.string().optional(),
  address: z.string().optional(), jurisdiction: z.string().optional(), phase: z.string().optional(),
  environment: EnvironmentSchema.optional(),
  readiness: z.number().min(0).max(100), componentCount: z.number().int().nonnegative(),
  openIssues: z.number().int().nonnegative(), updatedAt: z.string(),
});
export const StatsSchema = z.object({
  verified: z.number().int().nonnegative(), pending: z.number().int().nonnegative(), issue: z.number().int().nonnegative(),
  unknown: z.number().int().nonnegative(), total: z.number().int().nonnegative(),
});
const Vec3Schema = z.tuple([z.number(), z.number(), z.number()]);
export const ComponentSchema = z.object({
  id: z.string(), tag: z.string(), name: z.string(), kind: z.string(), system: z.string(), subsystem: z.string(),
  status: StatusSchema, position: Vec3Schema, rotation: Vec3Schema.optional(), description: z.string(),
  confidence: z.number().min(0).max(1), requirementCount: z.number().int().nonnegative(), verifiedCount: z.number().int().nonnegative(),
});
export const RequirementSchema = z.object({
  id: z.string(), code: z.string(), title: z.string(), description: z.string(), system: z.string(), componentId: z.string(),
  status: StatusSchema, sourceId: z.string(), sourceTitle: z.string(), sourcePage: z.number().int().nonnegative(), evidence: z.string(),
});
export const EvidenceSchema = z.object({
  id: z.string(), componentId: z.string(), requirementId: z.string(), filename: z.string(), note: z.string(),
  status: StatusSchema, createdAt: z.string(), url: z.string(),
});
export const DetailSchema = ComponentSchema.extend({ requirements: z.array(RequirementSchema), evidence: z.array(EvidenceSchema) });
export const DocumentSchema = z.object({
  id: z.string(), title: z.string(), filename: z.string(), category: z.string(), jurisdiction: z.string(),
  pages: z.number().int().nonnegative(), size: z.number().nonnegative(), uploadedAt: z.string(), url: z.string(),
});
export const AgentSchema = z.object({
  id: z.string(), name: z.string(), role: z.string(), status: z.enum(['idle', 'working', 'waiting', 'error']),
  identity: z.string(), lastAction: z.string(), tools: z.array(z.string()),
});
export const JobSchema = z.object({
  id: z.string(), propertyId: PropertyIdSchema, kind: z.string(), status: z.enum(['queued', 'running', 'completed', 'failed']),
  progress: z.number().min(0).max(100), message: z.string(), result: z.record(z.string(), z.unknown()).nullable().optional(),
  createdAt: z.string(), updatedAt: z.string(),
});
export const EventSchema = z.object({
  id: z.number().int(), propertyId: PropertyIdSchema, agentId: z.string(), type: z.string(), title: z.string(), detail: z.string(),
  componentId: z.string().nullable().optional(), createdAt: z.string(),
});
export const MemorySchema = z.object({ id: z.string(), propertyId: PropertyIdSchema, content: z.string(), source: z.string(), createdAt: z.string() });
export const IntegrationSchema = z.object({
  id: z.string(), name: z.string(), description: z.string(), status: z.enum(['connected', 'local', 'not_configured', 'error']), detail: z.string(),
});
export const WorkspaceSchema = z.object({
  property: PropertySchema, components: z.array(ComponentSchema), requirements: z.array(RequirementSchema), agents: z.array(AgentSchema),
  events: z.array(EventSchema), activeJob: JobSchema.nullable(), stats: StatsSchema,
});
export const ReportSchema = z.object({
  property: PropertySchema, generatedAt: z.string(), disclosure: z.string(), stats: StatsSchema,
  components: z.array(ComponentSchema), requirements: z.array(RequirementSchema), documents: z.array(DocumentSchema), evidence: z.array(EvidenceSchema),
});
export const HealthSchema = z.object({ status: z.string(), database: z.string(), mode: z.string() });

// ---- Reality layer (mirrors REALITY-CONTRACT.md / shared/types.ts exactly; camelCase JSON, ISO UTC timestamps) ----
export const AttributeClassSchema = z.enum(['reading', 'condition', 'document', 'identity']);
export const SourceKindSchema = z.enum(['scan', 'camera', 'sensor', 'patrol', 'human', 'agent', 'owner']);
export const FactStatusSchema = z.enum(['known', 'stale', 'unknown', 'conflict']);
export const VerdictSchema = z.enum(['accepted', 'rejected', 'needs_clarification']);
export const WorkStateSchema = z.enum(['open', 'dispatched', 'waiting', 'needs_clarification', 'escalated', 'resolved', 'rejected', 'expired']);
export const ChannelSchema = z.enum(['local', 'email', 'sms', 'imessage', 'call']);
export const CheckNameSchema = z.enum(['scope', 'identity', 'geometry', 'plausibility', 'time', 'integrity']);
export const FactValueSchema = z.union([z.string(), z.number(), z.boolean()]);

export const SourceSchema = z.object({ kind: SourceKindSchema, ref: z.string() });
export const CheckSchema = z.object({ name: CheckNameSchema, passed: z.boolean(), reason: z.string() });

export const FactSchema = z.object({
  id: z.string(), propertyId: z.string(), assetTag: z.string(), componentId: z.string(),
  attribute: z.string(), attributeClass: AttributeClassSchema, value: FactValueSchema, unit: z.string().nullable().optional(),
  observedAt: z.string(), ttlSeconds: z.number().nullable(), expiresAt: z.string().nullable(),
  source: SourceSchema, attestationId: z.string(), version: z.number(), createdAt: z.string(),
});

export const AttestationSchema = z.object({
  id: z.string(), propertyId: z.string(), assetTag: z.string(), componentId: z.string(), attribute: z.string(),
  value: FactValueSchema, unit: z.string().nullable().optional(), observedAt: z.string(),
  evidenceHashes: z.array(z.string()), checks: z.array(CheckSchema), verdict: VerdictSchema, source: SourceSchema,
  verifierVersion: z.string(), signedAt: z.string(), publicKey: z.string(), signature: z.string(),
});
/** GET /api/attestations/{id} returns the record plus `valid` after the backend re-verifies the Ed25519 signature. */
export const CheckedAttestationSchema = AttestationSchema.extend({ valid: z.boolean() });

export const DispatchSchema = z.object({
  id: z.string(), channel: ChannelSchema, to: z.string(), reference: z.string(), sentAt: z.string(),
  providerRef: z.string().nullable().optional(), body: z.string(),
});

export const ReceiptSchema = z.object({
  waitedSeconds: z.number(), tokensWhileWaiting: z.literal(0), estimatedPollingTokens: z.number(),
  dispatches: z.number(), cost: z.number(), currency: z.literal('USD'),
});

export const WorkItemSchema = z.object({
  id: z.string(), propertyId: z.string(), assetTag: z.string(), componentId: z.string(), attribute: z.string(), attributeClass: AttributeClassSchema,
  reference: z.string(), state: WorkStateSchema, requester: z.string(), budget: z.number(), deadlineAt: z.string().nullable(),
  dispatches: z.array(DispatchSchema),
  verdicts: z.array(z.object({ attestationId: z.string(), verdict: VerdictSchema, reasons: z.array(z.string()), at: z.string() })),
  factId: z.string().nullable().optional(), attestationId: z.string().nullable().optional(), receipt: ReceiptSchema.nullable().optional(),
  createdAt: z.string(), updatedAt: z.string(),
});

/** Change types: the contract's six plus addendum 2's `a2a` (every agent message) and mission/eval lifecycle events; kept open so a new backend type never breaks get_changes. */
export const ChangeTypeSchema = z.string().min(1);
export const ChangeSchema = z.object({
  version: z.number(), type: ChangeTypeSchema,
  propertyId: z.string(), assetTag: z.string().optional(), refId: z.string(), summary: z.string(), at: z.string(),
});

export const ResolveResultSchema = z.object({
  status: FactStatusSchema, propertyId: z.string(), assetTag: z.string(), attribute: z.string(),
  value: FactValueSchema.optional(), unit: z.string().nullable().optional(), observedAt: z.string().optional(), ageSeconds: z.number().optional(), attestationId: z.string().optional(),
  conflicts: z.array(z.object({ attestationId: z.string(), value: FactValueSchema, observedAt: z.string() })).optional(),
  workItemId: z.string().optional(), workState: WorkStateSchema.optional(), reference: z.string().optional(), dispatchedVia: ChannelSchema.optional(), expiresAt: z.string().optional(),
  cost: z.number().optional(), nextStep: z.string(),
});

export const AttestResultSchema = z.object({
  verdict: VerdictSchema, reasons: z.array(z.string()), checks: z.array(CheckSchema),
  attestationId: z.string().optional(), factId: z.string().optional(), workItemId: z.string().optional(), nextStep: z.string(),
});

export const SubscriptionSchema = z.object({ id: z.string(), propertyId: z.string(), callbackUrl: z.string(), requester: z.string(), createdAt: z.string() });

const Vec2Schema = z.tuple([z.number(), z.number()]);
export const ClearanceResultSchema = z.object({
  clear: z.boolean(), widthM: z.number(), blockingAssetTag: z.string().nullable().optional(), blockingComponentId: z.string().nullable().optional(), path: z.array(Vec2Schema),
});

export const ContextMinSchema = z.object({
  propertyId: z.string(), name: z.string(), version: z.number(), assets: z.number(),
  facts: z.object({ known: z.number(), stale: z.number(), unknown: z.number() }),
  blockers: z.array(z.object({ assetTag: z.string(), attribute: z.string(), state: WorkStateSchema, reference: z.string() })),
  sensors: z.array(z.object({ assetTag: z.string(), attribute: z.string(), value: FactValueSchema, ageSeconds: z.number() })),
});

export const ChangesSchema = z.object({ version: z.number(), changes: z.array(ChangeSchema), waiting: z.array(WorkItemSchema) });

// ---- Addendum 2 (REALITY-CONTRACT-2.md): issues, agents, missions, transcripts, evals ----
/** Addendum 2 issue; kept open (kind is a string, pin may be 2-D or 3-D) so addendum-3 issue kinds pass through get_issues. */
export const IssueSchema = z.looseObject({
  id: z.string(), assetTag: z.string().nullable().optional(), componentId: z.string().nullable().optional(), kind: z.string(),
  severity: z.enum(['low', 'medium', 'high']), summary: z.string(), refId: z.string().nullable().optional(), pin: z.record(z.string(), z.number()).nullable().optional(), at: z.string().optional(), simulated: z.boolean().optional(),
});
/** Contract 4 levels run 1 (the owner's agent) to 5 (field technicians); extra fields (siteId, role details) pass through. */
export const AgentInfoSchema = z.looseObject({
  id: z.string(), level: z.number().int().min(1).max(5), name: z.string(), role: z.string(), handle: z.string().nullable().optional(),
  status: z.string(), currentTask: z.string().nullable().optional(), lastActivityAt: z.string().nullable(), authority: z.array(z.string()),
});
export const MissionStepSchema = z.object({
  id: z.string(), at: z.string(), agentId: z.string(), summary: z.string(), taskId: z.string().nullable().optional(), workItemId: z.string().nullable().optional(), attestationId: z.string().nullable().optional(),
});
export const MissionStateSchema = z.enum(['running', 'input_required', 'completed', 'failed']);
export const ChecklistItemSchema = z.object({ assetTag: z.string(), attribute: z.string(), value: FactValueSchema, attestationId: z.string(), valid: z.boolean() });
export const MissionSchema = z.object({
  id: z.string(), siteId: z.string(), goal: z.literal('clear_for_restart'), budget: z.number(), requester: z.string(), state: MissionStateSchema,
  steps: z.array(MissionStepSchema), contextId: z.string(), checklist: z.array(ChecklistItemSchema).optional(), createdAt: z.string(), updatedAt: z.string(),
});
export const TranscriptEntrySchema = z.object({
  id: z.string(), agentId: z.string(), at: z.string(), kind: z.enum(['a2a', 'sms', 'email', 'imessage', 'call', 'mcp', 'decision', 'system']), direction: z.enum(['in', 'out']),
  counterpart: z.string(), text: z.string(), parts: z.array(z.unknown()).optional(), audioUrl: z.string().nullable().optional(),
  refs: z.object({ missionId: z.string().optional(), taskId: z.string().optional(), workItemId: z.string().optional(), attestationId: z.string().optional() }), simulated: z.boolean().optional(),
});
export const EvalStepSchema = z.object({ name: z.string(), target: z.string(), result: z.enum(['PASS', 'FAIL']), ms: z.number(), detail: z.string() });
/** Extra fields the backend records on a run (before, after, budget for the efficiency eval) pass through. */
export const EvalRunSchema = z.looseObject({ id: z.string(), suite: z.string(), startedAt: z.string(), finishedAt: z.string().nullable(), passed: z.number(), failed: z.number(), steps: z.array(EvalStepSchema) });
export const PublicKeySchema = z.object({ algorithm: z.literal('ed25519'), publicKey: z.string(), verifierVersion: z.string() });
/** Spec table: keyed by component kind, then attribute. Shape is the backend's; it is proxied verbatim as a resource. */
export const SpecsSchema = z.record(z.string(), z.unknown());

/** Canonical TS types for the reality layer, served as the steward://schema resource. Copied from shared/types.ts. */
export const REALITY_TYPES_TS = `export type AttributeClass = 'reading' | 'condition' | 'document' | 'identity';
export type SourceKind = 'scan' | 'camera' | 'sensor' | 'patrol' | 'human' | 'agent' | 'owner';
export type FactStatus = 'known' | 'stale' | 'unknown' | 'conflict';
export type Verdict = 'accepted' | 'rejected' | 'needs_clarification';
export type WorkState = 'open' | 'dispatched' | 'waiting' | 'needs_clarification' | 'escalated' | 'resolved' | 'rejected' | 'expired';
export type Channel = 'local' | 'email' | 'sms' | 'imessage' | 'call';
export interface Source { kind: SourceKind; ref: string; }
export interface Check { name: 'scope'|'identity'|'geometry'|'plausibility'|'time'|'integrity'; passed: boolean; reason: string; }
export interface Fact { id: string; propertyId: string; assetTag: string; componentId: string; attribute: string; attributeClass: AttributeClass; value: string | number | boolean; unit?: string | null; observedAt: string; ttlSeconds: number | null; expiresAt: string | null; source: Source; attestationId: string; version: number; createdAt: string; }
export interface Attestation { id: string; propertyId: string; assetTag: string; componentId: string; attribute: string; value: string | number | boolean; unit?: string | null; observedAt: string; evidenceHashes: string[]; checks: Check[]; verdict: Verdict; source: Source; verifierVersion: string; signedAt: string; publicKey: string; signature: string; }
export interface Dispatch { id: string; channel: Channel; to: string; reference: string; sentAt: string; providerRef?: string | null; body: string; }
export interface Receipt { waitedSeconds: number; tokensWhileWaiting: 0; estimatedPollingTokens: number; dispatches: number; cost: number; currency: 'USD'; }
export interface WorkItem { id: string; propertyId: string; assetTag: string; componentId: string; attribute: string; attributeClass: AttributeClass; reference: string; state: WorkState; requester: string; budget: number; deadlineAt: string | null; dispatches: Dispatch[]; verdicts: { attestationId: string; verdict: Verdict; reasons: string[]; at: string }[]; factId?: string | null; attestationId?: string | null; receipt?: Receipt | null; createdAt: string; updatedAt: string; }
export interface Change { version: number; type: 'fact'|'work_item'|'attestation'|'dispatch'|'escalation'|'owner_decision'|'a2a'|'eval'; propertyId: string; assetTag?: string; refId: string; summary: string; at: string; }
export interface ResolveResult { status: FactStatus; propertyId: string; assetTag: string; attribute: string; value?: string | number | boolean; unit?: string | null; observedAt?: string; ageSeconds?: number; attestationId?: string; conflicts?: { attestationId: string; value: string | number | boolean; observedAt: string }[]; workItemId?: string; workState?: WorkState; reference?: string; dispatchedVia?: Channel; expiresAt?: string; cost?: number; nextStep: string; }
export interface AttestResult { verdict: Verdict; reasons: string[]; checks: Check[]; attestationId?: string; factId?: string; workItemId?: string; nextStep: string; }
export interface Subscription { id: string; propertyId: string; callbackUrl: string; requester: string; createdAt: string; }
export interface ClearanceResult { clear: boolean; widthM: number; blockingAssetTag?: string | null; blockingComponentId?: string | null; path: [number, number][]; }
export interface ContextMin { propertyId: string; name: string; version: number; assets: number; facts: { known: number; stale: number; unknown: number }; blockers: { assetTag: string; attribute: string; state: WorkState; reference: string }[]; sensors: { assetTag: string; attribute: string; value: string|number|boolean; ageSeconds: number }[]; }
export type SiteId = 'myer-plant' | 'bristol-pumps' | 'tomioka-mill';
export interface Environment { kind: 'fixture' | 'splat'; splatId?: string; embedUrl?: string; thumbnailUrl?: string; credit: string; captureNote: string; }
export interface Issue { id: string; assetTag: string; componentId: string; kind: 'out_of_range'|'rejected_evidence'|'overdue'|'unknown_identity'|'escalated'; severity: 'low'|'medium'|'high'; summary: string; refId: string; pin?: { x: number; y: number } | null; at: string; simulated?: boolean; }
export type AgentId = 'operator' | 'director' | 'myer-manager' | 'myer-engineer' | 'myer-compliance' | 'myer-technician' | 'bristol-manager' | 'bristol-engineer' | 'bristol-compliance' | 'bristol-technician' | 'tomioka-manager' | 'tomioka-engineer' | 'tomioka-compliance' | 'tomioka-technician';
export interface AgentInfo { id: string; level: 1|2|3|4; name: string; role: string; handle?: string | null; status: 'idle'|'working'|'waiting'; currentTask?: string | null; lastActivityAt: string | null; authority: string[]; }
export interface A2AMessage { role: 'caller'|'agent'; parts: { text?: string; data?: Record<string, unknown> }[]; at: string; }
export interface A2ATask { id: string; contextId: string; caller: string; target: string; state: 'submitted'|'working'|'input_required'|'completed'|'failed'|'canceled'; messages: A2AMessage[]; transport: 'local'|'inkbox'; providerTaskId?: string | null; simulated?: boolean; createdAt: string; updatedAt: string; }
export interface MissionStep { id: string; at: string; agentId: string; summary: string; taskId?: string | null; workItemId?: string | null; attestationId?: string | null; }
export interface Mission { id: string; siteId: string; goal: 'clear_for_restart'; budget: number; requester: string; state: 'running'|'input_required'|'completed'|'failed'; steps: MissionStep[]; contextId: string; checklist?: { assetTag: string; attribute: string; value: string|number|boolean; attestationId: string; valid: boolean }[]; createdAt: string; updatedAt: string; }
export interface TranscriptEntry { id: string; agentId: string; at: string; kind: 'a2a'|'sms'|'email'|'imessage'|'call'|'mcp'|'decision'|'system'; direction: 'in'|'out'; counterpart: string; text: string; parts?: unknown[]; audioUrl?: string | null; refs: { missionId?: string; taskId?: string; workItemId?: string; attestationId?: string }; simulated?: boolean; }
export interface EvalStep { name: string; target: string; result: 'PASS'|'FAIL'; ms: number; detail: string; }
export interface EvalRun { id: string; suite: string; startedAt: string; finishedAt: string | null; passed: number; failed: number; steps: EvalStep[]; }
export interface SimulationStatus { enabled: boolean; counts: Record<string, number>; }
`;
