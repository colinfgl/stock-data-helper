#!/usr/bin/env python3
"""Source-first dividend factor-count research. Never promotes issuer/Formal/OOS."""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,math,pathlib
from zoneinfo import ZoneInfo
TZ=ZoneInfo("Asia/Taipei")
def check(ok,msg):
    if not ok:raise ValueError(msg)
def pos(x):return type(x) in (int,float) and math.isfinite(x) and x>0
def day(t):
    check(type(t) in (int,float) and math.isfinite(t),"INVALID_TIME")
    return dt.datetime.fromtimestamp(t,TZ).strftime("%Y-%m-%d")
def reconcile(raw,symbol,threshold=0.05):
    check(pos(threshold) and threshold<100,"INVALID_THRESHOLD")
    x=json.loads(raw)
    check(isinstance(x,dict) and isinstance(x.get("chart"),dict),"BAD_CHART_SCHEMA")
    check(x["chart"].get("error") is None,"YAHOO_ERROR")
    results=x["chart"].get("result")
    check(isinstance(results,list) and len(results)==1,"MULTI_OR_EMPTY_CHART")
    r=results[0]
    check(r.get("meta",{}).get("symbol")==symbol,"SYMBOL_CONFLICT")
    ts=r.get("timestamp")
    check(isinstance(ts,list) and len(ts)>1,"SHORT_HISTORY")
    dates=[day(t) for t in ts]
    check(dates==sorted(set(dates)),"DUPLICATE_OR_UNSORTED_DATES")
    try:
        quote=r["indicators"]["quote"][0]["close"]
        adjusted=r["indicators"]["adjclose"][0]["adjclose"]
    except (KeyError,IndexError,TypeError) as exc:
        raise ValueError("ADJUSTED_SERIES_MISSING") from exc
    check(isinstance(quote,list) and isinstance(adjusted,list) and len(quote)==len(ts)==len(adjusted),"ARRAY_DIMENSIONS")
    ev=(r.get("events") or {}).get("dividends",{})
    check(isinstance(ev,dict),"EVENT_SCHEMA_INVALID")
    index={d:i for i,d in enumerate(dates)}
    rows=[];seen=set()
    for key in sorted(ev):
        e=ev[key];check(isinstance(e,dict),"EVENT_NOT_DICT")
        amt=e.get("amount");check(pos(amt),"NONPOSITIVE_DIVIDEND")
        d=day(e.get("date"));check(d not in seen,"DUPLICATE_DIVIDEND_DATE");seen.add(d)
        i=index.get(d);v={"EventDate":d,"Dividend":amt,"FormalEligible":False}
        if i is None or i==0:
            v["Status"]="HOLD_EVENT_DAY_OR_PREVIOUS_DAY_MISSING"
        else:
            p,q,ap,aq=quote[i-1],quote[i],adjusted[i-1],adjusted[i]
            if not all(pos(n) for n in (p,q,ap,aq)) or p<=amt:
                v["Status"]="HOLD_BAD_RAW_OR_ADJUSTED_PRICE"
            else:
                observed=((aq/q)/(ap/p)-1)*100
                expected=amt/(p-amt)*100
                v.update(PreviousClose=p,ObservedFactorJumpPct=observed,
                         ExpectedCashFactorJumpPct=expected,DriftPctPoint=observed-expected)
                if abs(observed-expected)>max(0.005,0.02*expected):
                    v["Status"]="HOLD_FACTOR_INCONSISTENCY"
                elif observed<0:
                    v["Status"]="HOLD_NEGATIVE_FACTOR_JUMP"
                elif observed<=threshold:
                    v["Status"]="MATCHED_EXCLUDED_BY_THRESHOLD"
                else:
                    v["Status"]="MATCHED_INCLUDED_BY_THRESHOLD"
        rows.append(v)
    matched=[r for r in rows if r["Status"].startswith("MATCHED")]
    excluded=[r for r in rows if r["Status"]=="MATCHED_EXCLUDED_BY_THRESHOLD"]
    holds=[r for r in rows if r["Status"].startswith("HOLD")]
    return {"Status":"RESEARCH_MATCHED" if not holds else "RESEARCH_PARTIAL_HOLD",
      "Symbol":symbol,"RawSHA256":hashlib.sha256(raw).hexdigest(),
      "DividendLabels":len(rows),"Matched":len(matched),
      "ExcludedByCountingThreshold":len(excluded),"Holds":len(holds),
      "Events":rows,"FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
      "Warning":"Issuer event exhaustive not proven; no canonical forecast or position changes."}
