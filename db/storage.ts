import { env } from 'cloudflare:workers';
export function database(){if(!env.DB)throw Error('Experiment storage is temporarily unavailable.');return env.DB;}
