// Deterministic CPU benchmark for the local sample-to-DX7 path.
// This times preparation, proposal paths, and native scoring separately so
// progress decisions can be compared without hiding work in one aggregate.
import fs from 'node:fs/promises';
import {performance} from 'node:perf_hooks';
import {blank} from '../public/core.mjs';
import {prepareAudio} from '../public/audio-targets.mjs';
import {measuredScore} from '../runner/measurement.mjs';
import {Reference} from '../runner/reference.mjs';
import {nativeObservation} from '../models/native-dataset.mjs';
import {buildRetrievalIndex,retrieveCandidates} from '../models/retrieval.mjs';
import {predictPatch,trainPredictor} from '../models/predictor.mjs';

const args=process.argv.slice(2);
function option(name,fallback=null){const index=args.indexOf(name);return index<0?fallback:args[index+1]??fallback;}
const rounds=Number(option('--rounds','5'));
if(!Number.isInteger(rounds)||rounds<1||rounds>100)throw Error('--rounds must be 1 through 100.');

function wav16(samples,sampleRate=48000){
 const bytes=new Uint8Array(44+samples.length*2),view=new DataView(bytes.buffer);
 const text=(offset,value)=>value.split('').forEach((character,index)=>bytes[offset+index]=character.charCodeAt(0));
 text(0,'RIFF');view.setUint32(4,bytes.length-8,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,sampleRate,true);view.setUint32(28,sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,samples.length*2,true);
 samples.forEach((sample,index)=>view.setInt16(44+index*2,Math.max(-1,Math.min(1,sample))*32767,true));return bytes;
}
function cycle(frameCount=1,size=256){return Array.from({length:frameCount*size},(_,index)=>{const frame=Math.floor(index/size),phase=(index%size)/size;return .72*Math.sin(2*Math.PI*phase+frame*.11)+.18*Math.sin(6*Math.PI*phase-frame*.07)+.06*Math.cos(10*Math.PI*phase)});}
function pitched(size=8192,sampleRate=48000,fundamental=220){return Array.from({length:size},(_,index)=>{const phase=2*Math.PI*fundamental*index/sampleRate;return .68*Math.sin(phase)+.2*Math.sin(2*phase+.15)+.08*Math.sin(3*phase)});}
function median(values){const ordered=[...values].sort((a,b)=>a-b);return ordered[Math.floor(ordered.length/2)];}
function timed(fn){const start=performance.now();const value=fn();return {ms:performance.now()-start,value};}
function timedRounds(fn){for(let i=0;i<1;i++)fn();const values=[];for(let i=0;i<rounds;i++)values.push(timed(fn).ms);return {medianMs:median(values),rounds,values};}

const singleWav=wav16(cycle()),tableWav=wav16(cycle(4)),pitchedWav=wav16(pitched());
const preparation={
 singleCycle:timedRounds(()=>prepareAudio(singleWav,{mode:'single-cycle',frameSize:256,outputSize:256,name:'benchmark'})),
 wavetable:timedRounds(()=>prepareAudio(tableWav,{mode:'wavetable',frameSize:256,frameCount:4,outputSize:256,name:'benchmark'})),
 pitchedSample:timedRounds(()=>prepareAudio(pitchedWav,{mode:'pitched-sample',fundamentalHz:220,frameSize:256,cycles:8,outputSize:256,name:'benchmark'})),
};
const prepared=prepareAudio(singleWav,{mode:'single-cycle',frameSize:256,outputSize:256,name:'benchmark'});

// Synthetic descriptor records make this benchmark independent of dataset
// size and disk contents. They time proposal computation only; they are not
// evidence that synthetic observations match a real Dexed/FM-1 capture.
function syntheticCapture(patch){
 const notes=[45,57,69],waveforms=notes.map(note=>{const frequency=440*2**((note-69)/12);return Array.from({length:4096},(_,i)=>Math.sin(2*Math.PI*frequency*i/48000)+.1*Math.sin(4*Math.PI*frequency*i/48000))});
 return nativeObservation(patch,{sampleRate:48000,velocity:100,offsetSamples:7200,captureSamples:4096,notes,waveforms},{includeWaveforms:false});
}
const records=Array.from({length:16},(_,index)=>{const patch=blank();patch.algorithm=1;patch.feedback=index%8;patch.operators[0].level=70+index;return syntheticCapture(patch)});
const dataset={format:'dexfraggler-native-dataset',version:'native-observations-v1',descriptorVersion:'native-harmonics-v1',records};
const index=buildRetrievalIndex(dataset),checkpoint=timed(()=>trainPredictor(dataset,{algorithm:1,epochs:80})).value;
const proposals={
 retrieval:timedRounds(()=>retrieveCandidates(index,prepared.targets[0],1,{limit:8})),
 predictorTraining:{medianMs:timedRounds(()=>trainPredictor(dataset,{algorithm:1,epochs:80})).medianMs,epochs:80,examples:records.length},
 predictorInference:timedRounds(()=>predictPatch(checkpoint,prepared.targets[0])),
};

const nativePatch=blank(),reference=new Reference();let nativeCapture;
try{nativeCapture=await reference.render(nativePatch);}finally{await reference.close();}
const nativeScoring=timedRounds(()=>measuredScore(nativeCapture.waveforms[1],prepared.targets[0],57,{preview:false}));
const report={format:'dexfraggler-sample-pipeline-benchmark-v1',node:process.version,platform:process.platform,rounds,targets:prepared.targets.length,preparation,proposals,nativeScoring:{...nativeScoring,renderer:'Dexed Mark I / native',metric:'band-limited-match-v1'},limitations:['Synthetic records benchmark proposal CPU cost only; retrieval and predictor quality require held-out native data.','Native scoring timing excludes renderer startup and measures one 4,096-sample capture against one imported target.','Run with equal rounds, row budgets, and dataset limits when comparing changes.']};
const output=option('--output');if(output)await fs.writeFile(output,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
