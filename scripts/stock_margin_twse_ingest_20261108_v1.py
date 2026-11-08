#!/usr/bin/env python3
"""Fail-closed TWSE aggregate financing research collector (no production writes).

Accept downloaded official MI_MARGN JSON or fetch one specifically dated report.
Keep source bytes, SHA256, observed capture time and conservative PIT eligibility.
This tool does not revise PRESEALED forecasts, settlement, positions or model weights.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Taipei")
SOURCE = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
FIELDS = ("buy", "sell", "cash_repay", "previous", "current")
LABELS = {
    "融資(交易單位)": "units",
    "融資金額(仟元)": "amount_thousand_twd",
}


class SourceError(ValueError):
    """Source cannot be used to construct model inputs."""


def numeric(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SourceError(f"Invalid official numeric field: {value!r}")
    cleaned = str(value).replace(",", "").strip()
    if not re.fullmatch(r"[0-9]+", cleaned):
        raise SourceError(f"Missing or non-integer official numeric field: {value!r}")
    return int(cleaned)


def normalize_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def validate_report_date(report: dict, d: date) -> None:
    stamp = report.get("date")
    if stamp is None or stamp == "":
        # Some historical MI_MARGN response variants omit this metadata.
        return
    if not isinstance(stamp, str):
        raise SourceError("Unexpected TWSE report date datatype")
    cleaned = stamp.strip()
    ymd = d.strftime("%Y%m%d")
    roc = f"{d.year - 1911}{d:%m%d}"
    roc_chinese = f"{d.year - 1911}年{d:%m}月{d:%d}日"
    if cleaned not in (ymd, roc, roc_chinese):
        raise SourceError(f"TWSE response date {cleaned!r} != requested {ymd}")


def extract_rows(report: dict) -> dict[str, tuple[int, ...]]:
    """Match labels, never assume an unlabelled table's order or silently fill gaps."""
    candidates = []
    credit = report.get("creditList")
    if isinstance(credit, list):
        candidates.extend(credit)
    tables = report.get("tables", [])
    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue
            if "信用交易統計" in str(table.get("title", "")):
                data = table.get("data")
                if isinstance(data, list):
                    candidates.extend(data)
    found: dict[str, tuple[int, ...]] = {}
    for raw in candidates:
        if not isinstance(raw, (list, tuple)) or not raw:
            continue
        label = normalize_label(raw[0])
        if label not in LABELS:
            continue
        key = LABELS[label]
        if key in found:
            raise SourceError(f"Duplicate financing summary row {label}")
        contents = list(raw[1:])
        if len(contents) == 1 and isinstance(contents[0], (list, tuple)):
            contents = list(contents[0])
        if len(contents) != 5:
            raise SourceError(f"Expected exactly five TWSE balances for {label}")
        found[key] = tuple(numeric(x) for x in contents)
    if set(found) != set(LABELS.values()):
        raise SourceError("Missing two explicitly labelled financing balance rows")
    return found


def reconcile(label: str, values: tuple[int, ...]) -> dict:
    buy, sell, cash, previous, current = values
    expected = previous + buy - sell - cash
    if current != expected:
        raise SourceError(f"Official {label} arithmetic mismatch: {current} vs {expected}")
    if previous <= 0:
        raise SourceError(f"Official {label} prior balance not positive")
    change = current - previous
    percentage = (Decimal(change) * 100 / Decimal(previous)).quantize(Decimal("0.0001"))
    return {"buy": buy, "sell": sell, "cash_repay": cash,
            "previous": previous, "current": current, "delta": change,
            "delta_percent": str(percentage)}


def parse_source(raw_bytes: bytes, trade_date: date, capture: datetime) -> dict:
    if capture.tzinfo is None or capture.utcoffset() is None:
        raise SourceError("Capture timestamp must include a time zone")
    try:
        report = json.loads(raw_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceError("Invalid TWSE official JSON") from exc
    if not isinstance(report, dict) or report.get("stat") != "OK":
        raise SourceError("TWSE status not OK; never treat no-data as zero")
    validate_report_date(report, trade_date)
    if capture.astimezone(TZ).date() < trade_date:
        raise SourceError("Capture predates the reported trading day")
    rows = extract_rows(report)
    values = {key: reconcile(key, row) for key, row in rows.items()}
    first_pit_day = capture.astimezone(TZ).date() + timedelta(days=1)
    first_pit_time = datetime.combine(first_pit_day, time.min, tzinfo=TZ)
    return {
        "module": "FINANCING_BALANCE_CHANGE_V1_RESEARCH_ONLY",
        "trading_date": trade_date.isoformat(),
        "market": "TWSE_LISTED_ONLY",
        "source_url": f"{SOURCE}?date={trade_date:%Y%m%d}&selectType=MS&response=json",
        "raw_source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "captured_at": capture.isoformat(),
        "conservative_first_pit_at": first_pit_time.isoformat(),
        "amount_unit": "1000_TWD",
        "units": values["units"],
        "amount_thousand_twd": values["amount_thousand_twd"],
        "source_reconciliation": "PASS",
        "stock_level_data": "NOT_INCLUDED",
        "tpex_data": "NOT_INCLUDED",
        "forced_margin_calls": "NOT_IDENTIFIABLE_FROM_THIS_REPORT",
        "formal_prediction_modified": False,
        "formal_settlement_modified": False,
    }


def fetch(date_to_fetch: date) -> bytes:
    url = f"{SOURCE}?date={date_to_fetch:%Y%m%d}&selectType=MS&response=json"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "StockResearchPIT/1.0"})
    with urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise SourceError(f"TWSE HTTP {response.status}")
        payload = response.read(2_000_001)
        if len(payload) > 2_000_000:
            raise SourceError("Unexpected official response size")
        return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Official trading date YYYY-MM-DD")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-json", type=Path, help="Saved official JSON (offline source)")
    group.add_argument("--fetch", action="store_true", help="Fetch this exact date from TWSE")
    parser.add_argument("--captured-at", help="Observed capture timestamp with UTC offset; required for offline file")
    parser.add_argument("--out", type=Path, help="Optional isolated JSON output; stdout otherwise")
    parser.add_argument("--archive-raw", type=Path, help="Optional raw-source archive (refuses overwrite)")
    args = parser.parse_args(argv)
    try:
        day = date.fromisoformat(args.date)
        if args.source_json is not None:
            if not args.captured_at:
                raise SourceError("Offline file requires observed --captured-at")
            raw = args.source_json.read_bytes()
            capture = datetime.fromisoformat(args.captured_at)
        else:
            raw = fetch(day)
            capture = datetime.now(TZ)
        result = parse_source(raw, day, capture)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.archive_raw and args.archive_raw == args.out:
            raise SourceError("Raw source and derived result must use different paths")
        if args.archive_raw and args.archive_raw.exists():
            raise SourceError("Existing raw-source archive never overwritten")
        if args.out:
            if args.out.exists():
                raise SourceError("Existing destination never overwritten")
        if args.archive_raw:
            with args.archive_raw.open("xb") as handle:
                handle.write(raw)
        if args.out:
            with args.out.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            sys.stdout.write(rendered)
        return 0
    except (SourceError, OSError, ValueError) as exc:
        sys.stderr.write(f"FAIL_CLOSED: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
