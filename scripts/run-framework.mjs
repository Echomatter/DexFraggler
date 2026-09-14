import {fileURLToPath} from 'node:url';
const [command,...args]=process.argv.slice(2);
if(!['dev','build','start'].includes(command))throw Error('Expected dev, build, or start.');
if(args.some(a=>/^--?(host|hostname|h)(=|$)/.test(a)))throw Error('The app binds only to this computer.');
const cli=new URL('../node_modules/vinext/dist/cli.js',import.meta.url);
process.argv=[process.execPath,fileURLToPath(cli),command,...args,
  ...(command==='build'?[]:['--hostname','127.0.0.1','--port',process.env.DEXFRAGGLER_PORT??'5173'])];
await import(cli.href);
