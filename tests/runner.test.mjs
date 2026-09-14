import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import * as core from '../public/core.mjs';
import {columnTargets,DEFAULT_CONFIG,targetKey,METRIC_VERSION} from '../public/targets.mjs';
import {restoreState,runTableRunner} from '../runner/table-runner.mjs';

const targets=columnTargets(DEFAULT_CONFIG),keys=targets.map(targetKey);
const p=core.blank();p.algorithm=1;
function nativeResult(patch,loss=.1){return {patch:core.clone(patch),engine:'Dexed Mark I / native',metricVersion:METRIC_VERSION,loss,score:Math.sqrt(1-loss),notes:[45,57,69].map(note=>({note,error:Math.sqrt(loss),score:Math.sqrt(1-loss),wave:[0],target:[0]}))}}

test('restart reconstructs mechanics while preserving the saved champion and count',()=>{
  const saved=core.initialState(targets[0],[],127,1);saved.evaluations=20491;saved.elites[0].loss=.00001;saved.rng=123;saved.seedCursor=900;
  const cell={current:true,target_key:keys[0],evaluations:20491,state:saved,patch:p,reference:nativeResult(p)};
  const result=restoreState(core,targets[0],keys[0],DEFAULT_CONFIG,1,cell);
  assert.equal(result.evaluations,20491);assert.equal(result.elites[0].loss,.00001);
  assert.notEqual(result.rng,123);assert.notEqual(result.seedCursor,900);
  const changed=restoreState(core,targets[1],keys[1],DEFAULT_CONFIG,1,{...cell,current:false});
  assert.ok(changed.elites[0].loss>.00001);assert.ok(changed.evaluations<20491);
});

test('a cached optimizer retains its exploration cursor for an unchanged target',()=>{
 const cached=core.initialState(targets[0],[],127,1);cached.seedCursor=811;cached.rng=123;
 const restored=restoreState(core,targets[0],keys[0],DEFAULT_CONFIG,1,null,cached);
 assert.equal(restored.seedCursor,811);assert.equal(restored.rng,123);
});

test('restart retains all useful saved elites while rebuilding optimizer mechanics',()=>{
 const saved=core.initialState(targets[0],[],127,1);
 saved.evaluations=25000;saved.rng=123;saved.seedCursor=900;
 saved.elites=Array.from({length:16},(_,i)=>{
  const patch=core.clone(p);patch.operators[5].fine=i+1;
  return {patch,loss:(i+1)*1e-8,score:1-(i+1)*1e-8,error:Math.sqrt((i+1)*1e-8),spectralError:0,shift:0,scale:1};
 });
 const result=restoreState(core,targets[0],keys[0],DEFAULT_CONFIG,1,{current:true,target_key:keys[0],state:saved,evaluations:25000});
 assert.deepEqual(result.elites,saved.elites);assert.equal(result.evaluations,25000);
 assert.notEqual(result.rng,123);assert.notEqual(result.seedCursor,900);
 result.elites[0].patch.feedback=7;assert.equal(saved.elites[0].patch.feedback,0);
});

test('saved candidates for a different target are rescored and a cached different row is rebuilt',()=>{
 const saved=core.initialState(targets[31],[],127,1),patch=core.clone(p);patch.feedback=2;patch.operators[5].level=72;
 saved.elites=[{...core.evaluate(patch,targets[31]),loss:0,score:1}];
 const result=restoreState(core,targets[0],keys[0],DEFAULT_CONFIG,1,{current:true,target_key:keys[0],state:saved});
 const retained=result.elites.find(e=>JSON.stringify(e.patch)===JSON.stringify(patch));
 assert.ok(retained);assert.deepEqual(retained,core.evaluate(patch,targets[0]));assert.ok(retained.loss>0);
 const other=core.initialState(targets[0],[],127,2);other.rng=123;
 const rebuilt=restoreState(core,targets[0],keys[0],DEFAULT_CONFIG,1,null,other);
 assert.equal(rebuilt.algorithm,1);assert.notEqual(rebuilt.rng,123);assert.ok(rebuilt.elites.every(e=>e.patch.algorithm===1));
});

test('a stalled lease renewal does not block tray pause/status polling',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-renew-test-'));
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
  const abort=new AbortController();let first=true,renewed=false,closed=false;
  let resolveRenewal;const renewalStarted=new Promise(resolve=>{resolveRenewal=resolve});
  const renderer={healthy:true,child:{pid:null},async close(){await new Promise(r=>setTimeout(r,20));closed=true},async scoreMany(patch,subset){if(first){first=false;await new Promise(r=>setTimeout(r,1800))}return subset.map(()=>nativeResult(patch))}};
  const running=runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},createReference:()=>renderer,renewIntervalMs:50,signal:abort.signal,log(){},errorLog(){},async request(body,signal){
    if(body.action==='claim_row')return {running:true,job:{id:0,algorithm:1,generation:1,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells:[]}};
    if(body.action==='renew'){
      renewed=true;resolveRenewal();
      await new Promise(resolve=>{const timer=setTimeout(resolve,2000);signal?.addEventListener('abort',()=>{clearTimeout(timer);resolve()},{once:true})});
    }
    if(body.action==='checkpoint_row')abort.abort();
    return {ok:true,running:true};
  }});
  await renewalStarted;
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:true,priority:'Normal'}));
  await new Promise(r=>setTimeout(r,900));
  const interim=JSON.parse(await fs.readFile(path.join(temp,'runner-status.json'),'utf8'));
  assert.equal(renewed,true);assert.equal(interim.localPaused,true);assert.equal(interim.running,false);
  await running;assert.equal(closed,true);
});

