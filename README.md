# 2026_AWS_Contest
Just for 2026/08/01 ~ 2026/08/02 Contest 
# LLM 驅動之 Excel 報表轉簡報自動化系統

> 競賽專案：讀取**決賽現場提供之多份 Excel 資料**（依主辦方最新公告，決賽將提供 **11 份旅遊業務相關 Excel 檔案**，欄位結構與業務指標事先未知），依系統提示詞／使用者通用 Prompt 完成分析，並套用台新新光金控簡報版型，自動產出可編輯、可追溯且數值正確的策略簡報。
>
> ⚠️ **資料領域變更說明**：命題文件原以金管會公開信用卡業務統計資料作為示範資料來源，但主辦方後續說明決賽當天將改用**旅遊業務相關 Excel 資料（11 份）**，並期待系統能吃「通用 Prompt」直接一步到位生成簡報，而非針對特定領域寫死指標。本專案架構因此調整為**領域無關（domain-agnostic）**設計：不預先寫死業務指標，改以「通用運算積木 + 資料目錄 + LLM Function Calling」因應任意領域、任意數量的 Excel 輸入。信用卡範例資料仍保留作為開發期間的測試/模擬資料。

---

## 1. 專案目標

本專案要解決傳統報表製作流程中「人工彙整多張 Excel、跨表計算、製作圖表、撰寫洞察、套版簡報及寄送」耗時且容易出錯的問題。

系統輸入：

1. 台新新光金控 PowerPoint 簡報版型。
2. **多份 Excel 業務資料**（決賽現場提供，本次為 11 份旅遊業務相關資料；欄位結構、業務指標事先未知）。
3. 系統提示詞／使用者通用 Prompt（例：「整年度市占率」「哪個景點成長最快」）。
4. 收件主管或輸出位置等執行參數。

系統輸出：

1. 依 Prompt 動態規劃章節之策略簡報（頁數以 16 頁為基準，章節主題依實際資料與 Prompt 動態產生，不寫死於單一業務領域）。
2. 與簡報同步的分析結果 Excel。
3. 可編輯的 PowerPoint 原生圖表、表格與文字物件。
4. 每個數值的來源檔案／工作表／儲存格、計算積木鏈、計算假設聲明與校驗紀錄。
5. 可部署的 Live Demo 與完整 GitHub 原始碼。

---

## 2. 核心設計原則

### 2.1 LLM 不直接負責精確計算

LLM 僅負責：

- 理解任務與分析需求。
- 規劃簡報章節與分析方向。
- 選擇適合的指標、圖表及比較對象。
- 根據已驗證的計算結果撰寫商業洞察。
- 產生標題、摘要及策略建議。

所有加總、比率、排名、月增率、市占率等數值，必須由 Python 程式以確定性方式計算。

### 2.2 優先讀取 Excel 原生結構

系統應直接使用 `openpyxl`、`pandas` 或等效工具讀取：

- 工作表名稱。
- 儲存格原始值。
- 欄位名稱與月份。
- 公式與格式。
- 合併儲存格及單位資訊。

不得先將 Excel 轉為圖片，再由視覺模型辨識數值。

### 2.2a 多檔案先建「資料目錄」，LLM 不直接讀原始 Excel

因決賽將一次提供多份（11 份）領域未知的 Excel，系統需先離線建立 **Data Catalog**：跨檔案欄位語意比對（規則式比對 → embedding 相似度 → LLM/人工仲裁，逐層才升級成本）、統一欄位詞典、跨檔案關聯鍵推斷。LLM 後續只讀取精簡的 Data Catalog，不直接讀 11 份原始 Excel，藉此降低 context 負擔與欄位幻覺風險。詳細設計見 [`task1.md`](./task1.md)。

### 2.2b LLM 只能呼叫「白名單積木」，不得生成任意計算程式碼

為兼顧「通用 Prompt 一步到位生成」與「數字精確可追溯」，LLM 不直接生成 pandas 程式碼，也不寫死業務指標函式，而是透過 Function Calling 呼叫一組固定、領域無關的通用運算積木（`filter`、`group_sum`、`ratio`、`growth_rate`、`rank_top_n`、`pivot`、`join` 等，共 10 餘個）。任何業務指標（市占率、YoY、平均消費等）皆為積木的組合結果，換領域不需新增函式。LLM 同時須輸出非阻斷式的「計算假設聲明」，說明其對業務定義的理解，供人事後核對，而不是每次遇到模糊語意就中斷詢問使用者。詳細設計見 [`task1.md`](./task1.md)。

