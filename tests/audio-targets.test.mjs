import test from 'node:test';
import assert from 'node:assert/strict';
import {AUDIO_TARGET_VERSION,createPeriodicTarget,prepareAudio,previewFrames} from '../public/audio-targets.mjs';
import {coefficients,columnTargets,cycle,targetKey,validateConfig,validateTarget} from '../public/targets.mjs';
import {measuredScore} from '../runner/measurement.mjs';
import {MODEL} from '../public/core.mjs';
import {METRIC_VERSION} from '../runner/measurement.mjs';
import {tableSeeds} from '../public/table-import.mjs';

function wav16(samples,sampleRate=48000){
 const data=samples.length*2,bytes=new Uint8Array(44+data),view=new DataView(bytes.buffer);
 const text=(offset,value)=>value.split('').forEach((char,i)=>bytes[offset+i]=char.charCodeAt(0));
 text(0,'RIFF');view.setUint32(4,36+data,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,sampleRate,true);view.setUint32(28,sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,data,true);samples.forEach((sample,i)=>view.setInt16(44+i*2,Math.round(Math.max(-1,Math.min(1,sample))*32767),true));return bytes;
}

function cycleSamples(size,frames=1){return Array.from({length:size*frames},(_,i)=>Math.sin(2*Math.PI*(i%size)/size)+.1)}

test('WAV decoding and single-cycle preparation preserve a versioned phased target',()=>{
 const prepared=prepareAudio(wav16(cycleSamples(64)),{mode:'single-cycle',outputSize:64,name:'sine cycle'});
 assert.equal(prepared.frames.length,1);assert.equal(prepared.targets.length,32);assert.equal(prepared.targets[0].kind,AUDIO_TARGET_VERSION);assert.equal(validateTarget(prepared.targets[0]).id,prepared.targets[0].id);assert.equal(targetKey(prepared.targets[0]),targetKey(prepared.targets[1]));assert.ok(prepared.warnings.some(warning=>warning.includes('DC offset')));
 const config=validateConfig({allowDetune:false,anchors:[],targetSet:prepared.targets,source:{mode:'single-cycle'}});assert.equal(columnTargets(config).length,32);const harmonic=coefficients(prepared.targets[0],8);assert.ok(Math.hypot(harmonic.sin[0],harmonic.cos[0])>.9);assert.equal(cycle(prepared.targets[0],64).length,64);assert.equal(previewFrames(prepared.frames,16)[0].length,16);
 const importedTable={format:'dexfraggler-table',version:4,model:MODEL,targetVersion:'ideal-waveform-v1',metricVersion:METRIC_VERSION,config,targets:prepared.targets,cells:[]};assert.deepEqual(tableSeeds(importedTable).config,config);
});

test('wavetable imports require an explicit frame boundary when metadata is insufficient',()=>{
 const bytes=wav16(cycleSamples(16,3));assert.throws(()=>prepareAudio(bytes,{mode:'wavetable',outputSize:32}),/frame size or frame count/);
 const prepared=prepareAudio(bytes,{mode:'wavetable',frameSize:16,outputSize:32});assert.equal(prepared.frames.length,3);assert.equal(prepared.targets.length,32);assert.equal(prepared.targets[0].source.frameIndex,0);assert.equal(prepared.targets.at(-1).source.frameIndex,31);assert.ok(prepared.targets.some(target=>target.source.interpolated));
});

test('large wavetable files avoid argument-spread overflow during WAV statistics',()=>{
 const bytes=wav16(Array.from({length:100000},(_,i)=>Math.sin(2*Math.PI*i/256)));
 const parsed=prepareAudio(bytes,{mode:'wavetable',frameSize:1000,frameCount:100,outputSize:64});
 assert.equal(parsed.frames.length,100);assert.equal(parsed.targets.length,32);assert.ok(parsed.warnings.length>=0);
});

test('pitched-sample preparation extracts repeated pitch-aware cycles instead of chopping arbitrary samples',()=>{
 const sampleRate=48000,fundamental=220,samples=Array.from({length:sampleRate},(_,i)=>.8*Math.sin(2*Math.PI*fundamental*i/sampleRate));
 const prepared=prepareAudio(wav16(samples,sampleRate),{mode:'pitched-sample',fundamentalHz:fundamental,frameSize:128,cycles:8,outputSize:128});
 assert.ok(prepared.details.start>=0);assert.equal(prepared.details.cycles,8);assert.ok(prepared.details.periodicity>.95);assert.equal(prepared.targets.length,32);assert.ok(prepared.targets.every(target=>target.harmonics.sin.length>50));
});

test('phase-bearing imported targets survive native objective preparation',()=>{
 const n=1024,fundamental=440,target=createPeriodicTarget(Array.from({length:n},(_,i)=>Math.cos(2*Math.PI*i/n)),{sampleRate:48000,fundamentalHz:fundamental,source:{name:'cosine'}});
 const bands=109,audio=Array.from({length:4096},(_,i)=>Math.cos(2*Math.PI*fundamental*i/48000));
 const result=measuredScore(audio,target,69,{preview:false});
 assert.ok(result.score>.999999,`phase-aware score was ${result.score}`);assert.ok(Math.abs(result.phase)<1e-6||Math.abs(result.phase-2*Math.PI)<1e-6);
 assert.ok(coefficients(target,bands).cos[0]>.99);assert.ok(Math.abs(coefficients(target,bands).sin[0])<1e-10);
});
