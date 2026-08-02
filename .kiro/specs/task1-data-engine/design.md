# Task 1 設計層 — 架構、資料流與介面

> 對應需求見 [requirements.md](./requirements.md)。
> 設計層回答「怎麼做」與「為什麼這樣做」，實作細節見程式碼註解。

## D1. 核心分工

```
LLM          負責語意判斷與規劃「要算什麼」
白名單積木    負責確定性計算「怎麼算」
資料目錄      讓兩者在領域未知的情況下互相溝通
原生物件      負責呈現與可追溯
```

**為什麼不讓 LLM 直接生成 pandas 程式碼**：語法會對、業務定義會錯。
市占率分母誤抓成單一機構總和而非全市場總和時，Python 仍會忠實算出一個
「精確但錯誤」的數字，而且比純文字回答更容易被誤信為可靠。

## D2. 資料流

```
【Stage 1】一次性、離線、與 Prompt 無關

  多份 Excel/CSV
    → loaders          統一 .xlsx/.xls/.csv 的讀取介面
    → structure_detector  動態偵測標題/多層表頭/資料區，合併儲存格填平
    → normalizer          wide→long、年度正規化、異常值分類、版面轉置
    → fingerprint         Layer 0 runtime 結構指紋（同批次複用）
    → field_matcher       Layer 1 規則式語意比對
    → catalog             輸出 data_catalog.json
    → dataset             長表（記憶體，供積木運算）

【Stage 2】每次提問即時執行

  使用者 Prompt + data_catalog.json
    → llm_planner      ★ LLM 唯一出現的位置
    → MetricRecipe     配方：純指令，零數字
    → executor         白名單派發 + 欄位驗證 + 血緣追蹤
    → blocks           確定性運算，回原始 Excel 讀真實數值
    → sanity_check     失敗 → 回饋 LLM 重組（最多 2 次）
    → export           同源三輸出
```

## D3. 模組職責

| 模組 | 職責 | 關鍵設計 |
|---|---|---|
| `catalog_builder/loaders.py` | 統一輸入格式 | 以轉接器把 xlrd／csv 包成 openpyxl 介面，解析邏輯零改動 |
| `catalog_builder/structure_detector.py` | 標題／表頭／資料區偵測 | 唯一可靠訊號是「數值佔比」，不靠合併儲存格數量 |
| `catalog_builder/normalizer.py` | wide→long、正規化 | 期間靠**值**認不靠表頭認；支援兩種版面方向 |
| `catalog_builder/cell_tracker.py` | A1 座標追蹤 | melt 前綁定，避免血緣退化成偽座標 |
| `catalog_builder/fingerprint.py` | Layer 0 指紋 | **runtime 建立**，不預建樣板庫 |
| `catalog_builder/field_matcher.py` | Layer 1 語意比對 | 數值結構特徵優先於欄名字串 |
| `catalog_builder/catalog.py` | Catalog 組裝 | 一欄一張卡，不含列的數值 |
| `calculation_engine/blocks/` | 10 個白名單積木 | 純函式；`BLOCK_REGISTRY` 即白名單本身 |
| `calculation_engine/dataset.py` | 長表建置 | 與 catalog 走同一條解析路徑，避免兩邊對不上 |
| `calculation_engine/executor.py` | 配方執行 | 三道防線：積木白名單、欄位白名單、血緣 |
| `calculation_engine/llm_planner.py` | LLM 規劃 | Catalog 壓縮 + tool schema enum 約束 |
| `calculation_engine/recipe_factory.py` | 規則式配方 | LLM 範本 + 不可用時的後備 |
| `validation/sanity_check.py` | 合理性檢查 | N/A 列為 warning 不是 error |
| `export/` | 同源輸出 | 圖表值由 metric 查表，三方一致是結構必然 |

## D4. 關鍵設計決策

### D4.1 表頭偵測靠「數值佔比」

實測 11 份報表：表頭列數值佔比 **0.0**、資料列 **0.978**，中間沒有灰色地帶，
故門檻取 0.5 且不敏感（0.2～0.9 取值結果相同）。

**不能用合併儲存格數量推斷表頭層數**——表1-3 只有 1 個合併儲存格卻是 3 層表頭。

標題與分組表頭的區分靠「是否從第 1 欄開始橫跨整表」：標題從最左邊開始，
分組表頭一定讓出第 1 欄給維度欄。

### D4.2 期間辨識與版面方向

兩種版面都常見，只支援一種會讓另一種**靜默產出 0 筆**：

```
年度為列（旅遊）   年度 | 日本 | 韓國 …          期間在欄裡
期間為欄（財報）   金融機構名稱 | 11401 | 11402   期間在欄名上
```

- 前者：`detect_period_column` 靠**值**判斷哪一欄是期間（不能靠表頭——
  表2-2 的年度欄表頭寫的是「首站抵達地」）
