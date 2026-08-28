from __future__ import annotations

import calendar, csv, hashlib, io, json, re, sys, time, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

SOURCE_REPO='yukishirotsubasa/tw-stock-data-release'; SOURCE_TAG='daily-close-csv'; CUTOFF='20260817'
OUT=Path('output_all20_v2'); OUT.mkdir(exist_ok=True)
TARGETS={
 '0050':('元大台灣50','TWSE','20180102',2092),'00400A':('主動國泰動能高息','TWSE','20260409',90),'009820':('元大納斯達克精選','TWSE','20260423',80),
 '2207':('和泰車','TWSE','20180102',2097),'2308':('台達電','TWSE','20180102',2097),'2317':('鴻海','TWSE','20180102',2091),'2330':('台積電','TWSE','20180102',2097),
 '2368':('金像電','TWSE','20180102',2090),'2376':('技嘉','TWSE','20180102',2097),'2382':('廣達','TWSE','20180102',2097),'2383':('台光電','TWSE','20180102',2097),
 '2454':('聯發科','TWSE','20180102',2097),'2634':('漢翔','TWSE','20180102',2097),'2834':('臺企銀','TWSE','20180102',2097),'2885':('元大金','TWSE','20180102',2097),
 '3293':('鈊象','TPEX','20180102',2097),'3491':('昇達科','TPEX','20180102',2097),'3665':('貿聯-KY','TWSE','20180102',2094),'4916':('事欣科','TWSE','20180102',2094),
 '6770':('力積電','TWSE','20211206',1135),}
EXPECTED_TOTAL_SOURCE=36930; EXPECTED_TOTAL_NO_TRADE=6; EXPECTED_TOTAL_PRICE=36924
EXPECTED_LAST3_EVENTS={'3665':9,'4916':9,'6770':3}
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper/2.0'})

def get(url, timeout=120, tries=5):
 last=None
 for i in range(tries):
  try:
   r=S.get(url,timeout=timeout); r.raise_for_status(); return r
  except Exception as e:
   last=e; time.sleep(1.2*(i+1))
 raise last

def dec(x):
 s=str(x or '').strip().replace(',','').replace('−','-').replace('－','-'); s=re.sub(r'<[^>]+>','',s).strip()
 if s in ('','--','---','N/A','nan','None'): return None
 try:return Decimal(s)
 except InvalidOperation:return None

def norm_date(x):
 s=re.sub(r'<[^>]+>','',str(x or '')).strip().replace('年','/').replace('月','/').replace('日','')
 m=re.search(r'(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})',s)
 if m:
  y,mo,d=map(int,m.groups()); y=y+1911 if y<1911 else y; return f'{y:04d}{mo:02d}{d:02d}'
 digs=re.sub(r'\D','',s)
 if len(digs)==8:return digs
 if len(digs)==7:
  y=int(digs[:3])+1911;return f'{y:04d}{digs[3:5]}{digs[5:7]}'
 return None

def roc_date(yyyymmdd):
 y=int(yyyymmdd[:4])-1911; return f'{y}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}'

def months(start='20180101',end=CUTOFF):
 y,m=int(start[:4]),int(start[4:6]); ey,em=int(end[:4]),int(end[4:6])
 while (y,m)<=(ey,em):
  last=calendar.monthrange(y,m)[1]; s=f'{y:04d}{m:02d}01'; e=f'{y:04d}{m:02d}{last:02d}'
  if e>end:e=end
  yield s,e
  m+=1
  if m==13:y+=1;m=1

def release_assets():
 rel=get(f'https://api.github.com/repos/{SOURCE_REPO}/releases/tags/{SOURCE_TAG}').json(); out=[]
 for a in rel.get('assets',[]):
  n=a['name']
  if re.fullmatch(r'yearly_20(18|19|20|21|22|23|24|25)\.zip',n):out.append(a)
  elif re.fullmatch(r'weekly_2026_W\d{2}\.zip',n) and int(re.search(r'W(\d+)',n).group(1))<=34:out.append(a)
 return sorted(out,key=lambda a:a['name'])

