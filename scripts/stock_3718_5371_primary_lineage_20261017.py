#!/usr/bin/env python3
"""Research-only evidence recovery for 5371->3718 1:1 exchange on 2026-09-03.

Never splice predecessor and successor prices into formal model or write to
Prediction, Outcome, Cash, Config, Natural, OOS or immutable research history.
"""
import argparse, datetime as dt, hashlib, json, pathlib, re, urllib.parse, urllib.request, time

EVENT={"predecessor":"5371","successor":"3718","exchange_ratio":1.0,
       "last_predecessor_trade":"2026-08-21","trade_suspension":"2026-08-24",
       "conversion_date":"2026-09-03",
       "tpex_stop_url":"https://www.tpex.org.tw/storage/eb_data/11508/11500050581.html",
       "tpex_index_url":"https://www.tpex.org.tw/storage/eb_data/11508/11503025121.html",
       "issuer_mops_reprint_url":"https://news.cnyes.com/news/id/6550447"}
CASES=[("5371","2026-08-21"),("3718","2026-09-03"),("3718","2026-10-16")]
BASE="https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
def iso(d):
 y,m,n=map(int,d.split("-"));return f"{y-1911:03d}/{m:02d}/{n:02d}"
def validate_date(text,day):
 roc=iso(day)
 return day.replace("-","") in text or roc in text or day.replace("-","/") in text or f"{int(roc[:3])}年{int(roc[4:6])}月{int(roc[7:9])}日" in text
def parse_json(raw,symbol,day):
 o=json.loads(raw.decode("utf-8-sig"));assert isinstance(o,dict),"NOT_JSON_OBJECT"
 status=str(o.get("stat","")).upper()
 assert status in ("OK",""),"SOURCE_STAT_NOT_OK"
 fmt=json.dumps({k:v for k,v in o.items() if k!="data"},ensure_ascii=False)[:24000]
 assert validate_date(fmt,day),"PARENT_RESPONSE_DATE_UNVERIFIED"
 found=[]
 blocks=o.get("tables") if isinstance(o.get("tables"),list) else [o]
 for block in blocks:
  fields=block.get("fields") if isinstance(block,dict) else None
  rows=block.get("data") if isinstance(block,dict) else None
  if not isinstance(fields,list) or not isinstance(rows,list):continue
  names=[str(x).strip() for x in fields]
  co=next((names.index(x) for x in ("代號","股票代號","證券代號") if x in names),None)
  if co is None:continue
  price=next((names.index(x) for x in ("收盤","收盤價") if x in names),None)
  hi=next((names.index(x) for x in ("最高","最高價") if x in names),None)
  lo=next((names.index(x) for x in ("最低","最低價") if x in names),None)
  if price is None:continue
  for r in rows:
   if not isinstance(r,list) or len(r)!=len(names) or str(r[co]).strip()!=symbol:continue
   def get(i):
    if i is None:return None
    try:return float(str(r[i]).replace(",",""))
    except (ValueError,TypeError):return None
   c=get(price);h=get(hi);l=get(lo)
   assert c is not None and c>0 and (h is None or h>=c) and (l is None or l<=c),"BAD_CLOSE_OR_HILO"
   found.append({"symbol":symbol,"day":day,"close":c,"high":h,"low":l,"fields":names,"raw_row":r})
 assert len(found)==1,("NO_EXACT_SYMBOL_OHLC",len(found))
 return found[0]
def qa():
 fields=["代號","名稱","收盤","最高","最低"]
 blob=json.dumps({"stat":"OK","date":"115/08/21","tables":[{"fields":fields,"data":[["5371","中光電","63","64","62"]]}]},ensure_ascii=False).encode()
 x=parse_json(blob,"5371","2026-08-21")
 assert x["close"]==63.0
 failed=0
 for symbol,day in [("3718","2026-08-21"),("5371","2026-08-22"),("5371","2026-09-03")]:
  try:parse_json(blob,symbol,day)
  except AssertionError:failed+=1
 assert failed==3 and EVENT["exchange_ratio"]==1.0
 return {"tests":4,"passed":4,"result":"PASS_FAIL_CLOSED"}
