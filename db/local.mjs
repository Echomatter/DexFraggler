import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';

// The API's prepared statements retain their D1 shape, backed by local SQLite.
export function openDatabase(filename, {migrationsDir = path.resolve('drizzle')} = {}) {
  fs.mkdirSync(path.dirname(filename), {recursive:true});
  const raw = new DatabaseSync(filename);
  try {
    raw.exec('PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;');
    raw.exec('CREATE TABLE IF NOT EXISTS _local_migrations(name TEXT PRIMARY KEY, sha256 TEXT NOT NULL)');
    for (const name of fs.readdirSync(migrationsDir).filter(n=>/^\d+.*\.sql$/.test(n)).sort()) {
      const sql=fs.readFileSync(path.join(migrationsDir,name),'utf8');
      const hash=createHash('sha256').update(sql.replace(/\r\n/g,'\n')).digest('hex');
      const applied=raw.prepare('SELECT sha256 FROM _local_migrations WHERE name=?').get(name);
      if(applied) {if(applied.sha256!==hash)throw Error('Applied migration changed: '+name);continue;}
      raw.exec('BEGIN IMMEDIATE');
      try {raw.exec(sql);raw.prepare('INSERT INTO _local_migrations VALUES(?,?)').run(name,hash);raw.exec('COMMIT');}
      catch(e){raw.exec('ROLLBACK');throw e;}
    }
  } catch(e) {raw.close();throw e;}
  class Statement {
    constructor(sql,values=[]) {this.sql=sql;this.values=values;}
    bind(...values) {return new Statement(this.sql,values);}
    async first(column) {const row=raw.prepare(this.sql).get(...this.values);return column?row?.[column]??null:row??null;}
    async all() {return {results:raw.prepare(this.sql).all(...this.values),success:true,meta:{changes:0}};}
    execute() {const r=raw.prepare(this.sql).run(...this.values);return {results:[],success:true,meta:{changes:Number(r.changes),last_row_id:Number(r.lastInsertRowid)}};}
    async run() {return this.execute();}
  }
  return {raw,filename,prepare:sql=>new Statement(sql),close:()=>raw.close(),
    async batch(statements) {
      raw.exec('BEGIN IMMEDIATE');
      try {const results=statements.map(s=>s.execute());raw.exec('COMMIT');return results;}
      catch(e) {raw.exec('ROLLBACK');throw e;}
    }
  };
}

export function database() {
  const key=Symbol.for('dexfraggler.local.database');
  return globalThis[key]??=openDatabase(path.join(process.env.DEXFRAGGLER_DATA_DIR??path.resolve('.runtime/local'),'dexfraggler.sqlite'));
}
