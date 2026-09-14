import {scanAction} from './scans';
import {RUNNER_PROTOCOL} from '@/public/table-import.mjs';
import {localRequest} from '@/runner/local-url.mjs';
import {database} from '@/db/storage';
import {MODEL,validatePatch,blank} from '@/public/core.mjs';
import {TARGET_VERSION,METRIC_VERSION,DEFAULT_CONFIG,validateConfig,columnTargets,targetKey,scheduleCell} from '@/public/targets.mjs';
export const dynamic='force-dynamic';
type Row=Record<string,unknown>;
const json=(v:unknown,status=200)=>Response.json(v,{status,headers:{'Cache-Control':'no-store'}});
const parse=(v:unknown)=>v?JSON.parse(String(v)):null;
async function auth(req:Request){
 return localRequest(req);
}
async function board(){const db=database();await db.prepare('INSERT OR IGNORE INTO map_board(id,config) VALUES(1,?)').bind(JSON.stringify(DEFAULT_CONFIG)).run();await db.prepare("INSERT OR IGNORE INTO scans(id,name,config,created_at) SELECT scan_id,'Scan 1',config,? FROM map_board WHERE id=1").bind(Date.now()).run();return (await db.prepare('SELECT * FROM map_board WHERE id=1').first())!}
function decode(c:Row){return {...c,id:Number(c.id),algorithm:Math.floor(Number(c.id)/32)+1,slot:Number(c.id)%32,patch:parse(c.patch),state:parse(c.state),reference:parse(c.reference)}}
function cellId(v:unknown){if(!Number.isInteger(v)||Number(v)<0||Number(v)>1023)throw Error('Choose an algorithm and slice from 1 to 32.');return Number(v)}
function rowPatch(raw:unknown,id:number){const p=validatePatch(raw);if(p.algorithm!==Math.floor(id/32)+1)throw Error('A patch must use the cell’s row algorithm.');return p}
function workerId(v:unknown){if(typeof v!=='string'||!v.trim()||v.length>150)throw Error('Invalid worker.');return v}
async function summaries(scanId:unknown){return (await database().prepare('SELECT id,target_key,visits,evaluations,model_score,native_score,native_loss,updated_at,revision,failed_until,last_error FROM map_cells WHERE scan_id=?').bind(scanId).all()).results}
function owned(b:Row,x:{id:unknown;worker:unknown;generation:unknown}){return !!b.running&&b.active_id===x.id&&b.lease_owner===x.worker&&b.generation===x.generation&&Number(b.lease_until)>Date.now()}
const guard='EXISTS(SELECT 1 FROM map_board WHERE id=1 AND lease_owner=? AND generation=? AND running=1 AND active_id=? AND lease_until>?)';
async function heartbeat(worker:string,status:Record<string,unknown>={}){const engine=JSON.stringify({engine:'Dexed Mark I',priority:String(status.priority??'BelowNormal').slice(0,20),phase:String(status.phase??'Scanning').slice(0,80),localPaused:status.localPaused===true,cellsPerMinute:Math.max(0,Math.min(100000,Number(status.cellsPerMinute)||0))});await database().prepare('INSERT INTO workers(id,last_seen,engine) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,engine=excluded.engine').bind(worker,Date.now(),engine).run()}
function validateCheckpoint(x:Record<string,any>,id:number,config:Record<string,any>,key:string,old:Row|undefined){
 if(x.reference===null&&old?.target_key!==key)throw Error('An unchanged measurement must belong to the current target.');
 const s=x.state,r=x.reference===null?parse(old?.reference):x.reference;
 if(!s||s.model!==MODEL||s.algorithm!==Math.floor(id/32)+1||targetKey(s.shape)!==key||s.harmonics!==127||s.allowDetune!==config.allowDetune||!Number.isSafeInteger(s.evaluations)||s.evaluations<1||!Array.isArray(s.elites)||s.elites.length<1||s.elites.length>16||!Array.isArray(s.history)||s.history.length>120)throw Error('Invalid cell checkpoint.');
 for(const e of s.elites){rowPatch(e.patch,id);if(!Number.isFinite(e.loss)||e.loss<0||e.loss>5||!Number.isFinite(e.score)||e.score<0||e.score>1)throw Error('Invalid candidate score.')}
 if(s.elites.some((e:{loss:number})=>e.loss<s.elites[0].loss))throw Error('The best candidate must come first.');
 rowPatch(r?.patch,id);
 if(r.engine!=='Dexed Mark I / native'||r.metricVersion!==METRIC_VERSION||!Number.isFinite(r.loss)||r.loss<0||r.loss>1||!Number.isFinite(r.score)||r.score<0||r.score>1||!Array.isArray(r.notes)||r.notes.length!==3||!r.notes.every((n:{note:number;score:number;error:number;wave:number[];target:number[];idealTarget:number[];bands:number;phase:number;metricVersion:string},i:number)=>n.note===[45,57,69][i]&&n.metricVersion===METRIC_VERSION&&n.bands===[218,109,54][i]&&Number.isFinite(n.phase)&&Number.isFinite(n.score)&&n.score>=0&&n.score<=1&&Number.isFinite(n.error)&&n.error>=0&&n.error<=1&&Array.isArray(n.wave)&&Array.isArray(n.target)&&Array.isArray(n.idealTarget)&&n.idealTarget.length===n.wave.length&&n.wave.length<=512&&n.target.length===n.wave.length&&[...n.wave,...n.target,...n.idealTarget].every(Number.isFinite)))throw Error('Invalid native measurement.');
 if(Math.abs(r.score-Math.min(...r.notes.map((n:{score:number})=>n.score)))>1e-12||Math.abs(r.loss-Math.max(...r.notes.map((n:{error:number})=>n.error*n.error)))>1e-12)throw Error('Native measurement totals must agree with the notes.');
 const current=old?.target_key===key,oldState=parse(old?.state);
 if(current&&(s.evaluations<Number(old?.evaluations)||s.evaluations>Number(old?.evaluations)+100000||(oldState&&s.elites[0].loss>oldState.elites[0].loss+1e-12)||(old?.native_loss!==null&&r.loss>Number(old?.native_loss)+1e-12)))throw Error('A checkpoint cannot discard a better solution.');
 return {s,r,current};
}
export async function GET(req:Request){try{
 if(!await auth(req))return json({error:'Local access only.'},403);
 const b=await board(),config=parse(b.config),targets=columnTargets(config),keys=targets.map(targetKey),url=new URL(req.url),db=database();
 if(url.searchParams.has('scans'))return json({activeScanId:b.scan_id,generation:b.generation,scans:(await db.prepare('SELECT s.id,s.name,s.created_at,(SELECT count(*) FROM map_cells c WHERE c.scan_id=s.id) AS cells,(SELECT count(*) FROM scan_seeds q WHERE q.scan_id=s.id) AS pendingSeeds FROM scans s ORDER BY s.created_at DESC').all()).results});
 if(url.searchParams.has('cell')){const id=cellId(Number(url.searchParams.get('cell'))),c=await db.prepare('SELECT * FROM map_cells WHERE scan_id=? AND id=?').bind(b.scan_id,id).first();return json({cell:c?{...decode(c),current:c.target_key===keys[id%32]}:null,config,revision:b.revision,target:targets[id%32]})}
 if(url.searchParams.has('export')){
  // Compact, self-contained results: no search history or captured audio is needed to resume.
  const cells=(await db.prepare("SELECT id,patch,target_key,model_score,native_score,native_loss,evaluations,visits,json_extract(reference,'$.patch') AS native_patch,json_extract(reference,'$.testedAt') AS tested_at,json_extract(reference,'$.notes[0].score') AS score_a2,json_extract(reference,'$.notes[1].score') AS score_a3,json_extract(reference,'$.notes[2].score') AS score_a4 FROM map_cells WHERE scan_id=? ORDER BY id").bind(b.scan_id).all()).results.map(c=>({id:c.id,algorithm:Math.floor(Number(c.id)/32)+1,slot:Number(c.id)%32,patch:parse(c.patch),reference:c.native_patch?{patch:parse(c.native_patch),score:Number(c.native_score),loss:Number(c.native_loss),testedAt:c.tested_at,notes:[45,57,69].map((note,i)=>({note,score:Number(c[['score_a2','score_a3','score_a4'][i]])}))}:null,modelScore:c.model_score===null?null:Number(c.model_score),current:c.target_key===keys[Number(c.id)%32]}));
  const scan=await db.prepare('SELECT id,name FROM scans WHERE id=?').bind(b.scan_id).first();
  return json({scan,format:'dexfraggler-table',version:4,targetVersion:TARGET_VERSION,metricVersion:METRIC_VERSION,config,targets,model:MODEL,cells});
 }
 const scan=await db.prepare('SELECT id,name FROM scans WHERE id=?').bind(b.scan_id).first();
 const pendingSeeds=await db.prepare('SELECT count(*) AS count FROM scan_seeds WHERE scan_id=?').bind(b.scan_id).first();
 const [cells,workers]=await Promise.all([summaries(b.scan_id),db.prepare('SELECT * FROM workers ORDER BY last_seen DESC LIMIT 4').all()]);
 const activeId=Number(b.lease_until)>Date.now()?Number(b.active_id):null;
 return json({scan,pendingSeeds:Number(pendingSeeds?.count??0),config,revision:b.revision,generation:b.generation,running:!!b.running,activeId,activeIds:activeId===null?[]:Array.from({length:32},(_,i)=>Math.floor(activeId/32)*32+i),cells:cells.map(c=>({...c,current:c.target_key===keys[Number(c.id)%32],target_key:undefined})),workers:workers.results.map(w=>({...w,status:parse(w.engine)}))});
 }catch(e){return json({error:e instanceof Error?e.message:'Table unavailable.'},400)}}
