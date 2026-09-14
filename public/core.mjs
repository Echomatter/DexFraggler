import algorithms from './algorithms.mjs';
import {TARGET_VERSION,coefficients,targetKey} from './targets.mjs';
export { algorithms };
export const MODEL='dexfraggler-pm-48k-ideal-v1';
export const MODEL_HARMONICS=127;
export const TAU=2*Math.PI;
export const LIMITS={coarse:31,fine:99,level:99,detune:14,mode:1};
export const clone=x=>JSON.parse(JSON.stringify(x));
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const low=[0,5,9,13,17,20,23,25,27,29,31,33,35,37,39,41,42,43,45,46];
export function amplitude(level){if(level<=1)return 0;const l=clamp(level,0,99);const s=l>=20?l+28:low[Math.floor(l)]+(l%1)*((low[Math.ceil(l)]??48)-low[Math.floor(l)]);return 2**((s-127)/8)}
export function frequency(op,base=187.5){const log=Math.log2(base);const d=(op.detune-7)*.0209*Math.exp(-.396*log)/7*log;return op.mode?10**((op.coarse%4)+op.fine/100)*2**(Math.max(0,op.detune-7)*13457/16777216):base*(op.coarse===0?.5:op.coarse)*(1+op.fine/100)*2**d}
export function blank(){return {algorithm:32,feedback:0,operators:Array.from({length:6},(_,i)=>({op:i+1,coarse:1,fine:0,detune:7,mode:0,level:i===0?99:0}))}}
export function validatePatch(p){
  if(!p||Object.keys(p).some(k=>!['algorithm','feedback','operators'].includes(k))||!Number.isInteger(p.algorithm)||p.algorithm<1||p.algorithm>32||!Number.isInteger(p.feedback)||p.feedback<0||p.feedback>7||!Array.isArray(p.operators)||p.operators.length!==6)throw Error('A patch needs an algorithm (1–32), feedback (0–7) and six operators.');
  const ids=new Set(),allowed=['op',...Object.keys(LIMITS)];
  const operators=p.operators.map(o=>{
    if(!o||Object.keys(o).some(k=>!allowed.includes(k))||!Number.isInteger(o.op)||o.op<1||o.op>6||ids.has(o.op))throw Error('Operators need unique op numbers (1–6) and the canonical DX7 fields.');
    ids.add(o.op);const v={op:o.op,coarse:o.coarse,fine:o.fine,detune:o.detune,mode:o.mode,level:o.level};
    for(const [k,max] of Object.entries(LIMITS))if(!Number.isInteger(v[k])||v[k]<0||v[k]>max)throw Error(`Operator ${o.op}: invalid ${k}.`);
    return v;
  }).sort((a,b)=>a.op-b.op);
  return {algorithm:p.algorithm,feedback:p.feedback,operators};
}
const K=TAU*2;
const topology=algorithms.map(spec=>{
  const sources=Array.from({length:6},()=>[]);
  for(const [s,t] of spec.edges)sources[t].push(s);
  const closure=bits=>{let previous;do{previous=bits;for(let i=0;i<6;i++)if(bits&(1<<i))for(const s of sources[i])bits|=1<<s}while(bits!==previous);return bits};
  const warmMask=closure(1<<spec.feedback[0]);
  return {...spec,sources,warmMask};
});


export function render(p,n=1024,base=187.5,parts=false){
  const spec=topology[p.algorithm-1],a=p.operators.map(o=>amplitude(o.level));
  const w=new Float64Array(6),phase=new Float64Array(6);
  const inc=p.operators.map(o=>TAU*frequency(o,base)/48000);
  const output=new Float64Array(n),components=parts?spec.carriers.map(()=>new Float64Array(n)):null;
  const warm=p.feedback?4096:1024,gain=p.feedback?2**(p.feedback-8-(spec.special?2:0)):0;
  let prev=0,older=0;
  for(let t=-warm;t<n;t++){
    for(let i=5;i>=0;i--){
      let angle=phase[i];phase[i]=(phase[i]+inc[i])%TAU;
      if(t<0&&(!gain||!(spec.warmMask&(1<<i))))continue;
      for(const j of spec.sources[i])angle+=K*a[j]*w[j];
      if(i===spec.feedback[1])angle+=gain*K*a[spec.feedback[0]]*(prev+older)*.5;
      w[i]=Math.sin(angle);
    }
    older=prev;prev=w[spec.feedback[0]];
    if(t>=0)for(let c=0;c<spec.carriers.length;c++){
      const i=spec.carriers[c];output[t]+=a[i]*w[i];if(components)components[c][t]=w[i];
    }
  }
  return parts?{wave:output,components,carriers:spec.carriers}:output;
}


