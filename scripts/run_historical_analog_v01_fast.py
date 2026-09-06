#!/usr/bin/env python3
"""Fast runner for historical analog v0.1 using TWSE one-shot open-data TAIEX CSV.

This imports the frozen v0.1 breadth/analog builder and only replaces its slow
monthly TAIEX downloader. Research remains SHADOW / 0 formal weight / P4 LOCKED.
"""
import csv
import io
import os
import re
from datetime import datetime

os.environ.setdefault("ANALOG_OUT", "output/historical_analog_v01_fast")

import build_historical_analog_v01 as base

TAIEX_OPEN_DATA = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=open_data"


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

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise RuntimeError("TWSE TAIEX open_data returned no rows")

    header = [str(x).strip().replace("\ufeff", "") for x in rows[0]]
    close_idx = None
    date_idx = 0
    for i, h in enumerate(header):
        if "日期" in h or h.lower() == "date":
            date_idx = i
        if "收盤" in h or "closing" in h.lower() or h.lower() == "close":
            close_idx = i
    if close_idx is None:
        close_idx = 4

    out = {}
    for row in rows[1:]:
        if len(row) <= max(date_idx, close_idx):
            continue
        ds = base.roc_to_iso(str(row[date_idx]))
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d").date()
        except Exception:
            continue
        if dt > datetime(2026, 9, 4).date():
            continue
        cl = base.fnum(row[close_idx])
        if cl is not None:
            out[ds] = cl
    if len(out) < 3000:
        raise RuntimeError(f"TAIEX open_data unexpectedly short: {len(out)} rows; header={header}")
    print(f"fast TAIEX rows={len(out)} {min(out)}..{max(out)}", flush=True)
    return out


base.fetch_taiex = fast_fetch_taiex
base.main()
