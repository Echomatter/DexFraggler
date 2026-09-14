import {METRIC_VERSION,coefficients,nyquistHarmonics,projectionInfo,sample,targetKey} from '../public/targets.mjs';

const TAU=2*Math.PI,SAMPLE_RATE=48000,SCORE_TOLERANCE=1e-10,ROUNDING_ALLOWANCE=1e-11;
export {METRIC_VERSION};
const basisCache=new Map(),planCache=new Map();
const diagnostics={preparedAudio:0,plans:0,phaseEvaluations:0,subdivisions:0};
export function scoringDiagnostics(){return {...diagnostics,basisCount:basisCache.size,planCount:planCache.size};}
function remember(cache,key,value,limit){if(cache.size>=limit)cache.delete(cache.keys().next().value);cache.set(key,value);return value;}
function powerOfTwo(n){let result=1;while(result<n)result*=2;return result;}

// c[k] cos(k phi) + s[k] sin(k phi), including c[0].
function squareSeries(c,s){
  const h=c.length-1,cos=new Float64Array(2*h+1),sin=new Float64Array(2*h+1);
  cos[0]=c[0]*c[0];
  for(let k=1;k<=h;k++){cos[k]+=2*c[0]*c[k];sin[k]+=2*c[0]*s[k];}
  for(let k=1;k<=h;k++)for(let j=1;j<=h;j++){
    const d=k-j,a=c[k]*c[j],b=s[k]*s[j];
    cos[Math.abs(d)]+=(a+b)/2;cos[k+j]+=(a-b)/2;
    sin[k+j]+=(c[k]*s[j]+s[k]*c[j])/2;
    if(d)sin[Math.abs(d)]+=Math.sign(d)*(s[k]*c[j]-c[k]*s[j])/2;
  }
  return {cos,sin};
}
function inverseFft(real,imag){
  const n=real.length;
  for(let i=1,j=0;i<n;i++){let bit=n>>1;for(;j&bit;bit>>=1)j^=bit;j^=bit;if(i<j){[real[i],real[j]]=[real[j],real[i]];[imag[i],imag[j]]=[imag[j],imag[i]];}}
  for(let length=2;length<=n;length*=2){
    const wr0=Math.cos(TAU/length),wi0=Math.sin(TAU/length);
    for(let start=0;start<n;start+=length){let wr=1,wi=0;
      for(let j=0;j<length/2;j++){
        const a=start+j,b=a+length/2,tr=wr*real[b]-wi*imag[b],ti=wr*imag[b]+wi*real[b];
        real[b]=real[a]-tr;imag[b]=imag[a]-ti;real[a]+=tr;imag[a]+=ti;
        const next=wr*wr0-wi*wi0;wi=wr*wi0+wi*wr0;wr=next;
      }
    }
  }
  for(let i=0;i<n;i++)real[i]/=n;
  return real;
}
function onGrid(c,s,n){
  const real=new Float64Array(n),imag=new Float64Array(n);real[0]=n*c[0];
  for(let k=1;k<c.length;k++){
    if(k===n/2){real[k]=n*c[k];continue;}
    real[k]=real[n-k]=n*c[k]/2;imag[k]=-n*s[k]/2;imag[n-k]=n*s[k]/2;
  }
  return inverseFft(real,imag);
}
function bounds(c,s){let a0=Math.abs(c[0]),a1=0,a2=0;for(let k=1;k<c.length;k++){const a=Math.hypot(c[k],s[k]);a0+=a;a1+=k*a;a2+=k*k*a;}return [a0,a1,a2];}