export function amplitudeDerivative(level){
  if(level<=1||level>99)return 0;
  const slope=level>=20?1:(low[Math.floor(level)+1]??48)-low[Math.floor(level)];
  return amplitude(level)*Math.LN2/8*slope;
}

/** Exact forward-mode six-level derivatives of the smooth PM model. The
 * feedback tangent carries the same two delayed samples as the waveform.
 * Warmup evaluates only operators that feed the feedback loop, while advancing
 * every phase with the identical per-sample recurrence used by render().
 */
export function renderWithLevelJacobian(p,n=1024,base=187.5){
  const spec=topology[p.algorithm-1],{sources,carriers}=spec;
  const a=Float64Array.from(p.operators,o=>amplitude(o.level));
  const da=Float64Array.from(p.operators,o=>amplitudeDerivative(o.level));
  const phase=new Float64Array(6),w=new Float64Array(6),dw=new Float64Array(36);
  const inc=Float64Array.from(p.operators,o=>TAU*frequency(o,base)/48000);
  const wave=new Float64Array(n),jacobian=Array.from({length:6},()=>new Float64Array(n));
  const delayed=new Float64Array(6),olderD=new Float64Array(6);
  const warm=p.feedback?4096:1024,fs=spec.feedback[0],ft=spec.feedback[1];
  const gain=p.feedback?2**(p.feedback-8-(spec.special?2:0)):0;
  const fbFactor=gain*K*.5;
  let prev=0,older=0,finite=true;
  for(let t=-warm;t<n;t++){
    for(let i=5;i>=0;i--){
      const angle0=phase[i];
      phase[i]=(phase[i]+inc[i])%TAU;
      if(t<0&&(!gain||!(spec.warmMask&(1<<i))))continue;
      let angle=angle0;
      const off=i*6;
      for(let j=0;j<6;j++)dw[off+j]=0;
      for(const s of sources[i]){
        angle+=K*a[s]*w[s];
        const so=s*6,factor=K*a[s];
        for(let j=0;j<6;j++)dw[off+j]+=factor*dw[so+j];
        dw[off+s]+=K*da[s]*w[s];
      }
      if(i===ft){
        // Preserve operation ordering in render() for waveform equivalence.
        angle+=gain*K*a[fs]*(prev+older)*.5;
        for(let j=0;j<6;j++)dw[off+j]+=fbFactor*a[fs]*(delayed[j]+olderD[j]);
        dw[off+fs]+=fbFactor*da[fs]*(prev+older);
      }
      w[i]=Math.sin(angle);
      const cosine=Math.cos(angle);
      for(let j=0;j<6;j++)dw[off+j]*=cosine;
    }
    if(gain){
      older=prev;prev=w[fs];
      for(let j=0;j<6;j++){olderD[j]=delayed[j];delayed[j]=dw[fs*6+j]}
    }
    if(t>=0)for(const i of carriers){
      wave[t]+=a[i]*w[i];
      for(let j=0;j<6;j++)jacobian[j][t]+=a[i]*dw[i*6+j];
      jacobian[i][t]+=da[i]*w[i];
    }
  }
  // Strong nonlinear feedback may have an unbounded tangent even when its
  // waveform is bounded. Do not feed nonfinite normal equations to the solver.
  for(const column of jacobian)for(const x of column)if(!Number.isFinite(x)){finite=false;break}
  return {wave,jacobian,finite};
}


