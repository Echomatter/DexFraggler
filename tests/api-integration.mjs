import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {runBatch,clone} from '../public/core.mjs';
import {Reference} from '../runner/reference.mjs';
const base='http://localhost:5173';
const login=await fetch(base+'/signin-with-chatgpt?return_to=/',{redirect:'manual'});
const cookie=login.headers.get('set-cookie')?.split(';')[0];assert.ok(cookie);
async function get(){const r=await fetch(base+'/api/lab',{headers:{cookie}});assert.equal(r.status,200);return r.json()}
async function post(body){const r=await fetch(base+'/api/lab',{method:'POST',headers:{cookie,'Content-Type':'application/json',Origin:base},body:JSON.stringify(body)});return {status:r.status,data:await r.json()}}
assert.equal((await fetch(base+'/api/lab')).status,401);
let data=await get();assert.equal(data.runs.length,3);
for(const shape of ['saw','square','triangle'])await post({action:'running',shape,running:false});
assert.equal((await post({action:'running',shape:'noise',running:true})).status,400);
await post({action:'running',shape:'saw',running:true});
const claims=await Promise.all([post({action:'claim',worker:'test-a'}),post({action:'claim',worker:'test-b'})]);
assert.equal(claims.filter(x=>x.data.run).length,1);
const run=claims.find(x=>x.data.run).data.run,worker=run.lease_owner;
const state=runBatch(run.state,100);
const reference=new Reference();let measured;try{measured=await reference.score(state.elites[0].patch,'saw')}finally{reference.close()}
let result=await post({action:'checkpoint',shape:'saw',worker,revision:run.revision,state,reference:measured});assert.equal(result.status,200,JSON.stringify(result));
data=await get();assert.equal(data.runs.find(x=>x.shape==='saw').state.evaluations,state.evaluations);
const next=(await post({action:'claim',worker:'test-c'})).data.run;assert.ok(next);
await post({action:'running',shape:'saw',running:false});
assert.equal((await post({action:'checkpoint',shape:'saw',worker:'test-c',revision:next.revision,state:next.state})).status,409);
const after=await get();assert.equal(after.runs.find(x=>x.shape==='saw').running,0);
const wrong=clone(after.runs[0].state.elites[0].patch);wrong.operators[0].fine=100;
assert.equal((await post({action:'import',shape:'saw',patches:[wrong]})).status,400);
const origin=await fetch(base+'/api/lab',{method:'POST',headers:{cookie,Origin:'https://wrong.example','Content-Type':'application/json'},body:JSON.stringify({action:'running',shape:'saw',running:true})});assert.equal(origin.status,403);
const summary={authorization:true,singleLease:true,checkpointPersisted:true,nativeMeasurementPersisted:true,pauseRejectsStaleBatch:true,invalidPatchRejected:true,crossOriginRejected:true};
await fs.writeFile('.runtime/api-test-results.json',JSON.stringify(summary,null,2));console.log(summary);

