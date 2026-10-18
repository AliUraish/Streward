export type Status = 'verified' | 'pending' | 'issue' | 'unknown';
export type Vec3 = [number, number, number];
export interface Property { id:string; name:string; address:string; jurisdiction:string; phase:string; readiness:number; componentCount:number; openIssues:number; updatedAt:string; }
export interface Component { id:string; tag:string; name:string; kind:string; system:string; subsystem:string; status:Status; position:Vec3; rotation?:Vec3; description:string; confidence:number; requirementCount:number; verifiedCount:number; }
export interface Requirement { id:string; code:string; title:string; description:string; system:string; componentId:string; status:Status; sourceId:string; sourceTitle:string; sourcePage:number; evidence:string; }
export interface Document { id:string; title:string; filename:string; category:string; jurisdiction:string; pages:number; size:number; uploadedAt:string; url:string; extractedText?:string; }
export interface ComponentDetail extends Component { requirements:Requirement[]; evidence:Evidence[]; }
export interface Evidence { id:string; componentId:string; requirementId:string; filename:string; note:string; status:Status; createdAt:string; url:string; }
export interface ActivityEvent { id:number; propertyId:string; agentId:string; type:string; title:string; detail:string; componentId?:string|null; createdAt:string; }
export interface Agent { id:string; name:string; role:string; status:'idle'|'working'|'waiting'|'error'; identity:string; lastAction:string; tools:string[]; }
export interface Job { id:string; propertyId:string; kind:string; status:'queued'|'running'|'completed'|'failed'; progress:number; message:string; result?:Record<string,unknown>|null; createdAt:string; updatedAt:string; }
export interface ChatMessage { id:string; role:'user'|'assistant'; content:string; createdAt:string; sources?:{id:string;title:string;page?:number}[]; }
export interface Memory { id:string; propertyId:string; content:string; source:string; createdAt:string; }
export interface Integration { id:string; name:string; description:string; status:'connected'|'local'|'not_configured'|'error'; detail:string; capabilities?:Record<string,boolean>; }
export interface Purchase { id:string; componentId:string; description:string; amount:number; currency:string; status:string; createdAt:string; }
export interface Workspace { property:Property; components:Component[]; requirements:Requirement[]; agents:Agent[]; events:ActivityEvent[]; activeJob:Job|null; stats:{verified:number;pending:number;issue:number;unknown:number;total:number;}; }

// ---- Reality layer (see REALITY-CONTRACT.md) ----
export type AttributeClass = 'reading' | 'condition' | 'document' | 'identity';
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

// ---- Addendum 2: environments, agents, A2A, missions, transcripts, evals (see REALITY-CONTRACT-2.md) ----
export type SiteId = 'harbor-works' | 'myer-plant' | 'bristol-pumps';
export interface Environment { kind: 'fixture' | 'splat'; splatId?: string; embedUrl?: string; thumbnailUrl?: string; credit: string; captureNote: string; }
export interface Issue { id: string; assetTag: string; componentId: string; kind: 'out_of_range'|'rejected_evidence'|'overdue'|'unknown_identity'|'escalated'; severity: 'low'|'medium'|'high'; summary: string; refId: string; pin?: { x: number; y: number } | null; at: string; simulated?: boolean; }
export type AgentId = 'operator' | 'atlas' | `warden:${string}` | 'runner';
export interface AgentInfo { id: string; level: 1|2|3|4; name: string; role: string; handle?: string | null; status: 'idle'|'working'|'waiting'; currentTask?: string | null; lastActivityAt: string | null; authority: string[]; }
export interface A2AMessage { role: 'caller'|'agent'; parts: { text?: string; data?: Record<string, unknown> }[]; at: string; }
export interface A2ATask { id: string; contextId: string; caller: string; target: string; state: 'submitted'|'working'|'input_required'|'completed'|'failed'|'canceled'; messages: A2AMessage[]; transport: 'local'|'inkbox'; providerTaskId?: string | null; simulated?: boolean; createdAt: string; updatedAt: string; }
export interface MissionStep { id: string; at: string; agentId: string; summary: string; taskId?: string | null; workItemId?: string | null; attestationId?: string | null; }
export interface Mission { id: string; siteId: string; goal: 'clear_for_restart'; budget: number; requester: string; state: 'running'|'input_required'|'completed'|'failed'; steps: MissionStep[]; contextId: string; checklist?: { assetTag: string; attribute: string; value: string|number|boolean; attestationId: string; valid: boolean }[]; createdAt: string; updatedAt: string; }
export interface TranscriptEntry { id: string; agentId: string; at: string; kind: 'a2a'|'sms'|'email'|'imessage'|'call'|'mcp'|'decision'|'system'; direction: 'in'|'out'; counterpart: string; text: string; parts?: unknown[]; audioUrl?: string | null; refs: { missionId?: string; taskId?: string; workItemId?: string; attestationId?: string }; simulated?: boolean; }
export interface EvalStep { name: string; target: string; result: 'PASS'|'FAIL'; ms: number; detail: string; }
export interface EvalRun { id: string; suite: string; startedAt: string; finishedAt: string | null; passed: number; failed: number; steps: EvalStep[]; }
export interface SimulationStatus { enabled: boolean; counts: Record<string, number>; }
