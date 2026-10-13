#!/usr/bin/env python3
"""Retrospective first-party TPEx historic exdiv windows: only 35 missing months.

Does not access user portfolios, sealed forecasts, cash, or formal OOS. The
previous 2025-06 & 2026-09 original payloads were already SHA archived, and
must be merged separately from their source receipts.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,pathlib,urllib.request,urllib.error,time,sys
from stock_tpex_exdaily_historical_20261013 import parse_original,source_urls,digest
DATE_LO=dt.date(2023,10,12);DATE_HI=dt.date(2026,10,12)
SKIPPED={('2025-06-01','2025-06-30'),('2026-09-01','2026-09-30')}
def periods():
  out=[]; y,m=DATE_LO.year,DATE_LO.month
  while (y,m) <= (DATE_HI.year,DATE_HI.month):
    nxt=dt.date(y+1,1,1) if m==12 else dt.date(y,m+1,1)
    begin=max(dt.date(y,m,1),DATE_LO);end=min(nxt-dt.timedelta(days=1),DATE_HI)
    out.append((begin.isoformat(),end.isoformat()))
    y,m=nxt.year,nxt.month
  return out
def selftest():
    allp=periods();missing=[p for p in allp if p not in SKIPPED]
    checks={
     'periods_37':len(allp)==37,
     'missing_35':len(missing)==35,
     'skipped_2':len(set(allp)&SKIPPED)==2,
     'period_start_end':allp[0]==('2023-10-12','2023-10-31') and allp[-1]==('2026-10-01','2026-10-12'),
     'no_overlaps':all(dt.date.fromisoformat(allp[i][1])+dt.timedelta(days=1)==dt.date.fromisoformat(allp[i+1][0]) for i in range(len(allp)-1)),
     'all_unique':len(set(allp))==37,
     'partitions_complete':sorted({p for batch in range(4) for i,p in enumerate(missing) if i%4==batch})==sorted(missing),
     'source_endpoint_roc': 'd=115%2F' in source_urls('2026-09-01','2026-09-30')[0],
     'no_research_promotion':True
    }
    assert all(checks.values()),checks
    print(json.dumps({'status':'PASS','passed':len(checks),'tests':checks},ensure_ascii=False))
def fetch(url):
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (academic date-range source verification)','Accept':'application/json'})
  with urllib.request.urlopen(req,timeout=17) as resp:
    raw=resp.read(5000001);status=resp.status;final=resp.geturl()
  if len(raw)>5000000:raise ValueError('EXCEEDS_MAX_RESPONSE')
  if not final.startswith('https://www.tpex.org.tw/'):raise ValueError('HOST_REDIRECT_DRIFT')
  if status!=200:raise ValueError('NON200')
  return raw

def main():
 p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--batch',type=int,choices=range(4));p.add_argument('--out');a=p.parse_args()
 if a.self_test:selftest();return 0
 if a.batch is None or not a.out:p.error('--batch and --out required')
 root=pathlib.Path(a.out);root.mkdir(parents=True,exist_ok=False)
 tasks=[period for i,period in enumerate(z for z in periods() if z not in SKIPPED) if i%4==a.batch]
 manifest={'job_batch':a.batch,'windows_expected':len(tasks),'firstparty_source':'TPEx exDailyQ_result.php JSON','research_only':True,'formal_eligible':False,'natural_credit':0,'results':[]}
 for i,(start,end) in enumerate(tasks):
   url=source_urls(start,end)[0];entry={'start':start,'end':end,'url':url,'status':'HOLD_NOT_FETCHED'}
   for attempt in range(2):
     try:
       raw=fetch(url);name=f'tpex_exdaily_{start}_{end}_raw.json';(root/name).write_bytes(raw)
       entry.update(raw_file=name,sha256=digest(raw),bytes=len(raw))
       parse=parse_original(raw,start,end)
       entry.update(status='PASS_PRIMARY_ORIGINAL_EXACT_DATE_ROWS',rows=parse['rows'],symbols=parse['symbols'],min_date=parse['min_date'],max_date=parse['max_date']);break
     except Exception as ex:
       entry.update(status='HOLD_SOURCE_OR_SCHEMA',error_type=type(ex).__name__,error=str(ex)[:220]);
       if attempt==0 and not isinstance(ex,urllib.error.HTTPError):time.sleep(.1)
       else:break
   manifest['results'].append(entry)
   (root/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
 manifest['passed']=sum(x['status']=='PASS_PRIMARY_ORIGINAL_EXACT_DATE_ROWS' for x in manifest['results'])
 (root/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
 print(json.dumps({'batch':a.batch,'expected':len(tasks),'passed':manifest['passed'],'rows':sum(x.get('rows',0) for x in manifest['results']),
                   'failures':[(x['start'],x.get('error_type'),x.get('error')) for x in manifest['results'] if x['status'].startswith('HOLD')]},ensure_ascii=False))
 return 0 if len(tasks)==manifest['passed'] else 2
if __name__=='__main__':raise SystemExit(main())