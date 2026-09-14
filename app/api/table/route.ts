import {env} from 'cloudflare:workers';
import {database} from '@/db/storage';
import {MODEL,validatePatch,blank} from '@/public/core.mjs';
import {DEFAULT_CONFIG,validateConfig,columnTargets,targetKey,scheduleCell} from '@/public/targets.mjs';
export const dynamic='force-dynamic';
type Row=Record<string,unknown>;
const json=(v:unknown,status=200)=>Response.json(v,{status,headers:{'Cache-Control':'no-store'}});
const parse=(v:unknown)=>v?JSON.parse(String(v)):null;
async function auth(req:Request){
 const secret=(env as unknown as {DEXFRAGGLER_RUNNER_SECRET?:string}).DEXFRAGGLER_RUNNER_SECRET,token=req.headers.get('x-dexfraggler-worker');
 if(secret&&token&&secret.length===token.length){const enc=new TextEncoder(),[a,b]=await Promise.all([secret,token].map(s=>crypto.subtle.digest('SHA-256',enc.encode(s))));if(new Uint8Array(a).every((v,i)=>v===new Uint8Array(b)[i]))return true}
 return !!req.headers.get('oai-authenticated-user-id');
}
async function board(){const db=database();await db.prepare('INSERT OR IGNORE INTO map_board(id,config) VALUES(1,?)').bind(JSON.stringify(DEFAULT_CONFIG)).run();return (await db.prepare('SELECT * FROM map_board WHERE id=1').first())!}
function decode(c:Row){const {provenance:_provenance,...rest}=c;return {...rest,id:Number(c.id),algorithm:Math.floor(Number(c.id)/32)+1,slot:Number(c.id)%32,patch:parse(c.patch),state:parse(c.state),reference:parse(c.reference),seeds:parse(c.seeds)}}
function cellId(v:unknown){if(!Number.isInteger(v)||Number(v)<0||Number(v)>1023)throw Error('Choose an algorithm and slice from 1 to 32.');return Number(v)}
function rowPatch(raw:unknown,id:number){const p=validatePatch(raw);if(p.algorithm!==Math.floor(id/32)+1)throw Error('A patch must use the cell’s row algorithm.');return p}
function workerId(v:unknown){if(typeof v!=='string'||!v.trim()||v.length>150)throw Error('Invalid worker.');return v}
async function summaries(){return (await database().prepare('SELECT id,target_key,visits,evaluations,model_score,native_score,native_loss,updated_at,revision,failed_until,last_error FROM map_cells').all()).results}
function owned(b:Row,x:{id:unknown;worker:unknown;generation:unknown}){return !!b.running&&b.active_id===x.id&&b.lease_owner===x.worker&&b.generation===x.generation&&Number(b.lease_until)>Date.now()}
const guard='EXISTS(SELECT 1 FROM map_board WHERE id=1 AND lease_owner=? AND generation=? AND running=1 AND active_id=? AND lease_until>?)';
async function heartbeat(worker:string,status:Record<string,unknown>={}){const engine=JSON.stringify({engine:'Dexed Mark I',priority:String(status.priority??'BelowNormal').slice(0,20),phase:String(status.phase??'Scanning').slice(0,80),localPaused:status.localPaused===true,cellsPerMinute:Math.max(0,Math.min(100000,Number(status.cellsPerMinute)||0))});await database().prepare('INSERT INTO workers(id,last_seen,engine) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,engine=excluded.engine').bind(worker,Date.now(),engine).run()}
function validateCheckpoint(x:Record<string,any>,id:number,config:Record<string,any>,key:string,old:Row|undefined){
 const s=x.state,r=x.reference;
 if(!s||s.model!==MODEL||s.algorithm!==Math.floor(id/32)+1||targetKey(s.shape)!==key||s.harmonics!==config.harmonics||s.allowDetune!==config.allowDetune||!Number.isSafeInteger(s.evaluations)||s.evaluations<1||!Array.isArray(s.elites)||s.elites.length<1||s.elites.length>16||!Array.isArray(s.history)||s.history.length>120||!Array.isArray(s.nativeSeeds)||s.nativeSeeds.length>64)throw Error('Invalid cell checkpoint.');
 for(const e of s.elites){rowPatch(e.patch,id);if(!Number.isFinite(e.loss)||e.loss<0||e.loss>5||!Number.isFinite(e.score)||e.score<0||e.score>1)throw Error('Invalid candidate score.')}
 if(s.elites.some((e:{loss:number})=>e.loss<s.elites[0].loss))throw Error('The best candidate must come first.');
 s.nativeSeeds.forEach((p:unknown)=>rowPatch(p,id));rowPatch(r?.patch,id);
 if(r.engine!=='Dexed Mark I / native'||!Number.isFinite(r.loss)||r.loss<0||r.loss>1||!Number.isFinite(r.score)||r.score<0||r.score>1||!Array.isArray(r.notes)||r.notes.length!==3||!r.notes.every((n:{note:number;score:number;error:number;wave:number[];target:number[]},i:number)=>n.note===[45,57,69][i]&&Number.isFinite(n.score)&&n.score>=0&&n.score<=1&&Number.isFinite(n.error)&&n.error>=0&&n.error<=1&&Array.isArray(n.wave)&&Array.isArray(n.target)&&n.wave.length<=512&&n.target.length===n.wave.length&&[...n.wave,...n.target].every(Number.isFinite)))throw Error('Invalid native measurement.');
 if(Math.abs(r.score-Math.min(...r.notes.map((n:{score:number})=>n.score)))>1e-12||Math.abs(r.loss-Math.max(...r.notes.map((n:{error:number})=>n.error*n.error)))>1e-12)throw Error('Native measurement totals must agree with the notes.');
 const current=old?.target_key===key,oldState=parse(old?.state);
 if(current&&(s.evaluations<Number(old?.evaluations)||s.evaluations>Number(old?.evaluations)+100000||(oldState&&s.elites[0].loss>oldState.elites[0].loss+1e-12)||(old?.native_loss!==null&&r.loss>Number(old?.native_loss)+1e-12)))throw Error('A checkpoint cannot discard a better solution.');
 return {s,r,current};
}
export async function GET(req:Request){try{
 if(!await auth(req))return json({error:'Sign in to load your table.'},401);
 const b=await board(),config=parse(b.config),targets=columnTargets(config),keys=targets.map(targetKey),url=new URL(req.url),db=database();
 if(url.searchParams.has('cell')){const id=cellId(Number(url.searchParams.get('cell'))),c=await db.prepare('SELECT * FROM map_cells WHERE id=?').bind(id).first();return json({cell:c?{...decode(c),current:c.target_key===keys[id%32]}:null,config,revision:b.revision,target:targets[id%32]})}
 if(url.searchParams.has('export')){
  // Compact, self-contained results: no search history or captured audio is needed to resume.
  const cells=(await db.prepare("SELECT id,patch,target_key,model_score,native_score,native_loss,evaluations,visits,json_extract(reference,'$.patch') AS native_patch,json_extract(reference,'$.testedAt') AS tested_at,json_extract(reference,'$.notes[0].score') AS score_a2,json_extract(reference,'$.notes[1].score') AS score_a3,json_extract(reference,'$.notes[2].score') AS score_a4 FROM map_cells ORDER BY id").all()).results.map(c=>({id:c.id,algorithm:Math.floor(Number(c.id)/32)+1,slot:Number(c.id)%32,patch:parse(c.patch),reference:c.native_patch?{patch:parse(c.native_patch),score:Number(c.native_score),loss:Number(c.native_loss),testedAt:c.tested_at,notes:[45,57,69].map((note,i)=>({note,score:Number(c[['score_a2','score_a3','score_a4'][i]])}))}:null,modelScore:c.model_score===null?null:Number(c.model_score),current:c.target_key===keys[Number(c.id)%32]}));
  return json({format:'dexfraggler-table',version:3,config,targets,model:MODEL,cells});
 }
 const [cells,workers]=await Promise.all([summaries(),db.prepare('SELECT * FROM workers ORDER BY last_seen DESC LIMIT 4').all()]);
 const activeId=Number(b.lease_until)>Date.now()?Number(b.active_id):null;
 return json({config,revision:b.revision,generation:b.generation,running:!!b.running,activeId,activeIds:activeId===null?[]:Array.from({length:32},(_,i)=>Math.floor(activeId/32)*32+i),cells:cells.map(c=>({...c,current:c.target_key===keys[Number(c.id)%32],target_key:undefined})),workers:workers.results.map(w=>({...w,status:String(w.engine).startsWith('{')?parse(w.engine):null}))});
 }catch(e){return json({error:e instanceof Error?e.message:'Table unavailable.'},400)}}
