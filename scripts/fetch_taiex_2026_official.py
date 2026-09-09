#!/usr/bin/env python3
"""Fetch official TAIEX daily closes for 2026 through 2026-09-08.

Project utility for 存股作戰地圖. Data source is TWSE official
MI_5MINS_HIST monthly JSON. This script only writes a research data file;
it does not touch P4 or production model weights.
"""
from __future__ import annotations

import csv
import json
import re
import time
import urllib.request
from pathlib import Path

OUT = Path("output/taiex_2026_official.csv")
MAX_DATE = "2026-09-08"
UA = "stock-data-helper taiex-2026-official/1.0"


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


def main():
    rows = []
    for month in range(1, 10):
        datearg = f"2026{month:02d}01"
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
            print(f"month={month:02d} no data", flush=True)
            continue
        fields = [str(x) for x in payload.get("fields", [])]
        close_idx = 4
        open_idx, high_idx, low_idx = 1, 2, 3
        for i, field in enumerate(fields):
            if "開盤" in field: open_idx = i
            if "最高" in field: high_idx = i
            if "最低" in field: low_idx = i
            if "收盤" in field: close_idx = i
        for r in payload.get("data", []):
            ds = roc_to_iso(r[0])
            if not ds.startswith("2026-") or ds > MAX_DATE:
                continue
            if len(r) <= max(open_idx, high_idx, low_idx, close_idx):
                continue
            op, hi, lo, cl = (fnum(r[open_idx]), fnum(r[high_idx]), fnum(r[low_idx]), fnum(r[close_idx]))
            if cl is None:
                continue
            rows.append({"date": ds, "open": op, "high": hi, "low": lo, "close": cl, "source": "TWSE MI_5MINS_HIST", "source_url": src})
        print(f"month={month:02d} cumulative={len(rows)}", flush=True)
        time.sleep(0.2)

    uniq = {r["date"]: r for r in rows}
    rows = [uniq[k] for k in sorted(uniq)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "source", "source_url"])
        w.writeheader(); w.writerows(rows)
    if not rows or rows[-1]["date"] != MAX_DATE:
        raise RuntimeError(f"TAIEX coverage incomplete: last={rows[-1]['date'] if rows else None}, expected={MAX_DATE}")
    print(json.dumps({"status":"PASS","rows":len(rows),"first":rows[0]["date"],"last":rows[-1]["date"],"last_close":rows[-1]["close"],"formal_weight":0,"p4":"NO INTERACTION"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
