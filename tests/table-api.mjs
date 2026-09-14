import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {initialState,clone,blank} from '../public/core.mjs';
import {Reference} from '../runner/reference.mjs';
const base='http://localhost:5173',login=await fetch(base+'/signin-with-chatgpt?return_to=/',{redirect:'manual'}),cookie=login.headers.get('set-cookie')?.split(';')[0];assert.ok(cookie);
async function get(path=''){const r=await fetch(base+'/api/table'+path,{headers:{cookie}});assert.equal(r.status,200);return r.json()}
async function post(body){const r=await fetch(base+'/api/table',{method:'POST',headers:{cookie,'Content-Type':'application/json',Origin:base},body:JSON.stringify(body)});return {status:r.status,data:await r.json()}}
const original=await get(),ref=new Reference();
try{
 assert.equal((await fetch(base+'/api/table')).status,401);
 assert.equal((await post({action:'running',running:'yes'})).status,400);
 const cross=await fetch(base+'/api/table',{method:'POST',headers:{cookie,Origin:'https://example.com'},body:JSON.stringify({action:'running',running:true})});assert.equal(cross.status,403);
 await post({action:'running',running:false});let board=await get();
 const config={harmonics:32,allowDetune:false,anchors:[{slot:0,shape:'custom',name:'API validation',target:{kind:'fourier-path-v1',sin:[1,.17+Date.now()%1000/10000,...Array(30).fill(0)],cos:Array(32).fill(0)}}]};
 assert.equal((await post({action:'configure',config,revision:board.revision})).status,200);
 assert.equal((await post({action:'claim_row',worker:'paused'})).data.job,null);
 await post({action:'running',running:true});
 const claims=await Promise.all(['row-a','row-b'].map(worker=>post({action:'claim_row',worker,status:{priority:'BelowNormal',cellsPerMinute:42}})));
 assert.equal(claims.filter(r=>r.data.job).length,1);const index=claims.findIndex(r=>r.data.job),job=claims[index].data.job,worker=['row-a','row-b'][index];
 assert.equal(job.targets.length,32);assert.equal(job.targetKeys.length,32);
 assert.equal((await post({action:'renew',id:job.id,generation:job.generation,worker:'wrong'})).status,409);
 assert.equal((await post({action:'renew',id:job.id,generation:job.generation,worker})).status,200);
 const patch=blank();patch.algorithm=job.algorithm;const refs=await ref.scoreMany(patch,job.targets,32),start=Math.floor(job.id/32)*32;
 const cells=job.targets.map((target,i)=>({id:start+i,state:initialState(target,[{patch}],32,job.algorithm),reference:refs[i],visited:start+i===job.id}));
 const body={action:'checkpoint_row',id:job.id,generation:job.generation,worker,cells};
 const before=await get();const wrongRow=clone(body);wrongRow.cells[10].id=(start+32)%1024;assert.equal((await post(wrongRow)).status,400);assert.equal((await get()).revision,before.revision);
 const invalid=clone(body);invalid.cells[10].reference.score=.01;assert.equal((await post(invalid)).status,400);assert.equal((await get()).revision,before.revision);
 const duplicate=clone(body);duplicate.cells[10]=duplicate.cells[9];assert.equal((await post(duplicate)).status,400);
 const accepted=await post(body);assert.equal(accepted.status,200,JSON.stringify(accepted));assert.equal(accepted.data.count,32);assert.equal((await post(body)).status,409);
 board=await get();const row=board.cells.filter(c=>c.id>=start&&c.id<start+32);assert.equal(row.length,32);assert.ok(row.every(c=>c.current));assert.equal(row.filter(c=>c.visits===1).length,1);assert.equal(row.filter(c=>c.visits===0).length,31);
 const detail=(await get('?cell='+job.id)).cell;assert.equal(detail.reference.notes.length,3);assert.equal(detail.provenance,undefined);
 // Force visits only through normal claims; the next claim on this already-populated row must reject regressions.
 let regressionChecked=false;
 for(let attempt=0;attempt<34;attempt++){
  const name='next-'+attempt,next=(await post({action:'claim_row',worker:name})).data.job;assert.ok(next);
  if(next.algorithm===job.algorithm){
   const c=next.cells.find(c=>c.id===next.id),bad={action:'checkpoint_row',id:next.id,generation:next.generation,worker:name,cells:[{id:next.id,state:clone(c.state),reference:clone(c.reference),visited:true}]};
   bad.cells[0].state.elites[0].loss+=.1;assert.equal((await post(bad)).status,400);regressionChecked=true;
   assert.equal((await post({action:'release',id:next.id,generation:next.generation,worker:name})).status,200);break;
  }
  // Failed-cell cooldown lets the integration exercise another scheduling choice without forging measurements.
  assert.equal((await post({action:'failed',id:next.id,generation:next.generation,worker:name,error:'Integration retry check'})).status,200);
 }
 assert.ok(regressionChecked,'Visited row must be scheduled again');
 const next=(await post({action:'claim_row',worker:'stale'})).data.job;board=await get();const updated={...config,anchors:[{slot:0,shape:'square'}]};assert.equal((await post({action:'configure',config:updated,revision:board.revision})).status,200);
 assert.equal((await post({...body,id:next.id,worker:'stale',generation:next.generation})).status,409);assert.equal((await get('?cell='+job.id)).cell.current,false);assert.ok((await get('?cell='+job.id)).cell.reference.patch);
 board=await get();const silent={...updated,harmonics:16,anchors:[{slot:0,shape:'custom',target:{kind:'fourier-path-v1',sin:Array(31).fill(0).concat(1),cos:Array(32).fill(0)}}]};assert.equal((await post({action:'configure',config:silent,revision:board.revision})).status,400);assert.deepEqual((await get()).config,updated);
 await post({action:'running',running:false});const backup=await get('?export=1');assert.equal(backup.version,3);assert.equal(backup.targets.length,32);assert.ok(backup.cells.length);assert.equal(backup.cells[0].state,undefined);assert.equal(backup.cells[0].provenance,undefined);
 await fs.writeFile('.runtime/local-runner-config.json',JSON.stringify({url:base,cookie,secret:'',bypass:'',runtimeDir:'.runtime/local-runner'}));
 console.log('Table API passed: auth, row lease/renewal, atomic32-cell saves, monotonic champions, fair visits, pause, stale targets, invalid anchors, compact export.');
}finally{await ref.close();await post({action:'running',running:false});const b=await get();await post({action:'configure',config:original.config,revision:b.revision});}
