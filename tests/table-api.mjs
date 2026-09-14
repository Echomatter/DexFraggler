import {RUNNER_PROTOCOL} from '../public/table-import.mjs';
import assert from 'node:assert/strict';
import {MODEL,initialState,runBatch,clone,blank} from '../public/core.mjs';
import {TARGET_VERSION,columnTargets,targetKey,validateTarget} from '../public/targets.mjs';
import {METRIC_VERSION} from '../runner/measurement.mjs';
import {Reference} from '../runner/reference.mjs';

const base=(process.env.DEXFRAGGLER_TEST_URL??'http://127.0.0.1:5174').replace(/\/$/,'');
assert.ok(['localhost','127.0.0.1','[::1]'].includes(new URL(base).hostname),'API validation must use the isolated local database.');
const cookie='';

async function get(path=''){
 const response=await fetch(base+'/api/table'+path,{headers:{cookie}});
 assert.equal(response.status,200,`GET /api/table${path}`);
 return response.json();
}
async function post(body){
 const response=await fetch(base+'/api/table',{method:'POST',headers:{cookie,'Content-Type':'application/json',Origin:base},body:JSON.stringify(body)});
 return {status:response.status,data:await response.json()};
}
async function successful(body){const result=await post(body);assert.equal(result.status,200,JSON.stringify(result));return result.data;}
const claim=(worker,extra={})=>post({action:'claim_row',worker,protocol:RUNNER_PROTOCOL,model:MODEL,targetVersion:TARGET_VERSION,metricVersion:METRIC_VERSION,...extra});
async function rejectsAtomically(body,status=400){
 const before=await get(),result=await post(body);
 assert.equal(result.status,status,JSON.stringify(result));
 const after=await get();
 assert.equal(after.revision,before.revision);
 assert.equal(after.generation,before.generation);
 assert.equal(after.activeId,before.activeId);
 assert.deepEqual(after.cells,before.cells);
 return result;
}
function rowPatch(algorithm){const patch=blank();patch.algorithm=algorithm;return patch;}
function checkpoint(job,worker,cells){return {action:'checkpoint_row',id:job.id,generation:job.generation,worker,cells};}
function stateFor(target,algorithm){return initialState(target,[],127,algorithm);}

