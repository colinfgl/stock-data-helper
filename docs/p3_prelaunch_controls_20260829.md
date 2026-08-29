# 存股作戰地圖 P3 Prelaunch Controls — 2026-08-29

Status: **METHOD / ENGINEERING READY; WAITING FOR 2026-09 MONTH-END DATA**.

## Frozen production model
- Fundamental 30%
- Industry 20%
- Chip / flow 15%
- Valuation 15%
- Technical 10%
- Macro 10% remains research/risk context only; it does not mechanically allocate a sleeve.

## EPS v1 guardrail
Use `scripts/eps_growth_gate_v1.py`.

`robust_growth = (current - prior) / (abs(current) + abs(prior))`

The transform is bounded in [-1, 1], keeps positive-to-positive rank ordering monotonic with ordinary YoY, and fixes negative-base / cross-zero direction errors. Small-base is QA-only and does not alter score weights.

Historical audit before P3: 498 same-quarter YoY comparisons across the 17 operating-company names in the core20; 40 non-normal-base cases; 23 cases where traditional YoY gives the opposite economic direction; 10 small-base QA flags.

## Forward survivorship control
The initial P3 core20 universe is frozen for the first formal snapshot. Future additions/removals take effect only from the next formal snapshot and are never backfilled into prior snapshots. Delisting/untradeable exits are recorded using the last tradable price and a forced-outcome event.

Historical walk-forward results remain labelled as fixed-current-universe / survivor-cohort research and are not represented as unbiased full-market alpha evidence.

## Forward industry-map control
The industry proxy map is effective-dated from 2026-08-29. Future changes create a new effective-dated record; old snapshots are never rewritten. Historical R48 classification backcast bias remains disclosed as a historical limitation only.

## Macro V2 Shadow
Pre-registered features: VIX, SOX, NASDAQ, USD/TWD, US 10Y-2Y curve, TWSE breadth. These remain shadow-only during P3 and cannot change production weights. No governance review before at least 12 monthly shadow observations or 4 quarterly snapshots, and no repeated tuning on the same P3 sample.

## P3 logging / scoring
- Prediction records are append-only and frozen.
- Outcome records are appended at 1D / 5D / 20D / 60D / 120D.
- Benchmarks: core20 equal-weight, 0050, and actual portfolio as decision-relevance reference.
- Metrics: Direction Accuracy, Brier Score, Rank IC, Top5 positive-return rate, excess return, CAGR, MDD, Sharpe, turnover, and fee/tax-adjusted performance.

## Formal start
Do not create the first official P3 Forward Snapshot until 2026-09 month-end data are complete. R54/R55/R56 are pre-P3 / method-engineering records and must not be re-labelled as formal forward samples.