export function fft(real,imag,inverse=false){const n=real.length;for(let i=1,j=0;i<n;i++){let b=n>>1;for(;j&b;b>>=1)j^=b;j^=b;if(i<j){[real[i],real[j]]=[real[j],real[i]];[imag[i],imag[j]]=[imag[j],imag[i]]}}for(let len=2;len<=n;len<<=1){const angle=(inverse?TAU:-TAU)/len;const wr0=Math.cos(angle),wi0=Math.sin(angle);for(let start=0;start<n;start+=len){let wr=1,wi=0;for(let j=0;j<len/2;j++){const a=start+j,b=a+len/2,tr=wr*real[b]-wi*imag[b],ti=wr*imag[b]+wi*real[b];real[b]=real[a]-tr;imag[b]=imag[a]-ti;real[a]+=tr;imag[a]+=ti;const next=wr*wr0-wi*wi0;wi=wr*wi0+wi*wr0;wr=next}}}if(inverse)for(let i=0;i<n;i++){real[i]/=n;imag[i]/=n}}
const targetCache=new Map();
function requireTarget(target){if(target?.kind!==TARGET_VERSION)throw Error('Use an ideal waveform target.');targetKey(target);return target}
export function targetWave(target,harmonics=MODEL_HARMONICS,n=1024,base=187.5,phase=0){
  requireTarget(target);
  if(!Number.isInteger(harmonics)||harmonics<1||!Number.isFinite(base)||base<=0)throw Error('Invalid model projection.');
  const bands=Math.min(harmonics,Math.ceil(24000/base)-1);
  const {sin,cos}=coefficients(target,bands);
  return Float64Array.from({length:n},(_,i)=>{let value=0;const theta=TAU*base*i/48000+phase;for(let k=1;k<=bands;k++){value+=sin[k-1]*Math.sin(k*theta);if(cos[k-1])value+=cos[k-1]*Math.cos(k*theta)}return value});
}
function targetInfo(target,h,n){
  const key=[targetKey(requireTarget(target)),h,n].join(':');
  if(!targetCache.has(key)){
    const wave=targetWave(target,h,n),re=Float64Array.from(wave),im=new Float64Array(n);
    const energy=wave.reduce((a,b)=>a+b*b,0);fft(re,im);
    const magnitude=Float64Array.from(re,(x,k)=>Math.hypot(x,im[k])/Math.sqrt(energy));
    if(targetCache.size>=128)targetCache.delete(targetCache.keys().next().value);
    targetCache.set(key,{wave,re,im,energy,magnitude});
  }
  return targetCache.get(key);
}
/** Prepare the exact model objective once for any number of targets. The
 * returned arrays belong to this context; callers must treat them as read-only.
 * This retains every FFT bin, sample, and the existing 127-harmonic objective. */
