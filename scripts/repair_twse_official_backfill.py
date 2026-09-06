#!/usr/bin/env python3
"""Repair partial official TWSE breadth/TAIEX backfill from a previous artifact run.

This is a data-quality pass for 存股作戰地圖. It retries only missing official
TWSE observations, uses slower requests, and adds CSV/HTML fallbacks to reduce
rate-limit/legacy-format gaps.

It is research/data engineering only: formal model weight remains 0 and P4 has
NO INTERACTION.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

UA = "stock-data-helper twse-official-repair/1.0"


def read_bytes(url: str, retries: int = 5):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "text/csv,text/html,application/json;q=0.9,*/*;q=0.8",
                    "Referer": "https://www.twse.com.tw/",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 403, 503):
                time.sleep(3.0 * (i + 1))
            else:
                time.sleep(1.2 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    return None, str(last)


def decode_text(raw: bytes):
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


def n(x):
    if x is None:
        return None
    s = re.sub(r"[^0-9.+-]", "", str(x).replace(",", ""))
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_count_with_limit(raw):
    s = str(raw).strip().replace(",", "")
    m = re.search(r"([0-9]+)(?:\(([0-9]+)\))?", s)
    if not m:
        return None, 0
    return int(m.group(1)), int(m.group(2) or 0)


def breadth_from_table_rows(rows, ds, source, url):
    for i, row in enumerate(rows):
        vals = [str(x).strip() for x in row]
        if not vals:
            continue
        if vals[0] != "類型" or not any("股票" == x for x in vals):
            continue
        stock_idx = next(j for j, x in enumerate(vals) if x == "股票")
        data = {}
        limits = {}
        for rr in rows[i + 1:i + 8]:
            if len(rr) <= stock_idx:
                continue
            typ = str(rr[0]).strip()
            count, lim = parse_count_with_limit(rr[stock_idx])
            if count is None:
                continue
            if typ.startswith("上漲"):
                data["up"] = count; limits["limit_up"] = lim
            elif typ.startswith("下跌"):
                data["down"] = count; limits["limit_down"] = lim
            elif typ.startswith("持平"):
                data["flat"] = count
            elif typ.startswith("未成交"):
                data["no_trade"] = count
            elif typ.startswith("無比價"):
                data["no_compare"] = count
        if "up" in data and "down" in data:
            up=data.get("up",0); down=data.get("down",0); flat=data.get("flat",0)
            denom=up+down+flat
            return {
                "date": ds,
                "up": up,
                "down": down,
                "flat": flat,
                "no_trade": data.get("no_trade",0),
                "no_compare": data.get("no_compare",0),
                "limit_up": limits.get("limit_up",0),
                "limit_down": limits.get("limit_down",0),
                "advance_decline_ratio": (up/down if down else None),
                "advance_share": (up/denom if denom else None),
                "breadth_n": denom,
                "source": source,
                "source_url": url,
            }
    return None


def parse_csv_breadth(text, ds, url):
    try:
        rows = list(csv.reader(io.StringIO(text)))
        return breadth_from_table_rows(rows, ds, "TWSE MI_INDEX CSV", url)
    except Exception:
        return None


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows=[]; self.row=[]; self.cell=[]; self.in_cell=False
    def handle_starttag(self, tag, attrs):
        if tag in ("td","th"):
            self.in_cell=True; self.cell=[]
        elif tag=="tr":
            self.row=[]
    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ("td","th") and self.in_cell:
            self.row.append(html.unescape("".join(self.cell)).strip())
            self.in_cell=False
        elif tag=="tr" and self.row:
            self.rows.append(self.row)
            self.row=[]


def parse_html_breadth(text, ds, url):
    try:
        p=TableParser(); p.feed(text)
        return breadth_from_table_rows(p.rows, ds, "TWSE MI_INDEX HTML", url)
    except Exception:
        return None


def parse_json_breadth(text, ds, url):
    try:
        payload=json.loads(text)
    except Exception:
        return None
    tables=payload.get("tables") or []
    for t in tables:
        title=str(t.get("title", ""))
        if "漲跌證券數" not in title:
            continue
        fields=[str(x).strip() for x in (t.get("fields") or [])]
        data=t.get("data") or []
        if not fields or not data:
            continue
        rows=[fields]+data
        r=breadth_from_table_rows(rows,ds,"TWSE MI_INDEX JSON",url)
        if r:
            return r
    return None


def fetch_breadth(ds):
    ymd=ds.replace("-","")
    urls=[
        f"https://www.twse.com.tw/exchangeReport/MI_INDEX?date={ymd}&type=MS&response=csv",
        f"https://www.twse.com.tw/exchangeReport/MI_INDEX?date={ymd}&type=ALLBUT0999&response=csv",
        f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=MS&response=json",
        f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json",
        f"https://www.twse.com.tw/exchangeReport/MI_INDEX?date={ymd}&type=MS&response=html",
        f"https://www.twse.com.tw/exchangeReport/MI_INDEX?date={ymd}&type=ALLBUT0999&response=html",
    ]
    for url in urls:
        raw, ct=read_bytes(url, retries=3)
        if not raw:
            continue
        text=decode_text(raw)
        if "response=csv" in url:
            r=parse_csv_breadth(text,ds,url)
        elif "response=json" in url:
            r=parse_json_breadth(text,ds,url)
        else:
            r=parse_html_breadth(text,ds,url)
        if r:
            return r
        time.sleep(.15)
    return None


def roc_to_iso(s):
    parts=re.split(r"[/.-]",str(s).strip())
    if len(parts)!=3:
        return str(s)
    try:
        y,m,d=map(int,parts)
    except Exception:
        return str(s)
    if y<1911: y+=1911
    return f"{y:04d}-{m:02d}-{d:02d}"


def fetch_taiex_month(year, month):
    datearg=f"{year:04d}{month:02d}01"
    urls=[
        f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={datearg}&response=json",
        f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=json&date={datearg}",
    ]
    for url in urls:
        raw, ct=read_bytes(url,retries=5)
        if not raw:
            continue
        try:
            p=json.loads(decode_text(raw))
        except Exception:
            continue
        data=p.get("data") or []
        if not data:
            continue
        fields=[str(x) for x in p.get("fields",[])]
        close_idx=4
        for i,field in enumerate(fields):
            if "收盤" in field:
                close_idx=i; break
        out=[]
        for row in data:
            if len(row)<=close_idx: continue
            ds=roc_to_iso(row[0]); cl=n(row[close_idx])
            if ds.startswith(str(year)) and cl is not None:
                out.append({"date":ds,"close":cl,"source":"TWSE MI_5MINS_HIST","source_url":url})
        if out:
            return out
    return []


def read_csv_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def repair_year(year, input_dir, output_dir):
    meta_path=input_dir/f"meta_{year}.json"
    if not meta_path.exists():
        raise RuntimeError(f"missing meta {meta_path}")
    meta=json.loads(meta_path.read_text(encoding="utf-8"))
    bfile=input_dir/f"twse_official_breadth_{year}.csv"
    tfile=input_dir/f"twse_official_taiex_{year}.csv"
    brows={r["date"]:r for r in read_csv_rows(bfile)}
    trows={r["date"]:r for r in read_csv_rows(tfile)}
    expected=sorted(set(list(brows)+list(meta.get("breadth_missing",[]))))

    missing=[d for d in expected if d not in brows]
    recovered=0
    for i,ds in enumerate(missing,1):
        r=fetch_breadth(ds)
        if r:
            brows[ds]={k:("" if v is None else v) for k,v in r.items()}; recovered+=1
        if i%25==0:
            print(f"{year} breadth repair {i}/{len(missing)} recovered={recovered}",flush=True)
        time.sleep(.55)

    # Repair TAIEX by missing months only.
    missing_t_dates=[d for d in expected if d not in trows]
    months=sorted(set((int(d[5:7]) for d in missing_t_dates)))
    for month in months:
        got=fetch_taiex_month(year,month)
        for r in got:
            trows[r["date"]]={k:("" if v is None else v) for k,v in r.items()}
        print(f"{year} TAIEX month {month:02d}: got={len(got)} total={len(trows)}",flush=True)
        time.sleep(1.0)

    bfields=["date","up","down","flat","no_trade","no_compare","limit_up","limit_down","advance_decline_ratio","advance_share","breadth_n","source","source_url"]
    tfields=["date","close","source","source_url"]
    bout=[brows[k] for k in sorted(brows)]
    tout=[trows[k] for k in sorted(trows)]
    write_csv(output_dir/f"twse_official_breadth_{year}.csv",bout,bfields)
    write_csv(output_dir/f"twse_official_taiex_{year}.csv",tout,tfields)
    miss_b=[d for d in expected if d not in brows]
    miss_t=[d for d in expected if d not in trows]
    outmeta={
        "year":year,
        "calendar_dates":len(expected),
        "breadth_rows":len(bout),
        "breadth_missing":miss_b,
        "breadth_coverage":len(bout)/len(expected) if expected else 0,
        "taiex_rows":len(tout),
        "taiex_missing":miss_t,
        "taiex_coverage":len(tout)/len(expected) if expected else 0,
        "repair_recovered_breadth":recovered,
        "official":True,
        "formal_weight":0,
        "p4":"NO INTERACTION",
    }
    (output_dir/f"meta_{year}.json").write_text(json.dumps(outmeta,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(outmeta,ensure_ascii=False),flush=True)
    return outmeta


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--years",required=True,help="e.g. 2004-2009 or 2021,2022,2023")
    ap.add_argument("--input-dir",default="/tmp/base")
    ap.add_argument("--output-dir",default="output/twse_official_repair")
    args=ap.parse_args()
    years=[]
    for part in args.years.split(","):
        if "-" in part:
            a,b=map(int,part.split("-",1)); years.extend(range(a,b+1))
        else:
            years.append(int(part))
    inp=Path(args.input_dir); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    metas=[]
    for year in years:
        metas.append(repair_year(year,inp,out))
    manifest={
        "years":years,
        "calendar_dates":sum(x["calendar_dates"] for x in metas),
        "breadth_rows":sum(x["breadth_rows"] for x in metas),
        "taiex_rows":sum(x["taiex_rows"] for x in metas),
        "breadth_coverage":sum(x["breadth_rows"] for x in metas)/sum(x["calendar_dates"] for x in metas),
        "taiex_coverage":sum(x["taiex_rows"] for x in metas)/sum(x["calendar_dates"] for x in metas),
        "formal_weight":0,"p4":"NO INTERACTION"
    }
    (out/"repair_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