### 2.3 PowerPoint 必須保留原生物件

簡報中的圖表、表格與文字，應由 `python-pptx`、`PptxGenJS` 或其他簡報函式庫產生為可編輯物件，不得只貼上整頁圖片。

### 2.4 每個數值都必須可追溯

簡報中的數值必須能對應到：

- Excel 檔案名稱。
- 工作表名稱。
- 原始欄位與儲存格範圍。
- 計算公式。
- 單位轉換方式。
- 四捨五入規則。
- 校驗結果。

---

## 3. 建議系統流程

> 完整版含資料目錄建置與白名單積木細節，請見 [`task1.md`](./task1.md)。

```mermaid
flowchart LR
    A[上傳多份 Excel、PPT 模板及提示詞] --> B[逐檔解析：Excel 原生結構]
    B --> C[欄位語意比對：規則→embedding→LLM/人工]
    C --> C2[輸出 Data Catalog]
    C2 --> D[LLM 讀 Catalog，組合白名單積木]
    D --> D2[計算假設聲明 + 積木執行引擎]
    D2 --> E[Sanity Check 與資料血緣]
    E --> F[LLM 分析規劃與洞察生成]
    F --> G[圖表與頁面規格 JSON]
    G --> H[PPT 原生物件生成]
    H --> I[模板套用與版面檢查]
    I --> J[簡報數值回溯校驗]
    J --> K[輸出 PPT、Excel、QA 報告]
    K --> L[Live Demo／自動寄送]
```

---

# 4. 四人工作分配

## 第一大項：Excel 資料解析、指標計算與資料血緣

**主要負責人：成員 A — Data Engineer／Calculation Owner**

> 📄 **完整架構規格請見 [`task1.md`](./task1.md)**，以下為摘要。原本針對信用卡資料設計的「指標計算函式庫」（流通卡數、有效卡率、呆帳率…逐一寫死函式）已**不再適用**：因決賽當天提供的是 11 份**領域未知的旅遊業務 Excel**，且主辦方要求系統能吃「通用 Prompt」直接生成，不能針對單一領域寫死指標。

### 工作目標

建立可靠、**領域無關**的資料層，確保所有簡報數值不是由 LLM 猜測，而是由程式從原始 Excel 精確計算，且能因應決賽當天才公布、欄位結構未知的多份 Excel。

### 工作內容（新版摘要，詳見 task1.md）

1. **資料目錄建置（一次性、離線）**：逐檔解析多份 Excel 的工作表、欄位、型別、單位；跨檔案欄位語意比對（規則式比對 → embedding 相似度 → LLM/人工仲裁，逐層才升級成本）；建立統一欄位詞典與跨檔案關聯鍵；輸出精簡的 `data_catalog.json`。
2. **通用運算積木庫**：以 10 餘個領域無關的統計原語（`filter`、`filter_by_period`、`group_sum`、`group_mean`、`ratio`、`growth_rate`、`rank_top_n`、`pivot`、`join`、`cumulative_sum`）取代逐一寫死的業務指標函式；任何業務指標（市占率、YoY、平均消費…）皆為積木組合的結果。
3. **LLM Function Calling 執行流程**：LLM 讀取 `data_catalog.json`（非原始 Excel）→ 產生非阻斷式「計算假設聲明」→ 透過 function calling 選積木、填參數（欄位僅能從 Catalog 白名單選取，禁止自由輸入）→ 積木執行引擎確定性運算。
4. **Sanity Check 與例外處理**：比率是否落在 0–100%、分母是否為 0、結果是否 NaN；失敗則回饋 LLM 重新組積木（最多重試 2 次），仍失敗標記「需人工確認」；除以零、缺值、重複欄位、月份不完整一律明確處理，不默默吞錯。
5. **資料血緣紀錄**：保存來源檔案、工作表、儲存格範圍、積木調用鏈、計算假設聲明、校驗結果。
6. **標準化輸出**：匯出 `data_catalog.json`、`analysis_result.xlsx`、`data_lineage.json`，供成員 B／C／D 使用。

### 必須特別處理的問題

- 沒有提供前一年同期資料時，不得自行產生 YoY，輸出 `N/A` 並附原因。
- 市占率等比率的分母必須明確定義（由 LLM 輸出假設聲明供人核對，而非事後猜測）。
- 圖表座標軸須依實際單位設定，不得混用不同量級單位。
- 排名必須由積木（程式）排序，不能由 LLM 憑語意排列。
- 欄位比對信心不足時，優先列為人工核對清單，不強行自動配對。
- LLM 不得生成任意計算程式碼，僅能呼叫白名單積木。

