import fs from 'node:fs/promises';
import {loadPredictor,predictPatch} from '../models/predictor.mjs';
import {validateTarget} from '../public/targets.mjs';

function argument(name,fallback=null){const index=process.argv.indexOf(name);return index>=0?process.argv[index+1]??fallback:fallback}
const checkpointPath=argument('--checkpoint'),targetPath=argument('--target');if(!checkpointPath||!targetPath)throw Error('Use --checkpoint predictor.json --target imported-target.json.');
const checkpoint=await loadPredictor(checkpointPath),raw=JSON.parse(await fs.readFile(targetPath,'utf8')),target=Array.isArray(raw)?validateTarget(raw[0]):validateTarget(raw);console.log(JSON.stringify({patch:predictPatch(checkpoint,target),source:'linear-predictor-v1'}));
