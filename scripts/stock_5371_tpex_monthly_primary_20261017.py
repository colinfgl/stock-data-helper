#!/usr/bin/env python3
"""Recover 25 historic months of actual TPEx tradingStock data for delisted 5371.

Replays exactly the officially published web frontend's POST API, with date as
YYYY/MM/01; preserves original response per month and SHA256, fail-closed.
DOES NOT create approved adjusted-close nor replace 3718 prediction.
"""
import argparse,datetime as dt,hashlib,json,math,pathlib,time,urllib.parse,urllib.request
CODE="5371";FINAL_DATE="2026-08-21";FINAL_CLOSE=83.50
URL="https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
KEYS=["日 期","成交張數","成交仟元","開盤","最高","最低","收盤","漲跌","筆數"]
def periods():
 y,m=2024,8
 while (y,m)<=(2026,8):
  yield y,m
  m+=1
  if m>12:y,m=y+1,1
def parse(raw,year,month):
 obj=json.loads(raw.decode("utf-8-sig"))
 assert obj.get("stat")=="ok","OFFICIAL_STAT_NOT_OK"
 assert str(obj.get("code"))==CODE,"OFFICIAL_SYMBOL_MISMATCH"
 assert str(obj.get("date"))==f"{year:04d}{month:02d}01","OFFICIAL_MONTH_MISMATCH"
 tables=obj.get("tables")
 assert isinstance(tables,list) and len(tables)==1,"OFFICIAL_TABLE_NOT_UNIQUE"
 t=tables[0]; fields=[str(f).strip() for f in t.get("fields",[])]
 assert fields==KEYS or fields==[("成交仟股" if x=="成交張數" else x) for x in KEYS],"OFFICIAL_SCHEMA_DRIFT:"+repr(fields)
 dat=t.get("data")
 assert isinstance(dat,list) and len(dat)>0,"OFFICIAL_EMPTY_MONTH"
 all=[];seen=set()
 for r in dat:
  assert isinstance(r,list) and len(r)==len(KEYS),"SOURCE_ROW_WIDTH_DRIFT"
  yy,mm,dd=map(int,str(r[0]).replace("-","/").split("/"))
  day=dt.date(yy+1911 if yy<1911 else yy,mm,dd)
  assert (day.year,day.month)==(year,month),"TRADING_DATE_NOT_TARGET_MONTH"
  day=str(day);assert day not in seen,"DUPLICATE_SOURCE_DATE";seen.add(day)
  def n(idx):
   v=float(str(r[idx]).strip().replace(",",""))
   if not math.isfinite(v) or v<=0:raise ValueError("ZERO_OR_NONFINITE_PRICE")
   return v
  o,hi,lo,c=[n(i) for i in (3,4,5,6)]
  assert lo<=min(o,c)<=max(o,c)<=hi,"OHLC_INVARIANT"
  all.append({"date":day,"symbol":CODE,"open":o,"high":hi,"low":lo,"close":c})
 assert all==sorted(all,key=lambda x:x["date"]),"SOURCE_DATE_ORDER"
 return all
def selftest():
 obj={"stat":"ok","code":"5371","date":"20260801","tables":[{"fields":KEYS,"data":[["115/08/21","2,135","179,293","84.50","85.00","83.40","83.50","-0.80","3,726"]]}]}
 b=json.dumps(obj).encode()
 a=parse(b,2026,8);assert len(a)==1 and a[0]["close"]==83.50
 q=json.loads(json.dumps(obj));q["tables"][0]["fields"][1]="成交仟股"
 assert parse(json.dumps(q).encode(),2026,8)[0]["close"]==83.50
 n=0
 for k,v in [("code","3718"),("date","20260901")]:
  p=json.loads(json.dumps(obj));p[k]=v
  try:parse(json.dumps(p).encode(),2026,8)
  except (AssertionError,ValueError):n+=1
 p=json.loads(json.dumps(obj));p["tables"][0]["data"][0][5]="85.50"
 try:parse(json.dumps(p).encode(),2026,8)
 except (AssertionError,ValueError):n+=1
 assert n==3
 return {"tests":5,"passed":5,"status":"PASS_REPLAY_GUARDS_2_OFFICIAL_VOLUME_FIELD_VARIANTS"}
