#!/usr/bin/env python3
"""Research-only historical adjusted-price acquisition for retired 5371.

FinMind is a SECONDARY provider. Never upgrade its prices to TPEx official or
promote the segmented 5371->3718 series to Formal/Natural/OOS. Preserve bytes.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib, time, urllib.parse, urllib.request, urllib.error
START='2024-01-01'; END='2026-08-21'; STOCK='5371'; TPEx_RAW_LAST=83.5
DATASETS=['TaiwanStockPriceAdj','TaiwanStockPrice','TaiwanStockDividendResult']
def sha(b):return hashlib.sha256(b).hexdigest()
def parse(b):
 def unique(pairs):
  z={}
  for k,v in pairs:
   if k in z:raise ValueError('DUPLICATE_JSON_KEY')
   z[k]=v
  return z
 return json.loads(b.decode('utf-8-sig'),object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
def retrieve(url,out):
 for attempt in range(2):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 stock-audit/1.0','Accept':'application/json'})
   with urllib.request.urlopen(req,timeout=18) as resp:
    if urllib.parse.urlsplit(resp.geturl()).hostname!='api.finmindtrade.com':raise ValueError('UNEXPECTED_HOST')
    raw=resp.read(12_000_001)
    if resp.status!=200 or len(raw)>12_000_000:raise ValueError('INVALID_HTTP_OR_SIZE')
   out.write_bytes(raw)
   return {'ok':True,'http':200,'bytes':len(raw),'sha256':sha(raw),'path':out.name,'url':url},raw
  except Exception as ex:
   err={'ok':False,'error':f'{type(ex).__name__}: {str(ex)[:220]}','url':url}
   if isinstance(ex,urllib.error.HTTPError) and ex.code in (401,403,429):return err,None
   if attempt==0:time.sleep(1)
 return err,None
def validate(b,dataset):
 obj=parse(b)
 if not isinstance(obj,dict) or str(obj.get('status')) not in ('200','success') or not isinstance(obj.get('data'),list):raise ValueError('INVALID_FINMIND_SCHEMA_OR_STATUS')
 rows=obj['data'];dates=set();ret=[]
 for r in rows:
  if not isinstance(r,dict) or str(r.get('stock_id'))!=STOCK:raise ValueError('WRONG_CODE_IN_HISTORY')
  s=str(r.get('date'))
  if not START<=s<=END:raise ValueError('POST_CUTOFF_OR_OLD_LEAKAGE')
  if s in dates:raise ValueError('DUPLICATE_DATE')
  dates.add(s)
  if dataset!='TaiwanStockDividendResult':
   for k in ('open','max','min','close'):
    if not isinstance(r.get(k),(int,float)) or not (0<r[k]<1e6):raise ValueError('INVALID_PRICE_FIELD_'+k)
   if not r['max']>=max(r['open'],r['close'],r['min']) or not r['min']<=min(r['open'],r['close'],r['max']):raise ValueError('BAD_OHLC')
   ret.append({'date':s,'close':r['close']})
 if dataset!='TaiwanStockDividendResult':
  if len(ret)<401 or END not in dates:raise ValueError('INSUFFICIENT_HISTORY_OR_LAST_DATE')
  ret.sort(key=lambda x:x['date'])
  return {'rows':len(ret),'min_date':ret[0]['date'],'max_date':ret[-1]['date'],'last_close':ret[-1]['close'], 'last_close_vs_TPEx_raw':ret[-1]['close']-TPEx_RAW_LAST,'sha_verified_as_provider':True,'first_party_official':False}
 return {'rows':len(rows),'min_date':min(dates) if dates else None,'max_date':max(dates) if dates else None,'events_exhaustive':False}
def capture(dest):
 dest.mkdir(parents=True,exist_ok=False)
 info={'symbol':STOCK,'status':'RESEARCH_ONLY_FUNDAMENTAL_PROVENANCE_PENDING','source':'FINMIND_SECONDARY_PROVIDER',
       'tpex_last_close_original_sha':'bc52b4d651cf478f46f99103ef1a8e32b084d32d1f039ab36533a9b8bc6fa94b',
       'tpex_last_close':TPEx_RAW_LAST,'tpex_last_date':END,'start':START,'cutoff':END,
       'formal_prediction_count':0,'natural_oos_credit':0,'datasets':{}}
 for kind in DATASETS:
  url='https://api.finmindtrade.com/api/v4/data?'+urllib.parse.urlencode({'dataset':kind,'data_id':STOCK,'start_date':START,'end_date':END})
  src,raw=retrieve(url,dest/f'{kind}_5371_{END}.json')
  if raw is not None:
   try:
    src['valid']=validate(raw,kind)
    src['status']='PASS_PROVIDER_RAW_VALIDATED_RESEARCH_ONLY'
   except Exception as ex:src['status']='HOLD_PROVIDER_VALIDATION';src['validation_error']=str(ex)
  else:src['status']='UNAVAILABLE'
  info['datasets'][kind]=src
  (dest/'manifest_partial.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 ready=all(info['datasets'][k].get('status')=='PASS_PROVIDER_RAW_VALIDATED_RESEARCH_ONLY' for k in ('TaiwanStockPriceAdj','TaiwanStockPrice'))
 if ready:
  old=info['datasets']['TaiwanStockPrice']['valid']['last_close']
  if abs(old-TPEx_RAW_LAST)<=.03:
   info['status']='LEGACY_RAW_AND_ADJUSTED_PROVIDER_RESEARCH_READY_ACTION_NOT_EXHAUSTIVE'
  else:info['status']='HOLD_FINMIND_RAW_VS_OFFICIAL_TPEX_CONFLICT'
 info['issuer_action_primary_exhaustive']='HOLD'
 info['segmented_cross_ticker_3718_training']='RESEARCH_ONLY_NO_AUTO_SPLICE'
 (dest/'manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 return info

def selftest():
 import datetime as dt
 def day(i):return (dt.date(2024,1,1)+dt.timedelta(days=i)).isoformat()
 dates=[day(i) for i in range((dt.date(2026,8,21)-dt.date(2024,1,1)).days+1)]
 samples=[{'date':x,'stock_id':STOCK,'open':80.0,'max':84.0,'min':78.0,'close':80.0} for x in dates]
 samples[-1]['close']=83.5
 d={'msg':'success','status':200,'data':samples}
 p=lambda x:json.dumps(x).encode('utf-8')
 x=validate(p(d),'TaiwanStockPrice')
 assert x['rows']==len(dates) and x['last_close']==83.5
 for test in ('badcode','leak','dup','nonfinite','badmax','noend','short'):
  rows=[dict(x) for x in samples]
  if test=='badcode':rows[0]['stock_id']='3718'
  elif test=='leak':rows[-1]['date']='2026-08-22'
  elif test=='dup':rows[1]['date']=rows[0]['date']
  elif test=='nonfinite':rows[0]['close']=float('nan')
  elif test=='badmax':rows[0]['max']=40
  elif test=='noend':rows.pop()
  elif test=='short':rows=rows[:10]
  try:validate(p({**d,'data':rows}),'TaiwanStockPrice');raise AssertionError('Bad case not rejected:'+test)
  except (ValueError,TypeError):pass
 assert validate(p({'msg':'success','status':200,'data':[]}), 'TaiwanStockDividendResult')['events_exhaustive'] is False
 try:parse(b'{"a":1,"a":2}'); raise AssertionError('dup escaped')
 except ValueError:pass
 return {'tests':10,'passed':10,'status':'PASS','formal_affected':False}
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');a.add_argument('--output');opt=a.parse_args()
 if opt.self_test:print(json.dumps(selftest()))
 else:
  if not opt.output:a.error('--output required')
  z=capture(pathlib.Path(opt.output))
  print(json.dumps({'status':z['status'],'datasets':{k:v.get('status') for k,v in z['datasets'].items()}},ensure_ascii=False))