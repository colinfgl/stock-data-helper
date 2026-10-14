#!/usr/bin/env python3
"""Date-generic immutable three-original 68-stock research bridge.

No 2026-10-13/14 runtime constant, no synthetic vendor original and no
production price/prediction/OOS/issuer/cash claim. Three actual collector
receipts, 68 matching vendor symbols and first-party TWSE/TPEx day-specific
raw files are verified before issuing any research-ready row. A bad ticker
is held independently; the original strict 68 single-provider hard gate
remains untouched.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re

from stock_dual_origin_prior_close_research_v1_20261013 import (
    TZ,acceptable,chart,good,guard,official_prices,read_stamped_receipt,
)

N=68
DAY8=re.compile(r"^[0-9]{8}$")
SYMBOL=re.compile(r"^[0-9A-Z]{4,8}\.(?:TW|TWO)$")
SHA=re.compile(r"^[a-f0-9]{64}$")

def rawfile(root, filename, entries, cutoff):
    guard(re.fullmatch(r"[A-Za-z0-9_.-]+",filename) is not None,"UNSAFE_RAW_FILENAME")
    f=root/filename
    b=f.read_bytes()
    receipt=entries.get(filename)
    guard(isinstance(receipt,dict) and receipt.get("status")=="FETCHED",
          "MISSING_RAW_CAPTURE_RECEIPT_"+filename)
    guard(receipt.get("sha256")==hashlib.sha256(b).hexdigest(),
          "RAW_FILE_SHA_MISMATCH_"+filename)
    try:
        time=dt.datetime.fromisoformat(receipt["retrieved_at"].replace("Z","+00:00"))
    except (ValueError,KeyError,AttributeError):
        raise ValueError("ORIGINAL_CAPTURE_TIMESTAMP_MISSING")
    guard(time.tzinfo is not None and time.astimezone(TZ)<=cutoff,
          "SOURCE_AFTER_TARGET_PREOPEN_CUTOFF")
    return b,receipt,time.astimezone(TZ)

def dates_from_receipts(old,eve,morn):
    ad=eve.get("dates",{})
    bd=morn.get("dates",{})
    prev=ad.get("previous_session")
    cur=ad.get("price_cutoff")
    if not isinstance(prev,str) or not DAY8.fullmatch(prev) or not isinstance(cur,str) or not DAY8.fullmatch(cur):
        raise ValueError("INVALID_ORIGINAL_SESSION_DATES")
    try:
        p=dt.datetime.strptime(prev,"%Y%m%d").date()
        c=dt.datetime.strptime(cur,"%Y%m%d").date()
        target=dt.date.fromisoformat(ad.get("target_date",""))
    except ValueError:
        raise ValueError("INVALID_SESSION_OR_TARGET_DATE")
    guard(p<c<target and (c-p).days<=8 and (target-c).days<=8,
          "NONMONOTONIC_SOURCE_SESSION_TARGET")
    expected_prev=(c.isoformat(),prev)
    guard(old.get("dates",{}).get("target_date")==expected_prev[0] and
          old["dates"].get("price_cutoff")==expected_prev[1],
          "PRIOR_RAW_CAPTURE_FROM_WRONG_SOURCE_DAY")
    guard(bd.get("previous_session")==prev and
          bd.get("price_cutoff")==cur and bd.get("target_date")==target.isoformat(),
          "EVENING_AND_MORNING_SOURCE_DATES_CONFLICT")
    return prev,cur,target

def parent_pair(raw_old,raw_new,symbol,prev_day,cur_day,official_prev,official_cur):
    old=chart(raw_old,symbol)
    new=chart(raw_new,symbol)
    pp=old.get(prev_day)
    cc=new.get(cur_day)
    guard(pp and all(good(pp.get(k)) for k in ("close","adj")),"PRIOR_ORIGINAL_BAR_MISSING")
    guard(cc and all(good(cc.get(k)) for k in ("close","adj")),"CURRENT_ORIGINAL_BAR_MISSING")
    guard(acceptable(pp["close"],official_prev) and acceptable(cc["close"],official_cur),
          "VENDOR_CLOSE_CONFLICTS_WITH_OFFICIAL")
    shared=0
    for day in sorted(set(old)&set(new)):
        a,b=old[day],new[day]
        if all(good(z) for z in (a["close"],a["adj"],b["close"],b["adj"])):
            guard(acceptable(a["close"],b["close"]) and
                  acceptable(a["adj"],b["adj"]),"PARENT_ADJUSTMENT_OR_PRICE_DRIFT_"+day)
            shared+=1
    guard(shared>=5,"INSUFFICIENT_PARENT_OVERLAP")
    previous_in_current=new.get(prev_day)
    if previous_in_current and all(good(previous_in_current[k]) for k in ("close","adj")):
        guard(acceptable(previous_in_current["close"],official_prev) and
              acceptable(previous_in_current["adj"],pp["adj"]),
              "CURRENT_SOURCE_PREVIOUS_SESSION_MISMATCH")
    return shared

def reconcile_three(old_raw,eve_raw,morn_raw,symbol,prev_day,cur_day,official_prev,official_cur):
    parent_shared=parent_pair(old_raw,eve_raw,symbol,prev_day,cur_day,
                              official_prev,official_cur)
    e=chart(eve_raw,symbol)
    m=chart(morn_raw,symbol)
    overlaps=0
    for date in sorted(set(e)&set(m)):
        aa,bb=e[date],m[date]
        for key in ("close","adj"):
            if good(aa[key]) and good(bb[key]):
                guard(acceptable(aa[key],bb[key]),
                      "MORNING_EVENING_RAW_CONFLICT_"+date+"_"+key)
                overlaps+=1
    guard(overlaps>=10,"TOO_FEW_INDEPENDENT_COMMON_ORIGINAL_VALUES")
    eve=e[cur_day]
    guard(all(good(eve[k]) for k in ("close","adj")),
          "EVENING_ORIGINAL_CURRENT_CLOSE_NULL")
    current=m.get(cur_day)
    if current:
        for key in ("close","adj"):
            if good(current[key]):
                guard(acceptable(current[key],eve[key]),
                      "PARTIAL_MORNING_NEW_DAY_RAW_CONFLICT")
    direct=bool(current and all(good(current.get(k)) for k in ("close","adj")))
    if direct:
        parent_pair(old_raw,morn_raw,symbol,prev_day,cur_day,
                    official_prev,official_cur)
    chosen=current if direct else eve
    return {
       "RecoveryStatus":"THREE_ORIGINALS_RESEARCH_MATCH",
       "SelectedSourceRole":("MORNING_DIRECT_VERIFIED"
                             if direct else "EVENING_ORIGINAL_RESEARCH_FALLBACK"),
       "PreviousOfficialClose":official_prev,
       "CurrentOfficialClose":official_cur,
       "SelectedDayAdjustedClose":chosen["adj"],
       "ValidOverlapValues":overlaps,
       "ParentOverlappingDays":parent_shared,
       "MorningOriginalHadUsableDay":direct,
       "PriorSourceRawSHA256":hashlib.sha256(old_raw).hexdigest(),
       "EveningSourceRawSHA256":hashlib.sha256(eve_raw).hexdigest(),
       "MorningSourceRawSHA256":hashlib.sha256(morn_raw).hexdigest(),
       "SourceLineage":"THREE_SEPARATE_ORIGINAL_RAW_FILES_UNMERGED",
       "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
       "CashTradingAuthorized":False,"CanonicalPredictionWritten":False
    }

def run(prior_dir,evening_dir,morning_dir,outdir):
    roots=[pathlib.Path(z) for z in (prior_dir,evening_dir,morning_dir)]
    metas=[read_stamped_receipt(x) for x in roots]
    (pmeta,pent),(emeta,eent),(mmeta,ment)=metas
    prev,cur,target=dates_from_receipts(pmeta,emeta,mmeta)
    cutoff=dt.datetime.combine(target,dt.time(8,9,30),TZ)
    def syms(table):
        return sorted(k[len("chart_"):-5] for k in table
                      if k.startswith("chart_") and k.endswith(".json"))
    group=syms(pent)
    guard(len(group)==N and group==syms(eent)==syms(ment) and
          all(SYMBOL.fullmatch(z) for z in group),
          "68_SYMBOLS_THREE_SOURCE_UNIVERSE_DRIFT")
    official={}
    official_shas={}
    for tag,root,entries in (("evening",roots[1],eent),("morning",roots[2],ment)):
        for venue in ("TWSE","TPEX"):
            for day in (prev,cur):
                fname=f"{venue}_{day}.json"
                b,r,_=rawfile(root,fname,entries,cutoff)
                official[tag,venue,day]=official_prices(b,venue,day)
                official_shas[f"{tag}_{fname}"]=r["sha256"]
    rows=[]
    for symbol in group:
        code,ext=symbol.rsplit(".",1)
        venue="TPEX" if ext=="TWO" else "TWSE"
        day_prev=official["evening",venue,prev].get(code)
        day_cur=official["evening",venue,cur].get(code)
        other_prev=official["morning",venue,prev].get(code)
        other_cur=official["morning",venue,cur].get(code)
        name=day_cur.get("name") if day_cur else ""
        entry={"Symbol":code,"VendorSymbol":symbol,"Venue":venue,
               "OfficialName":name,"RecoveryStatus":"SOURCE_HOLD",
               "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
               "CashTradingAuthorized":False}
        try:
            guard(all((day_prev,day_cur,other_prev,other_cur)),
                  "OFFICIAL_TWO_DATE_ROW_ABSENT")
            guard(day_prev==other_prev and day_cur==other_cur,
                  "OFFICIAL_TWO_ORIGINAL_RECONCILIATION_CONFLICT")
            guard(day_prev["name"]==day_cur["name"] and
                  good(day_prev["close"]) and good(day_cur["close"]),
                  "OFFICIAL_NAME_OR_CLOSE_CHANGED")
            fn="chart_"+symbol+".json"
            prior,pc,pt=rawfile(roots[0],fn,pent,cutoff)
            eve,ec,et=rawfile(roots[1],fn,eent,cutoff)
            morning,mc,mt=rawfile(roots[2],fn,ment,cutoff)
            guard(pt<et<mt,"THREE_SOURCE_ORIGINAL_CAPTURE_CLOCK_CONFLICT")
            entry.update(reconcile_three(prior,eve,morning,symbol,
                      prev,cur,day_prev["close"],day_cur["close"]))
            entry.update(PriorRetrievedAt=pc["retrieved_at"],
                      EveningRetrievedAt=ec["retrieved_at"],
                      MorningRetrievedAt=mc["retrieved_at"])
        except (ValueError,KeyError,IndexError,TypeError,OSError) as exc:
            entry["MissingReason"]=str(exc)[:250]
        rows.append(entry)
    passed=sum(z["RecoveryStatus"]=="THREE_ORIGINALS_RESEARCH_MATCH" for z in rows)
    direct=sum(z.get("SelectedSourceRole")=="MORNING_DIRECT_VERIFIED" for z in rows)
    backup=sum(z.get("SelectedSourceRole")=="EVENING_ORIGINAL_RESEARCH_FALLBACK" for z in rows)
    report={
        "Status":"RESEARCH_THREE_ORIGINALS_68_COMPLETE_NO_FORMAL" if passed==N else
                 "RESEARCH_THREE_ORIGINALS_PARTIAL_HOLD",
        "TargetSession":target.isoformat(),"PreviousSession":prev,
        "CurrentSession":cur,"OriginalSourceUniverse":N,
        "EligibleResearchRows":passed,"ResearchHolds":N-passed,
        "MorningDirect":direct,"EveningFallback":backup,
        "OfficialParentRawSHA256":official_shas,
        "FrozenPreopenLatestEligibleTime":cutoff.isoformat(),
        "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
        "CanonicalPredictionWritten":False,"IssuerActionsFullyVerified":False,
        "CashTradingAuthorized":False,"NeverTreatThreeFilesAsOneProviderOriginal":True,
        "Rows":rows}
    out=pathlib.Path(outdir);out.mkdir(parents=True,exist_ok=True)
    jf=out/"three_original_research_68.json"
    mf=out/"three_original_research_68.md"
    jr=json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+"\n"
    jf.write_text(jr,encoding="utf8")
    md=["# "+target.isoformat()+" 三代原始行情 68 檔研究交付（不可升格正式）","",
        f"獨立原件核對 {passed}/68；直接 {direct}、前晚備援 {backup}、隔離 {N-passed}。",
        "Formal/Natural/OOS=0；三份原始檔不可重組成一份單一來源。",
        "|代號|官方中文名|前一日官方收盤|來源角色|研究狀態|",
        "|---|---|---:|---|---|"]
    for z in rows:
        price=z.get("CurrentOfficialClose")
        md.append("| "+" | ".join([
            z["Symbol"],str(z["OfficialName"]),
            f"{price:.2f}" if good(price) else "MISSING",
            z.get("SelectedSourceRole","HOLD"),
            z["RecoveryStatus"] if z["RecoveryStatus"]!="SOURCE_HOLD"
            else "HOLD:"+str(z.get("MissingReason","UNKNOWN"))
        ])+" |")
    ms="\n".join(md)+"\n";mf.write_text(ms,encoding="utf8")
    guard(jf.read_bytes()==jr.encode() and mf.read_bytes()==ms.encode(),
          "RESEARCH_REPORT_SHA_READBACK_FAILED")
    print(json.dumps({k:report[k] for k in (
        "Status","TargetSession","EligibleResearchRows","MorningDirect",
        "EveningFallback","ResearchHolds","FormalEligible")},
        ensure_ascii=False))
    return 0 if passed==N else 2

def selftest():
    import copy
    dates=[dt.datetime(2026,9,20+i,9,tzinfo=TZ) for i in range(12)]
    def generate(prev="20261013",current="20261014",morning_missing=True):
        p=dt.datetime.strptime(prev,"%Y%m%d").replace(hour=9,tzinfo=TZ)
        c=dt.datetime.strptime(current,"%Y%m%d").replace(hour=9,tzinfo=TZ)
        times=[int(z.timestamp()) for z in dates+[p,c]]
        def payload(valsp,valsc):
            b=[100+i for i in range(12)]+[valsp,valsc]
            return json.dumps({"chart":{"error":None,"result":[{
                "meta":{"symbol":"2330.TW"},"timestamp":times,
                "indicators":{"quote":[{"close":b}],"adjclose":[{"adjclose":b}]}}
            ]}},separators=(",",":")).encode()
        return payload(113,None),payload(None,114),payload(None,None if morning_missing else 114)
    x,y,z=generate()
    checks={}
    def test(name,fn,reject=False):
        try:
            out=fn()
            checks[name]=not reject and bool(out)
        except (ValueError,KeyError,TypeError,IndexError):
            checks[name]=reject
    test("missing_morning_falls_back_evening",
         lambda:reconcile_three(x,y,z,"2330.TW","20261013","20261014",113,114)
         ["SelectedSourceRole"]=="EVENING_ORIGINAL_RESEARCH_FALLBACK")
    test("fall_back_provenance_is_three_originals",
         lambda:reconcile_three(x,y,z,"2330.TW","20261013","20261014",113,114)
         ["SourceLineage"]=="THREE_SEPARATE_ORIGINAL_RAW_FILES_UNMERGED")
    test("fall_back_never_formal",
         lambda:reconcile_three(x,y,z,"2330.TW","20261013","20261014",113,114)
         ["FormalEligible"] is False)
    test("selected_prev_evening_adjusted_not_synthetic",
         lambda:reconcile_three(x,y,z,"2330.TW","20261013","20261014",113,114)
         ["SelectedDayAdjustedClose"]==114)
    a,b,c=generate(morning_missing=False)
    test("morning_direct_preferred",
         lambda:reconcile_three(a,b,c,"2330.TW","20261013","20261014",113,114)
         ["SelectedSourceRole"]=="MORNING_DIRECT_VERIFIED")
    a,b,c=generate(prev="20261021",current="20261022")
    test("dynamic_not_pinned_oct14",
         lambda:reconcile_three(a,b,c,"2330.TW","20261021","20261022",113,114)
         ["EveningSourceRawSHA256"]==hashlib.sha256(b).hexdigest())
    test("reject_wrong_prev_official",lambda:reconcile_three(x,y,z,"2330.TW","20261013","20261014",120,114),True)
    test("reject_wrong_current_official",lambda:reconcile_three(x,y,z,"2330.TW","20261013","20261014",113,110),True)
    def patch(raw,f):
        o=json.loads(raw);f(o);return json.dumps(o).encode()
    test("reject_morning_raw_history_conflict",
         lambda:reconcile_three(x,y,patch(z,lambda d:d["chart"]["result"][0]
         ["indicators"]["quote"][0]["close"].__setitem__(0,999)),
         "2330.TW","20261013","20261014",113,114),True)
    test("reject_vendor_symbol_change",
         lambda:reconcile_three(x,y,patch(z,lambda d:d["chart"]["result"][0]
         ["meta"].update(symbol="0000.TW")),
         "2330.TW","20261013","20261014",113,114),True)
    test("reject_adjusted_array_removed",
         lambda:reconcile_three(x,y,patch(z,lambda d:d["chart"]["result"][0]
         ["indicators"].pop("adjclose")),
         "2330.TW","20261013","20261014",113,114),True)
    test("reject_bad_current_evening_bar",
         lambda:reconcile_three(x,patch(y,lambda d:d["chart"]["result"][0]
         ["indicators"]["adjclose"][0]["adjclose"].__setitem__(-1,None)),
         z,"2330.TW","20261013","20261014",113,114),True)
    prev={"dates":{"target_date":"2026-10-13","price_cutoff":"20261012"}}
    eve={"dates":{"target_date":"2026-10-14","price_cutoff":"20261013","previous_session":"20261012"}}
    morn=copy.deepcopy(eve)
    test("valid_three_receipt_dates",
         lambda:dates_from_receipts(prev,eve,morn)==("20261012","20261013",dt.date(2026,10,14)))
    test("reject_morning_target_date_drift",
         lambda:dates_from_receipts(prev,eve,{"dates":{"target_date":"2026-10-15",
           "price_cutoff":"20261013","previous_session":"20261012"}}),True)
    test("reject_prior_old_wrong_cutoff",
         lambda:dates_from_receipts({"dates":{"target_date":"2026-10-13",
              "price_cutoff":"20261010"}},eve,morn),True)
    status="PASS" if all(checks.values()) and len(checks)==15 else "FAIL"
    return {"status":status,"total":len(checks),"passed":sum(checks.values()),
           "scope":"PURE_SYNTHETIC_GENERIC_MARKET_DATES_NO_FORMAL_NATURAL",
           "checks":checks}

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--self-test",action="store_true")
    a.add_argument("--prior-dir");a.add_argument("--evening-dir")
    a.add_argument("--morning-dir");a.add_argument("--out")
    v=a.parse_args()
    if v.self_test:
        x=selftest();print(json.dumps(x,ensure_ascii=False))
        return 0 if x["status"]=="PASS" else 2
    if not all((v.prior_dir,v.evening_dir,v.morning_dir,v.out)):
        a.error("prior-dir/evening-dir/morning-dir/out required")
    return run(v.prior_dir,v.evening_dir,v.morning_dir,v.out)

if __name__=="__main__":
    raise SystemExit(main())
