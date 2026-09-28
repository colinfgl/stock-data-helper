#!/usr/bin/env python3
"""Fetch official TWSE daily OHLCV for R146/R147 A+ shadow-model PIT sequences.

Scope:
- 3443 創意
- 6526 達發
- 3189 景碩
- 2345 智邦
- 3017 奇鋐

Source: TWSE official STOCK_DAY monthly JSON.
Outputs research CSV only. Never changes Production weights/trades/cash.
"""
from __future__ import annotations

import csv
import json
import re
import time
import urllib.request
from datetime import date
from pathlib import Path

MIN_ROWS = {"3443": 850, "6526": 680, "3189": 850, "2345": 850, "3017": 850}

SYMBOLS = {
    "3443": "創意",
    "6526": "達發",
    "3189": "景碩",
    "2345": "智邦",
    "3017": "奇鋐",
}
LISTING_START = {
    "3443": "2006-11-03",
    "6526": "2023-10-19",
    "3189": "2001-09-17",
    "2345": "1996-07-03",
    "3017": "2002-09-27",
}
START_YEAR, START_MONTH = 2023, 1
END_YEAR, END_MONTH = 2026, 9
MAX_DATE = "2026-09-24"
OUT_DIR = Path("output/a_plus_daily")
OUT_ALL = OUT_DIR / "a_plus_2023_2026_official.csv"
UA = "stock-data-helper a-plus-pit-sequence/1.0"


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
    s = str(x).strip().replace(",", "").replace("--", "")
    try:
        return float(s)
    except Exception:
        return None


def iter_months():
    y, m = START_YEAR, START_MONTH
    while (y, m) <= (END_YEAR, END_MONTH):
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


def fetch_symbol(symbol: str, name: str):
    rows = []
    for year, month in iter_months():
        datearg = f"{year:04d}{month:02d}01"
        urls = [
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
            f"?date={datearg}&stockNo={symbol}&response=json",
            "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
            f"?response=json&date={datearg}&stockNo={symbol}",
        ]
        payload = None
        url = None
        errors = []
        for candidate in urls:
            try:
                p = get_json(candidate, retries=4)
                if p.get("data"):
                    payload, url = p, candidate
                    break
                errors.append(f"{candidate}: no data")
            except Exception as e:
                errors.append(f"{candidate}: {e}")
        month_key = f"{year:04d}-{month:02d}"
        listing_month = LISTING_START[symbol][:7]
        if payload is None:
            if month_key < listing_month:
                print(f"{symbol} {month_key} pre-listing no data", flush=True)
                continue
            raise RuntimeError(
                f"{symbol} {month_key} official month missing after listing; "
                + " | ".join(errors)
            )
        data = payload.get("data") or []
        fields = [str(x) for x in payload.get("fields", [])]
        idx = {"date": 0, "volume": 1, "value": 2, "open": 3, "high": 4, "low": 5, "close": 6}
        for i, f in enumerate(fields):
            if "日期" in f:
                idx["date"] = i
            elif "成交股數" in f:
                idx["volume"] = i
            elif "成交金額" in f:
                idx["value"] = i
            elif "開盤" in f:
                idx["open"] = i
            elif "最高" in f:
                idx["high"] = i
            elif "最低" in f:
                idx["low"] = i
            elif "收盤" in f:
                idx["close"] = i
        for r in data:
            if len(r) <= max(idx.values()):
                continue
            ds = roc_to_iso(r[idx["date"]])
            if not re.match(r"^20\d\d-\d\d-\d\d$", ds):
                continue
            if ds > MAX_DATE:
                continue
            op, hi, lo, cl = [fnum(r[idx[k]]) for k in ("open", "high", "low", "close")]
            if cl is None:
                continue
            rows.append(
                {
                    "date": ds,
                    "symbol": symbol,
                    "name": name,
                    "open": op,
                    "high": hi,
                    "low": lo,
                    "close": cl,
                    "volume": fnum(r[idx["volume"]]),
                    "turnover_value": fnum(r[idx["value"]]),
                    "source": "TWSE STOCK_DAY",
                    "source_url": url,
                    "pit_available_date": ds,
                }
            )
        print(f"{symbol} {year}-{month:02d} cumulative={len(rows)}", flush=True)
        time.sleep(0.15)
    uniq = {(r["date"], r["symbol"]): r for r in rows}
    rows = [uniq[k] for k in sorted(uniq)]
    return rows


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "date", "symbol", "name", "open", "high", "low", "close",
        "volume", "turnover_value", "source", "source_url", "pit_available_date",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows = []
    qa = {}
    for symbol, name in SYMBOLS.items():
        rows = fetch_symbol(symbol, name)
        if not rows:
            raise RuntimeError(f"{symbol} no official STOCK_DAY rows")
        per = OUT_DIR / f"{symbol}_{START_YEAR}_{END_YEAR}_official.csv"
        write_csv(per, rows)
        seen_months = sorted({r["date"][:7] for r in rows})
        expected_months = []
        for y, m in iter_months():
            key = f"{y:04d}-{m:02d}"
            if key >= LISTING_START[symbol][:7] and key <= MAX_DATE[:7]:
                expected_months.append(key)
        missing_months = [x for x in expected_months if x not in seen_months]
        if missing_months:
            raise RuntimeError(f"{symbol} missing listed months: {missing_months}")
        qa[symbol] = {
            "rows": len(rows),
            "first": rows[0]["date"],
            "last": rows[-1]["date"],
            "last_close": rows[-1]["close"],
            "missing_months": missing_months,
        }
        all_rows.extend(rows)

    all_rows.sort(key=lambda r: (r["date"], r["symbol"]))
    write_csv(OUT_ALL, all_rows)

    bad_short = {s: v for s, v in qa.items() if v["rows"] < MIN_ROWS[s]}
    bad_last = {s: v for s, v in qa.items() if v["last"] < "2026-09-18"}
    if bad_short:
        raise RuntimeError(f"coverage below symbol-specific minimum: {bad_short}")
    if bad_last:
        raise RuntimeError(f"stale official coverage: {bad_last}")

    summary = {
        "status": "PASS",
        "max_date": MAX_DATE,
        "symbols": qa,
        "rows_all": len(all_rows),
        "formal_weight": 0,
        "production": "NO_INTERACTION",
    }
    (OUT_DIR / "qa_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
