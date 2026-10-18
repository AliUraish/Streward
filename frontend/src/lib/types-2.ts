/* Addendum 2 types (REALITY-CONTRACT-2.md), mirrored here because shared/types.ts belongs to the orchestrator.
   camelCase JSON, ISO UTC timestamps. Keep in step with shared/types.ts. */
import type { Change as Change1, Property } from "../../../shared/types";

export type SiteId = "harbor-works" | "myer-plant" | "bristol-pumps";

export interface Environment { kind: "fixture" | "splat"; splatId?: string; embedUrl?: string; thumbnailUrl?: string; credit: string; captureNote: string; }

/* The property record after the addendum: industrial fields plus the environment. Old fields stay optional so an old backend still renders. */
export interface SiteProperty extends Property { site?: string; operator?: string; status?: string; environment?: Environment | null; }

export type IssueKind = "out_of_range" | "rejected_evidence" | "overdue" | "unknown_identity" | "escalated";
export type Severity = "low" | "medium" | "high";
export interface Pin { x: number; y: number }
export interface Issue { id: string; assetTag: string; componentId: string; kind: IssueKind; severity: Severity; summary: string; refId: string; pin?: Pin | null; at: string; simulated?: boolean; }

export type AgentId = "operator" | "atlas" | `warden:${string}` | "runner";
export type AgentStatus = "idle" | "working" | "waiting";
export interface AgentInfo { id: string; level: 1 | 2 | 3 | 4; name: string; role: string; handle?: string | null; status: AgentStatus; currentTask?: string | null; why?: string | null; waitingOn?: string | null; lastActivityAt: string | null; authority: string[]; }

export interface A2AMessage { role: "caller" | "agent"; parts: { text?: string; data?: Record<string, unknown> }[]; at: string; }
export type A2AState = "submitted" | "working" | "input_required" | "completed" | "failed" | "canceled";
export interface A2ATask { id: string; contextId: string; caller: string; target: string; state: A2AState; messages: A2AMessage[]; transport: "local" | "inkbox"; providerTaskId?: string | null; simulated?: boolean; createdAt: string; updatedAt: string; }

export interface MissionStep { id: string; at: string; agentId: string; summary: string; taskId?: string | null; workItemId?: string | null; attestationId?: string | null; state?: A2AState | null; }
export type MissionState = "running" | "input_required" | "completed" | "failed";
export interface ChecklistRow { assetTag: string; attribute: string; value: string | number | boolean; attestationId: string; valid: boolean }
export interface Mission { id: string; siteId: string; goal: "clear_for_restart"; budget: number; requester: string; state: MissionState; steps: MissionStep[]; contextId: string; checklist?: ChecklistRow[]; missing?: string[]; createdAt: string; updatedAt: string; }
export interface MissionInput { siteId: string; goal: "clear_for_restart"; budget: number; requester: string }

export type TranscriptKind = "a2a" | "sms" | "email" | "imessage" | "call" | "mcp" | "decision" | "system";
export interface TranscriptRefs { missionId?: string; taskId?: string; workItemId?: string; attestationId?: string }
export interface TranscriptEntry { id: string; agentId: string; at: string; kind: TranscriptKind; direction: "in" | "out"; counterpart: string; text: string; parts?: unknown[]; audioUrl?: string | null; refs: TranscriptRefs; simulated?: boolean; }

export interface EvalStep { name: string; target: string; result: "PASS" | "FAIL"; ms: number; detail: string; }
export interface EvalRun { id: string; suite: string; startedAt: string; finishedAt: string | null; passed: number; failed: number; steps: EvalStep[]; }
export type EvalSuite = "demo-workflow" | "mission-workflow";

export interface SimulationStatus { enabled: boolean; counts: Record<string, number>; }

/* Change feed gains type 'a2a' (one per A2A message) and the simulated flag. */
export type ChangeType = Change1["type"] | "a2a";
export interface Change extends Omit<Change1, "type"> { type: ChangeType; simulated?: boolean; }
