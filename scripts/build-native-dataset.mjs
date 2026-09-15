import fs from 'node:fs/promises';
import path from 'node:path';
import {Reference} from '../runner/reference.mjs';
import {buildNativeDataset} from '../models/native-dataset.mjs';

function argument(name,fallback=null){const index=process.argv.indexOf(name);return index>=0?process.argv[index+1]??fallback:fallback}
function required(name){const value=argument(name);if(!value)throw Error(`Missing ${name}.`);return value}

const tablePath=required('--table'),outputPath=required('--out'),maxCandidates=Number(argument('--max','256')),maxBytes=Number(argument('--max-bytes',String(64*1024*1024))),includeWaveforms=!process.argv.includes('--descriptors-only');
if(!Number.isInteger(maxCandidates)||maxCandidates<1)throw Error('--max must be a positive integer.');
if(!Number.isSafeInteger(maxBytes)||maxBytes<1024)throw Error('--max-bytes must be at least 1,024.');
const table=JSON.parse(await fs.readFile(tablePath,'utf8')),reference=new Reference();
try{
 const result=await buildNativeDataset({table,reference,outputPath:path.resolve(outputPath),maxCandidates,maxBytes,includeWaveforms,log:entry=>console.log(JSON.stringify(entry))});
 console.log(JSON.stringify(result));
}finally{await reference.close()}
