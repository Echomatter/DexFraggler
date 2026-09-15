import {MODEL,validatePatch} from './core.mjs';
import {TARGET_VERSION,METRIC_VERSION,validateConfig,columnTargets,targetKey} from './targets.mjs';
export const RUNNER_PROTOCOL='named-scans-v1';
/** Only this platform's table format supplies seeds. Scores and optimizer
 * state are never trusted; legal patches are independently measured again. */
export function tableSeeds(table){
 if(!table||table.format!=='dexfraggler-table'||table.version!==4||table.model!==MODEL||table.targetVersion!==TARGET_VERSION||table.metricVersion!==METRIC_VERSION)throw Error('Choose a version 4 DexFraggler table from this engine.');
 const config=validateConfig(table.config),targets=columnTargets(config);
 if(!Array.isArray(table.targets)||table.targets.length!==32||table.targets.some((t,i)=>targetKey(t)!==targetKey(targets[i])))throw Error('Table targets do not match its stored target set or anchors.');
 if(!Array.isArray(table.cells)||table.cells.length>1024)throw Error('A table contains at most 1,024 cells.');
 const ids=new Set(),patches=new Map();
 for(const cell of table.cells){
  if(!Number.isInteger(cell.id)||cell.id<0||cell.id>1023||ids.has(cell.id)||cell.algorithm!==Math.floor(cell.id/32)+1||cell.slot!==cell.id%32)throw Error('Invalid or duplicate cell coordinates.');
  ids.add(cell.id);
  for(const raw of [cell.patch,cell.reference?.patch].filter(Boolean)){
   const patch=validatePatch(raw);if(patch.algorithm!==cell.algorithm)throw Error('A seed must use its algorithm row.');
   const key=JSON.stringify(patch);if(!patches.has(key))patches.set(key,{id:cell.id,patch});
  }
 }
 return {config,seeds:[...patches.values()]};
}
