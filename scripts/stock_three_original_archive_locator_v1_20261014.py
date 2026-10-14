#!/usr/bin/env python3
"""Date-generic archived original-source artifact locator for stock RESEARCH.

Locate prior day's authentic public input artifact and current day's independent
evening source capture before preopen, using only immutable GH metadata.
Actual original bytes, receipt SHA, ticker identity and exact trading days
MUST be reverified after download by generic_three_original_research. This
script never treats GitHub artifact metadata alone as source qualification,
nor modifies live model, Config, Cash, Natural or OOS.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import urllib.request

from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Taipei")
DATE8=re.compile(r"^[0-9]{8}$")
RUN_ID=re.compile(r"^[0-9]{7,20}$")

def clock(x):
    try:
        t=dt.datetime.fromisoformat(str(x).replace("Z","+00:00"))
    except (ValueError,TypeError):
        return None
    return t.astimezone(TZ) if t.tzinfo else None

def parse_meta(receipt):
    try:
        dates=receipt["dates"]
        prev=dates["previous_session"]
        cur=dates["price_cutoff"]
        target=dt.date.fromisoformat(dates["target_date"])
        if not DATE8.fullmatch(prev) or not DATE8.fullmatch(cur):
            raise ValueError("DATE8_INVALID")
        prior=dt.datetime.strptime(prev,"%Y%m%d").date()
        current=dt.datetime.strptime(cur,"%Y%m%d").date()
        if not prior<current<target or (target-current).days>8 or (current-prior).days>8:
            raise ValueError("SOURCE_SESSION_ORDER")
        started=clock(receipt["started_at"])
        if started is None:
            raise ValueError("SOURCE_RECEIPT_START_TIME_UNKNOWN")
        if started>dt.datetime.combine(target,dt.time(8,9,30),TZ):
            raise ValueError("SOURCE_AFTER_080930_CUTOFF")
        return prior,current,target,started
    except (KeyError,ValueError,TypeError,AttributeError):
        raise ValueError("ORIGINAL_CURRENT_SOURCE_RECEIPT_NOT_VERIFIED")

def selection(receipt,artifacts,current_run_id):
    if not isinstance(artifacts,list):
        return {"Status":"HOLD_BAD_ARTIFACT_LIST","Reason":"NOT_LIST",
                "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0}
    try:
        prior,cur,target,started=parse_meta(receipt)
        current_run_id=str(current_run_id)
        if not RUN_ID.fullmatch(current_run_id):
            raise ValueError("RUN_ID_NOT_NUMERIC")
    except (ValueError,KeyError,TypeError) as e:
        return {"Status":"HOLD_BAD_SOURCE_META","Reason":str(e)[:130],
                "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0}
    first=dt.datetime.combine(prior,dt.time(0),TZ)
    end_prev=dt.datetime.combine(cur,dt.time(19),TZ)
    evening_start=end_prev
    previous_candidates=[]
    evening_candidates=[]
    for art in artifacts:
        if not isinstance(art,dict) or art.get("expired") is not False:
            continue
        name=art.get("name")
        when=clock(art.get("created_at"))
        rid=str((art.get("workflow_run") or {}).get("id") or "")
        if not isinstance(name,str) or when is None or not RUN_ID.fullmatch(rid):
            continue
        if rid==current_run_id:
            continue
        if (name.startswith(f"stock-public-input-{cur:%Y%m%d}-") and
            re.fullmatch(rf"stock-public-input-{cur:%Y%m%d}-{rid}-[0-9]+",name) and
            first<=when<end_prev):
            previous_candidates.append((when,int(rid),name))
        if (name==f"stock-next-session-68-source-raw-{rid}" and
            evening_start<=when<started):
            evening_candidates.append((when,int(rid),name))
    # Prefer closest complete-source artifact; all candidates are still
    # unauthenticated until raw acquisition_receipt + per-file SHA revalidation.
    previous_candidates.sort(reverse=True)
    evening_candidates.sort(reverse=True)
    a=previous_candidates[0] if previous_candidates else None
    b=evening_candidates[0] if evening_candidates else None
    ok=bool(a and b)
    return {"Status":"ARTIFACT_METADATA_CANDIDATES_ONLY_NOT_SOURCE_QUALIFIED" if ok
            else "ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD",
            "TargetDate":target.isoformat(),"PreviousSession":prior.strftime("%Y%m%d"),
            "CurrentSession":cur.strftime("%Y%m%d"),
            "PriorPublicInputRunID":str(a[1]) if a else None,
            "PriorPublicInputArtifact":a[2] if a else None,
            "EveningRunID":str(b[1]) if b else None,
            "EveningArtifact":b[2] if b else None,
            "CandidateResearchEligible":ok,"RawSourceVerified":False,
            "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
            "NativePredictionWritten":False}

def get_latest(repo,token,maxpages):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo) or not token:
        raise ValueError("GH_IDENTITY_OR_TOKEN_UNAVAILABLE")
    out=[]
    for page in range(1,maxpages+1):
        url=f"https://api.github.com/repos/{repo}/actions/artifacts?per_page=100&page={page}"
        req=urllib.request.Request(url,headers={
            "Authorization":"Bearer "+token,
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"stock-three-original-research-only"})
        with urllib.request.urlopen(req,timeout=20) as resp:
            body=json.loads(resp.read())
        group=body.get("artifacts",[])
        if not isinstance(group,list):
            raise ValueError("INVALID_GITHUB_ARTIFACTS_RESPONSE")
        out.extend(group)
        if len(group)<100:
            break
    return out

def selftest():
    original={
      "dates":{"target_date":"2026-10-14","price_cutoff":"20261013",
               "previous_session":"20261012"},
      "started_at":"2026-10-14T07:21:00+08:00"}
    art=[
       {"name":"stock-public-input-20261013-38265016756-1",
        "workflow_run":{"id":38265016756},"created_at":"2026-10-12T16:01:00+08:00",
        "expired":False},
       {"name":"stock-next-session-68-source-raw-38401880091",
        "workflow_run":{"id":38401880091},"created_at":"2026-10-13T21:20:00+08:00",
        "expired":False},
       {"name":"stock-next-session-68-source-raw-38483763642",
        "workflow_run":{"id":38483763642},"created_at":"2026-10-14T07:27:00+08:00",
        "expired":False}]
    import copy
    checks={}
    def test(name,change=None,expect="ARTIFACT_METADATA_CANDIDATES_ONLY_NOT_SOURCE_QUALIFIED"):
        x=copy.deepcopy(original);y=copy.deepcopy(art)
        if change:change(x,y)
        r=selection(x,y,"38483763642")
        checks[name]=(r["Status"]==expect and r["FormalEligible"] is False and
                      r["NaturalCredit"]==r["OOSCredit"]==0)
    test("positive_oct14_metadata_candidate")
    checks["positive_both_runs"]=selection(original,art,"38483763642")["PriorPublicInputRunID"]=="38265016756" and selection(original,art,"38483763642")["EveningRunID"]=="38401880091"
    test("missing_prior",lambda x,y:y.pop(0),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("missing_evening",lambda x,y:y.pop(1),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("no_prior_expired",lambda x,y:y[0].update(expired=True),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("no_evening_expired",lambda x,y:y[1].update(expired=True),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("no_prior_cross_day",lambda x,y:y[0].update(created_at="2026-10-13T19:10:00+08:00"),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("no_evening_outside",lambda x,y:y[1].update(created_at="2026-10-13T18:59:00+08:00"),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("no_future_archive",lambda x,y:y[1].update(created_at="2026-10-14T07:30:00+08:00"),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("no_artifact_wrong_run",lambda x,y:y[0]["workflow_run"].update(id=2),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("no_artifact_missing_run",lambda x,y:y[0].pop("workflow_run"),"ARCHIVED_SOURCE_CANDIDATES_MISSING_RESEARCH_HOLD")
    test("old_source_wrong_cutoff",lambda x,y:x["dates"].update(price_cutoff="20261012"),"HOLD_BAD_SOURCE_META")
    test("future_leakage",lambda x,y:x.update(started_at="2026-10-14T09:21:00+08:00"),"HOLD_BAD_SOURCE_META")
    test("naive_time",lambda x,y:x.update(started_at="2026-10-14T07:21:00"),"HOLD_BAD_SOURCE_META")
    def arbitrary_session(x,y):
        x["dates"].update(target_date="2026-10-22",price_cutoff="20261021",previous_session="20261020")
        x["started_at"]="2026-10-22T07:20:00+08:00"
        y[0]["name"]="stock-public-input-20261021-38265016756-1"
        y[0]["created_at"]="2026-10-20T23:20:00+08:00"
        y[1]["created_at"]="2026-10-21T21:20:00+08:00"
    test("arbitrary_oct22_not_hardcoded",arbitrary_session)
    checks["three_orig_is_not_a_single_source"]=selection(original,art,"38483763642")["RawSourceVerified"] is False
    checks["no_native_prediction"]=selection(original,art,"38483763642")["NativePredictionWritten"] is False
    checks["selection_only_two_archive_roles"]=set(k for k in selection(original,art,"38483763642") if k.endswith("Artifact"))=={"PriorPublicInputArtifact","EveningArtifact"}
    result={"status":"PASS" if all(checks.values()) and len(checks)==18 else "FAIL",
            "total":len(checks),"passed":sum(checks.values()),
            "scope":"SYNTHETIC_ARCHIVE_LOCATOR_NO_PRIVATE_DATA_NO_FORMAL",
            "checks":checks}
    return result

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--self-test",action="store_true")
    a.add_argument("--current-receipt")
    a.add_argument("--output")
    a.add_argument("--max-pages",type=int,default=10)
    v=a.parse_args()
    if v.self_test:
        r=selftest();print(json.dumps(r,ensure_ascii=False))
        return 0 if r["status"]=="PASS" else 2
    if not v.current_receipt or not v.output:
        a.error("current-receipt and output required")
    data=json.loads(pathlib.Path(v.current_receipt).read_bytes())
    arts=get_latest(os.environ.get("GITHUB_REPOSITORY",""),
                    os.environ.get("GH_TOKEN",""),max(1,min(v.max_pages,20)))
    result=selection(data,arts,os.environ.get("GITHUB_RUN_ID",""))
    o=pathlib.Path(v.output);o.parent.mkdir(exist_ok=True,parents=True)
    raw=json.dumps(result,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    o.write_text(raw,encoding="utf8")
    if o.read_bytes()!=raw.encode():
        raise RuntimeError("ARCHIVE_CANDIDATE_RECEIPT_READBACK_FAILED")
    github_out=os.environ.get("GITHUB_OUTPUT")
    if github_out and result["Status"]=="ARTIFACT_METADATA_CANDIDATES_ONLY_NOT_SOURCE_QUALIFIED":
        with open(github_out,"a",encoding="utf8") as f:
            f.write("prior_run_id="+result["PriorPublicInputRunID"]+"\n")
            f.write("prior_name="+result["PriorPublicInputArtifact"]+"\n")
            f.write("evening_run_id="+result["EveningRunID"]+"\n")
            f.write("evening_name="+result["EveningArtifact"]+"\n")
            f.write("current_day8="+result["CurrentSession"]+"\n")
    print(json.dumps(result,ensure_ascii=False))
    return 0  # no archive is a truthful research HOLD; don't block core raw collection

if __name__=="__main__":
    raise SystemExit(main())
