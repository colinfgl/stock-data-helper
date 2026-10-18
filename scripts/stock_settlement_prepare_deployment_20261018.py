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

def prepare_successor(live, candidate, evidence):
    """Stage a NEW governed generation, not a historical v11 restoration.

    Requires authenticated evidence from a separate change-governance process.
    Never calls the automation update API.
    """
    from stock_settlement_prompt_preflight_20261018 import sha_body, split_prompt, envelope_values
    issues = []
    if not isinstance(live, dict) or not isinstance(candidate, dict) or not isinstance(evidence, dict):
        return {"status": "BLOCK", "reasons": ["INVALID_INPUT"]}
    for role, item in (("LIVE", live), ("CANDIDATE", candidate)):
        if item.get("id") != TASK:
            issues.append(role + "_TASK_ID_MISMATCH")
        if not isinstance(item.get("prompt"), str):
            issues.append(role + "_PROMPT_MISSING")
    for key in SETTINGS:
        if key not in live or key not in candidate:
            issues.append("MISSING_SETTING_" + key)
        elif live[key] != candidate[key]:
            issues.append("SETTINGS_DRIFT_" + key)
    # These fields are receipts from distinct authorities, not assertions from
    # the candidate document itself. Default DENY when any receipt is absent.
    for key in ("governance_approval_receipt", "fresh_two_task_rollback_receipt",
                "native_terminal_readback_receipt", "successor_bundle_readback_receipt",
                "live_task_snapshot_sha256"):
        if not isinstance(evidence.get(key), str) or not evidence[key].strip():
            issues.append("MISSING_EVIDENCE_" + key)
    if issues:
        return {"status": "BLOCK_NEW_SUCCESSOR", "reasons": issues}
    live_sha = hashlib.sha256(live["prompt"].encode("utf-8")).hexdigest()
    if evidence["live_task_snapshot_sha256"] != live_sha:
        issues.append("STALE_LIVE_SNAPSHOT_SHA")
    try:
        live_body_sha = sha_body(live["prompt"])
        next_body_sha = sha_body(candidate["prompt"])
        if live_body_sha != next_body_sha:
            issues.append("IMMUTABLE_BOOTSTRAP_BODY_CHANGED")
        env, _ = split_prompt(candidate["prompt"])
        fields = envelope_values(env, issues, "SUCCESSOR_")
        if fields.get("BootstrapBodySHA256") != next_body_sha:
            issues.append("BOOTSTRAP_DECLARATION_MISMATCH")
        if fields.get("RuntimeSupplementVersion", "").startswith("STOCK-SETTLEMENT-RECOVERY-"):
            issues.append("SUCCESSOR_GENERATION_NOT_DECLARED")
    except ValueError as exc:
        issues.append(str(exc))
    # The local checker cannot authenticate approvals, native Google Sheets
    # readbacks or a genuinely fresh two-task rollback. Arbitrary nonempty
    # strings must NEVER be sufficient to authorize a live task mutation.
    # Only an independently verified external control-plane cutover may
    # transition this state. Keep this preparation tool permanently read-only.
    issues.append("EXTERNAL_AUTHORITY_RECEIPTS_NOT_CRYPTOGRAPHICALLY_VERIFIED")
    if issues:
        return {"status": "BLOCK_NEW_SUCCESSOR", "reasons": issues}
    return {"status": "READY_FOR_SEPARATE_AUTHORIZED_CUTOVER",
            "deployment_executed": False, "natural_credit": 0,
            "task_id": TASK, "live_prompt_sha256": live_sha,
            "candidate_prompt_sha256": hashlib.sha256(candidate["prompt"].encode("utf-8")).hexdigest()}

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
