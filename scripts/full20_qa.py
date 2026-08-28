from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
CUTOFF = "20260817"
TARGETS = {
    "0050": ("元大台灣50", "20180102", 2092),
    "00400A": ("主動國泰動能高息", "20260409", 90),
    "009820": ("元大納斯達克精選", "20260423", 80),
    "2207": ("和泰車", "20180102", 2097),
    "2308": ("台達電", "20180102", 2097),
    "2317": ("鴻海", "20180102", 2091),
    "2330": ("台積電", "20180102", 2097),
    "2368": ("金像電", "20180102", 2090),
    "2376": ("技嘉", "20180102", 2097),
    "2382": ("廣達", "20180102", 2097),
    "2383": ("台光電", "20180102", 2097),
    "2454": ("聯發科", "20180102", 2097),
    "2634": ("漢翔", "20180102", 2097),
    "2834": ("臺企銀", "20180102", 2097),
    "2885": ("元大金", "20180102", 2097),
    "3293": ("鈊象", "20180102", 2097),
    "3491": ("昇達科", "20180102", 2097),
    "3665": ("貿聯-KY", "20180102", 2092),
    "4916": ("事欣科", "20180102", 2094),
    "6770": ("力積電", "20211206", 1135),
}
PRICE = ["open", "high", "low", "close"]


def num(x):
    try: return Decimal(str(x))
    except (InvalidOperation, ValueError): return None


def is_no_trade(r):
    return str(r.get("volume", "")).strip() in ("0", "0.0") and all(not str(r.get(c, "")).strip() for c in PRICE)


def main():
    manifest = list(csv.DictReader((OUT / "source_manifest.csv").open("r", encoding="utf-8-sig", newline="")))
    rows_by_code = defaultdict(list)
    sha_failures = 0

    for m in manifest:
        url = m["url"]
        b = requests.get(url, timeout=120).content
        got = hashlib.sha256(b).hexdigest()
        expected = m["expected_sha256"]
        if got != expected:
            sha_failures += 1
            continue
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            for fn in z.namelist():
                if not fn.lower().endswith(".csv"): continue
                text = z.read(fn).decode("utf-8-sig")
                for r in csv.DictReader(io.StringIO(text)):
                    code = str(r.get("code", "")).strip()
                    if code not in TARGETS: continue
                    date = str(r.get("date", "")).strip().replace("-", "")
                    name, start, _ = TARGETS[code]
                    if not (start <= date <= CUTOFF): continue
                    r = {k: ("" if v is None else str(v).strip()) for k, v in r.items()}
                    r["date"] = date
                    if is_no_trade(r):
                        continue
                    rows_by_code[code].append(r)

    summary = []
    all_pass = sha_failures == 0
    total_rows = 0
    for code, (name, start, expected_rows) in TARGETS.items():
        rows = rows_by_code[code]
        dates = [r["date"] for r in rows]
        dup = len(dates) - len(set(dates))
        null_bad = 0
        ohlc_bad = 0
        boundary_bad = 0
        for r in rows:
            vals = [num(r.get(c, "")) for c in PRICE]
            if any(v is None for v in vals):
                null_bad += 1
                continue
            o,h,l,c = vals
            if not (h >= max(o,c) and l <= min(o,c) and h >= l):
                ohlc_bad += 1
            if not (start <= r["date"] <= CUTOFF):
                boundary_bad += 1
        first = min(dates) if dates else ""
        last = max(dates) if dates else ""
        count_match = len(rows) == expected_rows
        date_match = first == start and last == CUTOFF
        code_pass = dup == 0 and null_bad == 0 and ohlc_bad == 0 and boundary_bad == 0 and count_match and date_match
        all_pass = all_pass and code_pass
        total_rows += len(rows)
        summary.append({
            "code": code, "name": name, "rows": len(rows), "expected_rows": expected_rows,
            "count_match": count_match, "first_date": first, "expected_start": start,
            "last_date": last, "expected_end": CUTOFF, "date_match": date_match,
            "duplicate_rows": dup, "null_or_non_numeric_rows": null_bad,
            "ohlc_logic_bad_rows": ohlc_bad, "date_boundary_bad_rows": boundary_bad,
            "pass": code_pass,
        })

    with (OUT / "full20_raw_qa_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": CUTOFF, "codes": 20, "total_price_rows": total_rows,
        "expected_total_price_rows": 36928, "sha_failures": sha_failures,
        "summary": summary, "all_pass": all_pass and total_rows == 36928,
    }
    (OUT / "full20_raw_qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["all_pass"] else 2)

if __name__ == "__main__": main()
