import type { AgentInfo, EvalRun, EvalSuite, Issue, Mission, MissionInput, SimulationStatus, SiteProperty, TranscriptEntry } from './types-2';
import type { Property, Workspace, ComponentDetail, Requirement, Document, Job, ActivityEvent, Agent, ChatMessage, Memory, Integration, Purchase, ResolveResult, AttestResult, Attestation, Fact, FactStatus, Change, WorkItem, Subscription, ClearanceResult, ContextMin, Verdict, Check } from '../../../shared/types';

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public recovery?: string) { super(message); }
  get notReady() { return this.status === 404 || this.status === 405 || this.status === 501; }
}
export async function request<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(path, { ...init, cache:'no-store', headers: { ...(init?.body && !(init.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...init?.headers } });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`; let code: string | undefined; let recovery: string | undefined;
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body); code = body.code; recovery = body.recovery; } catch {}
    throw new ApiError(detail, response.status, code, recovery);
  }
  return response.json() as Promise<T>;
}
const propertyPath = (id:string) => `/api/properties/${encodeURIComponent(id)}`;
const query = (values:Record<string,string|undefined>={}) => {const q=new URLSearchParams();Object.entries(values).forEach(([k,v])=>{if(v)q.set(k,v)});return q.size?`?${q}`:'';};
const post = <T>(path:string,body:unknown,headers?:Record<string,string>) => request<T>(path,{method:'POST',body:JSON.stringify(body),headers});

/* Every mutating endpoint takes the acting agent in X-Steward-Actor (REALITY-CONTRACT-2.md, authority table).
   The dashboard acts as the operator: it may start missions, set budgets and toggle the simulation, nothing more. */
export type Actor = 'operator' | 'atlas' | `warden:${string}` | 'counsel' | 'runner';
export const actorHeaders = (actor: Actor = 'operator'): Record<string,string> => ({ 'X-Steward-Actor': actor });
export const asOperator = actorHeaders('operator');

/* Reality layer response shapes (REALITY-CONTRACT.md, HTTP API table). */
export type FactRow = Fact & { status: FactStatus };
export interface ChangesResult { version: number; changes: Change[]; waiting: WorkItem[] }
export interface SignedAttestation extends Attestation { valid: boolean }
export interface PublicKey { algorithm: 'ed25519'; publicKey: string; verifierVersion: string }
export interface InboundResult { routed: boolean; workItemId?: string; verdict?: Verdict; reasons?: string[]; checks?: Check[]; attestationId?: string }
export interface ResolveInput { assetTag: string; attribute: string; maxAgeHours?: number; budget?: number; requester?: string; callbackUrl?: string }
export interface AttestInput { assetTag: string; attribute: string; value: string | number | boolean; unit?: string; observedAt?: string; source: { kind: string; ref: string }; statedTag?: string; workItemId?: string }
export interface InboundLocalInput { reference: string; body: string; statedTag?: string; value?: string; observedAt?: string; file?: File | null }
export interface OwnerDecisionInput { workItemId: string; decision: string; note?: string }
export type SpecTable = Record<string, Record<string, { class: string; unit?: string | null; min?: number; max?: number; enum?: string[] }>>;

export const api = {
  properties: () => request<Property[]>('/api/properties'),
  workspace: (id:string) => request<Workspace>(`${propertyPath(id)}/workspace`),
  component: (id:string,componentId:string) => request<ComponentDetail>(`${propertyPath(id)}/components/${encodeURIComponent(componentId)}`),
  documents: (id:string, filters:Record<string,string|undefined>={}) => request<Document[]>(`${propertyPath(id)}/documents${query(filters)}`),
  requirements: (id:string,filters:Record<string,string|undefined>={}) => request<Requirement[]>(`${propertyPath(id)}/requirements${query(filters)}`),
  inspect: (id:string,scope='all') => post<Job>(`${propertyPath(id)}/inspections`,{scope}),
  job: (id:string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  events: (id:string,after=0) => request<ActivityEvent[]>(`${propertyPath(id)}/events?after=${after}`),
  agents: (id:string) => request<Agent[]>(`${propertyPath(id)}/agents`),
  runAgent: (id:string,goal:string) => post<Job>(`${propertyPath(id)}/agents/run`,{goal}),
  chat: (id:string) => request<ChatMessage[]>(`${propertyPath(id)}/chat`),
  sendMessage: (id:string,message:string) => post<{message:ChatMessage;job?:Job}>(`${propertyPath(id)}/chat`,{message}),
  memory: (id:string) => request<Memory[]>(`${propertyPath(id)}/memory`),
  integrations: () => request<Integration[]>('/api/integrations'),
  uploadDocument: (id:string,file:File,category='Project documents') => {const data=new FormData();data.append('file',file);data.append('category',category);return request<Document>(`${propertyPath(id)}/documents`,{method:'POST',body:data});},
  uploadEvidence: (id:string,file:File,componentId:string,requirementId:string,note='') => {const data=new FormData();data.append('file',file);data.append('componentId',componentId);data.append('requirementId',requirementId);data.append('note',note);return request<unknown>(`${propertyPath(id)}/evidence`,{method:'POST',body:data});},
  purchases: (id:string) => request<Purchase[]>(`${propertyPath(id)}/purchases`),
  createPurchase: (id:string,body:{componentId:string;description:string;amount:number;currency?:string}) => post<Purchase>(`${propertyPath(id)}/purchases`,body),
  reportUrl: (id:string) => `${propertyPath(id)}/report`,

  /* Reality layer */
  resolve: (id:string, body:ResolveInput) => post<ResolveResult>(`${propertyPath(id)}/resolve`, body),
  attest: (id:string, body:AttestInput, file?:File|null) => {
    if (!file) return post<AttestResult>(`${propertyPath(id)}/attest`, body);
    const data = new FormData();
    Object.entries(body).forEach(([k,v]) => { if (v !== undefined && v !== null) data.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v)); });
    data.append('file', file);
    return request<AttestResult>(`${propertyPath(id)}/attest`, { method:'POST', body:data });
  },
  attestation: (attestationId:string) => request<SignedAttestation>(`/api/attestations/${encodeURIComponent(attestationId)}`),
  publicKey: () => request<PublicKey>('/api/attestations/public-key'),
  facts: (id:string, filters:{assetTag?:string;attribute?:string}={}) => request<FactRow[]>(`${propertyPath(id)}/facts${query(filters)}`),
  changes: (id:string, since=0, limit=100) => request<ChangesResult>(`${propertyPath(id)}/changes?since=${since}&limit=${limit}`),
  subscribe: (id:string, body:{callbackUrl:string;requester:string}) => post<Subscription>(`${propertyPath(id)}/subscriptions`, body),
  workItem: (workItemId:string) => request<WorkItem>(`/api/work-items/${encodeURIComponent(workItemId)}`),
  escalate: (workItemId:string, level:1|2|3|4, note?:string) => post<WorkItem>(`/api/work-items/${encodeURIComponent(workItemId)}/escalate`, { level, note }),
  clearance: (id:string, body:{from:[number,number];to:[number,number];widthM:number}) => post<ClearanceResult>(`${propertyPath(id)}/clearance`, body),
  contextMin: (id:string) => request<ContextMin>(`${propertyPath(id)}/context.min`),
  specs: (id:string) => request<SpecTable>(`${propertyPath(id)}/specs`),
  patrol: (id:string, scope?:string) => post<Job>(`${propertyPath(id)}/patrol`, { scope }),
  inboundLocal: (input:InboundLocalInput) => {
    const data = new FormData();
    data.append('reference', input.reference); data.append('body', input.body);
    if (input.statedTag) data.append('statedTag', input.statedTag);
    if (input.value) data.append('value', input.value);
    if (input.observedAt) data.append('observedAt', input.observedAt);
    if (input.file) data.append('file', input.file);
    return request<InboundResult>('/api/inbound/local', { method:'POST', body:data });
  },
  ownerDecision: (id:string, body:OwnerDecisionInput) => post<WorkItem>(`${propertyPath(id)}/owner-decision`, body, asOperator),

  /* Addendum 2: environments, agents, missions, transcripts, evals, simulation */
  sites: () => request<SiteProperty[]>('/api/properties'),
  issues: (id:string) => request<Issue[]>(`${propertyPath(id)}/issues`),
  simulation: () => request<SimulationStatus>('/api/simulation'),
  setSimulation: (enabled:boolean) => post<SimulationStatus>('/api/simulation', { enabled }, asOperator),
  agentList: () => request<AgentInfo[]>('/api/agents'),
  transcript: (agentId:string, since=0, limit=200) => request<TranscriptEntry[]>(`/api/agents/${encodeURIComponent(agentId)}/transcript?since=${since}&limit=${limit}`),
  startMission: (body:MissionInput) => post<Mission>('/api/missions', body, asOperator),
  mission: (id:string) => request<Mission>(`/api/missions/${encodeURIComponent(id)}`),
  missions: (siteId?:string) => request<Mission[]>(`/api/missions${query({ siteId })}`),
  evals: () => request<EvalRun[]>('/api/evals'),
  evalRun: (id:string) => request<EvalRun>(`/api/evals/${encodeURIComponent(id)}`),
  runEval: (suite:EvalSuite) => post<EvalRun>('/api/evals/run', { suite }, asOperator),
};
