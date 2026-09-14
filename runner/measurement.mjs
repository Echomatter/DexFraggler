// Same sampled target and phase search as measurement-baseline.mjs.
// Fourier projections prune only coarse phases that provably cannot win.
// The final score and all 28 refinement iterations use the original interpolant.
const TAU = 2 * Math.PI;
const TABLE_SIZE = 32768;
const MASK = TABLE_SIZE - 1;
const MAX_H = 64;
const basisCache = new Map();
const tableCache = new Map();
const planCache = new Map();
let targetBasis;
const diagnostics = {preparedAudio: 0, plans: 0, coarseExact: 0, coarsePruned: 0, fineExact: 0};

export function scoringDiagnostics() { return {...diagnostics, basisCount:basisCache.size, tableCount:tableCache.size, planCount:planCache.size}; }

function coefficients(shape, bands) {
  const sin = new Float64Array(bands), cos = new Float64Array(bands);
  if (shape && typeof shape === 'object') {
    for (let k = 0; k < bands; k++) {
      sin[k] = shape.sin[k] || 0;
      cos[k] = shape.cos[k] || 0;
    }
  } else {
    if (!['saw', 'square', 'triangle', 'sine'].includes(shape)) throw Error('Unknown target.');
    for (let k = 1; k <= bands; k++) {
      if (shape === 'sine') sin[k-1] = k === 1 ? 1 : 0;
      else if (shape === 'saw' || (shape === 'square' && k % 2)) sin[k-1] = 1/k;
      else if (shape === 'triangle' && k % 2) cos[k-1] = 1/(k*k);
    }
  }
  return {sin, cos};
}

function getTargetBasis() {
  if (targetBasis) return targetBasis;
  targetBasis = new Float64Array(TABLE_SIZE * MAX_H * 2);
  for (let i = 0; i < TABLE_SIZE; i++) {
    const theta = i / TABLE_SIZE * TAU;
    const offset = i * MAX_H * 2;
    for (let k = 1; k <= MAX_H; k++) {
      targetBasis[offset + 2*(k-1)] = Math.sin(k*theta);
      targetBasis[offset + 2*(k-1)+1] = Math.cos(k*theta);
    }
  }
  return targetBasis;
}

function getBasis(note, n) {
  const key = `${note}:${n}`;
  if (basisCache.has(key)) return basisCache.get(key);
  const base = 440 * 2**((note-69)/12);
  const step = base / 48000 * TABLE_SIZE;
  const positions = Float64Array.from({length:n}, (_,i) => (i*step)%TABLE_SIZE);
  const basis = new Float64Array(n * MAX_H * 2);
  for (let i = 0; i < n; i++) {
    const theta = positions[i] / TABLE_SIZE * TAU;
    const offset = i * MAX_H * 2;
    for (let k = 1; k <= MAX_H; k++) {
      basis[offset + 2*(k-1)] = Math.sin(k*theta);
      basis[offset + 2*(k-1)+1] = Math.cos(k*theta);
    }
  }
  const result = {base, step, positions, basis};
  // The production workload uses three pitches with one capture length.
  if (basisCache.size >= 8) basisCache.delete(basisCache.keys().next().value);
  basisCache.set(key, result);
  return result;
}

export function prepareAudio(audio, note) {
  if (!audio || !audio.length || !Number.isFinite(note)) throw Error('Expected a nonempty audio capture and finite MIDI note.');
  const n = audio.length;
  const mean = audio.reduce((sum,x) => sum+x, 0)/n;
  const centered = Float64Array.from(audio, x => x-mean);
  const energy = centered.reduce((sum,x) => sum+x*x, 0);
  if (!Number.isFinite(energy)) throw Error('Audio must contain finite samples.');
  const sampling = getBasis(note,n);
  const moments = new Float64Array(MAX_H*2);
  for (let i = 0; i < n; i++) {
    const value = centered[i], offset = i*MAX_H*2;
    for (let j = 0; j < MAX_H*2; j++) moments[j] += value*sampling.basis[offset+j];
  }
  diagnostics.preparedAudio++;
  return {audio,n,note,mean,centered,energy,moments,...sampling};
}

function getTable(shape, bands) {
  const {sin,cos} = coefficients(shape,bands);
  const key = JSON.stringify([Array.from(sin),Array.from(cos)]);
  if (tableCache.has(key)) return tableCache.get(key);
  const basis = getTargetBasis();
  const table = new Float64Array(TABLE_SIZE);
  for (let i = 0; i < TABLE_SIZE; i++) {
    let y=0;
    const offset=i*MAX_H*2;
    for (let k=0; k<bands; k++) y += sin[k]*basis[offset+2*k]+cos[k]*basis[offset+2*k+1];
    table[i]=y;
  }
  if (table.reduce((sum,x)=>sum+x*x,0)<1e-12) throw Error('Target is silent at this pitch after Nyquist truncation.');
  // Linear interpolation error <= max|f''| * angularStep^2 / 8.
  // Extra roundoff allowance covers the harmonic projection identity.
  let curvature=0;
  for (let k=1;k<=bands;k++) curvature += k*k*Math.hypot(sin[k-1],cos[k-1]);
  const interpolationBound = curvature*(TAU/TABLE_SIZE)**2/8 + 1e-10;
  const result={table,sin,cos,bands,key,interpolationBound};
  if (tableCache.size>=128) tableCache.delete(tableCache.keys().next().value);
  tableCache.set(key,result);
  return result;
}

