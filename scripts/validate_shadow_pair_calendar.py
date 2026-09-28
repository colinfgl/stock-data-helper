#!/usr/bin/env python3
"""Fail closed unless baseline and neural shadow folds use identical calendars."""
from pathlib import Path
import json
import pandas as pd

BASE = Path("output/shadow_baseline/fold_metrics.csv")
NN = Path("output/shadow_nn/fold_metrics.csv")
OUT = Path("output/shadow_pair_calendar_receipt.json")
COLS = ["symbol", "fold", "train_start", "train_end", "val_start", "val_end", "test_start", "test_end"]

def norm(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"missing fold metrics: {path}")
    x = pd.read_csv(path, dtype={"symbol": str})
    missing = [c for c in COLS if c not in x.columns]
    if missing:
        raise SystemExit(f"{path}: missing columns {missing}")
    x = x[COLS].copy()
    x["symbol"] = x["symbol"].astype(str)
    x["fold"] = x["fold"].astype(int)
    return x.sort_values(["symbol", "fold"]).reset_index(drop=True)

def main():
    b = norm(BASE)
    n = norm(NN)
    bkeys = set(map(tuple, b[["symbol","fold"]].to_numpy()))
    nkeys = set(map(tuple, n[["symbol","fold"]].to_numpy()))
    only_b = sorted(bkeys - nkeys)
    only_n = sorted(nkeys - bkeys)

    merged = b.merge(n, on=["symbol","fold"], how="inner", suffixes=("_baseline","_nn"))
    date_cols = ["train_start","train_end","val_start","val_end","test_start","test_end"]
    mismatches = []
    for _, r in merged.iterrows():
        bad = {c: [r[f"{c}_baseline"], r[f"{c}_nn"]] for c in date_cols
               if r[f"{c}_baseline"] != r[f"{c}_nn"]}
        if bad:
            mismatches.append({"symbol": r["symbol"], "fold": int(r["fold"]), "dates": bad})

    status = "PASS_PAIR_CALENDAR" if not only_b and not only_n and not mismatches else "BLOCK_PAIR_DATE_MISMATCH"
    receipt = {
        "status": status,
        "baseline_rows": int(len(b)),
        "nn_rows": int(len(n)),
        "baseline_symbols": sorted(b["symbol"].unique().tolist()),
        "nn_symbols": sorted(n["symbol"].unique().tolist()),
        "only_baseline_keys": only_b,
        "only_nn_keys": only_n,
        "date_mismatch_count": len(mismatches),
        "date_mismatches": mismatches[:50],
        "production": "NO_INTERACTION",
        "auto_promotion": False,
    }
    OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    if status != "PASS_PAIR_CALENDAR":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
