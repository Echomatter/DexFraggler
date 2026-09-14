import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
import {blank,clone,sysex} from '../public/core.mjs';
import {coefficients,TARGET_VERSION} from '../public/targets.mjs';
import {Reference} from '../runner/reference.mjs';
import {measuredScore,prepareAudio,scorePrepared} from '../runner/measurement.mjs';
import {measuredScore as baselineScore} from './fixtures/measurement-baseline.mjs';

// Run with: node --test tests/native-score.test.mjs
// An explicit path also supports testing a separately built reference binary.
const executablePath=process.env.DEXFRAGGLER_NATIVE_EXE
  ||fileURLToPath(new URL('../native/bin/DexfragglerReference.exe',import.meta.url));
const TOLERANCE=1e-8;
const NOTES=[45,57,69];

function patchCases(){
  const sine=blank();
  const algorithm4=blank();algorithm4.algorithm=4;algorithm4.feedback=7;
  algorithm4.operators.forEach((op,i)=>{op.level=[88,73,80,91,77,84][i];op.coarse=[1,2,3,1,2,1][i];});
  const algorithm6=clone(algorithm4);algorithm6.algorithm=6;algorithm6.feedback=4;
  algorithm6.operators.forEach((op,i)=>{op.detune=[4,10,6,8,7,11][i];op.fine=[0,7,0,3,0,11][i];});
  const algorithm32=blank();algorithm32.feedback=7;
  algorithm32.operators.forEach((op,i)=>{op.level=[82,74,69,63,59,81][i];op.coarse=[1,2,3,4,5,1][i];});
  const fixed=clone(algorithm32);fixed.feedback=2;
  Object.assign(fixed.operators[0],{mode:1,coarse:2,fine:34,detune:14});
  Object.assign(fixed.operators[3],{mode:1,coarse:1,fine:63,detune:3});
  return [{name:'sine',patch:sine},{name:'algorithm 4, feedback 7',patch:algorithm4},
    {name:'algorithm 6, feedback 4, fine and detune',patch:algorithm6},
    {name:'algorithm 32, feedback 7',patch:algorithm32},{name:'fixed and ratio oscillators',patch:fixed}];
}

const arbitrary={kind:TARGET_VERSION,
  sin:Array.from({length:64},(_,i)=>Math.sin((i+1)*1.317)/(i+1)**.8),
  cos:Array.from({length:64},(_,i)=>Math.cos((i+1)*.731)/(i+1)**1.1)};
const targetCases=[
  {name:'saw preset',target:'saw',h:16},
  {name:'square preset',target:'square',h:32},
  {name:'triangle preset',target:'triangle',h:64},
  ...[16,32,64].map(h=>({name:`arbitrary Fourier ${h}`,target:arbitrary,h})),
  {name:'table triangle coefficients',target:coefficients('triangle',32),h:32},
];

function closeNumber(actual,expected,label,maxima,key){
  assert.ok(Number.isFinite(actual)&&Number.isFinite(expected),`${label}: finite values required`);
  const delta=Math.abs(actual-expected);
  if(maxima)maxima[key]=Math.max(maxima[key]||0,delta);
  assert.ok(delta<=TOLERANCE,`${label}: ${actual} != ${expected}; delta ${delta}`);
}

function compareNote(actual,expected,label,maxima,{preview=true}={}){
  assert.equal(actual.note,expected.note,`${label}: pitch`);
  assert.equal(actual.bands,expected.bands,`${label}: Nyquist bandwidth`);
  for(const key of ['score','error','shift'])closeNumber(actual[key],expected[key],`${label}: ${key}`,maxima,key);
  for(const key of ['wave','target']){
    if(!preview){assert.equal(actual[key],undefined,`${label}: lazy ${key}`);continue;}
    assert.equal(actual[key].length,expected[key].length,`${label}: ${key} length`);
    for(let i=0;i<expected[key].length;i++)closeNumber(actual[key][i],expected[key][i],`${label}: ${key}[${i}]`,maxima,key);
  }
}

function validateCapture(capture){
  assert.equal(capture.ok,true);assert.equal(capture.sampleRate,48000);
  assert.equal(capture.velocity,100);assert.equal(capture.offsetSamples,7200);
  assert.equal(capture.captureSamples,4096);assert.deepEqual(capture.notes,NOTES);
  assert.equal(capture.waveforms.length,3);
  for(const waveform of capture.waveforms){
    assert.equal(waveform.length,4096);assert.ok(waveform.every(Number.isFinite));
    assert.ok(waveform.some(x=>Math.abs(x)>1e-6),'Expected a non-silent native capture');
  }
}

