import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
import {blank,clone,sysex} from '../public/core.mjs';
import {idealTarget,blendTargets,coefficients,nyquistHarmonics} from '../public/targets.mjs';
import {METRIC_VERSION,prepareAudio,scorePrepared,measuredScore,scoringDiagnostics} from '../runner/measurement.mjs';
const TAU=2*Math.PI;
const executablePath=process.env.DEXFRAGGLER_NATIVE_EXE||fileURLToPath(new URL('../native/bin/DexfragglerReference.exe',import.meta.url));
const targets=[...['sine','triangle','square','saw'].map(idealTarget),blendTargets(idealTarget('triangle'),idealTarget('saw'),.37)];
function near(a,b,tol=1e-8,label='value'){assert.ok(Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<=tol,`${label}: ${a} != ${b}`);}
function naive(audio,target,note,phase){
  const base=440*2**((note-69)/12),bands=nyquistHarmonics(base),{sin}=coefficients(target,bands),n=audio.length;
  const mean=audio.reduce((a,b)=>a+b,0)/n;let dot=0,sum=0,squares=0,energy=0;
  for(let i=0;i<n;i++){
    const theta=TAU*base*i/48000+phase;let y=0;
    for(let k=1;k<=bands;k++)y+=sin[k-1]*Math.sin(k*theta);
    const a=audio[i]-mean;dot+=a*y;sum+=y;squares+=y*y;energy+=a*a;
  }
  return {score:Math.max(0,Math.min(1,dot/Math.sqrt(energy*(squares-sum*sum/n)))),scale:dot/energy,targetMean:sum/n,mean};
}
function patches(){
  const sine=blank(),a=blank();a.algorithm=4;a.feedback=7;
  a.operators.forEach((op,i)=>Object.assign(op,{level:[88,73,80,91,77,84][i],coarse:[1,2,3,1,2,1][i]}));
  const b=clone(a);b.algorithm=6;b.feedback=4;b.operators.forEach((op,i)=>Object.assign(op,{fine:i*3,detune:[4,10,6,8,7,11][i]}));
  const c=clone(a);c.algorithm=32;c.feedback=7;
  const d=clone(c);d.feedback=2;Object.assign(d.operators[0],{mode:1,coarse:2,fine:34,detune:14});
  return [sine,a,b,c,d];
}

test('full-Nyquist scorer agrees with direct native sample comparisons and previews', {timeout:20000},async t=>{
  const child=spawn(executablePath,[],{windowsHide:true,stdio:['pipe','pipe','pipe']}),exited=once(child,'close');
  const lines=readline.createInterface({input:child.stdout}),responses=lines[Symbol.asyncIterator]();let stderr='';child.stderr.on('data',chunk=>{stderr+=chunk;});
  t.after(async()=>{if(child.exitCode===null)child.kill();await exited;lines.close();});
  let maxScoreDelta=0,maxPreviewDelta=0,comparisons=0;
  for(const patch of patches()){
    child.stdin.write(Array.from(sysex(patch).subarray(6,161)).join(',')+'\n');const reply=await responses.next();assert.equal(reply.done,false);const capture=JSON.parse(reply.value);
    assert.equal(capture.ok,true);assert.deepEqual(capture.notes,[45,57,69]);assert.ok(capture.waveforms.every(w=>w.length===4096&&w.every(Number.isFinite)));
    for(let i=0;i<3;i++){
      const audio=capture.waveforms[i],note=capture.notes[i],prepared=prepareAudio(audio,note);
      for(const target of targets){
        const actual=scorePrepared(prepared,target),expected=naive(audio,target,note,actual.phase);
        assert.equal(actual.metricVersion,METRIC_VERSION);assert.equal(actual.bands,[218,109,54][i]);
        const delta=Math.abs(actual.score-expected.score);maxScoreDelta=Math.max(maxScoreDelta,delta);near(actual.score,expected.score,1e-8,'direct correlation');
        near(actual.error,Math.sqrt(Math.max(0,1-actual.score**2)),1e-12,'error');
        const challenger=naive(audio,target,note,(actual.phase+1.23456789)%TAU);assert.ok(actual.score>=challenger.score-1e-9,'Phase search missed a better independent challenger');
        const compact=scorePrepared(prepared,target,{preview:false});near(compact.score,actual.score,1e-12);near(compact.phase,actual.phase,1e-12);assert.equal(compact.wave,undefined);
        for(const field of ['wave','target','idealTarget'])assert.equal(actual[field].length,512);
        const {sin}=coefficients(target,actual.bands),base=440*2**((note-69)/12);
        for(const j of [0,1,127,255,384,511]){
          const position=j/511*2*48000/base,idx=Math.floor(position),f=position-idx,theta=TAU*2*j/511+actual.phase;
          const wave=(audio[idx]*(1-f)+audio[idx+1]*f-expected.mean)*expected.scale;
          let projected=0;for(let k=1;k<=actual.bands;k++)projected+=sin[k-1]*Math.sin(k*theta);
          maxPreviewDelta=Math.max(maxPreviewDelta,Math.abs(actual.wave[j]-wave),Math.abs(actual.target[j]-(projected-expected.targetMean)));
          near(actual.wave[j],wave,1e-8,'gain-scaled native preview');near(actual.target[j],projected-expected.targetMean,1e-8,'projected preview');
        }
        comparisons++;
      }
    }
  }
  child.stdin.end();assert.equal((await exited)[0],0);assert.equal(stderr,'');
  t.diagnostic(JSON.stringify({nativePatches:5,comparisons,maxScoreDelta,maxPreviewDelta,diagnostics:scoringDiagnostics()}));
});

