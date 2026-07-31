"""
Task 1: Excel 資料解析、指標計算與資料血緣
主要功能模組位於:
  - src/data_loader/excel_loader.py      — Excel 讀取
  - src/data_loader/data_standardizer.py — 資料標準化
  - src/calculation_engine/metrics.py    — 指標計算引擎
  - src/calculation_engine/data_lineage.py — 資料血緣追蹤
  - src/validation/data_validator.py     — 資料驗證

本檔為 Task 1 獨立執行入口，可單獨測試 Excel 解析流程。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_loader import ExcelLoader, DataStandardizer
from src.calculation_engine import MetricCalculator, DataLineageTracker
from src.validation import DataValidator


def run_task1(excel_path: str, output_dir: str = "outputs"):
    """
    獨立執行 Task 1: Excel 解析 + 指標計算 + 資料血緣。

    Args:
        excel_path: Excel 檔案路徑
        output_dir: 輸出目錄
    """
    print("[Task 1] 開始 Excel 資料解析...")

    # Step 1: 載入 Excel
    loader = ExcelLoader(excel_path)
    print(f"  工作表: {loader.get_sheet_names()}")

    # Step 2: 資料標準化
    standardizer = DataStandardizer(excel_path)
    for sheet_name in loader.get_sheet_names():
        try:
            header_row = loader.detect_header_row(sheet_name)
            df = loader.read_sheet_to_dataframe(sheet_name, header_row=header_row)
            if not df.empty:
                records = standardizer.standardize_dataframe(df, sheet_name)
                print(f"  {sheet_name}: {len(records)} 筆記錄")
        except Exception as e:
            print(f"  [Warning] {sheet_name}: {e}")

    loader.close()
    std_data = standardizer.to_dataframe()
    print(f"  標準化總筆數: {len(std_data)}")

    # Step 3: 資料驗證
    print("[Task 1] 資料驗證...")
    validator = DataValidator(std_data)
    issues = validator.validate_all()
    summary = validator.get_validation_summary()
    print(f"  驗證結果: {summary['errors']} 錯誤, {summary['warnings']} 警告")

    # Step 4: 指標計算
    print("[Task 1] 指標計算...")
    lineage = DataLineageTracker()
    calculator = MetricCalculator(std_data, lineage)

    institutions = calculator.get_all_institutions()
    periods = calculator.get_all_periods()
    metrics = calculator.get_all_metrics()

    print(f"  機構數: {len(institutions)}")
    print(f"  期間數: {len(periods)}")
    print(f"  指標數: {len(metrics)}")

    if periods:
        latest = periods[-1]
        for inst in institutions:
            calculator.effective_card_rate(inst, latest)
            calculator.avg_purchase_per_card(inst, latest)
            for m in ["流通卡數", "當月簽帳金額"]:
                calculator.market_share(inst, latest, m)

    # Step 5: 匯出
    os.makedirs(output_dir, exist_ok=True)

    excel_output = os.path.join(output_dir, "analysis_result.xlsx")
    std_data.to_excel(excel_output, index=False, engine="openpyxl")
    print(f"  匯出: {excel_output}")

    lineage_output = os.path.join(output_dir, "data_lineage.json")
    lineage.export_json(lineage_output)
    print(f"  匯出: {lineage_output}")

    print("[Task 1] 完成!")
    return calculator, lineage


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python Task1/Excel_Process.py <excel_path>")
        sys.exit(1)
    run_task1(sys.argv[1])
