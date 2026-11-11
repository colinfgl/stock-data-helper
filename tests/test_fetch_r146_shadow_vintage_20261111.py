"""R146 historical-source tests: date-only archival data is NOT an as-of timestamp."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import fetch_r146_shadow_pit as m


class R146SourceTimingTests(unittest.TestCase):
    def test_taiex_monthly_history_does_not_fabricate_1400(self):
        payload = {
            "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
            "data": [["115/09/23", "30,000.01", "30,200.05", "29,900.07", "30,100.11"]],
        }
        with patch.object(m, "month_iter", return_value=iter([(2026, 9)])), \
             patch.object(m, "get_json", return_value=payload), \
             patch.object(m.time, "sleep"):
            rows = m.fetch_taiex()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-09-23")
        self.assertEqual(rows[0]["available_from"], "UNVERIFIED_HISTORICAL_PUBLICATION_TIME")
        self.assertIn("independently evidenced first_seen_at", rows[0]["pit_use_rule"])

    def test_stock_monthly_history_keeps_price_but_not_fake_timestamp(self):
        payload = {
            "fields": ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
            "data": [["115/09/23", "1,200,000", "100,000,000", "100.0", "104.0", "99.0", "103.0"]],
        }
        with patch.object(m, "month_iter", return_value=iter([(2026, 9)])), \
             patch.object(m, "get_json", return_value=payload), \
             patch.object(m.time, "sleep"):
            rows = m.fetch_stock("3443", "創意")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["close"], 103.0)
        self.assertEqual(rows[0]["volume"], 1200000.0)
        self.assertEqual(rows[0]["available_from"], "UNVERIFIED_HISTORICAL_PUBLICATION_TIME")
        self.assertIn("RESEARCH_ONLY", rows[0]["pit_use_rule"])

    def test_written_coverage_cannot_be_mistaken_for_formal_pit(self):
        sample = {
            "date": "2026-09-23", "symbol": "3443", "name": "創意",
            "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0,
            "volume": 1200000.0, "amount": 100000000.0,
            "source": "TWSE STOCK_DAY", "source_url": "https://www.twse.com.tw/",
            "available_from": "UNVERIFIED_HISTORICAL_PUBLICATION_TIME",
            "pit_use_rule": "RESEARCH_ONLY; independent first_seen_at required",
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(m, "OUT_DIR", out), \
                 patch.object(m, "fetch_taiex", return_value=[{**sample, "symbol": "TAIEX", "name": "加權指數"}]), \
                 patch.object(m, "fetch_stock", return_value=[sample]), \
                 patch.object(m, "coverage", side_effect=lambda rows, sym: {
                     "symbol": sym, "sequence_60_ready": True, "wf_first_fold_ready": False,
                 }):
                m.main()
            cov = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
            self.assertEqual(cov["status_scope"], "RAW_HISTORY_COVERAGE_ONLY")
            self.assertFalse(cov["formal_pit_eligible"])
            self.assertFalse(cov["publication_time_verified"])
            with (out / "stocks_daily.csv").open(encoding="utf-8-sig", newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["available_from"], "UNVERIFIED_HISTORICAL_PUBLICATION_TIME")


if __name__ == "__main__":
    unittest.main()
