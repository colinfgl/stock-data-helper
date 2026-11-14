"""Offline positive/negative tests; never contact TWSE or production controls."""

from __future__ import annotations

from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).with_name("stock_margin_twse_ingest_20261108_v1.py")
if not PATH.exists():
    PATH = Path(__file__).resolve().parents[1] / "scripts" / PATH.name
spec = importlib.util.spec_from_file_location("stock_margin_ingest", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample(day="2026-11-06"):
    cases = {
        "2026-11-05": (
            [455932, 518105, 12285, 9514913, 9440455],
            [22632780, 39992267, 3177309, 596945835, 576409039],
        ),
        "2026-11-06": (
            [560405, 928520, 34402, 9440465, 9037948],
            [28143760, 63253996, 7246171, 576409039, 534052632],
        ),
    }
    units, amount = cases[day]
    return {"stat": "OK", "date": day.replace("-", ""), "creditList": [
        ["融資(交易單位)", *[f"{x:,}" for x in units]],
        ["融券(交易單位)", "1", "2", "0", "3", "4"],
        ["融資金額(仟元)", *[f"{x:,}" for x in amount]],
    ]}


def audited(report=None, *, day="2026-11-06", at="2026-11-08T09:00:00+08:00"):
    contents = json.dumps(report or sample(day), ensure_ascii=False).encode("utf-8")
    return module.parse_source(contents, date.fromisoformat(day), datetime.fromisoformat(at))


class MarginIngestTests(unittest.TestCase):
    def test_two_official_20261105_20261106_amounts(self):
        d5 = audited(day="2026-11-05")
        d6 = audited(day="2026-11-06")
        self.assertEqual(d5["amount_thousand_twd"]["delta"], -20536796)
        self.assertEqual(d6["amount_thousand_twd"]["delta"], -42356407)
        self.assertEqual(d5["amount_thousand_twd"]["delta"]
                         + d6["amount_thousand_twd"]["delta"], -62893203)

    def test_official_unit_revisions_preserved(self):
        d5 = audited(day="2026-11-05")
        d6 = audited(day="2026-11-06")
        self.assertEqual(d6["units"]["previous"] - d5["units"]["current"], 10)
        self.assertEqual(d6["source_reconciliation"], "PASS")

    def test_lagged_first_point_in_time(self):
        result = audited(at="2026-11-08T23:59:00+08:00")
        self.assertEqual(result["conservative_first_pit_at"], "2026-11-09T00:00:00+08:00")
        self.assertFalse(result["formal_prediction_modified"])
        self.assertFalse(result["formal_settlement_modified"])

    def test_timezone_conversion_uses_taipei(self):
        result = audited(at="2026-11-07T20:00:00+00:00")
        self.assertEqual(result["conservative_first_pit_at"], "2026-11-09T00:00:00+08:00")

    def test_table_variant_label_selection(self):
        report = sample()
        report["tables"] = [{"title": "信用交易統計", "data": report.pop("creditList")}]
        self.assertEqual(audited(report)["amount_thousand_twd"]["current"], 534052632)

    def test_nested_credit_values_supported(self):
        report = sample()
        report["creditList"] = [[row[0], row[1:]] for row in report["creditList"]]
        self.assertEqual(audited(report)["units"]["current"], 9037948)

    def test_roc_report_date_supported(self):
        report = sample()
        report["date"] = "115年11月06日"
        self.assertEqual(audited(report)["trading_date"], "2026-11-06")

    def test_status_not_ok_rejected(self):
        report = sample()
        report["stat"] = "很抱歉，沒有符合條件的資料"
        with self.assertRaisesRegex(module.SourceError, "not OK"):
            audited(report)

    def test_mismatch_date_rejected(self):
        report = sample()
        report["date"] = "20261105"
        with self.assertRaisesRegex(module.SourceError, "response date"):
            audited(report)

    def test_missing_amount_rejected(self):
        report = sample()
        report["creditList"] = report["creditList"][:2]
        with self.assertRaisesRegex(module.SourceError, "Missing two"):
            audited(report)

    def test_duplicate_amount_rejected(self):
        report = sample()
        report["creditList"].append(list(report["creditList"][-1]))
        with self.assertRaisesRegex(module.SourceError, "Duplicate financing"):
            audited(report)

    def test_broken_financing_arithmetic_rejected(self):
        report = sample()
        report["creditList"][-1][-1] = "534,052,633"
        with self.assertRaisesRegex(module.SourceError, "arithmetic mismatch"):
            audited(report)

    def test_negative_numeric_rejected(self):
        report = sample()
        report["creditList"][-1][1] = "-1"
        with self.assertRaisesRegex(module.SourceError, "non-integer"):
            audited(report)

    def test_nan_not_inferred_zero(self):
        report = sample()
        report["creditList"][-1][1] = "--"
        with self.assertRaisesRegex(module.SourceError, "non-integer"):
            audited(report)

    def test_capture_before_trade_date_rejected(self):
        with self.assertRaisesRegex(module.SourceError, "predates"):
            audited(at="2026-11-05T23:59:59+08:00")

    def test_capture_without_timezone_rejected(self):
        with self.assertRaisesRegex(module.SourceError, "time zone"):
            audited(at="2026-11-08T12:00:00")

    def test_offline_cli_requires_capture_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "official.json"
            path.write_text(json.dumps(sample(), ensure_ascii=False), encoding="utf-8")
            status = module.main(["--date", "2026-11-06", "--source-json", str(path)])
            self.assertEqual(status, 2)

    def test_cli_refuses_overwriting_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "official.json"
            out = Path(folder) / "shadow.json"
            path.write_text(json.dumps(sample(), ensure_ascii=False), encoding="utf-8")
            out.write_text("preserve", encoding="utf-8")
            status = module.main(["--date", "2026-11-06", "--source-json", str(path),
                                  "--captured-at", "2026-11-08T09:00:00+08:00", "--out", str(out)])
            self.assertEqual(status, 2)
            self.assertEqual(out.read_text(), "preserve")

    def test_cli_archives_original_raw_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "official.json"
            archive = Path(folder) / "official_archive.json"
            out = Path(folder) / "shadow.json"
            path.write_text(json.dumps(sample(), ensure_ascii=False), encoding="utf-8")
            status = module.main(["--date", "2026-11-06", "--source-json", str(path),
                                  "--captured-at", "2026-11-08T09:00:00+08:00",
                                  "--archive-raw", str(archive), "--out", str(out)])
            self.assertEqual(status, 0)
            self.assertEqual(archive.read_bytes(), path.read_bytes())
            self.assertEqual(json.loads(out.read_text())["source_reconciliation"], "PASS")

    def test_cli_never_overwrites_raw_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "official.json"
            archive = Path(folder) / "official_archive.json"
            out = Path(folder) / "shadow.json"
            path.write_text(json.dumps(sample(), ensure_ascii=False), encoding="utf-8")
            archive.write_text("keep", encoding="utf-8")
            status = module.main(["--date", "2026-11-06", "--source-json", str(path),
                                  "--captured-at", "2026-11-08T09:00:00+08:00",
                                  "--archive-raw", str(archive), "--out", str(out)])
            self.assertEqual(status, 2)
            self.assertEqual(archive.read_text(), "keep")
            self.assertFalse(out.exists())

    def test_invalid_json_rejected(self):
        with self.assertRaisesRegex(module.SourceError, "Invalid TWSE official JSON"):
            module.parse_source(b"<html>error</html>", date(2026, 11, 6),
                                datetime.fromisoformat("2026-11-08T09:00:00+08:00"))

    def test_source_hash_recorded(self):
        report = sample()
        raw = json.dumps(report, ensure_ascii=False).encode("utf-8")
        import hashlib
        result = module.parse_source(raw, date(2026, 11, 6),
                                     datetime.fromisoformat("2026-11-08T09:00:00+08:00"))
        self.assertEqual(result["raw_source_sha256"], hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
