#!/usr/bin/env python3
"""Materialize canonical shadow-model PIT feature matrix from official TWSE CSVs.

No Production interaction. Features are known as of each row's cutoff date.
Target columns are isolated and carry a separate target_available_date.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd

IN_STOCK=Path("output/r146_shadow/stocks_daily.csv")
IN_MKT=Path("output/r146_shadow/taiex_daily.csv")
OUT=Path("output/shadow_feature_store")
FEATURES=["ret1","ret5","vol20","volume_z20","mkt_ret1","mkt_ret5","mkt_vol20"]

def sha256_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def main():
    if not IN_STOCK.exists() or not IN_MKT.exists():
        raise SystemExit("official PIT inputs missing")
    s=pd.read_csv(IN_STOCK)
    m=pd.read_csv(IN_MKT)
    for df in (s,m):
        df["date"]=pd.to_datetime(df["date"])
    m=m.sort_values("date").copy()
    m["mkt_ret1"]=m["close"].pct_change()
    m["mkt_ret5"]=m["close"].pct_change(5)
    m["mkt_vol20"]=np.log(m["close"]).diff().rolling(20).std()
    all_rows=[]
    coverage={}
    for sym,g in s.groupby("symbol"):
        g=g.sort_values("date").copy()
        g["ret1"]=g["close"].pct_change()
        g["ret5"]=g["close"].pct_change(5)
        g["vol20"]=np.log(g["close"]).diff().rolling(20).std()
        lv=np.log1p(g["volume"].replace(0,np.nan))
        g["volume_z20"]=(lv-lv.rolling(20).mean())/lv.rolling(20).std()
        g["target_ret1"]=g["close"].shift(-1)/g["close"]-1
        g["target_available_date"]=g["date"].shift(-1)
        g=g.merge(m[["date","mkt_ret1","mkt_ret5","mkt_vol20"]],on="date",how="left")
        g["cutoff_date"]=g["date"]
        g["symbol"]=sym
        g["missing_mask"]=g[FEATURES].isna().astype(int).astype(str).agg("".join,axis=1)
        usable=g.dropna(subset=FEATURES+["target_ret1"]).copy()
        coverage[str(sym)]={
            "raw_rows":int(len(g)),"usable_rows":int(len(usable)),
            "first":g["date"].min().date().isoformat(),"last":g["date"].max().date().isoformat(),
            "usable_first":usable["date"].min().date().isoformat() if len(usable) else None,
            "usable_last":usable["date"].max().date().isoformat() if len(usable) else None,
        }
        all_rows.append(g)
    x=pd.concat(all_rows,ignore_index=True).sort_values(["date","symbol"])
    cols=["date","symbol","name","cutoff_date","open","high","low","close","volume","amount"]+FEATURES+[
        "missing_mask","target_ret1","target_available_date","source","source_url","available_from"
    ]
    x=x[cols]
    OUT.mkdir(parents=True,exist_ok=True)
    matrix=OUT/"pit_matrix.csv"
    x.to_csv(matrix,index=False,encoding="utf-8-sig")
    manifest={
        "status":"PASS_SCHEMA_MATERIALIZED",
        "feature_version":"R147_PRICE_MARKET_CORE_v1",
        "features":FEATURES,
        "row_count":int(len(x)),
        "symbols":coverage,
        "stock_input_sha256":sha256_file(IN_STOCK),
        "market_input_sha256":sha256_file(IN_MKT),
        "matrix_sha256":sha256_file(matrix),
        "pit_rule":"all features from row date/cutoff or earlier; target isolated",
        "production":"NO_INTERACTION"
    }
    (OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False))
if __name__=="__main__": main()
