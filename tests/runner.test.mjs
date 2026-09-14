import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import * as core from '../public/core.mjs';
import {columnTargets,DEFAULT_CONFIG} from '../public/targets.mjs';
import {restoreState,runTableRunner} from '../runner/table-runner.mjs';

const targets=columnTargets(DEFAULT_CONFIG),keys=targets.map(JSON.stringify);
const p=core.blank();p.algorithm=1;
function nativeResult(patch,loss=.1){return {patch:core.clone(patch),engine:'Dexed Mark I / native',loss,score:Math.sqrt(1-loss),notes:[45,57,69].map(note=>({note,error:Math.sqrt(loss),score:Math.sqrt(1-loss),wave:[0],target:[0]}))}}

test('restart reconstructs mechanics while preserving the saved champion and count',()=>{
  const saved=core.initialState(targets[0],[{patch:p}],32,1);saved.evaluations=20491;saved.elites[0].loss=.00001;saved.rng=123;saved.seedCursor=900;
  const cell={current:true,target_key:keys[0],evaluations:20491,state:saved,patch:p,reference:nativeResult(p)};
  const result=restoreState(core,targets[0],keys[0],DEFAULT_CONFIG,1,cell);
  assert.equal(result.evaluations,20491);assert.equal(result.elites[0].loss,.00001);
  assert.notEqual(result.rng,123);assert.equal(result.seedCursor,0);
  const changed=restoreState(core,targets[1],keys[1],DEFAULT_CONFIG,1,{...cell,current:false});
  assert.ok(changed.elites[0].loss>.00001);assert.ok(changed.evaluations<20491);
});

test('a hot import is evaluated into an existing cached optimizer',()=>{
  const cached=core.initialState(targets[0],[{patch:p}],32,1),imported=core.clone(p);imported.feedback=7;imported.operators[5].level=91;imported.operators[5].fine=73;
  const evaluated=[],spy={...core,evaluate(patch,...args){evaluated.push(JSON.stringify(patch));return core.evaluate(patch,...args)}};
  restoreState(spy,targets[0],keys[0],DEFAULT_CONFIG,1,{current:true,patch:p,seeds:[imported],evaluations:cached.evaluations,state:cached},cached);
  assert.ok(evaluated.includes(JSON.stringify(imported)));
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

test('hot imports are measured first and only consumed native seeds are acknowledged',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-import-test-'));
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
  const abort=new AbortController(),importedA=core.clone(p),importedB=core.clone(p);
  importedA.feedback=7;importedA.operators[5].fine=79;importedA.operators[5].level=98;
  importedB.feedback=6;importedB.operators[4].fine=83;importedB.operators[4].level=96;
  let saved=[],claims=0,secondCheckpoint=null,paused=false,firstImportedMeasurement=null;
  const renderer={healthy:true,child:{pid:null},close(){},async scoreMany(patch,subset){
    if(claims===2&&!paused){firstImportedMeasurement=core.clone(patch);paused=true;await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:true,priority:'Normal'}));await new Promise(r=>setTimeout(r,320))}
    return subset.map(()=>nativeResult(patch));
  }};
  await runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},createReference:()=>renderer,signal:abort.signal,log(){},errorLog(){},async request(body){
    if(body.action==='claim_row'){
      claims++;const cells=core.clone(saved);if(claims===2)cells.find(c=>c.id===0).seeds=[importedA,importedB];
      return {running:true,job:{id:0,algorithm:1,generation:1,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells}};
    }
    if(body.action==='checkpoint_row'){
      if(claims===1)saved=body.cells.map(c=>({...core.clone(c),current:true,target_key:keys[c.id%32],evaluations:c.state.evaluations,seeds:[]}));
      else{secondCheckpoint=body;abort.abort()}
    }
    return {ok:true};
  }});
  assert.deepEqual(firstImportedMeasurement,importedA);
  assert.deepEqual(secondCheckpoint.cells.find(c=>c.id===0).consumedSeeds,[importedA]);
  assert.equal(secondCheckpoint.cells.flatMap(c=>c.consumedSeeds).some(q=>JSON.stringify(q)===JSON.stringify(importedB)),false);
});

test('one native capture propagates a row, visits only the focus, and local pause saves safely',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-row-test-'));
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
  const abort=new AbortController(),requests=[],checkpoints=[];let captures=0;
  const renderer={healthy:true,child:{pid:null},close(){},async scoreMany(patch,subset){if(captures===0){await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:true,priority:'Normal'}));await new Promise(r=>setTimeout(r,320))}captures++;return subset.map(()=>nativeResult(patch))}};
  await runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},createReference:()=>renderer,signal:abort.signal,log(){},errorLog(){},async request(body){requests.push(body);if(body.action==='claim_row')return {running:true,job:{id:15,algorithm:1,generation:1,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells:[]}};if(body.action==='checkpoint_row'){checkpoints.push(body);abort.abort()}return {ok:true}}});
  assert.equal(captures,4);assert.equal(checkpoints.length,1);assert.equal(checkpoints[0].cells.length,32);
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

test('a superseded checkpoint is discarded without marking the cell failed',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-supersede-test-'));
  await fs.writeFile(path.join(temp,'runner-control.json'),JSON.stringify({paused:false,priority:'Normal'}));
  const abort=new AbortController(),actions=[];
  await runTableRunner({root:temp,config:{runtimeDir:temp,rowBudgetMs:500},core,native:{nativeProposal:q=>core.clone(q)},createReference:()=>({healthy:true,child:{pid:null},close(){},async scoreMany(patch,subset){return subset.map(()=>nativeResult(patch))}}),signal:abort.signal,log(){},errorLog(){},async request(body){actions.push(body.action);if(body.action==='claim_row')return {running:true,job:{id:0,algorithm:1,generation:1,config:DEFAULT_CONFIG,targets,targetKeys:keys,cells:[]}};if(body.action==='checkpoint_row'){abort.abort();throw Object.assign(Error('Superseded'),{status:409})}return {ok:true}}});
  assert.ok(actions.includes('checkpoint_row'));assert.equal(actions.includes('failed'),false);
});
