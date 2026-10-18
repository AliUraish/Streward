/**
 * Addendum 3 (REALITY-CONTRACT-3.md) shapes as this MCP returns them. The backend stream is building the routes
 * concurrently, so every upstream read is parsed leniently (unknown fields kept, most fields optional) and then
 * normalised by src/factory.ts into the stricter output schemas below. Field names follow the contract and the
 * dashboard's mirror (frontend/src/lib/types-3.ts): camelCase JSON, ISO UTC timestamps.
 */
import { z } from 'zod';

export const SEVERITIES = ['none', 'low', 'medium', 'high'] as const;
export const SeveritySchema = z.enum(SEVERITIES);
export const Vec3TupleSchema = z.tuple([z.number(), z.number(), z.number()]);
export const Pin3Schema = z.object({ x: z.number(), y: z.number(), z: z.number() });
const OptStr = z.string().nullable().optional();
const Rec = z.record(z.string(), z.unknown());

// ---- upstream (lenient) ----
export const UpAssetSchema = z.looseObject({
  tag: z.string().optional(), assetTag: z.string().optional(), name: z.string().optional(), kind: z.string().optional(),
  pin: z.union([Pin3Schema, Vec3TupleSchema, z.looseObject({})]).nullable().optional(), pinSource: z.string().nullable().optional(),
  position: Vec3TupleSchema.optional(), openIssues: z.number().optional(), issueIds: z.array(z.string()).optional(), severity: z.string().optional(),
});
export const UpIssueSchema = z.looseObject({
  id: z.string(), siteId: OptStr, propertyId: OptStr, assetTag: z.string().nullable().optional(), kind: z.string().optional(), severity: z.string().optional(),
  summary: z.string().optional(), status: z.string().optional(), at: z.string().optional(), assignedTo: z.unknown().optional(), scenarioId: OptStr, refId: OptStr,
  synthetic: z.boolean().optional(), simulated: z.boolean().optional(),
});
export const UpWaitCreatedSchema = z.looseObject({ waitId: z.string().min(1).optional(), id: z.string().min(1).optional() });
export const UpWaitResultSchema = z.looseObject({ waitId: z.string().optional(), status: z.string(), event: z.unknown().optional(), firedAt: z.string().optional() });

// ---- outputs (normalised) ----
export const CreditSchema = z.object({ scene: z.string(), author: z.string(), url: z.string(), text: z.string() });
export const CameraPresetSchema = z.looseObject({ name: z.string(), position: Vec3TupleSchema, target: Vec3TupleSchema, fov: z.number().optional() });
export const SceneIssueSchema = z.object({ id: z.string(), severity: SeveritySchema, kind: z.string(), summary: z.string(), status: z.string() });
export const SceneAssetSchema = z.object({
  assetTag: z.string(), name: z.string(), kind: z.string(), pin: Pin3Schema.nullable(), pinSource: z.string().nullable(),
  severity: SeveritySchema, issues: z.array(SceneIssueSchema),
});
export const SceneSchema = z.object({
  siteId: z.string(), name: z.string(), splatId: z.string(), gaussians: z.string(), sogUrl: z.string(), credit: CreditSchema,
  environment: Rec.nullable(), cameraPresets: z.array(CameraPresetSchema), assets: z.array(SceneAssetSchema),
  counts: z.object({ assets: z.number(), pinned: z.number(), estimated: z.number(), openIssues: z.number() }), nextStep: z.string(),
});
export const FactorySchema = SceneSchema.extend({ summary: z.string(), widget: z.object({ resourceUri: z.string(), engine: z.string(), rendered: z.string() }) });

export const ViewerCommandOutSchema = z.object({ commandId: z.string(), siteId: z.string(), action: z.string(), assetTag: z.string().nullable(), issueId: z.string().nullable(), at: z.string().nullable(), nextStep: z.string() });
export const CaptureSchema = z.object({
  siteId: z.string(), assetTag: z.string(), frames: z.array(z.string()), count: z.number(), capturedAt: z.string().nullable(),
  synthetic: z.boolean().nullable(), defect: z.string().nullable(), caption: z.string(), nextStep: z.string(),
});

