#!/usr/bin/env python3
"""Stock source-only REPORT continuity, not a model/formal/cash/natural bridge.

Runs independently of the strict 68/68 single-provider source gate. An honest
full source-status report should survive that gate's failure. Validates the
original collector's per-symbol fallback, optionally cross-checks a separate
three-original research replay, and freezes an actual human-readable report
with exact SHA readback. No Google/ChatGPT writes or message-delivery claims.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import sys

CODE = re.compile(r"^[0-9A-Z]{4,8}$")
HEX = re.compile(r"^[0-9a-f]{64}$")
SRC_OK = "RESEARCH_SOURCE_ONLY_READY"
STATUS = ("RESEARCH_68_WITH_3_ORIGINAL_RECONCILIATION",
          "RESEARCH_PARTIAL_WITH_FULL_SYMBOL_ROSTER",
          "REPORT_HOLD_NO_VALID_INPUT")
EXPECTED = 68

def digest(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def h64(x):
    return isinstance(x,str) and bool(HEX.fullmatch(x))

def positive(x):
    return type(x) in (int,float) and math.isfinite(x) and x>0

def safe(x):
    return str(x if x is not None else "MISSING").replace("|","\\|").replace("\n"," ").replace("\r"," ")

def invalid(reason):
    return ValueError(reason)

def validate_partial(a):
    if not isinstance(a,dict):
        raise invalid("PARTIAL_NOT_OBJECT")
    if a.get("FormalEligible") is not False or a.get("NaturalCredit")!=0 or a.get("OOSCredit")!=0:
        raise invalid("PARTIAL_FALSE_PRODUCTION_CREDIT")
    if a.get("FullOriginalH9Qualified") is not False:
        raise invalid("PARTIAL_FALSE_H9_QUALIFICATION")
    target,source=a.get("TargetDate"),a.get("SourceDate")
    try:
        t=dt.date.fromisoformat(target)
        s=dt.date.fromisoformat(source)
    except (TypeError,ValueError):
        raise invalid("DATE_FIELDS_INVALID")
    if not s<t or (t-s).days>8:
        raise invalid("SOURCE_DATE_NOT_PRIOR_SESSION")
    rows=a.get("Rows")
    if not isinstance(rows,list) or len(rows)!=EXPECTED or a.get("TotalSymbols")!=EXPECTED:
        raise invalid("FULL_68_ROSTER_NOT_PRESERVED")
    out=[]
    ids=set()
    source_count=official_count=0
    for z in rows:
        if not isinstance(z,dict):
            raise invalid("ROW_NOT_OBJECT")
        sym=z.get("Symbol")
        if not isinstance(sym,str) or not CODE.fullmatch(sym) or sym in ids:
            raise invalid("DUPLICATE_OR_INVALID_SYMBOL")
        ids.add(sym)
        if z.get("FormalEligible") is not False or z.get("NaturalCredit")!=0 or z.get("OOSCredit")!=0:
            raise invalid("ROW_FALSE_PRODUCTION_CREDIT")
        if z.get("ModelPrediction") is not None:
            raise invalid("STOCK_MODEL_NUMBER_LEAKED_IN_SOURCE_REPORT")
        name=z.get("Name")
        close=z.get("OfficialClose")
        state=z.get("SourceStatus")
        if not isinstance(state,str) or not state:
            raise invalid("SOURCE_STATE_UNDEFINED")
        valid_official=positive(close)
        if valid_official:
            if not isinstance(name,str) or not name.strip() or not h64(z.get("OfficialRawSHA256")):
                raise invalid("OFFICIAL_NAME_OR_RAW_SHA_MISSING")
            official_count+=1
        elif close is not None:
            raise invalid("INVALID_OFFICIAL_CLOSE_MUST_BE_NULL")
        if state==SRC_OK:
            if not valid_official or not h64(z.get("ProviderSHA256")):
                raise invalid("READY_WITHOUT_VENDOR_OR_OFFICIAL_SHA")
            source_count+=1
        elif not isinstance(z.get("MissingReason"),str) or not z.get("MissingReason").strip():
            raise invalid("HOLD_MISSING_REASON")
        out.append({"Symbol":sym,"Name":name if valid_official else "MISSING",
                    "OfficialClose":close,"SourceStatus":state,
                    "Reason":z.get("MissingReason") or "",
                    "OfficialRawSHA256":z.get("OfficialRawSHA256") if valid_official else None,
                    "ProviderRawSHA256":z.get("ProviderSHA256") if state==SRC_OK else None})
    if (a.get("OfficialPriorCloseCount")!=official_count or
        a.get("IndependentAdjustedSourceCount")!=source_count or
        a.get("SourceHolds")!=EXPECTED-source_count):
        raise invalid("SOURCE_COHORT_COUNTS_MISMATCH")
    if not isinstance(a.get("SourceReceiptSHA256"),str) or not h64(a.get("SourceReceiptSHA256")):
        raise invalid("SOURCE_RECEIPT_SHA_MISSING")
    return {"TargetDate":target,"SourceDate":source,"Rows":out,
            "OfficialPriorCloseCount":official_count,
            "SingleOriginalResearchReadyCount":source_count,
            "SourceHolds":EXPECTED-source_count}

def reconcile_triple(p,triple):
    """Optional corroboration, never overrides primary source gate."""
    if triple is None:return {"status":"NOT_PRESENT","Direct":0,"Fallback":0}
    if not isinstance(triple,dict):
        return {"status":"TRIPLE_INVALID_NOT_USED","reason":"NOT_OBJECT","Direct":0,"Fallback":0}
    try:
        triple_day=triple.get("TargetSession")
        if isinstance(triple_day,str) and re.fullmatch(r"\\d{8}",triple_day):
            triple_day=dt.datetime.strptime(triple_day,"%Y%m%d").date().isoformat()
        if triple_day!=p["TargetDate"]:
            raise invalid("TRIPLE_TARGET_MISMATCH")
        if triple.get("FormalEligible") is not False or triple.get("NaturalCredit")!=0 or triple.get("OOSCredit")!=0:
            raise invalid("TRIPLE_FALSE_FORMAL_CREDIT")
        if triple.get("CanonicalPredictionWritten") is not False or triple.get("NeverTreatThreeFilesAsOneProviderOriginal") is not True:
            raise invalid("TRIPLE_MERGED_OR_PROMOTED_SOURCE")
        rows=triple.get("Rows")
        if not isinstance(rows,list) or len(rows)!=EXPECTED or triple.get("EligibleResearchRows")!=EXPECTED or triple.get("ResearchHolds")!=0:
            raise invalid("TRIPLE_NOT_68_VERIFIED")
        idx={z["Symbol"]:z for z in p["Rows"]}
        seen=set()
        direct=backup=0
        for z in rows:
            sym=z.get("Symbol")
            if sym in seen or sym not in idx:
                raise invalid("TRIPLE_DUPLICATE_OR_UNKNOWN_SYMBOL")
            seen.add(sym)
            official=z.get("CurrentOfficialClose")
            if not positive(official) or not positive(idx[sym]["OfficialClose"]):
                raise invalid("TRIPLE_OR_PARTIAL_OFFICIAL_NOT_POSITIVE")
            if abs(official-idx[sym]["OfficialClose"])>max(.011,official*.00002):
                raise invalid("TRIPLE_OFFICIAL_CLOSE_CONFLICT")
            if z.get("OfficialName")!=idx[sym]["Name"]:
                raise invalid("TRIPLE_OFFICIAL_NAME_CONFLICT")
            if z.get("FormalEligible") is not False or z.get("NaturalCredit")!=0 or z.get("OOSCredit")!=0:
                raise invalid("TRIPLE_ROW_FALSE_PRODUCTION")
            if z.get("RecoveryStatus")!="THREE_ORIGINALS_RESEARCH_MATCH":
                raise invalid("TRIPLE_HOLD_PRESENT")
            role=z.get("SelectedSourceRole")
            if role=="MORNING_DIRECT_VERIFIED":direct+=1
            elif role=="EVENING_ORIGINAL_RESEARCH_FALLBACK":backup+=1
            else:raise invalid("TRIPLE_SOURCE_ROLE_INVALID")
            if not all(h64(z.get(key)) for key in ("PriorSourceRawSHA256","EveningSourceRawSHA256","MorningSourceRawSHA256")):
                raise invalid("TRIPLE_MISSING_PARENT_SHA")
        if direct+backup!=EXPECTED or triple.get("MorningDirect")!=direct or triple.get("EveningFallback")!=backup:
            raise invalid("TRIPLE_ROLE_COUNTS_CONFLICT")
        return {"status":"TRIPLE_VERIFIED_INDEPENDENT_REPORT","Direct":direct,"Fallback":backup}
    except (ValueError,TypeError,KeyError) as exc:
        return {"status":"TRIPLE_QUARANTINED_PRIMARY_FALLBACK_RETAINED",
                "reason":str(exc)[:180],"Direct":0,"Fallback":0}

def summarize(partial,triple,trigger="UNKNOWN"):
    if trigger not in ("schedule","workflow_run","workflow_dispatch","push","UNKNOWN"):
        trigger="UNKNOWN"
    try:
        p=validate_partial(partial)
        tr=reconcile_triple(p,triple)
        state=STATUS[0] if tr["status"]=="TRIPLE_VERIFIED_INDEPENDENT_REPORT" else STATUS[1]
        result={"Status":state,"TargetDate":p["TargetDate"],"SourceDate":p["SourceDate"],
                "OfficialPriorCloseCount":p["OfficialPriorCloseCount"],
                "SingleOriginalResearchReadyCount":p["SingleOriginalResearchReadyCount"],
                "SourceHolds":p["SourceHolds"],"TripleResearch":tr,"Rows":p["Rows"],"RosterCount":EXPECTED,
                "OriginalResearchOnly":True,"FormalEligible":False,
                "NaturalCredit":0,"OOSCredit":0,"NativeChatReportDelivered":False,
                "ExecutableShares":0,"BrokersCashVerified":False,"TriggerClass":trigger}
    except (ValueError,TypeError,KeyError,IndexError) as exc:
        result={"Status":STATUS[2],"Reason":str(exc)[:180],"RosterCount":0,"Rows":[],
                "OfficialPriorCloseCount":0,"SingleOriginalResearchReadyCount":0,
                "SourceHolds":EXPECTED,"TripleResearch":{"status":"NOT_USED"},
                "OriginalResearchOnly":True,"FormalEligible":False,
                "NaturalCredit":0,"OOSCredit":0,"NativeChatReportDelivered":False,
                "ExecutableShares":0,"BrokersCashVerified":False,"TriggerClass":trigger}
    return result

def markdown(x):
    lines=["# 台股資料來源交付連續性｜獨立研究報告",
           "","**研究資料，不是正式股價預測或可下單建議。**",
           "","目標交易日："+safe(x.get("TargetDate","尚未核實"))+
           "；前收交易日："+safe(x.get("SourceDate","尚未核實"))+
           "；GitHub觸發："+safe(x["TriggerClass"]),
           "資料可驗證：官方前收 "+str(x["OfficialPriorCloseCount"])+"/68、"
           "當次調整價 "+str(x["SingleOriginalResearchReadyCount"])+"/68、"
           "缺來源 "+str(x["SourceHolds"])+" 檔。",
           "分離三原件研究："+safe(x["TripleResearch"].get("status"))+
           "；直接 "+str(x["TripleResearch"].get("Direct",0))+
           "、前晚獨立備援 "+str(x["TripleResearch"].get("Fallback",0))+".",
           "正式來源 Gate、正式模型、Natural、OOS、現金與實際送達均未因本報告放行。",
           "報告生成／GitHub Artifact 保存／ChatGPT對話顯示／平台MessageReference是四個獨立層級。",
           ""]
    if x["Rows"]:
        lines+=["| 代號 | 官方名稱 | 官方前收 | 單一來源判定 | 未合格原因 |",
                "|---|---|---:|---|---|"]
        for r in x["Rows"]:
            v=r["OfficialClose"]
            price=f"{v:,.2f}" if positive(v) else "MISSING"
            lines.append("| "+" | ".join((safe(r["Symbol"]),safe(r["Name"]),price,
                         safe(r["SourceStatus"]),safe(r["Reason"])))+" |")
    else:
        lines.append("未取得完整合格收據；本次逐檔內容不可驗證："+safe(x.get("Reason")))
    lines+=["","**下一步：** 將此報告原件SHA/保存收據接入既有19:00結算工作者；"
            "不能用檔案存在代替對話送達。",""]
    return "\n".join(lines)

def persist(result,outdir):
    out=pathlib.Path(outdir)
    out.mkdir(parents=True,exist_ok=True)
    j=out/"source_delivery_report.json"
    md=out/"source_delivery_report.md"
    raw=json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    rendered=markdown(result)
    j.write_text(raw,encoding="utf8")
    md.write_text(rendered,encoding="utf8")
    if j.read_bytes()!=raw.encode("utf8") or md.read_bytes()!=rendered.encode("utf8"):
        raise RuntimeError("REPORT_RAW_READBACK_MISMATCH")
    receipt={"Status":result["Status"],"TargetDate":result.get("TargetDate"),
             "ReportJsonSHA256":digest(j.read_bytes()),"ReportMarkdownSHA256":digest(md.read_bytes()),
             "MarkdownBytes":len(md.read_bytes()),"Rows":len(result["Rows"]),
             "GitHubFileWriteReadback":"PASS","NativeChatReportDelivered":False,
             "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0}
    rp=out/"source_delivery_receipt.json"
    b=json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False)+"\n"
    rp.write_text(b,encoding="utf8")
    if rp.read_bytes()!=b.encode("utf8"):
        raise RuntimeError("RECEIPT_READBACK_FAILED")
    return receipt

def selftest():
    good=[]
    for i in range(EXPECTED):
        sym=str(1001+i)
        good.append({"Symbol":sym,"Name":"示例"+sym,"OfficialClose":100+i,
                     "SourceStatus":SRC_OK if i<65 else "OFFICIAL_CLOSE_ONLY_HOLD_ADJUSTED",
                     "MissingReason":None if i<65 else "PROVIDER_MISSING_FINITE_PRIOR_ADJCLOSE",
                     "OfficialRawSHA256":"a"*64,"ProviderSHA256":"b"*64 if i<65 else None,
                     "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,"ModelPrediction":None})
    base={"Status":"PARTIAL_RESEARCH_SOURCE_FALLBACK","TargetDate":"2026-10-15",
          "SourceDate":"2026-10-14","TotalSymbols":68,"Rows":good,
          "OfficialPriorCloseCount":68,"IndependentAdjustedSourceCount":65,
          "SourceHolds":3,"SourceReceiptSHA256":"c"*64,"FormalEligible":False,
          "FullOriginalH9Qualified":False,"NaturalCredit":0,"OOSCredit":0}
    tri={"TargetSession":"2026-10-15","EligibleResearchRows":68,"ResearchHolds":0,
         "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
         "CanonicalPredictionWritten":False,"NeverTreatThreeFilesAsOneProviderOriginal":True,
         "MorningDirect":65,"EveningFallback":3,"Rows":[
           {"Symbol":z["Symbol"],"OfficialName":z["Name"],
            "CurrentOfficialClose":z["OfficialClose"],
            "RecoveryStatus":"THREE_ORIGINALS_RESEARCH_MATCH",
            "SelectedSourceRole":"MORNING_DIRECT_VERIFIED" if i<65 else "EVENING_ORIGINAL_RESEARCH_FALLBACK",
            "PriorSourceRawSHA256":"d"*64,"EveningSourceRawSHA256":"e"*64,"MorningSourceRawSHA256":"f"*64,
            "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0} for i,z in enumerate(good)]}
    import copy,tempfile
    tests={}
    def tc(name,alter=None,expect="REPORT_HOLD_NO_VALID_INPUT",triple=False):
        x,y=copy.deepcopy(base),copy.deepcopy(tri) if triple else None
        if alter:alter(x,y)
        z=summarize(x,y,"schedule")
        tests[name]=(z["Status"]==expect and z["NativeChatReportDelivered"] is False
                    and z["NaturalCredit"]==0 and z["OOSCredit"]==0)
    tc("valid65_partial68",expect=STATUS[1])
    tc("valid_triple68",expect=STATUS[0],triple=True)
    tc("duplicate_symbol",lambda x,y:x["Rows"][1].update(Symbol=x["Rows"][0]["Symbol"]))
    tc("wrong_source_count",lambda x,y:x.update(SourceHolds=0))
    tc("wrong_official_count",lambda x,y:x.update(OfficialPriorCloseCount=67))
    tc("no_official_sha",lambda x,y:x["Rows"][0].update(OfficialRawSHA256="BAD"))
    tc("vendor_sha_missing",lambda x,y:x["Rows"][0].update(ProviderSHA256=None))
    tc("no_hold_reason",lambda x,y:x["Rows"][-1].update(MissingReason=None))
    tc("row_formal",lambda x,y:x["Rows"][0].update(FormalEligible=True))
    tc("false_prediction",lambda x,y:x["Rows"][0].update(ModelPrediction=101))
    tc("top_natural",lambda x,y:x.update(NaturalCredit=1))
    tc("top_fullH9",lambda x,y:x.update(FullOriginalH9Qualified=True))
    tc("invalid_date",lambda x,y:x.update(TargetDate="foo"))
    tc("wrong_target",lambda x,y:x.update(TargetDate="2026-10-14"))
    tc("short_roster",lambda x,y:x["Rows"].pop())
    tc("nonpositive_official",lambda x,y:x["Rows"][0].update(OfficialClose=-1))
    tc("triple_official_conflict",lambda x,y:y["Rows"][0].update(CurrentOfficialClose=999),
       expect=STATUS[1],triple=True)
    tc("triple_name_conflict",lambda x,y:y["Rows"][0].update(OfficialName="錯誤名稱"),
       expect=STATUS[1],triple=True)
    tc("triple_false_natural",lambda x,y:y.update(NaturalCredit=1),
       expect=STATUS[1],triple=True)
    tc("triple_no_sha",lambda x,y:y["Rows"][0].update(PriorSourceRawSHA256="BAD"),
       expect=STATUS[1],triple=True)
    with tempfile.TemporaryDirectory() as td:
        z=summarize(base,tri,"workflow_run")
        receipt=persist(z,td)
        tests["report_exact_bytes_and_68_rows"]=(receipt["Rows"]==68 and
            receipt["GitHubFileWriteReadback"]=="PASS" and receipt["MarkdownBytes"]>1000)
        tests["no_message_fake"]=receipt["NativeChatReportDelivered"] is False
        tests["user_visible_68_names"]=all(x["Name"] in markdown(z) for x in z["Rows"])
    ok=all(tests.values())
    return {"status":"PASS" if ok else "FAIL","total":len(tests),
            "passed":sum(tests.values()),"tests":tests,
            "scope":"SYNTHETIC_REPORT_ONLY_NO_FORMAL_NO_NATURAL_NO_PLATFORM_DELIVERY"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--partial")
    p.add_argument("--triple")
    p.add_argument("--out")
    p.add_argument("--trigger",default="UNKNOWN")
    x=p.parse_args()
    if x.self_test:
        report=selftest()
        print(json.dumps(report,ensure_ascii=False))
        return 0 if report["status"]=="PASS" else 1
    if not x.out:p.error("--out required")
    partial=triple=None
    try:
        if x.partial:partial=json.loads(pathlib.Path(x.partial).read_bytes())
    except (ValueError,OSError,TypeError) as exc:
        partial={"Status":"INPUT_READ_ERROR","error":str(exc)[:180]}
    try:
        if x.triple and pathlib.Path(x.triple).is_file():
            triple=json.loads(pathlib.Path(x.triple).read_bytes())
    except (ValueError,OSError,TypeError):
        triple={"Status":"TRIPLE_INVALID"}
    result=summarize(partial,triple,x.trigger)
    receipt=persist(result,x.out)
    print(json.dumps({"report_status":result["Status"],
                      "rows":len(result["Rows"]),
                      "official":result["OfficialPriorCloseCount"],
                      "direct":result["SingleOriginalResearchReadyCount"],
                      "three_orig":result["TripleResearch"]["status"],
                      "ReportSHA":receipt["ReportMarkdownSHA256"],
                      "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
                      "NativeChatReportDelivered":False},ensure_ascii=False))
    return 0  # REPORT can be HOLD; strict 68 source gate remains a separate step.

if __name__=="__main__":
    raise SystemExit(main())
