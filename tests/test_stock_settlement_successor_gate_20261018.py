import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stock_settlement_prepare_deployment_20261018 import prepare_successor

TASK = "6a825a73808c81918c5c7b5d1fecaf28"
BODY = "sealed current settlement bootstrap"

def snap(version):
    sha = hashlib.sha256(BODY.encode()).hexdigest()
    envelope = (
        "BootstrapBodySHA256=" + sha + "\n"
        "RuntimeSupplementVersion=" + version + "\n"
        "TerminalizerNativeProtocol=verified\n"
        "TerminalizerSourceRepository=colinfgl/stock-data-helper\n"
        "TerminalizerSourceCommit=b157cab3df069bfbce897c629d40497a27d0d531\n"
        "TerminalizerPythonSHA256=" + "9" * 64 + "\n"
        "GovernanceSuccessorHandoff=verified\n"
        "NextConfigExecutableHandoff=verified\n"
        "H9SecondaryBaselineReadRoute=verified\n"
        "---BOOTSTRAP_BODY---\n" + BODY
    )
    return {"id": TASK, "prompt": envelope, "schedule": "weekdays 19:00",
            "is_enabled": True, "timing_mode": "exact_schedule",
            "notifications_enabled": True, "email_enabled": True}

def evidence(live):
    return {key: "qualified-receipt" for key in (
        "governance_approval_receipt", "fresh_two_task_rollback_receipt",
        "native_terminal_readback_receipt", "successor_bundle_readback_receipt"
    )} | {"live_task_snapshot_sha256": hashlib.sha256(live["prompt"].encode()).hexdigest()}

class SuccessorGateTests(unittest.TestCase):
    def test_missing_all_evidence_blocks(self):
        x = snap("STOCK-SETTLEMENT-RECOVERY-20261018")
        self.assertEqual(prepare_successor(x, snap("STOCK-SETTLEMENT-SUCCESSOR-20261018"), {})["status"], "BLOCK_NEW_SUCCESSOR")

    def test_stale_snapshot_blocks(self):
        x = snap("STOCK-SETTLEMENT-RECOVERY-20261018")
        e = evidence(x); e["live_task_snapshot_sha256"] = "f" * 64
        self.assertIn("STALE_LIVE_SNAPSHOT_SHA", prepare_successor(x, snap("STOCK-SETTLEMENT-SUCCESSOR-20261018"), e)["reasons"])

    def test_mutated_bootstrap_blocks(self):
        x = snap("STOCK-SETTLEMENT-RECOVERY-20261018")
        y = snap("STOCK-SETTLEMENT-SUCCESSOR-20261018")
        y["prompt"] = y["prompt"].replace(BODY, BODY + "changed")
        self.assertIn("IMMUTABLE_BOOTSTRAP_BODY_CHANGED", prepare_successor(x, y, evidence(x))["reasons"])

    def test_time_change_blocks(self):
        x = snap("STOCK-SETTLEMENT-RECOVERY-20261018")
        y = snap("STOCK-SETTLEMENT-SUCCESSOR-20261018"); y["schedule"] = "18:00"
        self.assertIn("SETTINGS_DRIFT_schedule", prepare_successor(x, y, evidence(x))["reasons"])

    def test_recovery_not_a_successor(self):
        x = snap("STOCK-SETTLEMENT-RECOVERY-20261018")
        y = snap("STOCK-SETTLEMENT-RECOVERY-20261018")
        self.assertIn("SUCCESSOR_GENERATION_NOT_DECLARED", prepare_successor(x, y, evidence(x))["reasons"])

    def test_full_synthetic_evidence_only_passes_structure_not_deploy(self):
        x = snap("STOCK-SETTLEMENT-RECOVERY-20261018")
        y = snap("STOCK-SETTLEMENT-SUCCESSOR-20261018")
        result = prepare_successor(x, y, evidence(x))
        self.assertEqual(result["status"], "READY_FOR_SEPARATE_AUTHORIZED_CUTOVER")
        self.assertFalse(result["deployment_executed"])
        self.assertEqual(result["natural_credit"], 0)

if __name__ == "__main__":
    unittest.main()
