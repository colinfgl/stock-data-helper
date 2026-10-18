import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stock_settlement_native_receipt_bridge_20261018 import execute_same_run, EXPECTED_TASK

class NoClient:
    def read_rows(self, *_):
        raise AssertionError("MUST_NOT_READ_BEFORE_PRECHECK")
    def append_row(self, *_):
        raise AssertionError("MUST_NOT_WRITE")

def kwargs():
    return dict(context={"TaskProfile":"STOCK_SETTLEMENT","TriggerClass":"NORMAL_SCHEDULE"},
                report_bytes=b"test", client=NoClient(), spreadsheet_id="control",
                lease_token="lease", lease_verified=True,
                worker_task_id=EXPECTED_TASK,
                native_code_verified=True, original_report_readback_verified=True)

class GuardTests(unittest.TestCase):
    def test_reject_wrong_task(self):
        x=kwargs();x["worker_task_id"]="other"
        with self.assertRaisesRegex(PermissionError,"WRONG_SETTLEMENT_TASK"):
            execute_same_run(**x)
    def test_reject_manual_trigger(self):
        x=kwargs();x["context"]["TriggerClass"]="MANUAL"
        with self.assertRaisesRegex(PermissionError,"NOT_GENUINE_SCHEDULED_RUN"):
            execute_same_run(**x)
    def test_reject_unverified_original_report(self):
        x=kwargs();x["original_report_readback_verified"]=False
        with self.assertRaisesRegex(PermissionError,"SOURCE_OR_REPORT_NOT_VERIFIED"):
            execute_same_run(**x)
    def test_reject_missing_lease(self):
        x=kwargs();x["lease_verified"]=False
        with self.assertRaisesRegex(PermissionError,"OWNED_LIVE_LEASE_REQUIRED"):
            execute_same_run(**x)
    def test_reject_no_authorized_client(self):
        x=kwargs();x["client"]=None
        with self.assertRaisesRegex(PermissionError,"AUTHORIZED_SHEETS_CLIENT_REQUIRED"):
            execute_same_run(**x)

if __name__=="__main__":
    unittest.main()
