#!/usr/bin/env python3
"""Exact TPEx native POST/JSON schema probe, historic 5371 monthly original, no formal mutation."""
import argparse,hashlib,json,pathlib,urllib.parse,urllib.request
BASE="https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
def main():
 p=argparse.ArgumentParser();p.add_argument("--out",required=True);a=p.parse_args()
 out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 cases=[("greg_full_YYYYMMDD","20260801"),("greg_slash","2026/08/01"),
        ("roc_full_YYMMDD","1150801"),("roc_slash","115/08/01")]
 all=[]
 for tag,date in cases:
  q={"code":"5371","date":date,"response":"json"}
  req=urllib.request.Request(BASE,data=urllib.parse.urlencode(q).encode(),headers={
   "User-Agent":"Mozilla/5.0","Accept":"application/json","Content-Type":"application/x-www-form-urlencoded",
   "Origin":"https://www.tpex.org.tw","Referer":"https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html"},method="POST")
  d={"tag":tag,"date":date,"status":"HOLD"}
  try:
   with urllib.request.urlopen(req,timeout=15) as r:
    raw=r.read(2500001);ctype=r.headers.get("Content-Type","");stat=r.status;url=r.geturl()
   if stat!=200 or not raw or len(raw)>2500000 or urllib.parse.urlsplit(url).hostname!="www.tpex.org.tw":raise ValueError("BAD_ORIGINAL_SOURCE")
   sha=hashlib.sha256(raw).hexdigest();(out/(tag+".bin")).write_bytes(raw)
   obj=json.loads(raw.decode("utf-8-sig"))
   d.update(sha256=sha,bytes=len(raw),stat=obj.get("stat"),resultDate=obj.get("date"),type=ctype,keys=list(obj.keys())[:12])
   tables=obj.get("tables",[]);items=[]
   if isinstance(tables,list):
    for t in tables:
     fields=t.get("fields",[]);rows=t.get("data",[]) or []
     items.append({"fields":fields,"row_count":len(rows),"first":rows[:2],"last":rows[-2:]})
   d["tables"]=items[:3]
   if isinstance(tables,list) and any(t.get("data") for t in tables):
    d["status"]="CANDIDATE_PRIMARY_TRADINGSTOCK_JSON_NEEDS_EXACT_5371_AND_DATE_QA"
   else:d["status"]="HOLD_OFFICIAL_NO_MONTH_ROWS"
  except Exception as e:d.update(status="HOLD_REQUEST_OR_PARSE",type=type(e).__name__,error=str(e)[:200])
  all.append(d);print(json.dumps(d,ensure_ascii=False)[:8500],flush=True)
 (out/"receipt.json").write_text(json.dumps(all,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__":main()
