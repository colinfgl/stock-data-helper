#!/usr/bin/env python3
"""Single-session TPEx 14-symbol strict official ORIGINAL recovery.

Never use Yahoo/secondary and never infer missing prices. Each official
HTTP raw file has its own SHA and time+endpoint receipt. Do not merge files
to pretend one original, and do not count Formal/Natural/OOS.
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import time
import urllib.request
from stock_official_actual_afterclose_v1_20261014 import dayparse,positive,strict,blocks

DAY=dt.date(2026,10,12)
CODES=("3105","3163","3293","3324","3363","3491","3529","3718",
       "4979","5274","5351","6223","6510","8147")
def verify_original(data,symbol):
    if not isinstance(data,dict) or str(data.get("stat","")).lower()!="ok":
        raise ValueError("TPEX_OFFICIAL_STATUS_NOT_OK")
    if dayparse(data.get("date"))!=DAY:
        raise ValueError("TPEX_EXACT_DATE_NOT_EQUAL_20261012")
    matches=[]
    for tb in blocks(data):
        head=tb.get("fields") or []
        needed=["代號","名稱","開盤","最高","最低","收盤"]
        if not all(head.count(f)==1 for f in needed):continue
        cols=[head.index(f) for f in needed]
        for vals in tb.get("data") or []:
            if not isinstance(vals,list) or len(vals)!=len(head):
                raise ValueError("TPEX_PHYSICAL_FIELD_OR_ROW_WIDTH")
            if str(vals[cols[0]]).strip()!=symbol:continue
            name=str(vals[cols[1]]).strip()
            op,hi,lo,cl=[positive(vals[k]) for k in cols[2:]]
            if not name or not all(v is not None for v in (op,hi,lo,cl)) or not lo<=min(op,cl)<=max(op,cl)<=hi:
                raise ValueError("TPEX_BAD_NAME_OHLC_"+symbol)
            matches.append({"symbol":symbol,"name":name,"open":op,"high":hi,"low":lo,"close":cl})
    if len(matches)!=1:raise ValueError("TPEX_TARGET_OR_DUPLICATE_ROWS_"+symbol+":"+str(len(matches)))
    return matches[0]

def once(symbol,root):
    # The 'id=' parameter is a source-provided filter; if API does not honor
    # it, the full original still must download and SHA/readback correctly.
    base=f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=2026/10/12&id={symbol}&response=json"
    outcomes=[]
    for attempt in range(1,3):
        rec={"symbol":symbol,"attempt":attempt,"url":base,
             "captured_at":dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            rq=urllib.request.Request(base,headers={"Accept":"application/json",
               "Accept-Encoding":"identity","User-Agent":"Mozilla/5.0 stock-official-research"})
            with urllib.request.urlopen(rq,timeout=18) as res:
                raw=res.read(24_000_001)
                if res.status!=200 or len(raw)>24_000_000:
                    raise ValueError("HTTP_NOT_OK_OR_OVERSIZE")
                if res.geturl().split("/")[2]!="www.tpex.org.tw":
                    raise ValueError("REDIRECTED_EXTERNAL_ORIGIN")
            obj=strict(raw)
            result=verify_original(obj,symbol)
            p=root/f"tpex_{symbol}_original.json";p.write_bytes(raw)
            h=hashlib.sha256(raw).hexdigest()
            if p.read_bytes()!=raw or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
                raise ValueError("RAW_BYTES_SHA_READBACK_FAILED")
            rec.update(status="FIRSTPARTY_EXACT_DATE_OHLC_SHA_PASS",bytes=len(raw),sha256=h)
            outcomes.append(rec)
            return {"symbol":symbol,"result":result,"receipts":outcomes,
                "qualified":True,"sourceSHA":h}
        except Exception as exc:
            rec.update(status="HOLD",error=type(exc).__name__+":"+str(exc)[:300])
            outcomes.append(rec)
            if attempt==1:time.sleep(1)
    return {"symbol":symbol,"result":None,"receipts":outcomes,"qualified":False,
            "sourceSHA":None}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="tpex_1012_14_recovery")
    a=p.parse_args()
    root=pathlib.Path(a.out);root.mkdir(parents=True,exist_ok=True)
    rows=[]
    for i,code in enumerate(CODES):
        z=once(code,root)
        rows.append(z)
        print("ORIGINAL_SYMBOL",i+1,"of14",code,"OK" if z["qualified"] else "HOLD",
              z["result"]["close"] if z["result"] else z["receipts"][-1]["error"],flush=True)
    out={"session":DAY.isoformat(),"strict_firstparty":True,
         "expected_symbols":list(CODES),"pass":sum(x["qualified"] for x in rows),
         "hold":sum(not x["qualified"] for x in rows),
         "rows":rows,"formal_prediction_written":False,
         "canonical_outcome_written":False,"natural_credit":0,"oos_credit":0}
    text=json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    fp=root/"tpex_original_14_recovery.json";fp.write_text(text,encoding="utf8")
    assert fp.read_bytes()==text.encode()
    print("RESULT",json.dumps({"pass":out["pass"],"hold":out["hold"],
           "date":out["session"],"rows":[z["result"] for z in rows if z["qualified"]]},
           ensure_ascii=False),flush=True)
    return 0 if out["hold"]==0 else 2
if __name__=="__main__":
    raise SystemExit(main())
