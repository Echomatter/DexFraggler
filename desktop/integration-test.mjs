import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import crypto from 'node:crypto';

const work=path.dirname(fileURLToPath(import.meta.url));
const executable=path.resolve(process.env.DEXFRAGGLER_TEST_TRAY??path.join(work,'DexFraggler.Tray.exe'));
const root=path.join(work,'integration-probe-'+crypto.randomUUID());
await fs.mkdir(path.join(root,'runner'),{recursive:true});
await fs.mkdir(path.join(root,'.runtime'),{recursive:true});
const serverScript=String.raw`
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
import crypto from 'node:crypto';
let running=true;
async function atomicStatus(text){const target=path.join(root,'.runtime/runner-status.json'),temporary=target+'.'+crypto.randomUUID()+'.tmp';await fs.writeFile(temporary,text);for(let i=0;;i++)try{await fs.rename(temporary,target);return}catch(e){if(i>=20)throw e;await new Promise(r=>setTimeout(r,20))}}
async function status(){await atomicStatus(JSON.stringify({pid:process.pid,root,processStartTime:Date.now()-process.uptime()*1000,running,localPaused:false,priority:'Normal',phase:'Isolated menu integration stub',updatedAt:Date.now(),evaluations:42}));}
await status();
setInterval(()=>status(),500).unref();
const server=http.createServer(async(req,res)=>{
 let body='';for await(const chunk of req)body+=chunk;
 const authenticated=req.headers['x-dexfraggler-worker']==='isolated-test-secret'&&req.headers['oai-sites-authorization']==='Bearer isolated-test-bypass'&&req.headers.cookie==='isolated=test';
 const event={method:req.method,url:req.url,authenticated};
 if(req.method==='POST'){Object.assign(event,JSON.parse(body));running=event.running;await status();}
 await fs.appendFile(path.join(root,'requests.jsonl'),JSON.stringify(event)+'\n');
 res.setHeader('content-type','application/json');
 if(!authenticated){res.writeHead(401);res.end('{}');return;}
 if(req.method==='POST'){res.end(JSON.stringify({ok:true}));return;}
 let mode;try{mode=JSON.parse(await fs.readFile(path.join(root,'response-mode.json'),'utf8'));}catch{mode={version:4};}
 const table={format:mode.invalid?'not-a-table':'dexfraggler-table',version:mode.version,targetVersion:'ideal-waveform-v1',config:{allowDetune:false,anchors:[{slot:0,shape:'triangle'},{slot:31,shape:'saw'}]},targets:Array.from({length:32},(_,slot)=>({kind:'ideal-waveform-v1',weights:[0,1-slot/31,0,slot/31]})),model:'test-model',cells:[{algorithm:1,slot:0,patch:{}}]};
 if(mode.fourier) { table.config.harmonics=32; table.targets[0]={kind:'fourier-v1',sin:[1],cos:[0]}; }
 if(mode.unknownTargetVersion) table.targetVersion='unknown';
 if(mode.empty) table.cells=[];
 res.end(JSON.stringify(table));
});
server.listen(0,'127.0.0.1',async()=>{await fs.writeFile(path.join(root,'ready.json'),JSON.stringify({port:server.address().port}));});
`;
await fs.writeFile(path.join(root,'runner/background.mjs'),serverScript);
const server=spawn(process.execPath,[path.join(root,'runner/background.mjs')],{cwd:root,windowsHide:true,stdio:'ignore'});
let tray;
const checks={};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function waitFor(fn,ms=10000){const until=Date.now()+ms;while(Date.now()<until){try{const result=await fn();if(result)return result;}catch{}await sleep(100);}throw Error('Timed out waiting for integration state.');}
async function read(name){return JSON.parse(await fs.readFile(path.join(root,name),'utf8'));}
let sequence=0;
async function cli(args,expectedExit=0){
 const report=path.join(root,'command-'+(++sequence)+'.json');
 const child=spawn(executable,['--root',root,...args,'--report',report],{cwd:work,windowsHide:true,stdio:'ignore'});
 const code=await new Promise((resolve,reject)=>{const t=setTimeout(()=>{child.kill();reject(Error('CLI command timed out.'));},35000);child.once('exit',c=>{clearTimeout(t);resolve(c)});child.once('error',e=>{clearTimeout(t);reject(e)});});
 if(code!==expectedExit)throw Error('Unexpected command exit '+code+' for '+args.join(' '));
 return JSON.parse(await fs.readFile(report,'utf8'));
}
try{
 const ready=await waitFor(()=>read('ready.json'));
 await fs.writeFile(path.join(root,'.runtime/runner-config.json'),JSON.stringify({url:'http://127.0.0.1:'+ready.port,bypass:'isolated-test-bypass',secret:'isolated-test-secret',cookie:'isolated=test'}));
 await fs.writeFile(path.join(root,'.runtime/runner-control.json'),JSON.stringify({paused:false,priority:'Normal',updatedAt:Date.now()}));
 tray=spawn(executable,['--root',root],{cwd:work,windowsHide:true,stdio:'ignore'});
 await waitFor(async()=>{const s=await read('.runtime/tray-status.json');return s.notifyIconVisible&&s.pid===tray.pid;});
 let result=await cli(['--status']);
 checks.liveNotifyIconVerified=result.alive&&result.processVerified&&result.uiHeartbeatFresh&&result.tray.menuItems===12;
 result=await cli(['--command','pause']);
 checks.pauseMenuLogic=result.localSaved&&result.paused&&result.siteSynchronized&&(await read('.runtime/runner-control.json')).paused;
 await waitFor(async()=>{const s=await read('.runtime/tray-status.json');return s.localPaused;});
 checks.existingTrayObservedPause=(await cli(['--status'])).tray.localPaused;
 result=await cli(['--command','resume']);
 checks.resumeMenuLogic=result.localSaved&&!result.paused&&result.siteSynchronized&&!(await read('.runtime/runner-control.json')).paused;
 result=await cli(['--command','priority','--value','BelowNormal']);
 checks.priorityAppliedToOwnedStub=result.priority==='BelowNormal'&&result.ownedWorkerPriority==='BelowNormal';
 await fs.writeFile(path.join(root,'response-mode.json'),JSON.stringify({version:4}));
 const output=path.join(root,'table-v4.json');
 result=await cli(['--command','download-to-path','--output',output]);
 const saved=await read('table-v4.json');
 checks.downloadV4=result.ok&&saved.version===4&&saved.targetVersion==='ideal-waveform-v1'&&saved.targets.length===32&&saved.config.anchors.length===2;
 await fs.writeFile(path.join(root,'response-mode.json'),JSON.stringify({version:4,empty:true}));
 result=await cli(['--command','download-to-path','--output',path.join(root,'empty-table-v4.json')]);
 checks.downloadEmptyV4=result.ok&&(await read('empty-table-v4.json')).cells.length===0;
 const protectedFile=path.join(root,'preserved.json');await fs.writeFile(protectedFile,'preserve this file');
 for(const [name,mode] of Object.entries({rejectV2:{version:2},rejectV3:{version:3},rejectInvalidFormat:{version:4,invalid:true},rejectFourier:{version:4,fourier:true},rejectUnknownTargetVersion:{version:4,unknownTargetVersion:true}})){
  await fs.writeFile(path.join(root,'response-mode.json'),JSON.stringify(mode));
  await cli(['--command','download-to-path','--output',protectedFile],1);
  checks[name]=(await fs.readFile(protectedFile,'utf8'))==='preserve this file';
 }
 const events=(await fs.readFile(path.join(root,'requests.jsonl'),'utf8')).trim().split('\n').map(JSON.parse);
 checks.authenticatedHeaders=events.every(e=>e.authenticated);
 checks.exactEndpoints=events.every(e=>e.url==='/api/table'||e.url==='/api/table?export=1');
 // Stop only the child processes launched by this isolated test. No actual project
 // runner is contacted, paused, reprioritized, started or terminated.
 tray.kill();await new Promise(r=>tray.once('exit',r));tray=null;
 checks.deadTrayRejected=!(await cli(['--status'],3)).alive;
 server.kill();await new Promise(r=>server.once('exit',r));
 result=await cli(['--command','pause']);
 checks.offlinePauseRetained=result.localSaved&&result.paused&&!result.siteSynchronized&&(await read('.runtime/runner-control.json')).paused;
 const report={passed:Object.values(checks).every(Boolean),checks,isolatedRoot:root,liveProjectTouched:false,finishedAt:new Date().toISOString()};
 await fs.writeFile(path.join(work,'integration-test.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report,null,2));
 if(!report.passed)process.exitCode=1;
}catch(error){console.error(error.message);process.exitCode=1;}finally{if(tray&&!tray.killed)tray.kill();if(!server.killed)server.kill();}
