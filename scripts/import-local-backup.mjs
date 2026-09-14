// Restore a full migration archive into a NEW database; never overwrite results.
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {createInterface} from 'node:readline';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {openDatabase} from '../db/local.mjs';

const [source,output]=process.argv.slice(2);
if(!source||!output)throw Error('Usage: node scripts/import-local-backup.mjs <archive directory> <new.sqlite>');
const directory=path.resolve(source),filename=path.resolve(output);
const manifest=JSON.parse(await fs.readFile(path.join(directory,'manifest.json'),'utf8'));
if(manifest.version!==1||!manifest.scans.length)throw Error('Unsupported archive.');
// Validate every complete file before creating the destination.
for(const scan of manifest.scans) {
  if(path.basename(scan.file)!==scan.file)throw Error('Invalid archive filename.');
  const hash=createHash('sha256');
  for await(const chunk of createReadStream(path.join(directory,scan.file)))hash.update(chunk);
  if(hash.digest('hex')!==scan.sha256)throw Error('Archive checksum mismatch.');
}
await fs.mkdir(path.dirname(filename),{recursive:true});
const reservation=await fs.open(filename,'wx');await reservation.close();
const db=openDatabase(filename);
let count=0;
try {
  const columns=db.raw.prepare('PRAGMA table_info(map_cells)').all().map(c=>c.name);
  const insert=db.raw.prepare(`INSERT INTO map_cells(${columns.join(',')}) VALUES(${columns.map(()=>'?').join(',')})`);
  db.raw.exec('BEGIN IMMEDIATE');
  try {
    for(const scan of manifest.scans) {
      db.raw.prepare('INSERT INTO scans VALUES(?,?,?,?)').run(scan.id,scan.name,JSON.stringify(scan.config),scan.created_at);
      let rows=0;
      for await(const line of createInterface({input:createReadStream(path.join(directory,scan.file)),crlfDelay:Infinity})) {
        const cell=JSON.parse(line);
        if(cell.scan_id!==scan.id)throw Error('Mixed scan archive.');
        const values=columns.map(c=>['patch','state','reference'].includes(c)?cell[c]==null?null:JSON.stringify(cell[c]):cell[c]??null);
        insert.run(...values);
        // Verify all persisted fields, including alternate elites and captured waves.
        const stored=db.raw.prepare('SELECT * FROM map_cells WHERE scan_id=? AND id=?').get(scan.id,cell.id);
        for(let i=0;i<columns.length;i++)if(stored[columns[i]]!==values[i])throw Error('Round-trip verification failed: '+columns[i]);
        rows++;count++;
      }
      if(rows!==scan.cells)throw Error('Incomplete scan archive.');
    }
    const active=manifest.scans.find(s=>s.id===manifest.activeScanId);
    if(!active)throw Error('Missing active scan.');
    db.raw.prepare('INSERT INTO map_board(id,config,running,scan_id) VALUES(1,?,0,?)').run(JSON.stringify(active.config),active.id);
    // Seed backups come from the complete database projection, not compact exports.
    const seeds=JSON.parse(await fs.readFile(path.join(directory,'scan_seeds.json'),'utf8'));
    if(seeds.has_more||seeds.model_projection?.truncated)throw Error('Incomplete seed backup.');
    for(const row of seeds.rows) {
      const seed=Array.isArray(row)?Object.fromEntries(seeds.columns.map((c,i)=>[typeof c==='string'?c:c.name,row[i]])):row;
      db.raw.prepare('INSERT INTO scan_seeds VALUES(?,?,?,?)').run(seed.scan_id,seed.key,seed.cell_id,seed.patch);
    }
    db.raw.exec('COMMIT');
  }catch(e){db.raw.exec('ROLLBACK');throw e;}
  if(db.raw.prepare('PRAGMA integrity_check').get().integrity_check!=='ok')throw Error('SQLite integrity check failed.');
  db.raw.exec('PRAGMA wal_checkpoint(TRUNCATE)');
  console.log(JSON.stringify({verified:true,scans:manifest.scans.length,cells:count,database:filename}));
}finally{db.close();}