- 後者：`detect_period_header_columns` 辨識期間代碼欄名，走轉置攤平

兩者產出的長表格式完全相同，因此積木、執行引擎、輸出層一行都不用改。

### D4.3 aggregation_role：防止明細與彙總混算

每個欄位標記 `detail` / `subtotal` / `total` / `residual`。

加總時排除 `subtotal` 與 `total`，**但保留 `residual`**——「其他」「未列明」
記的是真實數量，只是歸不進具名分類，本質是明細。

### D4.4 四層漏斗，逐層才升級成本

| 層級 | 方法 | 狀態 |
|---|---|---|
| Layer 0 | runtime 結構指紋（同批次相同結構複用） | 已實作 |
| Layer 1 | 規則式：數值結構特徵 + 單位關鍵字 + 字串相似度 | 已實作 |
| Layer 2 | Embedding 相似度 | 規格標「可選」，未實作 |
| Layer 3 | LLM 仲裁 → 降級為人工核對清單 | 以 `needs_manual_review` 實作 |

**Layer 0 改為 runtime 而非預建樣板庫**：決賽檔案開發期沒見過，
預建 mapping 命中率必然為 0。改成同批次內結構相同的工作表複用比對結果。

### D4.5 LLM 的三道防線

```
1. tool schema    block 欄位以 enum 鎖死 10 個積木名（結構上點不到別的）
2. 執行引擎        canonical 必須存在於 Catalog（擋下幻覺欄位）
3. Sanity Check   結果不合理 → 整批錯誤回饋 LLM 重新規劃，最多 2 次
```

重試以**整批**為單位而非逐一指標：一次失敗通常源自同一種誤解
（例如忘了指定 file），一起回饋讓 LLM 改一次就能全部修好。

### D4.6 Catalog 壓縮

完整 `data_catalog.json` 約 118 KB，每次提問全塞既慢又貴，且信心分數、
表頭列號、指紋對「決定要算什麼」毫無幫助。壓成一行一欄後約 12 KB
（約 3,000 tokens），只保留四項：

```
canonical | 單位 | aggregation_role | 來源檔案 | 2 個樣本值
```

樣本值刻意只給 2 個——給整欄等於讓 LLM 有機會直接抄數字。

### D4.7 同源輸出

**圖表值由 metric 查表產生，不另外計算**：一條折線就是 N 個 metric 的值。
「三方一致」因此是結構上的必然，不是靠事後比對維持。

所有序列化路徑共用單一取值入口 `serialize_value()`，統一保留 10 位小數
——Excel 只保存 15 位有效數字而 Python float 有 17 位，不統一會讓
JSON 與 Excel 對不起來。

## D5. 資料契約

### D5.1 長表 schema（normalizer → blocks）

```
period | canonical | dimension | value | file | sheet | row | col | aggregation_role
```

`canonical` 供 LLM 指定參數，`dimension` 保留原始表頭供人核對；
`row`／`col` 是血緣的根，melt 後仍能回答「這個數字來自哪一格」。

### D5.2 MetricRecipe（LLM → executor）

```json
{
  "metric_id": "...", "metric_name": "...", "unit": "...", "period": "...",
  "is_share": false,
  "assumption_statement": "對業務定義的理解，必填",
  "steps": [{"id": "...", "block": "...", "input": "...", "params": {...}}],
  "output": "最終取哪一步"
}
```

步驟間引用以 `{"$ref": "步驟id"}` 表示。**配方中不含任何計算結果。**

### D5.3 對外輸出

`metric` 與 `chart_data` 的 schema 見 `Task1/TASK1.md` 第 5 節。
`data_lineage.json` 的外層結構沿用既有格式（`generated_at` /
`total_records` / `records` 以 metric_id 為鍵），使成員 D 的
`PPTReconciler` 不必改程式；差異在 `sources` 補上真實 A1 座標。

## D6. 與其他成員的介接

| 成員 | 介接方式 | 需改動 |
|---|---|---|
| B | `analysis_result.json["data_summary"]` 鍵名沿用其既有簽名 | 無 |
| C | `load_chart_series()` 回傳 `categories` + `series_data` | 一行 import |
| D | `load_lineage_tracker()` 回傳 `DataLineageTracker` 物件 | 一行 import |

轉接函式一律放在 `src/export/`，不修改其他成員正在編輯的檔案。

## D7. 已知限制

1. **月度資料併入年度**：轉置版面的 `11401`～`11412` 全歸 2025，
   `group_sum` 得到年度合計。對流量型指標正確，對存量型指標需由 LLM 的
   假設聲明處理。系統會留下警告。
2. **Layer 2 Embedding 未實作**：規格標示為可選項。
3. **`.ods` / `.xlsb` 不支援**：會明確列入警告而非靜默略過。
4. **Top-N 需兩階段**：LLM 無法在計算前知道排名，單次規劃只能多算候選。