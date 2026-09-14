import {localUrl} from './local-url.mjs';
import {TARGET_VERSION,METRIC_VERSION,targetKey} from '../public/targets.mjs';
import {RUNNER_PROTOCOL} from '../public/table-import.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {randomUUID} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';

const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const WORKER='Windows tray runner';
const PRIORITIES={Idle:19,BelowNormal:10,Normal:0,AboveNormal:-7,High:-14};
export function normalizePriority(value){return Object.keys(PRIORITIES).find(k=>k.toLowerCase()===String(value).replace(/[ _-]/g,'').toLowerCase())??'BelowNormal'}
const patchKey=p=>JSON.stringify(p);
const finite=x=>typeof x==='number'&&Number.isFinite(x);

export async function atomicJson(filename,value){
  const temp=filename+'.'+process.pid+'.'+randomUUID()+'.tmp';
  await fs.writeFile(temp,JSON.stringify(value));
  try{for(let attempt=0;;attempt++)try{await fs.rename(temp,filename);break}catch(e){if(attempt>=8||!['EPERM','EBUSY','EACCES'].includes(e.code))throw e;await sleep(20*(attempt+1))}}
  finally{await fs.unlink(temp).catch(()=>{})}
}

/** Keep legal candidate results when constructing fresh optimizer mechanics.
 * Existing search counters are retained solely for monotonic checkpointing.
 */
export function restoreState(core,target,key,config,algorithm,cell,cached){
  const current=cell&&(cell.current??cell.target_key===key);
  const legal=p=>{try{return core.validatePatch(p).algorithm===algorithm}catch{return false}};
  const compatible=s=>{try{return s?.model===core.MODEL&&s.algorithm===algorithm&&s.harmonics===127&&targetKey(s.shape)===key}catch{return false}};
  const saved=Array.isArray(cell?.state?.elites)?cell.state.elites.filter(e=>legal(e?.patch)):[];
  const seeds=[cell?.patch,cell?.reference?.patch].filter(legal);
  let state=compatible(cached)?cached:core.initialState(target,[],127,algorithm);
  state.allowDetune=config.allowDetune;
  // Alternate elites are valuable search starting points, even when they are
  // not the champion. Reuse scores only for the exact model and target; old
  // target candidates remain legal proposals and are independently rescored.
  for(const item of saved){
    if(current&&compatible(cell.state)&&finite(item.loss)&&item.loss>=0&&item.loss<=5&&finite(item.score)&&item.score>=0&&item.score<=1){
      const same=state.elites.findIndex(e=>patchKey(e.patch)===patchKey(item.patch));
      if(same<0)state.elites.push(core.clone(item));
      else if(item.loss<state.elites[same].loss)state.elites[same]=core.clone(item);
    }else if(!state.elites.some(e=>patchKey(e.patch)===patchKey(item.patch)))addModelCandidate(state,core.evaluate(item.patch,target,127));
  }
  state.elites.sort((a,b)=>a.loss-b.loss);state.elites=state.elites.slice(0,16);
  for(const patch of seeds)if(!state.elites.some(e=>patchKey(e.patch)===patchKey(patch)))addModelCandidate(state,core.evaluate(patch,target,127));
  if(current){
    state.evaluations=Math.max(state.evaluations,Number(cell.evaluations)||0,Number(cell.state?.evaluations)||0);
  }
  return state;
}

export function addModelCandidate(state,item){
  state.evaluations++;
  const previous=state.elites[0]?.loss??Infinity,key=patchKey(item.patch);
  if(!state.elites.some(e=>patchKey(e.patch)===key)){
    state.elites.push(item);state.elites.sort((a,b)=>a.loss-b.loss);state.elites=state.elites.slice(0,16);
  }
  if(item.loss<previous){state.history.push({at:state.evaluations,error:item.error,score:item.score,time:Date.now()});state.history=state.history.slice(-120)}
  return item.loss<previous;
}

