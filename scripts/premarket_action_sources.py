#!/usr/bin/env python3
"""Fetch narrowly scoped official action sources. Never certifies adjusted prices."""
import argparse, concurrent.futures, datetime as dt, hashlib, json, pathlib, urllib.request, urllib.parse

ENDPOINTS = {
 'TWSE_FACE_VALUE': ('TWSE','GET','https://www.twse.com.tw/rwd/zh/change/TWTB8U'),
 'TWSE_ETF_SPLIT': ('TWSE','GET','https://www.twse.com.tw/rwd/zh/split/TWTCAU'),
 'TPEX_CAPITAL_REDUCTION': ('TPEX','POST','https://www.tpex.org.tw/www/zh-tw/bulletin/revivt'),
 'TPEX_FACE_VALUE': ('TPEX','POST','https://www.tpex.org.tw/www/zh-tw/bulletin/pvChgRslt'),
 'TPEX_ETF_SPLIT': ('TPEX','POST','https://www.tpex.org.tw/www/zh-tw/bulletin/etfSplitRslt'),
 'TPEX_ETF_REVERSE_SPLIT': ('TPEX','POST','https://www.tpex.org.tw/www/zh-tw/bulletin/etfRvsRslt')
}
def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()
def write(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def fetch_one(item,start,end,out):
 name,(market,method,url)=item
 fmt='%Y%m%d' if market=='TWSE' else '%Y/%m/%d'
 params={'startDate':start.strftime(fmt),'endDate':end.strftime(fmt),'response':'json'}
 encoded=urllib.parse.urlencode(params).encode()
 req_url=url+'?'+encoded.decode() if method=='GET' else url
 rec={'name':name,'market':market,'method':method,'url':url,'parameters':params,'attempts':1,'started_at':stamp(),'formal_input_qualified':False,'coverage_certified':False}
 try:
  req=urllib.request.Request(req_url,data=encoded if method=='POST' else None,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
  with urllib.request.urlopen(req,timeout=20) as r:
   data=r.read(); rec['http_status']=r.status;rec['content_type']=r.headers.get('Content-Type');rec['final_url']=r.url
  namefile=name+'.json'; (out/namefile).write_bytes(data)
  rec.update(path=namefile,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),retrieved_at=stamp())
  p=json.loads(data)
  if not isinstance(p,dict): raise ValueError('JSON_OBJECT_REQUIRED')
  tables=p.get('tables',[])
  rows=p.get('data',[]) if market=='TWSE' else [row for table in tables for row in table.get('data',[])]
  expected=start.strftime('%Y%m%d')+'~'+end.strftime('%Y%m%d')
  rec.update(provider_status=p.get('stat'),provider_range=p.get('date'),rows=len(rows),fields=p.get('fields') if market=='TWSE' else [t.get('fields') for t in tables])
  range_ok=(p.get('startDate',p.get('strDate'))==start.strftime('%Y%m%d') and p.get('endDate')==end.strftime('%Y%m%d')) if market=='TWSE' else p.get('date')==expected
  rec['range_verified']=range_ok
  rec['status']='RAW_RANGE_VERIFIED' if str(p.get('stat','')).lower()=='ok' and range_ok else 'RAW_REVIEW_REQUIRED'
 except Exception as e: rec.update(status='FETCH_OR_SCHEMA_FAILED',error=type(e).__name__+': '+str(e))
 rec['completed_at']=stamp(); return rec

def run(start,end,out):
 start=dt.date.fromisoformat(start);end=dt.date.fromisoformat(end)
 if start>end or (end-start).days>31: raise ValueError('INVALID_OR_EXCESSIVE_RANGE')
 out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=False)
 result={'started_at':stamp(),'coverage_from':start.isoformat(),'coverage_through':end.isoformat(),'sources':[],'prices_refetched':0,'existing_official_quotes_refetched':0,'formal_input_qualified':False,'prediction_generated':False}
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  for r in pool.map(lambda x:fetch_one(x,start,end,out),ENDPOINTS.items()):
   result['sources'].append(r);write(out/'actions_receipt.json',result)
 result['completed_at']=stamp();result['all_sources_fetched']=all(x['status']!='FETCH_OR_SCHEMA_FAILED' for x in result['sources'])
 result['all_requested_ranges_verified']=all(x.get('range_verified') for x in result['sources'])
 result['limitation']='These sources cover only their named categories and stated range. Trading suspension, effective dates, issuer announcements, price continuity and original model gates still require review. Empty arrays without validated range are not no-event proof.'
 write(out/'actions_receipt.json',result);print(json.dumps(result,ensure_ascii=False))
 return 0 if result['all_sources_fetched'] and result['all_requested_ranges_verified'] else 2
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(run(a.start,a.end,a.out))