def selftest():
    tz=dt.timezone(dt.timedelta(hours=8));d0=dt.datetime(2026,7,24,tzinfo=tz).timestamp()
    d1=dt.datetime(2026,7,27,tzinfo=tz).timestamp()
    def fixture(amt=0.217665):
        p=437.5;q=422.5
        return {"chart":{"error":None,"result":[{"meta":{"symbol":"DEMO.TW"},
         "timestamp":[d0,d1],"indicators":{"quote":[{"close":[p,q]}],
         "adjclose":[{"adjclose":[p-amt,q]}]},
         "events":{"dividends":{"a":{"date":d1,"amount":amt}}}}]}}
    def run(z,symbol="DEMO.TW",threshold=0.05):
        return reconcile(json.dumps(z).encode(),symbol,threshold)
    tests={}
    def evaluate(k,fn,reject=False):
        try:
            good=fn()
            tests[k]="FAIL" if reject else ("PASS" if good else "FAIL")
        except (ValueError,TypeError,KeyError,IndexError,OverflowError):
            tests[k]="PASS" if reject else "FAIL"
    result=run(fixture())
    evaluate("tiny_dividend_not_missing",lambda:result["ExcludedByCountingThreshold"]==1)
    evaluate("tiny_event_matched",lambda:result["Matched"]==1)
    evaluate("factor_expected_match",lambda:abs(result["Events"][0]["ObservedFactorJumpPct"]-0.04977676)<0.0001)
    evaluate("large_event_counted",lambda:run(fixture(1.0))["Matched"]==1 and run(fixture(1.0))["ExcludedByCountingThreshold"]==0)
    evaluate("never_formal",lambda:not result["FormalEligible"] and not result["NaturalCredit"] and not result["OOSCredit"])
    evaluate("reject_zero_threshold",lambda:run(fixture(),threshold=0),True)
    evaluate("reject_wrong_symbol",lambda:run(fixture(),symbol="OTHER.TW"),True)
    evaluate("reject_negative_dividend",lambda:run(fixture(-1)),True)
    bad=fixture();bad["chart"]["result"][0]["timestamp"]=[d1,d1]
    evaluate("reject_duplicate_bar",lambda:run(bad),True)
    bad=fixture();bad["chart"]["result"][0]["indicators"].pop("adjclose")
    evaluate("reject_missing_adjusted",lambda:run(bad),True)
    bad=fixture();bad["chart"]["result"][0]["indicators"]["quote"][0]["close"][0]=0
    evaluate("hold_invalid_prev_close",lambda:run(bad)["Holds"]==1)
    bad=fixture();bad["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][0]=437.5
    evaluate("hold_wrong_adjusted_factor",lambda:run(bad)["Holds"]==1)
    bad=fixture();bad["chart"]["result"][0]["events"]["dividends"]["b"]={"date":d1,"amount":0.1}
    evaluate("reject_duplicate_event",lambda:run(bad),True)
    bad=fixture();bad["chart"]["result"][0]["events"]["dividends"]["a"]["date"]=d0
    evaluate("hold_no_prior_event_bar",lambda:run(bad)["Holds"]==1)
    bad=fixture();bad["chart"]["result"][0]["timestamp"]=[d1,d0]
    evaluate("reject_backwards_bars",lambda:run(bad),True)
    good=all(x=="PASS" for x in tests.values())
    return {"status":"PASS" if good else "FAIL","passed":sum(x=="PASS" for x in tests.values()),
      "total":len(tests),"scope":"SYNTHETIC_NO_PRIVATE_INPUT_NO_FORMAL","tests":tests}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--chart");p.add_argument("--symbol");p.add_argument("--out")
    p.add_argument("--threshold",type=float,default=0.05)
    a=p.parse_args()
    if a.self_test:
        r=selftest();print(json.dumps(r));return 0 if r["status"]=="PASS" else 2
    if not all((a.chart,a.symbol,a.out)):p.error("--chart --symbol --out required")
    report=reconcile(pathlib.Path(a.chart).read_bytes(),a.symbol,a.threshold)
    path=pathlib.Path(a.out);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(json.dumps({k:report[k] for k in ("Status","DividendLabels","Matched","ExcludedByCountingThreshold","Holds")}))
    return 0 if report["Holds"]==0 else 2
if __name__=="__main__":raise SystemExit(main())
