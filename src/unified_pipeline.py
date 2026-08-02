"""
統一 Pipeline — 整合 Task1 → Task2 → Task3 為單一入口。

流程：
  Excel 檔案目錄 → Task1 (catalog + 積木計算) → analysis_result.json
  analysis_result.json → Task2 (三 Agent: Planner + Analyst + Reviewer) → slide_spec.json + qa_report.json
  slide_spec.json + 模板 → Task3 (PPT 生成) → final_presentation.pptx

網頁前端只需呼叫：
    from src.unified_pipeline import run_pipeline_from_files
    result = run_pipeline_from_files(excel_files, template_path, prompt, ...)
"""

import json
import os
import shutil
import sys
import time
import warnings
from pathlib import Path
from typing import Optional

# 確保專案根目錄在 sys.path 中
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(override=True)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


def run_pipeline(
    excel_dir: str,
    template_path: Optional[str] = None,
    prompt: Optional[str] = None,
    output_dir: str = "outputs",
    use_llm: bool = True,
    target_institution: str = "台新銀行",
    total_pages: int = 16,
    model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
    region: str = "us-east-1",
) -> dict:
    """
    統一端到端 Pipeline。

    Args:
        excel_dir: Excel 檔案所在目錄（可含多個 .xlsx/.xls/.csv）
        template_path: PPT 模板路徑（選填）
        prompt: 使用者提示詞（選填，影響 Task1 指標選擇與 Task2 章節規劃）
        output_dir: 輸出目錄
        use_llm: 是否使用 LLM（False 則全程走規則引擎）
        target_institution: 目標分析機構
        total_pages: 簡報頁數（預設 16）
        model_id: Bedrock 模型 ID
        region: AWS region

    Returns:
        {
            "success": bool,
            "duration": float,
            "ppt_path": str | None,
            "excel_path": str | None,
            "lineage_path": str | None,
            "slide_spec_path": str | None,
            "qa_report_path": str | None,
            "errors": [str],
            "metrics_count": int,
            "charts_count": int,
            "insights_count": int,
        }
    """
    start = time.time()
    os.makedirs(output_dir, exist_ok=True)
    errors = []

    result = {
        "success": False,
        "duration": 0,
        "ppt_path": None,
        "excel_path": None,
        "lineage_path": None,
        "slide_spec_path": None,
        "qa_report_path": None,
        "errors": errors,
        "metrics_count": 0,
        "charts_count": 0,
        "insights_count": 0,
    }

    try:
        # ══════════════════════════════════════════════════════════════
        # STAGE 1: Task1 — Excel 解析 + Data Catalog + 積木計算
        # ══════════════════════════════════════════════════════════════
        print("=" * 68)
        print("[Pipeline] Stage 1: Task1 — Excel → Data Catalog → 積木計算")
        print("=" * 68)

        from Task1.run_task1 import run as run_task1

        analysis_result = run_task1(
            data_dir=excel_dir,
            output_dir=output_dir,
            prompt=prompt,
            use_llm=use_llm,
        )

        analysis_json_path = os.path.join(output_dir, "analysis_result.json")
        if not os.path.exists(analysis_json_path):
            raise FileNotFoundError(
                f"Task1 未產出 analysis_result.json: {analysis_json_path}"
            )

        # 讀取 Task1 輸出的統計
        with open(analysis_json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        metrics_count = len(payload.get("metrics", []))
        charts_count = len(payload.get("chart_data", []))
        result["metrics_count"] = metrics_count
        result["charts_count"] = charts_count
        print(f"\n  ✓ Stage 1 完成：{metrics_count} 指標、{charts_count} 圖表")

        # ══════════════════════════════════════════════════════════════
        # STAGE 2: Task2 — 三 Agent (Planner → Analyst → Reviewer)
        # ══════════════════════════════════════════════════════════════
        print("\n" + "=" * 68)
        print("[Pipeline] Stage 2: Task2 — Agent 規劃 + 洞察 + 品質審核")
        print("=" * 68)

        from Task2.Agent_Part import run_task2_from_task1

        enriched_specs, qa_result = run_task2_from_task1(
            analysis_result_path=analysis_json_path,
            use_llm=use_llm,
            output_dir=output_dir,
            total_pages=total_pages,
        )

        slide_spec_path = os.path.join(output_dir, "slide_spec.json")
        qa_report_path = os.path.join(output_dir, "qa_report.json")

        insights_count = sum(len(s.get("insights", [])) for s in enriched_specs)
        result["insights_count"] = insights_count
        print(f"\n  ✓ Stage 2 完成：{len(enriched_specs)} 頁、{insights_count} 洞察")

        # 檢查 QA 是否有阻斷性錯誤
        blocking_errors = [
            e for e in qa_result.get("errors", [])
            if e.get("type") not in ("weak_insight",)
        ]
        if blocking_errors:
            print(f"  ⚠ QA 發現 {len(blocking_errors)} 個問題（非阻斷，繼續生成）")

        # ══════════════════════════════════════════════════════════════
        # STAGE 3: Task3 — PPT 生成
        # ══════════════════════════════════════════════════════════════
        print("\n" + "=" * 68)
        print("[Pipeline] Stage 3: Task3 — PPT 生成")
        print("=" * 68)

        from src.presentation import PPTGenerator

        ppt_output = os.path.join(output_dir, "final_presentation.pptx")
        generator = PPTGenerator(template_path)
        generator.generate(enriched_specs, ppt_output)
        print(f"\n  ✓ Stage 3 完成：{ppt_output}")

        # ══════════════════════════════════════════════════════════════
        # 完成
        # ══════════════════════════════════════════════════════════════
        result["success"] = True
        result["ppt_path"] = ppt_output
        result["excel_path"] = os.path.join(output_dir, "analysis_result.xlsx")
        result["lineage_path"] = os.path.join(output_dir, "data_lineage.json")
        result["slide_spec_path"] = slide_spec_path
        result["qa_report_path"] = qa_report_path

    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        print(f"\n[Pipeline] 錯誤: {e}")

    result["duration"] = time.time() - start
    result["errors"] = errors

    print("\n" + "=" * 68)
    if result["success"]:
        print(f"[Pipeline] 完成 ({result['duration']:.1f}s)")
        print(f"  指標: {result['metrics_count']}")
        print(f"  圖表: {result['charts_count']}")
        print(f"  洞察: {result['insights_count']}")
        print(f"  PPT:  {result['ppt_path']}")
    else:
        print(f"[Pipeline] 失敗 ({result['duration']:.1f}s)")
        for err in errors:
            print(f"  Error: {err}")
    print("=" * 68)

    return result


def run_pipeline_from_files(
    excel_files: list[str],
    template_path: Optional[str] = None,
    prompt: Optional[str] = None,
    output_dir: str = "outputs",
    use_llm: bool = True,
    target_institution: str = "台新銀行",
    total_pages: int = 16,
) -> dict:
    """
    從多個 Excel 檔案執行 Pipeline（網頁前端用）。
    會自動將多個檔案複製到暫存目錄後統一處理。

    Args:
        excel_files: Excel 檔案路徑清單
        其他參數同 run_pipeline
    """
    # 建暫存目錄，把所有 Excel 複製進去
    data_dir = os.path.join(output_dir, "_data")
    os.makedirs(data_dir, exist_ok=True)

    for f in excel_files:
        if os.path.exists(f):
            shutil.copy2(f, data_dir)

    return run_pipeline(
        excel_dir=data_dir,
        template_path=template_path,
        prompt=prompt,
        output_dir=output_dir,
        use_llm=use_llm,
        target_institution=target_institution,
        total_pages=total_pages,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="統一 Pipeline (Task1 → Task2 → Task3)")
    parser.add_argument("--data", required=True, help="Excel 檔案目錄")
    parser.add_argument("--template", default=None, help="PPT 模板路徑")
    parser.add_argument("--prompt", default=None, help="分析提示詞")
    parser.add_argument("--output", default="outputs", help="輸出目錄")
    parser.add_argument("--pages", type=int, default=16, help="簡報頁數 (預設 16)")
    parser.add_argument("--no-llm", action="store_true", help="停用 LLM")
    args = parser.parse_args()

    run_pipeline(
        excel_dir=args.data,
        template_path=args.template,
        prompt=args.prompt,
        output_dir=args.output,
        use_llm=not args.no_llm,
        total_pages=args.pages,
    )
