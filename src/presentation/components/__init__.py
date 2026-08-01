"""
頁面元件模組
每個 builder 負責填充特定類型的投影片內容區域。
"""

from .executive_summary import fill_executive_summary
from .toc import fill_toc
from .strategy import fill_strategy
from .chart_page import fill_chart
from .table_page import fill_table
from .insights_only import fill_insights_only

__all__ = [
    "fill_executive_summary",
    "fill_toc",
    "fill_strategy",
    "fill_chart",
    "fill_table",
    "fill_insights_only",
]
