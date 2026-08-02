# Task 1：Excel 資料解析、指標計算與資料血緣
### 負責人：成員 A — Data Engineer／Calculation Owner

> 本文件為 Task 1 的完整架構規格，取代 README 中原本針對信用卡資料設計的舊版指標函式庫。因決賽現場將提供 **11 份旅遊業務相關 Excel 資料**（欄位結構、業務指標事先未知），本模組改為**領域無關（domain-agnostic）**架構：不事先寫死任何業務指標，而是由「通用運算積木」+「LLM 動態組合」+「資料目錄」三者組成，同時滿足主辦方要求的「通用 prompt 一步到位生成」與「數字精確可溯源」。
>
> 開發期間以主辦方提供的旅遊統計資料（11 份「歷年來臺旅客／國民出國」Excel）作為真實測試集；信用卡範例資料保留作為多檔案情境的模擬對照。

---

## 1. 角色定位與核心主張

Task 1 是整個系統的地基：其他三個模組（LLM 規劃、PPT 生成、QA 校驗）能否正確運作，完全取決於這裡輸出的數字是否精確、可追溯。

**核心主張**：
> LLM 負責語意判斷與決策（要算什麼），程式碼負責確定性計算（怎麼算），資料目錄負責讓兩者可以在不事先知道資料長相的情況下互相溝通。

**三條不可違反的鐵律**：
1. **一律讀原生結構**：openpyxl／pandas 直接讀取儲存格、欄位、公式、單位，絕不轉圖片辨識。
2. **所有數字由程式確定性算出**：LLM 只能透過 function calling 呼叫「白名單積木」，不得自行生成任意計算程式碼、不得在文字中憑空提供數字。
3. **每個數字都可回溯**：來源檔案、工作表、儲存格範圍、積木調用鏈、計算假設、校驗結果，缺一不可。

---

## 2. 為什麼要改架構：從「單一領域指標庫」到「通用積木 + 資料目錄」

| 舊設計（信用卡專屬） | 問題 | 新設計（領域無關） |
|---|---|---|
| `compute_effective_card_rate()` 等業務指標函式，一個指標一個函式 | 換成旅遊資料全部要重寫，指標數量隨領域暴增 | 10 餘個通用統計積木（`group_sum`、`ratio`、`growth_rate`…），由 LLM 自由組合出任意業務指標 |
| 假設只有 1 份資料、欄位已知 | 11 份檔案一次丟入，欄位名稱、單位、關聯方式全部未知 | 新增「資料目錄建置」階段，離線一次性完成欄位比對與跨檔案關聯推斷 |
| LLM 直接被要求回答數字 | 無法驗證、精確度無保證 | LLM 只選積木、填參數；並強制輸出「計算假設聲明」供人核對 |

---

## 3. 整體架構流程

### Stage 0：輸入
- 11 份旅遊 Excel 檔案（決賽現場提供，欄位/業務指標未知）
- 系統提示詞／使用者通用 Prompt（例：「整年度市占率」「哪個景點成長最快」）

### Stage 1：資料目錄建置（Data Catalog Building）— 一次性、離線，與 Prompt 無關

**1a. 逐檔解析**
用 openpyxl／pandas 讀取每份 Excel 的原生結構：工作表名稱、欄位名稱、資料型別、樣本值、合併儲存格、單位標註、儲存格範圍。

**1a-2. 結構正規化前處理（catalog_builder 職責，不可丟給 LLM）**

政府開放資料（本次旅遊統計）有幾個一定會讓程式當掉的結構特徵，必須在解析階段用程式處理乾淨，不能丟給 LLM 現場臨機應變：

