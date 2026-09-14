import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {initialState,runBatch,evaluate,interpolate,MODEL} from '../public/core.mjs';
import {Reference,nativeProposal} from './reference.mjs';
import {targetKey} from '../public/targets.mjs';
const root=fileURLToPath(new URL('../',import.meta.url)),config=JSON.parse(await fs.readFile(process.argv[2]||root+'.runtime/runner-config.json','utf8'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms)),id='Windows background runner';
let reference=new Reference(),stopping=false,failures=0,activeJob=null;process.on('SIGINT',()=>{stopping=true});process.on('SIGTERM',()=>{stopping=true});
async function call(body){const r=await fetch(config.url+'/api/table',{method:'POST',headers:{'Content-Type':'application/json',...(config.cookie?{Cookie:config.cookie}:{}),'OAI-Sites-Authorization':'Bearer '+config.bypass,'x-dexfraggler-worker':config.secret},body:JSON.stringify(body),signal:AbortSignal.timeout(25000)});let d;try{d=await r.json()}catch{throw Error(`Site returned ${r.status}`)}if(!r.ok)throw Error(`${r.status}: ${d.error}`);return d}
async function checkpoint(data){const path=root+'.runtime/table-checkpoint.json',temp=path+'.'+process.pid+'.tmp';await fs.writeFile(temp,JSON.stringify(data));for(let i=0;;i++)try{await fs.rename(temp,path);break}catch(e){if(i>=8||!['EPERM','EBUSY','EACCES'].includes(e.code))throw e;await sleep(30*(i+1))}}
console.log(new Date().toISOString(),'Table scheduler started: one compute lane, 1,024 cells.');
while(!stopping)try{
 await call({action:'heartbeat',worker:id});const worker=id+' '+crypto.randomUUID(),{job}=await call({action:'claim',worker});if(!job){await sleep(5000);continue}activeJob={id:job.id,generation:job.generation,worker};
 const {cell,target,config:c}=job,current=cell?.target_key===job.targetKey;
 let seeds=[...(cell?.seeds??[]),...(cell?.state?.elites?.map(e=>e.patch)??[]),cell?.reference?.patch,cell?.patch,...job.neighbors.map(n=>n.patch)].filter(p=>p?.algorithm===job.algorithm);
 const left=job.neighbors.filter(n=>n.id<job.id).sort((a,b)=>b.id-a.id)[0],right=job.neighbors.filter(n=>n.id>job.id).sort((a,b)=>a.id-b.id)[0];if(left&&right)try{seeds.push(interpolate(left.patch,right.patch,(job.id-left.id)/(right.id-left.id)))}catch{}
 let state=current&&cell.state?.model===MODEL?cell.state:initialState(target,seeds.map(patch=>({patch})),c.harmonics,job.algorithm);state.allowDetune=c.allowDetune;
 let best=current?cell.reference:null;
 try{const saved=JSON.parse(await fs.readFile(root+'.runtime/table-checkpoint.json','utf8'));if(saved.id===job.id&&saved.generation===job.generation&&saved.cellRevision===(cell?.revision??0)&&targetKey(saved.state.shape)===job.targetKey){state=saved.state;best=saved.reference}}catch{}
 for(const p of seeds.slice(0,20)){const item=evaluate(p,target,c.harmonics);state.evaluations++;if(!state.elites.some(e=>JSON.stringify(e.patch)===JSON.stringify(p)))state.elites.push(item)}state.elites.sort((a,b)=>a.loss-b.loss);state.elites=state.elites.slice(0,16);state=runBatch(state,350);state.nativeSeeds=seeds.slice(0,32);
 let checked=state.nativeChecked??[],count=state.nativeCount??0,measured=0;
 for(const p of [state.elites[0].patch,...seeds]){const key=JSON.stringify(p);if(checked.includes(key))continue;const result=await reference.score(p,target,c.harmonics);if(!best||result.loss<best.loss)best=result;checked.push(key);if(++measured>=3)break}
 if(!best)best=await reference.score(state.elites[0].patch,target,c.harmonics);
 const until=Date.now()+550;while(Date.now()<until&&!stopping){const p=nativeProposal(count%8===0?state.elites[Math.floor(count/8)%state.elites.length].patch:best.patch,count++,c.allowDetune),result=await reference.score(p,target,c.harmonics);if(result.loss<best.loss)best=result}
 state.nativeCount=count;state.nativeChecked=checked.slice(-48);
 await checkpoint({id:job.id,generation:job.generation,cellRevision:cell?.revision??0,state,reference:best});await call({action:'checkpoint',id:job.id,generation:job.generation,worker,state,reference:best});
 console.log(new Date().toISOString(),`A${job.algorithm} S${job.slot+1}`,`visits ${current?cell.visits+1:1}`,`native ${best.score.toFixed(6)}`,`candidates ${state.evaluations}`);activeJob=null;failures=0;await sleep(300);
}catch(e){if(activeJob)try{await call({action:'failed',...activeJob,error:e.message})}catch{}activeJob=null;if(!reference.healthy){reference.close();reference=new Reference()}console.error(new Date().toISOString(),e.message);await sleep(Math.min(60000,5000*++failures))}
reference.close();console.log('Table scheduler stopped; saved work retained.');