def read_zip(blob,asset):
 z=zipfile.ZipFile(io.BytesIO(blob))
 for fn in z.namelist():
  if not fn.lower().endswith('.csv'):continue
  b=z.read(fn)
  try:t=b.decode('utf-8-sig')
  except UnicodeDecodeError:t=b.decode('cp950',errors='replace')
  for row in csv.DictReader(io.StringIO(t)):
   lo={str(k).strip().lower():v for k,v in row.items()}; code=str(lo.get('code') or lo.get('代號') or '').strip()
   if code not in TARGETS:continue
   d=re.sub(r'\D','',str(lo.get('date') or lo.get('日期') or ''))[:8]; start=TARGETS[code][2]
   if len(d)!=8 or not(start<=d<=CUTOFF):continue
   yield {'date':d,'code':code,'name':str(lo.get('name') or lo.get('名稱') or TARGETS[code][0]).strip(),'market':TARGETS[code][1],
          'volume':str(lo.get('volume') or lo.get('成交股數') or '').replace(',','').strip(),'open':str(lo.get('open') or lo.get('開盤') or '').replace(',','').strip(),
          'high':str(lo.get('high') or lo.get('最高') or '').replace(',','').strip(),'low':str(lo.get('low') or lo.get('最低') or '').replace(',','').strip(),
          'close':str(lo.get('close') or lo.get('收盤') or '').replace(',','').strip(),'source_asset':asset}

def build_release():
 by=defaultdict(dict); manifest=[]
 for i,a in enumerate(release_assets(),1):
  n=a['name']; print('asset',i,n,flush=True); blob=get(a['browser_download_url']).content
  sha=hashlib.sha256(blob).hexdigest(); exp=(a.get('digest') or '').replace('sha256:',''); added=0
  for r in read_zip(blob,n):
   old=by[r['code']].get(r['date'])
   if old and any(old[k]!=r[k] for k in ('volume','open','high','low','close')):raise RuntimeError(f'duplicate conflict {r["code"]} {r["date"]}')
   if not old:by[r['code']][r['date']]=r;added+=1
  manifest.append([n,len(blob),sha,exp,sha==exp,added,a['browser_download_url']])
 return by,manifest

def twse_month_rows(code,yyyymm):
 u=f'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={yyyymm}01&stockNo={code}&response=json'; j=get(u,30).json()
 out={}
 for row in j.get('data',[]):
  d=norm_date(row[0])
  if not d:continue
  out[d]={'date':d,'code':code,'name':TARGETS[code][0],'market':'TWSE','volume':str(row[1]).replace(',','').strip(),
          'open':str(row[3]).replace(',','').strip(),'high':str(row[4]).replace(',','').strip(),'low':str(row[5]).replace(',','').strip(),'close':str(row[6]).replace(',','').strip(),
          'source_asset':f'TWSE_STOCK_DAY_{yyyymm}'}
 return out,u

def tpex_daily_row(code,d):
 u=f'https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=csv&d={roc_date(d)}&s=0,asc,0'
 r=get(u,30); text=r.content.decode('utf-8-sig',errors='replace')
 for row in csv.reader(io.StringIO(text)):
  cells=[re.sub(r'^=','',x).strip().strip('"') for x in row]
  if len(cells)<9:continue
  c=re.sub(r'\D','',cells[0])
  if c!=code:continue
  # code,name,close,change,open,high,low,avg,shares,...
  return {'date':d,'code':code,'name':TARGETS[code][0],'market':'TPEX','volume':cells[8].replace(',',''),'open':cells[4].replace(',',''),'high':cells[5].replace(',',''),'low':cells[6].replace(',',''),'close':cells[2].replace(',',''),'source_asset':f'TPEX_DAILY_{d}'},u
 return None,u

