#!/usr/bin/env python3
"""Collect official TWSE-only breadth and official TAIEX history for one year.

Research/data-engineering utility for 存股作戰地圖.
- Official breadth source: TWSE afterTrading/MI_INDEX JSON, stock column from 漲跌證券數合計.
- Official TAIEX source: TWSE TAIEX/MI_5MINS_HIST monthly JSON.
- Trading calendar: previously generated proxy breadth CSV in this repo, only to identify trading dates.

This script does not touch production/P4 model weights.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

UA = "stock-data-helper official-twse-breadth/1.0"
CALENDAR = Path("output/historical_analog_v01_fast/market_breadth_full_history.csv")
OUTDIR = Path("output/twse_official_breadth_taiex")


def get_json(url: str, retries: int = 5, sleep_base: float = 1.2):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(sleep_base * (i + 1))
    raise RuntimeError(f"GET failed: {url}: {last}")


def n(x):
    if x is None:
        return None
    s = re.sub(r"[^0-9.-]", "", str(x).replace(",", ""))
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def roc_to_iso(s: str) -> str:
    s = str(s).strip().replace("年", "/").replace("月", "/").replace("日", "")
    parts = re.split(r"[/.-]", s)
    if len(parts) != 3:
        return str(s)
    y, m, d = map(int, parts)
    if y < 1911:
        y += 1911
    return f"{y:04d}-{m:02d}-{d:02d}"


def trading_dates(year: int):
    if not CALENDAR.exists():
        raise RuntimeError(f"calendar missing: {CALENDAR}")
    out=[]
    with CALENDAR.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            ds=r.get("date","")
            if ds.startswith(f"{year:04d}-"):
                out.append(ds)
    return sorted(set(out))


def parse_breadth(payload, ds):
    tables = payload.get("tables") or []
    # table title contains 漲跌證券數合計. Fields are typically 類型/整體市場/股票.
    for t in tables:
        title = str(t.get("title", ""))
        fields = [str(x).strip() for x in (t.get("fields") or [])]
        data = t.get("data") or []
        if "漲跌證券數" not in title:
            continue
        stock_idx = None
        for i, f in enumerate(fields):
            if f == "股票" or "股票" in f:
                stock_idx=i
        if stock_idx is None:
            continue
        vals={}
        limits={}
        for row in data:
            if len(row) <= stock_idx:
                continue
            typ=str(row[0]).strip()
            raw=str(row[stock_idx]).strip()
            m=re.search(r"([0-9,]+)(?:\(([0-9,]+)\))?", raw)
            if not m:
                continue
            count=int(m.group(1).replace(",",""))
            lim=int(m.group(2).replace(",","")) if m.group(2) else 0
            if typ.startswith("上漲"):
                vals["up"], limits["limit_up"] = count, lim
            elif typ.startswith("下跌"):
                vals["down"], limits["limit_down"] = count, lim
            elif typ.startswith("持平"):
                vals["flat"] = count
            elif typ.startswith("未成交"):
                vals["no_trade"] = count
            elif typ.startswith("無比價"):
                vals["no_compare"] = count
        if "up" in vals and "down" in vals:
            up=vals.get("up",0); down=vals.get("down",0); flat=vals.get("flat",0)
            denom=up+down+flat
            return {
                "date":ds,
                "up":up,"down":down,"flat":flat,
                "no_trade":vals.get("no_trade",0),"no_compare":vals.get("no_compare",0),
                "limit_up":limits.get("limit_up",0),"limit_down":limits.get("limit_down",0),
                "advance_decline_ratio": (up/down if down else None),
                "advance_share": (up/denom if denom else None),
                "breadth_n":denom,
                "source":"TWSE afterTrading/MI_INDEX",
            }
    return None


def fetch_breadth(ds: str):
    ymd=ds.replace("-","")
    urls=[
        f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=MS&response=json",
        f"https://www.twse.com.tw/exchangeReport/MI_INDEX?date={ymd}&type=MS&response=json",
        f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json",
    ]
    for url in urls:
        try:
            p=get_json(url, retries=3, sleep_base=.8)
            r=parse_breadth(p,ds)
            if r:
                r["source_url"]=url
                return r
        except Exception:
            pass
    return None


def fetch_taiex_year(year: int):
    out=[]
    for month in range(1,13):
        if year == 2026 and month > 9:
            break
        datearg=f"{year:04d}{month:02d}01"
        urls=[
            f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={datearg}&response=json",
            f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?date={datearg}&response=json",
        ]
        payload=None; src=None
        for u in urls:
            try:
                p=get_json(u,retries=3,sleep_base=.8)
                if p.get("data"):
                    payload=p; src=u; break
            except Exception:
                pass
        if not payload:
            continue
        fields=[str(x) for x in payload.get("fields",[])]
        close_idx=4
        for i,field in enumerate(fields):
            if "收盤" in field:
                close_idx=i; break
        for row in payload.get("data",[]):
            if len(row)<=close_idx:
                continue
            ds=roc_to_iso(row[0])
            if not ds.startswith(str(year)):
                continue
            close=n(row[close_idx])
            if close is None:
                continue
            out.append({"date":ds,"close":close,"source":"TWSE MI_5MINS_HIST","source_url":src})
        time.sleep(.25)
    uniq={r["date"]:r for r in out}
    return [uniq[k] for k in sorted(uniq)]


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--year",type=int,required=True); args=ap.parse_args()
    year=args.year
    dates=trading_dates(year)
    breadth=[]; missing=[]
    for i,ds in enumerate(dates,1):
        r=fetch_breadth(ds)
        if r: breadth.append(r)
        else: missing.append(ds)
        if i % 25 == 0: print(f"{year} breadth {i}/{len(dates)} ok={len(breadth)} missing={len(missing)}",flush=True)
        time.sleep(.22)
    taiex=fetch_taiex_year(year)
    OUTDIR.mkdir(parents=True,exist_ok=True)
    bfields=["date","up","down","flat","no_trade","no_compare","limit_up","limit_down","advance_decline_ratio","advance_share","breadth_n","source","source_url"]
    tfields=["date","close","source","source_url"]
    write_csv(OUTDIR/f"twse_official_breadth_{year}.csv",breadth,bfields)
    write_csv(OUTDIR/f"twse_official_taiex_{year}.csv",taiex,tfields)
    meta={
        "year":year,"calendar_dates":len(dates),"breadth_rows":len(breadth),"breadth_missing":missing,
        "taiex_rows":len(taiex),"generated_at":datetime.utcnow().isoformat()+"Z",
        "official":True,"breadth_scope":"TWSE listed stock column from 漲跌證券數合計",
        "p4":"NO INTERACTION","formal_weight":0
    }
    (OUTDIR/f"meta_{year}.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(meta,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