export function prepareModelWave(wave){
  const n=wave.length,mean=wave.reduce((a,b)=>a+b,0)/n;
  const centered=Float64Array.from(wave,x=>x-mean),energy=centered.reduce((a,b)=>a+b*b,0);
  const re=Float64Array.from(centered),im=new Float64Array(n),magnitude=new Float64Array(n);
  if(energy>=1e-16){fft(re,im);for(let k=0;k<n;k++)magnitude[k]=Math.hypot(re[k],im[k])/Math.sqrt(energy)}
  return {n,energy,re,im,magnitude};
}
export function analyzePreparedModel(prepared,target,h=MODEL_HARMONICS){
  const {n,energy,re,im,magnitude}=prepared,t=targetInfo(target,h,n);
  if(energy<1e-16)return {score:0,error:1,spectralError:1,loss:1,shift:0,scale:0};
  const cr=new Float64Array(n),ci=new Float64Array(n);let spectral=0;
  for(let k=0;k<n;k++){
    cr[k]=re[k]*t.re[k]+im[k]*t.im[k];ci[k]=im[k]*t.re[k]-re[k]*t.im[k];
    spectral+=(magnitude[k]-t.magnitude[k])**2;
  }
  fft(cr,ci,true);let shift=0,corr=-Infinity;
  for(let i=0;i<n;i++)if(cr[i]>corr){corr=cr[i];shift=i}
  const score=clamp(corr/Math.sqrt(energy*t.energy),0,1),error=Math.sqrt(Math.max(0,1-score*score));
  return {score,error,spectralError:Math.sqrt(spectral/n),loss:.85*error*error+.15*spectral/n,shift,scale:corr/energy};
}
export function analyze(wave,target,h=MODEL_HARMONICS){return analyzePreparedModel(prepareModelWave(wave),target,h)}
export function analyzeMany(wave,targets,h=MODEL_HARMONICS){
  const prepared=prepareModelWave(wave);return targets.map(target=>analyzePreparedModel(prepared,target,h));
}
export function evaluate(p,target,h=MODEL_HARMONICS){return {patch:clone(p),...analyze(render(p),target,h)}}
export function display(p,target,h=MODEL_HARMONICS){const w=render(p),m=analyze(w,target,h);const reference=targetInfo(target,h,w.length).wave,re=new Float64Array(w),im=new Float64Array(w.length);fft(re,im);let e=w.reduce((s,x)=>s+x*x,0);return {...m,wave:Array.from({length:512},(_,i)=>w[(i+m.shift)%w.length]*m.scale),target:Array.from(reference.slice(0,512)),harmonics:Array.from({length:32},(_,i)=>Math.hypot(re[4*(i+1)],im[4*(i+1)])/Math.sqrt(Math.max(e,1e-20)*w.length/2))}}
function random(state){let x=state.rng|0;x^=x<<13;x^=x>>>17;x^=x<<5;state.rng=x>>>0;return state.rng/4294967296}
function pick(state,list){return list[Math.floor(random(state)*list.length)]}
function nearestRatio(r){let best=[1,0],distance=Infinity;for(let c=0;c<=31;c++){const b=c||.5;const f=clamp(Math.round((r/b-1)*100),0,99);const d=Math.abs(b*(1+f/100)-r);if(d<distance){distance=d;best=[c,f]}}return best}
export function interpolate(a,b,f){a=validatePatch(a);b=validatePatch(b);if(a.algorithm!==b.algorithm||a.feedback!==b.feedback)throw Error('Choose two patches with the same algorithm and feedback.');if(!Number.isFinite(f)||f<0||f>1)throw Error('Blend must be between zero and one.');if(f===0)return clone(a);if(f===1)return clone(b);if(JSON.stringify(a)===JSON.stringify(b))return clone(a);const p=clone(a);p.operators.forEach((o,i)=>{const x=b.operators[i];if(o.mode!==x.mode)throw Error('Oscillator modes must agree.');const hz=frequency(o)*(1-f)+frequency(x)*f;if(o.mode){const log=clamp(Math.round(Math.log10(hz)*100),0,399);o.coarse=Math.floor(log/100);o.fine=log%100;o.detune=7}else{[o.coarse,o.fine]=nearestRatio(hz/187.5);o.detune=7}const amp=amplitude(o.level)*(1-f)+amplitude(x.level)*f;let best=0,dist=Infinity;for(let l=0;l<=99;l++){const d=Math.abs(amplitude(l)-amp);if(d<dist){best=l;dist=d}}o.level=best});return validatePatch(p)}
const profileCache=new Map();
function profile(target){
  const key=targetKey(requireTarget(target));if(profileCache.has(key))return profileCache.get(key);
  const {sin,cos}=coefficients(target,MODEL_HARMONICS),positive=[];let even=0,total=0;
  for(let i=0;i<sin.length;i++){
    const energy=sin[i]**2+cos[i]**2;total+=energy;if((i+1)%2===0)even+=energy;
    // DX7 carriers have nonnegative gains and no independent phase parameter.
    // Negative Fourier coefficients therefore cannot be copied as carrier
    // amplitudes; leave them for PM and feedback optimization.
    if(sin[i]>1e-12&&i<31)positive.push({harmonic:i+1,amplitude:sin[i]});
  }
  positive.sort((a,b)=>b.amplitude-a.amplitude||a.harmonic-b.harmonic);
  const result={positive,oddOnly:even<=total*1e-10};
  if(profileCache.size>=128)profileCache.clear();profileCache.set(key,result);return result;
}
function nearestLevel(gain){let best=0,distance=Infinity;for(let level=0;level<=99;level++){const delta=Math.abs(amplitude(level)-gain);if(delta<distance){distance=delta;best=level}}return best}
function carrierSeed(target,algorithm){
  const p=blank(),spec=algorithms[algorithm-1],harmonics=profile(target).positive;p.algorithm=algorithm;p.operators.forEach(o=>o.level=0);
  const scale=harmonics[0]?.amplitude??1;
  spec.carriers.forEach((op,i)=>{const harmonic=harmonics[i];if(harmonic){p.operators[op].coarse=harmonic.harmonic;p.operators[op].level=nearestLevel(harmonic.amplitude/scale)}});
  if(!harmonics.length)p.operators[spec.carriers[0]].level=99;
  return p;
}
function pathTo(spec,start,predicate,visited=new Set()){
  if(predicate(start))return [start];if(visited.has(start))return null;visited.add(start);
  for(const [source,destination] of spec.edges)if(source===start){const tail=pathTo(spec,destination,predicate,visited);if(tail)return [start,...tail]}
  return null;
}
/** Fresh mathematical seeds derived from the target and this row's topology.
 * These are proposals, not substitutes for objective/native measurement. */
