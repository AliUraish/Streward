import { Client } from 'eve/client';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const chunks=[];
for await (const chunk of process.stdin)chunks.push(chunk);
const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
const propertyId=input.propertyId ?? input.context?.property?.id;
if(!['cedar','harbor','juniper'].includes(propertyId))throw new Error('A valid property scope is required.');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const directory=path.join(root,'.eve','property-sessions');
await mkdir(directory,{recursive:true,mode:0o700});
const allowMutations=input.allowMutations===true;
const sessionFile=path.join(directory,`${propertyId}-${allowMutations?'actions':'readonly'}.json`);
const client=new Client({host:process.env.STEWARD_EVE_URL || 'http://127.0.0.1:2000',redirect:'error'});
const question=input.question || input.message;
if(typeof question!=='string' || !question.trim())throw new Error('A message is required.');
const message=`Work only within the ${propertyId} property scope. This is a ${allowMutations?'locally authorized inspection mission':'read-only evidence question; do not start inspection jobs or mutate records'}.\n${question}`;
let saved;
try{saved=JSON.parse(await readFile(sessionFile,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
let session,response;
if(saved?.sessionId){
  session=client.sessions.attach(saved.sessionId);
  response=await session.send(message,{clientContext:{propertyId}});
}else{
  const created=await client.sessions.create();
  session=created.session;
  const sessionId=session.state.sessionId;
  const policies=path.join(directory,'policies');
  await mkdir(policies,{recursive:true,mode:0o700});
  await writeFile(path.join(policies,`${sessionId}.json`),JSON.stringify({propertyId,allowMutations}),{mode:0o600});
  await writeFile(sessionFile,JSON.stringify({sessionId,propertyId}),{mode:0o600});
  response=await session.send(message,{clientContext:{propertyId}});
}
const result=await response.result();
if(result.status==='failed')throw new Error('Model agent turn failed. Inspect the local eve logs; no completion is claimed.');
console.log(JSON.stringify({text:result.message ?? '',sessionId:result.sessionId,status:result.status}));
