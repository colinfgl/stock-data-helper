#!/usr/bin/env python3
"""Future-day STOCK ConfigSealer v2: deterministic *plan*, never a native write.

This adapter is intentionally source-agnostic, date-generic and fail-closed.
It consumes LIVE-VERIFIED evidence supplied by an authorized worker. It cannot
fetch Drive, confirm a platform trigger, grant Natural/OOS, or mint a formal
ForecastSHA. A valid plan must still acquire a live writer lease, write through
the native Sheets API, recompute the hash and read back every cell.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")
SHA = re.compile(r"[a-f0-9]{64}\Z")
FIELDS = (
    "TargetDate", "DataRelease", "RuntimeControl", "CurrentID", "TodoID",
    "LatestID", "LatestSHA", "ControlSheetID", "LedgerID", "DataClosureSheet",
    "PremarketTaskID", "PremarketBootstrapSHA", "SettlementTaskID",
    "SettlementBootstrapSHA", "GovernanceBundleID", "GovernanceBundleSHA256",
    "FreezePolicy", "ConfigHashVersion"
)
COLUMN_ORDER = (
    "TargetDate","ConfigID","Status","SealedAt","EffectiveFrom","DataRelease",
    "RuntimeControl","CurrentID","TodoID","LatestID","LatestSHA","ControlSheetID",
    "LedgerID","DataClosureSheet","PremarketTaskID","PremarketBootstrapSHA",
    "SettlementTaskID","SettlementBootstrapSHA","FreezePolicy","ConfigHashSHA256",
    "SupersededBy","Notes","GovernanceBundleID","GovernanceBundleSHA256"
)

def sha_ok(x):
    return isinstance(x,str) and bool(SHA.fullmatch(x))

def iso_time(s):
    try:
        value = dt.datetime.fromisoformat(str(s).replace("Z","+00:00"))
        if value.tzinfo is None:
            return None
        return value.astimezone(TZ)
    except (TypeError,ValueError,OverflowError):
        return None

def session_date(value):
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError,ValueError):
        return None

def canonical_hash(fields):
    if set(fields) != set(FIELDS) or any(not isinstance(fields.get(k),str) or not fields[k] for k in FIELDS):
        raise ValueError("CFG_HASH_V2_FIELDS_INCOMPLETE")
    raw = json.dumps(fields,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def assess(snapshot):
    """Check proof readiness without changing any input or external resource."""
    errors=[]
    def check(condition,reason):
        if not condition and reason not in errors:
            errors.append(reason)
    if not isinstance(snapshot,dict):
        return {"decision":"HOLD","reasons":["INPUT_OBJECT_REQUIRED"],"native_write":False,"natural_credit":0,"oos_credit":0}
    a=snapshot.get("authority") or {}
    ca=snapshot.get("calendar") or {}
    ss=snapshot.get("settlement") or {}
    ent=snapshot.get("entries") or {}
    live=snapshot.get("live_tasks") or {}
    gov=snapshot.get("governance") or {}
    writer=snapshot.get("writer") or {}
    ex=snapshot.get("existing_configs") or []
    fields=a.get("canonical") or {}
    target=session_date(snapshot.get("target_date"))
    now=iso_time(snapshot.get("requested_at"))
    next_start=dt.datetime.combine(target,dt.time(8,10),TZ) if target else None
    check(target is not None and now is not None,"TARGET_OR_CLOCK_INVALID")
    check(target is not None and now is not None and now<next_start,
          "SEAL_AFTER_TARGET_0810_FORBIDDEN")
    sessions=[session_date(z) for z in ca.get("ordered_sessions",[])] if isinstance(ca.get("ordered_sessions"),list) else []
    sessions_ok=(all(x is not None for x in sessions) and len(sessions)==len(set(sessions))
                 and sessions==sorted(sessions) and target in sessions)
    prev=sessions[sessions.index(target)-1] if sessions_ok and sessions.index(target)>0 else None
    check(sessions_ok and prev is not None and ca.get("target_date")==str(target)
          and ca.get("verified_primary_original") is True and sha_ok(ca.get("official_raw_sha")),
          "OFFICIAL_SESSION_AND_SHA_NOT_VERIFIED")
    check(ss.get("session_date")==str(prev) if prev else False,"SETTLEMENT_PRIOR_SESSION_MISMATCH")
    check(ss.get("trigger_class")=="NORMAL_SCHEDULE" and ss.get("final_readback") is True
          and ss.get("final_terminal") is True,"REAL_SETTLEMENT_FINAL_READBACK_MISSING")
    rid=ss.get("run_id")
    check(isinstance(rid,str) and bool(rid) and ss.get("receipt20_run_id")==rid
          and ss.get("observability22_run_id")==rid
          and ss.get("receipt20_exact_readback") is True
          and ss.get("observability22_exact_readback") is True
          and sha_ok(ss.get("original_report_sha")),"SETTLEMENT_REPORT_AND_20_22_NOT_SAME_RUN")
    done=iso_time(ss.get("finished_at"))
    scheduled=iso_time(ss.get("scheduled_due"))
    check(done is not None and scheduled is not None and now is not None
          and done<=now and done>=scheduled
          and scheduled.date()==prev and scheduled.time()==dt.time(19,0),
          "SETTLEMENT_1900_TIME_OR_ORDER_INVALID")
    check(ent.get("current_fixed_id")==fields.get("CurrentID")
          and ent.get("todo_fixed_id")==fields.get("TodoID")
          and ent.get("same_state_revision") is True
          and ent.get("both_native_readback") is True
          and ent.get("runtime_r33_consistent") is True,
          "CURRENT_TODO_R29_R33_DRIFT_HOLD")
    check(live.get("premarket_id")==fields.get("PremarketTaskID")
          and live.get("settlement_id")==fields.get("SettlementTaskID")
          and live.get("premarket_bootstrap_sha")==fields.get("PremarketBootstrapSHA")
          and live.get("settlement_bootstrap_sha")==fields.get("SettlementBootstrapSHA")
          and live.get("both_enabled") is True
          and live.get("schedule_0810_1900_verified") is True
          and live.get("schedule_seal_exact_readback") is True,
          "LIVE_TASK_OR_SCHEDULE_SEAL_DRIFT")
    check(gov.get("bundle_id")==fields.get("GovernanceBundleID")
          and gov.get("bundle_sha")==fields.get("GovernanceBundleSHA256")
          and gov.get("components_exact_readback")==30
          and gov.get("approved_sealer_active") is True
          and gov.get("authority_digest_verified") is True,
          "BUNDLE_OR_SEALER_NOT_GOVERNED_ACTIVE")
    check(a.get("latest_sha_live")==fields.get("LatestSHA")
          and a.get("latest_file_id_live")==fields.get("LatestID")
          and a.get("latest_raw_sha_verified") is True,
          "LATEST_FILE_RAW_SHA_DRIFT")
    check(fields.get("TargetDate")==str(target) and fields.get("ConfigHashVersion")=="CFG-HASH-v2"
          and fields.get("FreezePolicy")=="IMMUTABLE_POLICY_FOR_TARGET_DATE"
          and fields.get("RuntimeControl")=="R151.6-IMMUTABLE-SLO"
          and sha_ok(fields.get("LatestSHA"))
          and sha_ok(fields.get("PremarketBootstrapSHA"))
          and sha_ok(fields.get("SettlementBootstrapSHA"))
          and sha_ok(fields.get("GovernanceBundleSHA256")),
          "CFG_HASH_V2_OR_POLICY_FIELDS_INVALID")
    try:
        cfg_hash=canonical_hash(fields)
    except (TypeError,ValueError):
        cfg_hash=None
        check(False,"CFG_HASH_V2_FIELDS_INCOMPLETE")
    check(writer.get("live_checked") is True and writer.get("state")=="FREE"
          and writer.get("writer_scope")=="STOCK_CONFIG_NEXTDAY",
          "FRESH_WRITER_LEASE_OR_UNCHECKED_CONFLICT")
    check(isinstance(ex,list) and not [r for r in ex if r.get("target_date")==str(target)
          and r.get("status") in ("SEALED","PRESEALED","ACTIVE_SEALED")],
          "TARGET_CONFIG_ALREADY_EXISTS_RECONCILE_DO_NOT_OVERWRITE")
    candidate=snapshot.get("candidate_id")
    check(isinstance(candidate,str)
          and bool(re.fullmatch(r"STOCK-CFG-"+(target.strftime("%Y%m%d") if target else "INVALID")+r"-[A-Z0-9-]+",candidate)),
          "CANDIDATE_ID_TARGET_OR_FORMAT_BAD")
    if errors:
        return {"decision":"HOLD","reasons":errors,"native_write":False,
                "natural_credit":0,"oos_credit":0,"formal_forecast_eligible":False,
                "target_date":str(target) if target else None}
    data={
      "TargetDate":str(target),"ConfigID":candidate,"Status":"PRESEALED",
      "SealedAt":now.strftime("%Y-%m-%d %H:%M:%S Asia/Taipei"),
      "EffectiveFrom":next_start.strftime("%Y-%m-%d %H:%M Asia/Taipei"),
      "DataRelease":fields["DataRelease"],"RuntimeControl":fields["RuntimeControl"],
      "CurrentID":fields["CurrentID"],"TodoID":fields["TodoID"],
      "LatestID":fields["LatestID"],"LatestSHA256":fields["LatestSHA"],
      "ControlSheetID":fields["ControlSheetID"],"LedgerID":fields["LedgerID"],
      "DataClosureTab":fields["DataClosureSheet"],
      "PremarketTaskID":fields["PremarketTaskID"],
      "PremarketBootstrapSHA256":fields["PremarketBootstrapSHA"],
      "SettlementTaskID":fields["SettlementTaskID"],
      "SettlementBootstrapSHA256":fields["SettlementBootstrapSHA"],
      "FreezePolicy":fields["FreezePolicy"],"ConfigHashSHA256":cfg_hash,
      "SupersededBy":"","Notes":"GOVERNED_NATIVE_WRITE_PLAN_ONLY; requires independently acquired lease and actual readback",
      "GovernanceBundleID":fields["GovernanceBundleID"],
      "GovernanceBundleSHA256":fields["GovernanceBundleSHA256"]
    }
    return {"decision":"READY_FOR_SEPARATE_NATIVE_WRITE_AND_READBACK",
            "canonical_hash":cfg_hash,
            "column_order":list(COLUMN_ORDER),
            "row":[data[c if c in data else ("LatestSHA256" if c=="LatestSHA" else c)] for c in COLUMN_ORDER],
            "run_id_dependency":rid,
            "native_write":False,"natural_credit":0,"oos_credit":0,
            "formal_forecast_eligible":False,
            "next_step":"Acquire *new* scoped writer lease, re-read evidence, write exactly 24 cells with no existing active target, recompute hash from native readback, verify unique target; this program never writes."}

def selftest():
    target="2026-10-15"; source="2026-10-14"
    v={
      "TargetDate":target,"DataRelease":"R-next-C01","RuntimeControl":"R151.6-IMMUTABLE-SLO",
      "CurrentID":"C","TodoID":"T","LatestID":"L","LatestSHA":"a"*64,
      "ControlSheetID":"CTRL","LedgerID":"DB","DataClosureSheet":"STOCK_Data_Closure",
      "PremarketTaskID":"PRE","PremarketBootstrapSHA":"b"*64,
      "SettlementTaskID":"SET","SettlementBootstrapSHA":"c"*64,
      "GovernanceBundleID":"BND","GovernanceBundleSHA256":"d"*64,
      "FreezePolicy":"IMMUTABLE_POLICY_FOR_TARGET_DATE","ConfigHashVersion":"CFG-HASH-v2"}
    rid="SYNTHETIC-SET-1"
    good={
      "target_date":target,"requested_at":"2026-10-14T19:23:00+08:00",
      "candidate_id":"STOCK-CFG-20261015-RNEXTC01-R34-01",
      "calendar":{"target_date":target,"ordered_sessions":[source,target,"2026-10-16"],
                  "official_raw_sha":"e"*64,"verified_primary_original":True},
      "settlement":{"session_date":source,"trigger_class":"NORMAL_SCHEDULE",
                    "final_readback":True,"final_terminal":True,
                    "run_id":rid,"receipt20_run_id":rid,"observability22_run_id":rid,
                    "receipt20_exact_readback":True,"observability22_exact_readback":True,
                    "original_report_sha":"f"*64,
                    "finished_at":"2026-10-14T19:19:00+08:00",
                    "scheduled_due":"2026-10-14T19:00:00+08:00"},
      "entries":{"current_fixed_id":"C","todo_fixed_id":"T",
                 "same_state_revision":True,"both_native_readback":True,
                 "runtime_r33_consistent":True},
      "live_tasks":{"premarket_id":"PRE","settlement_id":"SET",
                    "premarket_bootstrap_sha":"b"*64,"settlement_bootstrap_sha":"c"*64,
                    "both_enabled":True,"schedule_0810_1900_verified":True,
                    "schedule_seal_exact_readback":True},
      "governance":{"bundle_id":"BND","bundle_sha":"d"*64,
                    "components_exact_readback":30,"approved_sealer_active":True,
                    "authority_digest_verified":True},
      "authority":{"canonical":v,"latest_file_id_live":"L",
                   "latest_sha_live":"a"*64,"latest_raw_sha_verified":True},
      "writer":{"live_checked":True,"state":"FREE","writer_scope":"STOCK_CONFIG_NEXTDAY"},
      "existing_configs":[]}
    checks={}
    def run(name,modify=None,allow=False):
        z=copy.deepcopy(good)
        if modify:modify(z)
        a=assess(z)
        checks[name]=a["decision"].startswith("READY") if allow else a["decision"]=="HOLD"
    run("valid_plan_no_native_write",allow=True)
    r=assess(good)
    checks["plan_24_cells"]=len(r["row"])==24 and r["native_write"] is False
    checks["hash_exact_sorted_json"]=r["canonical_hash"]==canonical_hash(v)
    checks["no_formal_natural_oos"]=r["natural_credit"]==r["oos_credit"]==0 and not r["formal_forecast_eligible"]
    cases={
      "future_target_after_0810":lambda x:x.update(requested_at="2026-10-15T08:10:00+08:00"),
      "naive_clock":lambda x:x.update(requested_at="2026-10-14T19:23:00"),
      "calendar_unverified":lambda x:x["calendar"].update(verified_primary_original=False),
      "calendar_wrong_sha":lambda x:x["calendar"].update(official_raw_sha="ZZ"),
      "wrong_source_session":lambda x:x["settlement"].update(session_date="2026-10-13"),
      "not_normal_schedule":lambda x:x["settlement"].update(trigger_class="RECOVERY"),
      "no_final_readback":lambda x:x["settlement"].update(final_readback=False),
      "no_receipt20":lambda x:x["settlement"].update(receipt20_exact_readback=False),
      "no_observability22":lambda x:x["settlement"].update(observability22_exact_readback=False),
      "cross_runid":lambda x:x["settlement"].update(observability22_run_id="OTHER"),
      "bad_report_hash":lambda x:x["settlement"].update(original_report_sha="BAD"),
      "settlement_after_request":lambda x:x["settlement"].update(finished_at="2026-10-14T19:25:00+08:00"),
      "not_19settlement":lambda x:x["settlement"].update(scheduled_due="2026-10-14T18:00:00+08:00"),
      "entry_revision_drift":lambda x:x["entries"].update(same_state_revision=False),
      "entry_r29_not_r33":lambda x:x["entries"].update(runtime_r33_consistent=False),
      "live_task_disabled":lambda x:x["live_tasks"].update(both_enabled=False),
      "live_bootstrap_wrong":lambda x:x["live_tasks"].update(premarket_bootstrap_sha="f"*64),
      "schedule_seal_bad":lambda x:x["live_tasks"].update(schedule_seal_exact_readback=False),
      "bundle_hash_changed":lambda x:x["governance"].update(bundle_sha="f"*64),
      "components_incomplete":lambda x:x["governance"].update(components_exact_readback=29),
      "sealer_only_staged":lambda x:x["governance"].update(approved_sealer_active=False),
      "authority_digest_bad":lambda x:x["governance"].update(authority_digest_verified=False),
      "latest_sha_mismatch":lambda x:x["authority"].update(latest_sha_live="0"*64),
      "latest_raw_not_verified":lambda x:x["authority"].update(latest_raw_sha_verified=False),
      "wrong_cfg_hash_version":lambda x:x["authority"]["canonical"].update(ConfigHashVersion="CFG-HASH-v1"),
      "missing_field":lambda x:x["authority"]["canonical"].pop("DataRelease"),
      "writer_active":lambda x:x["writer"].update(state="ACTIVE"),
      "writer_scope_wrong":lambda x:x["writer"].update(writer_scope="SOMETHING_ELSE"),
      "duplicate_active_target":lambda x:x["existing_configs"].append({"target_date":target,"status":"PRESEALED"}),
      "wrong_candidate_day":lambda x:x.update(candidate_id="STOCK-CFG-20261014-RNEXTC01-R34-01"),
      "nonconsecutive_market_sessions":lambda x:x["calendar"].update(ordered_sessions=["2026-10-13",target,"2026-10-16"]),
    }
    for name,mutate in cases.items():run(name,mutate)
    expected_hash="d936e90f2e866de19bef4fc4ef740cf0a65c4b6c97fd4b311463ae03fbaf75fd"
    historic={
      "TargetDate":"2026-10-13","DataRelease":"R-next-C01","RuntimeControl":"R151.6-IMMUTABLE-SLO",
      "CurrentID":"1hdbBzeFRGSr0D8hJZkEeoDm0X7kXUrZ6","TodoID":"15iqV8Xtsl4PM5_LK3qFT-x2x09ymHgnP_IW6lP85Axk",
      "LatestID":"1eD-O6RPidhNiM5a8ZEr7dSJzCg215tem",
      "LatestSHA":"af7bec4aee198aa2cb5d7b6dae651d29f0386c119ba4e4ababebd69a37510863",
      "ControlSheetID":"1UYSxDe4g44QKJIQvGY4MW-Atcx6aqMja_lliC-f8p1o",
      "LedgerID":"1kgp0qv18eYbHYqEXVxe09f2SYpeBMIYxPaNwSzTBPWM",
      "DataClosureSheet":"STOCK_Data_Closure",
      "PremarketTaskID":"6a839f5cf6dc8191936ab9bb9d173ef4",
      "PremarketBootstrapSHA":"26ccf175da336e5af299e01ca739b43857ab7fce5efa998aefa71139a44ebada",
      "SettlementTaskID":"6a825a73808c81918c5c7b5d1fecaf28",
      "SettlementBootstrapSHA":"e5757022a47334e1364081f387e7a043b76ab033b451cce0ac348b9cbd37ea90",
      "GovernanceBundleID":"STOCK-GOVBUNDLE-V16-RNEXTC01-20261007-R33",
      "GovernanceBundleSHA256":"f80bd84f865ebcaf006db8d83311d6097a38d6d4d5fe759cf797cb65e1d497df",
      "FreezePolicy":"IMMUTABLE_POLICY_FOR_TARGET_DATE","ConfigHashVersion":"CFG-HASH-v2"}
    # This historic fingerprint is for a read-only hash implementation check only;
    # never generated from user holdings or elevated as a new live Config.
    checks["historic_v2_hash_contract"]=canonical_hash(historic)==expected_hash
    ok=all(checks.values())
    return {"status":"PASS" if ok else "FAIL","passed":sum(checks.values()),"total":len(checks),
            "scope":"SYNTHETIC_AND_HISTORIC_HASH_CHECK_NO_EXTERNAL_FETCH_NO_SHEETS_WRITE_NO_FORMAL_NATURAL_OOS",
            "checks":checks}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--input")
    p.add_argument("--output")
    args=p.parse_args()
    if args.self_test:
        result=selftest()
    else:
        if not args.input:p.error("required --input for read-only plan")
        result=assess(json.loads(Path(args.input).read_text(encoding="utf-8")))
    data=json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+"\n"
    if args.output:Path(args.output).write_text(data,encoding="utf-8")
    print(data,end="")
    return 0 if result.get("decision","READY").startswith("READY") or result.get("status")=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