- **多層合併表頭**：常見 2~3 層合併 header（洲別 → 國家 → 英文名，例如「東南亞地區 → 馬來西亞 Malaysia」）。需**動態偵測 header 結束列**（往下掃描，某列數值佔比 > 50% 即視為資料起點），再向上把多層表頭文字合併成完整欄名，**不可硬編碼「第 1 列是欄名」**。
- **寬表轉長表**：國家／地區為橫向欄位（wide format），但積木（`group_sum(group_col, value_col)`）預期吃長表。故 Catalog Builder 需先 `melt`／unpivot 成「年度｜維度｜數值」的長格式，再供積木使用。這一步務必寫在前處理，不丟給 LLM。
- **年度字串正規化**：儲存格值為「53年1964」「106 年 2017」這類民國+西元混合字串，非乾淨數字或日期。`filter_by_period` 前須抽取西元年（或民國年 +1911），否則排序、篩選會整組壞掉。
- **異常佔位值處理**：發現負數（如 -547、-10751）等疑似「小計調整／缺值標記」，不得默默當正常值加總，須標記進 `needs_manual_review`。
- **各檔起始年份不一**：如表 2-3 從 1994 起、表 1-9 從 1972 起，跨檔 `join` 須允許部分年度缺值，不可假設所有檔案年度範圍一致。
- **合計欄不必獨立列卡**：「亞洲合計」「總計」等本身是其他欄加總的結果，計算時由 `group_sum` 現場算即可，減少 canonical 欄位數量。

**1b. 欄位語意比對（四層漏斗，逐層才升級成本）**

| 層級 | 方法 | 成本 | 觸發時機 |
|---|---|---|---|
| Layer 0 | 樣板指紋比對：對表頭做 fingerprint／hash，命中開發期已知樣板則直接套用預定義 mapping（信心 0.99） | 幾乎零成本 | 一律先跑，命中即跳過後續漏斗 |
| Layer 1 | 規則式比對：字串相似度（`rapidfuzz`）、型別匹配、**數值結構特徵** | 無需模型 | Layer 0 未命中時一律跑 |
| Layer 2（可選） | Embedding 相似度比對 | 低（embedding model，非生成式 LLM） | Layer 1 信心不足時 |
| Layer 3 | LLM 仲裁 或 人工核對清單 | 中～高 | 前幾層仍模糊的極少數欄位；兩天時程建議優先人工核對 |

> **Layer 1 比對的是「數值的結構特徵」而非欄名字串本身**：欄位數值是否落在 0–100（像百分比）、是否為遞增四位數（像年份）、量級是否為大數（像人次），加上表頭的中英雙語模式與單位關鍵字（人次／美元／%／夜）。即使欄名亂寫、順序打亂、中英夾雜，只要數值統計特徵不變，信心分數就穩定——這是「換領域也能用」的關鍵，不是死背這 11 份的欄名。

> **為什麼不讓 LLM 當第一線做全部欄位比對**：（1）成本／速度——幾百個欄位每個都問 LLM 會拖垮兩天時程與 demo 現場；規則式先篩掉九成不需爭議的欄位。（2）可重現性——規則比對同輸入必得同結果，符合驗收標準「同 Prompt 重跑結果一致」；LLM 即使 temperature=0 對開放式語意判斷仍可能飄。（3）錯誤可見性——規則錯了看得到理由（相似度只有 40%），LLM 錯了往往「講得很有自信但悄悄錯」，難以事後察覺。LLM 只留給規則卡住的極少數模糊案例。

**1c. 建立統一欄位詞典**：`canonical_field → 各檔案實際欄位名稱` 的映射表

**1d. 推斷跨檔案關聯鍵**：找出各檔案共同維度（如國家、期間、景點類別），建立檔案關聯圖，供跨檔案 `join` 使用

**1e. 輸出 Data Catalog**：精簡 JSON，**只存欄位的「地址與意思」（欄名、單位、儲存格範圍、少量樣本值、信心分數），不含原始資料全文**。供 Stage 2 的 LLM 讀取（取代讀取 11 份原始 Excel，大幅降低 context 負擔與幻覺風險）。

> **Data Catalog 是「一欄一張卡」，不是「一格一張卡」**：不記錄任何「列」的實際數值。本次 11 份合計約 210 個原始欄位，扣掉合計欄與語意合併後更少，整份 Catalog 僅數十 KB，塞進 LLM 無壓力。實際數字永遠是計算時由程式直接回原始檔案讀取。

### Stage 2：使用者 Prompt 處理 — 每次提問即時執行

