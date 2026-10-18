import hashlib
import unittest
from scripts.stock_settlement_prompt_preflight_20261018 import check

TID = "6a825a73808c81918c5c7b5d1fecaf28"
BODY = "執行 STOCK_SETTLEMENT（R151.6 FINAL-v17）。"
REQUIRED = ["TerminalizerNativeProtocol=", "TerminalizerSourceRepository=",
            "TerminalizerSourceCommit=", "TerminalizerPythonSHA256=",
            "GovernanceSuccessorHandoff=", "NextConfigExecutableHandoff=",
            "H9SecondaryBaselineReadRoute="]

def snapshot():
    digest = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    prompt = ("BootstrapBodySHA256=" + digest + "\n" +
              "\n".join(REQUIRED) + "\n---BOOTSTRAP_BODY---\n" + BODY)
    return dict(id=TID, prompt=prompt, schedule="weekdays 19:00",
                is_enabled=True, timing_mode="exact_schedule",
                notifications_enabled=True, email_enabled=True)

class SettlementPreflightTests(unittest.TestCase):
    def test_exact_snapshot(self):
        x = snapshot()
        self.assertEqual(check(x, x.copy()), [])

    def test_missing_supplement(self):
        before = snapshot()
        after = before.copy()
        after["prompt"] = after["prompt"].replace("NextConfigExecutableHandoff=", "")
        self.assertTrue(check(before, after))

    def test_truncated_prompt(self):
        before = snapshot()
        after = before.copy()
        after["prompt"] = after["prompt"][:50]
        self.assertIn("PROMPT_LENGTH_REGRESSION", check(before, after))

    def test_body_mutated(self):
        before = snapshot()
        after = before.copy()
        after["prompt"] = after["prompt"].replace(BODY, BODY + " changed")
        self.assertIn("IMMUTABLE_BODY_CHANGED", check(before, after))

    def test_declared_digest_mutated(self):
        before = snapshot()
        after = before.copy()
        after["prompt"] = after["prompt"].replace("BootstrapBodySHA256=", "BootstrapBodySHA256=0")
        self.assertIn("BOOTSTRAP_SHA_MISMATCH", check(before, after))

    def test_schedule_changed(self):
        before = snapshot()
        after = before.copy()
        after["schedule"] = "weekdays 18:00"
        self.assertIn("UNAUTHORIZED_CHANGE_schedule", check(before, after))

    def test_notifications_changed(self):
        before = snapshot()
        after = before.copy()
        after["email_enabled"] = False
        self.assertIn("UNAUTHORIZED_CHANGE_email_enabled", check(before, after))

    def test_incomplete_original_cannot_authorize_promotion(self):
        before = snapshot()
        before["prompt"] = before["prompt"].replace("TerminalizerNativeProtocol=", "")
        self.assertTrue(any("ORIGINAL_SNAPSHOT_INCOMPLETE" in issue
                            for issue in check(before, snapshot())))

if __name__ == "__main__":
    unittest.main()
