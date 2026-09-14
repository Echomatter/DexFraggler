// CPU-only scoring benchmark: captures are rendered once, outside timed regions.
// Compare an earlier scorer without changing the metric:
// node scripts/benchmark-native-score.mjs --baseline .runtime/measurement-baseline.mjs
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
import {createHash} from 'node:crypto';
import {blank,clone} from '../public/core.mjs';
import {columnTargets,DEFAULT_CONFIG} from '../public/targets.mjs';
import {Reference} from '../runner/reference.mjs';
import * as current from '../runner/measurement.mjs';

const args=process.argv.slice(2);
function option(name){const index=args.indexOf(name);return index<0?null:args[index+1];}
const rounds=Number(option('--rounds')??5);
if(!Number.isInteger(rounds)||rounds<1||rounds>100)throw Error('--rounds must be 1 through 100.');
const baselinePath=option('--baseline'),snapshotPath=option('--snapshot');
const scorers=baselinePath?[['baseline',await import(pathToFileURL(path.resolve(baselinePath)).href)],['current',current]]:[['current',current]];
let targets=columnTargets(DEFAULT_CONFIG),patches=[],snapshotSha256;
if(snapshotPath){
  const contents=await fs.readFile(snapshotPath,'utf8'),snapshot=JSON.parse(contents);snapshotSha256=createHash('sha256').update(contents).digest('hex');
  if(snapshot.config)targets=columnTargets(snapshot.config);
  patches=(snapshot.cells??[]).map(cell=>cell.reference?.patch??cell.patch).filter(Boolean);
  const seen=new Set();patches=patches.filter(patch=>{const key=JSON.stringify(patch);if(seen.has(key))return false;seen.add(key);return true;});
  if(!patches.length)throw Error('Snapshot contains no candidate patches.');
}else{
  const sine=blank(),feedback=blank();feedback.algorithm=4;feedback.feedback=7;
  feedback.operators.forEach((op,i)=>Object.assign(op,{level:[88,73,80,91,77,84][i],coarse:[1,2,3,1,2,1][i]}));
  const detuned=clone(feedback);detuned.algorithm=6;detuned.feedback=4;
  detuned.operators.forEach((op,i)=>Object.assign(op,{fine:i*3,detune:[4,10,6,8,7,11][i]}));
  const additive=clone(feedback);additive.algorithm=32;
  const fixed=clone(additive);fixed.feedback=2;Object.assign(fixed.operators[0],{mode:1,coarse:2,fine:34,detune:14});
  patches=[sine,feedback,detuned,additive,fixed];
}
const limit=Number(option('--limit')??patches.length);
if(!Number.isInteger(limit)||limit<1)throw Error('--limit must be a positive integer.');
// Spread a limited sample across the full export, rather than only algorithm 1.
if(limit<patches.length)patches=Array.from({length:limit},(_,i)=>patches[Math.floor(i*(patches.length-1)/(limit-1||1))]);
const reference=new Reference(),captures=[];
try{for(const patch of patches)captures.push(await reference.render(patch));}finally{await reference.close();}
const inputs=captures.flatMap(capture=>capture.notes.map((note,i)=>({note,audio:capture.waveforms[i]})));
const prepared=new Map(),measurements={};
function measure(fn){const start=performance.now(),value=fn();return {ms:performance.now()-start,value};}
function scoreAll(scorer,contexts){return contexts.flatMap(context=>targets.map(target=>scorer.scorePrepared(context,target,{preview:false})));}
function delta(before,after,key){return after[key]-before[key];}
function median(values){const ordered=[...values].sort((a,b)=>a-b);return ordered[Math.floor(ordered.length/2)];}
for(const [name,scorer] of scorers){
  const setup=measure(()=>inputs.map(({audio,note})=>scorer.prepareAudio(audio,note)));prepared.set(name,setup.value);
  const cold=measure(()=>scoreAll(scorer,setup.value));
  measurements[name]={coldPrepareMs:setup.ms,coldScoreMs:cold.ms,prepareMs:[],scoreMs:[],results:cold.value};
}
let maxMomentDelta;
if(prepared.has('baseline')){
  maxMomentDelta=0;
  prepared.get('current').forEach((context,i)=>context.moments.forEach((moment,j)=>{maxMomentDelta=Math.max(maxMomentDelta,Math.abs(moment-prepared.get('baseline')[i].moments[j]));}));
  if(maxMomentDelta!==0)throw Error(`Projection accumulation changed: maximum moment difference ${maxMomentDelta}.`);
}
for(let warmup=0;warmup<2;warmup++)for(const [name,scorer] of scorers){inputs.map(({audio,note})=>scorer.prepareAudio(audio,note));scoreAll(scorer,prepared.get(name));}
// Alternate execution order each round so host load does not always favor one version.
for(let round=0;round<rounds;round++)for(const [name,scorer] of round%2?[...scorers].reverse():scorers){
  const item=measurements[name];
  item.prepareMs.push(measure(()=>inputs.map(({audio,note})=>scorer.prepareAudio(audio,note))).ms);
  const before=scorer.scoringDiagnostics(),run=measure(()=>scoreAll(scorer,prepared.get(name))),after=scorer.scoringDiagnostics();
  item.scoreMs.push(run.ms);item.results=run.value;
  item.phaseEvaluations=delta(before,after,'phaseEvaluations');item.subdivisions=delta(before,after,'subdivisions');
}
let equivalence;
if(measurements.baseline){
  let maxScoreDelta=0,maxErrorDelta=0,maxPhaseDelta=0;
  measurements.current.results.forEach((result,i)=>{
    const before=measurements.baseline.results[i];
    maxScoreDelta=Math.max(maxScoreDelta,Math.abs(result.score-before.score));
    maxErrorDelta=Math.max(maxErrorDelta,Math.abs(result.error-before.error));
    const phaseDelta=Math.abs(result.phase-before.phase)%(2*Math.PI);maxPhaseDelta=Math.max(maxPhaseDelta,Math.min(phaseDelta,2*Math.PI-phaseDelta));
    if(result.metricVersion!==before.metricVersion||result.bands!==before.bands||Math.abs(result.score-before.score)>1e-10)throw Error(`Scorer equivalence failed at comparison ${i}.`);
  });
  equivalence={comparisons:measurements.current.results.length,maxMomentDelta,maxScoreDelta,maxErrorDelta,maxPhaseDelta,scoreTolerance:1e-10};
}
for(const item of Object.values(measurements)){delete item.results;item.medianPrepareMs=median(item.prepareMs);item.medianScoreMs=median(item.scoreMs);}
const algorithms=[...new Set(patches.map(patch=>patch.algorithm))].sort((a,b)=>a-b);
const report={node:process.version,platform:process.platform,...(snapshotSha256?{snapshotSha256}:{}),patches:patches.length,algorithms,pitches:inputs.length,targets:targets.length,rounds,measurements,...(equivalence?{equivalence,scoreSpeedup:measurements.baseline.medianScoreMs/measurements.current.medianScoreMs,prepareSpeedup:measurements.baseline.medianPrepareMs/measurements.current.medianPrepareMs}:{})};
const output=option('--output');if(output)await fs.writeFile(output,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
