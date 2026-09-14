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

function rankColor(t){
 const a=t<.5?[214,69,69]:[242,201,76],b=t<.5?[242,201,76]:[31,111,235],f=t<.5?t*2:(t-.5)*2;
 return `rgb(${a.map((v,i)=>(v+(b[i]-v)*f).toFixed(3)).join(',')})`;
}
/** Derive every cell's paint from one complete table snapshot. A cell's own
 * score need not change for its rank, tooltip and color to change. */
export function tablePalette(cells,metric='native',mode='ranked'){
 const field=metric==='native'?'native_score':'model_score';
 const measured=cells.filter(c=>c.current&&c[field]!=null&&Number.isFinite(Number(c[field])));
 const values=measured.map(c=>Number(c[field])),ranks=relativeRanks(values);
 const positions=new Map();values.slice().sort((a,b)=>b-a).forEach((score,i)=>{if(!positions.has(score))positions.set(score,i+1)});
 return new Map(measured.map(c=>{
  const score=Number(c[field]),rank=ranks.get(score),value=mode==='absolute'?Math.min(1,-Math.log10(Math.max(1e-6,1-score))/6):rank;
  return [c.id,{score,rank,position:positions.get(score),total:values.length,color:rankColor(value)}];
 }));
}