export const OverviewSchema = z.object({
  sites: z.array(z.object({
    siteId: z.string(), name: z.string(), issues: z.object({ high: z.number(), medium: z.number(), low: z.number() }),
    compliance: z.object({ ok: z.number(), due_soon: z.number(), overdue: z.number(), blocked: z.number() }),
    crewOnShift: z.number(), activeScenario: z.string().nullable(),
  })),
  agents: z.array(z.object({ agentId: z.string(), status: z.string(), task: z.string().nullable(), waitingOn: z.string().nullable() })),
  activeScenario: z.object({ scenarioId: z.string(), state: z.string(), step: z.number().nullable() }).nullable(),
  changes: z.array(z.object({ at: z.string().nullable(), siteId: z.string().nullable(), type: z.string().nullable(), summary: z.string() })),
  tokensEstimate: z.number(), nextStep: z.string(),
});

export const ToolCallOutSchema = z.looseObject({ at: z.string().nullable(), tool: z.string(), tokens: z.number().nullable(), ok: z.boolean().nullable() });
export const ActivitySchema = z.object({
  agentId: z.string(), currentTask: z.string().nullable(), why: z.string().nullable(), waitingOn: z.string().nullable(),
  lastActions: z.array(ToolCallOutSchema), tokensThisHour: z.number().nullable(), memoryHighlights: z.array(z.string()), config: Rec.nullable(), nextStep: z.string(),
});

export const BoardTurnSchema = z.looseObject({ agentId: z.string(), text: z.string(), at: z.string().nullable().optional(), kind: z.string().nullable().optional() });
export const BoardMeetingSchema = z.object({
  id: z.string(), siteId: z.string().nullable(), issueId: z.string().nullable(), scenarioId: z.string().nullable(), title: z.string().nullable(),
  convenedBy: z.string().nullable(), participants: z.array(z.string()), transcript: z.array(BoardTurnSchema), resolution: z.string().nullable(),
  contact: Rec.nullable(), state: z.string().nullable(), at: z.string().nullable(), synthetic: z.boolean().nullable(), notice: z.string(), nextStep: z.string(),
});

export const MemoryOutSchema = z.object({
  agentId: z.string(), source: z.string(), container: z.string().nullable(), items: z.array(z.looseObject({ id: z.string(), text: z.string(), at: z.string().nullable().optional() })),
  notice: z.string(),
});

export const IssueOutSchema = z.object({
  id: z.string(), siteId: z.string().nullable(), assetTag: z.string().nullable(), kind: z.string(), severity: SeveritySchema, summary: z.string(),
  status: z.string(), at: z.string().nullable(), assignedTo: z.string().nullable(), scenarioId: z.string().nullable(), refId: z.string().nullable(), synthetic: z.boolean().nullable(),
  obligationId: z.string().nullable(), documentId: z.string().nullable(),
});
export const IssueDetailSchema = IssueOutSchema.extend({ detail: Rec, nextStep: z.string() });

export const InspectionStartSchema = z.object({ siteId: z.string(), status: z.string(), jobId: z.string().nullable(), dryRun: z.boolean(), message: z.string(), nextStep: z.string() });
export const ValveResultOutSchema = z.object({
  assetTag: z.string(), status: z.string(), score: z.number().nullable(), threshold: z.number().nullable(), model: z.string().nullable(),
  frames: z.number(), synthetic: z.boolean().nullable(), defect: z.string().nullable(), explanation: Rec.nullable(),
});
export const InspectionSchema = z.object({
  siteId: z.string(), ranAt: z.string().nullable(), model: z.string().nullable(), results: z.array(ValveResultOutSchema),
  counts: z.object({ fixed: z.number(), not_fixed: z.number(), uncertain: z.number() }), disclaimer: z.string(), nextStep: z.string(),
});

