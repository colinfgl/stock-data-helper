#!/usr/bin/env python3
"""Fetch official TAIEX daily history for PIT simulation warm-up and 2026 validation.

Outputs:
- output/taiex_2025_2026_official.csv : 2025-01-02 through 2026-09-08 (or first 2025 trading day)
- output/taiex_2026_official.csv      : 2026-01-02 through 2026-09-08

Project utility for 存股作戰地圖. Source is TWSE official MI_5MINS_HIST.
This script only writes research data; it does not touch P4 or production weights.
"""
from __future__ import annotations

import csv
import json
import re
import time
import urllib.request
from pathlib import Path

OUT_ALL = Path("output/taiex_2025_2026_official.csv")
OUT_2026 = Path("output/taiex_2026_official.csv")
MAX_DATE = "2026-09-08"
UA = "stock-data-helper taiex-pit-warmup/1.1"


def get_json(url: str, retries: int = 5):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def roc_to_iso(s: str) -> str:
    s = str(s).strip().replace("年", "/").replace("月", "/").replace("日", "")
    parts = re.split(r"[/.-]", s)
    if len(parts) != 3:
        return s
    y, m, d = map(int, parts)
    if y < 1911:
        y += 1911
    return f"{y:04d}-{m:02d}-{d:02d}"


def fnum(x):
    s = str(x).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def fetch_year(year: int):
    rows = []
    max_month = 9 if year == 2026 else 12
    for month in range(1, max_month + 1):
        datearg = f"{year:04d}{month:02d}01"
        urls = [
            f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={datearg}&response=json",
            f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?date={datearg}&response=json",
        ]
        payload = None
        src = None
        for u in urls:
            try:
                p = get_json(u, retries=3)
                if p.get("data"):
                    payload, src = p, u
                    break
            except Exception:
                pass
        if not payload:
            print(f"year={year} month={month:02d} no data", flush=True)
            continue
        fields = [str(x) for x in payload.get("fields", [])]
        close_idx, open_idx, high_idx, low_idx = 4, 1, 2, 3
        for i, field in enumerate(fields):
            if "開盤" in field: open_idx = i
            if "最高" in field: high_idx = i
            if "最低" in field: low_idx = i
            if "收盤" in field: close_idx = i
        for r in payload.get("data", []):
            ds = roc_to_iso(r[0])
            if not ds.startswith(f"{year:04d}-"):
                continue
            if ds > MAX_DATE:
                continue
            if len(r) <= max(open_idx, high_idx, low_idx, close_idx):
                continue
            op, hi, lo, cl = (fnum(r[open_idx]), fnum(r[high_idx]), fnum(r[low_idx]), fnum(r[close_idx]))
            if cl is None:
                continue
            rows.append({"date": ds, "open": op, "high": hi, "low": lo, "close": cl,
                         "source": "TWSE MI_5MINS_HIST", "source_url": src})
        print(f"year={year} month={month:02d} cumulative={len(rows)}", flush=True)
        time.sleep(0.2)
    return rows


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "source", "source_url"])
        w.writeheader(); w.writerows(rows)


def main():
    rows = fetch_year(2025) + fetch_year(2026)
    uniq = {r["date"]: r for r in rows}
    rows = [uniq[k] for k in sorted(uniq)]
    rows_2026 = [r for r in rows if r["date"].startswith("2026-")]
    write_csv(OUT_ALL, rows)
    write_csv(OUT_2026, rows_2026)
    if not rows_2026 or rows_2026[-1]["date"] != MAX_DATE:
        raise RuntimeError(f"2026 TAIEX coverage incomplete: last={rows_2026[-1]['date'] if rows_2026 else None}, expected={MAX_DATE}")
    if not rows or not rows[0]["date"].startswith("2025-"):
        raise RuntimeError("2025 warm-up history missing")
    print(json.dumps({
        "status":"PASS","rows_all":len(rows),"rows_2026":len(rows_2026),
        "first":rows[0]["date"],"last":rows[-1]["date"],"last_close":rows[-1]["close"],
        "formal_weight":0,"p4":"NO INTERACTION"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