def fill_gaps(by):
 calendar_dates=set(by['3293'])
 fills=[]; unresolved=[]
 for code,(name,market,start,expected) in TARGETS.items():
  cand=sorted(d for d in calendar_dates if start<=d<=CUTOFF and d not in by[code])
  if not cand:continue
  if market=='TWSE':
   groups=defaultdict(list)
   for d in cand:groups[d[:6]].append(d)
   for ym,ds in groups.items():
    try:off,u=twse_month_rows(code,ym)
    except Exception as e:
     unresolved.extend([[code,d,'TWSE_FETCH_ERROR',repr(e)] for d in ds]);continue
    for d in ds:
     if d in off:
      by[code][d]=off[d];fills.append([code,d,'TWSE_STOCK_DAY',u])
  else:
   for d in cand:
    try:r,u=tpex_daily_row(code,d)
    except Exception as e:
     unresolved.append([code,d,'TPEX_FETCH_ERROR',repr(e)]);continue
    if r:by[code][d]=r;fills.append([code,d,'TPEX_DAILY',u])
  # Remaining absent dates may be legitimate suspensions; only count mismatch later decides.
 return fills,unresolved

def parse_twse_actions():
 events=[]; errors=[]
 for s,e in months():
  u=f'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={s}&endDate={e}&response=json'
  try:j=get(u,30).json()
  except Exception as ex:errors.append([s,e,'TWSE',repr(ex),u]);continue
  if j.get('stat')!='OK' and not j.get('data'):continue
  fields=j.get('fields',[])
  for row in j.get('data',[]):
   if len(row)<5:continue
   d=norm_date(row[0]); code=re.sub(r'<[^>]+>','',str(row[1])).strip(); pre=dec(row[3]); ref=dec(row[4])
   if code in TARGETS and TARGETS[code][1]=='TWSE' and d and TARGETS[code][2]<=d<=CUTOFF and pre and ref and pre>0 and ref>0:
    events.append({'event_date':d,'code':code,'name':TARGETS[code][0],'market':'TWSE','previous_close':pre,'reference_price':ref,'factor':ref/pre,'official_source':u})
 return events,errors

def parse_tpex_actions():
 events=[];errors=[]
 for s,e in months():
  u=f'https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d={roc_date(s)}&ed={roc_date(e)}'
  try:j=get(u,30).json()
  except Exception as ex:errors.append([s,e,'TPEX',repr(ex),u]);continue
  tables=j.get('tables') or []
  rows=(tables[0].get('data',[]) if tables else (j.get('aaData') or j.get('data') or []))
  for row in rows:
   if len(row)<5:continue
   d=norm_date(row[0]); code=re.sub(r'<[^>]+>','',str(row[1])).strip(); pre=dec(row[3]); ref=dec(row[4])
   if code in TARGETS and TARGETS[code][1]=='TPEX' and d and TARGETS[code][2]<=d<=CUTOFF and pre and ref and pre>0 and ref>0:
    events.append({'event_date':d,'code':code,'name':TARGETS[code][0],'market':'TPEX','previous_close':pre,'reference_price':ref,'factor':ref/pre,'official_source':u})
 return events,errors

def prev_valid(rows,event_date):
 for r in reversed(rows):
  if r['date']>=event_date:continue
  if all(dec(r[k]) is not None for k in ('open','high','low','close')):return r
 return None

