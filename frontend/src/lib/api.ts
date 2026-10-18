import type { Property, Workspace, ComponentDetail, Requirement, Document, Job, ActivityEvent, Agent, ChatMessage, Memory, Integration, Purchase } from '../../../shared/types';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export async function request<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(path, { ...init, cache:'no-store', headers: { ...(init?.body && !(init.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...init?.headers } });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body); } catch {}
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}
const propertyPath = (id:string) => `/api/properties/${encodeURIComponent(id)}`;
const query = (values:Record<string,string|undefined>={}) => {const q=new URLSearchParams();Object.entries(values).forEach(([k,v])=>{if(v)q.set(k,v)});return q.size?`?${q}`:'';};
const post = <T>(path:string,body:unknown) => request<T>(path,{method:'POST',body:JSON.stringify(body)});
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
};
