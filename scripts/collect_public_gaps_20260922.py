"""Bounded public-only retrieval. No portfolio, prediction or synthetic values."""
import concurrent.futures as cf,datetime as dt,hashlib,json,pathlib,urllib.request,urllib.parse
OUT=pathlib.Path('public_gap_sources');OUT.mkdir(exist_ok=False)
DATES_PLACEHOLDER = ['20260825', '20260826', '20260827', '20260828', '20260831', '20260901', '20260902', '20260903', '20260904', '20260907', '20260908', '20260909', '20260910', '20260911', '20260914', '20260915', '20260916', '20260917', '20260918', '20260921']
JOBS=[]
for code in ['00400A','009820']:
 for host,period in [('query1.finance.yahoo.com','1mo'),('query2.finance.yahoo.com','3mo')]:
  JOBS.append((f'chart_{code}_{period}.json',f'https://{host}/v8/finance/chart/{code}.TW?interval=1d&range={period}&events=div%2Csplits&includeAdjustedClose=true'))
for code in ['2330','2383']:
 for month in ['20260601','20260701','20260801','20260901']:
  JOBS.append((f'price_{code}_{month}.json',f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={month}&stockNo={code}&response=json'))
for date in DATES_PLACEHOLDER:
 JOBS.append((f'chips_{date}.json',f'https://www.twse.com.tw/rwd/zh/fund/T86?date={date}&selectType=ALLBUT0999&response=json'))
JOBS.append(('exdiv.json','https://www.twse.com.tw/rwd/zh/exRight/TWT49U?response=json&startDate=20260601&endDate=20260921'))
JOBS.append(('margin.json','https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20260921&selectType=ALL&response=json'))
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def get(job):
 name,url=job;r={'name':name,'url':url,'started_at':now(),'status':'FAILED'}
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
  with urllib.request.urlopen(req,timeout=12) as f:
   b=f.read(12000001);r['http_status']=f.status
  if len(b)>12000000:raise ValueError('TOO_LARGE')
  (OUT/name).write_bytes(b);r.update(bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
  j=json.loads(b);r.update(status='FETCHED',payload_status=j.get('stat'),payload_date=j.get('date'))
 except Exception as e:r['error']=type(e).__name__+': '+str(e)
 r['completed_at']=now();return r
started=now()
with cf.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(get,JOBS))
r={'started_at':started,'completed_at':now(),'cutoff':'2026-09-21','sources':rows,'scope':'Public source retrieval only; no predictions; no qualification inferred from transport success'}
(OUT/'receipt.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
print(json.dumps({'fetched':sum(x['status']=='FETCHED' for x in rows),'requested':len(rows),'failed':[x['name'] for x in rows if x['status']!='FETCHED']}))
