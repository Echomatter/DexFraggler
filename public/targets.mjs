export const TARGET_VERSION='ideal-waveform-v1';
export const IMPORTED_TARGET_VERSION='periodic-wave-v1';
export const AUDIO_PREPROCESS_VERSION='audio-prep-v1';
export const METRIC_VERSION='band-limited-match-v1';
export const WAVEFORMS=Object.freeze(['sine','triangle','square','saw']);
export const DEFAULT_CONFIG=Object.freeze({allowDetune:false,anchors:[{slot:0,shape:'triangle'},{slot:15,shape:'square'},{slot:31,shape:'saw'}]});
const TAU=2*Math.PI;
const GRAM=[
  [.5,4/Math.PI**2,2/Math.PI,1/Math.PI],
  [4/Math.PI**2,1/3,.5,.25],
  [2/Math.PI,.5,1,.5],
  [1/Math.PI,.25,.5,1/3],
];

function exactKeys(value,keys){return value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));}
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const numberText=value=>Number(value).toPrecision(15);
function identity(value){let hash=2166136261;for(const character of value){hash^=character.charCodeAt(0);hash=Math.imul(hash,16777619)}return (hash>>>0).toString(16).padStart(8,'0')}
function periodicIdentity(value){return identity(`${value.kind}|${value.preprocessVersion}|${value.sampleRate}|${value.fundamentalHz}|${value.samples.map(numberText).join(',')}|${value.harmonics.sin.map(numberText).join(',')}|${value.harmonics.cos.map(numberText).join(',')}`)}
function validatePeriodicTarget(value){
  if(!value||typeof value!=='object'||value.kind!==IMPORTED_TARGET_VERSION||value.preprocessVersion!==AUDIO_PREPROCESS_VERSION||!Array.isArray(value.samples)||value.samples.length<2||value.samples.length>65536||!value.samples.every(finite)||!finite(value.sampleRate)||value.sampleRate<=0||!finite(value.fundamentalHz)||value.fundamentalHz<=0||!value.harmonics||!Array.isArray(value.harmonics.sin)||!Array.isArray(value.harmonics.cos)||value.harmonics.sin.length!==value.harmonics.cos.length||value.harmonics.sin.length<1||value.harmonics.sin.length>32767||!value.harmonics.sin.every(finite)||!value.harmonics.cos.every(finite)||typeof value.id!=='string'||value.id!==periodicIdentity(value)||!value.source||typeof value.source!=='object')throw Error('Use a versioned normalized periodic-wave target with harmonic phase and provenance.');
  return value;
}
export function validateTarget(value){
  if(value?.kind===IMPORTED_TARGET_VERSION)return validatePeriodicTarget(value);
  if(!exactKeys(value,['kind','weights'])||value.kind!==TARGET_VERSION||!Array.isArray(value.weights)||value.weights.length!==4
    ||!value.weights.every(x=>Number.isFinite(x)&&x>=0&&x<=1)||Math.abs(value.weights.reduce((a,b)=>a+b,0)-1)>1e-12)
    throw Error('A target must be a convex blend of the four ideal waveform formulas.');
  return {kind:TARGET_VERSION,weights:value.weights.map(x=>x===0?0:x)};
}
export function idealTarget(shape){if(!WAVEFORMS.includes(shape))throw Error('Choose sine, triangle, square or saw.');return {kind:TARGET_VERSION,weights:WAVEFORMS.map(name=>Number(name===shape))};}
export function blendTargets(left,right,f){
  left=validateTarget(left);right=validateTarget(right);
  if(left.kind!==TARGET_VERSION||right.kind!==TARGET_VERSION)throw Error('Only ideal waveform anchors can be blended.');
  if(!Number.isFinite(f)||f<0||f>1)throw Error('Blend position must be between zero and one.');
  return {kind:TARGET_VERSION,weights:left.weights.map((x,i)=>x*(1-f)+right.weights[i]*f)};
}
export function targetKey(value){const target=validateTarget(value);return target.kind===IMPORTED_TARGET_VERSION?`${IMPORTED_TARGET_VERSION}:${target.id}`:`${TARGET_VERSION}:${target.weights.join(',')}`;}
export function validateConfig(raw){
  const hasTargetSet=!!raw&&typeof raw==='object'&&Object.hasOwn(raw,'targetSet');
  if(!raw||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).some(key=>!['allowDetune','anchors','targetSet','source'].includes(key))||typeof raw.allowDetune!=='boolean'||!Array.isArray(raw.anchors)||raw.anchors.length>(hasTargetSet?32:32)||(!hasTargetSet&&raw.anchors.length<1)||hasTargetSet&&!Array.isArray(raw.targetSet))
    throw Error('Use 1–32 ideal waveform anchors and an explicit detuning preference.');
  const seen=new Set();
  const anchors=raw.anchors.map(anchor=>{
    if(!exactKeys(anchor,['slot','shape'])||!Number.isInteger(anchor.slot)||anchor.slot<0||anchor.slot>31||seen.has(anchor.slot)||!WAVEFORMS.includes(anchor.shape))
      throw Error('Each anchor needs a unique slice and one of the four ideal waveform formulas.');
    seen.add(anchor.slot);return {slot:anchor.slot,shape:anchor.shape};
  }).sort((a,b)=>a.slot-b.slot);
  const result={allowDetune:raw.allowDetune,anchors};
  if(hasTargetSet){
    if(raw.targetSet.length!==32)throw Error('An imported target set must contain exactly 32 waveform columns.');
    result.targetSet=raw.targetSet.map(validateTarget);
    if(raw.source!==undefined&&(!raw.source||typeof raw.source!=='object'||Array.isArray(raw.source)))throw Error('Imported target provenance must be an object.');
    if(raw.source!==undefined)result.source=raw.source;
  }else if(raw.source!==undefined)throw Error('Imported target provenance requires a target set.');
  return result;
}
export function columnTargets(raw){
  const config=validateConfig(raw);if(config.targetSet)return config.targetSet;
  const {anchors}=config;
  return Array.from({length:32},(_,slot)=>{
    const left=anchors.filter(a=>a.slot<=slot).at(-1)??anchors[0],right=anchors.find(a=>a.slot>=slot)??anchors.at(-1);
    return blendTargets(idealTarget(left.shape),idealTarget(right.shape),left.slot===right.slot?0:(slot-left.slot)/(right.slot-left.slot));
  });
}
export function labelAt(config,slot){
  if(config.targetSet)return config.source?.name?`${config.source.name} · frame ${slot+1}`:`Imported frame ${slot+1}`;
  const anchor=config.anchors.find(a=>a.slot===slot);if(anchor)return anchor.shape;
  const left=config.anchors.filter(a=>a.slot<slot).at(-1)??config.anchors[0],right=config.anchors.find(a=>a.slot>slot)??config.anchors.at(-1);
  return left.shape===right.shape?left.shape:`${left.shape} → ${right.shape}`;
}

