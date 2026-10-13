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


def decide(event, records, now, repository):
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
    normal = []
    for run in records:
        require(isinstance(run, dict), "BAD_RUN_RECORD")
        if run.get("event") != "schedule" or run.get("head_branch") != "main":
            continue
        created = utc_time(run.get("created_at"))
        if created >= cutoff and created <= nowutc + dt.timedelta(seconds=120):
            normal.append({"id": run.get("id"), "status": run.get("status"),
                           "conclusion": run.get("conclusion"),
                           "created_at": run.get("created_at")})
    successful = [x for x in normal if x["status"] == "completed" and x["conclusion"] == "success"]
    # An original still-running normal run has priority: no competing collector.
    running = [x for x in normal if x["status"] in ("queued", "in_progress", "waiting", "requested")]
    if successful:
        return {"should_collect": False, "reason": "NO_OP_ALREADY_SUCCESSFUL_NORMAL_SOURCE",
                "session": str(session), "normal_runs": normal, "research_only": True}
    if running:
        return {"should_collect": False, "reason": "NO_OP_NORMAL_SOURCE_ALREADY_RUNNING",
                "session": str(session), "normal_runs": normal, "research_only": True}
    return {"should_collect": True, "reason": "RECOVERY_SOURCE_ELIGIBLE_NO_SUCCESSFUL_NORMAL_RUN",
            "session": str(session), "normal_runs": normal, "research_only": True,
            "NaturalCredit": 0, "OOSCredit": 0, "FormalEligible": False,
            "note": "Existing source workflow recovery trigger only; no new cron, not a normal source schedule."}


def fetch_runs(repo, token):
    require(bool(token), "GH_TOKEN_UNAVAILABLE")
    # Bounded index, read-only token. Do not use parent workflow artifacts,
    # PR-supplied code, tokens in stdout, or a different repository URL.
    url = "https://api.github.com/repos/" + repo + "/actions/workflows/" + WORKFLOW + "/runs?event=schedule&per_page=100"
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
    return payload["workflow_runs"]


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
        result = decide(event, runs, now, repo)
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
    print(json.dumps({k:result[k] for k in ("should_collect","reason","checked_at_utc")},ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
