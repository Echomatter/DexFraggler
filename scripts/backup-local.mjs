import path from 'node:path';
import {database} from '../db/local.mjs';
const output=process.argv[2];
if(!output)throw Error('Usage: node scripts/backup-local.mjs <new-backup.sqlite>');
const db=database();
try {db.raw.prepare('VACUUM INTO ?').run(path.resolve(output));console.log('Complete scan database backed up to '+path.resolve(output));}
finally{db.close();}