// All four formulas have unit peak. At a jump, use the Fourier midpoint;
// idealPoints supplies both one-sided limits so SVG drawings keep sharp edges.
function valueAt(weights,u,side=0){
  const sine=Math.sin(TAU*u),triangle=u<.25?4*u:u<.75?2-4*u:4*u-4;
  const square=u===0?side:u===.5?-side:u<.5?1:-1;
  const saw=u===0?side:1-2*u;
  return weights[0]*sine+weights[1]*triangle+weights[2]*square+weights[3]*saw;
}
function wrap(u){return ((u%1)+1)%1;}
function periodicSample(target,theta){return valueAtPeriodic(target.samples,wrap(theta/TAU));}
function valueAtPeriodic(samples,u){return samples[Math.floor(u*samples.length)%samples.length]*(1-u*samples.length%1)+samples[(Math.floor(u*samples.length)+1)%samples.length]*(u*samples.length%1)}
export function sample(target,theta){const checked=validateTarget(target);return checked.kind===IMPORTED_TARGET_VERSION?periodicSample(checked,theta):valueAt(checked.weights,wrap(theta/TAU));}
export function cycle(target,n=256,phase=0){
  const checked=validateTarget(target);if(!Number.isInteger(n)||n<2||n>65536||!Number.isFinite(phase))throw Error('Invalid ideal display size or phase.');
  return Array.from({length:n},(_,i)=>sample(checked,TAU*i/n+phase));
}
export function idealPoints(target,segments=128,cycles=1,phase=0){
  const checked=validateTarget(target);
  if(!Number.isInteger(segments)||segments<4||segments>65536||!Number.isFinite(cycles)||cycles<=0||cycles>16||!Number.isFinite(phase))throw Error('Invalid ideal curve extent.');
  if(checked.kind===IMPORTED_TARGET_VERSION)return Array.from({length:segments+1},(_,i)=>{const x=i/segments*cycles;return {x,y:sample(checked,TAU*x+phase)}});
  const {weights}=checked;
  const offset=wrap(phase/TAU),positions=new Set(Array.from({length:segments+1},(_,i)=>i/segments*cycles));
  for(let k=Math.ceil(offset*4);k<=Math.floor((offset+cycles)*4);k++)positions.add(k/4-offset);
  const points=[];
  for(const x of [...positions].sort((a,b)=>a-b)){
    let u=wrap(x+offset);const quarter=Math.round(u*4)/4;if(Math.abs(u-quarter)<1e-13)u=quarter===1?0:quarter;
    const jump=(u===0&&(weights[2]>0||weights[3]>0))||(u===.5&&weights[2]>0);
    if(jump){if(x>0)points.push({x,y:valueAt(weights,u,-1)});if(x<cycles)points.push({x,y:valueAt(weights,u,1)});}
    else points.push({x,y:valueAt(weights,u)});
  }
  return points;
}

