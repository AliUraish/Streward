import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp,mkdir,writeFile,rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { propertyApi,propertyJob } from '../agent/lib/property-api.ts';

test('model sessions require an issued property-specific mutation mandate',async()=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),'steward-agent-scope-'));
  const previous=process.env.STEWARD_AGENT_RUNTIME_DIR;
  process.env.STEWARD_AGENT_RUNTIME_DIR=directory;
  const originalFetch=global.fetch;
  let requests=0;
  global.fetch=async()=>{requests++;return Response.json({id:'job-1',propertyId:'cedar'});};
  try{
    await assert.rejects(()=>propertyApi('cedar','inspections',{scope:'all'}),/no inspection-write mandate/);
    const policies=path.join(directory,'.eve','property-sessions','policies');
    await mkdir(policies,{recursive:true});
    await writeFile(path.join(policies,'session-readonly.json'),JSON.stringify({propertyId:'cedar',allowMutations:false}));
    await assert.rejects(()=>propertyApi('cedar','inspections',{scope:'all'},{id:'session-readonly'}),/read-only/);
    await writeFile(path.join(policies,'session-actions.json'),JSON.stringify({propertyId:'cedar',allowMutations:true}));
    await assert.rejects(()=>propertyApi('harbor','inspections',{scope:'all'},{id:'session-actions'}),/another property/);
    assert.equal(requests,0,'unapproved requests never reach the backend');
    const result=await propertyApi('cedar','inspections',{scope:'all'},{id:'child-agent',parent:{rootSessionId:'session-actions'}});
    assert.equal(result.id,'job-1');
    assert.equal(requests,1);
    await assert.rejects(()=>propertyJob('harbor','job-1'),/different property/);
  }finally{
    global.fetch=originalFetch;
    if(previous===undefined)delete process.env.STEWARD_AGENT_RUNTIME_DIR;else process.env.STEWARD_AGENT_RUNTIME_DIR=previous;
    await rm(directory,{recursive:true,force:true});
  }
});
