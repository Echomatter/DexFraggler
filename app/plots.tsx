'use client';
import {Tabs,TabsList,TabsTrigger} from '@/components/ui/tabs';
import {Select,SelectContent,SelectItem,SelectTrigger,SelectValue} from '@/components/ui/select';
import {algorithms} from '@/public/core.mjs';
export type Patch={algorithm:number;feedback:number;operators:{op:number;coarse:number;fine:number;level:number;mode:number;detune:number}[]};
export function Choice({value,onChange,items,label}:{value:string;onChange:(x:string)=>void;items:{value:string;label:string}[];label:string}){
 return <Select value={value} onValueChange={onChange}><SelectTrigger aria-label={label}><SelectValue/></SelectTrigger><SelectContent>{items.map(x=><SelectItem key={x.value} value={x.value}>{x.label}</SelectItem>)}</SelectContent></Select>;
}
export function Scope({wave,target}:{wave:number[];target:number[]}){
 const max=Math.max(1,...wave.map(Math.abs),...target.map(Math.abs))*1.17;
 const points=(a:number[])=>a.map((x,i)=>(i/(a.length-1)*1000)+','+(150-x/max*150)).join(' ');
 return <><svg viewBox="0 0 1000 300" role="img" aria-label="Two cycles: mathematical target in amber, candidate in green"><defs><pattern id="scope-grid" width="50" height="50" patternUnits="userSpaceOnUse"><path d="M50 0H0V50" fill="none" stroke="#42513e" strokeWidth=".65"/></pattern></defs><rect width="1000" height="300" fill="url(#scope-grid)"/><path d="M0 150H1000" stroke="#68745d" strokeWidth=".7"/><polyline points={points(target)} fill="none" stroke="#e5b06a" strokeWidth="2" strokeDasharray="5 4"/><polyline points={points(wave)} fill="none" stroke="#bdde9a" strokeWidth="2.2"/></svg><div className="axis"><span>0</span><span>1 cycle</span><span>2 cycles</span></div></>;
}
export function Routing({patch}:{patch:Patch}){
 const spec=algorithms[patch.algorithm-1],depth=Array(6).fill(0);
 for(let i=0;i<6;i++)for(const [a,b] of spec.edges)if(a===i)depth[a]=Math.max(depth[a],depth[b]+1);
 const max=Math.max(...depth,1),pos=(i:number)=>({x:40+i*70,y:30+(max-depth[i])*125/max});
 return <svg className="routing" viewBox="0 0 430 205" role="img" aria-label={'DX7 algorithm '+patch.algorithm+' routing'}>{spec.edges.map(([a,b]:number[],i:number)=>{const x=pos(a),y=pos(b);return <path key={i} d={'M'+x.x+' '+(x.y+14)+'V'+((x.y+y.y)/2)+'H'+y.x+'V'+(y.y-14)} stroke="#87977b" fill="none"/>})}{spec.carriers.map((i:number)=>{const p=pos(i);return <path key={i} d={'M'+p.x+' '+(p.y+14)+'V188H210'} stroke="#d3a66d" fill="none"/>})}{Array.from({length:6},(_,i)=>{const p=pos(i);return <g key={i}><rect x={p.x-17} y={p.y-14} width="34" height="28" rx="4" fill={spec.carriers.includes(i)?'#433d2d':'#303c2c'} stroke={spec.carriers.includes(i)?'#b59660':'#66795c'}/><text x={p.x} y={p.y+5} textAnchor="middle" fill="#dce6d3" fontSize="13">{i+1}</text></g>})}<text x="215" y="204" textAnchor="middle" fill="#a8b89c" fontSize="12">AUDIO OUT · FB {spec.feedback[0]+1} → {spec.feedback[1]+1}</text></svg>;
}