1. 使用者輸入通用 Prompt
2. LLM 讀取 Data Catalog（非原始 Excel），判斷需要哪些檔案、哪些標準化欄位
3. LLM 產生「**計算假設聲明**」（非阻斷式）：用一句結構化文字寫出對業務定義的理解（分子分母、期間範圍等），存入血緣、**不中斷流程**
4. LLM 透過 Function Calling 組合白名單積木（**不生成任意 pandas 程式碼**）
5. 積木執行引擎：已測試過的 Python 函式，依 Data Catalog 映射**回原始 Excel 讀取真實數值**，確定性運算
6. Sanity Check：比率是否落在 0–100%、分母是否為 0、結果是否 NaN。失敗 → 回饋 LLM 重新組積木（最多重試 2 次）→ 仍失敗標記「需人工確認」
7. 資料血緣紀錄：來源檔案、工作表、儲存格範圍、積木調用鏈、假設聲明、校驗結果
8. 輸出標準化結果（同源）：`analysis_result.xlsx` / `data_lineage.json` / metric JSON / chart_data JSON，交付成員 B（LLM 規劃）、C（PPT 生成）、D（QA 回溯）

```text
11 個 Excel + Prompt
   → [Stage 1．一次性] 逐檔解析 + 結構正規化前處理
      → 欄位語意比對(指紋→規則→embedding→LLM/人工) → 統一欄位詞典
      → 推斷跨檔案關聯鍵 → 輸出 Data Catalog
   → [Stage 2．每次提問] 讀 Catalog → LLM 判斷所需檔案/欄位 → 產生計算假設聲明
      → LLM function calling 組白名單積木 → 積木執行引擎回原始 Excel 確定性運算
      → Sanity Check（失敗則重試/標記人工） → 資料血緣紀錄
      → 由同一份計算結果同源輸出 JSON + Excel
   → 交付成員 B / C / D
```

---

## 4. 白名單積木庫（通用運算原語，非業務指標）

積木刻意設計在「比業務指標更低一層」，數量固定、領域無關，任何業務指標都是這些積木的組合結果。

```python
def filter(data, column, condition): ...
def filter_by_period(data, date_column, start, end): ...
def group_sum(data, group_col, value_col): ...
def group_mean(data, group_col, value_col): ...
def ratio(numerator, denominator): ...
def growth_rate(current, previous): ...
def rank_top_n(data, value_col, n): ...
def pivot(data, index, columns, values): ...
def join(data_a, data_b, on): ...
def cumulative_sum(data, value_col): ...
```

**範例：業務指標 = 積木組合，不需新增函式**

| 使用者問法 | 積木組合鏈 |
|---|---|
| 整年度市占率 | `filter_by_period(全年)` → `group_sum(by=國家)` → `ratio(單一國家/全部加總)` |
| 哪個景點成長最快 | 兩次 `filter_by_period` + `group_sum(by=景點)` → `growth_rate` → `rank_top_n` |
| 平均每人次消費 | `group_sum(消費金額)` → `group_sum(人次)` → `ratio` |
| 旺季 vs 淡季比較 | 兩次 `filter(月份區間)` → 各自 `group_sum` → 比較 |

新問法出現時只需重新組合積木，**不新增函式**，用 README 中原本規劃的十幾個信用卡指標反推驗證：全部可用上述積木表達，證明積木庫領域無關。

**LLM Function Calling 呼叫範例**：
```json
{
  "function": "ratio",
  "args": {
    "numerator": {
      "function": "group_sum",
      "args": {"filter": {"column": "國家", "value": "日本"}, "value_column": "旅客人次_canonical"}
    },
    "denominator": {
      "function": "group_sum",
      "args": {"filter": {"column": "國家", "value": "ALL"}, "value_column": "旅客人次_canonical"}
    }
  }
}
```
注意：`value_column` 只能從 Data Catalog 的 canonical 欄位白名單中選，不允許自由輸入字串，避免幻覺欄位名稱。**LLM 端須以 structured output／function calling schema 強制約束：只能點白名單積木、欄位只能選 Catalog canonical。**

---

## 5. 資料結構規格（與成員 B/C/D 的合約）

> **重要：本節所有 metric／chart_data schema 由 Python 程式組裝，非 LLM 生成。** LLM 僅輸出 function call（純指令、無數字，見上節），經積木引擎算出真值後，由程式填入 `value`／`source`／`validation_status` 等欄位。分工是：**LLM 端用 structured output 約束「能點什麼菜」；程式端用 Pydantic 驗證「端出來的成品格式對不對」。** 兩層守不同關卡。只要 `value`／`source`／`validation_status` 有一個是 LLM 生成的，「LLM 不碰數字」的賣點就破功。

