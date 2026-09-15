import fs from 'node:fs/promises';
import path from 'node:path';
import {buildCorpus} from './corpus.mjs';
import {validatePatch,sysex,clone} from '../public/core.mjs';

export const NATIVE_DATASET_VERSION='native-observations-v1';
export const NATIVE_DESCRIPTOR_VERSION='native-harmonics-v1';
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

function keyForPatch(patch){return Array.from(sysex(validatePatch(patch)),value=>value.toString(16).padStart(2,'0')).join('');}
function atomicWrite(filename,value){const temporary=`${filename}.${process.pid}.tmp`;return fs.writeFile(temporary,JSON.stringify(value,null,2)+'\n').then(()=>fs.rename(temporary,filename)).finally(()=>fs.unlink(temporary).catch(()=>{}));}

/** Project one native capture onto phase-bearing harmonic descriptors.
 * The descriptor is derived only from the native samples, not from the
 * mathematical model, and is intentionally normalized for retrieval. */
export function nativeDescriptor(audio,note,maxHarmonics=127){
 if(!Array.isArray(audio)||audio.length<3||!Number.isFinite(note))throw Error('A native observation needs finite audio and a MIDI note.');
 if(!Number.isInteger(maxHarmonics)||maxHarmonics<1||maxHarmonics>4096)throw Error('Choose 1–4,096 descriptor harmonics.');
 const sampleRate=48000,base=440*2**((note-69)/12),bands=Math.min(maxHarmonics,Math.ceil(sampleRate/(2*base))-1),mean=audio.reduce((sum,value)=>sum+value,0)/audio.length,centered=audio.map(value=>value-mean),energy=Math.sqrt(centered.reduce((sum,value)=>sum+value*value,0));
 if(!centered.every(finite)||!finite(energy))throw Error('Native observation audio must be finite.');
 const sin=[],cos=[],magnitude=[];
 for(let k=1;k<=bands;k++){
  let s=0,c=0;for(let i=0;i<centered.length;i++){const theta=2*Math.PI*k*base*i/sampleRate;s+=centered[i]*Math.sin(theta);c+=centered[i]*Math.cos(theta)}
  const normalized=energy>1e-12?2/energy:0;sin.push(s*normalized);cos.push(c*normalized);magnitude.push(Math.hypot(s*normalized,c*normalized));
 }
 return {version:NATIVE_DESCRIPTOR_VERSION,note,sampleRate,bands,mean,energy,sin,cos,magnitude};
}

export function nativeObservation(patch,capture,{includeWaveforms=true,provenance=[]}={}){
 const checked=validatePatch(patch),waveforms=capture?.waveforms;
 if(!capture||capture.sampleRate!==48000||capture.velocity!==100||capture.offsetSamples!==7200||capture.captureSamples!==4096||!Array.isArray(capture.notes)||capture.notes.length!==3||!Array.isArray(waveforms)||waveforms.length!==3)throw Error('Native observation capture does not match the DexFraggler reference contract.');
 const notes=capture.notes.map((note,index)=>({note,descriptor:nativeDescriptor(waveforms[index],note),sampleCount:waveforms[index].length}));
 return {version:NATIVE_DATASET_VERSION,key:keyForPatch(checked),patch:clone(checked),sysex:Array.from(sysex(checked)),engine:'Dexed Mark I / native',metricVersion:'band-limited-match-v1',sampleRate:capture.sampleRate,velocity:capture.velocity,offsetSamples:capture.offsetSamples,captureSamples:capture.captureSamples,binarySha256:capture.binarySha256,sourceManifest:capture.sourceManifest,notes,waveforms:includeWaveforms?waveforms.map(wave=>Array.from(wave)):undefined,provenance:clone(provenance),createdAt:Date.now()};
}

