# 存股作戰地圖：公司行動與歷史價格基準證據清單（2026-10-18）

狀態：RESEARCH_SOURCE_IDENTIFIED / RAW_SERIES_NOT_YET_VERIFIED；不得宣稱 68 檔全部補齊，亦不得做正式 OOS/Natural 加分。

## 已核實官方來源
- 臺灣證交所：除權除息資訊（2005-02-04起，普通股除權息、減資及增資等欄位）：https://eshop.twse.com.tw/zh/product/detail/c96acc4e31d442eab373414c9f134844
- 臺灣證交所：除權息及上下市資訊檔（2019-12-23起，前日收盤、除權參考價、權值/息值）：https://eshop.twse.com.tw/zh/product/detail/000000006e0bbe8d016f182105d90328
- 臺灣證交所：除權除息計算結果資料檔（2020-03-02起，除權息日期、前收及參考價）：https://eshop.twse.com.tw/zh/product/detail/000000006f6a5e3401702cea7ba20041

## 逐標的逐交易日必需證據
Symbol + Venue + HistoricalTradeDate + RawClose + CloseSourceURL + RawBytesSHA256 + CorporateActionDate + ActionType + DividendOrRatio + CorporateActionOriginalBytesSHA256 + AdjustmentMethod + AdjustmentBasis + AdjustedCloseOriginalBytesSHA256 + PITAvailableAt + CheckResult。

- 以上來源為官方資料目錄/商品規格，**非已購得完整商品原件**。須核對授權與資料供應途徑，不能繞過付費。
- 官方除權參考價不是第三方歷史調整收盤價；前收與基準調整需以可重現公式和同一條原始資料串核算。
- 交易所上市股票與櫃買股票、ETF需按各自規則區分；不得把TWSE的規格直接套到TPEx及ETF。
- 若原始逐日 adjusted-close 或公司行動原件缺，ResearchStatus=HOLD_SOURCE_EVIDENCE_INCOMPLETE，formal error=N/A；可並列原始數值和未校準差額。
- 不得事後補造原本不存在的事前預測、價格原始SHA、封存Config或自然樣本。

研究來源截至：2026-10-18 Asia/Taipei。正式主檔、V16、現有 Prediction/Outcome 與正式19:00排程均未因此改動。
