# Task 1 任務層 — 拆解與驗收狀態

> 對應 [requirements.md](./requirements.md) 與 [design.md](./design.md)。
> 每個任務都可獨立驗收，避免一次性生成整包難除錯的程式碼。

## 進度總覽

| Step | 任務 | 狀態 | 交付 |
|---|---|---|---|
| 0 | 版控隔離與環境整備 | ✅ | 分支、`.gitignore`、`.pyc` 移出版控 |
| 1 | 結構偵察（唯讀） | ✅ | `Task1/recon/` |
| 2 | 解析層 | ✅ | `src/catalog_builder/` 三支 |
| 3 | 欄位比對與 Catalog | ✅ | `data_catalog.json` |
| 4 | 白名單積木與測試 | ✅ | `src/calculation_engine/blocks/` |
| 5 | 執行引擎與 LLM | ✅ | `executor.py`、`llm_planner.py` |
| 6 | 同源輸出 | ✅ | `src/export/` |
| 7 | 端到端驗證與路徑切換 | ✅ | `outputs/` |
| 8 | 格式與版面擴充 | ✅ | `.xls`／`.csv`／轉置版面 |

**測試**：91 個單元測試全數通過。

---

## Step 0. 版控隔離與環境整備

- [x] 開 `feature/task1-catalog` 分支，`main` 全程不動
- [x] 合併 `.gitignore`（排除測試 Excel、`.env.*`、開發期輸出）
- [x] 將 19 個 `__pycache__/*.pyc` 移出版控

**為什麼**：四人直推 `main`，且 `.pyc` 曾造成實際的 merge 衝突
（`origin/main` 有 commit `618c1d6 merge: resolve pyc conflict` 為證）。

---

## Step 1. 結構偵察（唯讀）

- [x] `Task1/recon/scan_structure.py`：掃描 11 份檔案的結構特徵
- [x] 產出 `structure_report.md` 與 `raw_scan.json`

**驗收**：不修改任何 Excel、不寫入 `outputs/`。

**目的不是「認識這 11 份檔案」，而是測量結構變異範圍**，用以校準偵測門檻
——規格書原本寫的「數值佔比 > 50%」只是假設，沒有真實資料支撐。

---

## Step 2. 解析層

- [x] `structure_detector.py`：動態偵測標題／多層表頭／資料區
- [x] `normalizer.py`：wide→long、年度正規化、異常值分類
- [x] `cell_tracker.py`：A1 座標追蹤

**驗收**
- [x] 11/11 檔案的資料起始列偵測正確
- [x] 年度正規化 11/11 測試案例通過（含 `53年1964`、`66 年 1977`）
- [x] 抽查 表1-3 日本 1964 = 22,733 @ `C5`，與原檔逐格一致

---

## Step 3. 欄位比對與 Data Catalog

- [x] `fingerprint.py`：Layer 0 runtime 結構指紋
- [x] `field_matcher.py`：Layer 1 規則式比對、`aggregation_role` 判定
- [x] `catalog.py`：組裝 Catalog JSON
- [x] 0.85／0.6 兩道信心門檻與降級策略

**驗收**
- [x] 11 份 → 193 個欄位卡、8 組跨檔合併、1 個關聯鍵
- [x] 待人工覆核 2 筆，且均為真實問題（殘差欄含負數）
- [x] 東南亞群組正確分出 6 明細 + 1 殘差 + 1 小計

---

## Step 4. 白名單積木與單元測試

- [x] 10 個純函式積木
- [x] 邊界條件：分母 0、缺基期、NaN、明細與彙總混算
- [x] `BLOCK_REGISTRY` 作為白名單本體

**驗收**
- [x] 31 個積木測試通過
- [x] 明細加總 = 官方總計欄，6 個年度逐格相符
- [x] 積木為純函式：同輸入同輸出、不修改輸入資料

---

## Step 5. 執行引擎、Sanity Check 與 LLM