function validateRecord(record){
 if(!record||record.version!==NATIVE_DATASET_VERSION||typeof record.key!=='string'||!record.patch||!Array.isArray(record.notes)||record.notes.length!==3)throw Error('The native dataset contains an invalid observation.');
 const patch=validatePatch(record.patch);if(record.key!==keyForPatch(patch))throw Error('The native dataset patch key does not match its legal SysEx bytes.');
 if(record.notes.some(note=>!Number.isFinite(note.note)||!note.descriptor||note.descriptor.version!==NATIVE_DESCRIPTOR_VERSION||!Array.isArray(note.descriptor.magnitude)))throw Error('The native dataset contains an invalid harmonic descriptor.');
 if(record.waveforms!==undefined&&(!Array.isArray(record.waveforms)||record.waveforms.length!==3||record.waveforms.some(wave=>!Array.isArray(wave)||wave.length!==4096||!wave.every(finite))))throw Error('The native dataset contains an invalid captured waveform.');
 return record;
}

export async function readNativeDataset(filename){
 const text=await fs.readFile(filename,'utf8'),lines=text.split(/\r?\n/).map(line=>line.trim()).filter(Boolean);if(!lines.length)throw Error('The native dataset is empty.');
 const manifest=JSON.parse(lines[0]);if(manifest.format!=='dexfraggler-native-dataset'||manifest.version!==NATIVE_DATASET_VERSION)throw Error('Choose a DexFraggler native-observation dataset.');
 const records=lines.slice(1).map(line=>validateRecord(JSON.parse(line))),keys=new Set();for(const record of records){if(keys.has(record.key))throw Error('The native dataset contains a duplicate exact patch.');keys.add(record.key)}
 return {...manifest,records};
}

/** Build a bounded append-only JSONL dataset and a resumable checkpoint.
 * Existing lines are never rewritten, so an interrupted native run can be
 * resumed without re-rendering completed exact patches. */
export async function buildNativeDataset({table,reference,outputPath,checkpointPath=`${outputPath}.checkpoint.json`,maxCandidates=256,maxBytes=64*1024*1024,includeWaveforms=true,signal,log=()=>{}}={}){
 if(!table||!reference||typeof outputPath!=='string')throw Error('A table, native reference and output path are required.');
 const corpus=buildCorpus(table),candidates=corpus.candidates.slice(0,maxCandidates);
 let existing=[];try{existing=(await readNativeDataset(outputPath)).records}catch(error){if(error.code!=='ENOENT')throw error}
 const complete=new Set(existing.map(record=>record.key));
 if(!existing.length)await fs.writeFile(outputPath,JSON.stringify({format:'dexfraggler-native-dataset',version:NATIVE_DATASET_VERSION,descriptorVersion:NATIVE_DESCRIPTOR_VERSION,metricVersion:'band-limited-match-v1',renderer:'Dexed Mark I / native',createdAt:Date.now()})+'\n');
 let bytes=(await fs.stat(outputPath)).size,rendered=existing.length,stopped=null;
 for(const candidate of candidates){
  if(signal?.aborted){stopped='cancelled';break}if(complete.has(candidate.key))continue;
  const capture=await reference.render(candidate.patch),record=nativeObservation(candidate.patch,capture,{includeWaveforms,provenance:candidate.origins});
  record.binarySha256=reference.binarySha256??capture.binarySha256;record.sourceManifest=reference.sourceManifest??capture.sourceManifest??'native/source-provenance.json';
  const line=JSON.stringify(record)+'\n';if(bytes+Buffer.byteLength(line)>maxBytes){stopped='byte-budget';break}
  await fs.appendFile(outputPath,line);bytes+=Buffer.byteLength(line);complete.add(record.key);rendered++;log({key:record.key,rendered,total:candidates.length});
  await atomicWrite(checkpointPath,{version:NATIVE_DATASET_VERSION,outputPath:path.resolve(outputPath),next:rendered,rendered,bytes,stopped:null,updatedAt:Date.now()});
  await sleep(0);
 }
 if(!stopped&&rendered<candidates.length)stopped='complete';
 await atomicWrite(checkpointPath,{version:NATIVE_DATASET_VERSION,outputPath:path.resolve(outputPath),next:rendered,rendered,bytes,stopped,updatedAt:Date.now()});
 return {outputPath:path.resolve(outputPath),checkpointPath:path.resolve(checkpointPath),rendered,available:candidates.length,bytes,stopped};
}

export {keyForPatch};
