"""Invoke the EXISTING v11 terminalizer + native writer in one verified call.

An authorized NORMAL_SCHEDULE worker must inject the original frozen report
bytes, trustworthy run context, a live authenticated Sheets client, and an
independently verified writer lease. This module has no scheduler credentials.
It never invents START, raw market prices, Config, Natural/OOS, or delivery.
"""
from __future__ import annotations

from stock_delivery_terminalizer_v11_20261014 import receipt_plan, plan_actions
from stock_receipt_native_writer_v1_20261018 import (
    RECEIPT_FIELDS, OBS_FIELDS, write_native_receipts,
)

EXPECTED_TASK = "6a825a73808c81918c5c7b5d1fecaf28"
RECEIPT = "STOCK_Delivery_Receipt"
OBS = "STOCK_Delivery_Observability"

# These are fixed, non-sensitive failure codes emitted by the settlement
# bridge/gates. Arbitrary connector exception text must not be sent to users:
# it may include spreadsheet IDs, tokens, URLs, or other private details.
SAFE_HOLD_REASONS = frozenset({
    "WRONG_SETTLEMENT_TASK",
    "CONTEXT_TASK_ID_MISMATCH",
    "WRONG_TASK_PROFILE",
    "NOT_GENUINE_SCHEDULED_RUN",
    "SOURCE_OR_REPORT_NOT_VERIFIED",
    "OWNED_LIVE_LEASE_REQUIRED",
    "AUTHORIZED_SHEETS_CLIENT_REQUIRED",
    "DELIVERY_RECEIPT_SCHEMA_DRIFT",
    "DELIVERY_OBSERVABILITY_SCHEMA_DRIFT",
    "NATIVE_WRITE_PLAN_HOLD",
    "INCOMPLETE_DUAL_TABLE_READBACK",
    "TASK_RUN_IDENTITY_INVALID",
    "NO_SAME_RUN_ORIGINAL_TRIGGER_CONTEXT",
    "NO_SAME_RUN_ORIGINAL_REPORT_BYTES",
    "ORIGINAL_REPORT_RAW_BYTES_MISSING",
    "FROZEN_REPORT_SHA_MISMATCH",
    "REPORT_BODY_RUN_DATE_MISMATCH",
    "SAVE_READBACK_STATUS_EXPLICIT_REQUIRED",
    "SAVE_PASS_WITHOUT_ARTIFACT",
    "UNSAVED_CANNOT_BE_NATURAL",
    "NATURAL_WITHOUT_FORMAL_FORBIDDEN",
    "NATURAL_REQUIRES_INDEPENDENT_MORNING_AND_SAME_RUN_PROOF",
    "TERMINAL_FINAL_STATUS_MISSING",
    "UNSAVED_RESULT_MUST_HAVE_TRUTHFUL_TERMINAL_STATUS",
    "CONFIG_ID_SHA_PARTIAL_INCONSISTENCY",
    "MISSING_CONFIG_REQUIRES_EXPLICIT_FORMAL_NATURAL_FALSE",
    "MISSING_CONFIG_NOT_EXPLICITLY_CLASSIFIED",
    "BUNDLE_SHA_MISSING",
    "PLATFORM_EVIDENCE_UNVERIFIED_DO_NOT_PROMOTE",
    "RECEIPT_FIELD_COUNT_INVALID",
    "PLAN_NOT_WRITEABLE",
    "CROSS_TABLE_IDENTITY_MISMATCH",
    "FROZEN_PLAN_IDENTITY_MISMATCH",
    "UNVERIFIED_PLAN_AUTHORITY",
    "PLAN_ALREADY_EXECUTED",
    "STOCK_Delivery_Receipt_HEADER_DRIFT",
    "STOCK_Delivery_Receipt_ROW_WIDTH_OVERFLOW",
    "STOCK_Delivery_Receipt_DUPLICATE_KEY",
    "STOCK_Delivery_Receipt_CONTENT_CONFLICT",
    "STOCK_Delivery_Receipt_STALE_ACTION",
    "STOCK_Delivery_Receipt_READBACK_MISSING",
    "STOCK_Delivery_Observability_HEADER_DRIFT",
    "STOCK_Delivery_Observability_ROW_WIDTH_OVERFLOW",
    "STOCK_Delivery_Observability_DUPLICATE_KEY",
    "STOCK_Delivery_Observability_CONTENT_CONFLICT",
    "STOCK_Delivery_Observability_STALE_ACTION",
    "STOCK_Delivery_Observability_READBACK_MISSING",
})


