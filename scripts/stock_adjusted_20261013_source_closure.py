#!/usr/bin/env python3
"""2026-10-13 prospective stock-source acquisition, PUBLIC-ONLY, research evidence only.

The prior-session official daily raw bytes are loaded from GitHub Actions run
38263174970 (date 2026-10-12). Yahoo chart response must contain the same
symbol and exact raw close. Raw Yahoo JSON is independently SHA256 preserved.
No predictions, model, portfolio, cash, Formal, Natural, or OOS are modified.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib, re, time
import urllib.request, urllib.parse, urllib.error, socket, ssl, http.client
from zoneinfo import ZoneInfo

TARGET="2026-10-13"
CUTOFF="2026-10-12"
EXCHANGE_SHA={
 "TWSE":"a2b4f3f37d3f7c6e2ffdeadb918b796e167a92b622e4f6f698f61f2c0f7f6b70",
 "TPEx":"01793f9687c6ee39a61007bcf339b8b369c04dfd2d2c0784e5f6f9b4f398be45"
}
CODES=["00400A.TW","0050.TW","009820.TW","1503.TW","1513.TW","1519.TW","2049.TW","2059.TW","2207.TW","2301.TW","2303.TW","2308.TW","2313.TW","2317.TW","2330.TW","2345.TW","2359.TW","2368.TW","2376.TW","2382.TW","2383.TW","2395.TW","2454.TW","2466.TW","2634.TW","2645.TW","2834.TW","2885.TW","3017.TW","3037.TW","3105.TWO","3138.TW","3163.TWO","3189.TW","3293.TWO","3324.TWO","3363.TWO","3443.TW","3450.TW","3481.TW","3491.TWO","3529.TWO","3653.TW","3661.TW","3665.TW","3711.TW","3718.TWO","4585.TW","4916.TW","4979.TWO","5222.TW","5274.TWO","5351.TWO","6223.TWO","6285.TW","6442.TW","6451.TW","6510.TWO","6515.TW","6526.TW","6669.TW","6753.TW","6770.TW","6781.TW","6831.TW","8033.TW","8046.TW","8147.TWO"]
TZ=ZoneInfo("Asia/Taipei")

def digest(x):return hashlib.sha256(x).hexdigest()
def strict(raw):
 def hook(pairs):
  out={}
  for k,v in pairs:
   if k in out:raise ValueError("DUPLICATE_KEY:"+k)
   out[k]=v
  return out
 return json.loads(raw.decode("utf-8-sig"),object_pairs_hook=hook,
   parse_constant=lambda v:(_ for _ in ()).throw(ValueError("NONFINITE_JSON:"+v)))

def official_map(raw,venue):
 doc=strict(raw)
 if doc.get("date")!="20261012" or doc.get("stat") not in ("OK","ok"):
  raise ValueError("OFFICIAL_WRONG_DATE_OR_STATUS")
 tables=doc.get("tables") or []
 if "fields" in doc:tables=[doc]+tables
 ans={}
 for t in tables:
  f=t.get("fields") or []
  ci="證券代號" if venue=="TWSE" else "代號"
  pi="收盤價" if venue=="TWSE" else "收盤"
  if ci not in f or pi not in f:continue
  if f.count(ci)!=1 or f.count(pi)!=1:raise ValueError("DUPLICATE_OFFICIAL_FIELD")
  for row in t.get("data",[]):
   if len(row)!=len(f):raise ValueError("OFFICIAL_BAD_ROW")
   code=str(row[f.index(ci)])
   if code in ans:raise ValueError("DUPLICATE_OFFICIAL_CODE:"+code)
   try: ans[code]=float(str(row[f.index(pi)]).replace(",",""))
   except (ValueError,TypeError):ans[code]=None
 return ans

def retrieve(url,path):
 errors=[]
 for attempt in (1,2):
  meta={"attempt":attempt,"url":url,"retrieved_at":dt.datetime.now(dt.timezone.utc).isoformat()}
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 stock-source-evidence/1.0","Accept":"application/json"})
   with urllib.request.urlopen(req,timeout=16) as h:
    body=h.read(5000001)
    meta.update(http_status=h.status,final_url=h.geturl(),content_type=h.headers.get("Content-Type",""))
   if len(body)>5000000:raise ValueError("SOURCE_TOO_LARGE")
   if urllib.parse.urlsplit(meta["final_url"]).hostname!=urllib.parse.urlsplit(url).hostname:
    raise ValueError("REDIRECT_HOST_DRIFT")
   if meta["http_status"]!=200:raise ValueError("HTTP_NOT_200")
   path.write_bytes(body)
   meta.update(bytes=len(body),sha256=digest(body),status="RAW_SAVED")
   return body,meta
  except Exception as e:
   meta.update(status="FAILED",error_type=type(e).__name__,error=str(e)[:180])
   errors.append(meta)
   if isinstance(e,urllib.error.HTTPError) and e.code in (401,403,429):break
   if attempt==1:time.sleep(1)
 return None,{"status":"FAILED","attempts":errors}

def validate_chart(body,ticker,ref):
 obj=strict(body)
 if obj.get("chart",{}).get("error"):raise ValueError("YAHOO_PROVIDER_ERROR")
 res=obj.get("chart",{}).get("result") or []
 if len(res)!=1:raise ValueError("YAHOO_RESULT_NOT_UNIQUE")
 d=res[0]
 meta=d.get("meta") or {}
 if meta.get("symbol")!=ticker:raise ValueError("YAHOO_SYMBOL_MISMATCH:"+str(meta.get("symbol")))
 ts=d.get("timestamp") or []
 ind=d.get("indicators") or {}
 q=(ind.get("quote") or [{}])[0]
 aq=(ind.get("adjclose") or [{}])[0]
 raw=q.get("close") or []
 adj=aq.get("adjclose") or []
 if not(ts and len(ts)==len(raw)==len(adj)):raise ValueError("CHART_ADJUSTED_AXIS_REQUIRED")
 pairs={}
 for t,c,a in zip(ts,raw,adj):
  date=dt.datetime.fromtimestamp(t,TZ).date().isoformat()
  if date in pairs:raise ValueError("DUPLICATE_SESSION")
  if date>TARGET:raise ValueError("POST_TARGET_LEAKAGE")
  if date>=TARGET:raise ValueError("TARGET_SESSION_MUST_NOT_APPEAR")
  if c is None or a is None:continue
  try:
   c=float(c);a=float(a)
   if not(0<c<2000000 and 0<a<2000000):continue
  except (ValueError,TypeError):continue
  pairs[date]=(c,a)
 if CUTOFF not in pairs:raise ValueError("CUTOFF_SESSION_MISSING")
 c,a=pairs[CUTOFF]
 if abs(c-ref)>max(.03,ref*.00025):raise ValueError("OFFICIAL_YAHOO_CLOSE_CONFLICT:"+str(c)+"/"+str(ref))
 if len(pairs)<60:raise ValueError("HISTORY_LT60")
 if any(x>CUTOFF for x in pairs):raise ValueError("AFTER_CUTOFF_ROWS")
 return {"observations":len(pairs),"min_date":min(pairs),"max_date":max(pairs),"close_at_cutoff":c,
         "adjusted_at_cutoff":a,"official_close_at_cutoff":ref,"can_fit_H9_train400":len(pairs)>=401,
         "input_series":"adjusted_close","data_as_of":CUTOFF,
         "corporate_action_exhaustiveness":"UNVERIFIED_NOT_FORMAL"}

def main():
 p=argparse.ArgumentParser()
 p.add_argument("--official-dir",required=True)
 p.add_argument("--out",required=True)
 p.add_argument("--batch",type=int,required=True,choices=range(4))
 args=p.parse_args()
 out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=False)
 base=pathlib.Path(args.official_dir)/"2026-10-12"
 maps={}
 for venue,base_name in (("TWSE","twse.attempt1.json"),("TPEx","tpex.attempt1.json")):
  path=base/base_name;data=path.read_bytes()
  if digest(data)!=EXCHANGE_SHA[venue]:raise ValueError("OFFICIAL_SHA_MISMATCH:"+venue)
  maps[venue]=official_map(data,venue)
 codes=[c for i,c in enumerate(CODES) if i%4==args.batch]
 rows=[]
 period1=int(dt.datetime(2024,1,1,tzinfo=TZ).timestamp())
 period2=int(dt.datetime(2026,10,13,tzinfo=TZ).timestamp())
 for ticker in codes:
  code,venue=ticker.split(".")
  venue="TWSE" if venue=="TW" else "TPEx"
  rec={"ticker":ticker,"symbol":code,"venue":venue,"target_date":TARGET,"cutoff_date":CUTOFF,
       "official_payload_sha256":EXCHANGE_SHA[venue],
       "formal_input_qualified":False,"prediction_generated":False,"natural_credit":0}
  ref=maps[venue].get(code)
  if ref is None:
   rec.update(status="MISSING_OFFICIAL_CLOSE")
   rows.append(rec);continue
  rec["official_close"]=ref
  for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
   params=urllib.parse.urlencode({"period1":period1,"period2":period2,
      "interval":"1d","events":"div,splits","includeAdjustedClose":"true"})
   url=f"https://{host}/v8/finance/chart/{ticker}?{params}"
   path=out/f"raw_{ticker}_{host.split('.')[0]}.json"
   body,meta=retrieve(url,path)
   rec.setdefault("attempts",[]).append(meta)
   if body is None:continue
   try:
    chk=validate_chart(body,ticker,ref)
    rec.update(chk,status="RESEARCH_ADJUSTED_CUTOFF_CROSSCHECK_PASS",
       provider="Yahoo chart",raw_sha=meta["sha256"],raw_path=path.name,source_url=url)
    break
   except Exception as e:
    rec.setdefault("validation_errors",[]).append(type(e).__name__+":"+str(e))
  rec.setdefault("status","ADJUSTED_SOURCE_HOLD")
  rows.append(rec)
  (out/"manifest_partial.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
 results={"target_date":TARGET,"cutoff_date":CUTOFF,"batch":args.batch,"run_id":"GH_ACTIONS_ENV:"+str(__import__("os").environ.get("GITHUB_RUN_ID")),
  "generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"scope":"PUBLIC_RESEARCH_SOURCE_ONLY",
  "official_sha":EXCHANGE_SHA,"codes":codes,
  "research_adjusted_ready":sum(x["status"]=="RESEARCH_ADJUSTED_CUTOFF_CROSSCHECK_PASS" for x in rows),
  "source_qualified_formal_count":0,"formal_prediction_count":0,"rows":rows}
 (out/"manifest.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf8")
 print(json.dumps({k:v for k,v in results.items()if k!="rows"},ensure_ascii=False))
 return 0 if results["research_adjusted_ready"] else 2

if __name__=="__main__":raise SystemExit(main())
