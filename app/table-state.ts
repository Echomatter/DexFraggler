'use client';
import {useState,useEffect,useCallback,useRef,useMemo} from 'react';
import {DEFAULT_CONFIG,columnTargets} from '@/public/targets.mjs';
import type {Patch} from './plots';
import {registerTableTools} from './table-tools';
export type Target={kind:string;weights:number[]};
export type Anchor={slot:number;shape:string};
export type Config={allowDetune:boolean;anchors:Anchor[]};
export type Summary={id:number;current:boolean;visits:number;evaluations:number;model_score:string|null;native_score:string|null;native_loss:string|null;revision:number;updated_at:number;last_error?:string|null};
export type Measurement={note:number;score:number;error:number;wave:number[];target:number[];idealTarget:number[];phase:number;bands:number};
export type Result={patch:Patch;score:number;loss:number;error?:number;source?:string};
export type Cell={id:number;patch:Patch;target_key:string;state:{elites:Result[];evaluations:number;history:{at:number;error:number;score:number}[]}|null;reference:Result&{notes:Measurement[];testedAt:number;engine:string}|null;current?:boolean};
export type Data={scan:{id:string;name:string};pendingSeeds:number;config:Config;revision:number;generation:number;running:boolean;activeId:number|null;activeIds?:number[];cells:Summary[];workers:{id:string;last_seen:number;engine:string;status?:{cellsPerMinute?:number;priority?:string;phase?:string;localPaused?:boolean}}[]};
export const pad=(n:number)=>String(n).padStart(2,'0');
export function download(data:BlobPart,name:string,type='application/json'){const url=URL.createObjectURL(new Blob([data],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
export function useTable(){
 const [selected,setSelected]=useState(0),[data,setData]=useState<Data|null>(null),[cell,setCell]=useState<Cell|null>(null),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[now,setNow]=useState(0),selection=useRef(0),dataRef=useRef<Data|null>(null);
 // Initialize from the URL after mount so server and browser markup remain identical.
 // eslint-disable-next-line react-hooks/set-state-in-effect
 useEffect(()=>{const id=Number(new URL(location.href).searchParams.get('cell'));if(Number.isInteger(id)&&id>=0&&id<1024){setSelected(id);selection.current=id}},[]);
 const select=useCallback((id:number)=>{id=Math.max(0,Math.min(1023,id));selection.current=id;setSelected(id);const url=new URL(location.href);url.searchParams.set('cell',String(id));history.replaceState(null,'',url)},[]);
 const load=useCallback(async()=>{const r=await fetch('/api/table',{cache:'no-store'}),d=await r.json() as Data&{error:string};if(!r.ok)throw Error(d.error);const next=dataRef.current&&dataRef.current.revision>d.revision?dataRef.current:d;dataRef.current=next;setData(next);setNow(Date.now());return next},[]);
 const action=useCallback(async(body:Record<string,unknown>)=>{const r=await fetch('/api/table',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),d=await r.json() as {error:string};if(!r.ok)throw Error(d.error);return load()},[load]);
 const perform=async(body:Record<string,unknown>,message='Saved')=>{setBusy(true);setError('');try{const d=await action(body);setNotice(message);return d}catch(e){setError((e as Error).message);throw e}finally{setBusy(false)}};
 useEffect(()=>{const context=(document as Document&{modelContext?:{registerTool:(tool:unknown,options:unknown)=>unknown}}).modelContext;if(context)return registerTableTools(context,load,action,select,()=>selection.current)},[load,action,select]);
 useEffect(()=>{let alive=true;const poll=()=>load().catch(e=>{if(alive)setError(e.message)});void poll();const timer=setInterval(poll,2000);return()=>{alive=false;clearInterval(timer)}},[load]);
 const revision=data?.cells.find(c=>c.id===selected)?.revision??0;
 useEffect(()=>{let alive=true;fetch('/api/table?cell='+selected,{cache:'no-store'}).then(async r=>{const d=await r.json() as {cell:Cell|null;error:string};if(!r.ok)throw Error(d.error);if(alive)setCell(d.cell)}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[selected,revision,data?.generation]);
 const config:Config=data?.config??DEFAULT_CONFIG,targets=useMemo(()=>columnTargets(config) as Target[],[config]);
 const selectedCell=cell?.id===selected?cell:null;
 return {selected,select,selection,data,cell:selectedCell,config,targets,error,setError,notice,setNotice,busy,setBusy,load,action,perform,now};
}
