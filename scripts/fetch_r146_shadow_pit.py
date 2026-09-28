#!/usr/bin/env python3
"""Backfill official PIT daily sequences for R146 Shadow Model.

Sources
- TAIEX: TWSE MI_5MINS_HIST monthly endpoint.
- Stocks: TWSE STOCK_DAY monthly endpoint.

Targets
- TAIEX
- 3443 創意
- 6526 達發
- 3189 景碩
- 2345 智邦
- 3017 奇鋐

Coverage
- 2024-01-01 through 2026-09-24 inclusive.
- Data is after-close official daily data. For a premarket prediction on trade_date,
  only rows with date < trade_date are PIT-eligible.

Outputs
- output/r146_shadow/taiex_daily.csv
- output/r146_shadow/stocks_daily.csv
- output/r146_shadow/coverage.json
- output/r146_shadow/manifest.sha256

This script writes research/shadow data only. Push-trigger v1.1. It MUST NOT change production weights,
holdings, cash, trades, or Formal OOS state.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional

START_DATE = "2023-01-01"
MAX_DATE = "2026-09-24"
SYMBOLS: Dict[str, str] = {
    "3443": "創意",
    "6526": "達發",
    "3189": "景碩",
    "2345": "智邦",
    "3017": "奇鋐",
}
OUT_DIR = Path("output/r146_shadow")
UA = "stock-data-helper r146-shadow-pit/1.1"


def get_json(url: str, retries: int = 5):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
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


def fnum(x) -> Optional[float]:
    s = str(x).strip().replace(",", "")
    if s in ("", "--", "---", "----", "X"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def in_window(ds: str) -> bool:
    return START_DATE <= ds <= MAX_DATE


def month_iter(start_year=2023, start_month=1, end_year=2026, end_month=9):
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


def fetch_taiex() -> List[dict]:
    rows: List[dict] = []
    for year, month in month_iter():
        datearg = f"{year:04d}{month:02d}01"
        urls = [
            f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={datearg}&response=json",
            f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?date={datearg}&response=json",
        ]
        payload = None
        src = None
        for url in urls:
            try:
                p = get_json(url, retries=3)
                if p.get("data"):
                    payload, src = p, url
                    break
            except Exception:
                pass
        if not payload:
            print(f"TAIEX {year}-{month:02d}: no data", flush=True)
            continue
        fields = [str(x) for x in payload.get("fields", [])]
        idx = {"open": 1, "high": 2, "low": 3, "close": 4}
        for i, field in enumerate(fields):
            if "開盤" in field:
                idx["open"] = i
            elif "最高" in field:
                idx["high"] = i
            elif "最低" in field:
                idx["low"] = i
            elif "收盤" in field:
                idx["close"] = i
        for r in payload.get("data", []):
            ds = roc_to_iso(r[0])
            if not in_window(ds):
                continue
            if len(r) <= max(idx.values()):
                continue
            op = fnum(r[idx["open"]])
            hi = fnum(r[idx["high"]])
            lo = fnum(r[idx["low"]])
            cl = fnum(r[idx["close"]])
            if cl is None:
                continue
            rows.append({
                "date": ds,
                "symbol": "TAIEX",
                "name": "加權指數",
                "open": op,
                "high": hi,
                "low": lo,
                "close": cl,
                "volume": "",
                "amount": "",
                "source": "TWSE MI_5MINS_HIST",
                "source_url": src,
                "available_from": ds + " 14:00 Asia/Taipei",
                "pit_use_rule": "premarket trade_date may only use row.date < trade_date",
            })
        print(f"TAIEX {year}-{month:02d}: cumulative={len(rows)}", flush=True)
        time.sleep(0.18)
    return dedupe(rows, ("date", "symbol"))


def fetch_stock(code: str, name: str) -> List[dict]:
    rows: List[dict] = []
    for year, month in month_iter():
        datearg = f"{year:04d}{month:02d}01"
        url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
            f"?date={datearg}&stockNo={code}&response=json"
        )
        try:
            p = get_json(url, retries=4)
        except Exception as e:
            print(f"{code} {year}-{month:02d}: fetch error {e}", flush=True)
            continue
        data = p.get("data") or []
        if not data:
            print(f"{code} {year}-{month:02d}: no data", flush=True)
            time.sleep(0.15)
            continue
        fields = [str(x) for x in p.get("fields", [])]
        # TWSE standard: date, volume, amount, open, high, low, close, change, tx_count
        def find_idx(keyword: str, default: int) -> int:
            for i, f in enumerate(fields):
                if keyword in f:
                    return i
            return default

        vi = find_idx("成交股數", 1)
        ai = find_idx("成交金額", 2)
        oi = find_idx("開盤", 3)
        hi = find_idx("最高", 4)
        li = find_idx("最低", 5)
        ci = find_idx("收盤", 6)

        for r in data:
            ds = roc_to_iso(r[0])
            if not in_window(ds):
                continue
            if len(r) <= max(vi, ai, oi, hi, li, ci):
                continue
            close = fnum(r[ci])
            if close is None:
                continue
            rows.append({
                "date": ds,
                "symbol": code,
                "name": name,
                "open": fnum(r[oi]),
                "high": fnum(r[hi]),
                "low": fnum(r[li]),
                "close": close,
                "volume": fnum(r[vi]),
                "amount": fnum(r[ai]),
                "source": "TWSE STOCK_DAY",
                "source_url": url,
                "available_from": ds + " 14:00 Asia/Taipei",
                "pit_use_rule": "premarket trade_date may only use row.date < trade_date",
            })
        print(f"{code} {year}-{month:02d}: cumulative={len(rows)}", flush=True)
        time.sleep(0.18)
    return dedupe(rows, ("date", "symbol"))


def dedupe(rows: Iterable[dict], keys) -> List[dict]:
    uniq = {}
    for row in rows:
        k = tuple(row[x] for x in keys)
        uniq[k] = row
    return [uniq[k] for k in sorted(uniq)]


FIELDS = [
    "date", "symbol", "name", "open", "high", "low", "close",
    "volume", "amount", "source", "source_url", "available_from", "pit_use_rule"
]


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def coverage(rows: List[dict], symbol: str) -> dict:
    x = [r for r in rows if r["symbol"] == symbol]
    return {
        "symbol": symbol,
        "rows": len(x),
        "first": x[0]["date"] if x else None,
        "last": x[-1]["date"] if x else None,
        "sequence_60_ready": len(x) >= 60,
        "wf_min_raw_rows": 730,\n        "wf_first_fold_ready": len(x) >= 730,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    taiex = fetch_taiex()
    stocks: List[dict] = []
    for code, name in SYMBOLS.items():
        stocks.extend(fetch_stock(code, name))
    stocks = dedupe(stocks, ("date", "symbol"))

    taiex_path = OUT_DIR / "taiex_daily.csv"
    stock_path = OUT_DIR / "stocks_daily.csv"
    write_csv(taiex_path, taiex)
    write_csv(stock_path, stocks)

    cov = [coverage(taiex, "TAIEX")]
    cov.extend(coverage(stocks, code) for code in SYMBOLS)
    payload = {
        "status": "PASS" if all(x["sequence_60_ready"] for x in cov) else "PARTIAL",\n        "wf_status": "READY" if all(x["wf_first_fold_ready"] for x in cov) else "INSUFFICIENT_RAW_HISTORY",
        "range": {"start": START_DATE, "end": MAX_DATE},
        "source_policy": "official TWSE after-close; premarket uses date < trade_date",
        "formal_weight": 0,
        "production_effect": "NONE",
        "coverage": cov,
    }
    cov_path = OUT_DIR / "coverage.json"
    cov_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        str(taiex_path): sha256_file(taiex_path),
        str(stock_path): sha256_file(stock_path),
        str(cov_path): sha256_file(cov_path),
    }
    manifest_path = OUT_DIR / "manifest.sha256"
    manifest_path.write_text(
        "\n".join(f"{v}  {k}" for k, v in manifest.items()) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(payload, ensure_ascii=False))
    if not all(x["sequence_60_ready"] for x in cov):
        raise RuntimeError("R146 shadow PIT backfill incomplete: <60 rows for one or more targets")


if __name__ == "__main__":
    main()
