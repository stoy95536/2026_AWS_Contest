"""
Task 2: LLM 提示詞、分析 Agent 與商業洞察生成

設計原則：
  - 不內建任何特定產業假設，所有內容由資料驅動
  - 金融業為出發點（因為金融與百工百業相連），但系統能處理任何業務數據
  - 輸入信用卡資料就產出信用卡分析，輸入旅遊資料就產出旅遊分析
  - Agent 本身是通用的「理解→規劃→判斷」引擎

介面規格（遵循 README）：
  - 5.1 計算引擎輸出: {metric_id, metric_name, value, display_value, unit, period, source, validation_status}
  - 5.2 投影片規格: {slide_no, layout, title, headline, chart:{type, series_metric_ids}, insights:[{text, evidence_metric_ids}]}
  - 5.3 QA 報告: {status, errors:[{slide_no, type, message, expected}]}

模組位置：
  - src/agents/planner_agent.py
  - src/agents/analyst_agent.py
  - src/agents/reviewer_agent.py
  - prompts/system_prompt.md
  - prompts/slide_planner.md
  - prompts/insight_reviewer.md
  - schemas/metric.schema.json
  - schemas/slide_spec.schema.json
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
    total_pages: int = None,
):
    """
    獨立執行 Task 2。

    流程：
      1. 資料分類（判定情境、數據類型、分析主題）
      2. Planner Agent 規劃簡報結構
      3. Analyst Agent 生成策略洞察
      4. Reviewer Agent 品質審核
      5. 輸出 slide_spec.json + qa_report.json

    Args:
        data_summary: 資料摘要（None 則使用範例）
        use_llm: 是否使用 LLM
        output_dir: 輸出目錄
        total_pages: 使用者指定的頁數（None 表示未指定，預設 16）
    """
    pages = total_pages if total_pages is not None else 16

    print("=" * 70)
    print("  智匯數據簡報神器 — Task 2: LLM Agent 系統")
    print("  通用架構，資料驅動，無產業預設")
    print("=" * 70)

    if data_summary is None:
        data_summary = _default_data_summary()

    print(f"\n[設定] 主體數: {len(data_summary.get('institutions', []))}")
    print(f"[設定] 指標數: {len(data_summary.get('metrics', []))}")
    print(f"[設定] 期間數: {len(data_summary.get('periods', []))}")
    print(f"[設定] 頁數:   {pages} {'(使用者指定)' if total_pages is not None else '(預設)'}")
    print(f"[設定] LLM: {'啟用' if use_llm else '規則引擎'}")

    # ─── Step 1: 資料分類 ────────────────────────────────────────
    print("\n" + "─" * 60)
    print("[Step 1] 資料智慧分類")
    print("─" * 60)

    planner = PlannerAgent()
    classification = planner.classify_data(data_summary)

    print(f"  推測情境:   {classification['domain']}")
    print(f"  數據類型:   {classification['data_types']}")
    print(f"  分析主題:   {[t['name'] for t in classification['theme_groups']]}")
    print(f"  時間序列:   {classification['has_time_series']}")
    print(f"  橫截面:     {classification['has_cross_section']}")

    # ─── Step 2: 規劃簡報結構 ──────────────────────────────────
    print("\n" + "─" * 60)
    print(f"[Step 2] Planner Agent — {pages} 頁結構規劃")
    print("─" * 60)

    slide_specs = planner.plan_structure(data_summary, use_llm=use_llm, total_pages=total_pages)
    print(f"  產出 {len(slide_specs)} 頁\n")

    for s in slide_specs:
        print(f"    P{s['slide_no']:02d} | {s['layout']:<20s} | {s['title']}")

    # ─── Step 3: 生成洞察 ────────────────────────────────────────
    print("\n" + "─" * 60)
    print("[Step 3] Analyst Agent — 策略洞察生成")
    print("─" * 60)

    analyst = AnalystAgent()
    all_metric_data = _build_mock_metrics(slide_specs, data_summary)
    enriched_specs = analyst.generate_all_slides(slide_specs, all_metric_data, use_llm=use_llm)

    total_insights = sum(len(s.get("insights", [])) for s in enriched_specs)
    total_recs = sum(len(s.get("recommendations", [])) for s in enriched_specs)
    print(f"  洞察數: {total_insights}")
    print(f"  建議數: {total_recs}")

    print("\n  [洞察範例]")
    shown = 0
    for s in enriched_specs:
        for ins in s.get("insights", []):
            if shown >= 2:
                break
            print(f"    • {ins['text'][:70]}...")
            print(f"      evidence: {ins.get('evidence_metric_ids', [])[:2]}")
            shown += 1
        if shown >= 2:
            break

    # ─── Step 4: 品質審核 ────────────────────────────────────────
    print("\n" + "─" * 60)
    print("[Step 4] Reviewer Agent — 品質審核")
    print("─" * 60)

    reviewer = ReviewerAgent()
    verified = _build_verified_metrics(data_summary, enriched_specs)
    qa_result = reviewer.review(enriched_specs, verified, use_llm=False, expected_pages=pages)

    print(f"  Status: {qa_result['status'].upper()}")
    print(f"  Errors: {len(qa_result['errors'])}")
    if qa_result["errors"]:
        types = {}
        for e in qa_result["errors"]:
            types[e["type"]] = types.get(e["type"], 0) + 1
        print(f"  分類:  {types}")

    # ─── 輸出 ────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("[Output]")
    print("─" * 60)

    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "slide_spec.json"), "w", encoding="utf-8") as f:
        json.dump(enriched_specs, f, ensure_ascii=False, indent=2)
    print(f"  → {output_dir}/slide_spec.json")

    with open(os.path.join(output_dir, "qa_report.json"), "w", encoding="utf-8") as f:
        json.dump(qa_result, f, ensure_ascii=False, indent=2)
    print(f"  → {output_dir}/qa_report.json")

    with open(os.path.join(output_dir, "data_classification.json"), "w", encoding="utf-8") as f:
        json.dump(classification, f, ensure_ascii=False, indent=2)
    print(f"  → {output_dir}/data_classification.json")

    print("\n" + "=" * 70)
    print("  [Task 2] 完成")
    print("=" * 70)
    return enriched_specs, qa_result


def _default_data_summary() -> dict:
    """範例資料摘要 — 可替換為任何業務資料。"""
    return {
        "institutions": ["台新銀行", "中國信託", "國泰世華", "玉山銀行", "台北富邦",
                        "聯邦銀行", "永豐銀行", "第一銀行", "華南銀行", "彰化銀行"],
        "metrics": ["流通卡數", "有效卡數", "當月簽帳金額", "循環信用餘額",
                   "分期付款餘額", "逾期放款比率", "呆帳比率"],
        "periods": ["11401", "11402", "11403", "11404", "11405", "11406",
                   "11407", "11408", "11409", "11410", "11411", "11412"],
        "record_count": 840,
    }


def _build_mock_metrics(slides: list, data_summary: dict) -> dict:
    """模擬計算引擎結果（實際由 src/calculation_engine 提供）。"""
    metrics = data_summary.get("metrics", [])
    institutions = data_summary.get("institutions", [])
    periods = data_summary.get("periods", [])

    # 產出一組通用 mock metric 資料
    mock_pool = []
    for m in metrics:
        safe = m.replace(" ", "_")
        for p in periods[-3:]:
            mock_pool.append({"metric_id": f"{safe}_{p}", "metric_name": m, "value": 100, "unit": "", "period": p, "validation_status": "passed"})
    for inst in institutions[:10]:
        for m in metrics[:3]:
            safe_m = m.replace(" ", "_")
            safe_i = inst.replace(" ", "_")
            mock_pool.append({"metric_id": f"{safe_i}_{safe_m}", "metric_name": f"{inst}{m}", "value": 50, "unit": "", "period": periods[-1] if periods else "", "validation_status": "passed"})

    # 分配到各頁
    result = {}
    for s in slides:
        sno = s["slide_no"]
        chart = s.get("chart")
        if chart and isinstance(chart, dict):
            ids = set(chart.get("series_metric_ids", []))
            page_data = [m for m in mock_pool if m["metric_id"] in ids]
            result[sno] = page_data if page_data else mock_pool[:3]
        else:
            result[sno] = mock_pool[:2]
    return result


def _build_verified_metrics(data_summary: dict, slides: list) -> dict:
    """模擬 verified_metrics（實際由 validation 模組提供）。"""
    metrics = data_summary.get("metrics", [])
    institutions = data_summary.get("institutions", [])
    periods = data_summary.get("periods", [])
    verified = {}

    for m in metrics:
        safe = m.replace(" ", "_")
        for p in periods[-3:]:
            verified[f"{safe}_{p}"] = 100
    for inst in institutions[:10]:
        for m in metrics[:3]:
            verified[f"{inst.replace(' ', '_')}_{m.replace(' ', '_')}"] = 50
        verified[f"{inst.replace(' ', '_')}_scatter"] = 50

    # 加入所有在 slides 中引用的 id
    for s in slides:
        chart = s.get("chart")
        if chart and isinstance(chart, dict):
            for mid in chart.get("series_metric_ids", []):
                if mid not in verified:
                    verified[mid] = 50
        for ins in s.get("insights", []):
            for mid in ins.get("evidence_metric_ids", []):
                if mid not in verified:
                    verified[mid] = 50
        for mid in s.get("source_ids", []):
            if mid not in verified:
                verified[mid] = 50
        for kpi in s.get("kpis", []):
            mid = kpi.get("metric_id", "")
            if mid and mid not in verified:
                verified[mid] = 50

    return verified


if __name__ == "__main__":
    use_llm = "--llm" in sys.argv

    # 解析頁數參數
    total_pages = None
    for arg in sys.argv[1:]:
        if arg.startswith("--pages="):
            total_pages = int(arg.split("=")[1])

    if "--travel" in sys.argv:
        # 展示旅遊資料情境
        travel = {
            "institutions": ["日本", "韓國", "泰國", "越南", "新加坡",
                            "美國", "香港", "馬來西亞", "菲律賓", "印尼"],
            "metrics": ["旅客人次", "平均停留天數", "平均消費金額",
                       "住房率", "航班數", "回訪率"],
            "periods": ["11301", "11302", "11303", "11304", "11305", "11306",
                       "11307", "11308", "11309", "11310", "11311", "11312"],
            "record_count": 720,
        }
        run_task2(data_summary=travel, use_llm=use_llm, total_pages=total_pages)
    else:
        run_task2(use_llm=use_llm, total_pages=total_pages)