### 5.1 Data Catalog Schema
```json
{
  "files": [
    {
      "file_name": "表1-3-歷年來臺旅客按國籍分.xlsx",
      "sheet_topic": "來臺旅客按國籍",
      "sheets": [
        {
          "sheet_name": "歷年來臺旅客-按國籍",
          "header_rows": [2, 3, 4],
          "data_start_row": 6,
          "canonical_fields": [
            {
              "canonical_name": "旅客人次_日本",
              "source_column": "日本 Japan",
              "unit": "人次",
              "dtype": "number",
              "cell_range": "C6:C67",
              "sample_values": [22733, 40424],
              "confidence": 0.97,
              "alignment_method": "rule"
            }
          ],
          "dimension_columns": ["年度"]
        }
      ]
    }
  ],
  "join_keys": [
    {"dimension": "年度", "files": ["表1-3-歷年來臺旅客按國籍分.xlsx", "表1-10-歷年來臺旅客觀光支出統計表.xlsx"]}
  ],
  "needs_manual_review": [
    {"canonical_name_guess": "小計調整值", "source_column": "東南亞小計 Sub-Total", "file": "表1-2-...xlsx", "reason": "出現負數佔位值，語意待確認"}
  ]
}
```

### 5.2 Metric 輸出 Schema（單值，給 KPI 卡片用）
```json
{
  "metric_id": "tourist_share_japan_2015",
  "metric_name": "日本旅客市占率",
  "value": 0.187,
  "display_value": "18.7%",
  "unit": "%",
  "period": "2015",
  "assumption_statement": "市占率 = 日本旅客人次 ÷ 全部國家旅客人次總和，期間為2015年",
  "block_chain": ["group_sum(日本)", "group_sum(ALL)", "ratio"],
  "source": [
    {"file": "表1-3-歷年來臺旅客按國籍分.xlsx", "sheet": "歷年來臺旅客-按國籍", "range": "C6:C67"}
  ],
  "validation_status": "passed"
}
```

### 5.3 Chart Data 輸出 Schema（給成員 C 生成 PPT 原生圖表用）

單值 metric 只夠 KPI 卡片；PPT 原生可編輯圖表需要「整組資料表」（categories + series），一個點畫不出一張圖。由本模組輸出，成員 C 直接餵給 `python-pptx` 的 `CategoryChartData`。

```json
{
  "chart_data_id": "visitors_by_country_2015",
  "chart_type": "bar",
  "title": "2015年各國來臺旅客人次",
  "unit": "人次",
  "categories": ["日本", "韓國", "美國", "香港"],
  "series": [
    {"name": "旅客人次", "values": [1234567, 987654, 654321, 543210]}
  ],
  "source": [
    {"file": "表1-3-歷年來臺旅客按國籍分.xlsx", "sheet": "歷年來臺旅客-按國籍", "range": "C6:F67"}
  ],
  "validation_status": "passed"
}
```

> **三方一致性要求**：成員 C 用此資料生成的 PPT 原生圖表，其「右鍵→編輯資料」跳出的內嵌 Excel（存於 pptx 內部 `ppt/embeddings/*.xlsx`，這是 Office OOXML 機制，非本模組輸出的 `analysis_result.xlsx`）數值，必須與本 chart_data JSON 及 `analysis_result.xlsx` **三方逐格一致**，供成員 D 做 QA 回溯。三者必須源自同一次計算結果，不可各自重算。

### 5.4 信心分數降級策略（取代「人工卡關」，確保可上線）

`needs_manual_review` 為**非阻斷式標記**，是輸出報告裡的欄位，不是流程關卡——pipeline 全程自動跑完，人工覆核為事後、非同步進行，不影響簡報照樣產出。

| 信心分數 | 系統行為 |
|---|---|
| `confidence ≥ 0.85` | 自動採用 |
| `0.6 ≤ confidence < 0.85` | 採用，但在血緣註記「best-effort 比對，建議覆核」，不隱藏不確定性 |
| `confidence < 0.6` | **不猜**，輸出 `N/A` + 原因，讓下游知道此格算不出 |

