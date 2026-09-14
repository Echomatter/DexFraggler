import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
import {blank,clone,sysex} from '../public/core.mjs';
import {idealTarget} from '../public/targets.mjs';
import {Reference} from '../runner/reference.mjs';
import {measuredScore,prepareAudio,scorePrepared} from '../runner/measurement.mjs';

// Run with: node --test tests/native-score.test.mjs
// An explicit path also supports testing a separately built reference binary.
const executablePath=process.env.DEXFRAGGLER_NATIVE_EXE
  ||fileURLToPath(new URL('../native/bin/DexfragglerReference.exe',import.meta.url));
const TOLERANCE=1e-8;
const NOTES=[45,57,69];

function closeNumber(actual,expected,label,maxima,key){
  assert.ok(Number.isFinite(actual)&&Number.isFinite(expected),`${label}: finite values required`);
  const delta=Math.abs(actual-expected);
  if(maxima)maxima[key]=Math.max(maxima[key]||0,delta);
  assert.ok(delta<=TOLERANCE,`${label}: ${actual} != ${expected}; delta ${delta}`);
}

function compareNote(actual,expected,label,maxima,{preview=true}={}){
  assert.equal(actual.note,expected.note,`${label}: pitch`);
  assert.equal(actual.bands,expected.bands,`${label}: Nyquist bandwidth`);
  for(const key of ['score','error','phase'])closeNumber(actual[key],expected[key],`${label}: ${key}`,maxima,key);
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

test('exact SysEx cache coalesces requests, reuses projections and evicts the least recent patch', {timeout:10000},async t=>{
  const reference=new Reference({executablePath,cacheLimit:2});
  t.after(()=>reference.close());
  assert.ok(reference.pid>0);assert.ok(reference.startedAt<=Date.now());
  assert.equal(reference.processStartedAt,reference.startedAt);
  const a=blank(),b=clone(a),c=clone(a);
  // These silent-operator changes are acoustically identical, but their bytes differ.
  b.operators[5].fine=1;c.operators[5].fine=2;
  assert.notDeepEqual(sysex(a),sysex(b));assert.notDeepEqual(sysex(b),sysex(c));
  const targets=['triangle','square','saw'].map(idealTarget);
  const [many,capture,single]=await Promise.all([
    reference.scoreMany(a,targets),reference.render(a),reference.score(a,targets[0]),
  ]);
  assert.equal(reference.renders,1);assert.equal(reference.metrics.inflightHits,2);
  assert.equal(reference.metrics.preparedPitches,3);
  assert.equal(many[0].score,single.score);assert.equal(many[0].loss,single.loss);
  const compact=await reference.scoreMany(a,targets,{preview:false});
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
