#!/usr/bin/env python3
"""Fail-closed research training gap gate. Does not write formal Google Sheets.
Input is a SHA-verifiable JSON snapshot containing sheet rows, not credentials.
Do not reinterpret research-only rows as Formal/Natural/OOS PASS.
"""
import argparse
import datetime as dt
import json

REQUIRED=("STOCK_Run_Config","STOCK_HistoryGap_20261017",
          "STOCK_EventResolved_20261017","STOCK_ETF_OriginalRecovery_20261017",
          "STOCK_Stock_Horizon_Performance")

def audit(snapshot, target):
    if not isinstance(snapshot,dict) or any(k not in snapshot for k in REQUIRED):
        return {"verdict":"BLOCK","error":"INCOMPLETE_NATIVE_SNAPSHOT"}
    try:
        # Date must be an exact canonical calendar date, not a permissive ISO variant.
        if not isinstance(target,str) or len(target)!=10 or dt.date.fromisoformat(target).isoformat()!=target:
            raise ValueError("INVALID_CANONICAL_TARGET_DATE")
        sheets={k:v for k,v in snapshot.items() if k in REQUIRED}
        if any(not isinstance(v,list) or len(v)<2 for v in sheets.values()):
            raise ValueError("EMPTY_REQUIRED_SHEET")
        configs=sheets[REQUIRED[0]]
        if configs[0][:3]!=["TargetDate","ConfigID","Status"]:
            raise ValueError("UNEXPECTED_CONFIG_SCHEMA")
        if any(not isinstance(r,list) or len(r)<3 for r in configs[1:]):
            raise ValueError("MALFORMED_CONFIG_ROW")
        target_rows=[r for r in configs[1:] if r[0]==target]
        config_pass=(len(target_rows)==1 and len(target_rows[0])>=24 and target_rows[0][2]=="PRESEALED" and isinstance(target_rows[0][19],str) and len(target_rows[0][19])==64)
        hist=sheets[REQUIRED[1]]
        if hist[0][0]!="Symbol" or hist[0][5]!="ProviderAdjusted":
            raise ValueError("UNEXPECTED_HISTORY_SCHEMA")
        history_missing=sum(1 for r in hist[1:] if len(r)<12 or not r[5])
        prelisting=sum(1 for r in hist[1:] if len(r)>11 and r[11]=="PRELISTING_MEAN_NOT_CLOSE")
        events=sheets[REQUIRED[2]]
        if events[0][0]!="EventKey" or events[0][7]!="VendorConflict":
            raise ValueError("UNEXPECTED_EVENT_SCHEMA")
        conflicts=sum(1 for r in events[1:] if len(r)<9 or r[7]!="NO")
        etfs=sheets[REQUIRED[3]]
        if etfs[0][0]!="Symbol" or etfs[0][13]!="FormalEligible":
            raise ValueError("UNEXPECTED_ETF_SCHEMA")
        etf_block=sum(1 for r in etfs[1:] if len(r)<14 or r[13]!="YES")
        perf=sheets[REQUIRED[4]]
        if perf[0][20:23]!=["FormalProspectiveDayCount","NaturalProspectiveDayCount","OOSGovernanceDayCount"]:
            raise ValueError("UNEXPECTED_PERFORMANCE_SCHEMA")
        invalid_governance=sum(1 for r in perf[1:] if len(r)<23 or any(
            str(r[j]).strip() not in ("","0") for j in (20,21,22)))
        # Optional same-snapshot performance controls: missing controls stay
        # unverified rather than being silently called PASS.
        projection=snapshot.get("STOCK_HorizonPerf_Canonical28_Readonly_20261016")
        expected=snapshot.get("STOCK_Performance_Expected")
        projection_mismatch=None
        coverage_fail=None
        if projection is not None:
            if not isinstance(projection,list) or len(projection)!=len(perf):
                projection_mismatch=len(perf)
            else:
                projection_mismatch=sum(
                    1 for i,row in enumerate(perf)
                    if row[:28]!=projection[i]
                )
        if expected is not None:
            if (not isinstance(expected,list) or len(expected)<2
                    or len(expected[0])<8
                    or expected[0][7]!="CoverageGuard"):
                coverage_fail="INVALID_EXPECTED_SCHEMA"
            else:
                coverage_fail=sum(1 for row in expected[1:]
                                  if len(row)<8 or row[7]!="PASS")
        holds=[]
        if projection_mismatch is None or coverage_fail is None:
            holds.append("PERFORMANCE_READBACK_COMPARISON_NOT_VERIFIED")
        elif projection_mismatch or coverage_fail:
            holds.append("PERFORMANCE_READBACK_DRIFT")
        if not config_pass: holds.append("TARGET_CONFIG_NOT_UNIQUELY_PRESEALED")
        if history_missing: holds.append("HISTORY_PROVIDER_ADJUSTED_MISSING")
        if conflicts: holds.append("ISSUER_VENDOR_CONFLICT_OPEN")
        if etf_block: holds.append("ETF_FORMAL_BASIS_NOT_APPROVED")
        # Independent formal evidence is not in this snapshot; never grant formal pass.
        holds.append("FORMAL_AUTHORITY_AND_RAW_SHA_INDEPENDENT_GATE_REQUIRED")
        if invalid_governance: holds.append("UNVERIFIED_GOVERNANCE_CREDITS_PRESENT")
        return {"verdict":"BLOCK","target":target,"config_rows":len(target_rows),
                "config_presealed":config_pass,"history_missing":history_missing,
                "prelisting_cases":prelisting,"issuer_conflicts":conflicts,
                "etf_formal_blocked":etf_block,"governance_nonzero":invalid_governance,
                "projection_mismatch":projection_mismatch,"expected_guard_fail":coverage_fail,
                "holds":holds,"formal_credit":0,"natural_credit":0,"oos_credit":0}
    except (ValueError,TypeError,IndexError,KeyError) as exc:
        return {"verdict":"BLOCK","error":str(exc),"formal_credit":0,
                "natural_credit":0,"oos_credit":0}