test('one native capture propagates a row, visits only the focus, and local pause saves safely',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-row-test-'));
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
  const abort=new AbortController(),requests=[],checkpoints=[];let captures=0;
  const renderer={healthy:true,child:{pid:null},close(){},async scoreMany(patch,subset){if(captures===0){await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:true,priority:'Normal'}));await new Promise(r=>setTimeout(r,320))}captures++;return subset.map(()=>nativeResult(patch))}};
  await runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},createReference:()=>renderer,signal:abort.signal,log(){},errorLog(){},async request(body){requests.push(body);if(body.action==='claim_row')return {running:true,job:{id:15,algorithm:1,generation:1,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells:[]}};if(body.action==='checkpoint_row'){checkpoints.push(body);abort.abort()}return {ok:true}}});
  assert.equal(captures,8);assert.equal(checkpoints.length,1);assert.equal(checkpoints[0].cells.length,32);
  assert.deepEqual(checkpoints[0].cells.filter(c=>c.visited).map(c=>c.id),[15]);
  assert.equal(requests.some(r=>r.action==='running'||r.action==='failed'),false);
  const status=JSON.parse(await fs.readFile(path.join(temp,'runner-status.json'),'utf8'));
  assert.equal(status.localPaused,true);assert.equal(status.phase,'Stopped');assert.equal(status.running,false);
  assert.ok(status.evaluations>=32);
});

test('startup respects a saved local pause and never requests table start',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-pause-test-'));
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:true,priority:'Normal'}));
  const abort=new AbortController(),actions=[];
  await runTableRunner({root:temp,config:{runtimeDir:temp},core,native:{},createReference:()=>({healthy:true,child:{pid:null},close(){}}),signal:abort.signal,log(){},errorLog(){},async request(body){actions.push(body.action);abort.abort();return {ok:true}}});
  assert.deepEqual(actions,['heartbeat']);
});

test('uploaded seeds render first and only fully measured seeds are acknowledged on pause',async()=>{
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-seeds-'));
 await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
 const abort=new AbortController(),seed=core.blank(),second=core.blank();seed.algorithm=second.algorithm=1;seed.feedback=7;second.feedback=6;
 let renders=0,saved;
 await runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},signal:abort.signal,log(){},errorLog(){},createReference:()=>({healthy:true,child:{pid:null},close(){},async scoreMany(patch,subset){
  assert.deepEqual(patch,seed);
  if(renders++===0){await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:true,priority:'Normal'}));await new Promise(r=>setTimeout(r,320))}
  return subset.map(()=>nativeResult(patch));
 }}),async request(body){
  if(body.action==='claim_row'){assert.equal(body.protocol,'named-scans-v1');return {job:{scanId:'seeded',id:0,algorithm:1,generation:5,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells:[],seeds:[{key:'a'.repeat(64),patch:seed},{key:'b'.repeat(64),patch:second}]}}}
  if(body.action==='checkpoint_row'){saved=body;abort.abort()}
  return {ok:true};
 }});
 assert.deepEqual(saved.consumedSeeds,['a'.repeat(64)]);assert.equal(saved.cells.length,32);assert.equal(renders,8);
});

test('compact row claims reuse stored measurements without retransmitting preview arrays',async()=>{
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-compact-test-'));
 await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
 const abort=new AbortController();let saved=[],checkpoints=0;
 await runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},signal:abort.signal,log(){},errorLog(){},createReference:()=>({healthy:true,child:{pid:null},close(){},async scoreMany(patch,subset){return subset.map(()=>nativeResult(patch))}}),async request(body){
  if(body.action==='claim_row')return {running:true,job:{id:0,algorithm:1,generation:1,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells:core.clone(saved).map(c=>({...c,reference:{...c.reference,notes:c.reference.notes.map(({wave,target,...note})=>note)}}))}};
  if(body.action==='checkpoint_row'){
   checkpoints++;
   if(checkpoints===1)saved=body.cells.map(c=>({...core.clone(c),current:true,target_key:keys[c.id%32],evaluations:c.state.evaluations}));
   else{assert.ok(body.cells.every(c=>c.reference===null));abort.abort()}
  }
  return {ok:true};
 }});
 assert.equal(checkpoints,2);
});

test('a superseded checkpoint is discarded without marking the cell failed',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-supersede-test-'));
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
  const abort=new AbortController(),actions=[];
  await runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},createReference:()=>({healthy:true,child:{pid:null},close(){},async scoreMany(patch,subset){return subset.map(()=>nativeResult(patch))}}),signal:abort.signal,log(){},errorLog(){},async request(body){actions.push(body.action);if(body.action==='claim_row')return {running:true,job:{id:0,algorithm:1,generation:1,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells:[]}};if(body.action==='checkpoint_row'){abort.abort();throw Object.assign(Error('Superseded'),{status:409})}return {ok:true}}});
  assert.ok(actions.includes('checkpoint_row'));assert.equal(actions.includes('failed'),false);
});
