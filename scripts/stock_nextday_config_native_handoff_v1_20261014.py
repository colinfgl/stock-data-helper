#!/usr/bin/env python3
"""Two-phase native Google Sheets ConfigSealer handoff for future sessions.

Not an autonomous Google/ChatGPT worker. An authorized runtime supplies live
native sheet readbacks, owns a dedicated lease, and executes these EXACT
Google Sheets updateCells requests via its connected native tool. A plan is
NEVER an executed write. Pending rows cannot be consumed as PRESEALED.
The frozen 2026-10-14 08:10 attempt cannot be retroactively rehabilitated.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

from stock_nextday_config_preseal_gate_v2_20261014 import (
    TZ, COLUMN_ORDER, FIELDS, assess, canonical_hash, iso_time,
)
TAB="STOCK_Run_Config"
TAB_ID=508116522
CTRL="1UYSxDe4g44QKJIQvGY4MW-Atcx6aqMja_lliC-f8p1o"
PENDING="SEAL_PENDING_NATIVE_READBACK"
ACTIVE="PRESEALED"
EXPECTED_COLS=24
HARD=("FormalEligible","NaturalEligible","OOSGovernanceDayEligible","CashTradeAuthorized")

def digest(o):
    data=json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()

def hold(reason,**context):
    return {"decision":"HOLD","reason":reason,"native_write_performed":False,
            "natural_credit":0,"oos_credit":0,**context}

def valid_clock(value):
    return iso_time(value)

def live_lease(lease,time):
    if not isinstance(lease,dict):return False
    acquired=valid_clock(lease.get("acquired_at"))
    expires=valid_clock(lease.get("expires_at"))
    now=valid_clock(time)
    return (now is not None and acquired is not None and expires is not None
            and acquired<=now<expires
            and expires-acquired<=dt.timedelta(minutes=55,seconds=1)
            and lease.get("state")=="ACTIVE"
            and lease.get("lease_scope")=="STOCK_CONFIG_NEXTDAY"
            and lease.get("last_native_readback") is True
            and isinstance(lease.get("writer_token"),str)
            and lease["writer_token"].startswith("STOCK-WRITE-")
            and lease.get("no_competing_active_writer") is True)

def before_target_preopen(target_date,checked_at):
    """Never create/validate a newly operative config after 08:10 local."""
    try:
        target=dt.date.fromisoformat(str(target_date))
    except (TypeError,ValueError):
        return False
    instant=valid_clock(checked_at)
    return (instant is not None
            and instant<dt.datetime.combine(target,dt.time(8,10),TZ))

def sheet_data(sheet,minimum_time):
    """Confirm the caller read exactly the full canonical native physical range."""
    if not isinstance(sheet,dict):
        raise ValueError("NATIVE_SHEET_OBJECT_REQUIRED")
    if sheet.get("spreadsheet_id")!=CTRL or sheet.get("sheet_id")!=TAB_ID:
        raise ValueError("WRONG_FIXED_SHEET_ID")
    if sheet.get("sheet_name")!=TAB:
        raise ValueError("WRONG_CANONICAL_TAB")
    if sheet.get("read_range")!="A1:X200" or sheet.get("grid_row_count")!=200:
        raise ValueError("NOT_ALL_200_ROWS_SCANNED")
    t=valid_clock(sheet.get("captured_at"))
    m=valid_clock(minimum_time)
    if t is None or m is None or t<m:
        raise ValueError("STALE_OR_NAIVE_NATIVE_READBACK")
    rows=sheet.get("rows")
    if (not isinstance(rows,list) or len(rows)<1
        or len(rows)>200 or rows[0]!=list(COLUMN_ORDER)):
        raise ValueError("EXACT_PHYSICAL_24_HEADER_MISMATCH")
    for i,row in enumerate(rows[1:],2):
        if not isinstance(row,list) or len(row)>EXPECTED_COLS:
            raise ValueError("MALFORMED_NATIVE_ROW_"+str(i))
        if not row or not row[0]:
            raise ValueError("INTERIOR_BLANK_OR_UNVERIFIED_ROW_"+str(i))
    return rows,t

def fixed_canonical_from_row(row):
    mapping={
      "TargetDate":"TargetDate","DataRelease":"DataRelease",
      "RuntimeControl":"RuntimeControl","CurrentID":"CurrentID",
      "TodoID":"TodoID","LatestID":"LatestID","LatestSHA":"LatestSHA256",
      "ControlSheetID":"ControlSheetID","LedgerID":"LedgerID",
      "DataClosureSheet":"DataClosureTab",
      "PremarketTaskID":"PremarketTaskID",
      "PremarketBootstrapSHA":"PremarketBootstrapSHA256",
      "SettlementTaskID":"SettlementTaskID",
      "SettlementBootstrapSHA":"SettlementBootstrapSHA256",
      "GovernanceBundleID":"GovernanceBundleID",
      "GovernanceBundleSHA256":"GovernanceBundleSHA256",
      "FreezePolicy":"FreezePolicy",
    }
    source=dict(zip(COLUMN_ORDER,row))
    return {k:source[physical] for k,physical in mapping.items()}|{
      "ConfigHashVersion":"CFG-HASH-v2"}

def normalized_row(row):
    # Native Google Sheets often omits trailing empty cells. Preserve physical
    # indexes, but never allow extra cells or coercion of formal string fields.
    if not isinstance(row,list) or len(row)>24:
        return None
    return row+[""]*(24-len(row))

def update(rowindex,values,column_index=0):
    return {"updateCells":{"range":{
      "sheetId":TAB_ID,"startRowIndex":rowindex,"endRowIndex":rowindex+1,
      "startColumnIndex":column_index,"endColumnIndex":column_index+len(values)},
      "rows":[{"values":[{"userEnteredValue":{"stringValue":v}} for v in values]}],
      "fields":"userEnteredValue"}}

def resume_pending_target(rows,draft,lease,snapshot,before_captured_at):
    """Only same active writer and SAME immutable 24 fields may resume.

    A staged row is NEVER formal by itself. No overwrite, no second append.
    A crashed/abandoned writer with another lease token remains HOLD for
    governed reconciliation; silent takeover could hide a concurrent writer.
    """
    target=draft["row"][0]
    matches=[(i,r) for i,r in enumerate(rows[1:],1) if r and r[0]==target]
    if len(matches)!=1:
        return hold("MULTIPLE_TARGET_ROWS_OR_UNVERIFIED_RESUME")
    idx,original=matches[0]
    row=normalized_row(original)
    if row is None or row[2]!=PENDING:
        return hold("EXISTING_TARGET_NOT_OWNED_PENDING_DO_NOT_OVERWRITE")
    if row[1]!=draft["row"][1]:
        return hold("PENDING_EXISTING_CONFIG_ID_CONFLICT")
    if row[19]!=draft["canonical_hash"]:
        return hold("PENDING_CONFIG_HASH_CONFLICT")
    expected_note=("PENDING_READBACK_RUNID="+draft["run_id_dependency"]+
                   ";LEASE="+lease["writer_token"]+
                   ";REQUIRES_TRUE_NATIVE_STAGE_AND_FINAL_READBACK")
    if row[21]!=expected_note:
        return hold("PENDING_ORIGINAL_WRITER_OR_RUNID_CONFLICT_NO_TAKEOVER")
    try:
        stage_clock=dt.datetime.strptime(row[3],"%Y-%m-%d %H:%M:%S Asia/Taipei").replace(tzinfo=TZ)
    except (ValueError,TypeError):
        return hold("PENDING_ORIGINAL_SEAL_TIMESTAMP_UNVERIFIED")
    request_clock=valid_clock(snapshot.get("requested_at"))
    checked=valid_clock(before_captured_at)
    if (request_clock is None or checked is None or
        stage_clock>checked or stage_clock>request_clock or
        not before_target_preopen(target,row[3].replace(" Asia/Taipei","+08:00"))):
        return hold("PENDING_ORIGINAL_SEAL_TIME_OUTSIDE_PREOPEN")
    for j,expected in enumerate(draft["row"]):
        if j in (2,3,21):
            continue
        if row[j]!=expected:
            return hold("PENDING_NONSTATUS_IMMUTABLE_FIELD_CONFLICT_COL_"+str(j))
    try:
        native_hash=canonical_hash(fixed_canonical_from_row(row))
    except (TypeError,ValueError,KeyError) as exc:
        return hold("PENDING_NATIVE_SCHEMA_OR_HASH_INVALID",detail=str(exc))
    if native_hash!=draft["canonical_hash"]:
        return hold("PENDING_CANONICAL_FINGERPRINT_DIFFERENT")
    manifest={
       "decision":"STAGE_REQUEST_READY_NOT_EXECUTED",
       "target_date":target,"expected_config_id":row[1],
       "expected_lease_token":lease["writer_token"],
       "source_settlement_run_id":draft["run_id_dependency"],
       "cfg_hash":draft["canonical_hash"],
       "sheet_id":TAB_ID,"native_row_index_0based":idx,
       "stage_row":row,"stage_request":None,
       "source_snapshot_sha":digest(snapshot),
       "before_native_sha":digest(rows),
       "no_formal_prediction_credit":True,
       "natural_credit":0,"oos_credit":0,"native_write_performed":False,
       "skip_native_stage_write":True,
       "handoff_contract":"RESUME_IDENTICAL_OWNED_PENDING_ONLY_VERIFY_STAGE_THEN_ONE_CELL_PROMOTION"
    }
    return {"decision":"RESUME_PENDING_STAGE_ALREADY_NATIVE_NO_DUPLICATE_WRITE",
            "stage_manifest":manifest,
            "run_id":draft["run_id_dependency"],
            "target_date":target,"expected_lease_token":lease["writer_token"],
            "native_row_index_0based":idx,
            "next_step":"Never call stage_request again: pass stage_manifest to verify-stage with fresh native readback; only then may issue C-only promotion.",
            "native_write_performed":False,
            "natural_credit":0,"oos_credit":0,
            "formal_forecast_eligible":False}

def prepare(snapshot,before,lease,prepared_at):
    draft=assess(snapshot)
    if draft["decision"]!="READY_FOR_SEPARATE_NATIVE_WRITE_AND_READBACK":
        return hold("PLAN_GOVERNANCE_HOLD",underlying=draft.get("reasons",[]))
    if not before_target_preopen(draft["row"][0],prepared_at):
        return hold("LATE_NATIVE_STAGE_AFTER_TARGET_0810")
    if not live_lease(lease,prepared_at):
        return hold("NO_FRESH_OWNED_ACTIVE_NATIVE_LEASE")
    original_writer=snapshot.get("writer") or {}
    if (original_writer.get("state")=="ACTIVE_OWNED"
        and original_writer.get("active_lease_token")!=lease["writer_token"]):
        return hold("PLANNER_OWNER_TOKEN_DIFFERS_FROM_PHYSICAL_NATIVE_LEASE")
    when=valid_clock(prepared_at)
    requested=valid_clock(snapshot.get("requested_at"))
    if when is None or requested is None or when<requested:
        return hold("PHASE_TIME_REVERSED")
    try:
        rows,captured=sheet_data(before,lease["acquired_at"])
    except ValueError as exc:
        return hold(str(exc))
    if captured>when:
        return hold("FUTURE_SHEET_CAPTURE")
    target=draft["row"][0]
    matching=[(i,r) for i,r in enumerate(rows[1:],start=2) if r[0]==target]
    if matching:
        return resume_pending_target(rows,draft,lease,snapshot,before["captured_at"])
    if any(r[1]==draft["row"][1] for r in rows[1:] if len(r)>1):
        return hold("DUPLICATE_CONFIG_ID_NEVER_REWRITE")
    if len(rows)>=200:
        return hold("CANONICAL_CONFIG_GRID_FULL_NEEDS_GOVERNED_EXTENSION")
    # No stage is a legally effective PRESEALED config. It must be proven
    # byte-for-byte with native readback before one-cell status promotion.
    pending=draft["row"][:]
    pending[2]=PENDING
    pending[21]=("PENDING_READBACK_RUNID="+draft["run_id_dependency"]+
                 ";LEASE="+lease["writer_token"]+
                 ";REQUIRES_TRUE_NATIVE_STAGE_AND_FINAL_READBACK")
    if not all(isinstance(x,str) for x in pending):
        return hold("NATIVE_24_COLUMNS_NONSTRING_OR_NULL")
    if canonical_hash(fixed_canonical_from_row(pending))!=draft["canonical_hash"]:
        return hold("CANONICAL_HASH_ROUNDTRIP_MISMATCH")
    idx=len(rows) # zero-index new row. Existing header row index0, e.g. 30 existing rows -> new 31.
    manifest={
       "decision":"STAGE_REQUEST_READY_NOT_EXECUTED",
       "target_date":target,"expected_config_id":pending[1],
       "expected_lease_token":lease["writer_token"],
       "source_settlement_run_id":draft["run_id_dependency"],
       "cfg_hash":draft["canonical_hash"],
       "sheet_id":TAB_ID,"native_row_index_0based":idx,
       "stage_row":pending,"stage_request":update(idx,pending),
       "source_snapshot_sha":digest(snapshot),
       "before_native_sha":digest(rows),
       "no_formal_prediction_credit":True,
       "natural_credit":0,"oos_credit":0,"native_write_performed":False,
       "handoff_contract":"STAGE_WRITE_THEN_EXACT_READBACK_THEN_SINGLE_CELL_PROMOTION_THEN_FINAL_READBACK"}
    return manifest

def verify_stage(manifest,after,lease,checked_at):
    if not isinstance(manifest,dict) or manifest.get("decision")!="STAGE_REQUEST_READY_NOT_EXECUTED":
        return hold("NOT_VALIDATED_STAGE_PLAN")
    if not before_target_preopen(manifest.get("target_date"),checked_at):
        return hold("POST_0810_STAGE_PROMOTION_FORBIDDEN")
    if not live_lease(lease,checked_at) or lease["writer_token"]!=manifest.get("expected_lease_token"):
        return hold("LEASE_UNVERIFIED_AT_STAGE_READBACK")
    try:
        rows,t=sheet_data(after,lease["acquired_at"])
    except ValueError as exc:
        return hold(str(exc))
    if t>valid_clock(checked_at):
        return hold("FUTURE_STAGE_SHEET_CAPTURE")
    index=manifest["native_row_index_0based"]
    if index>=len(rows):
        return hold("NATIVE_STAGE_ROW_NOT_READ_BACK")
    actual=normalized_row(rows[index])
    if actual!=manifest["stage_row"]:
        return hold("STAGED_24_COLUMN_VALUE_MISMATCH_OR_REPLACEMENT")
    matches=[(i,r) for i,r in enumerate(rows[1:],1) if r[0]==manifest["target_date"]]
    if len(matches)!=1 or matches[0][0]!=index:
        return hold("TARGET_NOT_UNIQUE_AFTER_STAGE")
    if any(r[1]==actual[1] for i,r in enumerate(rows[1:],1) if i!=index and len(r)>1):
        return hold("CONFIGID_DUPLICATED_AFTER_STAGE")
    if (actual[2]!=PENDING or
        canonical_hash(fixed_canonical_from_row(actual))!=manifest["cfg_hash"] or
        actual[19]!=manifest["cfg_hash"]):
        return hold("STAGE_STATUS_OR_CONFIG_HASH_MISMATCH")
    return {
      "decision":"NATIVE_STAGE_EXACT_PASS_PROMOTE_ONE_CELL_NEXT",
      "promotion_request":update(index,[ACTIVE],column_index=2),
      "expected_config_id":actual[1],"cfg_hash":manifest["cfg_hash"],
      "native_row_index_0based":index,"native_write_performed":False,
      "natural_credit":0,"oos_credit":0,"formal_forecast_eligible":False
    }

def verify_final(manifest,after,lease,checked_at):
    if not isinstance(manifest,dict) or manifest.get("decision")!="STAGE_REQUEST_READY_NOT_EXECUTED":
        return hold("NO_PRIOR_VERIFIED_STAGE_MANIFEST")
    if not before_target_preopen(manifest.get("target_date"),checked_at):
        return hold("POST_0810_FINAL_READBACK_CANNOT_SEAL")
    if not live_lease(lease,checked_at) or lease["writer_token"]!=manifest.get("expected_lease_token"):
        return hold("LEASE_UNVERIFIED_AT_FINAL_READBACK")
    try:
        rows,t=sheet_data(after,lease["acquired_at"])
    except ValueError as exc:
        return hold(str(exc))
    if t>valid_clock(checked_at):
        return hold("FUTURE_FINAL_SHEET_CAPTURE")
    idx=manifest["native_row_index_0based"]
    if idx>=len(rows):return hold("FINAL_ROW_NOT_PRESENT")
    want=manifest["stage_row"][:];want[2]=ACTIVE
    actual=normalized_row(rows[idx])
    if actual!=want:
        return hold("FINAL_NATIVE_24_COLUMN_EXACT_READBACK_FAILED")
    matches=[(i,r) for i,r in enumerate(rows[1:],1) if r[0]==manifest["target_date"]
             and len(r)>2 and r[2] in (ACTIVE,"ACTIVE_SEALED","SEALED")]
    pending=[r for r in rows[1:] if r[0]==manifest["target_date"]
             and len(r)>2 and r[2]==PENDING]
    if len(matches)!=1 or matches[0][0]!=idx or pending:
        return hold("NOT_EXACTLY_ONE_PRESEALED_TARGET_AFTER_COMMIT")
    if actual[19]!=manifest["cfg_hash"] or canonical_hash(fixed_canonical_from_row(actual))!=actual[19]:
        return hold("LIVE_FINAL_CFG_HASH_V2_MISMATCH")
    return {
      "decision":"CONFIG_PRESEALED_NATIVE_24_EXACT_READBACK_PASS",
      "target_date":actual[0],"config_id":actual[1],
      "config_hash":actual[19],"source_settlement_run_id":manifest["source_settlement_run_id"],
      "lease_token":lease["writer_token"],"full_native_readback":True,
      "target_authoritative_count":1,"native_rows_verified":len(rows),
      "schema_columns":24,"formal_forecast_eligible":False,
      "natural_credit":0,"oos_credit":0,
      "next":"Record receipt, release scoped lease and independently revalidate config on next morning 08:10; no automatic Formal/Natural credit."
    }

def synthetic():
    target="2026-10-15";source="2026-10-14";rid="STK-SET-20261014-1900-R33"
    canonical={
      "TargetDate":target,"DataRelease":"R-next-C01",
      "RuntimeControl":"R151.6-IMMUTABLE-SLO",
      "CurrentID":"1hdbBzeFRGSr0D8hJZkEeoDm0X7kXUrZ6",
      "TodoID":"15iqV8Xtsl4PM5_LK3qFT-x2x09ymHgnP_IW6lP85Axk",
      "LatestID":"1eD-O6RPidhNiM5a8ZEr7dSJzCg215tem",
      "LatestSHA":"a"*64,
      "ControlSheetID":CTRL,
      "LedgerID":"1kgp0qv18eYbHYqEXVxe09f2SYpeBMIYxPaNwSzTBPWM",
      "DataClosureSheet":"STOCK_Data_Closure",
      "PremarketTaskID":"6a839f5cf6dc8191936ab9bb9d173ef4",
      "PremarketBootstrapSHA":"b"*64,
      "SettlementTaskID":"6a825a73808c81918c5c7b5d1fecaf28",
      "SettlementBootstrapSHA":"c"*64,
      "GovernanceBundleID":"STOCK-GOVBUNDLE-V16-RNEXTC01-20261007-R33",
      "GovernanceBundleSHA256":"d"*64,
      "FreezePolicy":"IMMUTABLE_POLICY_FOR_TARGET_DATE","ConfigHashVersion":"CFG-HASH-v2"}
    snapshot={
      "target_date":target,"requested_at":"2026-10-14T19:25:00+08:00",
      "candidate_id":"STOCK-CFG-20261015-RNEXTC01-R33-01",
      "calendar":{"target_date":target,"ordered_sessions":[source,target,"2026-10-16"],
                  "verified_primary_original":True,"official_raw_sha":"e"*64},
      "settlement":{"session_date":source,"trigger_class":"NORMAL_SCHEDULE",
                    "final_readback":True,"final_terminal":True,
                    "run_id":rid,"receipt20_run_id":rid,"observability22_run_id":rid,
                    "receipt20_exact_readback":True,"observability22_exact_readback":True,
                    "original_report_sha":"f"*64,
                    "finished_at":"2026-10-14T19:23:00+08:00",
                    "scheduled_due":"2026-10-14T19:00:00+08:00"},
      "entries":{"current_fixed_id":canonical["CurrentID"],"todo_fixed_id":canonical["TodoID"],
                 "same_state_revision":True,"both_native_readback":True,
                 "runtime_r33_consistent":True},
      "live_tasks":{"premarket_id":canonical["PremarketTaskID"],"settlement_id":canonical["SettlementTaskID"],
                    "premarket_bootstrap_sha":canonical["PremarketBootstrapSHA"],
                    "settlement_bootstrap_sha":canonical["SettlementBootstrapSHA"],
                    "both_enabled":True,"schedule_0810_1900_verified":True,
                    "schedule_seal_exact_readback":True},
      "governance":{"bundle_id":canonical["GovernanceBundleID"],
                    "bundle_sha":canonical["GovernanceBundleSHA256"],
                    "components_exact_readback":30,
                    "approved_sealer_active":True,"authority_digest_verified":True},
      "authority":{"canonical":canonical,"latest_file_id_live":canonical["LatestID"],
                   "latest_sha_live":canonical["LatestSHA"],"latest_raw_sha_verified":True},
      "writer":{"live_checked":True,"state":"FREE","writer_scope":"STOCK_CONFIG_NEXTDAY"},
      "existing_configs":[]}
    lease={"state":"ACTIVE","lease_scope":"STOCK_CONFIG_NEXTDAY",
           "writer_token":"STOCK-WRITE-20261014-CFG-V2-01",
           "acquired_at":"2026-10-14T19:25:30+08:00",
           "expires_at":"2026-10-14T20:20:30+08:00",
           "last_native_readback":True,"no_competing_active_writer":True}
    old=["2026-10-13","STOCK-CFG-20261013-R33","PRESEALED"]
    native={"spreadsheet_id":CTRL,"sheet_id":TAB_ID,"sheet_name":TAB,
            "read_range":"A1:X200","grid_row_count":200,
            "captured_at":"2026-10-14T19:26:00+08:00",
            "rows":[list(COLUMN_ORDER),old]}
    return snapshot,lease,native

def selftest():
    ss,lease,pre=synthetic()
    plan=prepare(ss,pre,lease,"2026-10-14T19:27:00+08:00")
    tests={}
    def check(name,ok):tests[name]=bool(ok)
    check("good_plan_pending_only",plan.get("decision")=="STAGE_REQUEST_READY_NOT_EXECUTED")
    check("exact_24_cells",len(plan.get("stage_row",[]))==24)
    check("pending_not_presealed",plan["stage_row"][2]==PENDING)
    check("same_hash_canonical",canonical_hash(fixed_canonical_from_row(plan["stage_row"]))==plan["cfg_hash"])
    check("no_oos_natural",plan["natural_credit"]==plan["oos_credit"]==0)
    check("native_writes_are_request_not_performed",plan["native_write_performed"] is False)
    check("stage_one_update_cells",set(plan["stage_request"])=={"updateCells"})
    check("stage_exact_sheet",plan["stage_request"]["updateCells"]["range"]["sheetId"]==TAB_ID)
    check("stage_exact_row",plan["stage_request"]["updateCells"]["range"]["startRowIndex"]==len(pre["rows"]))
    stage=copy.deepcopy(pre)
    stage["captured_at"]="2026-10-14T19:28:00+08:00"
    stage["rows"].append(plan["stage_row"])
    next_action=verify_stage(plan,stage,lease,"2026-10-14T19:28:30+08:00")
    check("verified_stage_single_cell_commit",next_action.get("decision")=="NATIVE_STAGE_EXACT_PASS_PROMOTE_ONE_CELL_NEXT")
    check("commit_only_col_C",next_action["promotion_request"]["updateCells"]["range"]["startColumnIndex"]==2
          and next_action["promotion_request"]["updateCells"]["range"]["endColumnIndex"]==3)
    final=copy.deepcopy(stage)
    final["rows"][-1][2]=ACTIVE
    final["captured_at"]="2026-10-14T19:29:00+08:00"
    closure=verify_final(plan,final,lease,"2026-10-14T19:29:30+08:00")
    check("final_native_pass",closure.get("decision")=="CONFIG_PRESEALED_NATIVE_24_EXACT_READBACK_PASS")
    check("unique_authority_one",closure.get("target_authoritative_count")==1)
    check("readback_doesnt_mint_formal",closure.get("formal_forecast_eligible") is False)
    def invalid(name,mutate,mode="prepare"):
        s,l,p=(copy.deepcopy(ss),copy.deepcopy(lease),copy.deepcopy(pre))
        mutate(s,l,p)
        d=prepare(s,p,l,"2026-10-14T19:27:00+08:00")
        check(name,d.get("decision")=="HOLD")
    invalid("reject_sealer_staged",lambda s,l,p:s["governance"].update(approved_sealer_active=False))
    invalid("reject_missing_natural19_receipt",lambda s,l,p:s["settlement"].update(receipt20_exact_readback=False))
    invalid("reject_earlier_not_19",lambda s,l,p:s["settlement"].update(scheduled_due="2026-10-14T18:00:00+08:00"))
    invalid("reject_missing19_final",lambda s,l,p:s["settlement"].update(final_readback=False))
    invalid("reject_cross_run",lambda s,l,p:s["settlement"].update(observability22_run_id="WRONG"))
    invalid("reject_bad_calendar_sha",lambda s,l,p:s["calendar"].update(official_raw_sha="BAD"))
    invalid("reject_target_is_today",lambda s,l,p:s.update(target_date="2026-10-14"))
    invalid("reject_bundle_authority_drift",lambda s,l,p:s["governance"].update(bundle_sha="0"*64))
    invalid("reject_today_after_0810",lambda s,l,p:s.update(requested_at="2026-10-15T08:12:00+08:00"))
    invalid("reject_writer_not_active",lambda s,l,p:l.update(state="FREE"))
    invalid("reject_writer_already_expired",lambda s,l,p:l.update(expires_at="2026-10-14T19:26:00+08:00"))
    invalid("reject_competing_writer",lambda s,l,p:l.update(no_competing_active_writer=False))
    invalid("reject_lease_not_readback",lambda s,l,p:l.update(last_native_readback=False))
    invalid("reject_wrong_writer_scope",lambda s,l,p:l.update(lease_scope="WRONG"))
    invalid("reject_sheet_wrong_id",lambda s,l,p:p.update(sheet_id=2))
    invalid("reject_sheet_wrong_tab",lambda s,l,p:p.update(sheet_name="STOCK_Run_Config_Staging"))
    invalid("reject_sheet_partial_scan",lambda s,l,p:p.update(read_range="A1:X25"))
    invalid("reject_wrong_header_order",lambda s,l,p:p["rows"][0].reverse())
    invalid("reject_interior_blank",lambda s,l,p:p["rows"].insert(1,[]))
    invalid("reject_stale_original_read",lambda s,l,p:p.update(captured_at="2026-10-14T19:00:00+08:00"))
    invalid("reject_existing_target",lambda s,l,p:p["rows"].append(["2026-10-15","C","SEAL_PENDING_NATIVE_READBACK"]))
    invalid("reject_target_duplicate_config_id",lambda s,l,p:p["rows"].append(["2026-10-13",s["candidate_id"],"HOLD"]))
    wrong=copy.deepcopy(stage);wrong["rows"][-1][15]="WRONG"
    check("reject_stage_tamper",verify_stage(plan,wrong,lease,"2026-10-14T19:28:30+08:00")["decision"]=="HOLD")
    wrong=copy.deepcopy(stage);wrong["rows"].append(plan["stage_row"])
    check("reject_duplicate_stage_target",verify_stage(plan,wrong,lease,"2026-10-14T19:28:30+08:00")["decision"]=="HOLD")
    wrong=copy.deepcopy(final);wrong["rows"][-1][19]="0"*64
    check("reject_final_sha_tamper",verify_final(plan,wrong,lease,"2026-10-14T19:29:30+08:00")["decision"]=="HOLD")
    wrong=copy.deepcopy(final);wrong["rows"][-1][2]=PENDING
    check("reject_final_not_promoted",verify_final(plan,wrong,lease,"2026-10-14T19:29:30+08:00")["decision"]=="HOLD")
    wrong=copy.deepcopy(final);wrong["rows"].append(["2026-10-15","OTHER","PRESEALED"])
    check("reject_duplicate_seal_final",verify_final(plan,wrong,lease,"2026-10-14T19:29:30+08:00")["decision"]=="HOLD")
    check("reject_prepare_after_target_preopen",
          prepare(ss,pre,lease,"2026-10-15T08:10:00+08:00").get("reason")=="LATE_NATIVE_STAGE_AFTER_TARGET_0810")
    check("reject_stage_readback_after_target_preopen",
          verify_stage(plan,stage,lease,"2026-10-15T08:10:00+08:00").get("reason")=="POST_0810_STAGE_PROMOTION_FORBIDDEN")
    check("reject_final_readback_after_target_preopen",
          verify_final(plan,final,lease,"2026-10-15T08:10:00+08:00").get("reason")=="POST_0810_FINAL_READBACK_CANNOT_SEAL")
    future_stage=copy.deepcopy(stage)
    future_stage["captured_at"]="2026-10-14T19:29:00+08:00"
    check("reject_future_timestamp_stage_sheet",
          verify_stage(plan,future_stage,lease,"2026-10-14T19:28:30+08:00").get("reason")=="FUTURE_STAGE_SHEET_CAPTURE")
    future_final=copy.deepcopy(final)
    future_final["captured_at"]="2026-10-14T19:30:00+08:00"
    check("reject_future_timestamp_final_sheet",
          verify_final(plan,future_final,lease,"2026-10-14T19:29:30+08:00").get("reason")=="FUTURE_FINAL_SHEET_CAPTURE")
    # Actual physical target already has pending row when the same lease
    # retries; report may only be resumed, NEVER appended twice.
    resumed=prepare(ss,stage,lease,"2026-10-14T19:29:10+08:00")
    check("same_owned_pending_is_resume",resumed.get("decision")==
          "RESUME_PENDING_STAGE_ALREADY_NATIVE_NO_DUPLICATE_WRITE")
    check("resume_prohibits_duplicate_append",
          resumed.get("stage_manifest",{}).get("stage_request") is None and
          resumed.get("stage_manifest",{}).get("skip_native_stage_write") is True)
    check("resume_preserves_original_native_seal_time",
          resumed["stage_manifest"]["stage_row"][3]==plan["stage_row"][3])
    check("resume_does_not_mint_formal",
          resumed["natural_credit"]==resumed["oos_credit"]==0 and
          resumed["formal_forecast_eligible"] is False)
    check("resume_can_reverify_native_pending",
          verify_stage(resumed["stage_manifest"],stage,lease,
                       "2026-10-14T19:29:15+08:00")["decision"]==
          "NATIVE_STAGE_EXACT_PASS_PROMOTE_ONE_CELL_NEXT")
    stage_wrong_token=copy.deepcopy(stage)
    stage_wrong_token["rows"][-1][21]=stage_wrong_token["rows"][-1][21].replace(
        "LEASE="+lease["writer_token"],"LEASE=UNKNOWN-OTHER-WRITER")
    check("reject_other_writer_pending_token",
          prepare(ss,stage_wrong_token,lease,"2026-10-14T19:29:10+08:00")["decision"]=="HOLD")
    stage_wrong_hash=copy.deepcopy(stage)
    stage_wrong_hash["rows"][-1][19]="0"*64
    check("reject_foreign_pending_config_hash",
          prepare(ss,stage_wrong_hash,lease,"2026-10-14T19:29:10+08:00")["decision"]=="HOLD")
    stage_wrong_source=copy.deepcopy(stage)
    stage_wrong_source["rows"][-1][10]="1"*64
    check("reject_pending_nonstatus_field_change",
          prepare(ss,stage_wrong_source,lease,"2026-10-14T19:29:10+08:00")["decision"]=="HOLD")
    stage_fake_future=copy.deepcopy(stage)
    stage_fake_future["rows"][-1][3]="2026-10-15 08:10:00 Asia/Taipei"
    check("reject_pending_original_seal_after_cutoff",
          prepare(ss,stage_fake_future,lease,"2026-10-14T19:29:10+08:00")["decision"]=="HOLD")
    duplicate_pending=copy.deepcopy(stage)
    duplicate_pending["rows"].append(plan["stage_row"])
    check("reject_two_pending_rows_no_takeover",
          prepare(ss,duplicate_pending,lease,"2026-10-14T19:29:10+08:00")["decision"]=="HOLD")
    # A genuine fresh retry will read the writer as ACTIVE_OWNED, not FREE.
    # The planner and native holder must verify the SAME owner token.
    owned=copy.deepcopy(ss)
    owned["writer"].update(state="ACTIVE_OWNED",
                           active_lease_token=lease["writer_token"],
                           same_scope_owner=True,lease_exact_readback=True,
                           no_competing_active_writer=True)
    recovered=prepare(owned,stage,lease,"2026-10-14T19:29:10+08:00")
    check("fresh_owned_active_snapshot_true_resume",
          recovered.get("decision")=="RESUME_PENDING_STAGE_ALREADY_NATIVE_NO_DUPLICATE_WRITE")
    owner_changed=copy.deepcopy(owned)
    owner_changed["writer"]["active_lease_token"]="STOCK-WRITE-DIFFERENT-OWNER"
    check("reject_valid_looking_other_owner_token",
          prepare(owner_changed,stage,lease,"2026-10-14T19:29:10+08:00")
          .get("reason")=="PLANNER_OWNER_TOKEN_DIFFERS_FROM_PHYSICAL_NATIVE_LEASE")
    owner_unverified=copy.deepcopy(owned)
    owner_unverified["writer"]["lease_exact_readback"]=False
    check("reject_owned_snapshot_without_live_lease_readback",
          prepare(owner_unverified,stage,lease,"2026-10-14T19:29:10+08:00")["decision"]=="HOLD")
    owner_competing=copy.deepcopy(owned)
    owner_competing["writer"]["no_competing_active_writer"]=False
    check("reject_owned_snapshot_competing_writer",
          prepare(owner_competing,stage,lease,"2026-10-14T19:29:10+08:00")["decision"]=="HOLD")
    status="PASS" if all(tests.values()) else "FAIL"
    return {"status":status,"passed":sum(tests.values()),"total":len(tests),
            "test_scope":"SYNTHETIC_TWO_PHASE_CONNECTOR_REQUEST_NO_NATIVE_EXTERNAL_WRITE_NO_FORECAST_NATURAL",
            "tests":tests,
            "example_stage_request":plan.get("stage_request") if status=="PASS" else None,
            "example_promotion_request":next_action.get("promotion_request") if status=="PASS" else None}

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--mode",required=True,choices=("self-test","prepare","verify-stage","verify-final"))
    a.add_argument("--snapshot")
    a.add_argument("--sheet-readback")
    a.add_argument("--lease")
    a.add_argument("--handoff")
    a.add_argument("--at")
    a.add_argument("--output")
    v=a.parse_args()
    if v.mode=="self-test":
        result=selftest()
    else:
        if not (v.sheet_readback and v.lease and v.at):
            a.error("sheet-readback + lease + at required")
        sheet=json.loads(Path(v.sheet_readback).read_text(encoding="utf8"))
        lease=json.loads(Path(v.lease).read_text(encoding="utf8"))
        if v.mode=="prepare":
            if not v.snapshot:a.error("snapshot required")
            result=prepare(json.loads(Path(v.snapshot).read_text(encoding="utf8")),
                           sheet,lease,v.at)
        else:
            if not v.handoff:a.error("handoff required")
            handoff=json.loads(Path(v.handoff).read_text(encoding="utf8"))
            result=(verify_stage if v.mode=="verify-stage" else verify_final)(
                handoff,sheet,lease,v.at)
    raw=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    if v.output:
        Path(v.output).write_text(raw,encoding="utf8")
        if Path(v.output).read_text(encoding="utf8")!=raw:
            raise RuntimeError("NATIVE_HANDOFF_RECEIPT_READBACK_FAILED")
    print(raw,end="")
    return 0 if result.get("decision")!="HOLD" and result.get("status")!="FAIL" else 2

if __name__=="__main__":
    raise SystemExit(main())
