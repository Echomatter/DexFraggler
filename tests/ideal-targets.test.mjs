import test from 'node:test';
import assert from 'node:assert/strict';
import {WAVEFORMS,DEFAULT_CONFIG,idealTarget,validateTarget,validateConfig,blendTargets,columnTargets,sample,cycle,idealPoints,coefficients,idealEnergy,projectionInfo,nyquistHarmonics,targetKey,scheduleCell} from '../public/targets.mjs';
const TAU=2*Math.PI;
function near(a,b,tolerance=1e-12){assert.ok(Math.abs(a-b)<=tolerance,`${a} != ${b}`);}

test('targets are strict analytic formulas and anchor blends, with no legacy/custom schema',()=>{
  assert.throws(()=>validateConfig({...DEFAULT_CONFIG,harmonics:32}));
  assert.throws(()=>validateConfig({allowDetune:false,anchors:[{slot:0,shape:'custom',target:{sin:[1],cos:[0]}}]}));
  assert.throws(()=>validateTarget({kind:'fourier-path-v1',sin:[1],cos:[0]}));
  assert.throws(()=>validateTarget({kind:'ideal-waveform-v1',weights:[1,0,0,0],samples:[0,1]}));
  const columns=columnTargets(DEFAULT_CONFIG);
  assert.deepEqual(columns[0],idealTarget('triangle'));assert.deepEqual(columns[15],idealTarget('square'));assert.deepEqual(columns[31],idealTarget('saw'));
  const left=idealTarget('triangle'),right=idealTarget('square'),blend=blendTargets(left,right,7/15);
  assert.deepEqual(columns[7],blend);
  for(let i=0;i<64;i++){const phase=TAU*(i+.317)/64;near(sample(blend,phase),sample(left,phase)*(1-7/15)+sample(right,phase)*7/15);}
});

test('ideal displays retain exact straight edges, corners and jump limits',()=>{
  const triangle=idealTarget('triangle'),square=idealTarget('square'),saw=idealTarget('saw');
  [0,1,0,-1].forEach((value,i)=>near(sample(triangle,i*Math.PI/2),value));
  const triangleCycle=cycle(triangle,256);for(let i=0;i<64;i++)near(triangleCycle[i],i/64);
  near(sample(square,0),0);near(sample(square,Math.PI/4),1);near(sample(square,5*Math.PI/4),-1);
  near(sample(saw,Math.PI/4),.75);near(sample(saw,Math.PI),0);near(sample(saw,7*Math.PI/4),-.75);
  const points=idealPoints(square,128,2);
  assert.deepEqual(points.filter(p=>p.x===.5),[{x:.5,y:1},{x:.5,y:-1}]);
  assert.deepEqual(points.filter(p=>p.x===1),[{x:1,y:-1},{x:1,y:1}]);
  assert.ok(points.every(p=>p.y===-1||p.y===1),'The ideal square drawing must have no Fourier ringing or rounded edges');
});

test('exact Fourier coefficients and full ideal energies remain independent of projection bandwidth',()=>{
  assert.deepEqual([110,220,440,187.5].map(base=>nyquistHarmonics(base)),[218,109,54,127]);
  const expectedEnergy={sine:.5,triangle:1/3,square:1,saw:1/3};
  for(const shape of WAVEFORMS){
    const target=idealTarget(shape),short=coefficients(target,16),long=coefficients(target,218);
    assert.deepEqual(short.sin,long.sin.slice(0,16));assert.ok(long.cos.every(x=>x===0));
    near(idealEnergy(target),expectedEnergy[shape]);
    const info=projectionInfo(target,110);assert.equal(info.bands,218);
    assert.ok(info.retainedEnergy>0&&info.retainedEnergy<=1);
    near(info.projectedEnergy+info.omittedEnergy,info.fullEnergy);
    if(shape==='sine')near(info.retainedEnergy,1);else assert.ok(info.omittedEnergy>0);
  }
  const blend={kind:'ideal-waveform-v1',weights:[.1,.2,.3,.4]},n=65536;
  let numerical=0;for(let i=0;i<n;i++)numerical+=sample(blend,TAU*(i+.5)/n)**2/n;
  near(idealEnergy(blend),numerical,2e-9);
  const tri=coefficients(idealTarget('triangle'),5).sin;
  near(tri[0],8/Math.PI**2);near(tri[2],-8/(9*Math.PI**2));near(tri[4],8/(25*Math.PI**2));
});

test('least-visited scheduling keeps revisiting every cell even when all scores equal one',()=>{
  const keys=columnTargets(DEFAULT_CONFIG).map(targetKey),cells=Array.from({length:1024},(_,id)=>({id,target_key:keys[id%32],visits:0,native_score:1}));
  for(let i=0;i<2048;i++){const id=scheduleCell(cells,DEFAULT_CONFIG,keys);assert.notEqual(id,null);cells[id].visits++;}
  assert.ok(cells.every(cell=>cell.visits===2));
});
