"""Offline evidence-boundary tests; they do not simulate platform delivery."""
import unittest

from scripts.stock_factor_vintage_gate_20261111 import VintageError, audit, classify


def snap(**kw):
    row = dict(source="TWSE_T86_WEB", market="TWSE", kind="INSTITUTIONAL",
               version="WEB_BLOCK_SCOPE_UNVERIFIED", trade_date="2026-11-11",
               observed_at="2026-11-11T20:02:42+08:00", raw_sha256="a"*64,
               published_at=None)
    row.update(kw)
    return row


class VintageGateTests(unittest.TestCase):
    def decision(self, row=None, when="2026-11-12T08:10:00+08:00",
                 role="PREMARKET_0810"):
        return classify(snap() if row is None else row, decision_at=when, role=role)

    def test_next_premarket_research_admissible_not_formal(self):
        out = self.decision()
        self.assertEqual(out["research_status"], "PIT_RESEARCH_SNAPSHOT_ADMISSIBLE")
        self.assertFalse(out["formal_eligible"])
        self.assertEqual(out["oos_credit"], 0)

    def test_same_day_1900_cannot_see_2002_capture(self):
        out = self.decision(when="2026-11-11T19:00:00+08:00",role="SETTLEMENT_1900")
        self.assertIn("NOT_YET_OBSERVED_AT_DECISION", out["hold_reasons"])

    def test_same_day_premarket_rejected_even_if_capture_backdated(self):
        row = snap(observed_at="2026-11-11T07:30:00+08:00")
        out = self.decision(row,when="2026-11-11T08:10:00+08:00")
        self.assertIn("PREMARKET_SOURCE_DATE_NOT_PRIOR", out["hold_reasons"])

    def test_timezone_equivalence_and_caveat(self):
        out = self.decision(when="2026-11-12T00:10:00Z")
        self.assertIn("WEB_T86_NOT_IDENTICAL_TO_PAID_18_OR_20_VERSION",out["caveats"])

    def test_naive_time_rejected(self):
        with self.assertRaisesRegex(VintageError, "NAIVE"):
            self.decision(when="2026-11-12T08:10:00")

    def test_unknown_source_or_wrong_market_rejected(self):
        with self.assertRaisesRegex(VintageError, "UNREGISTERED"):
            self.decision(snap(source="THIRD_PARTY_UNVERIFIED"))
        with self.assertRaisesRegex(VintageError, "CONFLICT"):
            self.decision(snap(market="TPEX"))

    def test_missing_full_raw_sha_held(self):
        out=self.decision(snap(raw_sha256=None))
        self.assertIn("COMPLETE_RAW_SHA_MISSING",out["hold_reasons"])

    def test_published_after_capture_rejected(self):
        with self.assertRaisesRegex(VintageError, "PUBLICATION_AFTER_CAPTURE"):
            self.decision(snap(published_at="2026-11-11T20:05:00+08:00"))

    def test_paid_2000_version_cannot_appear_at_1900(self):
        row=snap(source="TWSE_TWTAIUC", version="INCLUDING_BLOCK_TRADES",
                 observed_at="2026-11-11T18:30:00+08:00")
        out=self.decision(row,when="2026-11-11T19:00:00+08:00",role="SETTLEMENT_1900")
        self.assertIn("TWENTY_HOUR_PRODUCT_NOT_YET_PRODUCED_AT_CAPTURE",out["hold_reasons"])

    def test_early_paid_capture_still_invalid_tomorrow(self):
        row=snap(source="TWSE_TWTAIUC", version="INCLUDING_BLOCK_TRADES",
                 observed_at="2026-11-11T18:30:00+08:00")
        self.assertIn("TWENTY_HOUR_PRODUCT_NOT_YET_PRODUCED_AT_CAPTURE",
                      self.decision(row)["hold_reasons"])

    def test_1800_version_not_same_as_2000_version(self):
        row=snap(source="TWSE_TWT86UC",version="EXCLUDING_BLOCK_TRADES",
                 observed_at="2026-11-11T18:30:00+08:00")
        out=self.decision(row,when="2026-11-11T19:00:00+08:00",role="SETTLEMENT_1900")
        self.assertEqual(out["research_status"],"PIT_RESEARCH_SNAPSHOT_ADMISSIBLE")

    def test_margin_provisional_caveat(self):
        row=snap(source="TWSE_MI_MARGN",kind="MARGIN",
                 version="TODAY_BALANCE_PROVISIONAL",trade_date="2026-11-10")
        self.assertIn("TODAY_BALANCE_MAY_BE_REVISED_NEXT_DAY",self.decision(row)["caveats"])

    def test_final_margin_cannot_exist_same_trade_day(self):
        row=snap(source="TWSE_MI_MARGN_FINAL",kind="MARGIN",
                 version="PREVIOUS_BALANCE_FINAL")
        out=self.decision(row)
        self.assertIn("FINAL_MARGIN_BALANCE_NOT_NEXT_DAY",out["hold_reasons"])

    def test_duplicate_evidence_rejected(self):
        row=snap()
        with self.assertRaisesRegex(VintageError,"DUPLICATE"):
            audit({"role":"PREMARKET_0810","decision_at":"2026-11-12T08:10:00+08:00",
                   "snapshots":[row,row.copy()]})

    def test_research_only_output_zero_credit(self):
        out=audit({"role":"PREMARKET_0810","decision_at":"2026-11-12T08:10:00+08:00",
                   "snapshots":[snap()]})
        self.assertEqual(out["formal_natural_oos_credit"],0)
        self.assertFalse(out["model_automatically_updated"])


if __name__ == "__main__":
    unittest.main()
