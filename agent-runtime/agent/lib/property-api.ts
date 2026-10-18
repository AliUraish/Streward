import { readFile } from 'node:fs/promises';
import path from 'node:path';
export type PropertyId = 'cedar'|'harbor'|'juniper';
const ids = new Set(['cedar','harbor','juniper']);
type SessionScope={id:string;parent?:{rootSessionId?:string}|null};
async function assertWriteScope(property:PropertyId,session?:SessionScope){
  const sessionId=session?.parent?.rootSessionId || session?.id;
  if(!sessionId || !/^[a-zA-Z0-9_-]{3,200}$/.test(sessionId))throw new Error('This session has no inspection-write mandate.');
  const directory=path.resolve(process.env.STEWARD_AGENT_RUNTIME_DIR || process.cwd(),'.eve','property-sessions','policies');
  let policy;
  try{policy=JSON.parse(await readFile(path.join(directory,`${sessionId}.json`),'utf8'));}
  catch{throw new Error('This session is read-only; no inspection-write mandate was issued.');}
  if(policy.propertyId!==property || policy.allowMutations!==true)throw new Error('This session is read-only or belongs to another property.');
}
export async function propertyApi(property:PropertyId, suffix='workspace', body?:Record<string,unknown>, session?:SessionScope) {
  if(!ids.has(property))throw new Error('Unknown property scope');
  if(body)await assertWriteScope(property,session);
  const base = (process.env.STEWARD_BACKEND_URL || 'http://127.0.0.1:8001').replace(/\/$/,'');
  const response=await fetch(`${base}/api/properties/${property}/${suffix}`,{
    method:body?'POST':'GET',
    headers:body?{'Content-Type':'application/json'}:undefined,
    body:body?JSON.stringify(body):undefined,
    signal:AbortSignal.timeout(20000),redirect:'error',
  });
  if(!response.ok)throw new Error(`Property API ${response.status}: ${await response.text()}`);
  return response.json();
}
export async function propertyJob(property:PropertyId,jobId:string) {
  if(!/^[a-zA-Z0-9_-]+$/.test(jobId))throw new Error('Invalid job identifier');
  const base=(process.env.STEWARD_BACKEND_URL || 'http://127.0.0.1:8001').replace(/\/$/,'');
  const response=await fetch(`${base}/api/jobs/${encodeURIComponent(jobId)}`,{signal:AbortSignal.timeout(20000),redirect:'error'});
  if(!response.ok)throw new Error(`Job API ${response.status}`);
  const result=await response.json();
  if(result.propertyId!==property)throw new Error('Job belongs to a different property');
  return result;
}