def execute_same_run(*, context, report_bytes, client, spreadsheet_id,
                     lease_token, lease_verified, worker_task_id,
                     native_code_verified, original_report_readback_verified):
    """Append and read back both live tables, or fail closed before writing.

    Receipt-plan actions are based on the full current live rows; the writer
    rechecks both headers/keys before appending and verifies after append.
    A partial write is resumable under a newly verified lease.
    """
    if worker_task_id != EXPECTED_TASK:
        raise PermissionError("WRONG_SETTLEMENT_TASK")
    if context.get("TaskID") != EXPECTED_TASK:
        raise PermissionError("CONTEXT_TASK_ID_MISMATCH")
    if context.get("TaskProfile") != "STOCK_SETTLEMENT":
        raise PermissionError("WRONG_TASK_PROFILE")
    if context.get("TriggerClass") != "NORMAL_SCHEDULE":
        raise PermissionError("NOT_GENUINE_SCHEDULED_RUN")
    if not native_code_verified or not original_report_readback_verified:
        raise PermissionError("SOURCE_OR_REPORT_NOT_VERIFIED")
    if not lease_verified or not lease_token:
        raise PermissionError("OWNED_LIVE_LEASE_REQUIRED")
    if not spreadsheet_id or client is None:
        raise PermissionError("AUTHORIZED_SHEETS_CLIENT_REQUIRED")
    receipt_rows = client.read_rows(spreadsheet_id, RECEIPT)
    obs_rows = client.read_rows(spreadsheet_id, OBS)
    if not receipt_rows or tuple(receipt_rows[0]) != RECEIPT_FIELDS:
        raise ValueError("DELIVERY_RECEIPT_SCHEMA_DRIFT")
    if not obs_rows or tuple(obs_rows[0]) != OBS_FIELDS:
        raise ValueError("DELIVERY_OBSERVABILITY_SCHEMA_DRIFT")
    plan = receipt_plan(context, report_bytes, receipt_rows[0], obs_rows[0])
    actions = plan_actions(plan, receipt_rows, obs_rows)
    if not actions["AutoWriteAllowed"]:
        raise ValueError("NATIVE_WRITE_PLAN_HOLD")
    readbacks = write_native_receipts(
        plan=plan, actions=actions, client=client,
        spreadsheet_id=spreadsheet_id,
        lease_token=lease_token, lease_verified=lease_verified)
    if set(readbacks) != {RECEIPT, OBS}:
        raise RuntimeError("INCOMPLETE_DUAL_TABLE_READBACK")
    return {"status": "DUAL_NATIVE_READBACK_PASS",
            "RunID": plan["RunID"], "TargetDate": plan["TargetDate"],
            "ReportSHA": plan["ReportSHA"],
            "native_receipts": readbacks,
            "platform_delivery_verified": False,
            "natural_credit_granted_by_bridge": False}


def execute_report_preserving(*, context, report_bytes, client, spreadsheet_id,
                              lease_token, lease_verified, worker_task_id,
                              native_code_verified,
                              original_report_readback_verified):
    """Keep the original report available even if a native write fails.

    The original worker must explicitly render/deliver ``report_bytes`` after
    calling this adapter. Returning bytes is NOT platform delivery proof.
    A failed dual write may have appended the first table already, so its
    state is always UNVERIFIED_POSSIBLE_PARTIAL until a trusted readback.
    This wrapper never grants formal, natural, or delivery credit and does not
    weaken the fail-closed ``execute_same_run`` entry point.
    """
    if not isinstance(report_bytes, bytes) or not report_bytes:
        return {
            "status": "REPORT_UNAVAILABLE_NATIVE_WRITE_HOLD",
            "report_bytes": report_bytes,
            "reason_code": "ORIGINAL_REPORT_RAW_BYTES_MISSING",
            "native_write_state": "NOT_ATTEMPTED",
            "platform_delivery_verified": False,
            "natural_credit_granted_by_bridge": False,
        }
    try:
        result = execute_same_run(
            context=context, report_bytes=report_bytes, client=client,
            spreadsheet_id=spreadsheet_id, lease_token=lease_token,
            lease_verified=lease_verified, worker_task_id=worker_task_id,
            native_code_verified=native_code_verified,
            original_report_readback_verified=original_report_readback_verified)
    except Exception as exc:
        code = str(exc)
        if code not in SAFE_HOLD_REASONS:
            code = "NATIVE_WRITE_UNVERIFIED_ERROR"
        return {
            "status": "REPORT_AVAILABLE_NATIVE_WRITE_HOLD",
            "report_bytes": report_bytes,
            "reason_code": code,
            "native_write_state": "UNVERIFIED_POSSIBLE_PARTIAL",
            "platform_delivery_verified": False,
            "natural_credit_granted_by_bridge": False,
        }
    return {
        "status": "REPORT_AVAILABLE_NATIVE_DUAL_READBACK_PASS",
        "report_bytes": report_bytes,
        "native_write_result": result,
        "native_write_state": "DUAL_READBACK_PASS",
        "platform_delivery_verified": False,
        "natural_credit_granted_by_bridge": False,
    }
