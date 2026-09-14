import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {openDatabase} from '../db/local.mjs';
import {localUrl,localRequest} from '../runner/local-url.mjs';

test('SQLite persists named scans and rolls back an entire failed checkpoint batch',async()=>{
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'dexfraggler-db-')),file=path.join(folder,'test.sqlite');
  let db;
  try {
    db=openDatabase(file);
    await db.prepare('INSERT INTO scans VALUES(?,?,?,?)').bind('retained','Scan 1','{}',123).run();
    await assert.rejects(db.batch([
      db.prepare('INSERT INTO scans VALUES(?,?,?,?)').bind('partial','Must roll back','{}',124),
      db.prepare('INSERT INTO scans VALUES(?,?,?,?)').bind('retained','Duplicate','{}',125)
    ]));
    assert.equal(await db.prepare('SELECT count(*) n FROM scans').first('n'),1);
    db.close();db=openDatabase(file);
    assert.equal((await db.prepare('SELECT * FROM scans').all()).results[0].name,'Scan 1');
    assert.equal(db.raw.prepare('PRAGMA integrity_check').get().integrity_check,'ok');
  }finally{db?.close();await fs.rm(folder,{recursive:true,force:true});}
});

test('local boundaries reject remote URLs and cross-origin browser requests',()=>{
  for(const value of ['https://example.com','http://192.168.1.2','http://127.0.0.1.example.com','http://user@localhost'])assert.throws(()=>localUrl(value));
  const address='http://127.0.0.1:5173/api/table';
  assert.equal(localRequest(new Request(address)),true);
  assert.equal(localRequest(new Request(address,{headers:{origin:'http://127.0.0.1:5173'}})),true);
  assert.equal(localRequest(new Request(address,{headers:{origin:'https://example.com'}})),false);
  assert.equal(localRequest(new Request(address,{headers:{'sec-fetch-site':'cross-site'}})),false);
});
