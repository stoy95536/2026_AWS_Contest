# Task 2 — LLM Agent 系統開發準則（Steering）

> 本檔為 Kiro IDE 開發 Task 2 期間所遵循的設計原則與約束，供團隊成員與主辦單位檢視開發脈絡。

## 系統定位

智匯數據簡報神器的 LLM Agent 層。負責「理解、規劃與判斷」，將計算引擎（Task 1）產出的已驗證數據，轉化為具商業價值的策略簡報規格，交付 PPT 生成（Task 3）與 QA 校驗（Task 4）。

## 核心設計原則

### 1. 領域無關（Domain-Agnostic）
- Agent 程式碼本身**不得寫死任何特定產業內容**（不得出現「信用卡」「簽帳金額」等硬編碼字串）
- 所有簡報標題、章節命名、洞察措辭，一律由輸入資料動態推導
- 信用卡只是範例情境；系統須能處理旅遊、零售、保險等任何金融相關業務資料

### 2. 金融業為核心，跨域為延伸
- 系統定位服務金融機構，但金融業與百工百業相連
- 旅遊資料、零售資料等都是金融業可能面對的業務情境之一
- 目標是「一套能套用在各種情境的 LLM Agent 系統」

### 3. LLM 不碰數字（防幻覺）
- 所有數值由 Task 1 計算引擎以確定性方式產出
- LLM 只能引用計算引擎提供的 metric_id
- Analyst 產出洞察後，強制過濾掉不存在於計算引擎的 metric_id
- Planner 在有 Task1 chart_data 時，強制使用真實圖表資料，不讓 LLM 重新發明 metric_id

### 4. 洞察 ≠ 數字描述
- 每項洞察須包含 WIRA 四要素：發生什麼、為什麼重要、可能原因、建議行動
- 推測性內容須標注（可能、推測、顯示）
- headline 是洞察結論，不是數字重述

## 介面契約（與其他成員對接）

| 對象 | 介面 | 說明 |
|------|------|------|
| 成員 A（Task1） | 讀 `analysis_result.json` | data_summary + metrics[] + chart_data[] |
| 成員 C（Task3） | 產出 `slide_spec.json` | 含 chart.series[{name,values,metric_ids}] |
| 成員 D（Task4） | 產出 `qa_report.json` | {status, errors[{slide_no,type,message,expected}]} |

## 頁數規則
- 使用者明確指定 → 依指定
- 未指定 → 預設 16 頁
- 固定 5 頁（封面/目錄/摘要/策略/感謝），其餘動態分配給章節

## 檔案清單
- `src/agents/planner_agent.py` — 結構規劃
- `src/agents/analyst_agent.py` — 洞察生成
- `src/agents/reviewer_agent.py` — 品質審核
- `prompts/system_prompt.md` — 系統提示詞
- `prompts/slide_planner.md` — 規劃提示詞
- `prompts/insight_reviewer.md` — 審核提示詞
- `schemas/metric.schema.json` — 計算引擎輸出契約（README 5.1）
- `schemas/slide_spec.schema.json` — 投影片規格契約（README 5.2）
- `Task2/Agent_Part.py` — 執行入口（含 run_task2_from_task1 串接函式）
- `tests/test_llm_connection.py` — Bedrock 連線測試