function samplingFor(note,n){
  const key=`${note}:${n}`;if(basisCache.has(key))return basisCache.get(key);
  const base=440*2**((note-69)/12),bands=nyquistHarmonics(base,SAMPLE_RATE);
  if(bands>4096)throw Error('This analysis pitch is below the supported native range.');
  const step=TAU*base/SAMPLE_RATE,basis=new Float64Array(n*bands*2);
  const sinSum=new Float64Array(2*bands+1),cosSum=new Float64Array(2*bands+1);cosSum[0]=n;
  for(let i=0;i<n;i++){
    const theta=i*step,ds=Math.sin(theta),dc=Math.cos(theta);let s=0,c=1;
    for(let k=1;k<=2*bands;k++){
      const next=s*dc+c*ds;c=c*dc-s*ds;s=next;
      sinSum[k]+=s;cosSum[k]+=c;
      if(k<=bands){const offset=(k-1)*2*n+i;basis[offset]=s;basis[offset+n]=c;}
    }
  }
  return remember(basisCache,key,{base,bands,step,basis,sinSum,cosSum},8);
}
export function prepareAudio(audio,note){
  if(!audio||audio.length<3||!Number.isFinite(note))throw Error('Expected at least three finite audio samples and a MIDI note.');
  const n=audio.length,mean=audio.reduce((sum,x)=>sum+x,0)/n,centered=Float64Array.from(audio,x=>x-mean),energy=centered.reduce((sum,x)=>sum+x*x,0);
  if(!Number.isFinite(energy))throw Error('Audio must contain finite samples.');
  const sampling=samplingFor(note,n),moments=new Float64Array(sampling.bands*2);
  // Store one contiguous vector per basis function. Accumulate each dot product
  // in a scalar instead of reading/writing the moments array for every sample.
  // Sample order is unchanged, so this does not change floating-point sums.
  const basis=sampling.basis;let j=0;
  for(;j+3<moments.length;j+=4){
    const a=j*n,b=a+n,c=b+n,d=c+n;let sa=0,sb=0,sc=0,sd=0;
    for(let i=0;i<n;i++){const value=centered[i];sa+=value*basis[a+i];sb+=value*basis[b+i];sc+=value*basis[c+i];sd+=value*basis[d+i];}
    moments[j]=sa;moments[j+1]=sb;moments[j+2]=sc;moments[j+3]=sd;
  }
  for(;j<moments.length;j++){const offset=j*n;let sum=0;for(let i=0;i<n;i++)sum+=centered[i]*basis[offset+i];moments[j]=sum;}
  diagnostics.preparedAudio++;
  return {audio,n,note,mean,centered,energy,moments,...sampling};
}
function planFor(prepared,target){
  const key=`${prepared.note}:${prepared.n}:${targetKey(target)}`;if(planCache.has(key))return planCache.get(key);
  const {bands:h,n,sinSum,cosSum}=prepared,{sin:b}=coefficients(target,h);
  const zeros=new Float64Array(h+1),series=Float64Array.from([0,...b]);
  const squared=squareSeries(zeros,series),meanC=new Float64Array(h+1),meanS=new Float64Array(h+1);
  for(let k=1;k<=h;k++){meanC[k]=b[k-1]*sinSum[k];meanS[k]=b[k-1]*cosSum[k];}
  const meanSquared=squareSeries(meanC,meanS),energyC=new Float64Array(2*h+1),energyS=new Float64Array(2*h+1);
  for(let k=0;k<=2*h;k++){
    energyC[k]=squared.cos[k]*cosSum[k]-meanSquared.cos[k]/n;
    energyS[k]=-squared.cos[k]*sinSum[k]-meanSquared.sin[k]/n;
  }
  const energyBounds=bounds(energyC,energyS);
  let gridSize=powerOfTwo(Math.max(128,4*h)),energyGrid=onGrid(energyC,energyS,gridSize);
  // The interpolation remainder supplies a lower bound between grid samples.
  let energyMinimum=Math.min(...energyGrid)-energyBounds[2]*(TAU/gridSize)**2/8;
  while(energyMinimum<=1e-12&&gridSize<65536){gridSize*=2;energyGrid=onGrid(energyC,energyS,gridSize);energyMinimum=Math.min(...energyGrid)-energyBounds[2]*(TAU/gridSize)**2/8;}
  if(energyMinimum<=1e-12)throw Error('The capture is too short for a nondegenerate phase comparison at this pitch.');
  const plan={b,meanC,meanS,energyC,energyS,energyBounds,energyMinimum,gridSize,energyGrid,projection:projectionInfo(target,prepared.base,SAMPLE_RATE)};
  diagnostics.plans++;return remember(planCache,key,plan,128);
}

class MaxHeap{
  constructor(){this.items=[];}
  get top(){return this.items[0];}
  push(value){let i=this.items.length;this.items.push(value);while(i){const parent=(i-1)>>1;if(this.items[parent].upper>=value.upper)break;this.items[i]=this.items[parent];i=parent;}this.items[i]=value;}
  pop(){const result=this.items[0],last=this.items.pop();if(this.items.length){let i=0;while(2*i+1<this.items.length){let child=2*i+1;if(child+1<this.items.length&&this.items[child+1].upper>this.items[child].upper)child++;if(this.items[child].upper<=last.upper)break;this.items[i]=this.items[child];i=child;}this.items[i]=last;}return result;}
}

