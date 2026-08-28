from __future__ import annotations

import csv
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

EVENTS = {
    "3665": [
        ("20180802", "203", "196.17", "0.9663546798"),
        ("20190802", "248", "240.50", "0.9697580645"),
        ("20200715", "217.5", "208.5", "0.9586206897"),
        ("20210708", "272", "263.97", "0.9704779412"),
        ("20220714", "315.5", "306.05", "0.9700475436"),
        ("20230725", "309.5", "296.74", "0.9587722132"),
        ("20240723", "388", "379.22", "0.9773711340"),
        ("20250717", "882", "862.96", "0.9784126984"),
        ("20260715", "1775", "1759.82", "0.9914478873"),
    ],
    "4916": [
        ("20180816", "35.35", "34.36", "0.9719943423"),
        ("20190704", "36.15", "33.67", "0.9313969571"),
        ("20200702", "28.25", "26.25", "0.9292035398"),
        ("20210812", "23.60", "23.10", "0.9788135593"),
        ("20220817", "26.25", "25.75", "0.9809523810"),
        ("20230630", "42.75", "42.37", "0.9911111111"),
        ("20240729", "32.50", "32.10", "0.9876923077"),
        ("20250728", "47.15", "46.77", "0.9919406151"),
        ("20260730", "90.20", "89.70", "0.9944567627"),
    ],
    "6770": [
        ("20220224", "57.10", "55.90", "0.9789842382"),
        ("20220823", "35.05", "34.30", "0.9786019971"),
        ("20230313", "34.45", "34.15", "0.9912917271"),
    ],
}

NAMES = {"3665": "貿聯-KY", "4916": "事欣科", "6770": "力積電"}
PRICE_COLS = ["open", "high", "low", "close"]


def d(x: str) -> Decimal:
    return Decimal(str(x))


def q(x: Decimal, places="0.000001") -> str:
    return str(x.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def read_rows(code: str):
    p = OUT / f"{code}.csv"
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def cumulative_factor(code: str, date: str) -> Decimal:
    f = Decimal("1")
    for event_date, _, _, factor in EVENTS[code]:
        if event_date > date:
            f *= d(factor)
    return f


def main():
    OUT.mkdir(exist_ok=True)
    event_qa = []
    adj_summary = []
    overall = True

    for code in ("3665", "4916", "6770"):
        rows = read_rows(code)
        by_date = {r["date"]: r for r in rows}
        dates = sorted(by_date)

        out_rows = []
        bad = 0
        factor_bad = 0
        prev_factor = None
        for r in rows:
            f = cumulative_factor(code, r["date"])
            adj = {c: d(r[c]) * f for c in PRICE_COLS}
            logic_ok = adj["high"] >= max(adj["open"], adj["close"]) and adj["low"] <= min(adj["open"], adj["close"]) and adj["high"] >= adj["low"] and all(v > 0 for v in adj.values())
            if not logic_ok:
                bad += 1
            if f <= 0:
                factor_bad += 1
            out_rows.append({
                **r,
                "cumulative_factor": q(f, "0.0000000001"),
                "adj_open": q(adj["open"]),
                "adj_high": q(adj["high"]),
                "adj_low": q(adj["low"]),
                "adj_close": q(adj["close"]),
                "adj_qa": "OK" if logic_ok and f > 0 else "FAIL",
            })
            prev_factor = f

        out_path = OUT / f"{code}_adjusted.csv"
        fields = list(out_rows[0].keys())
        with out_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader(); w.writerows(out_rows)

        code_event_pass = True
        for event_date, exp_prev_close, ref_price, factor in EVENTS[code]:
            if event_date not in by_date:
                event_qa.append({"code": code, "name": NAMES[code], "event_date": event_date, "status": "FAIL", "reason": "event_date_missing"})
                code_event_pass = False
                continue
            prior_dates = [x for x in dates if x < event_date]
            if not prior_dates:
                event_qa.append({"code": code, "name": NAMES[code], "event_date": event_date, "status": "FAIL", "reason": "previous_trade_missing"})
                code_event_pass = False
                continue
            prev_date = prior_dates[-1]
            actual_prev = d(by_date[prev_date]["close"])
            expected_prev = d(exp_prev_close)
            ref = d(ref_price)
            fac = d(factor)
            derived = actual_prev * fac
            prev_match = abs(actual_prev - expected_prev) <= Decimal("0.01")
            ref_match = abs(derived - ref) <= Decimal("0.02")
            status = "PASS" if prev_match and ref_match else "FAIL"
            if status != "PASS": code_event_pass = False
            event_qa.append({
                "code": code, "name": NAMES[code], "event_date": event_date,
                "previous_trade_date": prev_date, "actual_previous_close": str(actual_prev),
                "expected_previous_close": str(expected_prev), "reference_price": str(ref),
                "event_factor": str(fac), "derived_reference_price": q(derived, "0.01"),
                "previous_close_match": prev_match, "reference_match": ref_match, "status": status,
            })

        adj_pass = bad == 0 and factor_bad == 0 and code_event_pass and len(out_rows) == len(rows)
        overall = overall and adj_pass
        adj_summary.append({
            "code": code, "name": NAMES[code], "rows": len(rows), "event_count": len(EVENTS[code]),
            "adjusted_ohlc_bad_rows": bad, "factor_bad_rows": factor_bad,
            "event_qa_failures": sum(1 for x in event_qa if x.get("code") == code and x.get("status") == "FAIL"),
            "first_date": dates[0], "last_date": dates[-1], "adjusted_pass": adj_pass,
        })

    with (OUT / "adjustment_event_qa.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = sorted({k for row in event_qa for k in row.keys()})
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(event_qa)
    with (OUT / "adjustment_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = list(adj_summary[0].keys())
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(adj_summary)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "Backward adjusted OHLC; multiply each raw date by product of event factors with event_date > row_date. Event date excludes its own factor.",
        "event_count": sum(len(v) for v in EVENTS.values()),
        "summary": adj_summary,
        "all_pass": overall,
    }
    (OUT / "adjustment_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if overall else 2)


if __name__ == "__main__":
    main()
