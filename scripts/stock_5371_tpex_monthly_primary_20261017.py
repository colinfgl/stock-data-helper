#!/usr/bin/env python3
"""TPEx primary month-by-month raw OHLC 5371 history; research-only, no formal/PIT splice."""
import argparse,datetime as dt,hashlib,json,math,pathlib,time,urllib.parse,urllib.request
CODE='5371';LAST='2026-08-21';LAST_CLOSE=83.5
BASE='https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php'
def dates():
 y,m=2024,8
 while (y,m)<=(2026,8):
  yield y,m
  m+=1
  if m>12:y,m=y+1,1
def parse(raw,year,month):
 o=json.loads(raw.decode('utf-8-sig'))
 assert isinstance(o,dict),'SOURCE_NOT_OBJECT'
 assert str(o.get('stat','OK')).upper() in ('OK','','SUCCESS'),'SOURCE_STATUS_NOT_OK'
 aa=o.get('aaData')
 assert isinstance(aa,list),'MONTHLY_AADATA_MISSING'
 if not aa:return []
 out=[];seen=set()
 for row in aa:
  assert isinstance(row,list) and len(row)>=7,'ROW_FORMAT_INVALID'
  yy,mm,dd=map(int,str(row[0]).strip().replace('-','/').split('/'))
  date=dt.date(yy+1911 if yy<1911 else yy,mm,dd)
  assert (date.year,date.month)==(year,month),'DATE_MONTH_MISMATCH'
  day=date.isoformat()
  assert day not in seen,'DUPLICATE_DATE';seen.add(day)
  try: vals=[float(str(row[i]).strip().replace(',','')) for i in (3,4,5,6)]
  except (TypeError,ValueError) as exc:raise ValueError('NON_NUMERIC_OHLC') from exc
  op,hi,lo,cl=vals
  assert all(math.isfinite(x) and x>0 for x in vals),'BAD_NONPOSITIVE_OHLC'
  assert lo<=min(op,cl)<=max(op,cl)<=hi,'PRICE_INVARIANT'
  out.append({'day':day,'open':op,'high':hi,'low':lo,'close':cl})
 assert out==sorted(out,key=lambda x:x['day']),'DATE_ORDER_INVALID'
 return out
def selftest():
 dat={'stat':'OK','aaData':[['115/08/21','10','100','84.5','85','83.4','83.5','-0.8','7']]}
 assert len(parse(json.dumps(dat).encode(),2026,8))==1
 fails=0
 for idx,value in [(0,'115/07/21'),(4,'82.9'),(6,'0')]:
  q=json.loads(json.dumps(dat));q['aaData'][0][idx]=value
  try:parse(json.dumps(q).encode(),2026,8)
  except (AssertionError,ValueError):fails+=1
 assert fails==3
 return {'qa':'PASS_DATE_AND_PRICE_FAIL_CLOSED','tests':4,'passed':4}
def retrieve(out,year,month):
 roc=f'{year-1911}/{month:02d}'
 url=BASE+'?'+urllib.parse.urlencode({'l':'zh-tw','d':roc,'stkno':CODE})
 e={'month':f'{year}-{month:02d}','url':url,'status':'HOLD'}
 try:
  req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'Mozilla/5.0 historical-firstparty-research'})
  with urllib.request.urlopen(req,timeout=12) as resp:
   raw=resp.read(4000001);status=resp.status;final=resp.geturl()
  assert status==200 and 30<len(raw)<4000001,'UNTRUSTED_HTTP_OR_BYTES'
  assert urllib.parse.urlsplit(final).hostname=='www.tpex.org.tw','UNTRUSTED_REDIRECT'
  rows=parse(raw,year,month)
  fname=f'official_5371_{year}{month:02d}.json'
  (out/fname).write_bytes(raw)
  e.update(status='PASS_TPEX_PRIMARY_MONTH' if rows else 'HOLD_OFFICIAL_NO_TRADE_ROWS',original_file=fname,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),row_count=len(rows))
  return e,rows
 except Exception as exc:
  e.update(status='HOLD_OFFICIAL_RETRIEVAL',error_class=type(exc).__name__,error=str(exc)[:190])
  return e,[]
def main():
 p=argparse.ArgumentParser();p.add_argument('--out');p.add_argument('--self-test',action='store_true');args=p.parse_args()
 if args.self_test:print(json.dumps(selftest()));return
 if not args.out:p.error('--out required unless --self-test')
 out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=False)
 receipts=[];rows=[]
 for y,m in dates():
  e,r=retrieve(out,y,m);receipts.append(e);rows+=r
  print(json.dumps({'period':e['month'],'status':e['status'],'count':len(r)}),flush=True)
  time.sleep(.25)
 rows.sort(key=lambda x:x['day'])
 duplicate=len(rows)!=len(set(x['day'] for x in rows))
 extra=[x for x in rows if x['day']>LAST]
 last=rows[-1] if rows else None
 direct=not duplicate and not extra and bool(last) and last['day']==LAST and abs(last['close']-LAST_CLOSE)<.06
 ok=sum(e['status']=='PASS_TPEX_PRIMARY_MONTH' for e in receipts)
 result={'symbol':CODE,'successor':'3718','shareConversion1to1':True,'requested_months':len(receipts),'valid_months':ok,'missing_months':[e['month'] for e in receipts if e['status']!='PASS_TPEX_PRIMARY_MONTH'],'raw_dates_total':len(rows),'duplicate_date':duplicate,'post_last_trade_dates':len(extra),'last':last,'official_last_close_match':bool(direct),'status':'PASS_COMPLETE_5371_TPEX_OHLC_RESEARCH' if ok==len(receipts) and len(rows)>=350 and direct else 'HOLD_COMPLETE_ADJUSTED_LINEAGE','source_url_template':BASE,'scope':'RESEARCH_TPEX_RAW_OHLC_ONLY','formal_eligible':False,'issuer_exhaustive':False,'approved_adjusted_series':False,'natural_credit':0,'oos_credit':0,'qa':selftest(),'receipts':receipts}
 (out/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (out/'raw_5371_price_history_RESEARCH_ONLY.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='receipts'},ensure_ascii=False))
if __name__=='__main__':main()
