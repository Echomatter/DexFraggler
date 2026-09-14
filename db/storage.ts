import {database as localDatabase} from './local.mjs';
type Row=Record<string,unknown>;
interface Result {results:Row[];success:boolean;meta:{changes:number;last_row_id?:number}}
interface Statement {
  bind(...values:unknown[]):Statement;
  first():Promise<Row|null>;
  first(column:string):Promise<unknown>;
  all():Promise<Result>;
  run():Promise<Result>;
}
interface Storage {prepare(sql:string):Statement;batch(statements:Statement[]):Promise<Result[]>}
export function database():Storage {return localDatabase();}
