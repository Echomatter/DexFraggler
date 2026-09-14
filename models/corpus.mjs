import {validatePatch,sysex,clone} from '../public/core.mjs';
import {targetKey} from '../public/targets.mjs';
import {tableSeeds} from '../public/table-import.mjs';

/** Index every supplied candidate without replacing the original measurements.
 * A corpus is research input, never an authority for accepting native scores.
 */
export function buildCorpus(table){
  tableSeeds(table); // Validate the version, coordinates, targets and champions.
  const sourceTable=clone(table),candidates=new Map();
  for(const cell of sourceTable.cells){
    const currentTargetKey=targetKey(sourceTable.targets[cell.slot]);
    const savedTargetKey=typeof cell.target_key==='string'?cell.target_key:
      cell.state?.shape?targetKey(cell.state.shape):null;
    const current=cell.current??(savedTargetKey? savedTargetKey===currentTargetKey:null);
    const entries=[['model-champion',cell.patch],['native-champion',cell.reference?.patch],
      ...(cell.state?.elites??[]).map((elite,i)=>[`model-elite:${i}`,elite.patch])];
    for(const [role,raw] of entries){
      if(!raw)continue;
      const patch=validatePatch(raw);
      if(patch.algorithm!==cell.algorithm)throw Error(`Cell ${cell.id}: candidate uses a different algorithm.`);
      // Exact bytes, including silent operators. Never acoustic similarity or
      // rounded scores: those would silently merge distinct legal solutions.
      const bytes=sysex(patch),key=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
      if(!candidates.has(key))candidates.set(key,{key,patch,sysex:Array.from(bytes),origins:[]});
      const observationTargetKey=role.startsWith('model-elite:')&&cell.state?.shape
        ?targetKey(cell.state.shape):savedTargetKey??(current===true?currentTargetKey:null);
      candidates.get(key).origins.push({cellId:cell.id,slot:cell.slot,role,
        current,targetKey:observationTargetKey,currentTargetKey});
    }
  }
  return {format:'dexfraggler-calculation-corpus',version:1,
    model:sourceTable.model,targetVersion:sourceTable.targetVersion,metricVersion:sourceTable.metricVersion,
    sourceTable,candidates:[...candidates.values()]};
}