test('known exact projected targets recover their phase, gain and DC-independent match',()=>{
  for(const note of [45,57,69])for(const target of targets){
    const base=440*2**((note-69)/12),h=nyquistHarmonics(base),{sin}=coefficients(target,h),phase=1.327451;
    const audio=Array.from({length:4096},(_,i)=>{const theta=TAU*base*i/48000+phase;let y=0;for(let k=1;k<=h;k++)y+=sin[k-1]*Math.sin(k*theta);return .27*y+.123;});
    const actual=measuredScore(audio,target,note,{preview:false});near(actual.score,1,1e-10);near(actual.phase,phase,1e-8,'recovered phase');
  }
  const context=prepareAudio(Array(4096).fill(0),45),silent=scorePrepared(context,idealTarget('square'),{preview:false});
  assert.equal(silent.score,0);assert.equal(silent.error,1);assert.equal(silent.wave,undefined);
  assert.throws(()=>scorePrepared(context,idealTarget('saw'),32),/automatic/);
  assert.throws(()=>scorePrepared(context,{kind:'fourier-path-v1',sin:[1],cos:[0]}));
});

test('certified phase search retains the global match for competing narrow harmonic peaks',()=>{
  // One complete sampled period makes the Fourier basis orthogonal. That gives
  // an independent analytic correlation, including every target harmonic, and
  // allows all its local maxima to be bracketed and refined without the scorer.
  const n=256,note=69+12*Math.log2(48000/n/440),gridSize=32768;
  const scenarios=[
    [[17,.7,.173],[13,.4,-.293],[1,.025,2.41]],
    [[61,.8,2.27],[59,.7,-.93],[3,.02,.117]],
    [[1,.02,.003],[43,.8,0],[47,.61,.043],[62,.4,-.63]],
  ];
  for(const harmonics of scenarios){
    const audio=Array.from({length:n},(_,i)=>.37+harmonics.reduce((sum,[k,a,phase])=>sum+a*Math.sin(TAU*k*i/n+phase),0));
    const prepared=prepareAudio(audio,note);
    for(const target of [idealTarget('square'),idealTarget('saw'),blendTargets(idealTarget('triangle'),idealTarget('saw'),.37)]){
      const {sin}=coefficients(target,prepared.bands),norm=Math.sqrt(harmonics.reduce((sum,[,a])=>sum+a*a,0)*sin.reduce((sum,b)=>sum+b*b,0));
      const correlation=phase=>harmonics.reduce((sum,[k,a,offset])=>sum+a*sin[k-1]*Math.cos(k*phase-offset),0)/norm;
      const grid=Float64Array.from({length:gridSize},(_,i)=>correlation(TAU*i/gridSize));
      let best=-Infinity,maxima=0;
      for(let i=0;i<gridSize;i++)if(grid[i]>=grid[(i+gridSize-1)%gridSize]&&grid[i]>=grid[(i+1)%gridSize]){
        maxima++;let left=TAU*(i-1)/gridSize,right=TAU*(i+1)/gridSize;
        for(let j=0;j<65;j++){
          const a=left+(right-left)/3,b=right-(right-left)/3;
          if(correlation(a)<correlation(b))left=a;else right=b;
        }
        best=Math.max(best,correlation((left+right)/2));
      }
      assert.ok(maxima>10,'The independent objective must contain competing peaks.');
      const actual=scorePrepared(prepared,target,{preview:false});
      near(actual.score,best,1e-10,'independent global maximum');
      near(actual.score,correlation(actual.phase),1e-10,'winning phase correlation');
      assert.equal(actual.phaseScoreTolerance,1e-10);
    }
  }
});