function validReference(r){return r?.engine==='Dexed Mark I / native'&&r.metricVersion===METRIC_VERSION&&finite(r.loss)&&finite(r.score)&&Array.isArray(r.notes)&&r.notes.length===3}
function completeReference(r){return validReference(r)&&r.notes.every(n=>Array.isArray(n.wave)&&Array.isArray(n.target))}

/** One asynchronous compute lane; no worker is attached to an individual cell.
 * The local scheduler selects the least-visited focus. Every native capture is compared
 * with all 32 targets in its algorithm row before another capture is rendered.
 */
export async function runTableRunner(options={}){
  const root=path.resolve(options.root??fileURLToPath(new URL('../',import.meta.url)));
  const config=options.config??JSON.parse(await fs.readFile(options.configPath??path.join(root,'.runtime','runner-config.json'),'utf8'));
  if(!options.request)localUrl(config.url);
  const runtimeDir=path.resolve(root,config.runtimeDir??'.runtime');
  await fs.mkdir(runtimeDir,{recursive:true});
  const core=options.core??await import(pathToFileURL(path.join(root,'public','core.mjs')));
  const native=options.native??await import(pathToFileURL(path.join(root,'runner','reference.mjs')));
  const createReference=()=>options.createReference?options.createReference():new native.Reference();
  const log=options.log??console.log,errorLog=options.errorLog??console.error;
  const started=Date.now(),processStartTime=new Date(started-process.uptime()*1000).toISOString();
  const statusFile=path.join(runtimeDir,'runner-status.json'),controlFile=path.join(runtimeDir,'runner-control.json');
  let reference=createReference(),stopping=false,active=null,failures=0,phase='Starting',cloudRunning=false;
  let localPaused=false,priority='BelowNormal',requestedPriority='BelowNormal',priorityError=null;
  let totalEvaluations=0,lastWrite=0,lastHeartbeat=0,ticking=false;
  const changedAt=new Map(),rows=new Map();
  const rowBudget=Math.max(500,Math.min(6000,config.rowBudgetMs??2800));
  const renewalControllers=new Set(),renewIntervalMs=options.renewIntervalMs??30000;
  const stop=()=>{stopping=true};
  process.on('SIGINT',stop);process.on('SIGTERM',stop);
  if(options.signal)options.signal.addEventListener('abort',stop,{once:true});

  const cellsPerMinute=()=>{const now=Date.now();for(const [id,time] of changedAt)if(now-time>60000)changedAt.delete(id);return Math.round(changedAt.size*60000/Math.max(5000,Math.min(60000,now-started)))};
  const compactStatus=()=>({priority,phase,cellsPerMinute:cellsPerMinute(),localPaused,running:cloudRunning&&!localPaused});
  const publish=async(force=false)=>{
    if(!force&&Date.now()-lastWrite<750)return;
    lastWrite=Date.now();
    await atomicJson(statusFile,{pid:process.pid,nativePid:reference.child?.pid??null,nativeProcessStartTime:reference.startedAt??null,processStartTime,root,running:cloudRunning&&!localPaused&&!stopping,localPaused,priority,phase,updatedAt:Date.now(),evaluations:totalEvaluations,cellsPerMinute:cellsPerMinute(),activeId:active?.job.id??null,priorityError});
  };
  const request=async(body,signal)=>{
    if(options.request)return options.request(body,signal);
    const timeout=AbortSignal.timeout(25000);
    const response=await fetch(config.url+'/api/table',{method:'POST',headers:{'Content-Type':'application/json','x-dexfraggler-worker':config.secret},body:JSON.stringify(body),redirect:'error',signal:signal?AbortSignal.any([signal,timeout]):timeout});
    let data;try{data=await response.json()}catch{throw Object.assign(Error(`Local app returned ${response.status}`),{status:response.status})}
    if(!response.ok)throw Object.assign(Error(`${response.status}: ${data.error}`),{status:response.status});
    return data;
  };
  const tick=async()=>{
    if(ticking)return;ticking=true;
    try{
      try{const value=JSON.parse(await fs.readFile(controlFile,'utf8'));if(typeof value.paused==='boolean')localPaused=value.paused;if(value.priority!==undefined)requestedPriority=normalizePriority(value.priority)}catch(e){if(e.code!=='ENOENT'&&!(e instanceof SyntaxError))priorityError=e.message}
      if(priority!==requestedPriority||!lastWrite){
        try{os.setPriority(process.pid,PRIORITIES[requestedPriority]);priority=requestedPriority;priorityError=null}catch(e){priorityError=e.message}
      }
      // Apply to the owned native child too, including a replacement renderer.
      if(reference.child?.pid)try{if(os.getPriority(reference.child.pid)!==PRIORITIES[priority])os.setPriority(reference.child.pid,PRIORITIES[priority])}catch{}
      if(localPaused&&!active)phase='Paused on this computer';
      if(active&&Date.now()-active.lastRenew>=renewIntervalMs&&!active.invalid&&!active.renewing){
        const lease=active;lease.lastRenew=Date.now();
        const controller=new AbortController();lease.renewalController=controller;lease.renewing=true;renewalControllers.add(controller);
        // Renewal network latency must never hold the local control/status
        // polling lock. The unique lease object receives its own response.
        void (async()=>{
          try{const result=await request({action:'renew',worker:lease.worker,id:lease.job.id,generation:lease.job.generation},controller.signal);if(result.running===false)lease.invalid=true}
          catch(e){if(e.status===409)lease.invalid=true;else if(!controller.signal.aborted)lease.renewalError=e.message}
          finally{lease.renewing=false;renewalControllers.delete(controller)}
        })();
      }
      await publish();
    }finally{ticking=false}
  };
  const timer=setInterval(()=>{tick().catch(e=>errorLog(new Date().toISOString(),'Status update:',e.message))},250);
  const responsiveSleep=async ms=>{const until=Date.now()+ms;while(!stopping&&Date.now()<until)await sleep(Math.min(250,until-Date.now()))};
  const heartbeat=async()=>{if(Date.now()-lastHeartbeat<5000)return;lastHeartbeat=Date.now();await request({action:'heartbeat',worker:WORKER,status:compactStatus()})};
  const assertLease=()=>{if(active?.invalid)throw Object.assign(Error('Search batch superseded.'),{status:409})};

  async function solveRow(job,worker){
    const rowStart=(job.algorithm-1)*32,focus=job.id%32,signature=JSON.stringify([job.scanId,job.generation,job.targetKeys]);
    let row=rows.get(job.algorithm);
    if(row?.signature!==signature){row={signature,generation:job.generation,states:new Map(),best:new Map(),checked:new Set(),count:0};rows.set(job.algorithm,row)}
    const cells=new Map((job.cells??[]).map(c=>[Number(c.id),c])),dirty=new Set();
    let didWork=false;
    for(let slot=0;slot<32;slot++){
      const id=rowStart+slot,cell=cells.get(id),key=job.targetKeys[slot];
      row.states.set(slot,restoreState(core,job.targets[slot],key,job.config,job.algorithm,cell,row.states.get(slot)));
      const current=cell&&(cell.current??cell.target_key===key),remote=current&&validReference(cell.reference)?cell.reference:null;
      if(remote&&(!row.best.get(slot)||remote.loss<=row.best.get(slot).loss))row.best.set(slot,remote);
      if(slot%8===7)await sleep(0);
    }
    // Keep only search memory for the present table generation.
    for(const [algorithm,other] of rows)if(other.generation!==job.generation)rows.delete(algorithm);
    let state=row.states.get(focus);
    phase=`Scanning algorithm ${job.algorithm}, slice ${focus+1}`;
    for(let pass=0;pass<2&&!stopping&&!localPaused;pass++){
      assertLease();const before=state.evaluations;state=core.runBatch(state,75);totalEvaluations+=state.evaluations-before;row.states.set(focus,state);dirty.add(focus);didWork=true;await sleep(0);
    }
    const seeds=[];
    const imported=new Map((job.seeds??[]).map(seed=>[patchKey(seed.patch),seed.key])),consumed=new Set();
    const add=p=>{if(p?.algorithm===job.algorithm&&!seeds.some(x=>patchKey(x)===patchKey(p)))seeds.push(p)};
    for(const seed of job.seeds??[])add(seed.patch);
    add(state.elites[0]?.patch);add(row.best.get(focus)?.patch);add(cells.get(job.id)?.reference?.patch);add(cells.get(job.id)?.patch);
    const ranked=Array.from({length:32},(_,slot)=>slot).sort((a,b)=>(row.best.get(b)?.loss??2)-(row.best.get(a)?.loss??2));
    for(const slot of [...job.config.anchors.map(a=>a.slot),...ranked]){add(row.states.get(slot)?.elites[0]?.patch);add(row.best.get(slot)?.patch);if(seeds.length>=10)break}
    // A neighboring pair often gives a useful first proposal for an in-between
    // column. It is a seed, never an assumed solution for that column.
    const neighbors=[...cells.values()].map(c=>({slot:c.id%32,patch:c.reference?.patch??c.patch})).filter(c=>c.patch);
    const left=neighbors.filter(c=>c.slot<focus).sort((a,b)=>b.slot-a.slot)[0],right=neighbors.filter(c=>c.slot>focus).sort((a,b)=>a.slot-b.slot)[0];
    if(left&&right)try{add(core.interpolate(left.patch,right.patch,(focus-left.slot)/(right.slot-left.slot)))}catch{}
    const end=Date.now()+rowBudget;
    let captures=0,duplicateAttempts=0;
    while(!stopping&&(Date.now()<end||!row.best.get(focus))){
      assertLease();
      if(localPaused&&row.best.get(focus))break;
      let p=seeds.shift();
      if(!p){
        const slot=row.count%5===0?ranked[Math.floor(row.count/5)%ranked.length]:focus;
        const base=row.count%7===0?row.states.get(slot).elites[0].patch:row.best.get(slot)?.patch??row.states.get(slot).elites[0].patch;
        p=native.nativeProposal(base,row.count++,job.config.allowDetune);
      }
      const key=patchKey(p);
      if(row.checked.has(key)&&!imported.has(key)&&row.best.get(focus)){if(++duplicateAttempts>128)break;continue}
      duplicateAttempts=0;
      // scoreMany reuses its cached capture/prepared pitch transforms between
      // chunks. Yield after eight targets so even display-wave generation for
      // a full row cannot starve tray pause/priority polling.
      const results=[];
      for(let start=0;start<32;start+=8){
        results.push(...await reference.scoreMany(p,job.targets.slice(start,start+8),{preview:false}));
        assertLease();await sleep(0);
      }
      if(!Array.isArray(results)||results.length!==32)throw Error('Native row scoring returned an incomplete row.');
      // Display samples are only needed for new champions. Scalar comparisons
      // reuse the full capture and exact objective for every other candidate.
      const improved=results.map((candidate,slot)=>!row.best.get(slot)||candidate.loss<row.best.get(slot).loss?slot:-1).filter(slot=>slot>=0);
      for(let start=0;start<improved.length;start+=8){
        const slots=improved.slice(start,start+8),previews=await reference.scoreMany(p,slots.map(slot=>job.targets[slot]));
        slots.forEach((slot,i)=>{if(!completeReference(previews[i])||Math.abs(previews[i].loss-results[slot].loss)>1e-12)throw Error('Preview and native score disagree.');results[slot]=previews[i]});
        assertLease();await sleep(0);
      }
      assertLease();captures++;didWork=true;
      // One model render also serves all targets; do not render the same patch
      // 32 times merely because the comparison target changes.
      const prepared=core.prepareModelWave(core.render(p));
      for(let slot=0;slot<32;slot++){
        const candidate=results[slot],current=row.best.get(slot);
        if(!current||candidate.loss<current.loss){row.best.set(slot,candidate);changedAt.set(rowStart+slot,Date.now());dirty.add(slot)}
        addModelCandidate(row.states.get(slot),{patch:core.clone(p),...core.analyzePreparedModel(prepared,job.targets[slot],127)});
        totalEvaluations++;dirty.add(slot);
        if(slot%8===7)await sleep(0);
      }
      row.checked.add(key);while(row.checked.size>384)row.checked.delete(row.checked.values().next().value);
      if(imported.has(key))consumed.add(imported.get(key));
      await publish();await sleep(0);
      if(captures>=24)break;
    }
    assertLease();
    const update=slot=>{
      const cell=cells.get(rowStart+slot),best=row.best.get(slot),remote=cell?.current?cell.reference:null;
      const unchanged=validReference(remote)&&remote.loss===best.loss&&patchKey(remote.patch)===patchKey(best.patch);
      if(!unchanged&&!completeReference(best))throw Error('A new native champion needs its complete measurement.');
      return {id:rowStart+slot,state:row.states.get(slot),reference:unchanged?null:best,visited:slot===focus&&didWork};
    };
    const updates=[...dirty].filter(slot=>validReference(row.best.get(slot))).map(update);
    if(!updates.some(c=>c.id===job.id)&&validReference(row.best.get(focus)))updates.push(update(focus));
    if(!updates.length){
      if(localPaused||stopping){await request({action:'release',worker,id:job.id,generation:job.generation});return}
      throw Error('No complete native cell result was available to save.');
    }
    phase='Saving table';
    await request({action:'checkpoint_row',worker,id:job.id,generation:job.generation,cells:updates,consumedSeeds:[...consumed]});
    log(new Date().toISOString(),`Algorithm ${job.algorithm}, slice ${focus+1}: ${captures} captures, ${updates.length} cells saved.`);
  }

  log(new Date().toISOString(),'DexFraggler table scheduler started.');
  try{
    await tick();
    while(!stopping)try{
      await heartbeat();
      if(localPaused){phase='Paused on this computer';await responsiveSleep(500);continue}
      const worker=WORKER+' '+randomUUID();
      const response=await request({action:'claim_row',worker,protocol:RUNNER_PROTOCOL,model:core.MODEL,targetVersion:TARGET_VERSION,metricVersion:METRIC_VERSION,status:compactStatus()});
      const job=response.job;cloudRunning=response.running??Boolean(job);
      if(!job){phase=cloudRunning?'Waiting for table':'Table paused';await responsiveSleep(1500);continue}
      cloudRunning=true;active={job,worker,lastRenew:Date.now(),invalid:false};
      await solveRow(job,worker);
      active?.renewalController?.abort();
      active=null;failures=0;phase=localPaused?'Paused on this computer':'Scanning table';await publish(true);
      await responsiveSleep(30);
    }catch(e){
      const lease=active;lease?.renewalController?.abort();active=null;
      if(lease&&e.status!==409)try{await request({action:localPaused||stopping?'release':'failed',worker:lease.worker,id:lease.job.id,generation:lease.job.generation,error:e.message})}catch{}
      if(!reference.healthy){await reference.close();reference=createReference()}
      if(e.status===409){phase='Refreshing table';failures=0;await responsiveSleep(150);continue}
      phase='Reconnecting';errorLog(new Date().toISOString(),e.message);await publish(true);await responsiveSleep(Math.min(30000,1500*++failures));
    }
  }finally{
    clearInterval(timer);process.off('SIGINT',stop);process.off('SIGTERM',stop);options.signal?.removeEventListener('abort',stop);
    for(const controller of renewalControllers)controller.abort();
    await reference.close();phase='Stopped';cloudRunning=false;await publish(true);
    log('DexFraggler stopped. Saved anchors and cell results are retained.');
  }
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  await runTableRunner({configPath:process.argv[2]});
}
