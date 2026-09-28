#!/usr/bin/env python3
"""Fetch official TAIEX daily OHLC for 2024-01 through 2026-09-24.

Research/PIT dataset for R147 shadow-model walk-forward. Does not touch Production.
"""
from __future__ import annotations
import csv, json, re, time, urllib.request
from pathlib import Path

START_YEAR=2024
END_YEAR=2026
MAX_DATE="2026-09-24"
OUT=Path("output/taiex_2024_2026_official.csv")
QA=Path("output/taiex_2024_2026_qa.json")
UA="stock-data-helper taiex-shadow-warmup/1.0"

def get_json(url,retries=4):
    last=None
    for i in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=45) as r:
                return json.load(r)
        except Exception as e:
            last=e
            time.sleep(1.2*(i+1))
    raise RuntimeError(f"GET failed {url}: {last}")

def roc_to_iso(s):
    s=str(s).strip().replace("年","/").replace("月","/").replace("日","")
    p=re.split(r"[/.-]",s)
    if len(p)!=3:return s
    y,m,d=map(int,p)
    if y<1911:y+=1911
    return f"{y:04d}-{m:02d}-{d:02d}"

def fnum(x):
    try:return float(str(x).strip().replace(",",""))
    except:return None

def main():
    rows=[]
    for year in range(START_YEAR,END_YEAR+1):
        max_month=9 if year==END_YEAR else 12
        for month in range(1,max_month+1):
            datearg=f"{year:04d}{month:02d}01"
            urls=[
              f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={datearg}&response=json",
              f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?date={datearg}&response=json",
            ]
            payload=src=None
            for u in urls:
                try:
                    p=get_json(u)
                    if p.get("data"):
                        payload,src=p,u;break
                except Exception:
                    pass
            if not payload:
                print(f"{year}-{month:02d} no data",flush=True);continue
            fields=[str(x) for x in payload.get("fields",[])]
            oi,hi,li,ci=1,2,3,4
            for i,f in enumerate(fields):
                if "開盤" in f: oi=i
                if "最高" in f: hi=i
                if "最低" in f: li=i
                if "收盤" in f: ci=i
            for r in payload.get("data",[]):
                ds=roc_to_iso(r[0])
                if ds>MAX_DATE or not ds.startswith(str(year)): continue
                op,high,low,cl=[fnum(r[i]) for i in (oi,hi,li,ci)]
                if cl is None: continue
                rows.append({"date":ds,"open":op,"high":high,"low":low,"close":cl,
                             "source":"TWSE MI_5MINS_HIST","source_url":src,"pit_available_date":ds})
            print(f"{year}-{month:02d} cumulative={len(rows)}",flush=True)
            time.sleep(0.15)
    rows=list({r["date"]:r for r in rows}.values())
    rows.sort(key=lambda r:r["date"])
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["date","open","high","low","close","source","source_url","pit_available_date"])
        w.writeheader();w.writerows(rows)
    summary={"status":"PASS" if len(rows)>=650 else "FAIL_SHORT",
             "rows":len(rows),"first":rows[0]["date"] if rows else None,
             "last":rows[-1]["date"] if rows else None,
             "max_date":MAX_DATE,"formal_weight":0,"production":"NO_INTERACTION"}
    QA.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    if len(rows)<650: raise RuntimeError(f"TAIEX rows<650: {summary}")
    if not rows or rows[-1]["date"]<"2026-09-18": raise RuntimeError(f"stale: {summary}")
    print(json.dumps(summary,ensure_ascii=False))
if __name__=="__main__": main()
