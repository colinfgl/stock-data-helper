#!/usr/bin/env python3
"""Conditional recovery for ONE existing 20:45 source workflow.

Checks the completed, existing public-market-daily scheduled workflow and
GitHub's real schedule-run receipts. Never invents a normal source trigger.
Only a new workflow_run event can request this recovery; other jobs are not
changed by the decision. No financial data, Forecast or Natural promotion.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")
WORKFLOW = "stock_daily_nextsession_source_closure_20261013.yml"
PARENT = "public-market-daily"


def require(test, code):
    if not test:
        raise ValueError(code)


def utc_time(value):
    require(isinstance(value, str) and value, "TIME_NOT_STRING")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "TIME_WITHOUT_TZ")
    return parsed.astimezone(dt.timezone.utc)


def source_session_date(now):
    """A 20:45 evening source becomes next morning's preopen basis.

    Same local day after market close, or previous day before local noon;
    a false skip may only cost a bounded redundant research collection.
    """
    local = now.astimezone(TZ)
    if local.hour < 12:
        return local.date() - dt.timedelta(days=1)
    return local.date()


def decide(event, records, now, repository, current_run_id=None):
    """Pure decision; 'yes' never means normal schedule or Formal."""
    require(now.tzinfo is not None, "NOW_MUST_BE_TIMEZONE_AWARE")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None, "REPO_INVALID")
    p = event.get("workflow_run") if isinstance(event, dict) else None
    if not isinstance(p, dict) or event.get("action") != "completed":
        return {"should_collect": False, "reason": "HOLD_NO_COMPLETED_PARENT", "research_only": True}
    if (p.get("name") != PARENT or p.get("event") != "schedule"
            or p.get("head_branch") != "main" or p.get("conclusion") != "success"
            or p.get("status") != "completed"):
        return {"should_collect": False, "reason": "HOLD_PARENT_NOT_SUCCESSFUL_NATURAL_SOURCE", "research_only": True}
    completed = utc_time(p.get("updated_at") or p.get("run_started_at") or p.get("created_at"))
    nowutc = now.astimezone(dt.timezone.utc)
    if not (dt.timedelta(seconds=-120) <= nowutc - completed <= dt.timedelta(hours=2)):
        return {"should_collect": False, "reason": "HOLD_STALE_OR_FUTURE_PARENT_RECEIPT", "research_only": True}
    require(isinstance(records, list), "SCHEDULE_RUN_INDEX_NOT_LIST")
    session = source_session_date(now)
    cutoff = dt.datetime.combine(session, dt.time(20, 45), tzinfo=TZ).astimezone(dt.timezone.utc)
    # Do not compete with the unique 20:45 cron. A parent that finishes early
    # is not evidence the primary source schedule has been missed.
    if nowutc < cutoff + dt.timedelta(minutes=10):
        return {"should_collect": False, "reason": "HOLD_BEFORE_PRIMARY_SOURCE_GRACE_WINDOW",
                "session": str(session), "research_only": True}
    normal, recoveries = [], []
    for run in records:
        require(isinstance(run, dict), "BAD_RUN_RECORD")
        event_name = run.get("event")
        if event_name not in ("schedule", "workflow_run") or run.get("head_branch") != "main":
            continue
        created = utc_time(run.get("created_at"))
        if not (cutoff <= created <= nowutc + dt.timedelta(seconds=120)):
            continue
        require(isinstance(run.get("id"), int) and run.get("id") > 0,
                "SOURCE_RUN_ID_INVALID")
        record = {"id": run["id"], "status": run.get("status"),
                  "conclusion": run.get("conclusion"), "created_at": run["created_at"]}
        if event_name == "schedule":
            normal.append(record)
        else:
            if record["status"] == "completed" and record["conclusion"] == "success":
                # A workflow_run can be green with both normal and recovery
                # collector SKIPPED; only the named collection JOB success is
                # proof that valid source originals were actually produced.
                require(type(run.get("capture_job_succeeded")) is bool,
                        "RECOVERY_CAPTURE_JOB_PROOF_MISSING")
                record["capture_job_succeeded"] = run["capture_job_succeeded"]
            recoveries.append(record)
    successful = [x for x in normal if x["status"] == "completed" and x["conclusion"] == "success"]
    # An original still-running normal run has priority: no competing collector.
    running = [x for x in normal if x["status"] in ("queued", "in_progress", "waiting", "requested")]
    if successful:
        return {"should_collect": False, "reason": "NO_OP_ALREADY_SUCCESSFUL_NORMAL_SOURCE",
                "session": str(session), "normal_runs": normal, "research_only": True}
    if running:
        return {"should_collect": False, "reason": "NO_OP_NORMAL_SOURCE_ALREADY_RUNNING",
                "session": str(session), "normal_runs": normal, "research_only": True}
    # Repeated completed parent events or reruns may create multiple recovery
    # workflow_run events. One successful earlier recovery is conclusive. For
    # concurrent queued runs, allow only the LOWEST GitHub run ID to collect.
    # The current run itself is not proof that another collector is running.
    done = [x for x in recoveries
            if x["status"] == "completed" and x["conclusion"] == "success"
            and x.get("capture_job_succeeded") is True]
    if done:
        return {"should_collect": False, "reason": "NO_OP_ALREADY_SUCCESSFUL_RECOVERY",
                "session": str(session), "recovery_runs": recoveries,
                "research_only": True}
    pending = [x for x in recoveries
               if x["status"] in ("queued", "in_progress", "waiting", "requested")]
    if current_run_id is None:
        # Pure synthetic use may omit the invoking ID; real GH recovery must
        # supply GITHUB_RUN_ID to avoid self-skip and simultaneous double work.
        other_pending = pending
    else:
        require(str(current_run_id).isdigit() and int(current_run_id) > 0,
                "INVOCATION_RUN_ID_INVALID")
        other_pending = [x for x in pending
                         if x["id"] < int(current_run_id)]
    if other_pending:
        return {"should_collect": False, "reason": "NO_OP_PRIOR_RECOVERY_IN_PROGRESS",
                "session": str(session), "recovery_runs": recoveries,
                "research_only": True}
    return {"should_collect": True, "reason": "RECOVERY_SOURCE_ELIGIBLE_NO_SUCCESSFUL_NORMAL_RUN",
            "session": str(session), "normal_runs": normal, "research_only": True,
            "NaturalCredit": 0, "OOSCredit": 0, "FormalEligible": False,
            "note": "Existing source workflow recovery trigger only; no new cron, not a normal source schedule."}


def fetch_runs(repo, token):
    require(bool(token), "GH_TOKEN_UNAVAILABLE")
    # Bounded index, read-only token. Do not use parent workflow artifacts,
    # PR-supplied code, tokens in stdout, or a different repository URL.
    url = "https://api.github.com/repos/" + repo + "/actions/workflows/" + WORKFLOW + "/runs?per_page=100"
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "stock-source-recovery-guard/2026-10-13"})
    with urllib.request.urlopen(req, timeout=15) as response:
        require(response.status == 200, "GITHUB_RUNS_HTTP_NON200")
        body = response.read(2_000_001)
        require(len(body) <= 2_000_000, "GITHUB_RUNS_TOO_LARGE")
    payload = json.loads(body)
    require(isinstance(payload, dict) and isinstance(payload.get("workflow_runs"), list),
            "GITHUB_RUN_INDEX_SCHEMA")
    rows = payload["workflow_runs"]
    # Green run != green capture: a workflow_run can succeed with the capture
    # job SKIPPED. Inspect the exact job conclusion for same-session earlier
    # recovery runs; do not let a no-op run suppress future genuine recovery.
    now = dt.datetime.now(dt.timezone.utc)
    session = source_session_date(now)
    cutoff = dt.datetime.combine(session, dt.time(20, 45), tzinfo=TZ).astimezone(dt.timezone.utc)
    candidates = [x for x in rows if isinstance(x, dict) and x.get("event") == "workflow_run"
                  and x.get("head_branch") == "main" and x.get("status") == "completed"
                  and x.get("conclusion") == "success" and
                  utc_time(x.get("created_at")) >= cutoff]
    require(len(candidates) <= 12, "TOO_MANY_SAME_SESSION_RECOVERY_RUNS")
    def read_jobs(run_id):
        require(type(run_id) is int and run_id > 0, "INVALID_RECOVERY_JOB_RUN_ID")
        url = "https://api.github.com/repos/" + repo + "/actions/runs/" + str(run_id) + "/jobs?per_page=100"
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "stock-source-recovery-guard/2026-10-13"})
        with urllib.request.urlopen(req, timeout=15) as response:
            require(response.status == 200, "RECOVERY_JOBS_HTTP_NON200")
            body = response.read(1_000_001)
            require(len(body) <= 1_000_000, "RECOVERY_JOBS_TOO_LARGE")
        doc = json.loads(body)
        require(isinstance(doc, dict) and isinstance(doc.get("jobs"), list),
                "RECOVERY_JOB_LIST_SCHEMA")
        hit = [z for z in doc["jobs"] if isinstance(z, dict)
               and z.get("name") == "collect-next-session-source"]
        require(len(hit) <= 1, "RECOVERY_COLLECTOR_DUPLICATED")
        return len(hit) == 1 and hit[0].get("conclusion") == "success"
    for record in candidates:
        record["capture_job_succeeded"] = read_jobs(record.get("id"))
    return rows


def selftest():
    now = dt.datetime(2026, 10, 14, 3, 50, tzinfo=TZ)
    parent = {"action": "completed", "workflow_run": {
        "name": PARENT, "event": "schedule", "head_branch": "main",
        "conclusion": "success", "status": "completed", "updated_at": "2026-10-13T19:50:00Z"}}
    normal = {"id": 5, "event": "schedule", "head_branch": "main",
              "created_at": "2026-10-13T12:48:00Z", "status": "completed", "conclusion": "success"}
    repo = "colinfgl/stock-data-helper"
    p = lambda e=parent, rs=None, at=now: decide(e, [] if rs is None else rs, at, repo)
    r = {}
    def test(name, f):
        try:
            r[name] = "PASS" if f() else "FAIL_ASSERT"
        except Exception as exc:
            r[name] = "FAIL_" + type(exc).__name__ + "_" + str(exc)[:80]
    test("missing_normal_source_allows_recovery", lambda: p()["should_collect"] is True)
    test("latest_successful_normal_skips", lambda: p(rs=[normal])["reason"] == "NO_OP_ALREADY_SUCCESSFUL_NORMAL_SOURCE")
    test("running_normal_skips", lambda: p(rs=[{**normal, "status":"in_progress", "conclusion": None}])["reason"] == "NO_OP_NORMAL_SOURCE_ALREADY_RUNNING")
    test("failed_normal_does_not_hide_recovery", lambda: p(rs=[{**normal, "conclusion":"failure"}])["should_collect"] is True)
    test("previous_day_success_not_duplicate", lambda: p(rs=[{**normal, "created_at":"2026-10-12T12:48:00Z"}])["should_collect"] is True)
    test("parent_push_rejected", lambda: p(e={**parent, "workflow_run":{**parent["workflow_run"],"event":"push"}})["should_collect"] is False)
    test("parent_failure_rejected", lambda: p(e={**parent, "workflow_run":{**parent["workflow_run"],"conclusion":"failure"}})["should_collect"] is False)
    test("parent_wrong_name_rejected", lambda: p(e={**parent, "workflow_run":{**parent["workflow_run"],"name":"unrelated"}})["should_collect"] is False)
    test("missing_parent_rejected", lambda: p(e={})["reason"] == "HOLD_NO_COMPLETED_PARENT")
    test("stale_parent_rejected", lambda: p(e={**parent, "workflow_run":{**parent["workflow_run"],"updated_at":"2026-10-12T18:00:00Z"}})["should_collect"] is False)
    test("early_parent_does_not_compete_with_primary", lambda: p(at=dt.datetime(2026,10,13,18,20,tzinfo=TZ),
        e={**parent, "workflow_run":{**parent["workflow_run"],"updated_at":"2026-10-13T10:20:00Z"}})["reason"] == "HOLD_BEFORE_PRIMARY_SOURCE_GRACE_WINDOW")
    test("after_grace_parent_allows_recovery",lambda: p(at=dt.datetime(2026,10,13,21,10,tzinfo=TZ),
        e={**parent, "workflow_run":{**parent["workflow_run"],"updated_at":"2026-10-13T13:10:00Z"}})["should_collect"] is True)
    test("recovery_is_never_formal", lambda: p()["NaturalCredit"] == p()["OOSCredit"] == 0 and p()["FormalEligible"] is False)
    test("session_rollover_no_yesterday_confusion", lambda: str(source_session_date(now)) == "2026-10-13")
    def invalid_date_is_rejected():
        try:
            p(rs=[{**normal,"created_at":"no-date"}])
        except ValueError:
            return True
        return False
    test("reject_invalid_schedule_run_date", invalid_date_is_rejected)
    prior_recovery = {"id": 6, "event": "workflow_run", "head_branch": "main",
                      "created_at": "2026-10-13T13:48:00Z", "status": "completed",
                      "conclusion": "success", "capture_job_succeeded": True}
    running_recovery = {**prior_recovery, "status": "in_progress", "conclusion": None}
    test("existing_successful_recovery_skips", lambda:
         p(rs=[prior_recovery], at=now)["reason"] == "NO_OP_ALREADY_SUCCESSFUL_RECOVERY")
    test("older_running_recovery_skips_newer", lambda:
         decide(parent, [{**running_recovery, "id": 4}], now, repo,
                current_run_id=5)["reason"] == "NO_OP_PRIOR_RECOVERY_IN_PROGRESS")
    test("higher_id_pending_does_not_block_lower", lambda:
         decide(parent, [{**running_recovery, "id": 7}], now, repo,
                current_run_id=5)["should_collect"] is True)
    test("own_recovery_run_is_not_its_own_duplicate", lambda:
         decide(parent, [{**running_recovery, "id": 5}], now, repo,
                current_run_id=5)["should_collect"] is True)
    test("failed_prior_recovery_can_be_retried", lambda:
         decide(parent, [{**prior_recovery, "conclusion": "failure"}], now, repo,
                current_run_id=7)["should_collect"] is True)
    test("qa_only_green_recovery_does_not_block_actual_collection", lambda:
         decide(parent, [{**prior_recovery, "capture_job_succeeded":False}], now, repo,
                current_run_id=7)["should_collect"] is True)
    def green_no_job_proof_blocks_safely():
        try: decide(parent, [{k:v for k,v in prior_recovery.items()
                             if k!="capture_job_succeeded"}],now,repo,current_run_id=7)
        except ValueError: return True
        return False
    test("no_claim_without_actual_capture_job_proof", green_no_job_proof_blocks_safely)
    ok = all(z == "PASS" for z in r.values())
    return {"status": "PASS" if ok else "FAIL", "passed": sum(x == "PASS" for x in r.values()),
            "total": len(r), "tests": r,
            "scope": "SYNTHETIC_PURE_GATE_NO_GITHUB_API_OR_FORMAL_NATURAL"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(selftest(), ensure_ascii=False))
        return 0 if selftest()["status"] == "PASS" else 2
    require(args.out, "OUTPUT_PATH_REQUIRED")
    now = dt.datetime.now(dt.timezone.utc)
    event = json.loads(pathlib.Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        runs = fetch_runs(repo, os.environ.get("GH_TOKEN", ""))
        result = decide(event, runs, now, repo, current_run_id=os.environ.get("GITHUB_RUN_ID"))
    except Exception as exc:
        result = {"should_collect": False,
                  "reason": "HOLD_SCHEDULE_INDEX_UNVERIFIED", "error_class": type(exc).__name__,
                  "error": str(exc)[:200], "research_only": True,
                  "NaturalCredit": 0, "OOSCredit": 0, "FormalEligible": False}
    result.update({"checked_at_utc": now.isoformat(), "parent_event": event.get("workflow_run",{}).get("event"),
                   "normal_run_not_promoted": True, "source_schedule_unchanged": True})
    dest=pathlib.Path(args.out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False) + "\n", encoding="utf8")
    gh_output=os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output,"a",encoding="utf8") as handle:
            handle.write("should_collect=" + ("true" if result["should_collect"] else "false") + "\n")
            if result["should_collect"]:
                verified_day=dt.date.fromisoformat(result["session"]).strftime("%Y%m%d")
                handle.write("source_day=" + verified_day + "\n")
    print(json.dumps({k:result[k] for k in ("should_collect","reason","checked_at_utc")},ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
