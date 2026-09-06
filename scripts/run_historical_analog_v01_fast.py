#!/usr/bin/env python3
"""Fast Historical Analog v0.1 runner using 0050 as the price-path proxy.

Why 0050 here:
- The public release archive supplies daily security closes in the same files used
  to build breadth, including 0050, from 2004 onward.
- This avoids hundreds of TWSE month-by-month index requests and keeps the entire
  walk-forward sample date-aligned with breadth.
- It is explicitly a 0050 proxy backtest, NOT a TAIEX backtest. The production
  model and P4 remain untouched.

Breadth scope: TWSE+TPEX ordinary 4-digit common stocks.
Price path proxy: 0050 close-to-close, unadjusted in the source archive.
Research status: SHADOW / 0 formal weight / P4 LOCKED.
"""
import csv
import io
import json
import os
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

os.environ.setdefault("ANALOG_OUT", "output/historical_analog_v01_fast")

import build_historical_analog_v01 as base

PROXY_0050 = {}


def normalize_date(value):
    s = str(value or "").strip().replace("\ufeff", "")
    # Gregorian YYYYMMDD
    if re.fullmatch(r"\d{8}", s):
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:])
        try:
            datetime(y, m, d)
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            return None
    # ROC YYYMMDD (e.g. 1150904)
    if re.fullmatch(r"\d{7}", s):
        y, m, d = int(s[:3]) + 1911, int(s[3:5]), int(s[5:])
        try:
            datetime(y, m, d)
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            return None
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
                    if not ds:
                        continue
                    groups[ds].append(row)
                    if str(row.get("code", "")).strip() == "0050":
                        cl = base.fnum(row.get("close"))
                        if cl is not None and cl > 0:
                            PROXY_0050[ds] = cl
            for ds in sorted(groups):
                yield ds, groups[ds]


def fetch_0050_proxy():
    # base.main calls build_breadth() first; grouped reader has populated PROXY_0050.
    cutoff = "2026-09-04"
    out = {d: v for d, v in PROXY_0050.items() if d <= cutoff}
    if len(out) < 3000:
        raise RuntimeError(
            f"0050 proxy unexpectedly short: {len(out)} rows; "
            f"range={min(out) if out else None}..{max(out) if out else None}"
        )
    print(f"0050 proxy rows={len(out)} {min(out)}..{max(out)}", flush=True)
    return out


base.iter_daily_csv_from_zip = grouped_daily_csv_from_zip
base.fetch_taiex = fetch_0050_proxy
base.main()

# Correct metadata inherited from the generic base builder so consumers do not
# mistake this fast result for an official TAIEX-price analog.
outdir = Path(os.environ["ANALOG_OUT"])
manifest_path = outdir / "historical_analog_v01_manifest.json"
if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["price_path_proxy"] = "0050 unadjusted close from public TWSE/TPEX-derived release archive"
    manifest["price_path_is_taiex"] = False
    manifest["proxy_rows"] = len(fetch_0050_proxy())
    manifest["limitations"].insert(0, "Price-path proxy is 0050 unadjusted close, not TAIEX; this is a broad-market proxy experiment.")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
