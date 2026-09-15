import test from 'node:test';
import assert from 'node:assert/strict';
import {DEFAULT_CONFIG,columnTargets,targetKey,scheduleCell} from '../public/targets.mjs';
import {blank} from '../public/core.mjs';
import {bankSysex,fromBank} from '../public/bank.mjs';
import {tableMetrics,relativeRanks,tablePalette} from '../public/table-metrics.mjs';
test('scheduler covers all 1024 cells before repeating and prioritizes stale targets',()=>{const config=DEFAULT_CONFIG,keys=columnTargets(config).map(targetKey),cells=[],seen=new Set();for(let i=0;i<1024;i++){const id=scheduleCell(cells,config,keys);assert.ok(!seen.has(id));seen.add(id);cells.push({id,visits:1,target_key:keys[id%32]})}assert.equal(seen.size,1024);assert.equal(scheduleCell(cells,config,keys),0);cells[500].target_key='obsolete';assert.equal(scheduleCell(cells,config,keys),cells[500].id)});
test('scheduler gives weak cells bounded recovery turns without starving coverage',()=>{const config=DEFAULT_CONFIG,keys=columnTargets(config).map(targetKey),cells=Array.from({length:1024},(_,id)=>({id,visits:0,target_key:keys[id%32]}));for(const id of [500,501,502])cells[id].visits=1;cells[501].native_loss=.2;cells[502].native_loss=.08;assert.equal(scheduleCell(cells,config,keys),501);cells[501].visits=2;assert.equal(scheduleCell(cells,config,keys),0)});
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

test('new scores repaint existing cells whose own score has not changed',()=>{
 const cells=[.2,.5,.8].map((score,id)=>({id,current:true,native_score:String(score)}));
 const before=tablePalette(cells),after=tablePalette([...cells,...[.6,.7,.9].map((score,i)=>({id:i+3,current:true,native_score:String(score)}))]);
 assert.equal(before.get(1).score,after.get(1).score);
 assert.notEqual(before.get(1).color,after.get(1).color);
 assert.equal(before.get(1).position,2);assert.equal(after.get(1).position,5);
 assert.notEqual(before.get(2).color,after.get(2).color);
 assert.equal(tablePalette(cells,'native','absolute').get(1).color,tablePalette([...cells,{id:3,current:true,native_score:'.9'}],'native','absolute').get(1).color);
});

test('improving another cell changes ranks and colors across unchanged rows',()=>{
 const cells=[.2,.4,.6,.8].map((score,i)=>({id:i*32,current:true,native_score:String(score),model_score:String(1-score)}));
 const before=tablePalette(cells),after=tablePalette(cells.map(c=>c.id===0?{...c,native_score:'.9'}:c));
 for(const id of [32,64,96]){assert.equal(before.get(id).score,after.get(id).score);assert.notEqual(before.get(id).color,after.get(id).color)}
 const model=tablePalette(cells,'model');assert.equal(model.get(0).position,1);assert.equal(before.get(0).position,4);
 const current=tablePalette([...cells,{id:1,current:false,native_score:'1'},{id:2,current:true,native_score:null}]);assert.equal(current.size,4);
});
