import test from 'node:test';
import assert from 'node:assert/strict';
import {MODEL_HARMONICS,blank,analyze,targetWave,render,sysex,fromSysex,validatePatch,runBatch,initialState,interpolate,fft,algorithms,display,frequency} from '../public/core.mjs';
import {idealTarget} from '../public/targets.mjs';
import {Reference,nativeProposal} from '../runner/reference.mjs';
import {measuredScore} from '../runner/measurement.mjs';

const saw=idealTarget('saw'),square=idealTarget('square'),triangle=idealTarget('triangle');

test('phase alignment preserves waveform shape with one global shift',()=>{
  const target=targetWave(saw),shift=53,wave=Float64Array.from(target,(_,i)=>3*target[(i+shift)%target.length]);
  const match=analyze(wave,saw);assert.ok(match.score>1-1e-12);assert.ok(Math.abs(match.scale-1/3)<1e-12);
});
test('phase-distorted equal-magnitude waves do not get a perfect score',()=>{
  const target=targetWave(saw),real=new Float64Array(target),imag=new Float64Array(target.length);fft(real,imag);
  for(let k=8;k<512;k+=8){real[k]*=-1;imag[k]*=-1;real[1024-k]*=-1;imag[1024-k]*=-1}
  fft(real,imag,true);assert.ok(analyze(real,saw).score<.99);
});
test('zero output cannot be a matching waveform',()=>{
  const patch=blank();patch.operators.forEach(op=>op.level=0);assert.equal(analyze(render(patch),triangle).score,0);
});
test('all 32 algorithms render finite delayed-feedback output',()=>{
  for(let algorithm=1;algorithm<=32;algorithm++){
    const patch=blank();patch.algorithm=algorithm;patch.feedback=7;patch.operators.forEach(op=>op.level=80);
    assert.ok(Array.from(render(patch)).every(Number.isFinite));
  }
  assert.equal(algorithms.length,32);
});
test('DX7 single-voice checksum and full parameter round trip',()=>{
  const patch=blank();patch.algorithm=4;patch.feedback=7;
  patch.operators.forEach((op,i)=>{op.coarse=i*6;op.fine=i*17;op.detune=i*2;op.level=i*18});
  const bytes=sysex(patch);assert.equal(bytes.length,163);assert.equal(Array.from(bytes.slice(6,162)).reduce((sum,x)=>sum+x,0)&127,0);
  assert.deepEqual(fromSysex(bytes),patch);bytes[36]^=1;assert.throws(()=>fromSysex(bytes),/checksum/);
});
test('patch validation rejects illegal and duplicate operators',()=>{
  const patch=blank();patch.operators[1].op=1;assert.throws(()=>validatePatch(patch));
  patch.operators[1].op=2;patch.operators[0].fine=100;assert.throws(()=>validatePatch(patch));
});
test('current optimizer resumes without regressing its champion',()=>{
  const state=initialState(square,[],MODEL_HARMONICS,1),before=JSON.stringify(state),next=runBatch(state,100);
  assert.equal(JSON.stringify(state),before);assert.ok(next.evaluations>state.evaluations);assert.ok(next.elites[0].loss<=state.elites[0].loss);
  const resumed=runBatch(JSON.parse(JSON.stringify(next)),100);assert.ok(resumed.elites[0].loss<=next.elites[0].loss);
  assert.ok(resumed.elites.every(e=>e.patch.algorithm===1));
});
test('interpolation blends effective ratios rather than raw coarse codes',()=>{
  const a=blank(),b=blank();a.operators[0].coarse=1;a.operators[0].fine=99;b.operators[0].coarse=2;b.operators[0].fine=0;
  const result=interpolate(a,b,.5);assert.ok(result.operators[0].coarse*(1+result.operators[0].fine/100)>1.98);
  b.algorithm=31;assert.throws(()=>interpolate(a,b,.5),/same algorithm/);
});
test('native engine measures the ideal target at all three pitches', {timeout:20000},async()=>{
  const reference=new Reference();
  try{
    const result=await reference.score(blank(),triangle);
    assert.deepEqual(result.notes.map(note=>note.note),[45,57,69]);assert.deepEqual(result.notes.map(note=>note.bands),[218,109,54]);
    assert.ok(result.notes.every(note=>note.score>.99&&note.score<1));
    for(const note of result.notes)for(const field of ['wave','target','idealTarget'])assert.equal(note[field].length,512);
  }finally{await reference.close()}
});
test('silent diagnostics and seven-bit SysEx validation remain finite and strict',()=>{
  const patch=blank();patch.operators.forEach(op=>op.level=0);assert.ok(display(patch,saw).harmonics.every(Number.isFinite));
  const checksum=sysex(blank());checksum[161]+=128;assert.throws(()=>fromSysex(checksum));
  const channel=sysex(blank());channel[2]=16;assert.throws(()=>fromSysex(channel));
});
test('interpolation preserves detuned endpoints and legal fixed-frequency boundaries',()=>{
  const patch=blank();patch.operators[0].detune=14;assert.deepEqual(interpolate(patch,patch,0),patch);
  const a=blank(),b=blank();a.operators[0].mode=b.operators[0].mode=1;a.operators[0].coarse=1;a.operators[0].fine=99;b.operators[0].coarse=2;b.operators[0].fine=0;
  assert.doesNotThrow(()=>validatePatch(interpolate(a,b,.9)));
  const detuned={...a.operators[0],detune:14};assert.ok(frequency(detuned)>frequency({...detuned,detune:7}));
});
test('native fine-tuning proposals move in both directions',()=>{
  const patch=blank();patch.operators.forEach(op=>op.fine=50);
  assert.equal(nativeProposal(patch,8).operators[0].fine,49);assert.equal(nativeProposal(patch,80).operators[0].fine,51);
});
test('full-Nyquist native phase refinement has no coarse-grid error floor',()=>{
  const wave=targetWave(saw,MODEL_HARMONICS,4096,220,.123456);
  const match=measuredScore(wave,saw,57,{preview:false});assert.equal(match.bands,109);assert.ok(match.error<1e-5,String(match.error));
});
