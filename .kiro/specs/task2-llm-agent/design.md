# Task 2 LLM Agent 系統 — Design

> 使用 Kiro IDE 開發。本檔記錄設計階段的架構決策。

## 整體架構

```
Task1 analysis_result.json
   (data_summary + metrics[] + chart_data[])
        │
        ▼
┌─────────────────────────────┐
│  PlannerAgent               │  規劃簡報結構
│  - classify_data()          │  判別情境/類型/主題
│  - plan_structure()         │  產出 slide_spec 骨架
└─────────────────────────────┘
        │ slide_specs
        ▼
┌─────────────────────────────┐
│  AnalystAgent               │  生成策略洞察
│  - _collect_metric_ids()    │  收集合法 metric_id
│  - _sanitize_insights()     │  防幻覺過濾
└─────────────────────────────┘
        │ enriched_specs
        ▼
┌─────────────────────────────┐
│  ReviewerAgent              │  品質審核
│  - _check_references()      │  驗證 metric_id 存在
│  - _check_percentage_logic()│  百分比邏輯
└─────────────────────────────┘
        │
        ▼
   slide_spec.json (→成員C) + qa_report.json (→成員D)
```

## 關鍵設計決策

### 決策 1：Agent 完全不含產業硬編碼
**問題**：初版 Agent 寫死了信用卡指標（如 `compute_effective_card_rate`、「簽帳金額」洞察模板）。
**決策**：改為通用「理解→規劃→判斷」引擎。所有產業相關內容由資料推導或 LLM 動態生成。
**理由**：決賽提供旅遊資料，且目標是通用簡報神器。

### 決策 2：有 chart_data 時強制規則引擎規劃結構
**問題**：LLM 規劃器會編造不存在的 metric_id（如 `出國人次_2020`），造成 QA 大量 missing_source。
**決策**：當 Task1 提供 chart_data 時，結構規劃走規則引擎（引用真實 ID），LLM 只負責 Analyst 的洞察文字。
**理由**：Task1 已算好圖表，Planner 不該重新發明。LLM 的價值在敘事，不在重編數據。

### 決策 3：Analyst 雙層防幻覺
**第一層**：LLM prompt 只提供合法 metric_id 白名單。
**第二層**：LLM 回應後，過濾 evidence_metric_ids，移除不存在的 ID；若全被過濾則退回該頁合法 ID。
**理由**：LLM 即使被約束仍可能幻覺，須有程式端的硬性保證。

### 決策 4：策略頁餵入全簡報關鍵指標
**問題**：策略頁無自帶指標，LLM 誤判「缺乏數據」。
**決策**：串接時給策略頁/摘要頁餵入全簡報前 15 個 passed 指標。
**理由**：策略頁是綜合前述分析，需要看到全局數據才能產出有依據的建議。

## 資料格式（README 契約）

### 輸入（Task1 → Task2）
```json
{
  "data_summary": {"metrics": [...], "institutions": [...], "periods": [...]},
  "metrics": [{"metric_id", "metric_name", "value", "display_value", "unit", "period", "validation_status"}],
  "chart_data": [{"chart_data_id", "chart_type", "title", "categories", "series": [{"name", "values", "metric_ids"}]}]
}
```

### 輸出（Task2 → Task3/Task4）
```json
{
  "slide_no", "layout", "title", "headline",
  "chart": {"type", "series_metric_ids", "series": [{"name", "values", "metric_ids"}]},
  "kpis": [{"label", "metric_id"}],
  "insights": [{"text", "evidence_metric_ids"}],
  "recommendations": [{"action", "rationale"}],
  "source_ids": [...]
}
```

## 容錯設計
- LLM 呼叫失敗 → 自動 fallback 到規則引擎（產出洞察骨架）
- JSON 解析失敗 → fallback 到規則引擎
- metric_id 不存在 → 過濾或標記，不中斷流程
