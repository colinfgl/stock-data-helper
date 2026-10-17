#!/usr/bin/env python3
"""Bounded official TPEx monthly endpoint discovery for delisted 5371; READ ONLY."""
import datetime as dt,hashlib,json,pathlib,re,urllib.parse,urllib.request
from html import unescape
import argparse
BASE="https://www.tpex.org.tw"
SITES=[
 "/zh-tw/mainboard/trading/info/stock-pricing.html?code=5371&date=115/08",
 "/www/zh-tw/mainboard/trading/info/stock-pricing?code=5371&date=115/08&response=json",
 "/www/zh-tw/afterTrading/st43?code=5371&date=115/08&response=json",
 "/www/zh-tw/afterTrading/st43?l=zh-tw&d=115/08&stkno=5371",
 "/www/zh-tw/afterTrading/stockPricing?date=115/08&code=5371&response=json",
 "/www/zh-tw/afterTrading/stockInfo?date=115/08&code=5371&response=json",
 "/www/zh-tw/afterTrading/dailyQuotes?response=json&date=115/08&code=5371",
 "/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d=115/08&stkno=5371",
 "/www/zh-tw/mainboard/trading/info/stock-pricing?date=115/08&code=5371",
 "/zh-tw/mainboard/trading/info/stock-pricing.html?code=5371&date=115/08&response=json",
]
def fetch(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 read-only-research-original","Accept":"application/json,text/html"})
 with urllib.request.urlopen(req,timeout=12) as r:
  raw=r.read(2500001);status=r.status;final=r.geturl();ctype=r.headers.get("Content-Type","")
 if len(raw)>=2500001 or status!=200 or urllib.parse.urlsplit(final).hostname not in ("www.tpex.org.tw","tpex.org.tw"): raise ValueError("NOT_OFFICIAL_HTTP")
 return raw,ctype,final
def main():
 pa=argparse.ArgumentParser();pa.add_argument("--out",required=True);a=pa.parse_args();out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 attempts=[]
 for i,rel in enumerate(SITES):
  url=BASE+rel;entry={"endpoint":rel,"status":"HOLD"}
  try:
   raw,ctype,final=fetch(url);content=raw.decode("utf-8-sig",errors="replace")
   entry.update(sha256=hashlib.sha256(raw).hexdigest(),size=len(raw),type=ctype,url=final,lead=content[:130])
   (out/f"probe_{i:02d}.bin").write_bytes(raw)
   try:
    obj=json.loads(content)
    keys=list(obj.keys()) if isinstance(obj,dict) else []
    entry["keys"]=keys[:12]
    encoded=json.dumps(obj,ensure_ascii=False)[:300000]
    # no PASS unless source-specific old ID and target month within data
    if "5371" in encoded and any(x in encoded for x in ("115/08/21","115/08/01","2026/08/21","2026-08-21")):
     entry["status"]="CANDIDATE_OFFICIAL_MONTHLY_JSON_VERIFY_SCHEMA"
    else:entry["status"]="HOLD_NO_5371_MONTHLY_ROW"
   except ValueError:
    entry["status"]="HOLD_HTML_NOT_JSON"
    if i==0:
     scripts=re.findall(r"<script[^>]+src=['\"]([^'\"]+)",content,re.I)
     entry["scripts"]=scripts[-20:]
     for kw in ("stock-pricing","afterTrading","api","query","stkno","ajax","download"):
      inds=[m.start() for m in re.finditer(re.escape(kw),content,re.I)]
      entry[f"around_{kw}"]=[content[max(0,ind-120):min(len(content),ind+200)] for ind in inds[:3]]
  except Exception as e:entry.update(status="HOLD_HTTP",error_type=type(e).__name__,error=str(e)[:160])
  attempts.append(entry)
  print(json.dumps({k:v for k,v in entry.items() if k not in ("around_stock-pricing","around_afterTrading","around_api","around_query","around_stkno","around_ajax","around_download","scripts")},ensure_ascii=False),flush=True)
 report={"symbol":"5371","month":"115/08","attempts":attempts,"nonpromotion":True,"format_tests_not_execution_proof":True}
 (out/"receipt.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print("SCRIPTS",json.dumps(attempts[0].get("scripts"),ensure_ascii=False))
 for k,v in attempts[0].items():
  if k.startswith("around_"):print(k,json.dumps(v,ensure_ascii=False)[:500])
if __name__=="__main__":main()