export function coefficients(target,h){
  const checked=validateTarget(target);
  if(checked.kind===IMPORTED_TARGET_VERSION){if(!Number.isInteger(h)||h<1||h>32767)throw Error('Projection requires a positive finite harmonic count.');return {sin:Array.from({length:h},(_,i)=>checked.harmonics.sin[i]??0),cos:Array.from({length:h},(_,i)=>checked.harmonics.cos[i]??0)};}
  const {weights:w}=checked;
  if(!Number.isInteger(h)||h<1||h>32767)throw Error('Projection requires a positive finite harmonic count.');
  const sin=Array.from({length:h},(_,i)=>{
    const k=i+1,odd=k%2;
    return w[0]*(k===1?1:0)+w[1]*(odd?8/Math.PI**2*(k%4===1?1:-1)/(k*k):0)+w[2]*(odd?4/(Math.PI*k):0)+w[3]*2/(Math.PI*k);
  });
  return {sin,cos:Array(h).fill(0)};
}
export function nyquistHarmonics(base,sampleRate=48000){
  if(!Number.isFinite(base)||base<=0||!Number.isFinite(sampleRate)||sampleRate<=2*base)throw Error('The fundamental must be strictly below Nyquist.');
  return Math.ceil(sampleRate/(2*base))-1;
}
export function projectedSample(target,theta,h){
  const {sin,cos}=coefficients(target,h);let value=0;for(let k=1;k<=h;k++)value+=cos[k-1]*Math.cos(k*theta)+sin[k-1]*Math.sin(k*theta);return value;
}
export function projectedCycle(target,n=256,h=127,phase=0){
  const {sin,cos}=coefficients(target,h);if(!Number.isInteger(n)||n<2||n>65536||!Number.isFinite(phase))throw Error('Invalid projected display size or phase.');
  return Array.from({length:n},(_,i)=>{let value=0;const theta=TAU*i/n+phase;for(let k=1;k<=h;k++)value+=cos[k-1]*Math.cos(k*theta)+sin[k-1]*Math.sin(k*theta);return value;});
}
export function idealEnergy(target){const checked=validateTarget(target);if(checked.kind===IMPORTED_TARGET_VERSION){const {sin,cos}=coefficients(checked,checked.harmonics.sin.length);return sin.reduce((sum,value,i)=>sum+(value*value+cos[i]*cos[i])/2,0)}const {weights}=checked;let energy=0;for(let i=0;i<4;i++)for(let j=0;j<4;j++)energy+=weights[i]*weights[j]*GRAM[i][j];return energy;}
export function projectionInfo(target,base,sampleRate=48000){
  const bands=nyquistHarmonics(base,sampleRate),series=coefficients(target,bands),fullEnergy=idealEnergy(target),projectedEnergy=series.sin.reduce((sum,x,i)=>sum+x*x+series.cos[i]*series.cos[i],0)/2;
  return {bands,sampleRate,base,fullEnergy,projectedEnergy,omittedEnergy:Math.max(0,fullEnergy-projectedEnergy),retainedEnergy:Math.min(1,projectedEnergy/fullEnergy)};
}
// The scheduler deliberately has two lanes. Coverage advances the least-visited
// frontier, while one bounded recovery turn periodically advances a weak cell by
// at most one visit. This keeps poor results moving without allowing easy,
// interpolated columns to crowd out untouched cells forever.
export const SCHEDULER_POLICY=Object.freeze({recoveryEvery:4,recoveryLead:1});
const numberOrNull=value=>{if(value===null||value===undefined||value==='')return null;const n=Number(value);return Number.isFinite(n)?n:null};
const ageOf=(updatedAt,now)=>Math.max(0,now-(numberOrNull(updatedAt)??0));
function cellOrder(a,b,mode){
  if(mode==='recovery')return b.loss-a.loss||b.age-a.age||a.visits-b.visits||a.anchor-b.anchor||a.slot-b.slot||a.id-b.id;
  return b.loss-a.loss||a.anchor-b.anchor||a.age-b.age||a.visits-b.visits||a.slot-b.slot||a.id-b.id;
}
export function scheduleCell(cells,config,keys){
  const now=Date.now(),byId=new Map(cells.map(c=>[Number(c.id),c])),anchors=new Set(config.anchors.map(a=>a.slot));
  const available=Array.from({length:1024},(_,id)=>{
    const cell=byId.get(id),current=cell?.target_key===keys[id%32],visits=current?Math.max(0,numberOrNull(cell?.visits)??0):0,loss=current?numberOrNull(cell?.native_loss):null;
    return {id,slot:id%32,current,visits,loss:loss??0,knownLoss:loss!==null,age:ageOf(cell?.updated_at,now),anchor:anchors.has(id%32)?0:1,blocked:Number(cell?.failed_until)>now};
  }).filter(c=>!c.blocked);
  if(!available.length)return null;
  const stale=available.filter(c=>!c.current);
  if(stale.length)return stale.sort((a,b)=>b.age-a.age||a.id-b.id)[0].id;
  const minimum=Math.min(...available.map(c=>c.visits)),total=available.reduce((sum,c)=>sum+c.visits,0),frontier=available.filter(c=>c.visits===minimum),weak=available.filter(c=>c.knownLoss&&c.visits<=minimum+SCHEDULER_POLICY.recoveryLead),recovery=weak.length>0&&total%SCHEDULER_POLICY.recoveryEvery===SCHEDULER_POLICY.recoveryEvery-1;
  return (recovery?weak:frontier).sort((a,b)=>cellOrder(a,b,recovery?'recovery':'coverage'))[0]?.id??null;
}