def retrieve(url,outdir,name):
 req=urllib.request.Request(url,headers={"Accept":"application/json,text/html","User-Agent":"Mozilla/5.0 academic-readonly-stock-event-qa"})
 with urllib.request.urlopen(req,timeout=18) as response:
  raw=response.read(3000001);status=response.status;final=response.geturl();ctype=response.headers.get("Content-Type","")
 if status!=200 or not raw or len(raw)>=3000001 or urllib.parse.urlparse(final).hostname not in ("www.tpex.org.tw","tpex.org.tw"):raise ValueError("SOURCE_HTTP_SIZE_OR_HOST_INVALID")
 (outdir/name).write_bytes(raw)
 return {"url":url,"final_url":final,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"content_type":ctype},raw
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--out",required=True);parser.add_argument("--self-test",action="store_true");a=parser.parse_args()
 if a.self_test:print(json.dumps(qa()));return
 outdir=pathlib.Path(a.out);outdir.mkdir(parents=True,exist_ok=False)
 result={"research_only":True,"official_price_basis_formal_approved":False,
    "original_prediction_point_modified":False,"event":EVENT,"qa":qa(),"daily":[],"announcements":[]}
 for symbol,day in CASES:
  row={"symbol":symbol,"date":day,"status":"HOLD","approvable":"EXCHANGE_OHLC_RESEARCH_ONLY"}
  for fmt in ("ROC","GREGORIAN"):
   q=iso(day) if fmt=="ROC" else day.replace("-","/")
   url=BASE+"?"+urllib.parse.urlencode({"response":"json","date":q})
   try:
    meta,raw=retrieve(url,outdir,f"{symbol}_{day}_{fmt}.json")
    record=parse_json(raw,symbol,day)
    row.update(status="PASS_FIRSTPARTY_DATE_SYMBOL_OHLC",receipt=meta,record=record,query_format=fmt)
    break
   except Exception as exc:
    row.setdefault("failure_attempts",[]).append({"format":fmt,"reason":type(exc).__name__,"details":str(exc)[:180]})
  result["daily"].append(row);time.sleep(.25)
 for kind,url,needle in [("stop",EVENT["tpex_stop_url"],"5371"),("index",EVENT["tpex_index_url"],"3718")]:
  x={"type":kind,"url":url,"status":"HOLD"}
  try:
   meta,raw=retrieve(url,outdir,f"tpex_{kind}_2026.html");txt=raw.decode("utf-8",errors="replace")
   if needle in txt and ("115年9月3日" in txt or "115/09/03" in txt or "9月3日" in txt):
    x.update(status="PASS_TPEX_PRIMARY_EVENT_SCHEDULE",receipt=meta)
   else:x.update(status="HOLD_PRIMARY_EVENT_TEXT_MISMATCH",receipt=meta)
  except Exception as ex:x.update(status="HOLD_PRIMARY_UNAVAILABLE",error=str(ex)[:180])
  result["announcements"].append(x)
 result["predecessor_2026_08_22_to_09_02"]="NO_TRADING_QUOTE_EXPECTED"
 result["share_conversion_1_TO_1"]="ISSUER_MOPS_REPRINT_CONFIRMED__EXCHANGE_PRIMARY_SCHEDULE_SEPARATE"
 result["historical_adjusted_close_lineage"]="HOLD_PRE_POST_ISSUER_FULL_HISTORY_AND_PRICE_BASIS"
 result["formal_natural_oos_credit"]=0
 (outdir/"receipts.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"qa":result["qa"],"prices":[{k:v for k,v in z.items() if k in ("symbol","date","status","receipt","record")} for z in result["daily"]],
       "announcements":[{k:v for k,v in z.items() if k in ("type","status","receipt")} for z in result["announcements"]],
       "still_hold":"HOLD_FULL_HISTORY_ISSUER_ADJUSTED_PIT_NOT_FORMAL"},ensure_ascii=False))
if __name__=="__main__":main()
