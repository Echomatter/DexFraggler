// Fast local smoke test: import one WAV, render a few bounded DX7 searches,
// and optionally verify the same patches with the native Dexed reference.
// It never creates or changes a named scan.
import fs from 'node:fs/promises';
import path from 'node:path';
import * as core from '../public/core.mjs';
import {parseWav,prepareAudio} from '../public/audio-targets.mjs';
import {measuredScore} from '../runner/measurement.mjs';
import {Reference} from '../runner/reference.mjs';

const args=process.argv.slice(2);
function option(name,fallback=null){const index=args.indexOf(name);return index<0?fallback:args[index+1]??fallback;}
function required(name){const value=option(name);if(!value)throw Error(`Missing ${name}.`);return value;}
function integerOption(name,fallback,min,max){const value=Number(option(name,String(fallback)));if(!Number.isInteger(value)||value<min||value>max)throw Error(`${name} must be an integer from ${min} through ${max}.`);return value;}
function parseSlots(value){const slots=String(value).split(',').map(item=>Number(item.trim()));if(!slots.length||slots.some(slot=>!Number.isInteger(slot)||slot<0||slot>31))throw Error('--slots must contain comma-separated columns from 0 through 31.');return [...new Set(slots)];}

const input=path.resolve(required('--input')),mode=option('--mode','auto'),slots=parseSlots(option('--slots','0,15,31')),algorithm=integerOption('--algorithm',1,1,32),modelMs=integerOption('--model-ms',100,10,1000),includeNative=!args.includes('--no-native');
const wav=parseWav(await fs.readFile(input)),prepareOptions={mode,outputSize:1024,name:path.basename(input)};
if(option('--frame-size')!==null)prepareOptions.frameSize=integerOption('--frame-size',0,2,65536);
if(option('--frame-count')!==null)prepareOptions.frameCount=integerOption('--frame-count',0,1,65536);
if(option('--fundamental-hz')!==null)prepareOptions.fundamentalHz=Number(option('--fundamental-hz'));if(prepareOptions.fundamentalHz!==undefined&&(!Number.isFinite(prepareOptions.fundamentalHz)||prepareOptions.fundamentalHz<=0))throw Error('--fundamental-hz must be positive.');
const prepared=prepareAudio(wav,prepareOptions),reference=includeNative?new Reference():null,rows=[];
try{
 for(const slot of slots){
  let state=core.initialState(prepared.targets[slot],[],127,algorithm);state=core.runBatch(state,modelMs);const best=state.elites[0],model=core.analyze(core.render(best.patch),prepared.targets[slot],127),row={slot,source:prepared.targets[slot].source,modelEvaluations:state.evaluations,patch:best.patch,modelScore:model.score,modelLoss:model.loss};
  if(reference){const native=measuredScore((await reference.render(best.patch)).waveforms[1],prepared.targets[slot],57,{preview:false});row.nativeScore=native.score;row.nativeLoss=native.loss;row.scoreDelta=Math.abs(model.score-native.score);row.nativeMetric=native.metricVersion;}
  rows.push(row);
 }
}finally{await reference?.close()}
const report={format:'dexfraggler-sample-dx7-smoke-v1',input,mode:prepared.mode,wav:{sampleRate:wav.sampleRate,channels:wav.channels,samples:wav.samples.length,sourceHash:wav.sourceHash,metadata:wav.metadata},prepared:{frames:prepared.frames.length,targets:prepared.targets.length,interpolatedTargets:prepared.targets.filter(target=>target.source.interpolated===true).length,warnings:prepared.warnings,details:prepared.details},algorithm,modelMs,nativeVerified:includeNative,rows};
const output=option('--output');if(output)await fs.writeFile(path.resolve(output),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
