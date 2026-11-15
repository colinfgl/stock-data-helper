# stock-data-helper

Temporary helper repository for the 存股作戰地圖 project.

Purpose: prepare, validate, and store public Taiwan stock historical OHLC data used to complete the final three symbols (3665, 4916, 6770) before 20/20 QA and Walk-Forward testing.

## STOCK_SETTLEMENT native write: keep the report available

`scripts/stock_settlement_native_receipt_bridge_20261018.py` provides two
separate interfaces:

- `execute_same_run`: strict, original dual-table append/readback. Any missing
  owned lease, trusted run identity, genuine frozen report, schema, or live
  Sheets client fails closed.
- `execute_report_preserving`: an **optional adapter** for an already-authorized
  original 19:00 worker. It returns the **same original report bytes** on both
  successful readback and native-write HOLD. The worker must **separately render
  those bytes to ChatGPT**; this adapter does not send a ChatGPT message.

In a HOLD, the adapter reports `UNVERIFIED_POSSIBLE_PARTIAL` because the first
Google Sheet may have been appended before the second failed. Re-run the
strict writer under a newly verified owned lease, using the **same** frozen
run identity, to perform idempotent readback/resume; never manufacture missing
rows, a PRESEALED Config, or a formal/Natural PASS.

The repository's Actions tests use **fake clients and synthetic run identities**.
They do not install code into an existing ChatGPT Scheduled Task, grant that
task a real Sheets client/lease, prove platform delivery, or cure `0/0` native
receipts. A live cutover requires independent original-worker authentication,
verified scheduler context, live row readback, and a separate delivery receipt.
