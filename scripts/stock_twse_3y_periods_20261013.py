#!/usr/bin/env python3
"""Run a bounded 35-month missing-only 3-year TWSE ex-date retrieval.

Existing verified windows 2026-08-17..09-16 and 09-17..10-12 are not
retrieved again; caller must combine their previously verified SHA originals.
Works with public exchange pages only. It never claims issuer-wide exhaustive
corporate actions or qualifications for formal predictive modeling.
"""
from __future__ import annotations
import argparse, calendar, datetime as dt, hashlib,json,pathlib,subprocess,sys

def months():
 out=[];yr,mo=2023,10
 while (yr,mo)<=(2026,8):
  first=dt.date(yr,mo,1);last=dt.date(yr,mo,calendar.monthrange(yr,mo)[1]);
  first=max(first,dt.date(2023,10,12));last=min(last,dt.date(2026,8,16))
  if first<=last:out.append((first,last))
  mo+=1
  if mo>12:mo=1;yr+=1
 return out

def selftest():
 m=months(); dates=[]
 for first,last in m:
  assert last>=first,(first,last)
  assert (last-first).days<=100,(first,last)
  d=first
  while d<=last:dates.append(d);d+=dt.timedelta(days=1)
 unique=len(set(dates))==len(dates)
 continuous=dates==[dt.date(2023,10,12)+dt.timedelta(days=i) for i in range((dt.date(2026,8,16)-dt.date(2023,10,12)).days+1)]
 tests={'months35':len(m)==35,'start':m[0][0]==dt.date(2023,10,12),'end':m[-1][1]==dt.date(2026,8,16),
        'every_day_once':unique,'continuous':continuous,'not_after_actual_cutoff':max(dates)<dt.date(2026,10,13),
        'four_worker_partition':sum(len(m[i::4]) for i in range(4))==35,
        'no_overlap_recovered_ranges':m[-1][1]<dt.date(2026,8,17)}
 assert all(tests.values()),tests
 return {'status':'PASS','tests':tests,'n_tests':len(tests),'months':len(m)}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--batch',type=int,choices=range(4));ap.add_argument('--out');ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
 if a.self_test:print(json.dumps(selftest()));return 0
 if a.batch is None or not a.out:ap.error('batch 0-3 and --out required')
 out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 script=pathlib.Path(__file__).with_name('stock_twse_exdate_range_firstparty_20261013.py')
 results=[]
 for start,end in months()[a.batch::4]:
  key=start.strftime('%Y%m%d')+'_'+end.strftime('%Y%m%d');target=out/key
  cmd=[sys.executable,str(script),'--start',start.isoformat(),'--end',end.isoformat(),'--out',str(target)]
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=35)
  receipt=target/'receipt.json'
  if receipt.exists():
   d=json.loads(receipt.read_bytes())
  else:d={'status':'CAPTURE_EXCEPTION_HOLD','stderr':p.stderr[-260:],'stdout':p.stdout[-260:]}
  results.append({'period':key,'from':start.isoformat(),'to':end.isoformat(),'status':d.get('status'),
                  'source_sha256':d.get('source_sha256'),'primary_event_rows':d.get('primary_event_rows'),
                  'raw_bytes':d.get('source_bytes'),'failure':d.get('failure'),'exit_code':p.returncode})
  print(json.dumps(results[-1],ensure_ascii=False),flush=True)
 state='PASS_ALL_MONTHLY_WINDOWS' if all(x['status']=='PASS_FIRSTPARTY_SCOPE_ONLY' for x in results) else 'PARTIAL_OFFICIAL_WINDOW_HOLD'
 data={'run_role':'TWSE_EXDATE_3YR_RESEARCH_ONLY','batch':a.batch,'status':state,'window_count':len(results),
       'window_pass_count':sum(x['status']=='PASS_FIRSTPARTY_SCOPE_ONLY' for x in results),
       'retrieval_after_preopen':True,'already_completed_nonrefetched':['20260817_20260916','20260917_20261012'],
       'issuer_actions_exhaustive':False,'official_tpex_corporate_actions_included':False,
       'formal_prediction_count':0,'natural_oos_credit':0,'rows':results}
 (out/'batch_summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print('FINAL '+json.dumps({k:v for k,v in data.items()if k!='rows'},ensure_ascii=False))
 return 0 if state=='PASS_ALL_MONTHLY_WINDOWS' else 2
if __name__=='__main__':sys.exit(main())