function getPlan(prepared, shape, h) {
  if (!Number.isInteger(h)||h<1||h>MAX_H) throw Error('Target bandwidth must be 1 through 64 harmonics.');
  const bands=Math.min(h,Math.floor(23999/prepared.base));
  const target=getTable(shape,bands);
  const key=`${prepared.note}:${prepared.n}:${target.key}`;
  if(planCache.has(key))return planCache.get(key);
  const coarseWeights=new Float64Array(128*bands*2);
  const coarseEnergy=new Float64Array(128),coarseMean=new Float64Array(128),bounds=new Float64Array(128);
  const {table,sin,cos}=target,{positions,n}=prepared;
  for(let q=0;q<128;q++){
    const shift=q*256,phi=shift/TABLE_SIZE*TAU;
    for(let k=1;k<=bands;k++){
      const s=Math.sin(k*phi),c=Math.cos(k*phi),offset=(q*bands+k-1)*2;
      coarseWeights[offset]=sin[k-1]*c-cos[k-1]*s;
      coarseWeights[offset+1]=sin[k-1]*s+cos[k-1]*c;
    }
    let sum=0,squares=0;
    for(let i=0;i<n;i++){
      const pos=positions[i]+shift,j=Math.floor(pos),f=pos-j,idx=j&MASK;
      const t=table[idx]*(1-f)+table[(idx+1)&MASK]*f;
      sum+=t;squares+=t*t;
    }
    coarseEnergy[q]=squares-sum*sum/n;
    coarseMean[q]=sum/n;
    bounds[q]=Math.sqrt(n/coarseEnergy[q])*target.interpolationBound;
  }
  const plan={...target,coarseWeights,coarseEnergy,coarseMean,bounds};
  if(planCache.size>=192)planCache.delete(planCache.keys().next().value);
  planCache.set(key,plan);diagnostics.plans++;
  return plan;
}

export function scorePrepared(prepared, shape, h=32, options={}) {
  const {audio,n,note,mean,centered,energy,moments,positions,step,base}=prepared;
  const plan=getPlan(prepared,shape,h);
  const {table,bands}=plan;
  if(energy<1e-12)return {note,score:0,error:1,shift:0,bands,wave:[],target:[]};
  function check(shift,q=-1){
    let dot=0,sum=0,squares=0;
    for(let i=0;i<n;i++){
      const pos=positions[i]+shift,j=Math.floor(pos),f=pos-j,idx=j&MASK;
      const t=table[idx]*(1-f)+table[(idx+1)&MASK]*f;
      dot+=centered[i]*t;
      if(q<0){sum+=t;squares+=t*t;}
    }
    const et=q<0?squares-sum*sum/n:plan.coarseEnergy[q];
    return {score:Math.max(0,Math.min(1,dot/Math.sqrt(energy*et))),scale:dot/energy,shift,targetMean:q<0?sum/n:plan.coarseMean[q]};
  }
  const approximate=new Float64Array(128);
  let bestLower=-Infinity;
  for(let q=0;q<128;q++){
    let dot=0;const offset=q*bands*2;
    for(let j=0;j<bands*2;j++)dot+=moments[j]*plan.coarseWeights[offset+j];
    approximate[q]=Math.max(0,Math.min(1,dot/Math.sqrt(energy*plan.coarseEnergy[q])));
    bestLower=Math.max(bestLower,approximate[q]-plan.bounds[q]);
  }
  let best={score:-1,shift:0};
  for(let q=0;q<128;q++){
    if(approximate[q]+plan.bounds[q]+1e-12<bestLower){diagnostics.coarsePruned++;continue;}
    const value=check(q*256,q);diagnostics.coarseExact++;
    if(value.score>best.score)best=value;
  }
  let left=best.shift-256,right=best.shift+256;
  for(let iteration=0;iteration<28;iteration++){
    const a=left+(right-left)/3,b=right-(right-left)/3,x=check(a),y=check(b);
    diagnostics.fineExact+=2;
    if(x.score>best.score)best=x;
    if(y.score>best.score)best=y;
    if(x.score<y.score)left=a;else right=b;
  }
  const result={note,score:best.score,error:Math.sqrt(Math.max(0,1-best.score**2)),shift:best.shift,bands};
  if(options.preview===false)return result;
  const viewN=Math.min(n,Math.round(2*48000/base));
  function at(pos){const j=Math.floor(pos),f=pos-j,idx=j&MASK;return table[idx]*(1-f)+table[(idx+1)&MASK]*f;}
  result.wave=Array.from({length:512},(_,i)=>{const pos=i/511*(viewN-1),idx=Math.floor(pos),f=pos-idx;return ((audio[idx]*(1-f)+audio[Math.min(idx+1,n-1)]*f)-mean)*best.scale;});
  result.target=Array.from({length:512},(_,i)=>at((i/511*(viewN-1))*step+best.shift)-best.targetMean);
  return result;
}

export function measuredScore(audio,shape,note,h=32){return scorePrepared(prepareAudio(audio,note),shape,h);}
