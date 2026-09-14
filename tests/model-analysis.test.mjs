import test from 'node:test';
import assert from 'node:assert/strict';
import {blank,render,targetWave,analyze,prepareModelWave,analyzePreparedModel,analyzeMany} from '../public/core.mjs';
import {columnTargets,DEFAULT_CONFIG} from '../public/targets.mjs';
import {analyzeBaseline} from './fixtures/model-analysis-baseline.mjs';

const targets=columnTargets(DEFAULT_CONFIG);
test('prepared row analysis is bit-for-bit equal to the previous objective for every algorithm',()=>{
  for(let algorithm=1;algorithm<=32;algorithm++){
    const p=blank();p.algorithm=algorithm;p.feedback=algorithm%8;
    p.operators.forEach((op,i)=>{op.level=35+(algorithm*7+i*11)%65;op.coarse=(algorithm+i)%7;op.fine=(i*13)%100;op.detune=i+5;op.mode=Number(algorithm%5===0&&i%2===0)});
    const wave=render(p),before=Array.from(wave),prepared=prepareModelWave(wave),snapshot=structuredClone(prepared);
    const expected=targets.map(target=>analyzeBaseline(wave,target));
    assert.deepEqual(targets.map(target=>analyzePreparedModel(prepared,target)),expected,`algorithm ${algorithm}`);
    assert.deepEqual(analyzeMany(wave,targets),expected,`batched algorithm ${algorithm}`);
    assert.deepEqual(analyze(wave,targets[algorithm%32]),expected[algorithm%32]);
    assert.deepEqual(prepared,snapshot);assert.deepEqual(Array.from(wave),before);
  }
});

test('prepared analysis keeps DC removal, global shift, silence and low-energy boundaries unchanged',()=>{
  const source=targetWave(targets[31]);
  const cases=[new Float64Array(1024),new Float64Array(1024).fill(3),
    Float64Array.from(source,x=>x*1e-12),Float64Array.from(source,x=>x*1e-8),
    Float64Array.from(source,(_,i)=>2+3*source[(i+53)%source.length])];
  for(const wave of cases)assert.deepEqual(analyzeMany(wave,targets),targets.map(target=>analyzeBaseline(wave,target)));
  const prepared=prepareModelWave(source),expected=analyzePreparedModel(prepared,targets[31]);
  source.fill(0);assert.deepEqual(analyzePreparedModel(prepared,targets[31]),expected);
});