test('native scores preserve the baseline metric, phase and every preview sample', {timeout:20000},async t=>{
  const reference=new Reference({executablePath});
  t.after(()=>reference.close());
  const maxima={score:0,error:0,shift:0,wave:0,target:0};let comparisons=0;
  for(const {name,patch} of patchCases()){
    const capture=await reference.render(patch);validateCapture(capture);
    const contexts=capture.waveforms.map((audio,i)=>prepareAudio(audio,NOTES[i]));
    for(const targetCase of targetCases){
      const {target,h}=targetCase;
      const measurement=await reference.score(patch,target,h);
      assert.equal(measurement.engine,'Dexed Mark I / native');
      assert.equal(measurement.sampleRate,48000);assert.equal(measurement.velocity,100);
      assert.equal(measurement.captureSamples,4096);assert.equal(measurement.offsetSamples,7200);
      assert.deepEqual(measurement.patch,patch);assert.equal(measurement.notes.length,3);
      const expectedNotes=[];
      for(let i=0;i<NOTES.length;i++){
        const label=`${name}, ${targetCase.name}, note ${NOTES[i]}`;
        const expected=baselineScore(capture.waveforms[i],target,NOTES[i],h);expectedNotes.push(expected);
        compareNote(measurement.notes[i],expected,`${label}: Reference`,maxima);
        compareNote(measuredScore(capture.waveforms[i],target,NOTES[i],h),expected,`${label}: drop-in`,maxima);
        compareNote(scorePrepared(contexts[i],target,h),expected,`${label}: prepared`,maxima);
        comparisons++;
      }
      closeNumber(measurement.score,Math.min(...expectedNotes.map(note=>note.score)),'aggregate score',maxima,'score');
      closeNumber(measurement.loss,Math.max(...expectedNotes.map(note=>note.error**2)),'aggregate loss');
    }
  }
  assert.equal(reference.renders,5);assert.equal(reference.metrics.preparedPitches,15);
  t.diagnostic(JSON.stringify({nativePatches:5,noteTargetComparisons:comparisons,pathsPerComparison:3,tolerance:TOLERANCE,maximumAbsoluteDelta:maxima}));
});

test('exact SysEx cache coalesces requests, reuses projections and evicts the least recent patch', {timeout:10000},async t=>{
  const reference=new Reference({executablePath,cacheLimit:2});
  t.after(()=>reference.close());
  assert.ok(reference.pid>0);assert.ok(reference.startedAt<=Date.now());
  assert.equal(reference.processStartedAt,reference.startedAt);
  const a=blank(),b=clone(a),c=clone(a);
  // These silent-operator changes are acoustically identical, but their bytes differ.
  b.operators[5].fine=1;c.operators[5].fine=2;
  assert.notDeepEqual(sysex(a),sysex(b));assert.notDeepEqual(sysex(b),sysex(c));
  const targets=[coefficients('triangle',32),coefficients('square',32),arbitrary];
  const [many,capture,single]=await Promise.all([
    reference.scoreMany(a,targets,32),reference.render(a),reference.score(a,targets[0],32),
  ]);
  assert.equal(reference.renders,1);assert.equal(reference.metrics.inflightHits,2);
  assert.equal(reference.metrics.preparedPitches,3);
  assert.equal(many[0].score,single.score);assert.equal(many[0].loss,single.loss);
  const compact=await reference.scoreMany(a,targets,32,{preview:false});
  for(let i=0;i<many.length;i++){
    assert.equal(compact[i].score,many[i].score);assert.equal(compact[i].loss,many[i].loss);
    for(let j=0;j<3;j++)compareNote(compact[i].notes[j],many[i].notes[j],`compact target ${i}, pitch ${j}`,null,{preview:false});
  }
  const reordered=clone(a);reordered.operators.reverse();
  assert.deepEqual(sysex(reordered),sysex(a));
  assert.strictEqual(await reference.render(reordered),capture,'Canonical byte identity must hit the cache');
  assert.equal(reference.renders,1);assert.equal(reference.metrics.preparedPitches,3);
  const captureB=await reference.render(b);assert.equal(reference.renders,2);
  assert.deepEqual(captureB.waveforms,capture.waveforms,'Silent-operator byte changes should keep this audio identical');
  assert.strictEqual(await reference.render(a),capture); // Refresh A; B becomes least recent.
  await reference.render(c);assert.equal(reference.renders,3);assert.equal(reference.metrics.evictions,1);
  assert.strictEqual(await reference.render(a),capture,'The recently touched capture must survive');
  await reference.render(b);assert.equal(reference.renders,4);assert.equal(reference.metrics.evictions,2);
  const invalid=clone(a);invalid.algorithm=33;
  await assert.rejects(reference.render(invalid));assert.equal(reference.metrics.pending,0);
  await reference.render(b);assert.equal(reference.renders,4,'Invalid patch must not corrupt a cached request');
  assert.equal(reference.metrics.cacheEntries,2);assert.equal(reference.metrics.inflight,0);
  assert.equal(reference.metrics.preparedPitches,3);
  t.diagnostic(JSON.stringify(reference.metrics));
  assert.equal((await reference.close()).code,0);
  await assert.rejects(reference.render(a),/unavailable/);
});

test('native line protocol reports malformed input and accepts the next valid patch', {timeout:10000},async t=>{
  const child=spawn(executablePath,[],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  const exited=once(child,'close');
  let stderr='';child.stderr.on('data',chunk=>{stderr+=chunk;});
  const lines=readline.createInterface({input:child.stdout});
  const responses=lines[Symbol.asyncIterator]();
  t.after(async()=>{if(child.exitCode===null)child.kill();await exited;lines.close();});
  async function request(line){
    child.stdin.write(`${line}\n`);
    const response=await responses.next();assert.equal(response.done,false,'Native process exited before a response');
    return JSON.parse(response.value);
  }
  for(const invalid of ['0,0,0','not,a,voice']){
    const error=await request(invalid);assert.equal(error.ok,false);assert.equal(typeof error.error,'string');
    const capture=await request(Array.from(sysex(blank()).subarray(6,161)).join(','));validateCapture(capture);
  }
  child.stdin.end();const [code]=await exited;assert.equal(code,0);assert.equal(stderr,'');
});
