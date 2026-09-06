#!/usr/bin/env python3
"""Fast runner for historical analog v0.1.

Fixes two source-format details without changing the frozen v0.1 research rules:
1) release yearly/weekly CSV files contain MANY trading dates in one CSV, so rows
   must be grouped by the `date` column before breadth is calculated;
2) TWSE open-data TAIEX dates may use ROC/Gregorian localized strings, so date
   parsing accepts numeric YYYY/MM/DD, YYY/MM/DD, and strings containing 年月日.

Research remains SHADOW / 0 formal weight / P4 LOCKED.
"""
import csv
import io
import os
import re
import zipfile
from collections import defaultdict
from datetime import datetime

os.environ.setdefault("ANALOG_OUT", "output/historical_analog_v01_fast")

import build_historical_analog_v01 as base

TAIEX_OPEN_DATA = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=open_data"


def normalize_date(value):
    s = str(value or "").strip().replace("\ufeff", "")
    if re.fullmatch(r"\d{8}", s):
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:])
        return f"{y:04d}-{m:02d}-{d:02d}"
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if len(nums) >= 3:
        y, m, d = nums[0], nums[1], nums[2]
        if y < 1911:
            y += 1911
        try:
            datetime(y, m, d)
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            return None
    return None


def grouped_daily_csv_from_zip(name, url):
    raw = base.get_bytes(url)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        entries = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
        for entry in entries:
            with zf.open(entry) as bf:
                text = io.TextIOWrapper(bf, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text)
                groups = defaultdict(list)
                for row in reader:
                    ds = normalize_date(row.get("date"))
                    if ds:
                        groups[ds].append(row)
            for ds in sorted(groups):
                yield ds, groups[ds]


def fast_fetch_taiex():
    raw = base.get_bytes(TAIEX_OPEN_DATA, retries=4)
    text = None
    for enc in ("utf-8-sig", "big5", "cp950", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise RuntimeError("Unable to decode TWSE MI_5MINS_HIST open_data CSV")

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise RuntimeError("TWSE TAIEX open_data returned no rows")
    header = [str(x).strip().replace("\ufeff", "") for x in rows[0]]
    date_idx, close_idx = 0, None
    for i, h in enumerate(header):
        if "日期" in h or h.lower() == "date":
            date_idx = i
        if "收盤" in h or "closing" in h.lower() or h.lower() == "close":
            close_idx = i
    if close_idx is None:
        close_idx = 4

    out = {}
    sample_dates = []
    for row in rows[1:]:
        if len(row) <= max(date_idx, close_idx):
            continue
        if len(sample_dates) < 5:
            sample_dates.append(str(row[date_idx]))
        ds = normalize_date(row[date_idx])
        if not ds:
            continue
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            continue
        if dt > datetime(2026, 9, 4).date():
            continue
        cl = base.fnum(row[close_idx])
        if cl is not None:
            out[ds] = cl
    if len(out) < 3000:
        raise RuntimeError(
            f"TAIEX open_data unexpectedly short: {len(out)} rows; "
            f"header={header}; sample_dates={sample_dates}"
        )
    print(f"fast TAIEX rows={len(out)} {min(out)}..{max(out)}", flush=True)
    return out


base.iter_daily_csv_from_zip = grouped_daily_csv_from_zip
base.fetch_taiex = fast_fetch_taiex
base.main()