### 交付成果

- `src/catalog_builder/`（多檔案解析、欄位比對、關聯推斷）
- `src/calculation_engine/blocks/`（白名單積木）
- `src/calculation_engine/executor.py`（function calling 執行引擎）
- `src/validation/sanity_check.py`
- `src/validation/data_lineage.py`
- `outputs/data_catalog.json`
- `outputs/analysis_result.xlsx`
- `outputs/data_lineage.json`
- 積木單元測試。

### 驗收標準

- 11 份檔案可一次上傳並完成 Catalog 建置。
- 指定抽查數值與原始 Excel 完全一致。
- 所有比例計算誤差不超過設定的四捨五入範圍。
- 缺少同期資料時，輸出 `N/A` 並附原因。
- 每個簡報 KPI 都可回查來源檔案、工作表、儲存格、積木鏈與假設聲明。
- 積木庫可在不新增函式的前提下，同時覆蓋信用卡與旅遊資料的指標需求。

---

## 第二大項：LLM 提示詞、分析 Agent 與商業洞察生成

**主要負責人：成員 B — LLM Engineer／Insight Owner**

### 工作目標

讓 LLM 負責「理解、規劃與判斷」，並以已驗證資料產生具商業價值的策略洞察，而不是只重述數字。

### 工作內容

1. 整理附件中的系統提示詞，轉換為可程式化的 Prompt Template。
2. 定義 LLM 可使用的工具（對接 Task 1 之白名單積木，領域無關）：
   - 查詢指標（呼叫積木組合）。
   - 取得排名（依實際資料維度，如國家／機構／景點）。
   - 取得期間趨勢。
   - 取得整體平均／總計。
   - 取得數值來源與校驗狀態。
3. 將任務拆分為多個 Agent 或階段：
   - Planner Agent：依實際資料目錄與 Prompt **動態規劃**簡報章節結構（以 16 頁為基準，章節主題不寫死於單一業務領域，例如信用卡情境可能是「同業競爭分析」，旅遊情境可能是「客源國比較」）。
   - Analyst Agent：選擇指標與比較對象。
   - Insight Agent：撰寫商業洞察。
   - Reviewer Agent：檢查敘述是否與數據一致。
4. 設計結構化輸出格式，避免直接輸出不可控的自然語言，例如：

```json
{
  "slide_no": 3,
  "title": "Executive Summary",
  "key_message": "市場成長主要由簽帳額驅動",
  "kpis": [],
  "chart_spec": {},
  "insights": [],
  "recommendations": [],
  "source_ids": []
}
```

5. 設計商業洞察規則：
   - 必須同時說明「發生什麼、為什麼重要、可能原因、建議行動」。
   - 不得將推測寫成確定事實。
   - 推測內容需使用「可能、推測、顯示」等措辭。
6. 建立防幻覺限制：
   - LLM 只能引用資料 API 傳回的數字。
   - 不允許在文字中自行新增數字。
   - 不存在的 YoY、市場平均或排名必須標示無法計算。
7. 使用 Kiro 作為 AI 整合開發環境，整理規格、任務與 Agent 工作流，以爭取加分項目。

### 交付成果

- `prompts/system_prompt.md`
- `prompts/slide_planner.md`
- `src/agents/planner_agent.py`
- `src/agents/analyst_agent.py`
- `src/agents/reviewer_agent.py`
- `schemas/slide_spec.schema.json`
- 範例 16 頁 `slide_spec.json`。

### 驗收標準

- LLM 輸出的所有數字都存在於計算引擎結果。
- 每頁有明確核心訊息，不只是數字清單。
- 洞察包含管理意涵與建議行動。
- 不得將未提供的前期資料當作 YoY 基期。
- 重新執行同一資料時，簡報架構與主要結論維持合理一致。

---

## 第三大項：PowerPoint 模板解析、原生圖表與版面生成

**主要負責人：成員 C — Presentation Engineer／PPT Owner**

### 工作目標

依台新新光金控模板產生 16 頁專業簡報，並確保文字、圖表、表格均可在 PowerPoint 中再次編輯。

### 工作內容

1. 分析附件一的模板：
   - 投影片尺寸。
   - 母片與版面配置。
   - Logo、頁尾、頁碼。
   - 字型、字級、色彩及間距。
   - 標題與內容區域座標。
