"""
LLM 驅動之 Excel 報表轉簡報自動化系統
主程式入口 — 端到端 Pipeline 執行

用法:
    python main.py --excel <excel_path> [--template <pptx_path>] [--output <output_dir>] [--no-llm]
"""

import argparse
import os
import sys

from src.pipeline import Pipeline, PipelineConfig


def parse_args():
    """解析命令列參數。"""
    parser = argparse.ArgumentParser(
        description="LLM 驅動之 Excel 報表轉簡報自動化系統",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python main.py --excel data/credit_card_stats.xlsx
  python main.py --excel data/stats.xlsx --template templates/taishin_template.pptx
  python main.py --excel data/stats.xlsx --no-llm --output results/
        """,
    )
    parser.add_argument("--excel", required=True, help="信用卡業務統計 Excel 檔案路徑")
    parser.add_argument("--template", default=None, help="PowerPoint 模板路徑")
    parser.add_argument("--output", default="outputs", help="輸出目錄 (預設: outputs/)")
    parser.add_argument("--no-llm", action="store_true", help="不使用 LLM（僅規則引擎）")
    parser.add_argument("--model", default="anthropic.claude-sonnet-4-20250514-v1:0", help="Bedrock 模型 ID")
    parser.add_argument("--region", default="us-east-1", help="AWS Region")
    parser.add_argument("--institution", default="台新銀行", help="目標分析機構")
    return parser.parse_args()


def main():
    """主程式。"""
    args = parse_args()

    # 驗證輸入檔案
    if not os.path.exists(args.excel):
        print(f"[Error] Excel 檔案不存在: {args.excel}")
        sys.exit(1)

    if args.template and not os.path.exists(args.template):
        print(f"[Error] 模板檔案不存在: {args.template}")
        sys.exit(1)

    print("=" * 60)
    print("  LLM 驅動之 Excel 報表轉簡報自動化系統")
    print("=" * 60)
    print(f"  Excel:       {args.excel}")
    print(f"  Template:    {args.template or '(使用預設)'}")
    print(f"  Output:      {args.output}")
    print(f"  Use LLM:     {not args.no_llm}")
    print(f"  Model:       {args.model}")
    print(f"  Institution: {args.institution}")
    print("=" * 60)

    # 建立 Pipeline 設定
    config = PipelineConfig(
        excel_path=args.excel,
        template_path=args.template,
        output_dir=args.output,
        use_llm=not args.no_llm,
        model_id=args.model,
        region=args.region,
        target_institution=args.institution,
    )

    # 執行 Pipeline
    pipeline = Pipeline(config)
    result = pipeline.run()

    # 輸出結果
    print("\n" + "=" * 60)
    if result.success:
        print("  Pipeline 執行成功!")
        print(f"  耗時: {result.duration_seconds:.1f} 秒")
        print(f"  完成步驟: {len(result.steps_completed)}")
        print(f"\n  輸出檔案:")
        if result.ppt_path:
            print(f"    - 簡報: {result.ppt_path}")
        if result.excel_path:
            print(f"    - Excel: {result.excel_path}")
        if result.lineage_path:
            print(f"    - 血緣: {result.lineage_path}")
        if result.qa_report_path:
            print(f"    - QA:   {result.qa_report_path}")
        if result.slide_spec_path:
            print(f"    - Spec: {result.slide_spec_path}")
    else:
        print("  Pipeline 執行失敗!")
        for err in result.errors:
            print(f"  Error: {err}")
    print("=" * 60)

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