const original=await get(),reference=new Reference();
try{
 assert.equal((await fetch(base+'/api/table')).status,200);
 assert.equal((await fetch(base+'/api/table',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://example.com'},body:JSON.stringify({action:'running',running:true})})).status,403);
 assert.equal((await post({action:'running',running:'yes'})).status,400);
 const cross=await fetch(base+'/api/table',{method:'POST',headers:{cookie,Origin:'https://example.com','Content-Type':'application/json'},body:JSON.stringify({action:'running',running:true})});
 assert.equal(cross.status,403);
 await successful({action:'running',running:false});

 for(const action of ['claim','import','checkpoint'])await rejectsAtomically({action});
 let board=await get();
 const config={allowDetune:false,anchors:[{slot:0,shape:'sine'}]};
 await successful({action:'configure',config,revision:board.revision});
 assert.deepEqual((await get()).config,config);
 await rejectsAtomically({action:'configure',config,revision:board.revision},409);
 for(const extra of [{model:undefined},{model:'outdated-model'},{targetVersion:undefined},{targetVersion:'outdated-target'},{metricVersion:undefined},{metricVersion:'outdated-metric'}]){
  const result=await claim('incompatible-engine',extra);assert.equal(result.status,409);
  assert.equal((await get()).activeId,null);
 }
 assert.equal((await claim('paused')).data.job,null);
 await successful({action:'running',running:true});

 const workers=['row-a','row-b'];
 const claims=await Promise.all(workers.map(worker=>claim(worker,{status:{priority:'BelowNormal',cellsPerMinute:42}})));
 assert.ok(claims.every(result=>result.status===200));
 assert.equal(claims.filter(result=>result.data.job).length,1,'Concurrent claims must grant one row lease.');
 const winner=claims.findIndex(result=>result.data.job),job=claims[winner].data.job,worker=workers[winner];
 assert.equal(job.targets.length,32);assert.equal(job.targetKeys.length,32);
 assert.deepEqual(job.targets,columnTargets(config));
 assert.deepEqual(job.targetKeys,job.targets.map(targetKey));
 assert.ok(job.targets.every(target=>validateTarget(target).weights[0]===1));
 await rejectsAtomically({action:'renew',id:job.id,generation:job.generation,worker:'wrong'},409);
 await successful({action:'renew',id:job.id,generation:job.generation,worker});

 // Model and native champions are independent. A measured blank patch remains
 // valid when the mathematical initialization already found a better model patch.
 const nativeResults=await reference.scoreMany(rowPatch(job.algorithm),job.targets);
 assert.ok(nativeResults.every(result=>result.metricVersion===METRIC_VERSION&&result.notes.every(note=>note.metricVersion===METRIC_VERSION)));
 const start=Math.floor(job.id/32)*32,states=new Map();
 const cells=job.targets.map((target,slot)=>{
  const key=targetKey(target);
  if(!states.has(key))states.set(key,stateFor(target,job.algorithm));
  return {id:start+slot,state:clone(states.get(key)),reference:nativeResults[slot],visited:start+slot===job.id};
 });
 const body=checkpoint(job,worker,cells),beforeSave=await get();
 const wrongRow=clone(body);wrongRow.cells[10].id=(start+32)%1024;await rejectsAtomically(wrongRow);
 const invalid=clone(body);invalid.cells[10].reference.score=.01;await rejectsAtomically(invalid);
 const wrongMetric=clone(body);wrongMetric.cells[10].reference.notes[0].metricVersion='outdated-metric';await rejectsAtomically(wrongMetric);
 const duplicate=clone(body);duplicate.cells[10]=clone(duplicate.cells[9]);await rejectsAtomically(duplicate);
 const concurrentSaves=await Promise.all([post(body),post(body)]);
 assert.deepEqual(concurrentSaves.map(result=>result.status).sort(),[200,409],'An atomic row lease must be consumed once.');
 assert.equal(concurrentSaves.find(result=>result.status===200).data.count,32);
 await rejectsAtomically(body,409);
 board=await get();
 assert.equal(board.revision,beforeSave.revision+1);
 const row=board.cells.filter(cell=>cell.id>=start&&cell.id<start+32);
 assert.equal(row.length,32);assert.ok(row.every(cell=>cell.current));
 for(const cell of row){
  const previous=beforeSave.cells.find(old=>old.id===cell.id);
  assert.equal(cell.visits,(previous?.current?previous.visits:0)+Number(cell.id===job.id));
 }
 const detail=(await get('?cell='+job.id)).cell;
 assert.equal(detail.reference.notes.length,3);
 assert.ok(detail.reference.notes.every(note=>note.metricVersion===METRIC_VERSION));
 assert.equal(detail.state.model,MODEL);
 assert.deepEqual(detail.state.shape,job.targets[job.slot]);

 // Cooldowns advance the scheduler using normal API operations until the
 // populated row returns, then exercise both champion monotonicity rules.
 let regressionChecked=false;
 for(let attempt=0;attempt<34;attempt++){
  const name='next-'+attempt,nextResult=await claim(name);
  assert.equal(nextResult.status,200);const next=nextResult.data.job;assert.ok(next);
  if(next.algorithm===job.algorithm){
   const current=next.cells.find(cell=>cell.id===next.id);assert.ok(current?.state&&current.reference);
   assert.ok(current.reference.notes.every(note=>note.wave===undefined&&note.target===undefined&&note.idealTarget===undefined));
   const fullReference=(await get('?cell='+next.id)).cell.reference;
   const change={id:next.id,state:clone(current.state),reference:clone(fullReference),visited:true};
   const badModel=checkpoint(next,name,[clone(change)]);
   badModel.cells[0].state.elites.forEach(elite=>{elite.loss=Math.min(5,elite.loss+.05)});
   await rejectsAtomically(badModel);
   const badNative=checkpoint(next,name,[clone(change)]),worse=badNative.cells[0].reference;
   const error=Math.sqrt(Math.min(1,worse.loss+.05));
   worse.notes.forEach(note=>{note.error=error;note.score=Math.sqrt(Math.max(0,1-error*error))});
   worse.loss=Math.max(...worse.notes.map(note=>note.error**2));worse.score=Math.min(...worse.notes.map(note=>note.score));
   assert.ok(worse.loss>current.reference.loss,'The native regression fixture must be strictly worse.');
   await rejectsAtomically(badNative);
   const badCount=checkpoint(next,name,[clone(change)]);badCount.cells[0].state.evaluations-=1;await rejectsAtomically(badCount);
   change.state=runBatch(change.state,10);
   assert.ok(change.state.evaluations>current.state.evaluations);
   assert.ok(change.state.elites[0].loss<=current.state.elites[0].loss+1e-12);
   change.reference=null;
   await successful(checkpoint(next,name,[change]));
   const saved=(await get('?cell='+next.id)).cell;
   assert.equal(saved.evaluations,change.state.evaluations);
   assert.deepEqual(saved.reference,fullReference);
   regressionChecked=true;break;
  }
  await successful({action:'failed',id:next.id,generation:next.generation,worker:name,error:'Integration scheduling check'});
 }
 assert.ok(regressionChecked,'The populated row must be scheduled again.');

 const stale=(await claim('stale')).data.job;assert.ok(stale);
 board=await get();
 const updated={allowDetune:false,anchors:[{slot:0,shape:'square'}]};
 await successful({action:'configure',config:updated,revision:board.revision});
 await rejectsAtomically({action:'renew',id:stale.id,generation:stale.generation,worker:'stale'},409);
 await rejectsAtomically(checkpoint(stale,'stale',cells),409);
 await rejectsAtomically({action:'release',id:stale.id,generation:stale.generation,worker:'stale'},409);
 const staleDetail=(await get('?cell='+job.id)).cell;
 assert.equal(staleDetail.current,false);assert.ok(staleDetail.reference.patch);
 const changedJob=(await claim('changed-target')).data.job;assert.ok(changedJob);
 await rejectsAtomically(checkpoint(changedJob,'changed-target',[{id:changedJob.id,state:stateFor(changedJob.targets[changedJob.slot],changedJob.algorithm),reference:null,visited:true}]));
 await successful({action:'release',id:changedJob.id,generation:changedJob.generation,worker:'changed-target'});
 board=await get();
 for(const anchors of [[],[{slot:0,shape:'sine'},{slot:0,shape:'square'}],[{slot:32,shape:'square'}]])
  await rejectsAtomically({action:'configure',config:{allowDetune:false,anchors},revision:board.revision});
 assert.deepEqual((await get()).config,updated);

 await successful({action:'running',running:false});
 assert.equal((await claim('paused-again')).data.job,null);
 const backup=await get('?export=1');
 assert.equal(backup.format,'dexfraggler-table');assert.equal(backup.version,4);
 assert.equal(backup.targetVersion,TARGET_VERSION);assert.equal(backup.metricVersion,METRIC_VERSION);assert.equal(backup.model,MODEL);
 assert.deepEqual(backup.config,updated);assert.deepEqual(backup.targets,columnTargets(updated));
 assert.equal(backup.targets.length,32);backup.targets.forEach(validateTarget);
 assert.ok(backup.cells.length>=32);assert.ok(backup.cells.length<=1024);
 assert.ok(backup.cells.every(cell=>cell.state===undefined));
 assert.ok(backup.cells.some(cell=>cell.reference?.notes.length===3));
 console.log('Table API passed: local access boundaries, current-engine handshake, concurrent row leases, atomic 32-cell checkpoints, model/native monotonic saves, visits, pause, stale generations, ideal anchors, version 4 export and removed-action rejection.');
}finally{
 await reference.close();
 await successful({action:'running',running:false});
 const board=await get();
 await successful({action:'configure',config:original.config,revision:board.revision});
}
