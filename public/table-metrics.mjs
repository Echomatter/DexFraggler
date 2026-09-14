export function tableMetrics(cells){
 const measured=cells.filter(c=>c.current&&c.native_score!==null&&Number.isFinite(Number(c.native_score)));
 const sum=measured.reduce((total,c)=>total+Number(c.native_score),0);
 return {measured:measured.length,pending:1024-measured.length,tableMatch:sum/1024,measuredMatch:measured.length?sum/measured.length:null,
  columns:Array.from({length:32},(_,slot)=>measured.filter(c=>c.id%32===slot).reduce((total,c)=>total+Number(c.native_score),0)/32)};
}
/** Equal scores share the midpoint of their ordinal positions. The color range
 * is normalized to the actual lowest/highest ranks, even for large tie groups. */
export function relativeRanks(values){
 const sorted=values.filter(Number.isFinite).slice().sort((a,b)=>a-b),ranks=new Map();
 for(let start=0;start<sorted.length;){let end=start+1;while(end<sorted.length&&sorted[end]===sorted[start])end++;ranks.set(sorted[start],(start+end-1)/2);start=end;}
 const entries=[...ranks],low=entries[0]?.[1]??0,high=entries.at(-1)?.[1]??0;
 return new Map(entries.map(([value,rank])=>[value,high===low?.5:(rank-low)/(high-low)]));
}
