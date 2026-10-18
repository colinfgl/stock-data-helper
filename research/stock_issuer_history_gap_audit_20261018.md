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


## 2026-10-18 精確例外核驗（再次直接回讀封存原列）
即使數值差極小，原封存 FormalEligible 均為 NO、PITCredit=0；禁止依本診斷擅自翻案。
| 事件鍵 | 差額或一致性 | 留置原因 |
| --- | --- | --- |
| 3665|2025-07-17|splits | +0.0000000074 | 比率近似，無合格完整PIT調整價 |
| 5222|2026-08-20|splits | +0.000000059 | 比率近似，無合格完整PIT調整價 |
| 6669|2026-09-02|splits | +0.00000010（封存顯示容差0.0000001） | 邊界精度不能自動當正式PASS |
| 6831|2024-08-16|dividends | 0.7787=0.77870000 | 原始事件日期與調整價鏈仍需補證 |
| 6831|2025-06-12|dividends | 1.25=1.25000000 | 同上 |
| 6831|2024-08-16|splits | 1.05489=1.05489000 | 同上 |

2025-08-01 的 4585達明機器人、6831邁科記錄為 PRELISTING_MEAN_NOT_CLOSE，非正式股價，禁止使用研究均值代替官方OHLC。
本輪所有六筆狀態保持原始研究表之 FormalEligible=NO/PITCredit=0；本次未觸碰正式工作簿或排程。


## 2026-10-18 12:44｜10/16研究D1模型逐股實績重新計算（與上列公司行動研究獨立）
來源：R33研究封存 `20261017_1016_68檔官方實績研究誤差!A8:U75`，68筆，官方當日收盤、事前研究Point、研究前收錨點。
以同一標的前收錨點當分母：研究Point MAE=**2.1472823%**；前收持平 MAE=**2.1464728%**；模型落後=**0.0008096百分點**。不是正式OOS。
模型相對持平基準誤差增量（pp，正數更差）：3363上詮+0.3889；2059川湖+0.2690；3653健策+0.2441；3443創意+0.2347；3711日月光投控+0.2159。這是事後誤差診斷，不能據此直接事前剔除五檔。
改善最多（負數較佳）：2466冠西電-1.3094；8046南電-0.3400；3189景碩-0.2975。亦不得利用事後勝負挑模型。
結論：同一交易日68檔，原模型沒有超越持平；不調整正式權重，維持Research-only。正式績效仍須具備上市日/PIT/價格基準一致、事前封存、有效Config、真實同Run收據。

## 2026-10-18 17:00｜兩筆事件日期與配股率補證（不升格正式調整價）

1. 6669 緯穎，公司官網股東服務頁面 https://www.wiwynn.com/zh/investors/shareholders-services 列出2026-09-02除權、2026-09-08除權基準日，以及每股股票股利19.8279460元。研究表股票股利因子2.98279460可由1+19.8279460/10重現。此處**原始發行人網站確認的是事件日期與配股率**，不保證歷史逐日PIT adjusted close。
2. 5222 全訊，2026-08-05公開資訊觀測站公告的新聞轉載 https://m.moneydj.com/f1a.aspx?a=03ED5ED3-1996-4366-AAD1-E0064587FA86 載明2026-08-20除權，調整後每股股票股利0.99966641元，理論因子1.099966641；與研究表1.099966641數字相同。公開資訊觀測站原件bytes尚未在本輪取得，列為「公告轉載交叉核對」，不可聲稱原件已封存。

上述只降低 **event date/rate source uncertainty**，不解除 issuer historical original-adjusted price raw / PIT as-of / venue basis Gate。兩筆原正式FormalEligible=NO、PITCredit=0保持不變。不是模型提權、不是10/19預測、不是Natural收據。