export function scorePrepared(prepared,target,options={}){
  if(!options||typeof options!=='object'||Array.isArray(options)||Object.keys(options).some(key=>key!=='preview')||('preview' in options&&typeof options.preview!=='boolean'))throw Error('Scoring options only support a preview flag; bandwidth is automatic.');
  const {preview=true}=options;
  const {audio,n,note,mean,energy,moments,bands:h,step,base}=prepared,plan=planFor(prepared,target);
  const metadata={note,bands:h,metricVersion:METRIC_VERSION,sampleRate:SAMPLE_RATE,retainedIdealEnergy:plan.projection.retainedEnergy};
  if(energy<1e-12)return {...metadata,score:0,error:1,phase:0,...(preview?{wave:[],target:[],idealTarget:[]}:{})};
  const audioNorm=Math.sqrt(energy),dotC=new Float64Array(h+1),dotS=new Float64Array(h+1);
  for(let k=1;k<=h;k++){dotC[k]=plan.b[k-1]*moments[(k-1)*2]/audioNorm;dotS[k]=plan.b[k-1]*moments[(k-1)*2+1]/audioNorm;}
  function at(phase,derivatives=false){
    const ds=Math.sin(phase),dc=Math.cos(phase);let s=0,c=1,dot=0,e=plan.energyC[0],dp=0,dpp=0,ep=0,epp=0;
    for(let k=1;k<=2*h;k++){
      const next=s*dc+c*ds;c=c*dc-s*ds;s=next;
      const ec=plan.energyC[k],es=plan.energyS[k],ev=ec*c+es*s;e+=ev;
      if(derivatives){ep+=k*(-ec*s+es*c);epp-=k*k*ev;}
      if(k<=h){const v=dotC[k]*c+dotS[k]*s;dot+=v;
        if(derivatives){dp+=k*(-dotC[k]*s+dotS[k]*c);dpp-=k*k*v;}}
    }
    diagnostics.phaseEvaluations++;return {phase,score:dot/Math.sqrt(e),dot,energy:e,dp,dpp,ep,epp};
  }
  const dotBounds=bounds(dotC,dotS),[d0,d1,d2]=dotBounds,[,e1,e2]=plan.energyBounds,emin=plan.energyMinimum;
  // Global bound on |d²/dphi² (dot / sqrt(target energy))|.
  const curvature=d2/Math.sqrt(emin)+d1*e1/emin**1.5+.5*d0*e2/emin**1.5+.75*d0*e1*e1/emin**2.5;
  const size=plan.gridSize,delta=TAU/size,dotGrid=onGrid(dotC,dotS,size),scores=new Float64Array(size);
  let best={score:-Infinity,phase:0};
  for(let i=0;i<size;i++){scores[i]=dotGrid[i]/Math.sqrt(plan.energyGrid[i]);if(scores[i]>best.score)best={score:scores[i],phase:i*delta};}
  best=at(best.phase);
  function polish(){
    for(let i=0;i<8;i++){
      const value=at(best.phase,true),f=2*value.dp*value.energy-value.dot*value.ep;
      const derivative=2*value.dpp*value.energy+value.dp*value.ep-value.dot*value.epp;
      if(!Number.isFinite(derivative)||derivative>=0)break;
      const change=f/derivative;if(!Number.isFinite(change)||Math.abs(change)>delta)break;
      const candidate=at((best.phase-change+TAU)%TAU);
      if(candidate.score+1e-14<best.score)break;best=candidate;if(Math.abs(change)<1e-13)break;
    }
  }
  const heap=new MaxHeap();
  function add(a,b,fa,fb){
    // With |f''| <= M, f(a+t*d) <= fa+(fb-fa)*t+M*d²*t*(1-t)/2.
    // Maximize this entire parabola, preserving the endpoint slope. The former
    // max(fa,fb)+M*d²/8 bound drops that slope and overestimates monotone spans.
    const bend=curvature*(b-a)**2/2,rise=bend-Math.abs(fb-fa);
    const upper=Math.max(fa,fb)+(rise>0?rise*rise/(4*bend):0)+ROUNDING_ALLOWANCE;
    if(upper>best.score+SCORE_TOLERANCE)heap.push({a,b,fa,fb,upper});
  }
  for(let i=0;i<size;i++)add(i*delta,(i+1)*delta,scores[i],scores[(i+1)%size]);
  while(heap.top&&heap.top.upper>best.score+SCORE_TOLERANCE){
    const interval=heap.pop(),middle=(interval.a+interval.b)/2,value=at(middle);diagnostics.subdivisions++;
    if(value.score>best.score)best=value;
    add(interval.a,middle,interval.fa,value.score);add(middle,interval.b,value.score,interval.fb);
  }
  // Newton polishing improves phase precision after the global score bound.
  polish();
  const phase=(best.phase+TAU)%TAU,score=Math.max(0,Math.min(1,best.score));
  const result={...metadata,score,error:Math.sqrt(Math.max(0,1-score*score)),phase,phaseScoreTolerance:SCORE_TOLERANCE};
  if(!preview)return result;
  // Target mean only affects display; compute it once for the winning phase.
  const ds=Math.sin(phase),dc=Math.cos(phase);let sum=0,s=0,c=1;
  for(let k=1;k<=h;k++){const next=s*dc+c*ds;c=c*dc-s*ds;s=next;sum+=plan.meanC[k]*c+plan.meanS[k]*s;}
  const scale=best.dot/audioNorm,targetMean=sum/n,viewSpan=Math.min(n-1,2*SAMPLE_RATE/base);
  result.wave=[];result.target=[];result.idealTarget=[];
  for(let i=0;i<512;i++){
    const position=i/511*viewSpan,idx=Math.floor(position),f=position-idx,theta=position*step+phase;
    result.wave.push((audio[idx]*(1-f)+audio[Math.min(idx+1,n-1)]*f-mean)*scale);
    const ds=Math.sin(theta),dc=Math.cos(theta);let projected=0,s=0,c=1;
    for(let k=1;k<=h;k++){const next=s*dc+c*ds;c=c*dc-s*ds;s=next;projected+=plan.b[k-1]*s;}
    result.target.push(projected-targetMean);result.idealTarget.push(sample(target,theta));
  }
  return result;
}
export function measuredScore(audio,target,note,options={}){return scorePrepared(prepareAudio(audio,note),target,options);}
