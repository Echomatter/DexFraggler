import fs from 'node:fs/promises';
import {validatePatch} from '../public/core.mjs';
const config=JSON.parse(await fs.readFile(process.argv[3]||new URL('../.runtime/runner-config.json',import.meta.url),'utf8'));
const data=JSON.parse(await fs.readFile(process.argv[2],'utf8'));const cells=data.cells??Object.values(data.algorithms).flat();
if(!Array.isArray(cells)||cells.length>1024)throw Error('Expected a table of up to 1,024 cells.');
for(const c of cells){validatePatch(c.patch);if(c.algorithm!==c.patch.algorithm||!Number.isInteger(c.slot)||c.slot<0||c.slot>31)throw Error('Invalid cell coordinates.');}
const headers={'Content-Type':'application/json','OAI-Sites-Authorization':'Bearer '+config.bypass,'x-dexfraggler-worker':config.secret};
for(let i=0;i<cells.length;i+=64){const r=await fetch(config.url+'/api/table',{method:'POST',headers,body:JSON.stringify({action:'import',cells:cells.slice(i,i+64).map(c=>({algorithm:c.algorithm,slot:c.slot,patch:c.patch}))})});if(!r.ok)throw Error(`${r.status} ${await r.text()}`);console.log(`Imported ${Math.min(i+64,cells.length)} / ${cells.length}`)}