2. 建立共用頁面元件：
   - 封面。
   - 目錄。
   - Chapter 分隔頁。
   - KPI 卡片。
   - 洞察卡片。
   - 策略建議卡片。
   - 頁尾與頁碼。
3. 建立原生圖表：
   - 排名橫條圖。
   - 市占率圖。
   - 月度趨勢折線圖。
   - 規模 vs 成長散點圖。
   - 佔比／滲透率比較圖（如原本的有效卡率比較圖，通用化為任意「率」指標）。
   - 熱力圖。
   - 分項堆疊圖（如原本的循環信用與分期堆疊圖，通用化為任意複合結構指標）。
   - 風險／異常象限圖。
4. 建立原生 PowerPoint 表格，不以圖片模擬表格。
5. 將 `slide_spec.json` 轉換為 PowerPoint 頁面。
6. 確保圖表的資料可透過 PowerPoint「編輯資料」檢視。
7. 處理長文字、自動換行、字級縮放及圖表標籤碰撞。
8. 產出以 16 頁為基準的簡報，**章節主題由 Planner Agent（成員 B）依實際 Data Catalog 與 Prompt 動態規劃**，不寫死於單一業務領域；固定不變的只有「封面／目錄／Executive Summary／感謝頁」等版面骨架。以下為**信用卡情境範例**（開發期間可先用此驗證 PPT 產生邏輯），供對照通用結構：

| 頁次 | 固定骨架 | 信用卡情境範例（僅供對照，非寫死） |
|---|---|---|
| 1 | 封面 | 封面 |
| 2 | 目錄 | 目錄 |
| 3 | Executive Summary | Executive Summary |
| 4 | Chapter 01（動態） | 市場整體概況 |
| 5 | 動態頁 | 市場規模趨勢 |
| 6 | 動態頁 | 市占率排名 |
| 7 | Chapter 02（動態） | 同業競爭分析 |
| 8 | 動態頁 | 規模 vs 成長 |
| 9 | 動態頁 | 有效卡率比較 |
| 10 | Chapter 03（動態） | 客戶活躍度與獲利能力 |
| 11 | 動態頁 | 每卡簽帳金額 |
| 12 | 動態頁 | 循環信用與分期 |
| 13 | Chapter 04（動態） | 風險與警訊 |
| 14 | 動態頁 | 風險指標比較 |
| 15 | Chapter 05（動態） | 台新策略建議 |
| 16 | 感謝頁／資料來源 | 感謝頁／資料來源 |

> 若決賽當天為旅遊資料，Chapter 主題可能改為「整體觀光概況」「主要客源國比較」「季節性／旺淡季」「消費力與停留天數」「策略建議」等，實際由 Planner Agent 依 Data Catalog 內容動態決定。

### 必須特別處理的問題

- 圖表不得以螢幕截圖或整張圖片嵌入。
- 座標軸的最小值、最大值、單位與標籤必須正確。
- 排名與圖表順序必須和分析資料一致。
- 「10.6% 高於 11.1%」等邏輯矛盾必須被攔截。
- PowerPoint 圖表顯示值需與其內嵌資料表一致。

### 交付成果

- `src/presentation/template_parser.py`
- `src/presentation/components/`
- `src/presentation/chart_factory.py`
- `src/presentation/ppt_generator.py`
- `outputs/final_presentation.pptx`
- 版面元件測試頁及字型設定文件。

### 驗收標準

- 簡報共 16 頁，版型與附件一一致。
- 所有圖表與表格皆可編輯。
- 圖表資料、標題、圖例、單位及排序正確。
- 無文字溢出、遮蔽、跑版或圖表標籤重疊。
- 在 Microsoft PowerPoint 開啟時不出現修復提示。

---

## 第四大項：數值回溯 QA、系統整合、部署與 Live Demo

**主要負責人：成員 D — QA／Integration／Demo Owner**

### 工作目標

將前三個模組整合為完整端到端系統，建立自動化校驗、操作介面、部署環境及比賽展示流程。

### 工作內容

1. 建立完整 Pipeline：

```text
上傳檔案 → 解析 → 計算 → LLM 規劃 → PPT 生成 → 數值回溯 → 輸出
```

2. 建立簡報回溯校驗：
   - 擷取簡報中的 KPI、圖表資料及表格數值。
   - 與 `analysis_result.xlsx` 或 `data_lineage.json` 比對。
   - 不一致時阻止輸出並產生錯誤報告。
