// Dependency-free calculation entry point, usable in Node or a browser worker.
export * as model from '../public/core.mjs';
export * as targets from '../public/targets.mjs';
export {bankSysex,fromBank} from '../public/bank.mjs';
export {buildCorpus} from './corpus.mjs';