export async function POST(req:Request){try{
 if(!await auth(req))return json({error:'Sign in to change your table.'},401);
 const origin=req.headers.get('origin');if(origin&&origin!==new URL(req.url).origin)return json({error:'Origin is not allowed.'},403);
 if(Number(req.headers.get('content-length'))>4000000)return json({error:'Send a smaller batch.'},413);
 const text=await req.text();if(text.length>4000000)return json({error:'Send a smaller batch.'},413);
 const x=JSON.parse(text),db=database(),b=await board(),config=parse(b.config);
 if(x.action==='heartbeat'){await heartbeat(workerId(x.worker),x.status);return json({ok:true})}
 if(x.action==='running'){if(typeof x.running!=='boolean')throw Error('Running must be true or false.');await db.prepare('UPDATE map_board SET running=?,revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1').bind(x.running?1:0).run();return json({ok:true})}
 if(x.action==='configure'){const next=validateConfig(x.config);columnTargets(next);if(x.revision!==b.revision)return json({error:'Table changed; reload before changing anchors.'},409);const r=await db.prepare('UPDATE map_board SET config=?,generation=generation+1,revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1 AND revision=?').bind(JSON.stringify(next),b.revision).run();return r.meta.changes?json({ok:true}):json({error:'Table changed; reload.'},409)}
 const targets=columnTargets(config),keys=targets.map(targetKey);
 if(x.action==='renew'){
  if(!owned(b,x))return json({error:'This search batch was superseded.'},409);
  const r=await db.prepare('UPDATE map_board SET lease_until=? WHERE id=1 AND '+guard).bind(Date.now()+120000,x.worker,x.generation,x.id,Date.now()).run();
  return r.meta.changes?json({ok:true,running:true}):json({error:'This search batch was superseded.'},409);
 }
 if(x.action==='claim'||x.action==='claim_row'){
  workerId(x.worker);if(x.action==='claim_row')await heartbeat('Windows tray runner',x.status);
  if(!b.running||Number(b.lease_until)>Date.now())return json({job:null,running:!!b.running});
  const id=scheduleCell(await summaries(),config,keys),now=Date.now();if(id===null)return json({job:null,running:!!b.running});
  const r=await db.prepare('UPDATE map_board SET lease_owner=?,lease_until=?,active_id=? WHERE id=1 AND running=1 AND generation=? AND lease_until<?').bind(x.worker,now+(x.action==='claim_row'?120000:60000),id,b.generation,now).run();if(!r.meta.changes)return json({job:null,running:!!b.running});
  const first=Math.floor(id/32)*32,cells=(await db.prepare('SELECT * FROM map_cells WHERE id>=? AND id<? ORDER BY id').bind(first,first+32).all()).results.map(c=>({...decode(c),current:c.target_key===keys[Number(c.id)%32]}));
  const job={id,algorithm:Math.floor(id/32)+1,slot:id%32,generation:b.generation,config};
  if(x.action==='claim_row')return json({job:{...job,targets,targetKeys:keys,cells}});
  const neighbors=cells.filter(c=>c.id!==id).sort((a,c)=>Math.abs(a.id-id)-Math.abs(c.id-id)).slice(0,6).map(c=>({id:c.id,patch:c.reference?.patch??c.patch}));
  return json({job:{...job,target:targets[id%32],targetKey:keys[id%32],cell:cells.find(c=>c.id===id)??null,neighbors}});
 }
 if(x.action==='checkpoint'||x.action==='checkpoint_row'){
  const focus=cellId(x.id);if(!owned(b,x))return json({error:'This search batch was superseded.'},409);
  const batch=x.action==='checkpoint'?[{...x,visited:true}]:x.cells;
  if(!Array.isArray(batch)||batch.length<1||batch.length>32)throw Error('Checkpoint 1–32 cells in one algorithm row.');
  const ids=batch.map((c:{id:unknown})=>cellId(c.id));if(new Set(ids).size!==ids.length||ids.some(id=>Math.floor(id/32)!==Math.floor(focus/32)))throw Error('Checkpoint cells must be unique and in the active row.');
  const first=Math.floor(focus/32)*32,oldRows=(await db.prepare('SELECT * FROM map_cells WHERE id>=? AND id<?').bind(first,first+32).all()).results;
  const now=Date.now(),statements=batch.map((c:Record<string,any>)=>{
   const id=cellId(c.id),old=oldRows.find(row=>row.id===id),{s,r,current}=validateCheckpoint(c,id,config,keys[id%32],old);
   if(c.visited!==undefined&&typeof c.visited!=='boolean')throw Error('Invalid visit flag.');
   if(c.consumedSeeds!==undefined&&(!Array.isArray(c.consumedSeeds)||c.consumedSeeds.length>64))throw Error('Invalid consumed seeds.');
   const consumed=new Set((c.consumedSeeds??[]).map((p:unknown)=>JSON.stringify(rowPatch(p,id))));
   const pending=(parse(old?.seeds)??[]).filter((p:unknown)=>!consumed.has(JSON.stringify(rowPatch(p,id))));
   return db.prepare('INSERT INTO map_cells(id,patch,state,reference,target_key,visits,evaluations,model_score,native_score,native_loss,updated_at,revision) SELECT ?,?,?,?,?,?,?,?,?,?,?,1 WHERE '+guard+' ON CONFLICT(id) DO UPDATE SET patch=excluded.patch,state=excluded.state,reference=excluded.reference,target_key=excluded.target_key,visits=excluded.visits,evaluations=excluded.evaluations,model_score=excluded.model_score,native_score=excluded.native_score,native_loss=excluded.native_loss,updated_at=excluded.updated_at,revision=map_cells.revision+1,seeds=?,failed_until=0,last_error=NULL').bind(id,JSON.stringify(s.elites[0].patch),JSON.stringify(s),JSON.stringify(r),keys[id%32],(current?Number(old?.visits):0)+(c.visited?1:0),s.evaluations,String(s.elites[0].score),String(r.score),String(r.loss),now,x.worker,x.generation,focus,now,JSON.stringify(pending));
  });
  statements.push(db.prepare('UPDATE map_board SET revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1 AND '+guard).bind(x.worker,x.generation,focus,now));
  const results=await db.batch(statements);return results[0].meta.changes?json({ok:true,count:batch.length}):json({error:'Checkpoint superseded.'},409);
 }
 if(x.action==='release'){
  if(!owned(b,x))return json({error:'Batch superseded.'},409);
  await db.prepare('UPDATE map_board SET lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1 AND '+guard).bind(x.worker,x.generation,x.id,Date.now()).run();return json({ok:true});
 }
 if(x.action==='failed'){
  const id=cellId(x.id);if(!owned(b,x))return json({error:'Batch superseded.'},409);
  const old=await db.prepare('SELECT patch FROM map_cells WHERE id=?').bind(id).first(),patch=blank();patch.algorithm=Math.floor(id/32)+1;
  await db.batch([db.prepare('INSERT INTO map_cells(id,patch,failed_until,last_error) SELECT ?,?,?,? WHERE '+guard+' ON CONFLICT(id) DO UPDATE SET failed_until=excluded.failed_until,last_error=excluded.last_error').bind(id,old?.patch??JSON.stringify(patch),Date.now()+300000,String(x.error||'Measurement failed.').slice(0,240),x.worker,x.generation,id,Date.now()),db.prepare('UPDATE map_board SET lease_owner=NULL,lease_until=0,active_id=NULL,revision=revision+1 WHERE id=1 AND '+guard).bind(x.worker,x.generation,id,Date.now())]);return json({ok:true});
 }
 if(x.action==='import'){
  if(!Array.isArray(x.cells)||x.cells.length<1||x.cells.length>64)throw Error('Import 1–64 cells per batch.');
  const cells=x.cells.map((c:{id?:number;algorithm:number;slot:number;patch:unknown})=>{if(c.id===undefined&&(!Number.isInteger(c.algorithm)||c.algorithm<1||c.algorithm>32||!Number.isInteger(c.slot)||c.slot<0||c.slot>31))throw Error('Invalid cell coordinates.');const id=cellId(c.id??(c.algorithm-1)*32+c.slot);return {id,patch:rowPatch(c.patch,id)}});
  if(new Set(cells.map((c:{id:number})=>c.id)).size!==cells.length)throw Error('Each cell may appear once per import batch.');
  const statements=cells.map((c:{id:number;patch:unknown})=>db.prepare('INSERT INTO map_cells(id,patch,seeds) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET seeds=excluded.seeds,revision=map_cells.revision+1').bind(c.id,JSON.stringify(c.patch),JSON.stringify([c.patch])));
  statements.push(db.prepare('UPDATE map_board SET revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1'));await db.batch(statements);return json({ok:true,count:cells.length});
 }
 return json({error:'Unknown table action.'},400);
 }catch(e){return json({error:e instanceof Error?e.message:'Unable to update table.'},400)}}
