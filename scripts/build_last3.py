from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

SOURCE_REPO = "yukishirotsubasa/tw-stock-data-release"
SOURCE_TAG = "daily-close-csv"
CUTOFF = "20260817"
TARGETS = {
    "3665": {"name": "貿聯-KY", "start": "20180102"},
    "4916": {"name": "事欣科", "start": "20180102"},
    "6770": {"name": "力積電", "start": "20211206"},
}
SAMPLE_MONTHS = {
    "3665": ["201801", "202307", "202608"],
    "4916": ["201801", "202407", "202608"],
    "6770": ["202112", "202303", "202608"],
}
OUT = Path("output")
OUT.mkdir(exist_ok=True)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "stock-data-helper/1.0"})


def get_json(url: str, retries: int = 4):
    last = None
    for i in range(retries):
        try:
            r = SESSION.get(url, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"GET failed: {url}: {last}")


def download(url: str, retries: int = 4) -> bytes:
    last = None
    for i in range(retries):
        try:
            r = SESSION.get(url, timeout=180)
            r.raise_for_status()
            return r.content
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"download failed: {url}: {last}")


def asset_plan():
    rel = get_json(f"https://api.github.com/repos/{SOURCE_REPO}/releases/tags/{SOURCE_TAG}")
    assets = {a["name"]: a for a in rel.get("assets", [])}
    wanted = [f"yearly_{y}.zip" for y in range(2018, 2026)]
    wanted += sorted(
        [n for n in assets if re.fullmatch(r"weekly_2026_W\d{2}\.zip", n)],
        key=lambda x: int(re.search(r"W(\d{2})", x).group(1)),
    )
    missing = [n for n in wanted[:8] if n not in assets]
    if missing:
        raise RuntimeError(f"Missing yearly assets: {missing}")
    return [assets[n] for n in wanted if n in assets]


def dec(v: str) -> Decimal:
    s = (v or "").replace(",", "").strip()
    if s in {"", "--", "---", "除權", "除息"}:
        raise InvalidOperation
    return Decimal(s)


def norm_date(s: str) -> str:
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return s
    if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", s):
        return re.sub(r"[-/]", "", s)
    m = re.fullmatch(r"(\d{2,3})/(\d{2})/(\d{2})", s)
    if m:
        y = int(m.group(1)) + 1911
        return f"{y:04d}{m.group(2)}{m.group(3)}"
    return s


def read_zip_rows(blob: bytes, asset_name: str, rows_by_code, manifest):
    digest = hashlib.sha256(blob).hexdigest()
    expected = None
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".csv"):
                continue
            with z.open(info) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text)
                if not reader.fieldnames:
                    continue
                fmap = {h.strip().lower(): h for h in reader.fieldnames}
                required = {"date", "code", "name", "volume", "open", "high", "low", "close"}
                if not required.issubset(set(fmap)):
                    continue
                for r in reader:
                    code = (r.get(fmap["code"]) or "").strip()
                    if code not in TARGETS:
                        continue
                    d = norm_date(r.get(fmap["date"]) or "")
                    if not (TARGETS[code]["start"] <= d <= CUTOFF):
                        continue
                    row = {
                        "date": d,
                        "code": code,
                        "name": (r.get(fmap["name"]) or "").strip(),
                        "volume": (r.get(fmap["volume"]) or "").replace(",", "").strip(),
                        "open": (r.get(fmap["open"]) or "").replace(",", "").strip(),
                        "high": (r.get(fmap["high"]) or "").replace(",", "").strip(),
                        "low": (r.get(fmap["low"]) or "").replace(",", "").strip(),
                        "close": (r.get(fmap["close"]) or "").replace(",", "").strip(),
                        "source_asset": asset_name,
                    }
                    rows_by_code[code].append(row)
    return digest


def qa_rows(code: str, rows: list[dict]):
    seen = defaultdict(int)
    duplicate_rows = 0
    null_rows = 0
    ohlc_bad = 0
    date_bad = 0
    valid_dates = []
    for r in rows:
        seen[r["date"]] += 1
        if seen[r["date"]] > 1:
            duplicate_rows += 1
        if not (TARGETS[code]["start"] <= r["date"] <= CUTOFF):
            date_bad += 1
        try:
            o, h, l, c = map(dec, (r["open"], r["high"], r["low"], r["close"]))
            if h < max(o, c) or l > min(o, c) or h < l:
                ohlc_bad += 1
        except Exception:
            null_rows += 1
        valid_dates.append(r["date"])
    uniq_dates = sorted(set(valid_dates))
    gaps = []
    for a, b in zip(uniq_dates, uniq_dates[1:]):
        da = datetime.strptime(a, "%Y%m%d")
        db = datetime.strptime(b, "%Y%m%d")
        gaps.append((db - da).days)
    max_gap = max(gaps) if gaps else None
    continuity_reasonable = (max_gap is not None and max_gap <= 20)
    return {
        "code": code,
        "name": TARGETS[code]["name"],
        "rows": len(rows),
        "unique_dates": len(uniq_dates),
        "first_date": uniq_dates[0] if uniq_dates else None,
        "last_date": uniq_dates[-1] if uniq_dates else None,
        "duplicate_rows": duplicate_rows,
        "null_or_non_numeric_rows": null_rows,
        "ohlc_logic_bad_rows": ohlc_bad,
        "date_boundary_bad_rows": date_bad,
        "max_calendar_gap_days": max_gap,
        "continuity_reasonable": continuity_reasonable,
    }


