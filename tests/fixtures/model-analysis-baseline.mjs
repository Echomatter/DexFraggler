// Frozen pre-preparation objective used as an independent parity oracle. Keep
// its per-target transform and operation ordering when optimizing production.
import {fft,targetWave} from '../../public/core.mjs';
import {targetKey} from '../../public/targets.mjs';
const targets=new Map();
export function analyzeBaseline(wave,target,h=127){
  const n=wave.length,key=[targetKey(target),h,n].join(':');
  if(!targets.has(key)){
    const wave=targetWave(target,h,n),re=Float64Array.from(wave),im=new Float64Array(n);
    const energy=wave.reduce((a,b)=>a+b*b,0);fft(re,im);targets.set(key,{re,im,energy});
  }
  const t=targets.get(key),mean=wave.reduce((a,b)=>a+b,0)/n;
  const centered=Float64Array.from(wave,x=>x-mean),energy=centered.reduce((a,b)=>a+b*b,0);
  if(energy<1e-16)return {score:0,error:1,spectralError:1,loss:1,shift:0,scale:0};
  const re=Float64Array.from(centered),im=new Float64Array(n);fft(re,im);
  const cr=new Float64Array(n),ci=new Float64Array(n);let spectral=0;
  for(let k=0;k<n;k++){
    cr[k]=re[k]*t.re[k]+im[k]*t.im[k];ci[k]=im[k]*t.re[k]-re[k]*t.im[k];
    spectral+=(Math.hypot(re[k],im[k])/Math.sqrt(energy)-Math.hypot(t.re[k],t.im[k])/Math.sqrt(t.energy))**2;
  }
  fft(cr,ci,true);let shift=0,corr=-Infinity;
  for(let i=0;i<n;i++)if(cr[i]>corr){corr=cr[i];shift=i}
  const score=Math.max(0,Math.min(1,corr/Math.sqrt(energy*t.energy))),error=Math.sqrt(Math.max(0,1-score*score));
  return {score,error,spectralError:Math.sqrt(spectral/n),loss:.85*error*error+.15*spectral/n,shift,scale:corr/energy};
}
