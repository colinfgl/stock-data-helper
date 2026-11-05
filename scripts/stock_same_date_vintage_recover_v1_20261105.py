#!/usr/bin/env python3
"""Use earlier SAME-CUTOFF verified originals for RESEARCH when a later Yahoo vintage goes NULL.
Never overwrite either original capture. No Formal, Natural, OOS, Cash, Config or delivery credit.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,pathlib,re
from zoneinfo import ZoneInfo
from stock_daily_prior_close_source_closure_v1_20261013 import (
    approved_universe, build_h9_package, bind_calendar_to_source_index,
)
TZ=ZoneInfo("Asia/Taipei")

def require(ok,reason):
    if not ok:raise ValueError(reason)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def as_local(s):
    t=dt.datetime.fromisoformat(str(s).replace("Z","+00:00"))
    require(t.tzinfo is not None,"TIMESTAMP_WITHOUT_TIMEZONE")
    return t.astimezone(TZ)

def recover(current_raw,earlier_raw,earlier_run_id,out):
    cur=pathlib.Path(current_raw);earlier=pathlib.Path(earlier_raw);out=pathlib.Path(out)
    require(re.fullmatch(r"[0-9]{7,20}",str(earlier_run_id)) is not None,"BAD_ARCHIVE_RUN_ID")
    require(not out.exists(),"OUTPUT_EXISTS_DO_NOT_OVERWRITE")
    current_receipt=json.loads((cur/"acquisition_receipt.json").read_bytes())
    earlier_receipt=json.loads((earlier/"acquisition_receipt.json").read_bytes())
    a=current_receipt["dates"];b=earlier_receipt["dates"]
    for key in ("target_date","price_cutoff","previous_session"):
        require(a[key]==b[key],"ORIGINAL_SOURCE_DATE_CONFLICT_"+key)
    day=dt.datetime.strptime(a["price_cutoff"],"%Y%m%d").date()
    target=dt.date.fromisoformat(a["target_date"])
    require(day<target and (target-day).days<=8,"INVALID_SESSION_ORDER")
    old_time=as_local(earlier_receipt["started_at"])
    new_time=as_local(current_receipt["started_at"])
    require(old_time<new_time<dt.datetime.combine(target,dt.time(8,9,30),TZ),
            "EARLIER_ORIGINAL_IS_LATE_OR_FUTURE")
    require(current_receipt.get("official_validation_pass") is True and
            earlier_receipt.get("official_validation_pass") is True,
            "OFFICIAL_SOURCE_VALIDATION_NOT_PASS")
    require(earlier_receipt.get("transport_complete") is True,
            "EARLIER_ORIGINAL_TRANSPORT_INCOMPLETE")
    official_names=[f"TWSE_{day:%Y%m%d}.json",f"TPEX_{day:%Y%m%d}.json",
                    "ohlc_raw.json","calendar.json"]
    official_sha={}
    old_sources={x["path"]:x for x in earlier_receipt["sources"] if x.get("path")}
    for name in official_names:
        x=(earlier/name).read_bytes();y=(cur/name).read_bytes()
        require(len(x)>100 and x==y,"OFFICIAL_DATE_ORIGINAL_BYTES_CONFLICT_"+name)
        require(old_sources.get(name,{}).get("sha256")==sha(x),
                "EARLIER_OFFICIAL_RECEIPT_SHA_INVALID_"+name)
        official_sha[name]=sha(x)
    symbols=approved_universe()
    statuses={x.get("symbol"):x for x in earlier_receipt.get("charts",[])}
    require(len(statuses)==len(symbols)==68,"ARCHIVE_UNIVERSE_NOT_68")
    for symbol in symbols:
        require(statuses.get(symbol,{}).get("status")=="NATIVE_ADJUSTED_CROSSCHECK_PASS",
                "EARLIER_SOURCE_NOT_VERIFIED_"+symbol)
        name=f"chart_{symbol}.json"
        raw=(earlier/name).read_bytes()
        require(len(raw)>100 and old_sources.get(name,{}).get("sha256")==sha(raw),
                "EARLIER_VENDOR_ORIGINAL_SHA_INVALID_"+symbol)
    root=out/"research_only";root.mkdir(parents=True)
    original=build_h9_package(earlier,target,day,symbols,root/"model_input")
    result=bind_calendar_to_source_index(root/"model_input",root,
                                        official_sha["calendar.json"],original)
    require(result.get("status")=="RESEARCH_SOURCE_68_OF_68_READY_NOT_FORMAL"
            and result.get("ticker_count")==68 and result.get("per_symbol_sha_count")==68,
            "ARCHIVE_REVALIDATION_NOT_FULL_68")
    require(result.get("formal_input_qualified") is False and
            result.get("natural_credit")==result.get("oos_credit")==0,
            "FORBIDDEN_FORMAL_OR_NATURAL_CREDIT")
    receipt={
      "Status":"VERIFIED_EARLIER_SAME_DATE_RESEARCH_SOURCE_ONLY",
      "TargetDate":target.isoformat(),"SourceDate":day.isoformat(),
      "EarlierGitHubRunID":str(earlier_run_id),
      "EarlierOriginalReceiptSHA256":sha((earlier/"acquisition_receipt.json").read_bytes()),
      "CurrentIncompleteReceiptSHA256":sha((cur/"acquisition_receipt.json").read_bytes()),
      "EarlierCapturedAt":earlier_receipt["started_at"],
      "CurrentAttemptAt":current_receipt["started_at"],
      "FourOfficialOriginalsSameBytesSHA256":official_sha,
      "ReverifiedRawSymbols":68,"ResearchBundleSHA256":result["package_sha256"],
      "UnmodifiedEarlierOriginal":True,"UnmodifiedCurrentOriginal":True,
      "VendorVintagesAreNotIndependentProviders":True,
      "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
      "ForecastWritten":False,"CashWritten":False,
      "Limitation":"Separately labeled prior original, not the current attempt or a formal market source approval."
    }
    file=root/"same_date_recovery_receipt.json"
    text=json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    file.write_text(text,encoding="utf-8")
    require(file.read_bytes()==text.encode(),"RECOVERY_RECEIPT_READBACK_FAILED")
    return receipt

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--current-raw",required=True)
    a.add_argument("--earlier-raw",required=True)
    a.add_argument("--earlier-run-id",required=True)
    a.add_argument("--output",required=True)
    v=a.parse_args()
    r=recover(v.current_raw,v.earlier_raw,v.earlier_run_id,v.output)
    print(json.dumps({k:r[k] for k in
       ("Status","TargetDate","SourceDate","EarlierGitHubRunID","ReverifiedRawSymbols",
        "FormalEligible","NaturalCredit","OOSCredit")},ensure_ascii=False))
if __name__=="__main__":main()
