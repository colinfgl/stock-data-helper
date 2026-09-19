#!/usr/bin/env python3
"""Resume exact public inputs. No synthetic prices, portfolio or model execution."""
import argparse, concurrent.futures as cf, datetime as dt, hashlib, json, pathlib, shutil, urllib.request
from zoneinfo import ZoneInfo
from premarket_daily_inputs import official_quotes, validate_chart, get_json, date_of, InputError
TZ=ZoneInfo('Asia/Taipei')
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):
 p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()
def resume(base,out,target,symbols):
 out=pathlib.Path(out)
 if out.exists(): raise InputError('OUTPUT_MUST_BE_NEW')
 out.mkdir(parents=True);started=stamp()
 paths=list(pathlib.Path(base).rglob('acquisition_receipt.json'))
 if len(paths)!=1: raise InputError('EXACT_BASELINE_RECEIPT_REQUIRED')
 rp=paths[0];b=json.loads(rp.read_text());dates=b['dates']
 if dates['target_date']!=target: raise InputError('TARGET_MISMATCH')
 prev,cut=dates['previous_session'],dates['price_cutoff'];root=rp.parent
 records=[]
 for s in b['sources']:
  if s.get('status')!='FETCHED': continue
  name=s['path']
  if pathlib.Path(name).name!=name: raise InputError('UNSAFE_SOURCE_PATH')
  p=root/name
  if sha(p)!=s['sha256'] or p.stat().st_size!=s['bytes']: raise InputError('BASELINE_HASH_OR_SIZE:'+name)
  dst=out/'baseline'/name;dst.parent.mkdir(exist_ok=True);shutil.copyfile(p,dst)
  records.append(dict(s,reused=True,path='baseline/'+name))
 save(out/'baseline_receipt.json',b)
 quotes={(m,d):official_quotes(json.loads((root/(m+'_'+d+'.json')).read_text()),m,d) for m in ('TWSE','TPEX') for d in (prev,cut)}
 old={r['symbol']:r for r in b['charts']}
 def chart(s):
  import re
  if not re.fullmatch(r'[A-Z0-9]{4,8}\.(TW|TWO)',s): raise InputError('BAD_SYMBOL')
  market='TPEX' if s.endswith('.TWO') else 'TWSE';code=s.split('.')[0]
  refs={d:quotes[market,d].get(code) for d in (prev,cut)};attempts=[]
  p=root/('chart_'+s+'.json')
  if p.exists() and old.get(s,{}).get('status')=='NATIVE_ADJUSTED_CROSSCHECK_PASS':
   v=validate_chart(json.loads(p.read_text()),s,[prev,cut],refs)
   return dict(v,path='baseline/'+p.name,sha256=sha(p),reused=True,attempts=[])
  a=int(dt.datetime.combine(date_of(prev)-dt.timedelta(days=100),dt.time(),TZ).timestamp());z=int(dt.datetime.combine(date_of(cut)+dt.timedelta(days=1),dt.time(),TZ).timestamp())
  urls=[f'https://query1.finance.yahoo.com/v8/finance/chart/{s}?period1={a}&period2={z}&interval=1d&events=div%2Csplits&includeAdjustedClose=true',f'https://query2.finance.yahoo.com/v8/finance/chart/{s}?range=1mo&interval=1d&events=div%2Csplits&includeAdjustedClose=true']
  for i,u in enumerate(urls):
   fp=out/f'chart_{s}_{i+1}.json';p,m=get_json(u,fp,attempt_limit=1);attempts.append(m)
   try:
    v=validate_chart(p,s,[prev,cut],refs)
    return dict(v,path=fp.name,sha256=sha(fp),reused=False,attempts=attempts)
   except Exception as e: attempts[-1]['validation_error']=str(e)
  return dict(symbol=s,status='BLOCKED',formal_input_qualified=False,reused=False,attempts=attempts)
 with cf.ThreadPoolExecutor(max_workers=4) as pool: charts=list(pool.map(chart,sorted(set(symbols))))
 # Obtain missing primary corporate-action documentation, without asserting completeness.
 jobs=[('twse_reductions.json',f'https://www.twse.com.tw/exchangeReport/TWTAVU?response=json&date={cut}'),('twse_capital_changes.json',f'https://www.twse.com.tw/exchangeReport/TWTAUU?response=json&date={cut}'),('tpex_openapi.json','https://www.tpex.org.tw/openapi/swagger.json'),('twse_openapi.json','https://openapi.twse.com.tw/v1/swagger.json')]
 extra=[]
 for name,url in jobs:
  p,m=get_json(url,out/name,attempt_limit=1);extra.append(m)
  if p and 'paths' in p:
   for path,methods in p['paths'].items():
    text=json.dumps(methods,ensure_ascii=False)
    if any(w in text for w in ('減資','分割','面額','恢復買賣')): extra.append({'discovered_path':path,'spec_source':name,'description':methods})
 receipt={'started_at':started,'completed_at':stamp(),'target_date':target,'dates':dates,'baseline_receipt_sha256':sha(rp),'reused_sources':records,'charts':charts,'additional_sources':extra,'expected_symbols':sorted(set(symbols)),'native_adjusted_pass':sum(x['status']=='NATIVE_ADJUSTED_CROSSCHECK_PASS' for x in charts),'native_adjusted_blocked':[x['symbol'] for x in charts if x['status']!='NATIVE_ADJUSTED_CROSSCHECK_PASS'],'formal_input_qualified':False,'prediction_generated':False,'scope':'public source acquisition only; corporate actions and original model continuity require separate validation'}
 save(out/'resume_receipt.json',receipt)
 manifest=[{'path':str(p.relative_to(out)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()]
 save(out/'MANIFEST.json',manifest)
 return receipt
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--baseline',required=True);ap.add_argument('--out',required=True);ap.add_argument('--target-date',required=True);ap.add_argument('--symbols',required=True);a=ap.parse_args()
 try:
  r=resume(a.baseline,a.out,a.target_date,[s.strip() for s in a.symbols.split(',') if s.strip()]);print(json.dumps({k:r[k] for k in ('completed_at','native_adjusted_pass','native_adjusted_blocked','formal_input_qualified')},ensure_ascii=False));raise SystemExit(0 if not r['native_adjusted_blocked'] else 2)
 except (InputError,OSError,KeyError,ValueError) as e:
  save(pathlib.Path(a.out)/'failure_receipt.json',{'completed_at':stamp(),'status':'BLOCKED','reason':str(e),'formal_input_qualified':False});raise
