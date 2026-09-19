#!/usr/bin/env python3
"""Inventory all requested public tickers. Does not certify a private model or make predictions."""
import argparse, concurrent.futures, datetime as dt, hashlib, json, pathlib, re
from premarket_daily_inputs import get_json, official_quotes, validate_chart

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def run(base,expected_sha,codes,target,out):
 base=pathlib.Path(base);out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=False)
 rp=base/'acquisition_receipt.json'
 if sha(rp)!=expected_sha:raise ValueError('RECEIPT_INTEGRITY')
 old=json.loads(rp.read_text());d=old['dates']
 if d['target_date']!=target:raise ValueError('TARGET_MISMATCH')
 if len(set(codes))!=len(codes) or any(not re.fullmatch(r'[A-Z0-9]{4,8}',c)for c in codes):raise ValueError('INVALID_CODES')
 quotes={};sources={x['path']:x for x in old['sources']}
 for market in ('TWSE','TPEX'):
  for day in (d['previous_session'],d['price_cutoff']):
   name=f'{market}_{day}.json';p=base/name;m=sources[name]
   if sha(p)!=m['sha256'] or p.stat().st_size!=m['bytes']:raise ValueError('OFFICIAL_SOURCE_INTEGRITY')
   quotes[market,day]=official_quotes(json.loads(p.read_text()),market,day)
 records=[];jobs=[]
 for c in codes:
  markets=[m for m in ('TWSE','TPEX')if c in quotes[m,d['price_cutoff']]]
  if len(markets)!=1:
   records.append({'code':c,'status':'NO_UNIQUE_OFFICIAL_CLOSE','formal_input_qualified':False});continue
  m=markets[0];symbol=c+('.TW'if m=='TWSE'else'.TWO');ref={day:quotes[m,day].get(c) for day in (d['previous_session'],d['price_cutoff'])}
  name=f'chart_{symbol}.json'
  if name in sources:
   f=base/name;meta=sources[name]
   if sha(f)!=meta['sha256']:raise ValueError('CHART_BASELINE_INTEGRITY')
   rec={'code':c,'symbol':symbol,'market':m,'reused':True,'source':meta,'formal_input_qualified':False}
   try:rec.update(validate_chart(json.loads(f.read_text()),symbol,list(ref),ref))
   except Exception as e:rec.update(status='BLOCKED',error=str(e))
   records.append(rec)
  else:jobs.append((c,m,symbol,ref))
 result={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'dates':d,'baseline_receipt_sha256':expected_sha,'requested_codes':codes,'symbols':records,'formal_input_qualified':False,'prediction_generated':False,'official_quotes_refetched':0,'known_charts_refetched':0}
 def fetch(job):
  c,m,s,ref=job;name=f'chart_{s}.json'
  p,meta=get_json(f'https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d&range=3mo&events=div%2Csplits&includeAdjustedClose=true',out/name,attempt_limit=1)
  rec={'code':c,'symbol':s,'market':m,'reused':False,'source':meta,'formal_input_qualified':False}
  try:rec.update(validate_chart(p,s,list(ref),ref))
  except Exception as e:rec.update(status='BLOCKED',error=str(e))
  return rec
 with concurrent.futures.ThreadPoolExecutor(max_workers=3)as pool:
  for r in pool.map(fetch,jobs):result['symbols'].append(r);write(out/'inventory_receipt.json',result)
 result['completed_at']=dt.datetime.now(dt.timezone.utc).isoformat();result['requested_scope_accounted']=set(codes)=={r['code']for r in result['symbols']} and len(codes)==len(result['symbols'])
 result['native_valid_count']=sum(r['status']=='NATIVE_ADJUSTED_CROSSCHECK_PASS'for r in result['symbols']);result['new_chart_requests']=len(jobs)
 result['scope_note']='Coverage is of requested public tickers only. Model scope, corporate actions and historical continuity must be independently verified.'
 write(out/'inventory_receipt.json',result);print(json.dumps({k:v for k,v in result.items()if k!='symbols'},ensure_ascii=False))
 return 0 if result['requested_scope_accounted'] else 2
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--receipt-sha',required=True);p.add_argument('--codes',required=True);p.add_argument('--target',required=True);p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(run(a.baseline,a.receipt_sha,a.codes.split(','),a.target,a.out))
