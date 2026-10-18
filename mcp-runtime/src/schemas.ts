import { z } from 'zod';
import { PROPERTY_IDS } from './config.js';

export const PropertyIdSchema = z.enum(PROPERTY_IDS);
export const StatusSchema = z.enum(['verified', 'pending', 'issue', 'unknown']);
export const PropertySchema = z.object({
  id: PropertyIdSchema, name: z.string(), address: z.string(), jurisdiction: z.string(), phase: z.string(),
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
