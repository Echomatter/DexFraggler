import {database} from '@/db/storage';
import {tableSeeds} from '@/public/table-import.mjs';
import {validateConfig} from '@/public/targets.mjs';
const json=(value:unknown,status=200)=>Response.json(value,{status,headers:{'Cache-Control':'no-store'}});
const generationGuard='EXISTS(SELECT 1 FROM map_board WHERE id=1 AND generation=?)';
export async function scanAction(x:Record<string,unknown>,board:Record<string,unknown>){
 const action=typeof x.action==='string'?x.action:'';
 if(!['new_scan','switch_scan','import_seeds'].includes(action))return null;
 if(x.generation!==board.generation)return json({error:'The active scan changed. Reopen the scan dialog and try again.'},409);
  const db=database(),imported=action==='import_seeds'?tableSeeds(x.table):null;
 const create=action==='new_scan'||(imported&&x.destination==='new');
  let target:Record<string,unknown>;
 if(create){
  if(typeof x.name!=='string'||!x.name.trim()||x.name.trim().length>80)throw Error('Give the scan a name of 1–80 characters.');
   const nextConfig=imported?.config??(x.config!==undefined?validateConfig(x.config):validateConfig(JSON.parse(String(board.config))));
   target={id:crypto.randomUUID(),name:x.name.trim(),config:JSON.stringify(nextConfig),created_at:Date.now()};
 }else{
  if(typeof x.scanId!=='string')throw Error('Choose a destination scan.');
  const found=await db.prepare('SELECT * FROM scans WHERE id=?').bind(x.scanId).first();
  if(!found)throw Error('That scan no longer exists.');
  target={...found,config:found.id===board.scan_id?board.config:found.config};
 }
 const statements=[db.prepare('UPDATE scans SET config=? WHERE id=? AND '+generationGuard).bind(board.config,board.scan_id,board.generation)];
 if(create)statements.push(db.prepare('INSERT INTO scans(id,name,config,created_at) SELECT ?,?,?,? WHERE '+generationGuard).bind(target.id,target.name,target.config,target.created_at,board.generation));
 const seeds=await Promise.all((imported?.seeds??[]).map(async(seed:{id:number;patch:unknown})=>{
  const patch=JSON.stringify(seed.patch),digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(patch));
  return {cell_id:seed.id,patch,key:Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('')};
 }));
 for(let start=0;start<seeds.length;start+=64)statements.push(db.prepare("INSERT OR IGNORE INTO scan_seeds(scan_id,key,cell_id,patch) SELECT ?,json_extract(value,'$.key'),json_extract(value,'$.cell_id'),json_extract(value,'$.patch') FROM json_each(?) WHERE "+generationGuard).bind(target.id,JSON.stringify(seeds.slice(start,start+64)),board.generation));
 statements.push(db.prepare('UPDATE map_board SET scan_id=?,config=?,running=1,generation=generation+1,revision=revision+1,lease_owner=NULL,lease_until=0,active_id=NULL WHERE id=1 AND generation=?').bind(target.id,target.config,board.generation));
 const results=await db.batch(statements);
 if(!results.at(-1)?.meta.changes)return json({error:'The active scan changed. Reopen the scan dialog and try again.'},409);
 return json({ok:true,scan:{id:target.id,name:target.name},seeds:seeds.length});
}
