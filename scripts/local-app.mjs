import fs from 'node:fs/promises';
import {openSync,closeSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import {localUrl} from '../runner/local-url.mjs';

export const root=fileURLToPath(new URL('../',import.meta.url)).replace(/[\\/]$/,'');
export async function localConfig() {
  const runtime=path.join(root,'.runtime');
  await fs.mkdir(runtime,{recursive:true});
  const filename=path.join(runtime,'runner-config.json');
  try {const config=JSON.parse(await fs.readFile(filename,'utf8'));localUrl(config.url);return config;}
  catch(e) {
    if(e.code!=='ENOENT')throw e;
    const config={url:'http://127.0.0.1:5173',secret:'local-only',rowBudgetMs:2800};
    await fs.writeFile(filename,JSON.stringify(config),{flag:'wx'});
    return config;
  }
}

export async function ensureLocalServer(config) {
  config??=await localConfig();
  const url=localUrl(config.url),workspace=createHash('sha256').update(root).digest('hex');
  const ready=async()=>{
    let response;
    try {response=await fetch(new URL('/api/local/health',url),{signal:AbortSignal.timeout(3000),redirect:'error'});}
    catch {return false;}
    if(!response.ok)throw Error('Another application is using the configured local port.');
    const health=await response.json();
    if(health.app!=='DexFraggler'||health.workspace!==workspace||health.database!=='ok')throw Error('The local port belongs to another workspace.');
    return true;
  };
  if(await ready())return url.href;
  await fs.access(path.join(root,'dist/server/index.js')).catch(()=>{throw Error('Build the local app first: npm ci && npm run build');});
  const out=openSync(path.join(root,'.runtime/local-server.log'),'a');
  let child;
  try {child=spawn(process.execPath,[path.join(root,'scripts/run-framework.mjs'),'start'],{
    cwd:root,detached:true,windowsHide:true,stdio:['ignore',out,out],
    env:{...process.env,DEXFRAGGLER_PORT:url.port||'80'}
  });} finally {closeSync(out);}
  let failure;child.on('error',e=>{failure=e;});child.unref();
  for(let attempt=0;attempt<60;attempt++) {
    if(failure)throw failure;
    if(await ready())return url.href;
    await new Promise(r=>setTimeout(r,1000));
  }
  throw Error('Local server did not start. See .runtime/local-server.log.');
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  console.log('DexFraggler is ready at '+await ensureLocalServer());
}
