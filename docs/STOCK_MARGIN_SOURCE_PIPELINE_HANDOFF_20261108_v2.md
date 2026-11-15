# 存股作戰地圖｜融資研究管線修復／交接（2026-11-08 v2）

## 範圍與現在的結論

專案新增一個**獨立、手動、無正式寫入權限**的 TWSE `MI_MARGN` 融資研究擷取模組。
這不是將融資變數正式納入盤前預測權重，也不是修復正式排程的 PRESEALED Config 或收據。
金融市場風險判讀應把融資餘額變動與價格、量、外資現貨、期貨部位一起比較；融資沒有退乾淨並不保證股價必跌。

## 四項驗收

1. **來源與算式**：已知 2026-11-05、11-06 TWSE 官方信用交易統計數字在離線測試可完整對帳；融資金額變化分別為 -205.36796 億元及 -423.56407 億元，合計 -628.93203 億元；融資交易單位 11/05 當日結餘與 11/06 前日餘額差 10，依官方次日修訂解釋，不冒充數據錯誤。
2. **時點防洩漏**：必須記錄 `captured_at` 含時區，保守設定隔日起方可作為新預測資訊；不可把 11/08 才取得的來源代入 11/05 的盤前回測。
3. **失敗關閉**：檢驗官方回覆 `stat=OK`、日期、兩個融資欄名、買賣及現金償還恆等式；缺項、錯誤、重複、不整數、時區不明則退出且不產出宣稱可用的數據。
4. **隔離與交付**：獨立 GitHub `workflow_dispatch` 手動執行，原始官方 JSON 與研究成果皆作為短期 Actions artifact；`permissions: contents: read`，不碰正式 PRE/SET 98k prompt、模型權重、控制台 CURRENT/Registry、任何持股或交易。

## 關鍵證據（2026-11-08 實際只讀查核）

- 《台股盤前預判》既存平日 08:10 排程仍為 enabled，但 2026-11-06 指定 08:10、實際約 08:42:52 才開始，且輸出報告維持正式 HOLD。
- 《存股預判回填》既存平日 19:00 排程仍為 enabled，11/06 有 PARTIAL 報告，但 native receipt 未核。
- 控制台 `STOCK_Run_Config` 搜尋 `2026-11-06`／`2026-11-09` 為零行；`STOCK_Delivery_Receipt` 搜尋 `2026-11-06` 為零行；`STOCK_Research_Module_Registry` 搜尋 `MARGIN` 為零行。這是「正式鏈尚未接通」的證據，不可宣稱已修復。
- GitHub `colinfgl/stock-data-helper` 原來搜尋 `MI_MARGN`／`margin_balance`／`financing` 無程式，原有市場源閉環工作流程獨立於新增融資研究模組。

## 使用方法與治理

### 本地官方 JSON 核驗（保留原始來源）

```bash
python scripts/stock_margin_twse_ingest_20261108_v1.py \
  --date 2026-11-06 \
  --source-json path/to/original_official_twse.json \
  --captured-at 2026-11-08T09:00:00+08:00 \
  --archive-raw research_original.json \
  --out research_result.json
```

### Github Actions 手動取源

選 `stock-margin-research-manual-20261108`，輸入交易日 `YYYY-MM-DD`，由 GitHub runner 從 TWSE 官方 `MI_MARGN?selectType=MS&response=json` 取得一個日期、驗證，再以 Actions artifact 交付。若 HTTP、官方格式、驗證、TWSE 暫時未發布失敗，工作應顯示失敗，不應產生空白 PASS。這是**待 PR 合併後才能手動觸發**，目前不可宣稱自然排程已驗收。

## 已有來源與尚待來源

- 官方總量：[TWSE 信用交易統計](https://www.twse.com.tw/exchangeReport/MI_MARGN?date=&response=html)，官方說明明確強調「隔日公布的前日餘額」比前日「今日餘額」更終局。
- 個股：[TWSE 上市融資融券彙總](https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20260814&response=html&selectType=ALL)，尚未取得 11 月有完整時間戳的逐檔樣本。
- 上櫃：TPEx 融資融券資料，仍無可核對數值；缺完整 2018 以來歷史及實際來源取得時間。
- 正式交易日 `Natural 3/3`、20/60 天未來 OOS、baseline vs baseline+margin 之 D1 高低收、D5/D10 的增益評估，**尚未通過**。
- `融資追繳／斷頭戶數`、每戶維持率並非此公開來源揭露的資料，不能從餘額變化直接推論。

## 不採用高風險捷徑

不更動既存 PRESEALED Config、FINAL Registry、控制台正式狀態及本身未完成的 20/22 收據；不存在的預測值與原生 delivery ID 不得盤後補造。新 GitHub PR 必須由 CI/審核通過後，才考慮併入正式來源閉環，且這一步不等於可升級為正式模型權重。
