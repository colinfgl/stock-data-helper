# 存股作戰地圖｜2026-10-18 11:19 台北時間｜歷史價格與公司行動正式來源封存複核

本紀錄直接重讀 **2026-10-17既有控制台研究封存** (ID 1Du6cqfDP9_hADcLWlErB7MkmCiyNTLujb4_O0MOVZRI)，不重算正式預測、不改歷史原件、不得冒充新官方資料。

## 逐列實際計數
- STOCK_HistoryGap_20261017，共 **64資料列**（標題不計）：**62** 筆 `OFFICIAL_CLOSE_RECOVERED_ADJUSTED_STILL_MISSING`、**2** 筆 `PRELISTING_MEAN_NOT_CLOSE`。研究估計上下界不能替代提供者原始調整收盤。
- STOCK_IssuerFinal_20261017，共 **28資料列**（標題不計）：
  - **7** `NO_EXACT_ISSUER_DATE_MATCH`：發行人相同日期無法精確匹配。
  - **14** `ISSUER_CONFIRMS_CASH_VENDOR_DIFFERENCE_OPEN`：發行人資料證實某些事件，但提供者差異仍未釐清。
  - **1** `ISSUER_EARNINGS_COMPONENT_MATCH_TOTAL_DIFFERS_RESEARCH`。
  - **4** `ISSUER_SPLIT_RATIO_MATCH_RESEARCH`。
  - **2** `ISSUER_CASH_MATCH_RESEARCH`。
- STOCK_IssuerCash_FactorQA_20261017 已標示15筆差異股息事件的研究因素診斷，正式核可仍為0；不可把「發行人比率相符」等同歷史PIT調整價核可。

## 實際判定
- 對上述 **62筆**，可保留官方原始收盤價與研究區間，但是 `AdjustmentBasis=HOLD_ORIGINAL_ADJUSTED_CLOSE_MISSING`，FormalEligible=NO。
- 對 **2筆** 上市前區段，正式OHLC仍不存在：`HOLD_PRELISTING_NOT_TRADABLE`，不得補值。
- **28筆事件**的各個狀態保留不變，絕不能單靠事件狀態推定68標的每一歷史日都具有合格價格基準。
- Cash7私有券商原件、正式19:00 Worker同次RUN收據、10/19事前Config、Natural與OOS均不在本研究記錄中生成。

## 後續真正有效之原始證據
每一筆欲升級時，需要 Symbol、date、venue、可驗證的原始調整收盤完整bytes/SHA、發行人事件正確日期/種類及其raw SHA、商業授權、事前PIT可得時間；經獨立相同基準驗證才可考慮正式調整價。此為已確認的缺證據分類，不是已完成的核准。

本輪沒有更動正式控制台、封存工作簿、Prediction/Outcome、既有排程 Prompt。
