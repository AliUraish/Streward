import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const backendPort=process.env.BACKEND_PORT || '8001';
const mcpPort=process.env.STEWARD_MCP_PORT || '8002';
const children=[];
let stopping=false;
function signalChild(child,signal){
  if(!child.pid || child.exitCode!==null || child.signalCode!==null)return;
  try{process.kill(process.platform==='win32'?child.pid:-child.pid,signal);}catch(error){if(error.code!=='ESRCH')throw error;}
}
async function stop(code=0){
  if(stopping)return;
  stopping=true;
  for(const child of children)signalChild(child,'SIGTERM');
  const timeout=setTimeout(()=>{for(const child of children)signalChild(child,'SIGKILL');process.exit(code);},5000);
  timeout.unref();
  await Promise.all(children.map(child=>!child.pid || child.exitCode!==null || child.signalCode!==null?Promise.resolve():new Promise(resolve=>child.once('exit',resolve))));
  clearTimeout(timeout);
  process.exit(code);
}
for(const sig of ['SIGINT','SIGTERM']) process.on(sig,()=>stop());
for(const [name,cmd,args,cwd] of [
  ['backend','bash',['run.sh'],path.join(root,'backend')],
  ['frontend','npm',['run','dev'],path.join(root,'frontend')],
  ['mcp','npm',['run','dev'],path.join(root,'mcp-runtime')],
]){
  const child=spawn(cmd,args,{cwd,detached:process.platform!=='win32',env:{...process.env,BACKEND_PORT:backendPort,BACKEND_URL:`http://127.0.0.1:${backendPort}`,STEWARD_BACKEND_URL:`http://127.0.0.1:${backendPort}`,STEWARD_MCP_PORT:mcpPort,MCP_URL:`http://127.0.0.1:${mcpPort}/mcp`,NEXT_TELEMETRY_DISABLED:'1',UV_CACHE_DIR:'/private/tmp/steward-uv-cache',UV_PYTHON_INSTALL_DIR:path.join(root,'.runtime','python')},stdio:['inherit','pipe','pipe']});
  children.push(child);
  for(const stream of [child.stdout,child.stderr])stream.on('data',data=>process.stdout.write(`[${name}] ${data}`));
  child.on('error',error=>{process.stderr.write(`${name}: ${error.message}\n`);stop(1);});
  child.on('exit',code=>{if(!stopping){process.stderr.write(`${name} stopped (${code}).\n`);stop(code??1);}});
}
console.log(`Steward local: http://127.0.0.1:3000 · API: http://127.0.0.1:${backendPort}/docs · MCP: http://127.0.0.1:${mcpPort}/mcp`);
