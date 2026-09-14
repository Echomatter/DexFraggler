// One persistent scheduler owns the whole table.
import {runTableRunner} from './table-runner.mjs';
await runTableRunner({configPath:process.argv[2]});
