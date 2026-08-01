"""
A1 座標追蹤。

存在的理由：wide→long 的 `melt` 會把「第 5 列第 3 欄」這件事徹底洗掉，
melt 完只剩下值。一旦失去原始行列位置，`SourceRef` 就只能退化成
「日本@1964」這種偽座標——而偽座標無法讓人打開 Excel 逐格核對，
等於整個「可追溯」賣點是假的（TASK1.md 第 7 節）。

所以座標必須在 melt **之前**就綁上每一格，跟著值一路走到輸出。
"""

from __future__ import annotations

from dataclasses import dataclass

from openpyxl.utils import get_column_letter


def to_a1(row: int, col: int) -> str:
    """(1-indexed 列, 1-indexed 欄) → A1 表示法，如 (5, 3) → 'C5'。"""
    return f"{get_column_letter(col)}{row}"


def to_a1_range(row_start: int, col_start: int, row_end: int, col_end: int) -> str:
    """
    矩形範圍 → A1 範圍字串。

    單一儲存格時回傳單格表示（'C5' 而非 'C5:C5'），
    因為 SourceRef 兩種都收，單格形式對人比較好讀。
    """
    start = to_a1(row_start, col_start)
    if row_start == row_end and col_start == col_end:
        return start
    return f"{start}:{to_a1(row_end, col_end)}"


def column_range(col: int, row_start: int, row_end: int) -> str:
    """整欄某段列的範圍，如 C6:C67。這是最常用的血緣單位（一個欄位的資料區）。"""
    return to_a1_range(row_start, col, row_end, col)


@dataclass(frozen=True)
class CellRef:
    """
    單一儲存格的來源座標。

    綁在每一個 melt 後的資料點上，讓任何一個數字都能反查回原始位置。
    """

    sheet: str
    row: int
    col: int

    @property
    def a1(self) -> str:
        return to_a1(self.row, self.col)

    def __str__(self) -> str:
        return f"{self.sheet}!{self.a1}"


def span_of(refs: list[CellRef]) -> str:
    """
    一組儲存格的涵蓋範圍（外接矩形）。

    用於彙總型血緣：`group_sum` 加總了 C6:C67 這一整段，
    輸出的 metric 要指回整段而非某一格。

    注意這是**外接矩形**，不是精確的儲存格集合——若來源不連續，
    範圍會涵蓋到未參與計算的格子。彙總計算幾乎都是連續區段，
    但若日後出現不連續來源，需改為輸出多段 range。
    """
    if not refs:
        raise ValueError("span_of 需要至少一個 CellRef")
    return to_a1_range(
        min(r.row for r in refs),
        min(r.col for r in refs),
        max(r.row for r in refs),
        max(r.col for r in refs),
    )