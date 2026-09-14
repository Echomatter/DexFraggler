import {createHash} from 'node:crypto';
import {database} from '@/db/storage';
import {localRequest} from '@/runner/local-url.mjs';
export const dynamic='force-dynamic';
export async function GET(req:Request) {
  if(!localRequest(req))return Response.json({error:'Local access only.'},{status:403});
  await database().prepare('SELECT 1').first();
  return Response.json({app:'DexFraggler',local:true,workspace:createHash('sha256').update(process.cwd()).digest('hex'),database:'ok'});
}
