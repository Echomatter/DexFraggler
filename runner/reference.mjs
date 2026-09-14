import {spawn} from 'node:child_process';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';
import {sysex,clone,LIMITS} from '../public/core.mjs';
import {measuredScore} from './measurement.mjs';
export class Reference {
 constructor(){this.pending=[];this.healthy=true;this.child=spawn(fileURLToPath(new URL('../native/bin/DexfragglerReference.exe',import.meta.url)),[],{windowsHide:true,stdio:['pipe','pipe','pipe']});readline.createInterface({input:this.child.stdout}).on('line',line=>{const q=this.pending.shift();if(!q)return;clearTimeout(q.timer);try{const d=JSON.parse(line);if(!d.ok)q.reject(Error(d.error));else q.resolve(d)}catch(e){q.reject(e)}});this.child.on('error',e=>this.fail(e));this.child.stdin.on('error',e=>this.fail(e));this.child.on('exit',()=>this.fail(Error('Native renderer exited.')));this.child.stderr.on('data',data=>process.stderr.write(data));}
 fail(error){this.healthy=false;for(const q of this.pending){clearTimeout(q.timer);q.reject(error)}this.pending=[]}
 async render(p){if(!this.healthy)throw Error('Native renderer is unavailable.');const request=Array.from(sysex(p).slice(6,161)).join(',')+'\n';return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{this.child.kill();this.fail(Error('Native render timed out.'))},30000);this.pending.push({resolve,reject,timer});this.child.stdin.write(request)})}
 async score(p,shape,h=32){const d=await this.render(p);const notes=d.notes.map((note,i)=>measuredScore(d.waveforms[i],shape,note,h));return {engine:'Dexed Mark I / native',sampleRate:48000,velocity:100,captureSamples:4096,offsetSamples:7200,patch:clone(p),notes,loss:Math.max(...notes.map(x=>x.error**2)),score:Math.min(...notes.map(x=>x.score)),testedAt:Date.now(),binarySha256:'d67045da4b058bb1c7ff62cc347e5cfbd3ea67e260475bb10a7a00cc04d2b5e2',sourceManifest:'native/source-provenance.json'}}
 close(){this.child.stdin.end()}
}
export function nativeProposal(p,count,allowDetune=false){p=clone(p);const op=p.operators[(Math.floor(count/12))%6],step=[-1,1,-2,2,-4,4,-8,8,-12,12][count%10];const mode=count%12;if(mode<8)op.level=Math.max(0,Math.min(99,op.level+step));else if(mode===8)op.fine=Math.max(0,Math.min(99,op.fine+(Math.floor(count/72)%2?1:-1)));else if(mode===9)op.coarse=[0,1,2,3,4,5,6,7,8,9,11,13,15,19,23,31][Math.floor(count/72)%16];else if(mode===10)p.feedback=(Math.floor(count/72))%8;else if(allowDetune)op.detune=(Math.floor(count/72))%15;else op.level=Math.max(0,Math.min(99,op.level+step));return p}
