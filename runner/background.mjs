// One persistent scheduler owns the whole table.
import {runTableRunner} from './table-runner.mjs';
import {localConfig,ensureLocalServer} from '../scripts/local-app.mjs';
let watchdog;
if(!process.argv[2]) {
  const config=await localConfig();
  await ensureLocalServer(config);
  let checking=false;
  watchdog=setInterval(async()=>{
    if(checking)return;checking=true;
    try{await ensureLocalServer(config);}catch(e){console.error(e.message);}finally{checking=false;}
  },30000);
  watchdog.unref();
}
await runTableRunner({configPath:process.argv[2]});
clearInterval(watchdog);