> 設計哲學：**不要求 matcher 100% 準，而是讓它在不確定時「安全地閉嘴」，而非硬猜一個錯的數字上簡報。** 一個誠實顯示 N/A 的系統，遠比一個看起來完整但可能算錯的系統更值得信任——這正好命中命題文件點名的「簡報數字與 Excel 不符」，在「商業應用性 50%」是加分而非扣分。

---

## 6. 同源輸出：一份 JSON + 一個 Excel（防止兩份數字對不上）

命題文件明文要求「於生成 PPT 的同時，自動輸出一份與簡報圖表對應的 Excel，內含每張圖表之原始資料」。本模組因此同時輸出機器可讀的 JSON 與人可讀／可驗證的 Excel。

**鐵律：兩份必須「同源」——由同一份計算結果物件分別序列化，不可各算各的、更不可讓 LLM 把 JSON 轉成 Excel。**

```python
# 積木引擎算完，得到唯一一份結果（single source of truth）
results = calculation_engine.run(prompt, catalog)

# 從同一份 results 分兩路輸出，保證數字一致
export_to_json(results, "outputs/analysis_result.json")   # 給程式（成員 B/C/D）
export_to_excel(results, "outputs/analysis_result.xlsx")  # 給人看／評審驗證
```

**`analysis_result.xlsx` 建議工作表結構**（分表，讓評審一看就懂）：

| 工作表名 | 內容 | 對應 |
|---|---|---|
| `指標總表` | 所有 metric：名稱、值、單位、期間、來源檔案/工作表/儲存格、驗證狀態 | metric JSON |
| `圖表資料_各國人次` | 一張圖一個區塊：categories + series | chart_data JSON |
| `圖表資料_年度趨勢` | 每張圖獨立 | chart_data JSON |
| `資料血緣` | 每個數字的積木鏈、假設聲明、來源範圍 | data_lineage JSON |

「圖表資料」各表要跟 PPT 內嵌圖表的資料逐格對得上——這是評審右鍵點 PPT 圖表時會拿來對照的東西。

---

## 7. 資料血緣與可追溯性（回應「能不能追回原始 11 張表」）

- **PPT 圖表右鍵跳出的，永遠是 pptx 內部的內嵌迷你 Excel**（Office OOXML 機制），不可能直接跳到原始那 11 份歷史報表——這不是設計缺陷，是任何工具都一樣，且原始表有多層表頭與數十年資料，使用者也無法直接編輯。
- **本模組保證的是更強的東西**：每個數字都帶 `source`（原始檔案／工作表／儲存格範圍），可現場打開原始 Excel 逐格核對、一碼不差。
- **加分 demo（成員 D）**：Web Demo 可讓簡報上每個數字可點擊，點下去讀取該 metric 的 `source`，直接開啟原始 Excel 並高亮對應儲存格，把「資料血緣」變成評審看得見的一幕。

---

## 8. 例外與風險控管

| 風險 | 對策 |
|---|---|
| 沒有基期資料卻要算 YoY | 不得估算，輸出 `N/A` 並附原因 |
| 分母抓錯（業務定義理解錯誤） | 強制輸出「計算假設聲明」供人核對；Reviewer Agent 獨立覆核 |
| LLM 生成任意程式碼的語法/安全風險 | 全面改用白名單積木 + function calling，禁止 `eval()` 任意執行 |
| 欄位幻覺（抓錯欄位不報錯） | `value_column` 僅能從 Catalog 白名單選取，禁止自由輸入 |
| 同一 Prompt 重跑結果不一致 | LLM temperature 設 0；已驗證通過的積木鏈快取複用 |
| 除以零、缺值、重複欄位、月份不完整 | 積木內統一例外處理，回傳明確錯誤原因，不默默吞錯 |
| 多層合併表頭／寬表／民國年字串 | 於 Stage 1a-2 結構正規化前處理統一處理，不丟給 LLM |
| 異常負數佔位值被當正常值加總 | 標記進 `needs_manual_review`，不默默納入計算 |
| 欄位比對信心不足 | 依 5.4 降級策略：中信心加註、低信心輸出 N/A，不硬猜 |
| JSON 與 Excel 數字對不上 | 同源輸出（第 6 節），由同一份計算結果分兩路序列化 |
| 11 檔案主題不同，不需每次全掃 | Catalog 標註每檔案主題（`sheet_topic`），LLM 先判斷需動用哪些檔案 |

