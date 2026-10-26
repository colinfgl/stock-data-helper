"""Verified, source-only market-session overlays. No price edits or formal credit."""
from __future__ import annotations
import datetime as dt,hashlib,json,pathlib,urllib.request,shutil,tempfile
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Taipei')
REVIEWS=[{'date':'2026-10-23','published_date':'2026-10-22','reviewed_at':'2026-10-25T08:39:52.792776+00:00','scope':'TWSE_TPEX_FULL_DAY','evidence':[
 {'venue':'TWSE','url':'https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d6a0fa351b01a1638507940202.pdf','sha256':'07cdb8663b36ad6a89f4568fd653f6bdb8c2699af60781187c1d8e77279cbd5f','name':'twse_closure_20261023.pdf'},
 {'venue':'TPEX','url':'https://www.tpex.org.tw/www/zh-tw/news/detail?id=23117','sha256':'5f4f06dbe27a1bf5c4cf8731dda35ad29e15a1338e8cf3e23cef15f53d0bc220','name':'tpex_closure_20261023.json'}]}]
def req(v,m):
 if not v:raise ValueError(m)
def digest(b):return hashlib.sha256(b).hexdigest()
def aware(s):
 x=dt.datetime.fromisoformat(s.replace('Z','+00:00'));req(x.tzinfo is not None,'CLOSURE_AWARE_TIME_REQUIRED');return x
def fetch_raw(url,path):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 stock-source-calendar/1.0'}),timeout=20) as r:
  req(r.status==200,'CLOSURE_HTTP_STATUS');raw=r.read(1048577);req(len(raw)<=1048576,'CLOSURE_RESPONSE_SIZE')
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('xb') as f:f.write(raw)
 return dt.datetime.now(dt.timezone.utc).isoformat()
def fetch_context(candidate,root,now,fetcher=fetch_raw,reviews=None):
 req(now.tzinfo is not None,'CLOSURE_NAIVE_CLOCK');root=pathlib.Path(root);root.mkdir(parents=True,exist_ok=True);entries=[]
 for review in REVIEWS if reviews is None else reviews:
  day=dt.date.fromisoformat(review['date'])
  if abs((day-candidate).days)>10 or aware(review['reviewed_at'])>now:continue
  req(review['scope']=='TWSE_TPEX_FULL_DAY' and set(e['venue'] for e in review['evidence'])=={'TWSE','TPEX'},'CLOSURE_SCOPE_REVIEW')
  item={k:review[k] for k in ['date','published_date','reviewed_at','scope']};item['evidence']=[]
  for e in review['evidence']:
   path=root/e['name'];retrieved=fetcher(e['url'],path);req(path.is_file() and digest(path.read_bytes())==e['sha256'],'CLOSURE_FETCH_SHA')
   item['evidence'].append({**e,'file':e['name'],'retrieved_at':retrieved})
  entries.append(item)
 return {'closures':entries,'formal_input_qualified':False,'natural_credit':0,'oos_credit':0}
def verify_context(context,root,now=None,reviews=None):
 now=now or dt.datetime.now(dt.timezone.utc);req(now.tzinfo is not None,'CLOSURE_NAIVE_CLOCK');root=pathlib.Path(root).resolve();known={r['date']:r for r in (REVIEWS if reviews is None else reviews)}
 req(context.get('formal_input_qualified') is False and context.get('natural_credit')==context.get('oos_credit')==0,'CLOSURE_NO_FORMAL_CREDIT');closed=set();seen=set()
 for item in context['closures']:
  req(item['date'] in known and item['date'] not in seen,'CLOSURE_UNREGISTERED_OR_DUPLICATE');seen.add(item['date']);review=known[item['date']]
  req(all(item[k]==review[k] for k in ['published_date','reviewed_at','scope']) and aware(item['reviewed_at'])<=now,'CLOSURE_REVIEW_BINDING')
  req(dt.date.fromisoformat(item['published_date'])<=now.astimezone(TZ).date(),'CLOSURE_PUBLICATION_AFTER_NOW')
  req(len(item['evidence'])==2 and {e['venue'] for e in item['evidence']}=={'TWSE','TPEX'},'CLOSURE_BOTH_MARKETS_REQUIRED')
  for e in item['evidence']:
   expected=next(x for x in review['evidence'] if x['venue']==e['venue']);req(all(e[k]==expected[k] for k in ['url','sha256','name']),'CLOSURE_SOURCE_BINDING');p=(root/e['file']).resolve();req(p.is_relative_to(root),'CLOSURE_PATH_ESCAPE');req(aware(e['retrieved_at'])<=now and digest(p.read_bytes())==expected['sha256'],'CLOSURE_ORIGINAL_SHA_OR_TIME')
  closed.add(dt.date.fromisoformat(item['date']))
 return closed
