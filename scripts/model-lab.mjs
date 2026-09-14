import fs from 'node:fs/promises';
import {model,targets,buildCorpus} from '../models/index.mjs';

const help=`DexFraggler calculation lab (no Site account required)

  node scripts/model-lab.mjs score [--patch patch.json] [--shape sine|triangle|square|saw]
       [--target target.json] [--native] [--out result.json]
  node scripts/model-lab.mjs corpus --table table.json --out corpus.json

score defaults to the initial sine patch and the sine target. --target accepts
an exact four-weight ideal target instead of --shape. --native independently
measures A2/A3/A4 with the native renderer. DEXFRAGGLER_NATIVE_EXE selects a build.
Output files are created exclusively; choose a new path to keep older results.
corpus retains the full input table and indexes every supplied champion/elite.
`;

async function main(){
  const [command,...args]=process.argv.slice(2);
  if(!command||command==='--help'||command==='help'){console.log(help);return;}
  if(!['score','corpus'].includes(command))throw Error('Expected score or corpus. Use --help.');
  const values={},allowed=new Set(command==='score'?['--patch','--shape','--target','--native','--out']:['--table','--out']);
  for(let i=0;i<args.length;i++){
    const flag=args[i];
    if(!allowed.has(flag)||Object.hasOwn(values,flag))throw Error(`Unknown or repeated option: ${flag}`);
    if(flag==='--native'){values[flag]=true;continue;}
    if(!args[i+1]||args[i+1].startsWith('--'))throw Error(`Missing value for ${flag}`);
    values[flag]=args[++i];
  }
  const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
  let result;
  if(command==='corpus'){
    if(!values['--table']||!values['--out'])throw Error('corpus requires --table and --out.');
    result=buildCorpus(await read(values['--table']));
  }else{
    if(values['--shape']&&values['--target'])throw Error('Choose --shape or --target.');
    const patch=model.validatePatch(values['--patch']?await read(values['--patch']):model.blank());
    const target=values['--target']?targets.validateTarget(await read(values['--target'])):targets.idealTarget(values['--shape']??'sine');
    result={format:'dexfraggler-calculation',version:1,modelVersion:model.MODEL,
      targetVersion:targets.TARGET_VERSION,metricVersion:targets.METRIC_VERSION,patch,target,
      proposalModel:model.evaluate(patch,target),nativeMeasurement:null};
    if(values['--native']){
      const {Reference}=await import('../runner/reference.mjs');
      const reference=new Reference();
      try{result.nativeMeasurement=await reference.score(patch,target);}
      finally{await reference.close();}
    }
  }
  const json=JSON.stringify(result,null,2)+'\n';
  if(values['--out']){
    await fs.writeFile(values['--out'],json,{flag:'wx'});
    console.log(JSON.stringify({output:values['--out'],format:result.format,...(result.candidates?{cells:result.sourceTable.cells.length,candidates:result.candidates.length}:{})}));
  }else process.stdout.write(json);
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
