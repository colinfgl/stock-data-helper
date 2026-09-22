"""Bounded public-only retrieval. No portfolio, prediction or synthetic values."""
import concurrent.futures as cf,datetime as dt,hashlib,json,pathlib,urllib.request,urllib.parse
OUT=pathlib.Path('public_gap_sources');OUT.mkdir(exist_ok=False)
JOBS=[('index_20260601.json', 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=20260601&response=json'), ('index_20260701.json', 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=20260701&response=json'), ('index_20260801.json', 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=20260801&response=json'), ('index_20260901.json', 'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=20260901&response=json'), ('chart_00400A_exact.json', 'https://query1.finance.yahoo.com/v8/finance/chart/00400A.TW?interval=1d&period1=1789660800&period2=1790006400&events=div%2Csplits&includeAdjustedClose=true'), ('chart_009820_exact.json', 'https://query1.finance.yahoo.com/v8/finance/chart/009820.TW?interval=1d&period1=1789660800&period2=1790006400&events=div%2Csplits&includeAdjustedClose=true')]
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
