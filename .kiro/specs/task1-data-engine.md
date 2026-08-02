# Task 1: Excel 資料解析、指標計算與資料血緣

> ⚠️ **本檔案已由三層規格取代，內容僅保留作為架構變更的對照。**
>
> 現行規格請見 [`task1-data-engine/`](./task1-data-engine/)：
>
> | 層級 | 文件 | 內容 |
> |---|---|---|
> | 需求層 | [requirements.md](./task1-data-engine/requirements.md) | 要滿足什麼：積木邊界條件、信心門檻、N/A 規則 |
> | 設計層 | [design.md](./task1-data-engine/design.md) | 怎麼做與為什麼：資料流、模組職責、關鍵決策 |
> | 任務層 | [tasks.md](./task1-data-engine/tasks.md) | 可逐一驗收的任務拆解與狀態 |
> | 歷程 | [development-log.md](./task1-data-engine/development-log.md) | 被實測推翻的假設與 15 項缺陷修正紀錄 |

---

## 為什麼架構變更

以下為**變更前**的規格，針對金管會信用卡統計資料設計。主辦方後續說明
**決賽現場提供 11 份旅遊業務 Excel、欄位結構事先未知**，並要求系統能吃
通用 Prompt 直接生成簡報、不要把指標寫死成 Python 函式。

原設計的根本問題是**一個業務指標一個寫死函式**——換領域全部要重寫，
且指標數量隨領域暴增。新架構改為「資料目錄 + 白名單通用積木 +
LLM Function Calling」，任何業務指標都是積木的組合結果，換領域不新增函式。

| | 舊架構 | 新架構 |
|---|---|---|
| 指標 | `compute_effective_card_rate()` 等專屬函式 | 10 個領域無關積木自由組合 |
| 欄位 | 寫死工作表名稱與欄位對應 | 動態建 Data Catalog |
| 期間 | 假設民國年月在欄名 | 兩種版面方向皆支援 |
| LLM | 未介入計算規劃 | Function Calling 組合積木，不碰數字 |
| 血緣 | `institution@period` 偽座標 | 真實 A1 儲存格範圍 |

---

## 以下為變更前的原始規格（僅供對照）

### 輸入
- 附件四_預期修正參照資料.xlsx
- 工作表: P.5預期修正_流通卡數, P.5預期修正_當月簽帳金額, P.7預期修正_流通卡數, P.7預期修正_當月簽帳金額

### 資料格式
- Row 0: header (金融機構名稱, 11401-11412)
- Rows 1-32: 各銀行
- Row 33: 總計
- P.7 工作表多一欄「市佔率」

### 標準化輸出格式
```
institution | period | metric | value | unit | source_file | source_sheet | source_cell
```

### 指標計算
- 有效卡率 = 有效卡數 / 流通卡數 * 100
- 市占率 = 機構值 / 總計 * 100
- MoM = (本期 - 前期) / 前期 * 100
- YoY = (本期 - 去年同期) / 去年同期 * 100（需有基期資料）
- 排名 = 程式排序（排除「總計」）

### 交付成果（舊架構，仍保留於 repo 供成員 D 的既有流程使用）
- [x] src/data_loader/excel_loader.py
- [x] src/data_loader/data_standardizer.py
- [x] src/calculation_engine/metrics.py
- [x] src/calculation_engine/data_lineage.py
- [x] src/validation/data_validator.py

### 舊架構驗收標準
- [x] 市場流通卡數 = 60,485,911 (6,049 萬張)
- [x] 台新市占率 = 11.0%
- [x] 排名: 中信 > 玉山 > 北富邦 > 國泰 > 台新
- [x] 無113年資料時 YoY = N/A

> 新架構在**不新增任何業務指標函式**的前提下，同樣涵蓋上述指標：
> 市占率 = `filter → group_sum → ratio`，YoY = `filter_by_period ×2 →
> group_sum → growth_rate`，排名 = `group_sum → rank_top_n`。
> 實測附件四可產出 20 個指標，占比落在 13.30%～17.85%。