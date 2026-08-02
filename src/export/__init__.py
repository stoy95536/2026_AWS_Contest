"""
同源輸出（TASK1.md 鐵律 13）：一份計算結果，三種序列化。

    AnalysisResult ─┬─→ analysis_result.json   metric + chart_data（成員 B、C）
                    ├─→ analysis_result.xlsx   與簡報同步的分析結果（評審）
                    └─→ data_lineage.json      數值回溯校驗（成員 D）

三份檔案不各算各的——圖表值就是 metric 值、Excel 只是同一份資料排進儲存格。
「chart_data、analysis_result.xlsx 與 metric JSON 三方一致」因此是結構上的
必然，不是靠事後比對維持的巧合。
"""

from .lineage_loader import load_chart_series, load_lineage_tracker, load_metrics
from .result import SCHEMA_VERSION, AnalysisResult, ChartSpec, format_display
from .writers import (
    write_all,
    write_analysis_excel,
    write_analysis_json,
    write_lineage_json,
)

__all__ = [
    "SCHEMA_VERSION",
    "AnalysisResult",
    "ChartSpec",
    "format_display",
    "load_chart_series",
    "load_lineage_tracker",
    "load_metrics",
    "write_all",
    "write_analysis_excel",
    "write_analysis_json",
    "write_lineage_json",
]