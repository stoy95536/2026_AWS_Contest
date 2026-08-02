"""
統一 Pipeline — 整合 Task1 → Task2 → Task3 → QA 為單一入口。

流程：
  Excel 檔案目錄 → Task1 (catalog + 計算) → analysis_result.json
  analysis_result.json → Task2 (Agent 規劃 + 洞察) → slide_spec.json
  slide_spec.json + 模板 → Task3 (PPT 生成) → final_presentation.pptx

網頁前端只需呼叫：
    from src.unified_pipeline import run_pipeline
    result = run_pipeline(excel_dir, template_path, prompt, use_llm)
"""

import json
import os
import time
import shutil
import warnings
from pathlib import Path
from typing import Optional

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
    model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
    region: str = "us-east-1",
) -> dict:
    """
    統一端到端 Pipeline。

    Args:
        excel_dir: Excel 檔案所在目錄（可含多個 .xlsx/.xls）
        template_path: PPT 模板路徑（選填）
        prompt: 使用者提示詞（選填）
        output_dir: 輸出目錄
        use_llm: 是否使用 LLM
        target_institution: 目標分析機構
        model_id: Bedrock 模型 ID
        region: AWS region

    Returns:
        {
            "success": bool,
            "duration": float,
            "ppt_path": str,
            "excel_path": str,
            "lineage_path": str,
            "slide_spec_path": str,
            "qa_report_path": str,
            "errors": [str],
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
    }

    try:
        # ══════════════════════════════════════════════════════════
        # STAGE 1: Task1 — Excel 解析 + 指標計算
        # ══════════════════════════════════════════════════════════
        print("[Pipeline] Stage 1: Task1 — Excel → 指標計算")
        from Task1.run_task1 import run as run_task1

        analysis_result = run_task1(
            data_dir=excel_dir,
            output_dir=output_dir,
            prompt=prompt,
            use_llm=use_llm,
        )
        analysis_json_path = os.path.join(output_dir, "analysis_result.json")
        print(f"  ✓ 產出: {analysis_json_path}")

        # ══════════════════════════════════════════════════════════
        # STAGE 2: Task2 — Agent 規劃結構 + 洞察生成
        # ══════════════════════════════════════════════════════════
        print("\n[Pipeline] Stage 2: Task2 — Agent 規劃 + 洞察")
        from Task2.Agent_Part import run_task2_from_task1

        enriched_specs, qa_report = run_task2_from_task1(
            analysis_result_path=analysis_json_path,
            use_llm=use_llm,
            output_dir=output_dir,
        )

        slide_spec_path = os.path.join(output_dir, "slide_spec.json")
        qa_report_path = os.path.join(output_dir, "qa_report.json")
        print(f"  ✓ 產出: {slide_spec_path}")

        # ══════════════════════════════════════════════════════════
        # STAGE 3: Task3 — PPT 生成
        # ══════════════════════════════════════════════════════════
        print("\n[Pipeline] Stage 3: Task3 — PPT 生成")
        from src.presentation import PPTGenerator

        ppt_output = os.path.join(output_dir, "final_presentation.pptx")
        generator = PPTGenerator(template_path)
        generator.generate(enriched_specs, ppt_output)
        print(f"  ✓ 產出: {ppt_output}")

        # 填入結果
        result["success"] = True
        result["ppt_path"] = ppt_output
        result["excel_path"] = os.path.join(output_dir, "analysis_result.xlsx")
        result["lineage_path"] = os.path.join(output_dir, "data_lineage.json")
        result["slide_spec_path"] = slide_spec_path
        result["qa_report_path"] = qa_report_path

    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
        print(f"\n[Pipeline] 錯誤: {e}")

    result["duration"] = time.time() - start
    print(f"\n[Pipeline] {'完成' if result['success'] else '失敗'} ({result['duration']:.1f}s)")
    return result


def run_pipeline_from_files(
    excel_files: list[str],
    template_path: Optional[str] = None,
    prompt: Optional[str] = None,
    output_dir: str = "outputs",
    use_llm: bool = True,
    target_institution: str = "台新銀行",
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
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="統一 Pipeline")
    parser.add_argument("--data", required=True, help="Excel 檔案目錄")
    parser.add_argument("--template", default=None, help="PPT 模板")
    parser.add_argument("--prompt", default=None, help="分析提示詞")
    parser.add_argument("--output", default="outputs", help="輸出目錄")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    run_pipeline(
        excel_dir=args.data,
        template_path=args.template,
        prompt=args.prompt,
        output_dir=args.output,
        use_llm=not args.no_llm,
    )