export function harmonicSeeds(target,algorithm){
  requireTarget(target);if(!Number.isInteger(algorithm)||algorithm<1||algorithm>32)throw Error('Choose an algorithm from 1 through 32.');
  const spec=algorithms[algorithm-1],base=blank();base.algorithm=algorithm;
  const seeds=[base,carrierSeed(target,algorithm)];
  const edge=spec.edges.find(([,destination])=>spec.carriers.includes(destination));
  if(edge)for(const ratio of profile(target).oddOnly?[2,4]:[1,2])for(const level of [60,76]){
    const p=blank();p.algorithm=algorithm;p.operators.forEach(o=>o.level=0);
    p.operators[edge[1]].level=99;p.operators[edge[0]].level=level;p.operators[edge[0]].coarse=ratio;seeds.push(p);
  }
  const [source,destination]=spec.feedback;
  const loop=pathTo(spec,destination,op=>op===source)??[source];
  const output=pathTo(spec,source,op=>spec.carriers.includes(op))??[source];
  for(let feedback=1;feedback<=7;feedback++){
    const p=blank();p.algorithm=algorithm;p.feedback=feedback;p.operators.forEach(o=>o.level=0);
    for(const op of new Set([...loop,...output])){p.operators[op].level=spec.carriers.includes(op)?99:60;p.operators[op].coarse=spec.carriers.includes(op)?1:profile(target).oddOnly?2:1}
    seeds.push(p);
  }
  return [...new Map(seeds.map(p=>[JSON.stringify(p),p])).values()];
}
function proposal(state){
  const v=state.seedCursor??0;let p;
  if(v<64||random(state)<.22){
    state.seedCursor=v+1;p=blank();p.algorithm=state.algorithm;p.feedback=v%8;
    const spec=algorithms[p.algorithm-1],targetProfile=profile(state.shape);
    if(p.algorithm===32){
      p=carrierSeed(state.shape,state.algorithm);p.feedback=v%8;
      for(const o of p.operators)if(o.level)o.level=clamp(o.level+pick(state,[-4,-2,0,0,2,4]),0,99);
      if(v%3===0)p.operators[5].level=pick(state,[0,45,60,75,87,99]);
    }else for(const o of p.operators){
      const carrier=spec.carriers.includes(o.op-1);
      o.level=carrier?pick(state,[75,87,99]):pick(state,[0,45,60,70,80]);
      o.coarse=carrier?pick(state,[1,1,1,2,3]):pick(state,targetProfile.oddOnly?[2,2,4,6,8]:[1,1,2,3,4,5,7]);
    }
  }else{
    const pool=random(state)<.7?state.elites.slice(0,4):state.elites;p=clone(pick(state,pool).patch);
    if(random(state)<.1&&pool.length>1){const b=pick(state,pool).patch;if(b.feedback===p.feedback)p=interpolate(p,b,random(state))}
    const o=pick(state,p.operators),r=random(state);
    if(r<.55)o.level=clamp(o.level+pick(state,[-16,-8,-4,-2,-1,1,2,4,8,16]),0,99);
    else if(r<.76)o.coarse=pick(state,[0,1,1,2,3,4,5,6,7,8,9,11,13,15,17,23,31]);
    else if(r<.89)o.fine=clamp(o.fine+pick(state,[-10,-2,-1,1,2,10]),0,99);
    else if(r<.96)p.feedback=pick(state,[0,1,2,3,4,5,6,7]);
    else if(state.allowDetune)o.detune=pick(state,[0,4,6,7,8,10,14]);
    else o.level=clamp(o.level+pick(state,[-1,1]),0,99);
  }
  return p;
}
function solveLinear(A,b){
  const n=b.length,M=A.map((row,i)=>[...row,b[i]]);
  for(let i=0;i<n;i++){
    let pivot=i;for(let j=i+1;j<n;j++)if(Math.abs(M[j][i])>Math.abs(M[pivot][i]))pivot=j;
    [M[i],M[pivot]]=[M[pivot],M[i]];
    const d=M[i][i];if(!Number.isFinite(d)||Math.abs(d)<1e-20)return null;
    for(let k=i;k<=n;k++)M[i][k]/=d;
    for(let j=0;j<n;j++)if(j!==i){const q=M[j][i];for(let k=i;k<=n;k++)M[j][k]-=q*M[i][k]}
  }
  const result=M.map(row=>row[n]);return result.every(Number.isFinite)?result:null;
}