def main():
 by,manifest=build_release(); fills,unresolved=fill_gaps(by)
 tw,twerr=parse_twse_actions(); tp,tperr=parse_tpex_actions(); evdict={}
 for e in tw+tp:evdict[(e['code'],e['event_date'])]=e
 events=sorted(evdict.values(),key=lambda x:(x['code'],x['event_date'])); byev=defaultdict(list)
 for e in events:byev[e['code']].append(e)

 qas=[]; event_out=[]; combined=[]; all_ok=True
 for code,(name,market,start,expected) in TARGETS.items():
  rows=sorted(by[code].values(),key=lambda x:x['date']); source=len(rows); no_trade=0; price=0; bad=0; dup=source-len({x['date'] for x in rows})
  for r in rows:
   vals=[dec(r[k]) for k in ('open','high','low','close')]; vol=dec(r['volume'])
   if all(v is None for v in vals) and (vol is None or vol==0):no_trade+=1;continue
   if any(v is None for v in vals):bad+=1;continue
   o,h,l,c=vals;price+=1
   if h<max(o,c) or l>min(o,c) or h<l:bad+=1
  count_ok=(source==expected); date_ok=bool(rows) and rows[0]['date']==start and rows[-1]['date']==CUTOFF
  evs=byev.get(code,[]); invalid=0; prev_mis=0
  if code not in ('00400A','009820') and not evs:invalid+=1
  if code in EXPECTED_LAST3_EVENTS and len(evs)!=EXPECTED_LAST3_EVENTS[code]:invalid+=1
  for e in evs:
   pr=prev_valid(rows,e['event_date']); actual=dec(pr['close']) if pr else None; pm=actual is not None and abs(actual-e['previous_close'])<=Decimal('0.05')
   if not pm:prev_mis+=1
   valid=e['factor']>0
   if not valid:invalid+=1
   event_out.append([e['event_date'],code,name,market,str(e['previous_close']),str(e['reference_price']),f'{e["factor"]:.12f}',pr['date'] if pr else '',str(actual) if actual is not None else '',pm,'PASS' if valid else 'FAIL',e['official_source']])
  stock_ok=count_ok and date_ok and dup==0 and bad==0 and invalid==0; all_ok=all_ok and stock_ok
  qas.append([code,name,market,source,price,no_trade,expected,count_ok,start,rows[0]['date'] if rows else '',CUTOFF,rows[-1]['date'] if rows else '',dup,bad,len(evs),prev_mis,invalid,stock_ok])
  for r in rows:
   f=Decimal('1')
   for e in evs:
    if e['event_date']>r['date']:f*=e['factor']
   vals=[dec(r[k]) for k in ('open','high','low','close')]; nt=all(v is None for v in vals)
   adj=['','','',''] if nt else [f'{(v*f):.6f}' if v is not None else '' for v in vals]
   combined.append([r['date'],code,name,market,r['volume'],r['open'],r['high'],r['low'],r['close'],r['source_asset'],nt,f'{f:.12f}',*adj,'OK' if nt or all(v is not None for v in vals) else 'FAIL'])

 totals={'source_rows_total':sum(int(x[3]) for x in qas),'price_rows_total':sum(int(x[4]) for x in qas),'no_trade_rows_total':sum(int(x[5]) for x in qas)}
 totals_ok=(totals['source_rows_total']==EXPECTED_TOTAL_SOURCE and totals['price_rows_total']==EXPECTED_TOTAL_PRICE and totals['no_trade_rows_total']==EXPECTED_TOTAL_NO_TRADE)
 all_ok=all_ok and totals_ok and len(events)>0 and not twerr and not tperr
 with open(OUT/'source_manifest.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['asset','size_bytes','sha256','expected_sha256','sha_ok','release_rows_added','url']);w.writerows(manifest)
 with open(OUT/'gap_fills.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['code','date','source','url']);w.writerows(fills)
 with open(OUT/'gap_unresolved.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['code','date','reason','detail']);w.writerows(unresolved)
 with open(OUT/'corporate_actions_all20.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['event_date','code','name','market','official_previous_close','official_reference_price','factor','previous_trade_date','actual_previous_close','previous_close_match','status','official_source']);w.writerows(event_out)
 with open(OUT/'all20_qa_summary.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['code','name','market','source_rows','price_rows','no_trade_rows','expected_source_rows','source_count_match','expected_start','actual_start','expected_end','actual_end','duplicate_rows','price_or_ohlc_bad_rows','corporate_action_events','previous_close_mismatches_info','event_invalid','pass']);w.writerows(qas)
 with open(OUT/'price_history_all20_adjusted.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['date','code','name','market','volume','open','high','low','close','source_asset','no_trade_placeholder','cumulative_factor','adj_open','adj_high','adj_low','adj_close','qa_status']);w.writerows(combined)
 with open(OUT/'action_fetch_errors.csv','w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['start','end','market','error','url']);w.writerows(twerr+tperr)
 report={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'cutoff':CUTOFF,**totals,'expected_source_rows_total':EXPECTED_TOTAL_SOURCE,'expected_price_rows_total':EXPECTED_TOTAL_PRICE,'expected_no_trade_rows_total':EXPECTED_TOTAL_NO_TRADE,'gap_fills':len(fills),'gap_unresolved_candidates':len(unresolved),'corporate_action_events_total':len(events),'twse_action_fetch_errors':len(twerr),'tpex_action_fetch_errors':len(tperr),'stocks':len(qas),'all_pass':all_ok}
 (OUT/'all20_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2),flush=True);sys.exit(0 if all_ok else 2)
if __name__=='__main__':main()
