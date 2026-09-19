#!/usr/bin/env python3
"""Retrieve only unverified public B1 scope; no portfolio or prediction execution."""
import concurrent.futures as cf
import datetime as dt
import hashlib,json,pathlib,re,urllib.parse,urllib.request
import premarket_daily_inputs as core
CODES='00400A 0050 009820 2207 2308 2317 2330 2368 2376 2382 2383 2454 2634 2834 2885 3481 3665 4916 6770 3293 3491 2303 3443 6526 3189 2345 3017 3661 6669 3037 6223 6442 3324 3653 8046 3450 3363 3163 4979 6451 6515 6510 3529 5222 6285 3138 2314 2313 2367 8033 2645 2630 6753 3718 7402 2231 3105 8086 2466 4541 4572 8222 3004 2359 5351 2395 6166 6414 6188 2049 4540 1597 4583 2439 3227 2458 3019 6214 6752 6112 3029 6689 4953 2471 6874 2301 6412 6282 6781 4931 3211 1519 1503 1513 2371 6806 6831 8147 3711 1504 4958 4585 5274 2059'.split()
ROOT=pathlib.Path('b1_restored/official_daily_inputs')
OUT=pathlib.Path('b1_scope_output');OUT.mkdir(exist_ok=True)
def checked(name,rec):
 b=(ROOT/name).read_bytes();assert hashlib.sha256(b).hexdigest()==rec['sha256'] and len(b)==rec['bytes'],name
 return json.loads(b)
def main():
 raw=(ROOT/'acquisition_receipt.json').read_bytes()
 assert hashlib.sha256(raw).hexdigest()=='218b7c4c91b6d4dd6444dec895ae817577d49fc722727009e43e5dabf13bf8c0'
 receipt=json.loads(raw);records={r['path']:r for r in receipt['sources']};days=[receipt['dates']['previous_session'],receipt['dates']['price_cutoff']]
 assert days==['20260917','20260918'] and receipt['dates']['target_date']=='2026-09-21'
 quotes={(m,d):core.official_quotes(checked(f'{m}_{d}.json',records[f'{m}_{d}.json']),m,d) for m in ('TWSE','TPEX') for d in days}
 results=[];jobs=[]
 for code in CODES:
  markets=[m for m in ('TWSE','TPEX') if code in quotes[m,days[-1]]]
  if len(markets)!=1:
   results.append({'code':code,'status':'OFFICIAL_REFERENCE_MISSING_OR_AMBIGUOUS','markets':markets});continue
  m=markets[0];symbol=code+('.TW' if m=='TWSE' else '.TWO')
  old=next((c for c in receipt['charts'] if c['symbol']==symbol),None)
  if old:
   original=checked('chart_'+symbol+'.json',records['chart_'+symbol+'.json'])
   try:v=core.validate_chart(original,symbol,days,{d:quotes[m,d].get(code) for d in days})
   except Exception as e:v={'status':'FAIL','error':str(e)}
   results.append({'code':code,'symbol':symbol,'reuse':True,'validation':v,'source':records['chart_'+symbol+'.json']});continue
  jobs.append((code,symbol,m))
 result={'started_at':core.stamp(),'target_date':'2026-09-21','sessions':days,'universe_codes':CODES,'universe_count':len(CODES),'baseline_receipt_sha256':hashlib.sha256(raw).hexdigest(),'already_checked_reused':len([r for r in results if r.get('reuse')]),'new_native_sources_requested':len(jobs),'official_refetches':0,'model_runs':0,'formal_input_qualified':False,'charts':results,'action_sources':[]}
 core.dump(OUT/'scope_receipt.json',result)
 p1=int(dt.datetime(2026,9,1,tzinfo=core.TZ).timestamp());p2=int(dt.datetime(2026,9,19,tzinfo=core.TZ).timestamp())
 def fetch_chart(item):
  code,symbol,m=item
  url=f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?'+urllib.parse.urlencode({'period1':p1,'period2':p2,'interval':'1d','events':'div,splits','includeAdjustedClose':'true'})
  p,src=core.get_json(url,OUT/'native'/('chart_'+symbol+'.json'),attempt_limit=1)
  try:
   if p is None:raise ValueError('SOURCE_FETCH_FAILED')
   v=core.validate_chart(p,symbol,days,{d:quotes[m,d].get(code) for d in days})
  except Exception as e:v={'status':'FAIL','error':str(e)}
  return {'code':code,'symbol':symbol,'reuse':False,'source':src,'validation':v}
 with cf.ThreadPoolExecutor(max_workers=4) as pool:
  for row in pool.map(fetch_chart,jobs):result['charts'].append(row);core.dump(OUT/'scope_receipt.json',result)
 urls=[
 ('twse_reduction_page','https://www.twse.com.tw/zh/announcement/reduction/twtauu.html'),
 ('twse_split_page','https://www.twse.com.tw/zh/announcement/split/twtcau.html'),
 ('tpex_reduction_page','https://www.tpex.org.tw/zh-tw/announce/market/reduction/reference.html'),
 ('twse_reduction','https://www.twse.com.tw/rwd/zh/announcement/reduction/TWTAUU?response=json&startDate=20260917&endDate=20260921'),
 ('twse_etf_split','https://www.twse.com.tw/rwd/zh/announcement/split/TWTCAU?response=json&startDate=20260917&endDate=20260921'),
 ('twse_menu','https://www.twse.com.tw/res/data/zh/menu-mega.html')]
 def fetch_raw(item):
  key,url=item;f=OUT/'actions'/(key+'.raw');f.parent.mkdir(exist_ok=True)
  src={'key':key,'url':url,'retrieved_at':core.stamp(),'qualified':False}
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/html'})
   with urllib.request.urlopen(req,timeout=20) as r:b=r.read();src['http_status']=r.status;src['content_type']=r.headers.get('Content-Type');src['final_url']=r.url
   f.write_bytes(b);src.update(status='FETCHED',path=str(f.relative_to(OUT)),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
  except Exception as e:src.update(status='FETCH_FAILED',error=str(e))
  return src
 with cf.ThreadPoolExecutor(max_workers=3) as pool:
  for row in pool.map(fetch_raw,urls):result['action_sources'].append(row);core.dump(OUT/'scope_receipt.json',result)
 result['completed_at']=core.stamp();result['native_pass_count']=sum(r.get('validation',{}).get('status')=='NATIVE_ADJUSTED_CROSSCHECK_PASS' for r in result['charts'])
 result['native_fail_count']=len(CODES)-result['native_pass_count']
 result['corporate_action_qualification']='NOT_YET_REVIEWED';core.dump(OUT/'scope_receipt.json',result)
 print(json.dumps({'native_pass':result['native_pass_count'],'native_fail':result['native_fail_count'],'formal_input_qualified':False}))
 return 0
if __name__=='__main__':raise SystemExit(main())
