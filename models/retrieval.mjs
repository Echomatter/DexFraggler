import {clone,validatePatch} from '../public/core.mjs';
import {METRIC_VERSION,coefficients,columnTargets,validateConfig} from '../public/targets.mjs';
import {keyForPatch} from './native-dataset.mjs';

export const RETRIEVAL_INDEX_VERSION='native-retrieval-index-v1';
const finite=value=>typeof value==='number'&&Number.isFinite(value);

function magnitudeDescriptor(target,note,maxHarmonics=127){
 const base=440*2**((note-69)/12),bands=Math.min(maxHarmonics,Math.ceil(48000/(2*base))-1),series=coefficients(target,bands),values=series.sin.map((value,index)=>Math.hypot(value,series.cos[index]));
 const norm=Math.hypot(...values)||1;return {note,bands,magnitude:values.map(value=>value/norm)};
}
function distance(a,b){const length=Math.min(a.magnitude.length,b.magnitude.length),missing=Math.abs(a.magnitude.length-b.magnitude.length),scale=Math.max(1,length+missing);let sum=missing;for(let i=0;i<length;i++)sum+=(a.magnitude[i]-b.magnitude[i])**2;return Math.sqrt(sum/scale)}

export function buildRetrievalIndex(dataset,{maxRecords=100000}={}){
 const records=(dataset?.records??[]).slice(0,maxRecords);if(!Array.isArray(records))throw Error('A native dataset must provide observation records.');
 const seen=new Set(),entries=[];
 for(const record of records){const patch=validatePatch(record.patch);if(record.key!==keyForPatch(patch))throw Error('A retrieval record has an invalid exact patch key.');if(seen.has(record.key))continue;seen.add(record.key);const notes=new Map((record.notes??[]).map(note=>[note.note,note.descriptor]));entries.push({key:record.key,patch:clone(patch),provenance:clone(record.provenance??[]),notes:[45,57,69].map(note=>notes.get(note)).filter(Boolean)});}
 return {format:'dexfraggler-native-retrieval-index',version:RETRIEVAL_INDEX_VERSION,metricVersion:METRIC_VERSION,descriptorVersion:dataset.descriptorVersion??'native-harmonics-v1',records:entries,createdAt:Date.now()};
}

export function retrieveCandidates(index,target,algorithm,{limit=8,notes=[45,57,69]}={}){
 if(!index||index.format!=='dexfraggler-native-retrieval-index'||index.version!==RETRIEVAL_INDEX_VERSION)throw Error('Choose a DexFraggler native retrieval index.');
 if(!Number.isInteger(algorithm)||algorithm<1||algorithm>32||!Number.isInteger(limit)||limit<1||limit>64)throw Error('Choose a legal algorithm and retrieval limit.');
 const queries=notes.map(note=>magnitudeDescriptor(target,note)),scored=index.records.filter(record=>record.patch.algorithm===algorithm).map(record=>{
  const available=queries.map(query=>record.notes.find(observation=>observation.note===query.note)).filter(Boolean),error=available.length?queries.reduce((sum,query)=>sum+distance(query,record.notes.find(observation=>observation.note===query.note)??{magnitude:[]}),0)/queries.length:Infinity;
  return {key:record.key,patch:clone(record.patch),distance:error,provenance:clone(record.provenance)};
 }).filter(result=>finite(result.distance)).sort((a,b)=>a.distance-b.distance||a.key.localeCompare(b.key));
 return scored.slice(0,limit);
}

/** Add native-retrieved proposals to empty cells in an exported table.
 * Existing patches and references are never overwritten. The runner then
 * treats these as legal seeds and still measures every proposal natively. */
export function addRetrievalSeeds(table,index,{perAlgorithm=8}={}){
 if(!table||table.format!=='dexfraggler-table')throw Error('Choose a DexFraggler table export.');
 const config=validateConfig(table.config),targets=columnTargets(config);if(!Array.isArray(table.cells))throw Error('A table export must contain cells.');
 const cells=table.cells.map(cell=>clone(cell)),occupied=new Set(cells.map(cell=>cell.id)),added=[];
 for(let algorithm=1;algorithm<=32;algorithm++){
  const available=Array.from({length:32},(_,slot)=>(algorithm-1)*32+slot).filter(id=>!occupied.has(id));
  if(!available.length)continue;
  const candidates=new Map();
  for(let slot=0;slot<32;slot++)for(const result of retrieveCandidates(index,targets[slot],algorithm,{limit:perAlgorithm}))if(!candidates.has(result.key))candidates.set(result.key,result);
  let cursor=0;for(const result of candidates.values()){if(cursor>=available.length)break;const id=available[cursor++],slot=id%32;cells.push({id,algorithm,slot,patch:result.patch,retrieval:{distance:result.distance,source:'native-retrieval-index-v1'}});occupied.add(id);added.push({id,key:result.key,distance:result.distance});}
 }
 return {...clone(table),cells:cells.sort((a,b)=>a.id-b.id),retrieval:{version:RETRIEVAL_INDEX_VERSION,added}};
}

export {magnitudeDescriptor,distance};
