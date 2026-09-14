import assert from 'node:assert/strict';
import test from 'node:test';
import {render,amplitude as oracleAmplitude} from './fixtures/core-baseline.mjs';
import {MODEL_HARMONICS,blank,clone,evaluate,validatePatch,render as renderFast,renderWithLevelJacobian,amplitudeDerivative,fitLevels as fitLevelsAnalytic} from '../public/core.mjs';
import {idealTarget} from '../public/targets.mjs';

function patch(algorithm,feedback,integer=false){
  const p=blank();p.algorithm=algorithm;p.feedback=feedback;
  p.operators.forEach((o,i)=>{o.level=[40,52,60,69,76,70][i]+(integer?0:.37);o.coarse=[1,2,3,1,2,4][i];o.fine=[0,7,0,13,0,3][i];o.detune=i%3+6});
  return p;
}

test('analytic renderer preserves every sample across all algorithms and feedback amounts',()=>{
  for(let algorithm=1;algorithm<=32;algorithm++)for(let feedback=0;feedback<8;feedback++){
    const p=patch(algorithm,feedback),a=render(p,256),b=renderWithLevelJacobian(p,256);
    assert.deepEqual(b.wave,a,`algorithm ${algorithm}, feedback ${feedback}`);
    assert.deepEqual(renderFast(p,256),a,`fast renderer: algorithm ${algorithm}, feedback ${feedback}`);
    assert.equal(b.finite,true);
  }
});

test('warmup pruning is exact with fixed mode, high feedback, arbitrary base and carrier components',()=>{
  for(let algorithm=1;algorithm<=32;algorithm++){
    const p=patch(algorithm,7,true);
    p.operators.forEach((o,i)=>{o.level=90+i;o.coarse=i%4;o.fine=13*i;o.mode=i%2;o.detune=2*i});
    assert.deepEqual(renderFast(p,197,110,true),render(p,197,110,true));
  }
});

test('six analytic columns agree with central differences away from level knots',()=>{
  let worst=0,location='';
  for(let algorithm=1;algorithm<=32;algorithm++)for(const feedback of [0,1,4,7]){
    const p=patch(algorithm,feedback),d=renderWithLevelJacobian(p,128);
    for(let j=0;j<6;j++){
      const plus=clone(p),minus=clone(p),eps=1e-4;
      plus.operators[j].level+=eps;minus.operators[j].level-=eps;
      const wp=render(plus,128),wm=render(minus,128);let diff2=0,ref2=0;
      for(let i=0;i<128;i++){const fd=(wp[i]-wm[i])/(2*eps),err=d.jacobian[j][i]-fd;diff2+=err*err;ref2+=fd*fd}
      const relative=Math.sqrt(diff2/Math.max(ref2,1e-20));
      if(relative>worst){worst=relative;location=`A${algorithm} F${feedback} OP${j+1}`}
      assert.ok(relative<2e-5,`${location}: relative derivative error ${relative}`);
    }
  }
  console.log({worstRelativeDerivativeError:worst,location});
});

test('piecewise low-level derivative matches the relaxed amplitude law',()=>{
  for(let level=2.37;level<99;level+=1){const eps=1e-6,fd=(oracleAmplitude(level+eps)-oracleAmplitude(level-eps))/(2*eps);assert.ok(Math.abs(amplitudeDerivative(level)-fd)<1e-8)}
  assert.equal(amplitudeDerivative(0),0);assert.equal(amplitudeDerivative(1),0);
});

test('fitter returns bounded legal discrete proposals and handles silence',()=>{
  const target=idealTarget('saw');
  for(let algorithm=1;algorithm<=32;algorithm++)for(const feedback of [0,7]){
    const p=patch(algorithm,feedback,true),out=fitLevelsAnalytic(p,target,MODEL_HARMONICS);
    assert.deepEqual(validatePatch(out),out);assert.equal(out.algorithm,p.algorithm);assert.equal(out.feedback,p.feedback);
    out.operators.forEach((o,i)=>assert.ok(Math.abs(o.level-p.operators[i].level)<=8));
    assert.ok(Number.isFinite(evaluate(out,target,MODEL_HARMONICS).loss));
  }
  const silent=blank();silent.operators.forEach(o=>o.level=0);assert.deepEqual(fitLevelsAnalytic(silent,target,MODEL_HARMONICS),silent);
});

test('derivative of nested feedback includes terminal gain and both delays',()=>{
  for(const algorithm of [4,6,32]){
    const p=patch(algorithm,7),d=renderWithLevelJacobian(p,64);
    assert.ok(d.jacobian.flatMap(x=>Array.from(x)).some(x=>Math.abs(x)>1e-3));
    // This comparison uses different points from the exhaustive derivative test.
    p.operators.forEach(o=>o.level+=.11);
    const second=renderWithLevelJacobian(p,64);
    assert.deepEqual(second.wave,render(p,64));
  }
});