export const CrewOutSchema = z.object({
  id: z.string(), siteId: z.string(), name: z.string(), role: z.string(), shift: z.string(), onShift: z.boolean().nullable(),
  hasPhone: z.boolean(), hasEmail: z.boolean(), certifications: z.array(z.looseObject({ name: z.string(), expiresAt: z.string().nullable().optional() })),
  owns: z.array(z.string()), synthetic: z.boolean().nullable(),
});
export const ResponsibleSchema = z.object({ siteId: z.string(), issueKind: z.string(), crewMember: CrewOutSchema.nullable(), via: z.string().nullable(), reason: z.string().nullable(), nextStep: z.string() });
export const ObligationOutSchema = z.object({
  id: z.string(), siteId: z.string(), assetTag: z.string().nullable(), title: z.string(), ruleRef: z.string(), frequency: z.string().nullable(),
  lastDoneAt: z.string().nullable(), dueAt: z.string().nullable(), status: z.string(), documentId: z.string().nullable(), ownerId: z.string().nullable(), synthetic: z.boolean().nullable(),
});
export const DocumentOutSchema = z.object({
  id: z.string(), siteId: z.string().nullable(), title: z.string(), kind: z.string().nullable(), obligationId: z.string().nullable(), assetTag: z.string().nullable(),
  issuedAt: z.string().nullable(), expiresAt: z.string().nullable(), fileUrl: z.string().nullable(), flagged: z.boolean(), flagReason: z.string().nullable(),
  suspectedInjection: z.boolean(), textIsData: z.literal(true), text: z.string().nullable(), notice: z.string(), synthetic: z.boolean().nullable(),
});
export const NoticeOutSchema = z.looseObject({ id: z.string(), to: z.string().nullable().optional(), channel: z.string().nullable().optional(), sentAt: z.string().nullable().optional(), dryRun: z.boolean().nullable().optional() });

/** Contract 3 §5 plus contract 4 §7 (x-maintenance: the two factories share an examiner visit). */
export const SCENARIO_IDS = ['my-overpressure', 'my-extinguisher', 'br-sump', 'br-vessel-cert', 'ops-counsel-tokens', 'ops-injection', 'x-maintenance'] as const;
export const ScenarioOutSchema = z.looseObject({ id: z.string(), siteId: z.string().nullable(), title: z.string(), summary: z.string(), owners: z.array(z.string()), synthetic: z.boolean().nullable() });
export const ScenarioRunOutSchema = z.looseObject({ id: z.string(), scenarioId: z.string(), siteId: z.string().nullable(), state: z.string(), step: z.number().nullable(), steps: z.number().nullable(), startedAt: z.string().nullable() });

export const WaitOutSchema = z.object({
  status: z.string(), waitId: z.string(), event: Rec.nullable(), waitedSeconds: z.number(), windowSeconds: z.number(),
  progressNotifications: z.number(), tokensWhileWaiting: z.literal(0), nextStep: z.string(),
});
export const DecisionSchema = z.object({
  status: z.enum(['decided', 'declined', 'routed']), issueId: z.string(), question: z.string(), options: z.array(z.string()), answer: z.string().nullable(),
  via: z.string(), routedTo: z.string().nullable(), dryRun: z.boolean().nullable(), waitId: z.string().nullable(), record: Rec.nullable(), nextStep: z.string(),
});

export const FindingsSchema = z.object({
  agents: z.array(z.looseObject({ agentId: z.string(), tokensPerMission: z.number().nullable(), polls: z.number().nullable().optional(), failures: z.number().nullable().optional() })),
  flags: z.array(Rec), loop: Rec.nullable(), metrics: Rec.nullable(), source: z.string(), armature: Rec.nullable(), at: z.string().nullable(), nextStep: z.string(),
});
export const ReconfigureSchema = z.object({ agentId: z.string(), config: Rec, change: Rec, why: z.string(), at: z.string().nullable(), nextStep: z.string() });
