"""Offline only: fail-soft report handoff, not a natural worker or Sheet run."""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stock_settlement_native_receipt_bridge_20261018 import (
    EXPECTED_TASK, execute_report_preserving,
)
from stock_receipt_native_writer_v1_20261018 import RECEIPT_FIELDS, OBS_FIELDS


class SheetsDouble:
    def __init__(self):
        self.data = {
            "STOCK_Delivery_Receipt": [list(RECEIPT_FIELDS)],
            "STOCK_Delivery_Observability": [list(OBS_FIELDS)],
        }
        self.writes = 0

    def read_rows(self, spreadsheet_id, tab):
        return [list(row) for row in self.data[tab]]

    def append_row(self, spreadsheet_id, tab, row):
        self.data[tab].append(list(row))
        self.writes += 1


class FailAfterFirstAppend(SheetsDouble):
    def __init__(self):
        super().__init__()
        self.fail_second_once = True

    def append_row(self, spreadsheet_id, tab, row):
        if tab == "STOCK_Delivery_Observability" and self.fail_second_once:
            self.fail_second_once = False
            raise OSError("connector dropped after first real append")
        super().append_row(spreadsheet_id, tab, row)


class SecretBearingConnector(SheetsDouble):
    def read_rows(self, spreadsheet_id, tab):
        raise RuntimeError("client failed: bearer=never-expose-to-report")


def fixture():
    report = (b"2026-11-16 TEST-ONLY-NOT-NATURAL-20261115 "
              b"original-report-frozen-no-natural-credit")
    ctx = {
        "RunID": "TEST-ONLY-NOT-NATURAL-20261115",
        "TargetDate": "2026-11-16",
        "TaskProfile": "STOCK_SETTLEMENT",
        "TaskID": EXPECTED_TASK,
        "TriggerClass": "NORMAL_SCHEDULE",
        "OriginalReportBytesFromSameRun": True,
        "FrozenReportSHA": hashlib.sha256(report).hexdigest(),
        "GeneratedAt": "2026-11-15 19:01 Asia/Taipei",
        "CheckedAt": "2026-11-15 19:02 Asia/Taipei",
        "SaveReadbackStatus": "PASS",
        "ArtifactID": "fixture-not-a-real-report",
        "FormalEligible": False,
        "NaturalEligible": False,
        "ConfigID": "",
        "ConfigHash": "",
        "ConfigStatus": "NO_VALID_PRESEALED_CONFIG",
        "FinalStatus": "PARTIAL_RESEARCH_ONLY",
        "GovernanceBundleSHA": "f" * 64,
        "Schedule": "weekdays 19:00",
        "EnabledAtSeal": True,
        "NotificationsAtSeal": True,
        "EmailAtSeal": True,
    }
    return dict(
        context=ctx, report_bytes=report, client=SheetsDouble(),
        spreadsheet_id="TEST-ONLY-NOT-A-SPREADSHEET",
        lease_token="test-only-lease", lease_verified=True,
        worker_task_id=EXPECTED_TASK, native_code_verified=True,
        original_report_readback_verified=True)


class ReportPreservingTests(unittest.TestCase):
    def test_missing_original_bytes_never_claims_report_available(self):
        args = fixture()
        args["report_bytes"] = None
        output = execute_report_preserving(**args)
        self.assertEqual(output["status"], "REPORT_UNAVAILABLE_NATIVE_WRITE_HOLD")
        self.assertEqual(output["native_write_state"], "NOT_ATTEMPTED")
        self.assertEqual(args["client"].writes, 0)

    def test_missing_owned_lease_keeps_report_without_writes(self):
        args = fixture()
        args["lease_verified"] = False
        output = execute_report_preserving(**args)
        self.assertEqual(output["status"], "REPORT_AVAILABLE_NATIVE_WRITE_HOLD")
        self.assertIs(output["report_bytes"], args["report_bytes"])
        self.assertEqual(output["reason_code"], "OWNED_LIVE_LEASE_REQUIRED")
        self.assertEqual(args["client"].writes, 0)
        self.assertFalse(output["platform_delivery_verified"])
        self.assertFalse(output["natural_credit_granted_by_bridge"])

    def test_no_authenticated_client_keeps_report(self):
        args = fixture()
        args["client"] = None
        output = execute_report_preserving(**args)
        self.assertEqual(output["reason_code"], "AUTHORIZED_SHEETS_CLIENT_REQUIRED")
        self.assertIs(output["report_bytes"], args["report_bytes"])

    def test_wrong_task_does_not_write(self):
        args = fixture()
        args["worker_task_id"] = "wrong"
        output = execute_report_preserving(**args)
        self.assertEqual(output["reason_code"], "WRONG_SETTLEMENT_TASK")
        self.assertEqual(args["client"].writes, 0)

    def test_original_report_sha_gate_remains_closed(self):
        args = fixture()
        args["context"]["FrozenReportSHA"] = "0" * 64
        output = execute_report_preserving(**args)
        self.assertEqual(output["reason_code"], "FROZEN_REPORT_SHA_MISMATCH")
        self.assertEqual(args["client"].writes, 0)

    def test_dual_readback_still_does_not_prove_platform_delivery(self):
        args = fixture()
        output = execute_report_preserving(**args)
        self.assertEqual(output["status"], "REPORT_AVAILABLE_NATIVE_DUAL_READBACK_PASS")
        self.assertIs(output["report_bytes"], args["report_bytes"])
        self.assertEqual(output["native_write_state"], "DUAL_READBACK_PASS")
        self.assertEqual(args["client"].writes, 2)
        self.assertFalse(output["platform_delivery_verified"])
        self.assertFalse(output["natural_credit_granted_by_bridge"])

    def test_one_table_partial_write_is_not_misreported_as_zero(self):
        args = fixture()
        args["client"] = FailAfterFirstAppend()
        first = execute_report_preserving(**args)
        self.assertEqual(first["status"], "REPORT_AVAILABLE_NATIVE_WRITE_HOLD")
        self.assertEqual(first["native_write_state"], "UNVERIFIED_POSSIBLE_PARTIAL")
        self.assertIs(first["report_bytes"], args["report_bytes"])
        self.assertEqual(args["client"].writes, 1)
        self.assertEqual(len(args["client"].data["STOCK_Delivery_Receipt"]), 2)
        self.assertEqual(len(args["client"].data["STOCK_Delivery_Observability"]), 1)
        second = execute_report_preserving(**args)
        self.assertEqual(second["status"], "REPORT_AVAILABLE_NATIVE_DUAL_READBACK_PASS")
        self.assertEqual(args["client"].writes, 2)
        self.assertEqual(second["native_write_result"]["native_receipts"][
            "STOCK_Delivery_Receipt"], "NO_OP_READBACK_PASS")

    def test_connector_secrets_are_not_echoed(self):
        args = fixture()
        args["client"] = SecretBearingConnector()
        output = execute_report_preserving(**args)
        self.assertEqual(output["reason_code"], "NATIVE_WRITE_UNVERIFIED_ERROR")
        self.assertNotIn("never-expose", repr(output))
        self.assertIs(output["report_bytes"], args["report_bytes"])


if __name__ == "__main__":
    unittest.main()
