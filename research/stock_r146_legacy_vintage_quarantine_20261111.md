# R146 Historical Source Vintage Audit — 2026-11-11

## Decision

**QUARANTINE_AS_FORMAL_PIT / RESEARCH_ONLY.** The previously generated R146 archive may support retrospective price/volume research, but its `available_from` field must **not** be treated as an independently verified first-publication timestamp. No official model weight, official benchmark claim, or next-day prediction audit credit is authorized by this file.

## Observed legacy archive (GitHub main; inspected 2026-11-11)

| Artifact | Blob SHA at inspection | Evidence and disposition |
| --- | --- | --- |
| `output/r146_shadow/taiex_daily.csv` | `8fef306e2cda4f044aae12162f7f46172c9c5bc4` | First visible rows show `available_from=2024-01-02 14:00 Asia/Taipei` and same-day synthetic 14:00 for subsequent dates; historical release time unverified. Quarantine PIT claim. |
| `output/r146_shadow/stocks_daily.csv` | `3a6b9f10990334e589a568c6a9a4d2a6f9b76935` | First visible stock rows also show synthetic `14:00 Asia/Taipei`. Quarantine PIT claim. |
| `output/r146_shadow/coverage.json` | `a3cf59ba9caada63abede914480f52849fcd5b28` | `status=PASS` describes old raw coverage, not publication-time proof; `formal_weight=0`, `production_effect=NONE`. Do not promote as Formal/Natural/OOS. |
| `output/r146_shadow/manifest.sha256` | `9a01c437b0d897da1f7ff50afa5ef336ad4b0398` | Legacy artifact manifest; preservation, not a release-time certificate. |

The old output files remain in version control, intentionally unmodified, to retain the original evidence and avoid invalidating their manifest. This document records the quarantine explicitly; changing source code alone does not rewrite archived output. A later manual research-only backfill would create new artifacts with the source-release-time sentinel, but still would **not** establish actual historical source vintages.

## Correction implemented

- `scripts/fetch_r146_shadow_pit.py`: both market and stock rows now emit `available_from=UNVERIFIED_HISTORICAL_PUBLICATION_TIME`, require separately evidenced `first_seen_at` for any decision-time use, and keep `formal_weight=0`, `production_effect=NONE`.
- `.github/workflows/fetch-r146-shadow-pit.yml`: remains **manual `workflow_dispatch`**; renamed historic fetch/commit descriptions and runs a source-vintage regression test before any manual fetch.
- `tests/test_fetch_r146_shadow_vintage_20261111.py`: three focused tests ensure unchanged OHLCV and fail-closed temporal metadata; 18 tests passed together with the 15 preexisting factor-vintage tests on 2026-11-11.

## Practical use and remaining blocker

Past price dates can be used for shadow retrospective estimates with explicit ex-post caveat. Historical first-publication or first-seen vintages require independently timestamped raw captures, company-action adjustments, source version and trading cutoffs before the model may claim point-in-time correctness. The production 08:10/19:00 Scheduled Tasks, their delivery receipt, and PRESEALED Config must be verified separately; this code change is **not** a fix or acceptance of those platform gates. No model was retrained and no claimed forecasting accuracy increased by this correction.
