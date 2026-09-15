import fs from 'node:fs/promises';
import path from 'node:path';
import {readNativeDataset} from '../models/native-dataset.mjs';
import {buildRetrievalIndex,addRetrievalSeeds} from '../models/retrieval.mjs';

function argument(name,fallback=null){const index=process.argv.indexOf(name);return index>=0?process.argv[index+1]??fallback:fallback}
function required(name){const value=argument(name);if(!value)throw Error(`Missing ${name}.`);return value}
const tablePath=required('--table'),datasetPath=required('--dataset'),outputPath=required('--out'),perAlgorithm=Number(argument('--per-algorithm','8'));
if(!Number.isInteger(perAlgorithm)||perAlgorithm<1||perAlgorithm>32)throw Error('--per-algorithm must be 1–32.');
const [table,dataset]=await Promise.all([fs.readFile(tablePath,'utf8').then(JSON.parse),readNativeDataset(datasetPath)]),index=buildRetrievalIndex(dataset),seeded=addRetrievalSeeds(table,index,{perAlgorithm});
const temporary=`${path.resolve(outputPath)}.${process.pid}.tmp`;await fs.writeFile(temporary,JSON.stringify(seeded,null,2)+'\n');await fs.rename(temporary,path.resolve(outputPath));
console.log(JSON.stringify({out:path.resolve(outputPath),datasetRecords:index.records.length,added:seeded.retrieval.added.length}));