- [x] `executor.py`：白名單派發、欄位驗證、血緣蒐集
- [x] `sanity_check.py`：比率範圍、分母、NaN／Inf、加總對帳、跨檔重複
- [x] `execute_with_retry`：失敗回饋 LLM，最多 2 次
- [x] `llm_planner.py`：Catalog 壓縮、tool schema、Function Calling
- [x] `recipe_factory.py`：規則式後備

**驗收**
- [x] 假積木 `exec_sql` 被擋下
- [x] 幻覺欄位「來臺旅客_瓦干達」被擋下
- [x] 真實 Bedrock 呼叫成功，重試機制實戰生效
      （第 1 次 13 個配方 6 個失敗 → 第 2 次全部通過）
- [x] LLM 產出的數值逐格核對相符（7/7）
- [x] 憑證失效時正確落回規則式後備，仍產出可追溯數字

---

## Step 6. 同源輸出

- [x] `AnalysisResult`：唯一計算結果物件
- [x] 三種序列化：`analysis_result.json` / `.xlsx` / `data_lineage.json`
- [x] `serialize_value()` 統一精度入口
- [x] B／C／D 的相容層（`load_metrics` / `load_chart_series` /
      `load_lineage_tracker`）

**驗收**
- [x] 四方一致性以**嚴格相等**比對全數通過
- [x] 以三位成員的真實程式碼實測介接成功

---

## Step 7. 端到端驗證與路徑切換

- [x] 輸出路徑由開發期的 `outputs/v2/` 切換至正式的 `outputs/`
- [x] 正式路徑下重新驗證四方一致性
- [x] `Task1/samples/` 提供交付範例與串接說明

---

## Step 8. 格式與版面擴充

- [x] `loaders.py`：`.xlsx` / `.xlsm` / `.xls` / `.csv`
- [x] 不支援格式明確列入警告，不靜默略過
- [x] 期間代碼欄名辨識（民國年月／西元年月）
- [x] 轉置版面（期間為欄）攤平

**驗收**
- [x] 信用卡資料（附件四）由 0 筆 → 396 筆長表記錄
- [x] 旅遊資料回歸無退化
- [x] 13 個格式測試通過

---

## 驗收標準對照

| 需求 | 狀態 | 證據 |
|---|---|---|
| 11 份可一次上傳並完成 Catalog | ✅ | 193 欄位卡 |
| 抽查數值與原始 Excel 一致 | ✅ | 多次隨機抽樣逐格核對 |
| 可回查來源／積木鏈／假設聲明 | ✅ | `data_lineage.json` |
| 缺基期輸出 N/A 附原因 | ✅ | 3 筆 N/A 均有具體原因 |
| 同 Prompt 重跑一致 | ✅ | 純函式 + temperature 0 |
| **同時覆蓋信用卡與旅遊資料** | ✅ | Step 8 驗證 |
| Sanity Check 攔截並重試 | ✅ | 實戰觸發並修正 |
| 三方數值一致 | ✅ | 嚴格相等比對 0 不一致 |
| 多層表頭／寬表／民國年 | ✅ | 11/11 正確 |
| 信心不足依降級策略 | ✅ | 2 筆進入 needs_manual_review |
| 單元測試確保不變質 | ✅ | 91 個測試 |

---

## 跨模組待辦（需與其他成員確認，非本模組可單方面決定）

| # | 事項 | 對象 |
|---|---|---|
| 1 | `outputs/` 寫入衝突：`pipeline.py` 與 `run_task1.py` 檔名相同會互相覆蓋 | D |
| 2 | `ppt_reconciler._check_chart_data` 讀 `series[i].metric_ids`，但 slide_spec 為 `series_metric_ids`，圖表校驗實際在空轉 | B、D |
| 3 | `user_prompt_path` 在 `pipeline.py` 只宣告未讀取，使用者 Prompt 未進入計算 | D |