def fetch_one(year,month,folder):
 date=f"{year:04d}/{month:02d}/01"
 query=urllib.parse.urlencode({"code":CODE,"date":date,"response":"json"}).encode()
 req=urllib.request.Request(URL,data=query,method="POST",headers={
  "Content-Type":"application/x-www-form-urlencoded","Accept":"application/json",
  "User-Agent":"Mozilla/5.0","Origin":"https://www.tpex.org.tw",
  "Referer":"https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html"})
 receipt={"month":f"{year:04d}-{month:02d}","status":"HOLD","requested":date}
 try:
  with urllib.request.urlopen(req,timeout=15) as r:
   blob=r.read(3000001);status=r.status;url=r.geturl()
  assert status==200 and 20<len(blob)<3000001 and urllib.parse.urlsplit(url).hostname=="www.tpex.org.tw","OFFICIAL_HTTP_SOURCE_HOLD"
  data=parse(blob,year,month)
  filename=f"tpex_original_5371_{year:04d}{month:02d}.json"
  (folder/filename).write_bytes(blob)
  receipt.update(status="PASS_PRIMARY_EXACT_MONTH",raw_sha256=hashlib.sha256(blob).hexdigest(),bytes=len(blob),file=filename,original_url=URL,row_count=len(data),first=data[0]["date"],last=data[-1]["date"])
  return receipt,data
 except Exception as exc:
  receipt.update(status="HOLD_PRIMARY_OR_SCHEMA_ERROR",error_type=type(exc).__name__,error=str(exc)[:220])
  return receipt,[]
def main():
 a=argparse.ArgumentParser();a.add_argument("--out");a.add_argument("--self-test",action="store_true");a=a.parse_args()
 if a.self_test:print(json.dumps(selftest()));return
 if not a.out:raise SystemExit("--out required unless --self-test")
 out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 entries=[];all=[]
 for y,m in periods():
  receipt,rows=fetch_one(y,m,out);entries.append(receipt);all+=rows
  print("MONTH",json.dumps({"month":receipt["month"],"status":receipt["status"],"count":len(rows),"reason":receipt.get("error")},ensure_ascii=False),flush=True)
  time.sleep(.16)
 all.sort(key=lambda r:r["date"]);unique=len({z["date"] for z in all})==len(all)
 last=all[-1] if all else None
 lastpass=bool(last) and last["date"]==FINAL_DATE and abs(last["close"]-FINAL_CLOSE)<0.06
 missing=[z["month"] for z in entries if z["status"]!="PASS_PRIMARY_EXACT_MONTH"]
 status="PASS_COMPLETE_5371_TPEX_RAW_HISTORY_RESEARCH_ONLY" if len(entries)==25 and not missing and len(all)>=350 and unique and lastpass else "HOLD_COMPLETENESS_OR_RAW_HISTORY"
 report={"status":status,"symbol":CODE,"successor":"3718","source_method":"NATIVE_POST_www_zh-tw_afterTrading_tradingStock_Gregorian_YYYYMM01",
  "source_form":"https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html","num_months":len(entries),
  "verified_months":len(entries)-len(missing),"missing_months":missing,
  "raw_ohlc_rows":len(all),"unique_dates":unique,"final_date_close_matches_tpex_daily_official":bool(lastpass),"first":all[0] if all else None,"last":last,
  "original_issued_share_ratio":1.0,"price_overnight_jump_is_NOT_company_action_adjustment_factor":True,
  "research_only":True,"formal_eligible":False,"adjusted_close_NOT_approved":True,"natural_OOS_credit":0,
  "qa":selftest(),"period_receipts":entries}
 (out/"official_5371_daily_ohlc_RESEARCH_ONLY.json").write_text(json.dumps(all,ensure_ascii=False,indent=2)+"\n")
 (out/"receipt.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
 print("FINAL",json.dumps({k:v for k,v in report.items() if k!="period_receipts"},ensure_ascii=False))
if __name__=="__main__":main()
