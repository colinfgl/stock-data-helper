"""Offline positive end-to-end bridge test. Not evidence of a natural worker."""
import hashlib
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stock_settlement_native_receipt_bridge_20261018 import execute_same_run,EXPECTED_TASK
from stock_receipt_native_writer_v1_20261018 import RECEIPT_FIELDS,OBS_FIELDS

class SheetsDouble:
    def __init__(self):
        self.data={"STOCK_Delivery_Receipt":[list(RECEIPT_FIELDS)],
                   "STOCK_Delivery_Observability":[list(OBS_FIELDS)]}
        self.writes=0
    def read_rows(self,_,tab):
        return [list(x) for x in self.data[tab]]
    def append_row(self,_,tab,row):
        self.data[tab].append(list(row))
        self.writes+=1

def context():
    run="TEST-ONLY-NOT-NATURAL-20261019"
    date="2026-10-19"
    b=f"{date} {run} research-only example".encode()
    ctx=dict(RunID=run,TargetDate=date,TaskProfile="STOCK_SETTLEMENT",
        TaskID=EXPECTED_TASK,TriggerClass="NORMAL_SCHEDULE",
        OriginalReportBytesFromSameRun=True,FrozenReportSHA=hashlib.sha256(b).hexdigest(),
        GeneratedAt="2026-10-19 19:01 Asia/Taipei",CheckedAt="2026-10-19 19:03 Asia/Taipei",
        SaveReadbackStatus="PASS",ArtifactID="fixture-only-not-real",
        FormalEligible=False,NaturalEligible=False,ConfigID="",ConfigHash="",
        ConfigStatus="NO_VALID_PRESEALED_CONFIG",FinalStatus="PARTIAL_RESEARCH_ONLY",
        GovernanceBundleSHA="f"*64,Schedule="weekdays 19:00",
        EnabledAtSeal=True,NotificationsAtSeal=True,EmailAtSeal=True)
    return ctx,b

class IntegrationTests(unittest.TestCase):
    def test_append_both_then_noop(self):
        fake=SheetsDouble()
        ctx,report=context()
        args=dict(context=ctx,report_bytes=report,client=fake,spreadsheet_id="FICTIONAL_FIXTURE",
            lease_token="fixture-lease",lease_verified=True,worker_task_id=EXPECTED_TASK,
            native_code_verified=True,original_report_readback_verified=True)
        a=execute_same_run(**args)
        self.assertEqual(a["status"],"DUAL_NATIVE_READBACK_PASS")
        self.assertEqual(fake.writes,2)
        self.assertEqual(a["native_receipts"]["STOCK_Delivery_Receipt"],"APPEND_READBACK_PASS")
        self.assertFalse(a["natural_credit_granted_by_bridge"])
        b=execute_same_run(**args)
        self.assertEqual(fake.writes,2)
        self.assertEqual(b["native_receipts"]["STOCK_Delivery_Receipt"],"NO_OP_READBACK_PASS")

    def test_resume_one_table_only(self):
        fake=SheetsDouble()
        ctx,report=context()
        args=dict(context=ctx,report_bytes=report,client=fake,spreadsheet_id="FICTIONAL_FIXTURE",
            lease_token="fixture-lease",lease_verified=True,worker_task_id=EXPECTED_TASK,
            native_code_verified=True,original_report_readback_verified=True)
        execute_same_run(**args)
        fake.data["STOCK_Delivery_Observability"].pop()
        self.assertEqual(fake.writes,2)
        out=execute_same_run(**args)
        self.assertEqual(fake.writes,3)
        self.assertEqual(out["native_receipts"]["STOCK_Delivery_Receipt"],"NO_OP_READBACK_PASS")
        self.assertEqual(out["native_receipts"]["STOCK_Delivery_Observability"],"APPEND_READBACK_PASS")

    def test_wrong_sha_blocks_before_append(self):
        fake=SheetsDouble()
        ctx,report=context()
        ctx["FrozenReportSHA"]="0"*64
        with self.assertRaisesRegex(ValueError,"FROZEN_REPORT_SHA_MISMATCH"):
            execute_same_run(context=ctx,report_bytes=report,client=fake,
                spreadsheet_id="FICTIONAL_FIXTURE",lease_token="fixture-lease",
                lease_verified=True,worker_task_id=EXPECTED_TASK,
                native_code_verified=True,original_report_readback_verified=True)
        self.assertEqual(fake.writes,0)

if __name__=="__main__":unittest.main()
