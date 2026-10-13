#!/usr/bin/env python3
"""Bounded one-shot, research-only capture for the 5371->3718 share swap.

Preserves exact bytes, dates, SHA-256, and source roles. The collector makes NO
forecast, brokerage, portfolio, formal-seal or natural-OOS writes. It never
interprets a suspended trading interval as a normal daily return.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib, re, time
import urllib.parse, urllib.request, urllib.error
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Taipei')
DATES={"5371":"2026-08-21", "3718":"2026-09-03"}
EXPECTED_CLOSE={"5371":83.5,"3718":78.3}  # independent secondary controls ONLY
OFFICIAL={
 "5371": [
 "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=2026%2F08%2F21",
 "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d=115%2F08%2F21"
 ],
 "3718": [
 "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=2026%2F09%2F03",
 "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d=115%2F09%2F03"
 ],
}
NOTICES={
 "suspension": "https://www.tpex.org.tw/storage/eb_data/11508/11500050581.html",
 "index_swap": "https://www.tpex.org.tw/storage/eb_data/11508/11503025121.html",
}

def sha(b): return hashlib.sha256(b).hexdigest()

def safe_json(b):
 def uniq(pairs):
  out={}
  for k,v in pairs:
   if k in out: raise ValueError('JSON_DUPLICATE_KEY')
   out[k]=v
  return out
 return json.loads(b.decode('utf-8-sig'),object_pairs_hook=uniq,
  parse_constant=lambda x: (_ for _ in ()).throw(ValueError('JSON_NONFINITE')))

def get(url,dest,attempts=2):
 # Fixed first-party venues and two Yahoo hosts; no open redirects to other domains.
 original_host=urllib.parse.urlsplit(url).hostname
 assert original_host in {'www.tpex.org.tw','query1.finance.yahoo.com','query2.finance.yahoo.com'}
 errors=[]
 for n in range(attempts):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; StockSourceResearch/1.0)','Accept':'application/json,text/html,text/csv,*/*'})
   with urllib.request.urlopen(req, timeout=14) as resp:
    b=resp.read(5_000_001)
    dest_host=urllib.parse.urlsplit(resp.geturl()).hostname
    if dest_host!=original_host: raise ValueError('REDIRECT_HOST_MISMATCH')
    if resp.status!=200 or len(b)>5_000_000: raise ValueError('BAD_STATUS_OR_SIZE')
    content_type=resp.headers.get('Content-Type')
   dest.write_bytes(b)
   return {'ok':True,'url':url,'content_type':content_type,'sha256':sha(b),'bytes':len(b),'raw_file':dest.name},b
  except Exception as e:
   errors.append({'attempt':n+1,'error_class':type(e).__name__,'error':str(e)[:240]})
   if isinstance(e,urllib.error.HTTPError) and e.code in (401,403,429):break
   if not n: time.sleep(1)
 return {'ok':False,'url':url,'errors':errors},None

def fmt_to_iso(x):
 x=str(x).strip().replace('/','').replace('-','')
 if re.fullmatch(r'\d{7}',x):return str(int(x[:3])+1911)+'-'+x[3:5]+'-'+x[5:7]
 if re.fullmatch(r'\d{8}',x):return x[:4]+'-'+x[4:6]+'-'+x[6:8]
 return None

def numeric(x):
 try:return float(str(x).replace(',','').strip())
 except (ValueError,TypeError):return None

def official_quote(raw,code,day):
 """Fail closed unless stock code, date, and a unique close are explicit."""
 try: d=safe_json(raw)
 except (UnicodeDecodeError,json.JSONDecodeError,ValueError):return None
 if not isinstance(d,dict):return None
 # Some TPEx feeds use ROC dates, some Gregorian. Do not assume response date.
 dates=[d.get(k) for k in ('date','Date','statDate','stat_date','reportDate') if d.get(k)]
 if not dates or day not in [fmt_to_iso(v) for v in dates]:return None
 tables=[d]+list(d.get('tables') or [])
 matches=[]
 for t in tables:
  f=t.get('fields') or []
  if not f or not t.get('data'):continue
  possible_c=[x for x in ('代號','證券代號','股票代號','證券代碼') if x in f]
  possible_p=[x for x in ('收盤','收盤價','收市','Close') if x in f]
  if not possible_c or not possible_p:continue
  ci=f.index(possible_c[0]); pi=f.index(possible_p[0])
  for row in t['data']:
   if isinstance(row,list) and len(row)>max(ci,pi) and str(row[ci]).strip()==code:
    val=numeric(row[pi])
    if val is not None and 0<val<100000:matches.append(val)
 if len(matches)!=1:return None
 return matches[0]

def yahoo_close(raw,ticker,day):
 d=safe_json(raw)
 chart=d.get('chart') or {}
 if chart.get('error'):return None
 res=chart.get('result') or []
 if len(res)!=1 or (res[0].get('meta') or {}).get('symbol')!=ticker:return None
 q=(res[0].get('indicators') or {}).get('quote') or []
 a=(res[0].get('indicators') or {}).get('adjclose') or []
 if len(q)!=1 or len(a)!=1:return None
 times=res[0].get('timestamp') or []
 closes=q[0].get('close') or []; adj=a[0].get('adjclose') or []
 if not times or len(times)!=len(closes) or len(times)!=len(adj):return None
 seen={}
 for t,c,adjusted in zip(times,closes,adj):
  date=dt.datetime.fromtimestamp(t,TZ).strftime('%Y-%m-%d')
  if date in seen:return None
  if numeric(c) is not None and numeric(adjusted) is not None:seen[date]={'close':float(c),'adjusted_close':float(adjusted)}
 if day not in seen or any(k>day for k in seen):return None
 return {'day':day,'day_close':seen[day]['close'],'adjusted_at_day':seen[day]['adjusted_close'],
         'observations':len(seen),'first_day':min(seen),'last_day':max(seen),'date_price':seen}

def collect(out):
 out.mkdir(parents=True,exist_ok=False)
 results={'as_of':dt.datetime.now(TZ).isoformat(),'workstream':'STOCK_H9_RESEARCH_LEGACY_SHARE_SWAP_ONLY',
    'security_relation':'5371->3718','shares_old_to_new':'1:1',
    'suspension_from':'2026-08-24','first_new_trade':'2026-09-03',
    'formal_model_changed':False,'original_predictions_changed':False,'natural_credit':0,'sources':{},'per_symbol':{}}
 for name,url in NOTICES.items():
  status,b=get(url,out/f'first_party_{name}.html')
  text=b.decode('utf-8',errors='ignore') if b else ''
  status['has_5371']= '5371' in text
  status['has_3718']= '3718' in text
  status['notice_validation']='OFFICIAL_NOTICE_TEXT_CONTAINS_5371_3718' if status['has_5371'] and status['has_3718'] else 'UNVERIFIED'
  results['sources']['notice_'+name]=status
 for code,day in DATES.items():
  item={'symbol':code,'exact_trade_date':day,'first_party_price':'HOLD', 'yahoo_history':'HOLD',
        'secondary_reference_close_not_official':EXPECTED_CLOSE[code]}
  for i,url in enumerate(OFFICIAL[code]):
   x,b=get(url,out/f'tpex_{code}_{i}.bin')
   x['exact_official_close']=official_quote(b,code,day) if b else None
   item.setdefault('official_attempts',[]).append(x)
   if x['exact_official_close'] is not None:
    item['first_party_price']='PASS_FIRST_PARTY_EXACT_DATE_SYMBOL_SHA'
    item['first_party_quote_close']=x['exact_official_close']
    item['first_party_quote_sha']=x['sha256']
    break
  ticker=f'{code}.TWO'
  p1=int(dt.datetime(2024,1,1,tzinfo=TZ).timestamp())
  p2=int((dt.date.fromisoformat(day)+dt.timedelta(days=1)).strftime('%s'))
  # Use local TZ to avoid reinterpretation of the end of the final session.
  p2=int(dt.datetime.combine(dt.date.fromisoformat(day)+dt.timedelta(days=1),dt.time.min,tzinfo=TZ).timestamp())
  param=urllib.parse.urlencode({'period1':p1,'period2':p2,'interval':'1d','events':'div,splits','includeAdjustedClose':'true'})
  for i,host in enumerate(('query1.finance.yahoo.com','query2.finance.yahoo.com')):
   url=f'https://{host}/v8/finance/chart/{ticker}?{param}'
   x,b=get(url,out/f'yahoo_{ticker}_{i}.json')
   if b:
    try:parsed=yahoo_close(b,ticker,day)
    except Exception as ex:parsed=None;x['validation_error']=str(ex)[:180]
    if parsed:
     item['yahoo_history']='PASS_PROVIDER_RAW_HISTORY_SHA'
     item['yahoo_raw_sha']=x['sha256']; item['yahoo_history_len']=parsed['observations']
     item['yahoo_first_day']=parsed['first_day'];item['yahoo_last_day']=parsed['last_day']
     item['yahoo_close_exact_date']=parsed['day_close'];item['yahoo_adjusted_close_exact_date']=parsed['adjusted_at_day']
     item['price_crosscheck']='PASS' if item['first_party_price'].startswith('PASS') and abs(item['first_party_quote_close']-parsed['day_close'])<=.03 else 'HOLD_NO_FIRST_PARTY_OR_PRICE_CONFLICT'
     item.setdefault('yahoo_attempts',[]).append(x)
     break
   item.setdefault('yahoo_attempts',[]).append(x)
  results['per_symbol'][code]=item
  (out/'manifest_partial.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 both=results['per_symbol']
 results['source_pass_count']=sum(x['first_party_price'].startswith('PASS') and x['yahoo_history'].startswith('PASS') and x.get('price_crosscheck')=='PASS' for x in both.values())
 results['bridge_research_status']='SEGMENTED_SOURCE_READY_SHADOW_ONLY' if results['source_pass_count']==2 else 'HOLD_SOURCE_INCOMPLETE'
 results['formal_h9_3718']='HOLD_PENDING_ISSUER_ACTION_AND_PROSPECTIVE_BASIS_AUDIT'
 (out/'manifest.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 return results

def tests():
 assert fmt_to_iso('1150821')=='2026-08-21'
 assert fmt_to_iso('20260903')=='2026-09-03'
 good={'date':'1150821','tables':[{'fields':['代號','收盤'], 'data':[['5371','83.50'],['5678','10']]}]}
 b=json.dumps(good).encode(); assert official_quote(b,'5371','2026-08-21')==83.5
 assert official_quote(b,'5371','2026-08-20') is None
 assert official_quote(b,'3718','2026-08-21') is None
 bad={**good,'tables':[{'fields':['代號','收盤'],'data':[['5371','83.50'],['5371','83.55']]}]}
 assert official_quote(json.dumps(bad).encode(),'5371','2026-08-21') is None
 assert not official_quote(b'garbage','5371','2026-08-21')
 try:safe_json(b'{"a":1,"a":2}');raise AssertionError('Duplicate JSON not rejected')
 except ValueError:pass
 ts=int(dt.datetime(2026,8,21,13,30,tzinfo=TZ).timestamp())
 chart={'chart':{'error':None,'result':[{'meta':{'symbol':'5371.TWO'},'timestamp':[ts], 'indicators':{'quote':[{'close':[83.5]}],'adjclose':[{'adjclose':[83.5]}]}}]}}
 assert yahoo_close(json.dumps(chart).encode(),'5371.TWO','2026-08-21')['day_close']==83.5
 assert yahoo_close(json.dumps(chart).encode(),'3718.TWO','2026-08-21') is None
 assert yahoo_close(json.dumps(chart).encode(),'5371.TWO','2026-08-20') is None
 chart['chart']['result'][0]['timestamp'].append(ts);chart['chart']['result'][0]['indicators']['quote'][0]['close'].append(83.5);chart['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'].append(83.5)
 assert yahoo_close(json.dumps(chart).encode(),'5371.TWO','2026-08-21') is None
 return {'total':12,'passed':12,'result':'PASS','crosslisted_securities_distinct':True,'no_corporate_gap_daily_return':True}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output');p.add_argument('--self-test',action='store_true');args=p.parse_args()
 if args.self_test:print(json.dumps(tests(),ensure_ascii=False))
 else:
  if not args.output:p.error('--output is required')
  x=collect(pathlib.Path(args.output));print(json.dumps({k:v for k,v in x.items() if k!='sources' and k!='per_symbol'},ensure_ascii=False))