#!/usr/bin/env python3
"""R147 simple shadow baselines: multinomial logistic + Ridge.

Consumes only the canonical PIT feature-store matrix.
Strict time split, no shuffle, train-only scaling and label calibration.
The fold calendar is intentionally aligned to the neural challenger's 60-day
sequence endpoint calendar so paired comparisons use identical symbol/date folds.
Shadow only: never writes Production weights/trades/cash.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error
from sklearn.preprocessing import StandardScaler

SEED = 20260928
LOOKBACK = 60
TRAIN = 504
VAL = 126
PURGE = 10
TEST = 20
STEP = 20
EPS = 1e-12
IN_MATRIX = Path("output/shadow_feature_store/pit_matrix.csv")
OUT = Path("output/shadow_baseline")
FEATURES = ["ret1", "ret5", "vol20", "volume_z20", "mkt_ret1", "mkt_ret5", "mkt_vol20"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def q333(x) -> float:
    return float(np.quantile(np.asarray(x, dtype=float), 1 / 3))


def labels(ret, sigma, k):
    thr = k * sigma
    return np.where(ret > thr, "UP", np.where(ret < -thr, "DOWN", "SIDE"))


def brier_multiclass(y_true, probs, classes) -> float:
    y = np.zeros_like(probs)
    pos = {c: i for i, c in enumerate(classes)}
    for i, c in enumerate(y_true):
        y[i, pos[c]] = 1
    return float(np.mean(np.sum((probs - y) ** 2, axis=1)))


def prep():
    if not IN_MATRIX.exists():
        raise SystemExit("canonical PIT feature store missing")
    x = pd.read_csv(IN_MATRIX)
    x["date"] = pd.to_datetime(x["date"])
    x = x.dropna(subset=FEATURES + ["target_ret1", "vol20"]).sort_values(["symbol", "date"])
    x = x.rename(columns={"target_ret1": "fwd_ret1"})
    return x


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = prep()
    folds = []
    receipts = []

    for sym, g in data.groupby("symbol"):
        g = g.reset_index(drop=True)

        # Calendar parity contract:
        # train_tcn_mlp_shadow.py emits one sample for each 60-day sequence
        # endpoint, so its first eligible endpoint is raw row LOOKBACK-1.
        # The tabular baseline uses only the endpoint features, but must start
        # from the same endpoint calendar. This also makes short-history symbols
        # ineligible in both challengers under the same fold rule.
        if len(g) < LOOKBACK:
            continue
        g = g.iloc[LOOKBACK - 1 :].reset_index(drop=True)

        start = 0
        fold_no = 0

        while start + TRAIN + VAL + PURGE + TEST <= len(g):
            tr = g.iloc[start : start + TRAIN].copy()
            va = g.iloc[start + TRAIN : start + TRAIN + VAL].copy()
            te = g.iloc[
                start + TRAIN + VAL + PURGE : start + TRAIN + VAL + PURGE + TEST
            ].copy()

            k = q333(np.abs(tr["fwd_ret1"] / tr["vol20"]))
            ytr = labels(tr["fwd_ret1"].values, tr["vol20"].values, k)
            yte = labels(te["fwd_ret1"].values, te["vol20"].values, k)

            if len(set(ytr)) < 3:
                start += STEP
                continue

            scaler = StandardScaler().fit(tr[FEATURES])
            xtr = scaler.transform(tr[FEATURES])
            xte = scaler.transform(te[FEATURES])

            clf = LogisticRegression(
                solver="lbfgs",
                max_iter=2000,
                random_state=SEED,
            )
            clf.fit(xtr, ytr)

            ridge = Ridge(alpha=20.0)
            ridge.fit(xtr, tr["fwd_ret1"].values)

            p = clf.predict_proba(xte)
            pred = clf.classes_[np.argmax(p, axis=1)]
            rhat = ridge.predict(xte)

            fold = {
                "symbol": str(sym),
                "fold": fold_no,
                "train_start": tr["date"].iloc[0].date().isoformat(),
                "train_end": tr["date"].iloc[-1].date().isoformat(),
                "val_start": va["date"].iloc[0].date().isoformat(),
                "val_end": va["date"].iloc[-1].date().isoformat(),
                "test_start": te["date"].iloc[0].date().isoformat(),
                "test_end": te["date"].iloc[-1].date().isoformat(),
                "k_train_q333": k,
                "direction_accuracy": float(accuracy_score(yte, pred)),
                "brier": brier_multiclass(yte, p, clf.classes_),
                "log_loss": float(log_loss(yte, np.clip(p, EPS, 1 - EPS), labels=clf.classes_)),
                "mae_return": float(mean_absolute_error(te["fwd_ret1"], rhat)),
                "test_n": len(te),
                "seed": SEED,
            }
            folds.append(fold)
            receipts.append(
                {
                    "symbol": str(sym),
                    "fold": fold_no,
                    "classes": clf.classes_.tolist(),
                    "features": FEATURES,
                    "logistic_coef": clf.coef_.tolist(),
                    "logistic_intercept": clf.intercept_.tolist(),
                    "ridge_coef": ridge.coef_.tolist(),
                    "ridge_intercept": float(ridge.intercept_),
                    "scaler_mean": scaler.mean_.tolist(),
                    "scaler_scale": scaler.scale_.tolist(),
                }
            )
            fold_no += 1
            start += STEP

    if not folds:
        raise RuntimeError("no eligible walk-forward folds; coverage still insufficient")

    df = pd.DataFrame(folds)
    df.to_csv(OUT / "fold_metrics.csv", index=False, encoding="utf-8-sig")
    (OUT / "model_receipts.json").write_text(
        json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = {
        "status": "PASS_SHADOW_BASELINE",
        "seed": SEED,
        "lookback_calendar_alignment": LOOKBACK,
        "calendar_contract": "MATCH_TCN_SEQUENCE_ENDPOINTS",
        "split": {
            "train": TRAIN,
            "validation": VAL,
            "purge": PURGE,
            "test": TEST,
            "step": STEP,
            "shuffle": False,
        },
        "features": FEATURES,
        "folds": len(folds),
        "symbols": sorted(df.symbol.astype(str).unique().tolist()),
        "mean_direction_accuracy": float(df.direction_accuracy.mean()),
        "mean_brier": float(df.brier.mean()),
        "mean_log_loss": float(df.log_loss.mean()),
        "mean_mae_return": float(df.mae_return.mean()),
        "feature_store_sha256": sha256_file(IN_MATRIX),
        "production": "NO_INTERACTION",
        "auto_promotion": False,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
