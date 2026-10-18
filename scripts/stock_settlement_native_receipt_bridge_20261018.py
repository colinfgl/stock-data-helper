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