def selftest():
    h=["Symbol","","","","","ProviderAdjusted"]+[""]*10
    e=["EventKey"]+[""]*6+["VendorConflict"]+[""]*5
    t=["Symbol"]+[""]*12+["FormalEligible"]+[""]*2
    p=[""]*20+["FormalProspectiveDayCount","NaturalProspectiveDayCount","OOSGovernanceDayCount"]
    s={"STOCK_Run_Config":[["TargetDate","ConfigID","Status"],["2026-10-21","id","PRESEALED"]],
       "STOCK_HistoryGap_20261017":[h,["4585","","","","",""]+[""]*5+["PRELISTING_MEAN_NOT_CLOSE"]],
       "STOCK_EventResolved_20261017":[e,["event"]+[""]*6+["YES"]+[""]*5],
       "STOCK_ETF_OriginalRecovery_20261017":[t,["0050"]+[""]*12+["NO"]+[""]*2],
       "STOCK_Stock_Horizon_Performance":[p,[""]*20+["0","0","0"]]}
    a=audit(s,"2026-10-22")
    assert a["verdict"]=="BLOCK" and a["config_rows"]==0
    assert (a["history_missing"],a["prelisting_cases"],a["issuer_conflicts"],a["etf_formal_blocked"])==(1,1,1,1)
    assert (a["formal_credit"],a["natural_credit"],a["oos_credit"])==(0,0,0)
    s["STOCK_Run_Config"].append(["2026-10-22","id2","PRESEALED"])
    assert audit(s,"2026-10-22")["config_presealed"] is False
    s["STOCK_Run_Config"][-1].extend([""]*16 + ["a"*64] + [""]*4)
    assert audit(s,"2026-10-22")["config_presealed"] is True
    s["STOCK_Run_Config"].append(["2026-10-22","duplicate","PRESEALED"])
    assert audit(s,"2026-10-22")["config_presealed"] is False
    s["STOCK_EventResolved_20261017"][1][7]="UNKNOWN"
    assert audit(s,"2026-10-22")["issuer_conflicts"]==1
    s["STOCK_EventResolved_20261017"][1][7]="NO"
    assert audit(s,"2026-10-22")["issuer_conflicts"]==0
    assert audit(s,"2026-2-2")["error"]=="INVALID_CANONICAL_TARGET_DATE"
    s["STOCK_Run_Config"].append(["2026-10-22"])
    assert audit(s,"2026-10-22")["error"]=="MALFORMED_CONFIG_ROW"
    s["STOCK_Run_Config"].pop()
    del s["STOCK_EventResolved_20261017"]
    assert audit(s,"2026-10-22")["error"]=="INCOMPLETE_NATIVE_SNAPSHOT"
    s["STOCK_EventResolved_20261017"]=[e,["event"]+[""]*6+["NO"]+[""]*5]
    s["STOCK_HorizonPerf_Canonical28_Readonly_20261016"]=[p,s["STOCK_Stock_Horizon_Performance"][1][:28]]
    s["STOCK_Performance_Expected"]=[[""]*7+["CoverageGuard"],[""]*7+["PASS"]]
    assert audit(s,"2026-10-22")["projection_mismatch"]==0
    assert audit(s,"2026-10-22")["expected_guard_fail"]==0
    s["STOCK_HorizonPerf_Canonical28_Readonly_20261016"][1][1]="DRIFT"
    assert audit(s,"2026-10-22")["projection_mismatch"]==1
    assert "PERFORMANCE_READBACK_DRIFT" in audit(s,"2026-10-22")["holds"]
    s["STOCK_Performance_Expected"][1][7]="FAIL"
    assert audit(s,"2026-10-22")["expected_guard_fail"]==1
    print(json.dumps({"selftest":"PASS","checks":15,"formal_credit":0}))

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--input")
    ap.add_argument("--target")
    args=ap.parse_args()
    if args.self_test:selftest()
    else:
        if not args.input or not args.target:ap.error("--input and --target required")
        with open(args.input,encoding="utf-8") as f: payload=json.load(f)
        print(json.dumps(audit(payload,args.target),ensure_ascii=False,sort_keys=True))
