"""
Catalog Builder：Stage 1 資料目錄建置（一次性、離線，與 Prompt 無關）。

把領域未知的多份 Excel 解析成統一的長格式 + 資料目錄，讓 Stage 2 的 LLM
只讀精簡 Catalog 就能組合積木，不必讀原始 Excel。

模組職責（TASK1.md 1a-2）：
  structure_detector — 動態偵測標題/多層表頭/資料區，合併儲存格填平
  normalizer         — wide→long、年度字串正規化、異常值標記
  cell_tracker       — A1 座標追蹤，確保 melt 後仍可回溯原始儲存格
"""

from .cell_tracker import CellRef, column_range, span_of, to_a1, to_a1_range
from .structure_detector import ColumnInfo, SheetStructure, detect_structure

__all__ = [
    "CellRef",
    "ColumnInfo",
    "SheetStructure",
    "column_range",
    "detect_structure",
    "span_of",
    "to_a1",
    "to_a1_range",
]