import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {MODEL,blank} from '../public/core.mjs';
import {columnTargets,TARGET_VERSION,METRIC_VERSION} from '../public/targets.mjs';
import {RUNNER_PROTOCOL} from '../public/table-import.mjs';
import {runTableRunner} from '../runner/table-runner.mjs';

const base=process.env.DEXFRAGGLER_TEST_URL??'http://127.0.0.1:5174',cookie='';
async function get(query=''){const r=await fetch(base+'/api/table'+query,{headers:{cookie}});assert.equal(r.status,200);return r.json()}
async function post(body,expected=200){const r=await fetch(base+'/api/table',{method:'POST',headers:{cookie,'Content-Type':'application/json'},body:JSON.stringify(body)}),data=await r.json();assert.equal(r.status,expected,JSON.stringify(data));return data}
const original=await get(),before=await get('?export=1');
const temp=await fs.mkdtemp(path.join(os.tmpdir(),'DexFraggler-scans-'));
await fs.mkdir(path.join(temp,'.runtime'));
await fs.writeFile(path.join(temp,'.runtime/runner-config.json'),JSON.stringify({url:base,cookie,secret:'isolated-local-test'}));
await fs.writeFile(path.join(temp,'.runtime/runner-control.json'),JSON.stringify({paused:true,priority:'Normal'}));
const tray=path.resolve(process.env.DEXFRAGGLER_TEST_TRAY??'.runtime/tray-v9-build/DexFraggler.Tray.exe');
let sequence=0;
async function cli(command,value,input){
 const report=path.join(temp,`command-${++sequence}.json`),args=['--root',temp,'--command',command,'--report',report];
 if(value)args.push('--value',value);if(input)args.push('--input',input);
 const child=spawn(tray,args,{windowsHide:true,stdio:'ignore'});
 const code=await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>{child.kill();reject(Error('Tray command timed out'))},40000);child.on('error',reject);child.on('exit',code=>{clearTimeout(timeout);resolve(code)})});
 assert.equal(code,0,await fs.readFile(report,'utf8'));return JSON.parse(await fs.readFile(report,'utf8'));
}
const config={allowDetune:false,anchors:[{slot:0,shape:'square'},{slot:31,shape:'saw'}]},patch={...blank(),algorithm:1};
const table={format:'dexfraggler-table',version:4,model:MODEL,targetVersion:TARGET_VERSION,metricVersion:METRIC_VERSION,config,targets:columnTargets(config),cells:[{id:0,algorithm:1,slot:0,patch,reference:{patch,score:1,loss:0}}]};
const seedFile=path.join(temp,'seeds.json');await fs.writeFile(seedFile,JSON.stringify(table));
try{
 await post({action:'running',running:false});
 const fresh=await cli('new-scan','Fresh scan integration'),freshId=fresh.scan.id;
 let current=await get();assert.equal(current.scan.id,freshId);assert.equal(current.cells.length,0);assert.deepEqual(current.config,original.config);
 assert.equal(JSON.parse(await fs.readFile(path.join(temp,'.runtime/runner-control.json'),'utf8')).paused,false);
 let catalog=await cli('list-scans');assert.ok(catalog.scans.some(s=>s.id===original.scan.id&&s.cells===original.cells.length));
 const claim=()=>post({action:'claim_row',worker:'seed-test',protocol:RUNNER_PROTOCOL,model:MODEL,targetVersion:TARGET_VERSION,metricVersion:METRIC_VERSION});
 const leased=(await claim()).job;assert.ok(leased);
 await cli('import-seeds',freshId,seedFile);
 current=await get();assert.equal(current.cells.length,0);assert.equal(current.pendingSeeds,1);assert.deepEqual(current.config,original.config);
 await post({action:'release',worker:'seed-test',id:leased.id,generation:leased.generation},409);
 const queued=(await claim()).job;assert.equal(queued.algorithm,1);assert.equal(queued.seeds.length,1);assert.deepEqual(queued.seeds[0].patch,patch);
 await post({action:'checkpoint_row',worker:'seed-test',id:queued.id,generation:queued.generation,cells:[],consumedSeeds:[queued.seeds[0].key]},400);
 assert.equal((await get()).pendingSeeds,1);
 await post({action:'release',worker:'seed-test',id:queued.id,generation:queued.generation});
 // Exercise the real renderer and current runner, including transactional queue acknowledgment.
 const abort=new AbortController();let checkpoints=0;
 const runtime=path.join(temp,'native-run');await fs.mkdir(runtime);await fs.writeFile(path.join(runtime,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
 await runTableRunner({root:path.resolve('.'),config:{runtimeDir:runtime,rowBudgetMs:500},signal:abort.signal,log(){},errorLog(){abort.abort()},async request(body){
  try{const result=await post(body);if(body.action==='checkpoint_row'){checkpoints++;abort.abort()}return result}catch(e){abort.abort();throw e}
 }});
 assert.equal(checkpoints,1);current=await get();assert.equal(current.pendingSeeds,0);assert.equal(current.cells.length,32);assert.ok(current.cells.every(c=>c.current));
 const established=await get('?export=1');await cli('import-seeds',freshId,seedFile);
 assert.deepEqual((await get('?export=1')).cells,established.cells,'Import must not replace any destination result with uploaded scores');
 const imported=await cli('import-seeds','new:Seeded scan integration',seedFile);current=await get();assert.equal(current.scan.id,imported.scan.id);assert.deepEqual(current.config,config);assert.equal(current.cells.length,0);assert.equal(current.pendingSeeds,1);
 // Validate all input before changing either the active scan or the queue.
 const bad=structuredClone(table);bad.cells[0].patch.feedback=8;
 await post({action:'import_seeds',destination:'new',name:'Invalid',generation:current.generation,table:bad},400);
 assert.equal((await get()).scan.id,imported.scan.id);assert.equal((await get('?scans=1')).scans.some(s=>s.name==='Invalid'),false);
 const races=await Promise.all(['A','B'].map(name=>fetch(base+'/api/table',{method:'POST',headers:{cookie,'Content-Type':'application/json'},body:JSON.stringify({action:'new_scan',name:'Race '+name,generation:current.generation})})));
 assert.deepEqual(races.map(r=>r.status).sort(),[200,409]);
 await cli('switch-scan',freshId);assert.deepEqual((await get('?export=1')).cells,established.cells);assert.deepEqual((await get()).config,original.config);
 console.log('Scan integration passed: desktop create/switch/import, isolated results, destination anchors, native seed remeasurement, atomic acknowledgment, stale leases, invalid input and concurrent scan changes.');
}finally{
 const current=await get();await post({action:'switch_scan',scanId:original.scan.id,generation:current.generation});await post({action:'running',running:original.running});
 assert.deepEqual((await get('?export=1')).cells,before.cells,'The original table must remain untouched');
 assert.deepEqual((await get()).config,original.config);
}
