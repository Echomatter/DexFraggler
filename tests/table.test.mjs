import test from 'node:test';
import assert from 'node:assert/strict';
import {DEFAULT_CONFIG,columnTargets,targetKey,scheduleCell} from '../public/targets.mjs';
import {blank} from '../public/core.mjs';
import {bankSysex,fromBank} from '../public/bank.mjs';
import {tableMetrics,relativeRanks} from '../public/table-metrics.mjs';
test('scheduler covers all 1024 cells before repeating and prioritizes stale targets',()=>{const config=DEFAULT_CONFIG,keys=columnTargets(config).map(targetKey),cells=[],seen=new Set();for(let i=0;i<1024;i++){const id=scheduleCell(cells,config,keys);assert.ok(!seen.has(id));seen.add(id);cells.push({id,visits:1,target_key:keys[id%32]})}assert.equal(seen.size,1024);assert.equal(scheduleCell(cells,config,keys),0);cells[500].target_key='obsolete';assert.equal(scheduleCell(cells,config,keys),cells[500].id)});
test('32 voice banks round trip all algorithms and preserve legal codes',()=>{const patches=Array.from({length:32},(_,i)=>{const p=blank();p.algorithm=i+1;p.feedback=i%8;p.operators.forEach((o,j)=>{o.coarse=(i+j)%32;o.fine=(i*3+j)%100;o.level=(i+j*7)%100;o.detune=(i+j)%15;o.mode=j%2});return p});const b=bankSysex(patches,[],2);assert.equal(b.length,4104);assert.equal(b[2],1);assert.deepEqual(fromBank(b),patches);assert.throws(()=>bankSysex(patches.slice(0,31)));const bad=b.slice();bad[20]^=1;assert.throws(()=>fromBank(bad))});

test('progress is the exact full-table average with unmeasured cells contributing zero',()=>{
 const cells=[{id:0,current:true,native_score:'0.9985'},{id:32,current:true,native_score:'0.9'},{id:1,current:false,native_score:'1'},{id:2,current:true,native_score:null}];
 const stats=tableMetrics(cells);assert.equal(stats.tableMatch,(.9985+.9)/1024);assert.equal(stats.measured,2);assert.equal(stats.columns[0],(.9985+.9)/32);assert.equal(stats.columns[1],0);
 const full=tableMetrics(Array.from({length:1024},(_,id)=>({id,current:true,native_score:'1'})));assert.equal(full.tableMatch,1);assert.equal(full.measured,1024);
 // Even a perfect table stays eligible; the scheduler never terminates on scores.
 assert.equal(scheduleCell(Array.from({length:1024},(_,id)=>({id,visits:100,target_key:columnTargets(DEFAULT_CONFIG).map(targetKey)[id%32],native_score:1})),DEFAULT_CONFIG,columnTargets(DEFAULT_CONFIG).map(targetKey)),0);
});
test('rank colors follow relative order rather than absolute score and ties share ranks',()=>{
 const a=relativeRanks([.9,.91,.91,.999]),b=relativeRanks([.99999,.999991,.999991,.999999]);
 assert.deepEqual([...a.values()],[0,.5,1]);assert.deepEqual([...a.values()],[...b.values()]);assert.equal(relativeRanks([1,1,1]).get(1),.5);
 assert.equal(relativeRanks([.1,.1,.1,.1,.2,.3]).get(.3),1);assert.equal(relativeRanks([.1,.1,.1,.1,.2,.3]).get(.1),0);
});
