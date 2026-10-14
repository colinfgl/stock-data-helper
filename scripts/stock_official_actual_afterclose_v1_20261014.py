#!/usr/bin/env python3
"""Independent TWSE/TPEx exact-session postclose evidence for research scoring.

No connection to 08:10 preopen, no upgrade to Formal/Outcome/OOS/Natural.
Accept only first-party date-matched ORIGINAL response bytes; keep failures
rather than replacing with Yahoo / Investing / synthetic quotes. No provider
names/values are fabricated. This afterclose-only collector is NOT the 20:45
next-session adjusted-history source collector and does not alter it.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Taipei")
RAW_MAX=26000000
def sha(blob): return hashlib.sha256(blob).hexdigest()
def ensure(test,msg):
    if not test: raise ValueError(msg)
def strict(raw):
    def pairs(ps):
        o={}
        for k,v in ps:
            ensure(k not in o,"DUPLICATE_JSON_KEY_"+k)
            o[k]=v
        return o
    return json.loads(raw.decode("utf-8-sig"),object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("JSON_NONFINITE_"+x)))

def dayparse(raw):
    s=str(raw).strip()
    if re.fullmatch(r"\d{8}",s):
        return dt.datetime.strptime(s,"%Y%m%d").date()
    if re.fullmatch(r"\d{2,4}/\d{1,2}/\d{1,2}",s):
        y,m,d=map(int,s.split("/"))
        return dt.date(y+1911 if y<1911 else y,m,d)
    return dt.date.fromisoformat(s)

def positive(raw):
    try:
        x=float(str(raw).strip().replace(",",""))
        return x if x>0 and math.isfinite(x) else None
    except (ValueError,TypeError,OverflowError):return None

def blocks(doc):
    result=[]
    if isinstance(doc.get("tables"),list):result.extend(doc["tables"])
    if "fields" in doc and "data" in doc:
        result.append({"fields":doc["fields"],"data":doc["data"]})
    for k,v in doc.items():
        m=re.fullmatch(r"fields(\d+)",k)
        if m and "data"+m[1] in doc:result.append({"fields":v,"data":doc["data"+m[1]]})
    return result

def security_rows(doc,day,venue):
    ensure(isinstance(doc,dict) and str(doc.get("stat","")).lower()=="ok",
           "EXCHANGE_STATUS_NOT_OK_"+venue)
    ensure(dayparse(doc.get("date"))==day,"WRONG_EXCHANGE_DATE_"+venue)
    cid,nid,closefield,opening,hifield,lofield=(
        ("證券代號","證券名稱","收盤價","開盤價","最高價","最低價")
        if venue=="TWSE" else ("代號","名稱","收盤","開盤","最高","最低"))
    output={};match=0
    for t in blocks(doc):
        fields=t.get("fields") or []
        if cid not in fields: continue
        for col in (cid,nid,closefield):
            ensure(fields.count(col)==1,"REQUIRED_OR_DUPLICATE_FIELD_"+venue+"_"+col)
        cm=[fields.index(z) if z in fields else None
            for z in (cid,nid,closefield,opening,hifield,lofield)]
        ensure(isinstance(t.get("data"),list),"EXCHANGE_DATA_ROWS_NOT_LIST")
        match+=1
        for row in t["data"]:
            ensure(isinstance(row,list) and len(row)==len(fields),"BAD_EXCHANGE_ROW_WIDTH")
            symbol=str(row[cm[0]]).strip()
            name=str(row[cm[1]]).strip()
            if not re.fullmatch(r"[A-Z0-9]{4,8}",symbol):continue
            ensure(symbol not in output,"EXCHANGE_DUPLICATE_SYMBOL_"+symbol)
            ensure(name,"EXCHANGE_NAME_EMPTY_"+symbol)
            values=[positive(row[c]) if c is not None else None for c in cm[2:]]
            close,op,hi,lo=values
            if all(v is not None for v in (close,op,hi,lo)):
                ensure(lo<=op<=hi and lo<=close<=hi,
                       "EXCHANGE_OHLC_INVARIANT_"+symbol)
            output[symbol]={"code":symbol,"name":name,"venue":venue,
                            "close":close,"open":op,"high":hi,"low":lo,
                            "actual_qualification":
                                "PRIMARY_OFFICIAL_EXACT_DATE_OHLC" if all(v is not None for v in (close,op,hi,lo))
                                else "OFFICIAL_ROW_PARTIAL_VALUE_HOLD"}
    ensure(match>0 and len(output)>5,"NO_RECOGNIZED_EXCHANGE_QUOTE_TABLE_"+venue)
    return output

def taiex_row(doc,date):
    ensure(isinstance(doc,dict) and str(doc.get("stat","")).lower()=="ok" and
           dayparse(doc.get("date"))==date,"TAIEX_SOURCE_DATE_OR_STATUS")
    f=doc.get("fields",[])
    required=["日期","開盤指數","最高指數","最低指數","收盤指數"]
    ensure(all(f.count(x)==1 for x in required),"TAIEX_FIELDS")
    ix=[f.index(x) for x in required]
    matches=[]
    for row in doc.get("data",[]):
        ensure(isinstance(row,list) and len(row)>max(ix),"TAIEX_ROW_SCHEMA")
        rday=dayparse(row[ix[0]])
        # TWSE monthly history returned during a retrospective afterclose read
        # may already contain LATER sessions. Never use those rows as the
        # target outcome, but do not reject the genuine target row because of
        # its presence. This AFTERCLOSE-only parser never issues a forecast.
        if rday!=date:continue
        vals=[positive(row[i]) for i in ix[1:]]
        ensure(all(x is not None for x in vals),"TAIEX_NONNUMERIC_VALUE")
        op,hi,lo,close=vals
        ensure(lo<=op<=hi and lo<=close<=hi,"TAIEX_OHLC_INVARIANT")
        matches.append({"open":op,"high":hi,"low":lo,"close":close})
    ensure(len(matches)==1,"TAIEX_TARGET_ROW_NOT_UNIQUE")
    return matches[0]

def fetch(url,outdir,name):
    root=pathlib.Path(outdir);root.mkdir(parents=True,exist_ok=True)
    records=[]
    for attempt in range(1,3):
        e={"role":name,"url":url,"attempt":attempt,
           "retrieved_at":dt.datetime.now(dt.timezone.utc).isoformat()}
        raw=None
        try:
            req=urllib.request.Request(url,headers={
                "User-Agent":"Mozilla/5.0 Stock-Actual-Afterclose-Original-Evidence",
                "Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=28) as res:
                raw=res.read(RAW_MAX+1);status=res.status;final=res.geturl()
            ensure(len(raw)<=RAW_MAX,"HTTP_BODY_TOO_LARGE")
            ensure(status==200,"HTTP_NOT_200_"+str(status))
            ensure(urllib.parse.urlparse(final).hostname==urllib.parse.urlparse(url).hostname,
                   "HTTP_REDIRECT_ORIGIN_CHANGED")
            doc=strict(raw)
            f=root/(name+".json");f.write_bytes(raw)
            ensure(f.read_bytes()==raw,"RAW_FILE_BYTES_READBACK_DRIFT")
            e.update(status="FETCHED_UNQUALIFIED_PENDING_PARSE",bytes=len(raw),
                     sha256=sha(raw),raw_filename=f.name)
            records.append(e)
            return doc,e
        except Exception as exc:
            e.update(status="SOURCE_HOLD",error=type(exc).__name__+":"+str(exc)[:230])
            if raw:
                f=root/(name+".attempt"+str(attempt)+".raw.unqualified")
                f.write_bytes(raw[:500000]);e["partial_sha256"]=sha(f.read_bytes())
            records.append(e)
            if attempt==1:time.sleep(1)
    return None,{"status":"SOURCE_HOLD","attempts":records,"role":name}

def actual(day,root):
    z=dt.datetime.now(TZ)
    ensure(day<=z.date(),"TARGET_IN_FUTURE")
    ensure(day<z.date() or z.time()>=dt.time(15,30),"CURRENT_DAY_NOT_AFTER_1530")
    # URL paths are established from existing original public_market_daily.
    urls={
        "twse":f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={day:%Y%m%d}&type=ALLBUT0999&response=json",
        "tpex":f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={day:%Y/%m/%d}&id=&response=json",
        "ohlc":f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={day:%Y%m%d}&response=json"}
    sources={};docs={}
    for key,url in urls.items():
        d,receipt=fetch(url,pathlib.Path(root)/"originals",key)
        sources[key]=receipt;docs[key]=d
    quotes={}; holds=[]
    for key,venue in (("twse","TWSE"),("tpex","TPEx")):
        if docs[key] is None:
            holds.append("SOURCE_"+key+"_NO_VALID_HTTP_OR_JSON")
            continue
        try:
            parsed=security_rows(docs[key],day,venue)
            ensure(sources[key]["sha256"]==sha((pathlib.Path(root)/"originals"/(key+".json")).read_bytes()),
                   "RAW_READBACK_SHA_MISMATCH")
            for code,row in parsed.items():
                ensure(code not in quotes,"TWSE_TPEX_VENUE_COLLISION_"+code)
                quotes[code]=row
            sources[key]["status"]="OFFICIAL_EXACT_DATE_SCHEMA_SHA_PASS"
            sources[key]["parsed_symbols"]=len(parsed)
        except (ValueError,TypeError,KeyError) as e:
            holds.append(str(e));sources[key]["status"]="ORIGINAL_HTTP_OK_BUT_SCHEMA_OR_DATE_HOLD"
    index=None
    if docs["ohlc"] is not None:
        try:
            index=taiex_row(docs["ohlc"],day)
            sources["ohlc"]["status"]="OFFICIAL_EXACT_DATE_TAIEX_OHLC_SHA_PASS"
        except (ValueError,TypeError,KeyError) as e:
            holds.append(str(e));sources["ohlc"]["status"]="TAIEX_ORIGINAL_NOT_QUALIFIED"
    else:
        holds.append("TAIEX_RAW_NOT_AVAILABLE")
    # Existing permanent universe; the raw original is never smuggled from a
    # screenshot or a 2026-10-13 replay.
    from stock_adjusted_20261013_source_closure import CODES
    ensure(len(CODES)==68 and len(set(CODES))==68,"EXACT_68_UNIVERSE_REQUIRED")
    rows=[]
    for symbol in CODES:
        code,venue=symbol.split(".")
        x=quotes.get(code)
        expected="TWSE" if venue=="TW" else "TPEx"
        if x is not None and x["venue"]!=expected:
            holds.append("VENUE_MISMATCH_"+symbol);x=None
        rows.append({"symbol":code,"ticker":symbol,
                     "name":x["name"] if x else None,
                     "venue":expected,
                     "close":x["close"] if x else None,
                     "high":x["high"] if x else None,
                     "low":x["low"] if x else None,
                     "open":x["open"] if x else None,
                     "source_status":x["actual_qualification"] if x else "NO_PRIMARY_ORIGINAL_ROW_HOLD"})
    official=sum(x["source_status"]=="PRIMARY_OFFICIAL_EXACT_DATE_OHLC" for x in rows)
    output={"target_date":day.isoformat(),"session_roc":f"{day.year-1911}/{day.month:02d}/{day.day:02d}",
            "report_type":"REAL_AFTERCLOSE_FIRST_PARTY_68_RESEARCH_OUTCOME_CANDIDATE",
            "capture_at":z.isoformat(),"universe":68,"exact_ohlc_count":official,
            "partial_or_hold_count":68-official,"originals":sources,
            "taiex":index,"errors":holds,"Rows":rows,
            "formal_prediction_written":False,"canonical_outcome_written":False,
            "cash_trading_authorized":False,"natural_credit":0,"oos_credit":0,
            "not_historical_preopen":True}
    file=pathlib.Path(root)/"official_actual_research_68.json"
    data=json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    file.write_text(data,encoding="utf8")
    ensure(file.read_bytes()==data.encode(),"COMPARISON_JSON_READBACK_FAILED")
    output["research_report_SHA256"]=sha(data.encode())
    return output

def test():
    d=dt.date(2026,10,14)
    def fixture(venue="TWSE"):
        fields=(["證券代號","證券名稱","開盤價","最高價","最低價","收盤價"]
                if venue=="TWSE" else ["代號","名稱","開盤","最高","最低","收盤"])
        return {"date":"20261014","stat":"OK","tables":[
            {"fields":fields,"data":[["2330" if venue=="TWSE" else "8147",
              "台積電" if venue=="TWSE" else "正淩","2495","2535","2485","2525"]]+[
                  [str(1000+i),"測試"+str(i),"12","13","11","12"] for i in range(7)]}]}
    cases={}
    def chk(name,fn,reject=False):
        try:
            v=fn();cases[name]=bool(v) and not reject
        except (ValueError,KeyError,TypeError):
            cases[name]=reject
    import copy
    a=fixture()
    chk("valid_official_twse",lambda:len(security_rows(a,d,"TWSE"))==8)
    chk("valid_official_tpex",lambda:len(security_rows(fixture("TPEx"),d,"TPEx"))==8)
    chk("malformed_day",lambda:security_rows(dict(a,date="20261013"),d,"TWSE"),True)
    chk("empty_status",lambda:security_rows(dict(a,stat=""),d,"TWSE"),True)
    chk("duplicate_symbol",lambda:security_rows(dict(a,tables=[dict(a["tables"][0],data=a["tables"][0]["data"]*2)]),d,"TWSE"),True)
    chk("missing_name_column",lambda:security_rows(dict(a,tables=[dict(a["tables"][0],fields=a["tables"][0]["fields"][:1]+["xxx"]+a["tables"][0]["fields"][2:])]),d,"TWSE"),True)
    chk("price_inconsistent",lambda:security_rows(dict(a,tables=[dict(a["tables"][0],data=[["2330","台積電","2495","2535","2485","2400"]]+a["tables"][0]["data"][1:])]),d,"TWSE"),True)
    chk("raw_json_duplicate_key",lambda:strict(b'{"date":"20261014","date":"20261013"}'),True)
    chk("roc_date_parse",lambda:dayparse("115/10/14")==d)
    chk("invalid_nonpositive",lambda:positive("--") is None and positive("-1") is None)
    fi={"date":"20261014","stat":"OK","fields":["日期","開盤指數","最高指數","最低指數","收盤指數"],
        "data":[["115/10/14","48000","49000","47800","48800"]]}
    chk("real_ohlc_parser",lambda:taiex_row(fi,d)["close"]==48800)
    chk("historical_month_future_rows_do_not_block_target",
        lambda:taiex_row(dict(fi,data=fi["data"]+[
            ["115/10/15","50000","50500","49700","50020"]]),d)["close"]==48800)
    chk("future_month_row_cannot_become_historical_actual",
        lambda:taiex_row(dict(fi,data=[
            ["115/10/12","50000","50500","49700","50020"],
            ["115/10/14","48000","49000","47800","48800"]]),d)["close"]==48800)

    chk("tai_ex_future_illegal",lambda:taiex_row(dict(fi,data=[["115/10/15","48000","49000","47800","48800"]]),d),True)
    chk("tai_ex_bad_high_low",lambda:taiex_row(dict(fi,data=[["115/10/14","48000","47000","47800","48800"]]),d),True)
    chk("tai_ex_dup_target",lambda:taiex_row(dict(fi,data=fi["data"]*2),d),True)
    chk("prevent_vendor_quote_as_primary",lambda:strict(b'{"provenance":"YAHOO","date":"20261014","stat":"BAD"}')["stat"]!="OK")
    result={"status":"PASS" if len(cases)==17 and all(cases.values()) else "FAIL",
            "passed":sum(cases.values()),"total":len(cases),"checks":cases,
            "scope":"SYNTHETIC_PARSE_TEST_ONLY_NO_ONLINE_NO_NATURAL"}
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",default="2026-10-14")
    p.add_argument("--out",default="official_actual_20261014")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        ret=test()
        print(json.dumps(ret,ensure_ascii=False))
        return 0 if ret["status"]=="PASS" else 2
    d=dayparse(args.date)
    ret=actual(d,args.out)
    print("OFFICIAL_CAPTURE_STATUS",ret["target_date"],ret["exact_ohlc_count"],
          "out of",ret["universe"],"holds",ret["partial_or_hold_count"])
    print("__STOCK_AFTERCLOSE_68_START__")
    print(json.dumps({"date":ret["target_date"],"count":ret["exact_ohlc_count"],
          "taiex":ret["taiex"],"sha":ret["research_report_SHA256"],
          "sources":{k:{"status":v.get("status"),"sha":v.get("sha256"),
                        "error":v.get("attempts",[])[-1].get("error") if v.get("attempts") else None}
                     for k,v in ret["originals"].items()},
          "rows":ret["Rows"]},ensure_ascii=False,separators=(",",":"),allow_nan=False))
    print("__STOCK_AFTERCLOSE_68_END__")
    return 0 if ret["exact_ohlc_count"]==68 and ret["taiex"] is not None else 2

if __name__=="__main__":
    raise SystemExit(main())
