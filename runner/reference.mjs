import {spawn} from 'node:child_process';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
import {sysex,clone} from '../public/core.mjs';
import {prepareAudio,scorePrepared} from './measurement.mjs';

const BINARY_SHA256='d67045da4b058bb1c7ff62cc347e5cfbd3ea67e260475bb10a7a00cc04d2b5e2';
const DEFAULT_EXE=fileURLToPath(new URL('../native/bin/DexfragglerReference.exe',import.meta.url));

export class Reference {
 constructor({executablePath=DEFAULT_EXE,cacheLimit=16}={}){
  if(!Number.isInteger(cacheLimit)||cacheLimit<1||cacheLimit>64)throw Error('Native capture cache limit must be 1 through 64.');
  this.cacheLimit=cacheLimit;
  this.pending=[];this.cache=new Map();this.inflight=new Map();
  this.healthy=true;this.closing=false;this.startedAt=Date.now();
  this.counters={renders:0,cacheHits:0,inflightHits:0,preparedPitches:0,evictions:0};
  this.child=spawn(executablePath,[],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  this.exitPromise=new Promise(resolve=>this.child.once('close',(code,signal)=>resolve({code,signal})));
  this.lines=readline.createInterface({input:this.child.stdout});
  this.lines.on('line',line=>this.receive(line));
  this.child.on('error',error=>this.fail(error));
  this.child.stdin.on('error',error=>this.fail(error));
  this.child.on('exit',()=>this.fail(Error('Native renderer exited.')));
  this.child.stderr.on('data',data=>process.stderr.write(data));
 }

 get pid(){return this.child.pid??null;}
 get processStartedAt(){return this.startedAt;}
 get renders(){return this.counters.renders;}
 get cacheHits(){return this.counters.cacheHits;}
 get metrics(){
  let captureBytes=0,preparedBytes=0;
  for(const entry of this.cache.values()){
   for(const waveform of entry.capture.waveforms)captureBytes+=waveform.length*8;
   for(const context of entry.contexts??[])preparedBytes+=context.centered.byteLength+context.moments.byteLength;
  }
  return {...this.counters,cacheEntries:this.cache.size,cacheLimit:this.cacheLimit,inflight:this.inflight.size,pending:this.pending.length,captureBytesApprox:captureBytes,preparedBytes,entryBytesApprox:captureBytes+preparedBytes};
 }

 receive(line){
  const request=this.pending.shift();
  if(!request){this.fail(Error('Unexpected response from native renderer.'));this.child.kill();return;}
  clearTimeout(request.timer);
  try{
   const capture=JSON.parse(line);
   if(!capture.ok){request.reject(Error(capture.error||'Native render failed.'));return;}
   if(capture.sampleRate!==48000||capture.velocity!==100||capture.offsetSamples!==7200||capture.captureSamples!==4096
    ||!Array.isArray(capture.notes)||capture.notes.length!==3||!capture.notes.every((note,i)=>note===[45,57,69][i])
    ||!Array.isArray(capture.waveforms)||capture.waveforms.length!==3
    ||!capture.waveforms.every(wave=>Array.isArray(wave)&&wave.length===4096&&wave.every(Number.isFinite)))
    throw Error('Native renderer returned an invalid capture.');
   request.resolve(capture);
  }catch(error){request.reject(error);this.fail(error);this.child.kill();}
 }

 fail(error){
  this.healthy=false;
  for(const request of this.pending){clearTimeout(request.timer);request.reject(error);}
  this.pending=[];
 }

 async request(bytes){
  if(!this.healthy||this.closing)throw Error('Native renderer is unavailable.');
  const input=Array.from(bytes.subarray(6,161)).join(',')+'\n';
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{this.child.kill();this.fail(Error('Native render timed out.'));},30000);
   this.pending.push({resolve,reject,timer});
   this.counters.renders++;
   this.child.stdin.write(input);
  });
 }

 async entry(patch){
  if(!this.healthy||this.closing)throw Error('Native renderer is unavailable.');
  // Validation precedes queue/timer creation. The key includes exact framing,
  // all 155 VCED bytes, and checksum; no rounded or acoustic-similarity keys.
  const bytes=sysex(patch),key=Buffer.from(bytes).toString('hex');
  if(this.cache.has(key)){
   const value=this.cache.get(key);this.cache.delete(key);this.cache.set(key,value);
   this.counters.cacheHits++;return value;
  }
  if(this.inflight.has(key)){this.counters.inflightHits++;return this.inflight.get(key);}
  const pending=this.request(bytes).then(capture=>{
   const value={capture,contexts:null};this.cache.set(key,value);
   while(this.cache.size>this.cacheLimit){this.cache.delete(this.cache.keys().next().value);this.counters.evictions++;}
   return value;
  }).finally(()=>this.inflight.delete(key));
  this.inflight.set(key,pending);return pending;
 }

 async render(patch){return (await this.entry(patch)).capture;}

 contexts(entry){
  if(!entry.contexts){entry.contexts=entry.capture.notes.map((note,i)=>prepareAudio(entry.capture.waveforms[i],note));this.counters.preparedPitches+=entry.contexts.length;}
  return entry.contexts;
 }

 async score(patch,target,h=32){return (await this.scoreMany(patch,[target],h))[0];}

 async scoreMany(patch,targets,h=32,{preview=true}={}){
  if(!Array.isArray(targets))throw Error('Targets must be an array.');
  if(!Number.isInteger(h)||h<1||h>64)throw Error('Target bandwidth must be 1 through 64 harmonics.');
  if(!targets.length)return [];
  const entry=await this.entry(patch),contexts=this.contexts(entry);
  return targets.map(target=>{
   const notes=contexts.map(context=>scorePrepared(context,target,h,{preview}));
   return {engine:'Dexed Mark I / native',sampleRate:48000,velocity:100,captureSamples:4096,offsetSamples:7200,
    patch:clone(patch),notes,loss:Math.max(...notes.map(note=>note.error**2)),score:Math.min(...notes.map(note=>note.score)),testedAt:Date.now(),
    binarySha256:BINARY_SHA256,sourceManifest:'native/source-provenance.json'};
  });
 }

 close(){
  if(!this.closing){this.closing=true;this.child.stdin.end();}
  return this.exitPromise;
 }
}

export function nativeProposal(p,count,allowDetune=false){p=clone(p);const op=p.operators[(Math.floor(count/12))%6],step=[-1,1,-2,2,-4,4,-8,8,-12,12][count%10];const mode=count%12;if(mode<8)op.level=Math.max(0,Math.min(99,op.level+step));else if(mode===8)op.fine=Math.max(0,Math.min(99,op.fine+(Math.floor(count/72)%2?1:-1)));else if(mode===9)op.coarse=[0,1,2,3,4,5,6,7,8,9,11,13,15,19,23,31][Math.floor(count/72)%16];else if(mode===10)p.feedback=(Math.floor(count/72))%8;else if(allowDetune)op.detune=(Math.floor(count/72))%15;else op.level=Math.max(0,Math.min(99,op.level+step));return p}