---

## 9. AWS Kiro 規格拆解（Requirements → Design → Tasks）

**Requirements**：
- 每個積木的輸入輸出定義、邊界條件（例：`ratio` 分母為 0 時回傳 `N/A`）
- Data Catalog 各欄位的必填項與信心分數門檻（0.85／0.6 兩道）
- 結構正規化前處理的邊界規則（header 偵測、wide→long、年度字串）

**Design**：
- 資料流：11 Excel → 結構正規化 → Catalog Builder → Data Catalog JSON → LLM Function Calling → 積木執行引擎 → 血緣紀錄 → 同源 JSON+Excel 輸出
- 與成員 B（讀 metric JSON）、C（讀 chart_data JSON 生成 PPT 原生圖表）、D（讀 data_lineage.json 做回溯校驗）的介面對齊

**Tasks（可逐一驗收）**：
1. 讀取單一 Excel 工作表 + 動態偵測多層表頭 + 轉標準長表
2. 實作 Layer 0 樣板指紋 + Layer 1 規則式欄位比對，輸出信心分數
3. 實作 10 個白名單積木並各自寫單元測試
4. 實作 Sanity Check 規則與 self-repair 重試邏輯
5. 實作資料血緣紀錄輸出（含假設聲明欄位）
6. 實作同源 JSON + Excel 輸出（含 chart_data）
7. 用範例資料驗證：11 份旅遊 Excel 跑通全流程

---

## 10. 交付成果與驗收標準

**交付成果**：
- `src/catalog_builder/`（解析、結構正規化、欄位比對、關聯推斷）
- `src/calculation_engine/blocks/`（10 餘個白名單積木）
- `src/calculation_engine/executor.py`（function calling 執行引擎）
- `src/validation/sanity_check.py`
- `src/validation/data_lineage.py`
- `src/export/`（同源 JSON + Excel 輸出）
- `outputs/data_catalog.json`
- `outputs/analysis_result.json`（metric + chart_data）
- `outputs/analysis_result.xlsx`
- `outputs/data_lineage.json`
- 積木單元測試

**驗收標準**：
- [ ] 11 份檔案可一次上傳並完成 Catalog 建置
- [ ] 抽查數值與原始 Excel 完全一致
- [ ] 每個 metric 都可回查來源檔案、工作表、儲存格、積木鏈、假設聲明
- [ ] 缺基期資料時輸出 `N/A` 並附原因，不自行估算
- [ ] 同一 Prompt 重跑，結果一致
- [ ] 積木庫可在不新增函式的前提下，覆蓋 README 原信用卡指標與旅遊資料指標
- [ ] Sanity Check 攔截異常值並觸發重試或人工標記
- [ ] chart_data、analysis_result.xlsx 與 metric JSON 三方數值一致
- [ ] 多層合併表頭、寬表、民國年字串皆能正確解析
- [ ] 欄位比對信心不足時，依降級策略輸出而非硬猜

---

## 11. 兩天時程建議

| 時段 | 工作重點 |
|---|---|
| Day 1 上午 | 結構正規化前處理（多層表頭偵測、wide→long、年度字串）+ Layer 1 規則式欄位比對 + Catalog Builder 打通 |
| Day 1 下午 | 10 餘個白名單積木實作 + 單元測試 |
| Day 1 晚上 | Function Calling 執行引擎 + Sanity Check + 降級策略 |
| Day 2 上午 | 資料血緣輸出 + 同源 JSON/Excel 輸出（含 chart_data）+ 與成員 B/C/D 介面對接 |
| Day 2 下午 | 現場拿到 11 份旅遊 Excel 後，跑通端到端，修正 Catalog 邊界案例 |

> 壓力測試建議：不要只拿乾淨版測。複製幾份故意打亂欄位順序、中英表頭互換、插入雜訊欄、拿掉某幾年造成年份不連續，跑過 matcher 看信心分數分佈與降級行為是否合理——決賽現場要面對的正是「乾淨版你沒看過的親戚」。