#!/usr/bin/env python3
"""Fetch an explicit public-only source plan; preserve all bytes and errors."""
import argparse, concurrent.futures as cf, datetime as dt, hashlib, json, pathlib, re, urllib.parse, urllib.request
ALLOWED={'www.twse.com.tw','openapi.twse.com.tw','www.tpex.org.tw','mops.twse.com.tw','mopsov.twse.com.tw','finance.yahoo.com','tw.stock.yahoo.com','www.yuantaetfs.com'}
def digest(b):return hashlib.sha256(b).hexdigest()
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()
def run(plan,out):
 out=pathlib.Path(out)
 if out.exists():raise ValueError('OUTPUT_EXISTS')
 out.mkdir(parents=True);started=stamp();jobs=json.loads(pathlib.Path(plan).read_text())
 if len(jobs)>20 or len({j['name'] for j in jobs})!=len(jobs):raise ValueError('PLAN_LIMIT_OR_DUPLICATE')
 for j in jobs:
  u=urllib.parse.urlsplit(j['url'])
  if u.scheme!='https' or u.hostname not in ALLOWED or u.username or u.password or not re.fullmatch(r'[A-Za-z0-9_.-]+',j['name']):raise ValueError('PUBLIC_PLAN_REJECTED')
 def get(j):
  r=dict(j,retrieved_at=None,status='FAILED')
  try:
   req=urllib.request.Request(j['url'],headers={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/html'})
   with urllib.request.urlopen(req,timeout=20) as h:
    b=h.read(15000001);r['http_status']=h.status;r['content_type']=h.headers.get('Content-Type');r['final_url']=h.geturl()
   if len(b)>15000000:raise ValueError('SOURCE_TOO_LARGE')
   (out/j['name']).write_bytes(b);r.update(status='FETCHED',retrieved_at=stamp(),bytes=len(b),sha256=digest(b))
   try:
    p=json.loads(b);r['parsed_type']=type(p).__name__
    if isinstance(p,dict):r['payload_status']=p.get('stat');r['payload_title']=p.get('title');r['date']=p.get('date');r['range']=[p.get('strDate'),p.get('endDate')]
   except Exception:r['parsed_type']='text'
  except Exception as e:r['error']=type(e).__name__+': '+str(e)
  return r
 with cf.ThreadPoolExecutor(max_workers=3)as pool:results=list(pool.map(get,jobs))
 receipt={'started_at':started,'completed_at':stamp(),'sources':results,'transport_complete':bool(results) and all(r['status']=='FETCHED' for r in results),'formal_input_qualified':False,'scope':'Source retrieval only. No inferred prices or model/portfolio operations.'}
 (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
 print(json.dumps({'completed_at':receipt['completed_at'],'transport_complete':receipt['transport_complete'],'sources':[{'name':s['name'],'status':s['status'],'error':s.get('error')} for s in results],'formal_input_qualified':False},ensure_ascii=False));return receipt
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--plan',required=True);p.add_argument('--out',required=True);a=p.parse_args();r=run(a.plan,a.out);raise SystemExit(0 if r['transport_complete'] else 2)
