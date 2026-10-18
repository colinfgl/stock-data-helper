# STOCK_SETTLEMENT successor contract candidate — 2026-10-18
Status: RESEARCH_STAGED_HOLD_NOT_DEPLOYED
Target: existing TaskID `6a825a73808c81918c5c7b5d1fecaf28`, weekdays 19:00 Asia/Taipei, exact_schedule, enabled=true, notifications=true, email=true. No extra scheduled task.

## Evidence hierarchy
1. Active immutable bootstrap: hash `e5757022a47334e1364081f387e7a043b76ab033b451cce0ac348b9cbd37ea90`, preserved unchanged after `---BOOTSTRAP_BODY---`. Historical v16 source is explicitly NOT the active bootstrap: `research/stock_settlement_v16_historical_body_source_20261018.md`.
2. Existing governance: V16 active, V17 candidate STAGED_NOT_ACTIVE, unique same-day PRESEALED Config only; no 2026-10-19 valid config is presumed.
3. Verified native terminalizer: commit `b157cab3df069bfbce897c629d40497a27d0d531`, file `scripts/stock_delivery_terminalizer_v11_20261014.py`, SHA256 `9b7b4eaf9233730869643f17767bf0df6017466e826026c336deec662376ba89`.
4. Native receipt writer: `scripts/stock_receipt_native_writer_v1_20261018.py`, verified as source in repository; executable SHA and real same-run execution still require live verification. Git blob SHA is NOT content SHA256.
5. Existing v11 supplemental original was overwritten on 2026-10-18 and cannot be represented as exact recovered bytes. This document is an independently authored successor draft and must never masquerade as restored v11.

## Required existing-run settlement steps
0. Resolve unique active authority from CURRENT -> TODO -> Active Authority Index -> target date Config -> active Bundle -> policies -> sealed predictions. Confirm current TaskID, current exchange business date, exact cutoff, prestart durable receipt; do not use archived histories as current.
1. Check original same-day valid PRESEALED Config and true schedule trigger. Config absent => FORMAL/NATURAL/OOS BLOCK for affected run only. Continue research and complete user-visible report, with legitimate values only.
2. Read ALL due D1-D10 sealed PredictionKeys independently; retain full cohort denominator, quarantine malformed siblings only, append-only outcomes with conflict-hold. Never manufacture a missing sealed forecast or force same-symbol de-duplication.
3. Fetch original TWSE/TPEx official exact-date raw prices. Validate venue/symbol/date, source raw bytes SHA, corporate-action basis and cross-venue conflicts. Missing originals => affected source HOLD, not synthetic actual.
4. Recompute permitted error and secondary baselines with HORIZON-METRIC-v2, Decimal material direction ±0.5%, Winkler60; preserve absent ComparisonEligible as MISSING. Read formal performance 28 canonical columns A:AB; AC:AF are optional separate extensions. Run mandatory performance_write_contract_v9 before native write and after readback; any mismatch => PERFORMANCE_READBACK_HOLD.
5. Print full Traditional Chinese settlement report 0–9 IN CHAT, including original sealed stocks and TAIEX CLOSE/HIGH/LOW predictions against independent official actuals, error status, stock names, current position, missing data, source cutoff, governance and actions. If official data missing, print available sections and explicit per-key HOLD rather than blank sections.
6. Freeze actual complete report bytes and ReportSHA. RUN -> REPORT -> SAVE -> READBACK -> MESSAGE are distinct. Missing platform message reference/timestamp => UNVERIFIED_NONBLOCKING; never hide report.
7. Only after real same-run RunID, TaskID, exact frozen report SHA, durable SAVE/readback, authenticated terminalizer original bytes, native client, writer lease, and live exact 20-column STOCK_Delivery_Receipt + 22-column STOCK_Delivery_Observability headers are verified, run terminalizer followed by eligible native writer `receipt_plan`, `plan_actions`, `write_native_receipts` and exact same-run dual readbacks. If unavailable mark NATIVE_WRITE_NOT_EXECUTED_HOLD; do NOT write sham receipt.
8. Only a real NORMAL_SCHEDULE eligible earlier premarket and same-day settlement complete chain may credit Natural; manual/replay/research credit 0. Natural 3/3 must be truly earned, 20-day observe and 60-day formal governance not backfilled.
9. End with user-visible five-line simple conclusion format (Engineering/Data, Next, Evidence/Sample, Delivery/Trigger, Remaining category) while preserving the full 0–9 report.

## Next-run config / successor governance
- Next actual target date must be independently checked against official TWSE calendar. Before any formal forecast, ensure unique future PRESEALED Config created *before* cutoff with true CFG-HASH-v2, live Bundle SHA, current active task bootstrap and schedule seal readback. Any missing gate blocks Formal only; no retrospective fabrication.
- V17 candidate has 30/30 components; this does not make it active. Governance successor cutover requires genuine same-run terminal settlement receipt, fresh full rollback snapshot of both existing stock tasks with settings, separate exclusive cutover and Config leases, active authority switch, native readbacks and cross-surface reconciliation.
- Before changing *any* existing task: fresh full live snapshot, independently archived complete original, exact protected bootstrap and settings hashes, successful guard/CI, controlled authorization, update same TaskID only, and post-update full readback. Inability to obtain v11 original means a new governed generation must be reviewed explicitly, not described as exact restoration.

## Admission gate
Current candidate STATUS = HOLD_UNDEPLOYABLE. Absent complete current live prompt bytes, independent original v11 snapshot, original native code SHA/readback, and fresh governance cutover controls, the actual 19:00 task MUST NOT be overwritten. Research-only document cannot create Config, actual, Natural, OOS or delivered claims.
