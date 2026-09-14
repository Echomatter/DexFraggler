import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {initialState,runBatch,clone} from '../public/core.mjs';
import {Reference} from '../runner/reference.mjs';
import {DEFAULT_CONFIG} from '../public/targets.mjs';
const base='http://localhost:5173',login=await fetch(base+'/signin-with-chatgpt?return_to=/',{redirect:'manual'}),cookie=login.headers.get('set-cookie')?.split(';')[0];assert.ok(cookie);
async function get(path=''){const r=await fetch(base+'/api/table'+path,{headers:{cookie}});assert.equal(r.status,200);return r.json()}
async function post(body){const r=await fetch(base+'/api/table',{method:'POST',headers:{cookie,'Content-Type':'application/json',Origin:base},body:JSON.stringify(body)});return {status:r.status,data:await r.json()}}
assert.equal((await fetch(base+'/api/table')).status,401);assert.equal((await post({action:'running',running:'yes'})).status,400);
await post({action:'running',running:false});let board=await get();assert.equal((await post({action:'configure',config:DEFAULT_CONFIG,revision:board.revision})).status,200);
if(process.argv[2]){const seeds=JSON.parse(await fs.readFile(process.argv[2],'utf8'));for(let i=0;i<seeds.cells.length;i+=64)assert.equal((await post({action:'import',cells:seeds.cells.slice(i,i+64)})).status,200);board=await get();assert.equal(board.cells.length,1024);assert.ok(board.cells.every(c=>!c.current));console.log('All 1,024 historical patches imported; old scores remain unverified.');}
await post({action:'running',running:true});const claims=await Promise.all(['test-a','test-b'].map(worker=>post({action:'claim',worker})));assert.equal(claims.filter(r=>r.data.job).length,1);const index=claims.findIndex(r=>r.data.job),job=claims[index].data.job,worker=['test-a','test-b'][index];
let state=initialState(job.target,job.cell?[{patch:job.cell.patch}]:[],32,job.algorithm);state.allowDetune=false;state=runBatch(state,25);const ref=new Reference();let reference;try{reference=await ref.score(state.elites[0].patch,job.target,32)}finally{ref.close()}
const body={action:'checkpoint',id:job.id,generation:job.generation,worker,state,reference};const bad=clone(body);bad.state.elites[0].patch.algorithm=job.algorithm===32?1:32;assert.equal((await post(bad)).status,400);
const accepted=await post(body);assert.equal(accepted.status,200,JSON.stringify(accepted));assert.equal((await post(body)).status,409);
board=await get();assert.ok(board.cells.find(c=>c.id===job.id).current);assert.equal((await get('?cell='+job.id)).cell.reference.notes.length,3);
const next=(await post({action:'claim',worker:'stale'})).data.job;board=await get();const config={...DEFAULT_CONFIG,anchors:[{slot:0,shape:'sine'},...DEFAULT_CONFIG.anchors.slice(1)]};assert.equal((await post({action:'configure',config,revision:board.revision})).status,200);assert.equal((await post({...body,id:next.id,worker:'stale',generation:next.generation})).status,409);board=await get();assert.equal(board.cells.find(c=>c.id===job.id).current,false);assert.ok((await get('?cell='+job.id)).cell.patch);
const invalid={...DEFAULT_CONFIG,harmonics:16,anchors:[{slot:0,shape:'custom',target:{kind:'fourier-path-v1',sin:Array(31).fill(0).concat(1),cos:Array(32).fill(0)}}]};assert.equal((await post({action:'configure',config:invalid,revision:board.revision})).status,400);assert.deepEqual((await get()).config,config);
await post({action:'running',running:false});board=await get();await post({action:'configure',config:DEFAULT_CONFIG,revision:board.revision});const backup=await get('?export=1');assert.equal(backup.version,2);assert.ok(backup.cells.length);console.log('Table API passed: auth, import, one lease, algorithm guard, native checkpoint, stale rejection, invalid anchors and backup.');