export async function POST(req:Request){try{
 if(!await auth(req))return json({error:'Local access only.'},403);
 const origin=req.headers.get('origin');if(origin&&origin!==new URL(req.url).origin)return json({error:'Origin is not allowed.'},403);
 if(Number(req.headers.get('content-length'))>4000000)return json({error:'Send a smaller batch.'},413);
 const text=await req.text();if(text.length>4000000)return json({error:'Send a smaller batch.'},413);
 const x=JSON.parse(text),db=database(),b=await board(),config=parse(b.config);
 const scanResponse=await scanAction(x,b);if(scanResponse)return scanResponse;
 if(x.action==='heartbeat'){await heartbeat(workerId(x.worker),x.status);return json({ok:true})}
 if(x.action==='running'){if(typeof x.running!=='boolean')throw Error('Running must be true or false.');await db.prepare('UPDATE map_board SET running=?,revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1').bind(x.running?1:0).run();return json({ok:true})}
 if(x.action==='configure'){const next=validateConfig(x.config);columnTargets(next);if(x.revision!==b.revision)return json({error:'Table changed; reload before changing anchors.'},409);const r=await db.prepare('UPDATE map_board SET config=?,generation=generation+1,revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1 AND revision=?').bind(JSON.stringify(next),b.revision).run();return r.meta.changes?json({ok:true}):json({error:'Table changed; reload.'},409)}
 const targets=columnTargets(config),keys=targets.map(targetKey);
 if(x.action==='renew'){
  if(!owned(b,x))return json({error:'This search batch was superseded.'},409);
  const r=await db.prepare('UPDATE map_board SET lease_until=? WHERE id=1 AND '+guard).bind(Date.now()+120000,x.worker,x.generation,x.id,Date.now()).run();
  return r.meta.changes?json({ok:true,running:true}):json({error:'This search batch was superseded.'},409);
 }
 if(x.action==='claim_row'){
  if(x.protocol!==RUNNER_PROTOCOL||x.model!==MODEL||x.targetVersion!==TARGET_VERSION||x.metricVersion!==METRIC_VERSION)return json({error:'Restart DexFraggler to load the current search engine.'},409);
  workerId(x.worker);await heartbeat('Windows tray runner',x.status);
  if(!b.running||Number(b.lease_until)>Date.now())return json({job:null,running:!!b.running});
  const pending=(await db.prepare('SELECT DISTINCT cell_id FROM scan_seeds WHERE scan_id=? ORDER BY cell_id').bind(b.scan_id).all()).results;
  const rows=await summaries(b.scan_id),blocked=new Set(rows.filter(c=>Number(c.failed_until)>Date.now()).map(c=>Number(c.id)));
  const id=pending.map(c=>Number(c.cell_id)).find(id=>!blocked.has(id))??scheduleCell(rows,config,keys),now=Date.now();if(id===null)return json({job:null,running:!!b.running});
  const r=await db.prepare('UPDATE map_board SET lease_owner=?,lease_until=?,active_id=? WHERE id=1 AND running=1 AND generation=? AND lease_until<?').bind(x.worker,now+120000,id,b.generation,now).run();if(!r.meta.changes)return json({job:null,running:!!b.running});
  const first=Math.floor(id/32)*32,cells=(await db.prepare("SELECT id,patch,state,json_remove(reference,'$.notes[0].wave','$.notes[0].target','$.notes[0].idealTarget','$.notes[1].wave','$.notes[1].target','$.notes[1].idealTarget','$.notes[2].wave','$.notes[2].target','$.notes[2].idealTarget') AS reference,target_key,visits,evaluations,model_score,native_score,native_loss,updated_at,revision,failed_until,last_error FROM map_cells WHERE scan_id=? AND id>=? AND id<? ORDER BY id").bind(b.scan_id,first,first+32).all()).results.map(c=>({...decode(c),current:c.target_key===keys[Number(c.id)%32]}));
  const seeds=(await db.prepare('SELECT key,cell_id AS id,patch FROM scan_seeds WHERE scan_id=? AND cell_id>=? AND cell_id<? ORDER BY cell_id,key LIMIT 64').bind(b.scan_id,first,first+32).all()).results.map(seed=>({...seed,patch:parse(seed.patch)}));
  const job={scanId:b.scan_id,seeds,id,algorithm:Math.floor(id/32)+1,slot:id%32,generation:b.generation,config};
  return json({job:{...job,targets,targetKeys:keys,cells:cells.map(c=>({...c,reference:c.reference?{...c.reference,notes:c.reference.notes.map(({wave:_wave,target:_target,idealTarget:_ideal,...note}:Record<string,unknown>)=>note)}:null}))}});
 }
 if(x.action==='checkpoint_row'){
  const focus=cellId(x.id);if(!owned(b,x))return json({error:'This search batch was superseded.'},409);
  const batch=x.cells;
  if(!Array.isArray(batch)||batch.length<1||batch.length>32)throw Error('Checkpoint 1–32 cells in one algorithm row.');
  const ids=batch.map((c:{id:unknown})=>cellId(c.id));if(new Set(ids).size!==ids.length||ids.some(id=>Math.floor(id/32)!==Math.floor(focus/32)))throw Error('Checkpoint cells must be unique and in the active row.');
  const first=Math.floor(focus/32)*32,oldRows=(await db.prepare('SELECT * FROM map_cells WHERE scan_id=? AND id>=? AND id<?').bind(b.scan_id,first,first+32).all()).results;
  const now=Date.now(),statements=batch.map((c:Record<string,any>)=>{
   const id=cellId(c.id),old=oldRows.find(row=>row.id===id),{s,r,current}=validateCheckpoint(c,id,config,keys[id%32],old);
   if(c.visited!==undefined&&typeof c.visited!=='boolean')throw Error('Invalid visit flag.');
   return db.prepare('INSERT INTO map_cells(scan_id,id,patch,state,reference,target_key,visits,evaluations,model_score,native_score,native_loss,updated_at,revision) SELECT ?,?,?,?,?,?,?,?,?,?,?,?,1 WHERE '+guard+' ON CONFLICT(scan_id,id) DO UPDATE SET patch=excluded.patch,state=excluded.state,reference=COALESCE(excluded.reference,map_cells.reference),target_key=excluded.target_key,visits=excluded.visits,evaluations=excluded.evaluations,model_score=excluded.model_score,native_score=excluded.native_score,native_loss=excluded.native_loss,updated_at=excluded.updated_at,revision=map_cells.revision+1,failed_until=0,last_error=NULL').bind(b.scan_id,id,JSON.stringify(s.elites[0].patch),JSON.stringify(s),c.reference===null?null:JSON.stringify(r),keys[id%32],(current?Number(old?.visits):0)+(c.visited?1:0),s.evaluations,String(s.elites[0].score),String(r.score),String(r.loss),now,x.worker,x.generation,focus,now);
  });
  const consumed=x.consumedSeeds??[];if(!Array.isArray(consumed)||consumed.length>64||consumed.some(k=>typeof k!=='string'||!(/^[a-f0-9]{64}$/).test(k)))throw Error('Invalid seed acknowledgment.');
  if(consumed.length)statements.push(db.prepare('DELETE FROM scan_seeds WHERE scan_id=? AND cell_id>=? AND cell_id<? AND key IN ('+consumed.map(()=>'?').join(',')+') AND '+guard).bind(b.scan_id,first,first+32,...consumed,x.worker,x.generation,focus,now));
  statements.push(db.prepare('UPDATE map_board SET revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1 AND '+guard).bind(x.worker,x.generation,focus,now));
  const results=await db.batch(statements);return results[0].meta.changes?json({ok:true,count:batch.length}):json({error:'Checkpoint superseded.'},409);
 }
 if(x.action==='release'){
  if(!owned(b,x))return json({error:'Batch superseded.'},409);
  await db.prepare('UPDATE map_board SET lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1 AND '+guard).bind(x.worker,x.generation,x.id,Date.now()).run();return json({ok:true});
 }
 if(x.action==='failed'){
  const id=cellId(x.id);if(!owned(b,x))return json({error:'Batch superseded.'},409);
  const old=await db.prepare('SELECT patch FROM map_cells WHERE scan_id=? AND id=?').bind(b.scan_id,id).first(),patch=blank();patch.algorithm=Math.floor(id/32)+1;
  await db.batch([db.prepare('INSERT INTO map_cells(scan_id,id,patch,failed_until,last_error) SELECT ?,?,?,?,? WHERE '+guard+' ON CONFLICT(scan_id,id) DO UPDATE SET failed_until=excluded.failed_until,last_error=excluded.last_error').bind(b.scan_id,id,old?.patch??JSON.stringify(patch),Date.now()+300000,String(x.error||'Measurement failed.').slice(0,240),x.worker,x.generation,id,Date.now()),db.prepare('UPDATE map_board SET lease_owner=NULL,lease_until=0,active_id=NULL,revision=revision+1 WHERE id=1 AND '+guard).bind(x.worker,x.generation,id,Date.now())]);return json({ok:true});
 }
 return json({error:'Unknown table action.'},400);
 }catch(e){return json({error:e instanceof Error?e.message:'Unable to update table.'},400)}}
