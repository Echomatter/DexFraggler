export const TARGET_VERSION='ideal-waveform-v1';
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
export function validateTarget(value){
  if(!exactKeys(value,['kind','weights'])||value.kind!==TARGET_VERSION||!Array.isArray(value.weights)||value.weights.length!==4
    ||!value.weights.every(x=>Number.isFinite(x)&&x>=0&&x<=1)||Math.abs(value.weights.reduce((a,b)=>a+b,0)-1)>1e-12)
    throw Error('A target must be a convex blend of the four ideal waveform formulas.');
  return {kind:TARGET_VERSION,weights:value.weights.map(x=>x===0?0:x)};
}
export function idealTarget(shape){if(!WAVEFORMS.includes(shape))throw Error('Choose sine, triangle, square or saw.');return {kind:TARGET_VERSION,weights:WAVEFORMS.map(name=>Number(name===shape))};}
export function blendTargets(left,right,f){
  left=validateTarget(left);right=validateTarget(right);
  if(!Number.isFinite(f)||f<0||f>1)throw Error('Blend position must be between zero and one.');
  return {kind:TARGET_VERSION,weights:left.weights.map((x,i)=>x*(1-f)+right.weights[i]*f)};
}
export function targetKey(value){const target=validateTarget(value);return `${TARGET_VERSION}:${target.weights.join(',')}`;}
export function validateConfig(raw){
  if(!exactKeys(raw,['allowDetune','anchors'])||typeof raw.allowDetune!=='boolean'||!Array.isArray(raw.anchors)||raw.anchors.length<1||raw.anchors.length>32)
    throw Error('Use 1–32 ideal waveform anchors and an explicit detuning preference.');
  const seen=new Set();
  const anchors=raw.anchors.map(anchor=>{
    if(!exactKeys(anchor,['slot','shape'])||!Number.isInteger(anchor.slot)||anchor.slot<0||anchor.slot>31||seen.has(anchor.slot)||!WAVEFORMS.includes(anchor.shape))
      throw Error('Each anchor needs a unique slice and one of the four ideal waveform formulas.');
    seen.add(anchor.slot);return {slot:anchor.slot,shape:anchor.shape};
  }).sort((a,b)=>a.slot-b.slot);
  return {allowDetune:raw.allowDetune,anchors};
}
export function columnTargets(raw){
  const {anchors}=validateConfig(raw);
  return Array.from({length:32},(_,slot)=>{
    const left=anchors.filter(a=>a.slot<=slot).at(-1)??anchors[0],right=anchors.find(a=>a.slot>=slot)??anchors.at(-1);
    return blendTargets(idealTarget(left.shape),idealTarget(right.shape),left.slot===right.slot?0:(slot-left.slot)/(right.slot-left.slot));
  });
}
export function labelAt(config,slot){
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
export function sample(target,theta){return valueAt(validateTarget(target).weights,wrap(theta/TAU));}
export function cycle(target,n=256,phase=0){
  const {weights}=validateTarget(target);if(!Number.isInteger(n)||n<2||n>65536||!Number.isFinite(phase))throw Error('Invalid ideal display size or phase.');
  return Array.from({length:n},(_,i)=>valueAt(weights,wrap(i/n+phase/TAU)));
}
export function idealPoints(target,segments=128,cycles=1,phase=0){
  const {weights}=validateTarget(target);
  if(!Number.isInteger(segments)||segments<4||segments>65536||!Number.isFinite(cycles)||cycles<=0||cycles>16||!Number.isFinite(phase))throw Error('Invalid ideal curve extent.');
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
  const {weights:w}=validateTarget(target);
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
  const {sin}=coefficients(target,h);let value=0;for(let k=1;k<=h;k++)value+=sin[k-1]*Math.sin(k*theta);return value;
}
export function projectedCycle(target,n=256,h=127,phase=0){
  const {sin}=coefficients(target,h);if(!Number.isInteger(n)||n<2||n>65536||!Number.isFinite(phase))throw Error('Invalid projected display size or phase.');
  return Array.from({length:n},(_,i)=>{let value=0;const theta=TAU*i/n+phase;for(let k=1;k<=h;k++)value+=sin[k-1]*Math.sin(k*theta);return value;});
}
export function idealEnergy(target){const {weights}=validateTarget(target);let energy=0;for(let i=0;i<4;i++)for(let j=0;j<4;j++)energy+=weights[i]*weights[j]*GRAM[i][j];return energy;}
export function projectionInfo(target,base,sampleRate=48000){
  const bands=nyquistHarmonics(base,sampleRate),series=coefficients(target,bands),fullEnergy=idealEnergy(target),projectedEnergy=series.sin.reduce((sum,x)=>sum+x*x,0)/2;
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
