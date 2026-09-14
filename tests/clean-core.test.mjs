import test from 'node:test';
import assert from 'node:assert/strict';
import {MODEL,MODEL_HARMONICS,blank,clone,validatePatch,harmonicSeeds,initialState,runBatch,render,renderWithLevelJacobian,targetWave,evaluate,sysex,fromSysex} from '../public/core.mjs';
import {idealTarget,coefficients,targetKey,blendTargets} from '../public/targets.mjs';
import {render as independentlyRetainedRenderer} from './fixtures/core-baseline.mjs';

test('the optimizer only accepts the ideal target contract and an explicit algorithm',()=>{
  const target=idealTarget('saw');
  assert.equal(MODEL_HARMONICS,127);assert.equal(MODEL,'dexfraggler-pm-48k-ideal-v1');
  for(const algorithm of [undefined,0,33,-1,1.5])assert.throws(()=>initialState(target,[],127,algorithm));
  assert.throws(()=>initialState('saw',[],127,1));
  assert.throws(()=>targetWave({kind:'fourier-path-v1',sin:[1],cos:[0]}));
  assert.throws(()=>initialState(target,[],32,1));
  assert.throws(()=>initialState(target,[{patch:blank()}],127,1));
  const state=initialState(target,[],127,1);assert.equal(state.nativeSeeds,undefined);assert.equal(state.elites.some(e=>'source' in e),false);
  assert.throws(()=>runBatch({...state,model:'dexfraggler-pm-48k-v1'},10));
});

test('patches require canonical fields and reject aliases, defaults and extra properties',()=>{
  assert.deepEqual(validatePatch(blank()),blank());
  for(const key of ['op','coarse','fine','detune','mode','level']){const p=blank();delete p.operators[2][key];assert.throws(()=>validatePatch(p),key)}
  for(const [key,value] of [['output_level',99],['osc_mode','ratio'],['name','operator']]){const p=blank();p.operators[0][key]=value;assert.throws(()=>validatePatch(p),key)}
  const extra=blank();extra.name='Test';assert.throws(()=>validatePatch(extra));
  const reversed=blank();reversed.operators.reverse();assert.deepEqual(validatePatch(reversed),blank());
  assert.deepEqual(fromSysex(sysex(blank())),blank());
});

test('additive startup candidates follow each target and never turn negative coefficients positive',()=>{
  const active=p=>p.operators.filter(o=>o.level>1).map(o=>o.coarse);
  const find=shape=>harmonicSeeds(idealTarget(shape),32).filter(p=>p.feedback===0).at(-1);
  assert.deepEqual(active(find('sine')),[1]);
  assert.deepEqual(active(find('saw')),[1,2,3,4,5,6]);
  assert.deepEqual(active(find('square')),[1,3,5,7,9,11]);
  assert.deepEqual(active(find('triangle')),[1,5,9,13,17,21]);
  const t=idealTarget('triangle'),c=coefficients(t,31);
  assert.ok(c.sin[2]<0);assert.ok(find('triangle').operators.filter(o=>o.level>1).every(o=>c.sin[o.coarse-1]>0));
});

test('every topology has fresh legal feedback0–7 candidates and stays in its row',()=>{
  const target=blendTargets(idealTarget('triangle'),idealTarget('saw'),.4);
  for(let algorithm=1;algorithm<=32;algorithm++){
    const seeds=harmonicSeeds(target,algorithm);
    assert.deepEqual([...new Set(seeds.map(p=>p.feedback))].sort(),[0,1,2,3,4,5,6,7]);
    seeds.forEach(p=>{assert.equal(p.algorithm,algorithm);validatePatch(p);assert.ok(p.operators.some(o=>o.level>1))});
    const state=initialState(target,[],127,algorithm),before=state.elites[0].loss;
    assert.ok(state.elites.every(e=>Number.isFinite(e.loss)&&e.patch.algorithm===algorithm));
    const after=runBatch(state,10);assert.ok(after.elites[0].loss<=before);assert.ok(after.elites.every(e=>e.patch.algorithm===algorithm));
  }
});

test('model target projection reaches harmonic127 and excludes the Nyquist harmonic128',()=>{
  const target=idealTarget('saw'),wave=targetWave(target),series=coefficients(target,127);
  for(const i of [0,1,7,35,100,255]){
    const theta=2*Math.PI*187.5*i/48000,expected=series.sin.reduce((sum,c,j)=>sum+c*Math.sin((j+1)*theta),0);
    assert.ok(Math.abs(wave[i]-expected)<1e-13);
  }
  assert.deepEqual(targetWave(target,128),wave);
  assert.ok(evaluate(blank(),target).loss>0);
});

test('clean target/proposal changes preserve the renderer and analytic Jacobian waveform exactly',()=>{
  for(let algorithm=1;algorithm<=32;algorithm++)for(const feedback of [0,1,4,7]){
    const p=blank();p.algorithm=algorithm;p.feedback=feedback;p.operators.forEach((o,i)=>{o.level=45.37+6*i;o.coarse=i+1;o.fine=3*i});
    const expected=independentlyRetainedRenderer(p,128),actual=render(p,128);
    assert.deepEqual(actual,expected);assert.deepEqual(renderWithLevelJacobian(p,128).wave,expected);
  }
});

test('new state resume is monotonic and distinct targets use distinct initialization randomness',()=>{
  const a=initialState(idealTarget('square'),[],127,32),b=initialState(idealTarget('triangle'),[],127,32);
  assert.notEqual(a.rng,b.rng);assert.notEqual(targetKey(a.shape),targetKey(b.shape));
  const first=runBatch(a,50),resumed=runBatch(clone(first),50);
  assert.ok(resumed.evaluations>first.evaluations);assert.ok(resumed.elites[0].loss<=first.elites[0].loss);
});