export function fitLevels(p,shape,h=MODEL_HARMONICS){
  p=clone(p);
  const {wave,jacobian:J,finite}=renderWithLevelJacobian(p);
  if(!finite)return p;
  const m=analyze(wave,shape,h),target=targetInfo(shape,h,wave.length).wave,n=wave.length;
  if(m.scale<=1e-12)return p;
  let mean=0,energy=0;
  for(const x of wave)mean+=x/n;
  const centered=Float64Array.from(wave,x=>x-mean);
  for(const x of centered)energy+=x*x;
  const res=Float64Array.from(centered,(x,i)=>x*m.scale-target[(i-m.shift+n)%n]);
  for(let j=0;j<6;j++){
    let dMean=0;for(const x of J[j])dMean+=x/n;
    let parallel=0;for(let i=0;i<n;i++)parallel+=centered[i]*(J[j][i]-dMean);
    parallel/=Math.max(energy,1e-20);
    for(let i=0;i<n;i++)J[j][i]=m.scale*(J[j][i]-dMean-centered[i]*parallel);
  }
  const A=Array.from({length:6},()=>Array(6).fill(0)),b=Array(6).fill(0);
  let maxDiagonal=0;
  for(let i=0;i<6;i++){
    for(let j=0;j<=i;j++){let value=0;for(let k=0;k<n;k++)value+=J[i][k]*J[j][k];A[i][j]=A[j][i]=value/n}
    for(let k=0;k<n;k++)b[i]-=J[i][k]*res[k]/n;
    maxDiagonal=Math.max(maxDiagonal,A[i][i]);
  }
  if(!Number.isFinite(maxDiagonal)||maxDiagonal<1e-20)return p;
  // A fixed level-space ridge retains useful movement for weakly coupled
  // columns; purely diagonal damping over-amplified near-null directions in
  // comparisons. The shared trust radius preserves the solved direction.
  for(let i=0;i<6;i++)A[i][i]+=.0005;
  const delta=solveLinear(A,b);
  if(delta){
    const length=Math.max(1,...delta.map(x=>Math.abs(x)/8));
    p.operators.forEach((o,i)=>{o.level=clamp(Math.round(o.level+delta[i]/length),0,99)});
  }
  return p;
}

