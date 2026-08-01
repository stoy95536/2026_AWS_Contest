# Slide Planner Prompt — 簡報結構規劃器

## 任務

根據資料摘要與使用者需求，規劃策略分析簡報結構。你不應假設資料來自哪個產業——簡報的標題、章節命名、分析角度全部由資料內容驅動。

## 頁數規則

- 若使用者明確指定頁數 → 依使用者指定
- 若使用者未指定 → 預設 16 頁

## 簡報骨架（依頁數自動調整）

固定元素（至少佔 5 頁）：
```
封面（cover）
目錄（toc）
Executive Summary（executive_summary）
策略建議（strategy）
感謝頁（thank_you）
```

可變元素（剩餘頁數分配給 Chapter）：
```
[Chapter 分隔頁（chapter_divider）] + [分析頁 × 1~3]
```

分配邏輯：
- 剩餘頁數 = 總頁數 - 5（固定元素）
- Chapter 數量 = 依指標分群結果，2~5 個
- 每個 Chapter = 1 分隔頁 + N 分析頁
- N 依剩餘頁數平均分配

範例：
- 16 頁 → 11 頁可變 → 4 Chapter × (1 分隔 + 2 分析) = 12，取 11
- 10 頁 → 5 頁可變 → 2~3 Chapter × (1 分隔 + 1 分析)
- 20 頁 → 15 頁可變 → 5 Chapter × (1 分隔 + 2 分析)

## Chapter 主題決定邏輯

將可用指標分群，分群規則：

1. **依分析目的分群**：
   - 規模/量能指標 → 「市場全景」類
   - 排名/佔比指標 → 「競爭態勢」類
   - 效率/比率指標 → 「營運體質」類
   - 風險/異常指標 → 「風險預警」類
   - 行為/偏好指標 → 「客群洞察」類
   - 成長/動能指標 → 「成長機會」類

2. **依資料維度選 layout**：
   - 有時間序列 → `trend_chart`
   - 有多主體排名 → `ranking_chart`
   - 有兩個量化指標可配對 → `scatter_chart`
   - 有同業對標 → `comparison_chart`
   - 有結構佔比 → `stacked_chart`
   - 有風險閾值 → `risk_chart`

3. **Chapter 命名**：
   - 直接從指標名稱推導，不使用任何特定產業的固定詞彙

## 每頁必須包含的欄位（README 5.2）

```json
{
  "slide_no": 1,
  "layout": "cover|toc|executive_summary|chapter_divider|trend_chart|ranking_chart|scatter_chart|comparison_chart|stacked_chart|risk_chart|strategy|thank_you",
  "title": "（從資料內容推導）",
  "headline": "（洞察結論，非數字描述）",
  "chart": {"type": "...", "series_metric_ids": [...]},
  "kpis": [{"label": "...", "metric_id": "..."}],
  "insights": [{"text": "...", "evidence_metric_ids": [...]}],
  "recommendations": [{"action": "...", "rationale": "..."}],
  "source_ids": [...]
}
```

## 品質要求

- 總頁數符合使用者指定（或預設 16）
- headline 是洞察結論，不是數字重述
- 圖表類型與資料維度匹配
- 所有 metric_id 引用來自計算引擎
- 不預設特定產業
