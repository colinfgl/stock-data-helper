#!/usr/bin/env python3
"""Fail-closed read-only preflight for a proposed STOCK_SETTLEMENT task update.
Does NOT deploy, create tasks, or credit Natural/OOS.
Usage: python scripts/stock_settlement_prompt_preflight_20261018.py before.json proposed.json
Both files must contain id, prompt, schedule, is_enabled, timing_mode,
notifications_enabled and email_enabled from an actual task snapshot.
"""
import hashlib
import json
import sys

ID = "6a825a73808c81918c5c7b5d1fecaf28"
REQUIRED = (
    "TerminalizerNativeProtocol=", "TerminalizerSourceRepository=",
    "TerminalizerSourceCommit=", "TerminalizerPythonSHA256=",
    "GovernanceSuccessorHandoff=", "NextConfigExecutableHandoff=",
    "H9SecondaryBaselineReadRoute=", "---BOOTSTRAP_BODY---",
)
UNCHANGED = ("id", "schedule", "is_enabled", "timing_mode",
             "notifications_enabled", "email_enabled")
MARKER = "---BOOTSTRAP_BODY---\n"

def sha_body(prompt):
    if prompt.count(MARKER) != 1:
        raise ValueError("MISSING_OR_DUPLICATED_MARKER")
    body = prompt.split(MARKER, 1)[1].replace("\r\n", "\n")
    if body.endswith("\n"):
        body = body[:-1]
    return hashlib.sha256(body.encode("utf-8")).hexdigest()

def check(before, proposed):
    issues = []
    if before.get("id") != ID or proposed.get("id") != ID:
        issues.append("WRONG_TASK_ID")
    for field in UNCHANGED:
        if field not in before or field not in proposed:
            issues.append("MISSING_FIELD_" + field)
        elif before[field] != proposed[field]:
            issues.append("UNAUTHORIZED_CHANGE_" + field)
    old, new = before.get("prompt", ""), proposed.get("prompt", "")
    if not isinstance(old, str) or not isinstance(new, str):
        return ["PROMPT_NOT_STRING"]
    if len(new.encode("utf-8")) < len(old.encode("utf-8")):
        issues.append("PROMPT_LENGTH_REGRESSION")
    for item in REQUIRED:
        if item not in new:
            issues.append("MISSING_REQUIRED_" + item)
    try:
        if sha_body(old) != sha_body(new):
            issues.append("IMMUTABLE_BODY_CHANGED")
        sha = sha_body(new)
        declaration = next((line.split("=", 1)[1] for line in new.splitlines()
                           if line.startswith("BootstrapBodySHA256=")), None)
        if declaration != sha:
            issues.append("BOOTSTRAP_SHA_MISMATCH")
    except ValueError as exc:
        issues.append(str(exc))
    # An incomplete pre-accident snapshot must not be treated as evidence of v11.
    for item in REQUIRED:
        if item not in old:
            issues.append("ORIGINAL_SNAPSHOT_INCOMPLETE_" + item)
    return issues

def main():
    if len(sys.argv) != 3:
        print("Usage: script before.json proposed.json", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as fh:
        before = json.load(fh)
    with open(sys.argv[2], encoding="utf-8") as fh:
        proposed = json.load(fh)
    issues = check(before, proposed)
    print(json.dumps({"status": "BLOCK" if issues else "PASS_READONLY_PREFLIGHT",
                      "issues": issues}, ensure_ascii=False))
    return 1 if issues else 0

if __name__ == "__main__":
    raise SystemExit(main())