def twse_month(code: str, yyyymm: str):
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={yyyymm}01&stockNo={code}&response=json"
    data = get_json(url)
    out = {}
    for row in data.get("data", []):
        if len(row) < 7:
            continue
        d = norm_date(row[0])
        if d > CUTOFF:
            continue
        try:
            out[d] = {
                "volume": str(int(row[1].replace(",", ""))),
                "open": str(dec(row[3])),
                "high": str(dec(row[4])),
                "low": str(dec(row[5])),
                "close": str(dec(row[6])),
            }
        except Exception:
            continue
    return url, out


def compare_twse(code: str, dedup: dict[str, dict]):
    results = []
    total_checked = 0
    mismatch = 0
    fetch_errors = []
    for ym in SAMPLE_MONTHS[code]:
        try:
            url, official = twse_month(code, ym)
        except Exception as e:
            fetch_errors.append({"month": ym, "error": str(e)})
            continue
        month_checked = 0
        month_mismatch = 0
        for d, off in official.items():
            if d not in dedup:
                continue
            src = dedup[d]
            month_checked += 1
            total_checked += 1
            for k in ("open", "high", "low", "close"):
                try:
                    if dec(src[k]) != dec(off[k]):
                        month_mismatch += 1
                        mismatch += 1
                        break
                except Exception:
                    month_mismatch += 1
                    mismatch += 1
                    break
        results.append({
            "month": ym,
            "official_url": url,
            "official_rows": len(official),
            "compared_rows": month_checked,
            "mismatch_rows": month_mismatch,
        })
        time.sleep(1.0)
    return {
        "code": code,
        "months": results,
        "total_compared_rows": total_checked,
        "mismatch_rows": mismatch,
        "fetch_errors": fetch_errors,
        "pass": total_checked > 0 and mismatch == 0 and not fetch_errors,
    }


def main():
    plan = asset_plan()
    rows_by_code = defaultdict(list)
    manifest_rows = []
    print(f"Assets selected: {len(plan)}")
    for i, a in enumerate(plan, 1):
        name = a["name"]
        print(f"[{i}/{len(plan)}] {name}")
        blob = download(a["browser_download_url"])
        actual = hashlib.sha256(blob).hexdigest()
        exp = (a.get("digest") or "").replace("sha256:", "") or None
        sha_ok = (exp is None or exp == actual)
        if not sha_ok:
            raise RuntimeError(f"SHA mismatch for {name}")
        before = {c: len(rows_by_code[c]) for c in TARGETS}
        read_zip_rows(blob, name, rows_by_code, manifest_rows)
        added = sum(len(rows_by_code[c]) - before[c] for c in TARGETS)
        manifest_rows.append({
            "asset": name,
            "size_bytes": len(blob),
            "sha256": actual,
            "expected_sha256": exp or "",
            "sha_ok": sha_ok,
            "target_rows_added": added,
            "url": a["browser_download_url"],
        })

    qa = []
    twse = []
    for code in TARGETS:
        rows = rows_by_code[code]
        dedup = {}
        duplicates_conflict = 0
        for r in rows:
            d = r["date"]
            if d in dedup:
                prev = dedup[d]
                if any(prev[k] != r[k] for k in ("open", "high", "low", "close", "volume")):
                    duplicates_conflict += 1
            else:
                dedup[d] = r
        ordered = [dedup[d] for d in sorted(dedup)]
        out_path = OUT / f"{code}.csv"
        with out_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date","code","name","volume","open","high","low","close","source_asset"])
            w.writeheader()
            w.writerows(ordered)
        q = qa_rows(code, rows)
        q["dedup_output_rows"] = len(ordered)
        q["duplicate_value_conflicts"] = duplicates_conflict
        q["raw_pass"] = (
            q["duplicate_rows"] == 0
            and q["null_or_non_numeric_rows"] == 0
            and q["ohlc_logic_bad_rows"] == 0
            and q["date_boundary_bad_rows"] == 0
            and q["continuity_reasonable"]
            and len(ordered) > 0
        )
        qa.append(q)
        twse.append(compare_twse(code, dedup))

    with (OUT / "source_manifest.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader(); w.writerows(manifest_rows)

    with (OUT / "qa_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = list(qa[0].keys())
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(qa)

    report = {
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source_repo": SOURCE_REPO,
        "source_tag": SOURCE_TAG,
        "cutoff": CUTOFF,
        "targets": TARGETS,
        "qa": qa,
        "twse_crosscheck": twse,
    }
    report["all_pass"] = all(x["raw_pass"] for x in qa) and all(x["pass"] for x in twse)
    (OUT / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_pass"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
