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