def retain_context(context,source_root,dest):
 verify_context(context,source_root);dest=pathlib.Path(dest);out=json.loads(json.dumps(context))
 for item in out['closures']:
  for e in item['evidence']:
   p=dest/'reviewed_closures'/e['name'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(pathlib.Path(source_root)/e['file'],p);e['file']=p.relative_to(dest).as_posix()
 verify_context(out,dest);return out
def completed_session(candidate,closed,years):
 day=candidate
 for _ in range(32):
  req(day.year in years,'COMPLETED_SESSION_YEAR_UNVERIFIED')
  if day.weekday()<5 and day not in closed:return day
  day-=dt.timedelta(days=1)
 raise ValueError('COMPLETED_SESSION_NOT_FOUND_IN_VERIFIED_WINDOW')
def selftest():
 checks={};now=dt.datetime(2026,10,26,7,tzinfo=TZ);day=dt.date(2026,10,23);closed={dt.date(2026,10,26),day}
 def reject(n,f):
  try:f();checks[n]=False
  except (ValueError,FileNotFoundError):checks[n]=True
 checks['typhoon_source23_resolves22']=completed_session(day,closed,{2026})==dt.date(2026,10,22)
 checks['weekend24_resolves22']=completed_session(dt.date(2026,10,24),closed,{2026})==dt.date(2026,10,22)
 checks['holiday26_resolves22']=completed_session(dt.date(2026,10,26),closed,{2026})==dt.date(2026,10,22)
 checks['ordinary27_remains27']=completed_session(dt.date(2026,10,27),closed,{2026})==dt.date(2026,10,27)
 reject('unknown_year_holds',lambda:completed_session(dt.date(2027,1,1),closed,{2026}))
 # Test-only records cannot pass the default production review bindings.
 a=b'%PDF-test-only';b=b'{"test_only":true}';review={'date':'2026-10-23','published_date':'2026-10-22','reviewed_at':'2026-10-25T08:39:52.792776+00:00','scope':'TWSE_TPEX_FULL_DAY','evidence':[dict(REVIEWS[0]['evidence'][0],sha256=digest(a)),dict(REVIEWS[0]['evidence'][1],sha256=digest(b))]}
 def fake(url,path):path.write_bytes(a if url.endswith('.pdf') else b);return (now-dt.timedelta(seconds=1)).isoformat()
 with tempfile.TemporaryDirectory() as td:
  root=pathlib.Path(td);ctx=fetch_context(day,root,now,fake,[review]);checks['both_reviewed_bytes_verified']=verify_context(ctx,root,now,[review])=={day}
  reject('synthetic_context_not_production_proof',lambda:verify_context(ctx,root,now))
  bad=json.loads(json.dumps(ctx));bad['closures'][0]['evidence'].pop();reject('one_market_missing_holds',lambda:verify_context(bad,root,now,[review]))
  bad=json.loads(json.dumps(ctx));bad['closures'][0]['evidence'][0]['retrieved_at']=(now+dt.timedelta(seconds=1)).isoformat();reject('late_acquisition_holds',lambda:verify_context(bad,root,now,[review]))
  bad=json.loads(json.dumps(ctx));bad['closures'][0]['scope']='UNKNOWN';reject('wrong_scope_holds',lambda:verify_context(bad,root,now,[review]))
  (root/review['evidence'][0]['name']).write_bytes(b'changed');reject('raw_tamper_holds',lambda:verify_context(ctx,root,now,[review]))
 checks['historic_sources_not_rewritten']=REVIEWS[0]['date']=='2026-10-23' and REVIEWS[0]['published_date']=='2026-10-22'
 return {'status':'PASS' if all(checks.values()) else 'FAIL','passed':sum(checks.values()),'total':len(checks),'cases':checks,'scope':'SYNTHETIC_ENGINEERING_ONLY_NO_MARKET_OR_FORMAL_CREDIT'}
if __name__=='__main__':print(json.dumps(selftest()))
