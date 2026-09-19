#!/usr/bin/env python3
"""Public-only daily collector with a hash-checked same-date native-price cache.
No portfolio/model inputs, no synthetic adjusted prices, no cron or broker actions.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, datetime as dt, hashlib, json, pathlib, shutil, re
from zoneinfo import ZoneInfo
from premarket_daily_inputs import collect, date_of, get_json, official_quotes, validate_chart, resolve_calendar, calendar_days, InputError
TZ=ZoneInfo('Asia/Taipei')
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def put(p,x):
 p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()
def checked(root,item):
 root=pathlib.Path(root).resolve();p=(root/item['path']).resolve()
 if not p.is_relative_to(root) or not p.is_file() or sha(p)!=item['sha256']:raise InputError('CACHE_SOURCE_HASH_OR_PATH')
 if item.get('bytes') is not None and p.stat().st_size!=item['bytes']:raise InputError('CACHE_SOURCE_SIZE')
 return p

def run(seed,out,symbols,requested='auto'):
 out=pathlib.Path(out)
 if out.exists():raise InputError('OUTPUT_EXISTS')
 out.mkdir(parents=True);started=stamp();now=dt.datetime.now(TZ)
 symbols=sorted(symbols)
 if not symbols or len(symbols)!=len(set(symbols)) or any(not re.fullmatch(r'[A-Z0-9]{4,8}\.(TW|TWO)',s) for s in symbols):raise InputError('EXACT_PUBLIC_SYMBOL_SCOPE_REQUIRED')
 paths=list(pathlib.Path(seed).rglob('resume_receipt.json'));old=None
 if len(paths)==1:
  rp=paths[0];old=json.loads(rp.read_text());root=rp.parent
  if sorted(old['expected_symbols'])!=symbols:raise InputError('CACHE_SCOPE_MISMATCH')
  cal_source=next(s for s in old['reused_sources'] if pathlib.Path(s['path']).name=='calendar.json')
  cal=json.loads(checked(root,cal_source).read_text())
  day=now.date() if requested=='auto' else date_of(requested)
  closed,years=calendar_days([cal])
  if day.year in years:
   if requested=='auto':
    while day.weekday()>4 or day in closed:day+=dt.timedelta(days=1)
   try:dates=resolve_calendar([cal],day)
   except InputError:old=None
  else:old=None
  if old and (old['dates']!=dates):old=None
 if old is None:
  result=collect(out/'fresh',requested,symbols)
  result['cache_mode']='FRESH_DATED_SOURCE_SET';result['requested_symbols']=symbols;result['additional_action_refresh_required']=True
  put(out/'daily_receipt.json',result)
  return result
 dates=old['dates'];prev,cut=dates['previous_session'],dates['price_cutoff'];records=[]
 def copyrec(item,name):
  src=checked(root,item);dst=out/'seed'/name;dst.parent.mkdir(exist_ok=True)
  if dst.exists() and sha(dst)!=item['sha256']:raise InputError('CACHE_NAME_COLLISION')
  if not dst.exists():shutil.copyfile(src,dst)
  return dict(item,path='seed/'+name,reused=True)
 for s in old['reused_sources']:records.append(copyrec(s,pathlib.Path(s['path']).name))
 sources={pathlib.Path(s['path']).name:s for s in old['reused_sources']}
 refs={(m,d):official_quotes(json.loads(checked(root,sources[f'{m}_{d}.json']).read_text()),m,d) for m in ('TWSE','TPEX') for d in (prev,cut)}
 indexed={c['symbol']:c for c in old['charts']}
 def one(sym):
  c=indexed[sym];code=sym.split('.')[0];m='TPEX' if sym.endswith('.TWO') else'TWSE';official={d:refs[m,d].get(code) for d in (prev,cut)}
  if c['status']=='NATIVE_ADJUSTED_CROSSCHECK_PASS':
   f=checked(root,c);v=validate_chart(json.loads(f.read_text()),sym,[prev,cut],official)
   cp=copyrec(dict(c,bytes=f.stat().st_size),'native_'+sym+'.json')
   return dict(v,path=cp['path'],sha256=cp['sha256'],bytes=f.stat().st_size,reused=True,attempts=[])
  attempts=[];a=int(dt.datetime.combine(date_of(prev)-dt.timedelta(days=100),dt.time(),TZ).timestamp());z=int(dt.datetime.combine(date_of(cut)+dt.timedelta(days=1),dt.time(),TZ).timestamp())
  for n,h in enumerate(('query1.finance.yahoo.com','query2.finance.yahoo.com'),1):
   f=out/f'chart_{sym}_{n}.json';u=f'https://{h}/v8/finance/chart/{sym}?period1={a}&period2={z}&interval=1d&events=div%2Csplits&includeAdjustedClose=true'
   p,meta=get_json(u,f,attempt_limit=1);attempts.append(meta)
   try:
    v=validate_chart(p,sym,[prev,cut],official)
    return dict(v,path=f.name,sha256=sha(f),bytes=f.stat().st_size,reused=False,attempts=attempts)
   except Exception as e:meta['validation_error']=str(e)
  return {'symbol':sym,'status':'BLOCKED','formal_input_qualified':False,'reused':False,'attempts':attempts}
 with cf.ThreadPoolExecutor(max_workers=3) as pool:charts=list(pool.map(one,symbols))
 end=dates['target_date'].replace('-','');ps=f'{prev[:4]}/{prev[4:6]}/{prev[6:]}';es=dates['target_date'].replace('-','/')
 # Current announcements can change while dated prices stay unchanged. Refresh only these bounded action sources.
 jobs=[('twse_exdiv.json',f'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json&startDate={prev}&endDate={end}'),
 ('tpex_exdiv.json',f'https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={ps}&endDate={es}&response=json'),
 ('twse_reduction.json',f'https://www.twse.com.tw/rwd/zh/reducation/TWTAUU?response=json&startDate={prev}&endDate={end}'),
 ('tpex_reduction.json',f'https://www.tpex.org.tw/www/zh-tw/bulletin/revivt?startDate={ps}&endDate={es}&response=json'),
 ('twse_split.json',f'https://www.twse.com.tw/rwd/zh/change/TWTB8U?response=json&startDate={prev}&endDate={end}'),
 ('tpex_split.json',f'https://www.tpex.org.tw/www/zh-tw/bulletin/pvChgRslt?startDate={ps}&endDate={es}&response=json')]
 def action(j):
  p,m=get_json(j[1],out/j[0],attempt_limit=1);m['role']='CURRENT_ACTION_REFERENCE';return m
 with cf.ThreadPoolExecutor(max_workers=3)as pool:actions=list(pool.map(action,jobs))
 r={'started_at':started,'completed_at':stamp(),'target_date':dates['target_date'],'dates':dates,'expected_symbols':symbols,'reused_sources':records,
 'charts':charts,'additional_sources':actions,'native_adjusted_pass':sum(c['status']=='NATIVE_ADJUSTED_CROSSCHECK_PASS' for c in charts),
 'native_adjusted_blocked':[c['symbol']for c in charts if c['status']!='NATIVE_ADJUSTED_CROSSCHECK_PASS'],
 'cache_mode':'HASH_VERIFIED_SAME_DATE','requested_symbols':[c['symbol']for c in charts if not c['reused']],
 'official_close_sources_refetched':0,'formal_input_qualified':False,'prediction_generated':False,'source_snapshot_only':True,
 'limitation':'This job does not qualify model history, action completeness or delivery. A next-session public snapshot is not a premarket forecast.'}
 put(out/'resume_receipt.json',r);put(out/'daily_receipt.json',r)
 return r
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--seed',required=True);p.add_argument('--out',required=True);p.add_argument('--symbols-file',required=True);p.add_argument('--target-date',default='auto');a=p.parse_args()
 try:
  r=run(a.seed,a.out,json.loads(pathlib.Path(a.symbols_file).read_text()),a.target_date)
  checks=r.get('charts',[]);blocked=[c['symbol']for c in checks if c['status']!='NATIVE_ADJUSTED_CROSSCHECK_PASS']
  print(json.dumps({'mode':r.get('cache_mode'),'target':r.get('dates',{}).get('target_date'),'native_pass':len(checks)-len(blocked),'blocked':blocked,'formal_input_qualified':False}))
  raise SystemExit(2 if blocked or r.get('official_validation_pass') is False or r.get('transport_complete') is False or any(s.get('status')!='FETCHED' for s in r.get('additional_sources',[]) if 'path' in s) else 0)
 except (InputError,KeyError,OSError,ValueError)as e:
  put(pathlib.Path(a.out)/'failure_receipt.json',{'status':'BLOCKED','reason':str(e),'completed_at':stamp(),'formal_input_qualified':False});raise