export function fitCarriers(p,shape,h=MODEL_HARMONICS){p=clone(p);const spec=algorithms[p.algorithm-1];const free=spec.carriers.filter(i=>!(p.feedback&&i===spec.feedback[0])&&!spec.edges.some(([s])=>s===i));if(!free.length)return p;const data=render(p,1024,187.5,true),m=analyze(data.wave,shape,h),target=targetInfo(shape,h,1024).wave;let weights=spec.carriers.map(i=>amplitude(p.operators[i].level));const desired=Float64Array.from(target,(_,i)=>target[(i-m.shift+1024)%1024]/Math.max(m.scale,1e-8));for(let pass=0;pass<5;pass++)for(const op of free){const c=spec.carriers.indexOf(op),basis=data.components[c];let numerator=0,denominator=0;for(let i=0;i<1024;i++){let residual=desired[i];for(let j=0;j<weights.length;j++)if(j!==c)residual-=weights[j]*data.components[j][i];numerator+=basis[i]*residual;denominator+=basis[i]*basis[i]}weights[c]=clamp(numerator/Math.max(denominator,1e-10),0,1)}for(const op of free){const weight=weights[spec.carriers.indexOf(op)];let best=0,dist=Infinity;for(let l=0;l<=99;l++){const d=Math.abs(amplitude(l)-weight);if(d<dist){dist=d;best=l}}p.operators[op].level=best}return p}
export function initialState(target,seeds=[],h=MODEL_HARMONICS,algorithm){
  requireTarget(target);
  if(!Array.isArray(seeds)||seeds.length)throw Error('A fresh optimizer starts from mathematical seeds only.');
  if(h!==MODEL_HARMONICS)throw Error('The model uses all 127 harmonics below Nyquist.');
  if(!Number.isInteger(algorithm)||algorithm<1||algorithm>32)throw Error('Choose an algorithm from 1 through 32.');
  let rng=2166136261;for(const ch of `${targetKey(target)}:${algorithm}`){rng^=ch.charCodeAt(0);rng=Math.imul(rng,16777619)}
  const state={model:MODEL,shape:clone(target),algorithm,harmonics:h,evaluations:0,seedCursor:0,rng:rng>>>0||1,elites:[],history:[],allowDetune:false,method:'Harmonic initialization'};
  for(const patch of harmonicSeeds(target,algorithm))consider(state,evaluate(patch,target,h));
  return state;
}
function consider(state,item){state.evaluations++;const prev=state.elites[0]?.loss??Infinity;const key=JSON.stringify(item.patch);if(!state.elites.some(x=>JSON.stringify(x.patch)===key)){state.elites.push(item);state.elites.sort((a,b)=>a.loss-b.loss);state.elites=state.elites.slice(0,16)}if(item.loss<prev){state.history.push({at:state.evaluations,error:item.error,score:item.score,time:Date.now()});state.history=state.history.slice(-120)}return item.loss<prev}
export function runBatch(state,budgetMs=600){
  if(state?.model!==MODEL||state.harmonics!==MODEL_HARMONICS||!Number.isInteger(state.algorithm)||state.algorithm<1||state.algorithm>32||!Array.isArray(state.elites)||!state.elites.length||state.elites.some(e=>e.patch?.algorithm!==state.algorithm))throw Error('Use a current optimizer for one algorithm row.');
  requireTarget(state.shape);state=clone(state);const until=performance.now()+clamp(budgetMs,10,5000);
  do{const count=state.evaluations;let p;if(count%17===0){state.method='Damped least squares';p=fitLevels(pick(state,state.elites.slice(0,4)).patch,state.shape,state.harmonics)}else if(count%11===0){state.method='Carrier least squares';p=fitCarriers(pick(state,state.elites.slice(0,4)).patch,state.shape,state.harmonics)}else{state.method=state.seedCursor<64?'Harmonic exploration':'Discrete refinement';p=proposal(state)}consider(state,evaluate(p,state.shape,state.harmonics))}while(performance.now()<until);
  return state;
}
export function sysex(p,name='DEXFRAG'){p=validatePatch(p);const data=[];for(const o of [...p.operators].reverse())data.push(99,99,99,99,99,99,99,0,39,0,0,0,0,0,0,0,o.level,o.mode,o.coarse,o.fine,o.detune);data.push(99,99,99,99,50,50,50,50,p.algorithm-1,p.feedback,1,0,0,0,0,0,4,0,24);const nm=name.replace(/[^\x20-\x7e]/g,' ').slice(0,10).padEnd(10);data.push(...Array.from(nm,x=>x.charCodeAt(0)));return new Uint8Array([240,67,0,0,1,27,...data,(-data.reduce((a,b)=>a+b,0))&127,247])}
export function fromSysex(bytes){const b=Array.from(bytes);if(b.length!==163||b[0]!==240||b[1]!==67||b[2]>15||b[161]>127||b[3]!==0||b[4]!==1||b[5]!==27||b.at(-1)!==247)throw Error('Import a DX7 single-voice .syx (163 bytes).');const d=b.slice(6,161);if(d.some(x=>x>127)||((d.reduce((a,x)=>a+x,0)+b[161])&127))throw Error('Invalid Yamaha checksum.');return validatePatch({algorithm:d[134]+1,feedback:d[135],operators:Array.from({length:6},(_,i)=>{const j=(5-i)*21;return {op:i+1,level:d[j+16],mode:d[j+17],coarse:d[j+18],fine:d[j+19],detune:d[j+20]}})})}
