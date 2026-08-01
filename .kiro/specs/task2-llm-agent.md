# Task 2: LLM 提示詞、分析 Agent 與商業洞察生成

## 需求
讓 LLM 負責「理解、規劃與判斷」，以已驗證資料產生策略洞察。

## 規格

### Agent 架構
1. **Planner Agent** — 規劃 16 頁簡報結構
2. **Analyst Agent** — 生成商業洞察與策略建議
3. **Reviewer Agent** — 檢查數值一致性與邏輯正確性

### LLM 模型
- AWS Bedrock: anthropic.claude-sonnet-4-20250514
- Fallback: rule-based engine (不依賴 LLM 也能運作)

### 提示詞
- prompts/system_prompt.md — 系統角色與限制
- prompts/slide_planner.md — 簡報結構規劃
- prompts/insight_reviewer.md — 品質審核規則

### 結構化輸出
```json
{
  "slide_no": 3,
  "layout": "executive_summary",
  "title": "Executive Summary",
  "headline": "核心訊息",
  "kpis": [...],
  "insights": [...],
  "source_ids": [...]
}
```

### 交付成果
- [x] src/agents/planner_agent.py
- [x] src/agents/analyst_agent.py
- [x] src/agents/reviewer_agent.py
- [x] prompts/system_prompt.md
- [x] prompts/slide_planner.md
- [x] prompts/insight_reviewer.md

### 驗收標準
- [x] Rule-based 模式可獨立運作
- [x] LLM 模式架構已實作（需 AWS credentials）
- [x] 所有數字引用自計算引擎
- [x] 推測性內容有標注
