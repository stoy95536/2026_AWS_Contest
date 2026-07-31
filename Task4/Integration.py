"""
Task 4: 數值回溯 QA、系統整合、部署與 Live Demo
主要功能模組位於:
  - src/pipeline.py                     — 端到端 Pipeline
  - src/validation/ppt_reconciler.py    — 簡報數值回溯校驗
  - app/api/server.py                   — Web Demo API
  - app/web/index.html                  — Web Demo 前端
  - deployment/                         — Docker 部署設定

本檔為 Task 4 獨立執行入口，整合前三個 Task 的完整流程。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline import Pipeline, PipelineConfig


def run_task4(
    excel_path: str = None,
    template_path: str = None,
    output_dir: str = "outputs",
    use_llm: bool = False,
):
    """
    獨立執行 Task 4: 完整端到端系統。

    Args:
        excel_path: Excel 檔案路徑
        template_path: 模板路徑
        output_dir: 輸出目錄
        use_llm: 是否使用 LLM
    """
    print("[Task 4] 端到端整合測試...")
    print("=" * 50)

    if excel_path is None:
        print("[Task 4] 未提供 Excel 檔案，執行模組整合檢查...")
        _check_module_integration()
        return

    # 執行完整 Pipeline
    config = PipelineConfig(
        excel_path=excel_path,
        template_path=template_path,
        output_dir=output_dir,
        use_llm=use_llm,
    )

    pipeline = Pipeline(config)
    result = pipeline.run()

    # 報告結果
    print("\n" + "=" * 50)
    print("[Task 4] 結果報告:")
    print(f"  成功: {result.success}")
    print(f"  耗時: {result.duration_seconds:.1f} 秒")
    print(f"  步驟: {result.steps_completed}")

    if result.errors:
        print(f"  錯誤:")
        for err in result.errors:
            print(f"    - {err}")

    if result.ppt_path:
        print(f"\n  輸出檔案:")
        print(f"    PPT:     {result.ppt_path}")
        print(f"    Excel:   {result.excel_path}")
        print(f"    Lineage: {result.lineage_path}")
        print(f"    QA:      {result.qa_report_path}")

    print("=" * 50)
    return result


def _check_module_integration():
    """檢查所有模組是否可正確匯入。"""
    checks = []

    try:
        from src.data_loader import ExcelLoader, DataStandardizer
        checks.append(("Task 1 - Data Loader", True))
    except ImportError as e:
        checks.append(("Task 1 - Data Loader", False, str(e)))

    try:
        from src.calculation_engine import MetricCalculator, DataLineageTracker
        checks.append(("Task 1 - Calculation Engine", True))
    except ImportError as e:
        checks.append(("Task 1 - Calculation Engine", False, str(e)))

    try:
        from src.validation import DataValidator
        checks.append(("Task 1 - Validator", True))
    except ImportError as e:
        checks.append(("Task 1 - Validator", False, str(e)))

    try:
        from src.agents import PlannerAgent, AnalystAgent, ReviewerAgent
        checks.append(("Task 2 - Agents", True))
    except ImportError as e:
        checks.append(("Task 2 - Agents", False, str(e)))

    try:
        from src.presentation import TemplateParser, ChartFactory, PPTGenerator
        checks.append(("Task 3 - Presentation", True))
    except ImportError as e:
        checks.append(("Task 3 - Presentation", False, str(e)))

    try:
        from src.pipeline import Pipeline, PipelineConfig
        checks.append(("Task 4 - Pipeline", True))
    except ImportError as e:
        checks.append(("Task 4 - Pipeline", False, str(e)))

    try:
        from src.validation.ppt_reconciler import PPTReconciler
        checks.append(("Task 4 - Reconciler", True))
    except ImportError as e:
        checks.append(("Task 4 - Reconciler", False, str(e)))

    print("\n模組整合檢查:")
    all_pass = True
    for check in checks:
        name = check[0]
        passed = check[1]
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            print(f"         {check[2]}")
            all_pass = False

    print(f"\n結果: {'全部通過' if all_pass else '有模組未通過'}")
    return all_pass


def start_web_demo():
    """啟動 Web Demo 伺服器。"""
    print("[Task 4] 啟動 Web Demo...")
    print("  URL: http://localhost:8000")
    print("  按 Ctrl+C 停止")
    import uvicorn
    uvicorn.run("app.api.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    if "--web" in sys.argv:
        start_web_demo()
    elif "--excel" in sys.argv:
        idx = sys.argv.index("--excel")
        excel = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        use_llm = "--llm" in sys.argv
        run_task4(excel_path=excel, use_llm=use_llm)
    else:
        run_task4()
