import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {model,targets,buildCorpus} from '../models/index.mjs';

function fixture(){
  const a=model.blank(),b=model.clone(a);b.operators[5].fine=1;
  return {format:'dexfraggler-table',version:4,model:model.MODEL,
    targetVersion:targets.TARGET_VERSION,metricVersion:targets.METRIC_VERSION,
    config:targets.DEFAULT_CONFIG,targets:targets.columnTargets(targets.DEFAULT_CONFIG),
    cells:[{id:992,slot:0,algorithm:32,current:true,patch:a,modelScore:.9,
      reference:{patch:b,score:.8,loss:.36,notes:[{note:45,score:.8}]},
      state:{elites:[{patch:a,score:.9,loss:.19},{patch:b,score:.7,loss:.51}]}}]};
}
test('research corpus preserves every source field and distinct silent-operator codes',()=>{
  const source=fixture(),original=model.clone(source),corpus=buildCorpus(source);
  assert.deepEqual(source,original);assert.deepEqual(corpus.sourceTable,original);
  assert.equal(corpus.candidates.length,2);
  assert.equal(corpus.candidates.reduce((n,c)=>n+c.origins.length,0),4);
  for(const candidate of corpus.candidates)assert.deepEqual(model.fromSysex(candidate.sysex),candidate.patch);
  corpus.sourceTable.cells[0].reference.score=0;assert.equal(source.cells[0].reference.score,.8);
  const invalid=model.clone(fixture());invalid.cells[0].state.elites[1].patch.algorithm=31;
  assert.throws(()=>buildCorpus(invalid),/different algorithm/);
});
test('headless CLI scores independently and refuses to overwrite previous results',async t=>{
  const dir=await mkdtemp(path.join(os.tmpdir(),'dexfraggler-models-'));
  t.after(()=>rm(dir,{recursive:true,force:true}));
  const output=path.join(dir,'score.json');
  const run=(...args)=>spawnSync(process.execPath,['scripts/model-lab.mjs',...args],{encoding:'utf8'});
  let result=run('score','--shape','triangle','--out',output);
  assert.equal(result.status,0,result.stderr);
  const score=JSON.parse(await readFile(output,'utf8'));
  assert.equal(score.nativeMeasurement,null);assert.deepEqual(score.proposalModel,model.evaluate(model.blank(),targets.idealTarget('triangle')));
  const before=await readFile(output,'utf8');result=run('score','--out',output);
  assert.notEqual(result.status,0);assert.equal(await readFile(output,'utf8'),before);
  const tableFile=path.join(dir,'table.json'),corpusFile=path.join(dir,'corpus.json');
  await writeFile(tableFile,JSON.stringify(fixture()));result=run('corpus','--table',tableFile,'--out',corpusFile);
  assert.equal(result.status,0,result.stderr);
  assert.deepEqual(JSON.parse(await readFile(corpusFile,'utf8')),buildCorpus(fixture()));
  assert.notEqual(run('score','--shape','saw','--target',tableFile).status,0);
});
test('stale observations retain their original target or explicitly mark it unknown',()=>{
  const table=fixture(),cell=table.cells[0];cell.current=false;
  for(const candidate of buildCorpus(table).candidates)for(const origin of candidate.origins){
    assert.equal(origin.targetKey,null);
    assert.equal(origin.currentTargetKey,targets.targetKey(table.targets[0]));
  }
  cell.state.shape=targets.idealTarget('saw');cell.target_key=targets.targetKey(cell.state.shape);
  for(const candidate of buildCorpus(table).candidates)for(const origin of candidate.origins){
    assert.equal(origin.targetKey,targets.targetKey(targets.idealTarget('saw')));
    assert.notEqual(origin.targetKey,origin.currentTargetKey);
  }
});
