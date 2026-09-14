export function localUrl(value) {
  const url=new URL(value);
  if(url.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(url.hostname)||url.username||url.password)
    throw Error('DexFraggler requires a local HTTP address.');
  return url;
}

export function localRequest(req) {
  try {
    const url=localUrl(req.url),origin=req.headers.get('origin');
    return (!origin||origin===url.origin)&&req.headers.get('sec-fetch-site')!=='cross-site';
  } catch {return false;}
}
