#!/usr/bin/env python3
"""Prepare a STOCK_SETTLEMENT prompt change for review; NEVER deploy by itself.

Fail closed until independently archived pre-accident v11 original is supplied.
Inputs are JSON snapshots with actual task fields and complete prompts.
Produces a content-addressed manifest only after comparing archive -> candidate,
AND live -> candidate task settings; no automation APIs are called.
"""
import hashlib
import json
import sys
from pathlib import Path

from stock_settlement_prompt_preflight_20261018 import check, sha_body

TASK = "6a825a73808c81918c5c7b5d1fecaf28"
SETTINGS = ("id", "schedule", "is_enabled", "timing_mode",
            "notifications_enabled", "email_enabled")

def prepare(archive, live, candidate):
    problems = []
    for x, role in ((archive, "archive"), (live, "live"), (candidate, "candidate")):
        if x.get("id") != TASK:
            problems.append(role + ":WRONG_TASK")
        if not isinstance(x.get("prompt"), str):
            problems.append(role + ":PROMPT_MISSING")
    for key in SETTINGS:
        if not all(key in x for x in (archive, live, candidate)):
            problems.append("MISSING_SETTING:" + key)
        elif any(x[key] != live[key] for x in (archive, candidate)):
            problems.append("SETTINGS_MISMATCH:" + key)
    if problems:
        return {"status": "BLOCK", "reasons": problems}
    checks = check(archive, candidate)
    if checks:
        return {"status": "BLOCK", "reasons": checks}
    if archive["prompt"] != candidate["prompt"]:
        # Exact restoration only. New governance-generation deployments need
        # separate explicit authorization and independent review.
        return {"status": "BLOCK", "reasons": ["NOT_EXACT_PREACCIDENT_V11"]}
    if archive["prompt"] == live["prompt"]:
        return {"status": "NO_OP_ALREADY_MATCHES", "reasons": []}
    body_digest = sha_body(candidate["prompt"])
    prompt_sha = hashlib.sha256(candidate["prompt"].encode("utf-8")).hexdigest()
    return {"status": "READY_FOR_INDEPENDENT_AUTHORIZED_REVIEW",
            "task_id": TASK, "prompt_sha256": prompt_sha,
            "bootstrap_sha256": body_digest, "prompt_chars": len(candidate["prompt"]),
            "settings": {k: live[k] for k in SETTINGS},
            "applies_to_live_prompt_sha256":
                hashlib.sha256(live["prompt"].encode("utf-8")).hexdigest(),
            "natural_credit": 0, "deployment_executed": False}

def main(argv):
    if len(argv) != 4:
        print("Usage: ... archived_v11.json live.json candidate.json", file=sys.stderr)
        return 2
    a, l, c = (json.loads(Path(s).read_text(encoding="utf-8")) for s in argv[1:])
    result = prepare(a, l, c)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"].startswith(("READY_", "NO_OP_")) else 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
