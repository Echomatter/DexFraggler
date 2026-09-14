import test from 'node:test';
import assert from 'node:assert/strict';
import {MODEL,blank} from '../public/core.mjs';
import {DEFAULT_CONFIG,columnTargets,TARGET_VERSION,METRIC_VERSION} from '../public/targets.mjs';
import {tableSeeds} from '../public/table-import.mjs';
const patch=()=>({...blank(),algorithm:1});
const fixture=()=>({format:'dexfraggler-table',version:4,model:MODEL,targetVersion:TARGET_VERSION,metricVersion:METRIC_VERSION,config:structuredClone(DEFAULT_CONFIG),targets:columnTargets(DEFAULT_CONFIG),cells:[{id:0,algorithm:1,slot:0,patch:patch()}]});
test('imports only legal patches and anchors, ignoring scores and optimizer history',()=>{
 const table=fixture();table.cells[0].reference={patch:patch(),score:1,loss:0};table.cells[0].state={elites:[{patch:'untrusted'}]};
 table.cells.push({...table.cells[0],id:1,slot:1});
 assert.deepEqual(tableSeeds(table),{config:DEFAULT_CONFIG,seeds:[{id:0,patch:patch()}]});
 const different=patch();different.feedback=7;table.cells[0].reference.patch=different;
 assert.equal(tableSeeds(table).seeds.length,2);
});
test('malformed, mismatched and obsolete tables cannot seed a scan',()=>{
 for(const mutate of [t=>t.version=3,t=>t.model='other',t=>t.metricVersion='other',t=>t.targets[0]=t.targets[31],t=>t.cells.push(t.cells[0]),t=>t.cells[0].algorithm=2,t=>t.cells[0].patch.algorithm=2,t=>t.cells[0].patch.feedback=8]){
  const table=fixture();mutate(table);assert.throws(()=>tableSeeds(table));
 }
 const empty=fixture();empty.cells=[];assert.equal(tableSeeds(empty).seeds.length,0);
});
