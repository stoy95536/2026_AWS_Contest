"""
Task 2: LLM 提示詞、分析 Agent 與商業洞察生成
主要功能模組位於:
  - src/agents/planner_agent.py   — 簡報結構規劃
  - src/agents/analyst_agent.py   — 分析洞察生成
  - src/agents/reviewer_agent.py  — 品質審核
  - prompts/system_prompt.md      — 系統提示詞
  - prompts/slide_planner.md      — 規劃提示詞
  - prompts/insight_reviewer.md   — 審核提示詞

本檔為 Task 2 獨立執行入口，可單獨測試 Agent 流程。
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agents import PlannerAgent, AnalystAgent, ReviewerAgent


def run_task2(
    data_summary: dict = None,
    use_llm: bool = False,
    output_dir: str = "outputs",
):
    """
    獨立執行 Task 2: Agent 規劃 + 洞察生成 + 審核。

    Args:
        data_summary: 資料摘要 (若無則使用範例)
        use_llm: 是否使用 LLM
        output_dir: 輸出目錄
    """
    print("[Task 2] 開始 LLM Agent 流程...")

    # 預設資料摘要
    if data_summary is None:
        data_summary = {
            "institutions": ["台新銀行", "中國信託", "國泰世華", "玉山銀行", "台北富邦"],
            "metrics": ["流通卡數", "有效卡數", "當月簽帳金額", "循環信用餘額"],
            "periods": ["11401", "11402", "11403", "11404", "11405", "11406",
                       "11407", "11408", "11409", "11410", "11411", "11412"],
            "record_count": 500,
        }

    # Step 1: Planner Agent — 規劃簡報結構
    print("[Task 2] Step 1: Planner Agent 規劃結構...")
    planner = PlannerAgent()
    slide_specs = planner.plan_structure(data_summary, use_llm=use_llm)
    print(f"  產生 {len(slide_specs)} 頁結構")

    # Step 2: Analyst Agent — 生成洞察
    print("[Task 2] Step 2: Analyst Agent 生成洞察...")
    analyst = AnalystAgent()
    all_metric_data = {spec.get("slide_no", 0): [] for spec in slide_specs}
    enriched_specs = analyst.generate_all_slides(slide_specs, all_metric_data, use_llm=use_llm)
    print(f"  已為 {len(enriched_specs)} 頁生成洞察")

    # Step 3: Reviewer Agent — 品質審核
    print("[Task 2] Step 3: Reviewer Agent 審核...")
    reviewer = ReviewerAgent()
    verified_metrics = {}  # 實際執行時從計算引擎取得
    qa_result = reviewer.review(enriched_specs, verified_metrics, use_llm=False)
    print(f"  審核結果: {qa_result['status']} ({qa_result['total_issues']} issues)")

    # 匯出 slide_spec
    os.makedirs(output_dir, exist_ok=True)
    spec_output = os.path.join(output_dir, "slide_spec.json")
    with open(spec_output, "w", encoding="utf-8") as f:
        json.dump(enriched_specs, f, ensure_ascii=False, indent=2)
    print(f"  匯出: {spec_output}")

    print("[Task 2] 完成!")
    return enriched_specs, qa_result


if __name__ == "__main__":
    use_llm = "--llm" in sys.argv
    run_task2(use_llm=use_llm)
