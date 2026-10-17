#!/usr/bin/env python3
"""Read-only original vendor history recovery for predecessor ticker 5371.TWO.
Never splice 5371 into 3718 as formal adjusted-close/PIT, seal predictions or modify legacy cash.
"""
import argparse,datetime as dt,hashlib,json,math,pathlib,urllib.parse,urllib.request
from zoneinfo import ZoneInfo
TZ=ZoneInfo("Asia/Taipei")
CODE="5371.TWO"
LAST="2026-08-21"
OFFICIAL_LAST=83.5
def verify(raw):
 o=json.loads(raw)
 assert not o.get("chart",{}).get("error"),"VENDOR_ERROR"
 arr=o.get("chart",{}).get("result")
 assert isinstance(arr,list) and len(arr)==1,"VENDOR_RESULT_COUNT"
 z=arr[0];meta=z.get("meta") or {}
 assert str(meta.get("symbol"))==CODE,"VENDOR_SYMBOL_MISMATCH"
 times=z.get("timestamp") or [];quote=((z.get("indicators") or {}).get("quote") or [{}])[0]
 close=quote.get("close") or []
 adj=(((z.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or []
 assert len(times)==len(close) and len(times)>=150 and len(adj)==len(close),"VENDOR_HISTORY_INCOMPLETE"
 dayrows=[]; seen=set()
 for t,c,a in zip(times,close,adj):
  if c is None or a is None:continue
  date=dt.datetime.fromtimestamp(t,TZ).date().isoformat()
  if date in seen:raise ValueError("DUPLICATE_TRADING_DATE")
  seen.add(date)
  if not all(isinstance(x,(float,int)) and math.isfinite(x) and x>0 for x in (c,a)):raise ValueError("BAD_VENDOR_PRICES")
  dayrows.append({"date":date,"close":c,"adjusted_close":a})
 assert len(dayrows)>=150 and dayrows==sorted(dayrows,key=lambda x:x["date"]),"EMPTY_OR_UNSORTED"
 assert all(x["date"]<=LAST for x in dayrows),"VENDOR_AFTER_DELISTING_FUTURE_LEAK"
 assert dayrows[-1]["date"]==LAST,"VENDOR_LAST_DAY_NOT_2026_08_21"
 assert abs(dayrows[-1]["close"]-OFFICIAL_LAST)<=.06,"OFFICIAL_LAST_CLOSE_CONFLICT"
 return {"rows":dayrows,"count":len(dayrows),"first":dayrows[0],"last":dayrows[-1],
         "source_vendor":meta.get("exchangeName"),"currency":meta.get("currency"),
         "last_official_proof":"TPEx 5371 2026-08-21 official 83.50, SHA bc52b4d651cf478f46f99103ef1a8e32b084d32d1f039ab36533a9b8bc6fa94b"}
def selftest():
 fixture={"chart":{"error":None,"result":[{"meta":{"symbol":CODE}, "timestamp":[], "indicators":{"quote":[{"close":[]}],"adjclose":[{"adjclose":[]}]}}]}}
 # The production parser must fail-closed for missing data, wrong identity or delisted-day mismatch
 errors=0
 for z in (fixture,{**fixture,"chart":{"error":None,"result":[{"meta":{"symbol":"5371.TW"},"timestamp":[],"indicators":fixture["chart"]["result"][0]["indicators"]}]}}):
  try:verify(json.dumps(z).encode())
  except (AssertionError,ValueError,KeyError,TypeError):errors+=1
 assert errors==2
 return {"qa":"PASS_FAIL_CLOSED","tests":2,"passed":2}
def main():
 pa=argparse.ArgumentParser();pa.add_argument("--out");pa.add_argument("--self-test",action="store_true");args=pa.parse_args()
 if args.self_test: print(json.dumps(selftest()));return
 if not args.out:pa.error("--out required unless --self-test")
 out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=False)
 start=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp())
 end=int(dt.datetime(2026,8,24,tzinfo=dt.timezone.utc).timestamp())
 attempts=[]
 result={"symbol":CODE,"scope":"RESEARCH_PREDECESSOR_VENDOR_ORIGINAL_ONLY","status":"HOLD","formalEligible":False,"naturalCredit":0,"oosCredit":0,
         "shareSwapRatio":1,"lastPredecessorTrade":LAST,"firstSuccessorTrade":"2026-09-03","officialPricesNotDirectlyBackAdjusted":True,"qa":selftest()}
 for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
  url=f"https://{host}/v8/finance/chart/{CODE}?"+urllib.parse.urlencode({"period1":start,"period2":end,"interval":"1d","events":"div,splits","includeAdjustedClose":"true"})
  info={"url":url,"status":"HOLD"}
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 stock-history-research","Accept":"application/json"})
   with urllib.request.urlopen(req,timeout=18) as response:
    body=response.read(3000001);status=response.status;final=response.geturl()
   assert status==200 and 0<len(body)<3000001 and urllib.parse.urlparse(final).hostname==host,"HTTP_HOST_SIZE_CONFLICT"
   info.update(rawSHA256=hashlib.sha256(body).hexdigest(),bytes=len(body))
   filename="5371_predecessor_vendor_raw.json";(out/filename).write_bytes(body)
   verified=verify(body)
   (out/"verified_rows.json").write_text(json.dumps(verified,ensure_ascii=False,indent=2)+"\n")
   info.update(status="PASS_VENDOR_ORIGINAL_HISTORY_AND_OFFICIAL_LASTCLOSE_RESEARCH",rows=verified["count"],first=verified["first"],last=verified["last"])
   result.update(status=info["status"],vendor=host,rawSHA256=info["rawSHA256"],rowCount=verified["count"],last=verified["last"])
   attempts.append(info);break
  except Exception as ex:info.update(status="HOLD_ORIGINAL_NOT_VALIDATED",error_type=type(ex).__name__,error=str(ex)[:260])
  attempts.append(info)
 result["attempts"]=attempts
 result["issuerFullHistoryAndPIT"]="HOLD_SOURCE_CHAIN_NOT_YET_RECONCILED"
 (out/"receipt.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":main()