3. 建立邏輯校驗規則：
   - 百分比大小關係與文案一致。
   - 排名文字與圖表順序一致。
   - Top N 不重複、不漏項。
   - 市占率總和合理。
   - 圖表座標軸涵蓋所有資料點。
   - 無基期時不得出現 YoY。
4. 建立 Web Demo：
   - 上傳 Excel、模板及提示詞。
   - 顯示處理進度。
   - 預覽分析摘要。
   - 下載 PPT、Excel 及 QA 報告。
5. 規劃 AWS 部署：
   - 前端／API。
   - 檔案暫存。
   - 任務佇列。
   - 環境變數與密鑰管理。
6. 建立自動寄送功能，將成果寄送指定主管。
7. 建立 GitHub 專案管理：
   - Issue。
   - Pull Request。
   - Branch protection。
   - CI 測試。
   - Release。
8. 規劃比賽 Live Demo、備援影片及操作腳本。

### 交付成果

- `src/pipeline.py`
- `src/validation/ppt_reconciler.py`
- `app/` 或 `frontend/`
- `deployment/`
- `tests/integration/`
- `outputs/qa_report.html`
- Demo 網址與錄製影片連結。
- GitHub README、安裝與執行說明。

### 驗收標準

- 從上傳檔案到產出結果可一鍵完成。
- 所有頁面通過數值與邏輯校驗後才允許下載。
- 發生錯誤時能指出頁碼、指標、來源值及簡報值。
- Demo 可於比賽現場穩定執行。
- GitHub 包含完整程式碼、安裝方式、測試與範例輸出。

---

# 5. 四人協作界面

為避免四個人各自開發後無法整合，需先固定以下介面。

## 5.1 資料引擎輸出格式

> 以下為信用卡情境的**示例**（schema 結構不變，欄位值換領域即可沿用）；正式版 schema（新增 `assumption_statement`、`block_chain` 等欄位）請見 [`task1.md`](./task1.md) 第 5 節。

```json
{
  "metric_id": "market_total_cards_11412",
  "metric_name": "市場流通卡數",
  "value": 60485911,
  "display_value": "6,049 萬張",
  "unit": "張",
  "period": "11412",
  "formula": "SUM(all institutions)",
  "source": [
    {
      "file": "附件四_預期修正參照資料.xlsx",
      "sheet": "P.5預期修正_流通卡數",
      "range": "B2:M34"
    }
  ],
  "validation_status": "passed"
}
```

旅遊情境對應範例：

```json
{
  "metric_id": "tourist_share_japan_2025",
  "metric_name": "日本旅客市占率",
  "value": 0.187,
  "display_value": "18.7%",
  "unit": "%",
  "period": "2025",
  "assumption_statement": "市占率 = 日本旅客人次 ÷ 全部國家旅客人次總和，期間為2025年1-12月",
  "block_chain": ["group_sum(日本)", "group_sum(ALL)", "ratio"],
  "source": [
    {"file": "附件_旅客統計_01.xlsx", "sheet": "工作表1", "range": "B2:M13"}
  ],
  "validation_status": "passed"
}
```

## 5.2 LLM 投影片規格格式

```json
{
  "slide_no": 5,
  "layout": "trend_chart",
  "title": "市場規模趨勢 — 流通卡數與簽帳金額",
  "headline": "市場卡數維持緩增，簽帳金額波動幅度更高",
  "chart": {
    "type": "combo",
    "series_metric_ids": [
      "market_total_cards_11401_11412",
      "market_purchase_amount_11401_11412"
    ]
  },
  "insights": [
    {
      "text": "簽帳金額的變動幅度明顯高於卡數，顯示市場競爭重點已由發卡規模逐步轉向卡戶活躍度。",
      "evidence_metric_ids": [
        "market_total_cards_11401_11412",
        "market_purchase_amount_11401_11412"
      ]
    }
  ]
}
```

## 5.3 QA 報告格式

```json
{
  "status": "failed",
  "errors": [
    {
      "slide_no": 6,
      "type": "narrative_logic_error",
      "message": "文案稱 10.6% 高於 11.1%，大小關係錯誤",
      "expected": "10.6% 低於 11.1%"
    }
  ]
}
```

---

# 6. GitHub 目錄規劃

