import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {MODEL,blank,clone} from '../public/core.mjs';
import {DEFAULT_CONFIG,METRIC_VERSION,TARGET_VERSION,columnTargets} from '../public/targets.mjs';
import {buildNativeDataset,nativeDescriptor,readNativeDataset} from '../models/native-dataset.mjs';
import {addRetrievalSeeds,buildRetrievalIndex,retrieveCandidates} from '../models/retrieval.mjs';

const patch=(algorithm,feedback)=>{const value=blank();value.algorithm=algorithm;value.feedback=feedback;value.operators[0].level=80+feedback;return value};
const table=()=>({format:'dexfraggler-table',version:4,model:MODEL,targetVersion:TARGET_VERSION,metricVersion:METRIC_VERSION,config:clone(DEFAULT_CONFIG),targets:columnTargets(DEFAULT_CONFIG),cells:[0,1,2].map((id)=>({id,algorithm:1,slot:id,patch:patch(1,id)}))});
function capture(){return {sampleRate:48000,velocity:100,offsetSamples:7200,captureSamples:4096,notes:[45,57,69],waveforms:[45,57,69].map(note=>Array.from({length:4096},(_,i)=>Math.sin(2*Math.PI*(110*2**((note-69)/12))*i/48000)))}};

test('native descriptors retain phase-bearing harmonic quadratures',()=>{
 const descriptor=nativeDescriptor(Array.from({length:4096},(_,i)=>Math.cos(2*Math.PI*220*i/48000)),57);
 assert.equal(descriptor.version,'native-harmonics-v1');assert.ok(descriptor.magnitude[0]>.01);assert.ok(Math.abs(descriptor.cos[0])>Math.abs(descriptor.sin[0]));
});

test('native dataset append and checkpoint resume without rerendering completed exact patches',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-native-dataset-')),output=path.join(root,'dataset.jsonl');let calls=0;
 const reference={binarySha256:'test-binary',async render(p){calls++;return {...capture(),binarySha256:'test-binary',sourceManifest:'test-manifest',patch:p}}};
 const first=await buildNativeDataset({table:table(),reference,outputPath:output,maxCandidates:2,includeWaveforms:false});assert.equal(first.rendered,2);assert.equal(calls,2);
 const second=await buildNativeDataset({table:table(),reference,outputPath:output,maxCandidates:3,includeWaveforms:false});assert.equal(second.rendered,3);assert.equal(calls,3);
 const dataset=await readNativeDataset(output);assert.equal(dataset.records.length,3);assert.ok(dataset.records.every(record=>record.binarySha256==='test-binary'||record.binarySha256===undefined));
 const index=buildRetrievalIndex(dataset),results=retrieveCandidates(index,columnTargets(DEFAULT_CONFIG)[0],1,{limit:2});assert.equal(results.length,2);assert.ok(results.every(result=>result.patch.algorithm===1));
 const seeded=addRetrievalSeeds(table(),index,{perAlgorithm:2});assert.ok(seeded.retrieval.added.length>0);assert.ok(seeded.cells.length>table().cells.length);
});
