#!/usr/bin/env python3
"""Fetch only missing official action evidence. No price construction or predictions."""
import concurrent.futures as cf
import datetime as dt
import hashlib,json,pathlib,re,urllib.request
OUT=pathlib.Path('b1_actions_output');OUT.mkdir(exist_ok=True)
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()
def dump(name,x):(OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
JOBS=[
('twse_reduction_reference','https://www.twse.com.tw/reducation/TWTAUU?response=json&startDate=20260917&endDate=20260921'),
('twse_etf_split_reference','https://www.twse.com.tw/split/TWTCAU?response=json&startDate=20260917&endDate=20260921'),
('tpex_reduction_reference','https://www.tpex.org.tw/www/zh-tw/bulletin/revivt?startDate=2026%2F09%2F17&endDate=2026%2F09%2F21&response=json'),
('twse_reduction_notice_page','https://www.twse.com.tw/zh/announcement/reduction/twtavu.html'),
('twse_denomination_notice_page','https://www.twse.com.tw/zh/announcement/change/twtb7u.html'),
('twse_denomination_reference_page','https://www.twse.com.tw/zh/announcement/change/twtb8u.html'),
('twse_etf_split_notice_page','https://www.twse.com.tw/zh/announcement/split/twtc9u.html'),
('tpex_main_js','https://www.tpex.org.tw/rsrc/js/main.js'),
('tpex_menu','https://www.tpex.org.tw/zh-tw/sitemap.html')]
def fetch(item):
 key,url=item;r={'source_id':key,'url':url,'started_at':stamp(),'qualified':False}
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json,text/html'})
  with urllib.request.urlopen(req,timeout=20) as f:b=f.read();r.update(status='FETCHED',http_status=f.status,final_url=f.url,content_type=f.headers.get('Content-Type'))
  (OUT/(key+'.raw')).write_bytes(b);r.update(path=key+'.raw',sha256=hashlib.sha256(b).hexdigest(),bytes=len(b),retrieved_at=stamp())
  try:p=json.loads(b);r['payload_type']=type(p).__name__
  except ValueError:r['payload_type']='NOT_JSON'
  r['declared_api_paths']=re.findall(r'data-api="([^"]+)"',b.decode('utf8',errors='replace'))
 except Exception as e:r.update(status='FETCH_FAILED',error=str(e),completed_at=stamp())
 return r
def main():
 result={'started_at':stamp(),'scope_from':'2026-09-17','scope_through':'2026-09-21','sources':[],'formal_input_qualified':False,'model_runs':0,'price_requests':0}
 with cf.ThreadPoolExecutor(max_workers=3) as pool:
  for row in pool.map(fetch,JOBS):result['sources'].append(row);dump('action_acquisition.json',result)
 nextjobs=[]
 for src in result['sources']:
  for path in src.get('declared_api_paths',[]):
   if not re.fullmatch(r'/(?:reducation|change|split)/[A-Z0-9]+',path):continue
   url='https://www.twse.com.tw'+path+'?response=json&startDate=20260917&endDate=20260921'
   nextjobs.append((src['source_id'].replace('_page','_data'),url))
 with cf.ThreadPoolExecutor(max_workers=3) as pool:
  for row in pool.map(fetch,nextjobs):result['sources'].append(row);dump('action_acquisition.json',result)
 result['completed_at']=stamp();dump('action_acquisition.json',result)
 print(json.dumps({'sources':len(result['sources']),'fetched':sum(s['status']=='FETCHED' for s in result['sources']),'formal_input_qualified':False}))
if __name__=='__main__':main()