```text
project-root/
├─ README.md
├─ task1.md                     # Task 1 完整架構規格（成員A）
├─ requirements.txt
├─ .env.example
├─ app/
│  ├─ api/
│  └─ web/
├─ prompts/
│  ├─ system_prompt.md
│  ├─ slide_planner.md
│  └─ insight_reviewer.md
├─ schemas/
│  ├─ data_catalog.schema.json  # 新增：資料目錄 schema
│  ├─ metric.schema.json
│  └─ slide_spec.schema.json
├─ src/
│  ├─ catalog_builder/          # 新增：多檔案解析、欄位比對、關聯推斷
│  ├─ calculation_engine/
│  │  ├─ blocks/                # 新增：白名單積木（領域無關）
│  │  └─ executor.py            # 新增：LLM function calling 執行引擎
│  ├─ agents/
│  ├─ presentation/
│  ├─ validation/
│  └─ pipeline.py
├─ templates/
│  └─ taishin_template.pptx
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ outputs/
│  └─ data_catalog.json         # 新增：資料目錄輸出
├─ deployment/
└─ docs/
   ├─ architecture.md
   ├─ data_dictionary.md
   └─ demo_script.md
```

---

# 7. 分支與協作規則

| 分支 | 用途 |
|---|---|
| `main` | 比賽可展示的穩定版本 |
| `develop` | 日常整合 |
| `feature/data-engine` | 成員 A |
| `feature/llm-agent` | 成員 B |
| `feature/ppt-generator` | 成員 C |
| `feature/qa-demo` | 成員 D |

協作規則：

1. 每項功能使用獨立 Pull Request。
2. 不直接 Push 至 `main`。
3. 所有 PR 至少由一名其他成員 Review。
4. 修改共用 JSON Schema 時，四人必須同步確認。
5. 合併前必須通過單元測試與端到端測試。
6. 每日固定一次 15 分鐘整合會議，確認介面變更與阻塞事項。

---

# 8. 建議開發時程

## 第一階段：規格與資料盤點

- 確認附件資料結構、簡報模板及 16 頁內容。
- 固定資料 Schema、Slide Spec 與 QA 規則。
- 建立 GitHub、分支及開發環境。

## 第二階段：四模組平行開發

- A：完成 Excel 解析、指標計算與資料血緣。
- B：完成 Prompt、Agent 與結構化輸出。
- C：完成模板解析、頁面元件及圖表工廠。
- D：完成 Pipeline 骨架、Web Demo 與 QA 規格。

## 第三階段：端到端整合

- 串接資料引擎、LLM 及 PPT 生成器。
- 完成第一版 16 頁簡報。
- 修正資料欄位、圖表單位、排序及版面問題。

## 第四階段：QA 與比賽展示

- 執行數值逐頁回溯。
- 壓力測試不同 Excel 工作表與缺值情境。
- 部署 AWS。
- 完成 Demo 影片、提案簡報及現場操作腳本。

---

# 9. Definition of Done

本專案只有同時符合以下條件才視為完成：

- [ ] 可讀取多張 Excel 工作表。
- [ ] 可依指定 Prompt 生成 16 頁簡報規格。
- [ ] 所有計算由程式完成，不由 LLM 手算。
- [ ] 缺少基期資料時不會產生錯誤 YoY。
- [ ] 所有簡報數值可回溯至原始 Excel。
- [ ] 排名、市占率、座標軸及單位正確。
- [ ] PowerPoint 圖表與表格為可編輯原生物件。
- [ ] 簡報套用台新新光金控模板。
- [ ] 簡報文案與圖表數值不存在邏輯矛盾。
- [ ] 可同時輸出 PPT、Excel 及 QA 報告。
- [ ] Live Demo 可穩定執行。
- [ ] GitHub 包含完整原始碼、安裝方式及測試。
- [ ] 提供部署網址及錄製影片連結。

---

# 10. 評分對應

| 評分項目 | 對應實作 |
|---|---|
| 完成度 15% | 端到端 Pipeline、16 頁簡報、Excel、寄送及 Demo |
| 技術可行性 25% | 結構化解析、確定性計算、Agent、原生 PPT 物件 |
| 商業應用性 50% | 數值正確、簡報品質、端到端速度、商業洞察 |
| 主題切合度 5% | 聚焦金融業管報自動化痛點，並以領域無關架構因應決賽當天公布之旅遊資料 |
| 創意度 5% | 資料血緣、回溯校驗、多 Agent 與可編輯簡報 |
| 加分：口述驅動 | 支援語音轉文字後啟動同一 Pipeline |
| 加分：Kiro | 使用 Kiro 管理規格、Agent 與整合開發 |

---