"""
結構正規化：wide→long、年度字串正規化、異常值分類。

積木庫（`group_sum(group_col, value_col)`）預期吃長表，但政府統計報表一律是
寬表（年度為列、國家/年齡層/交通工具為欄）。這一步必須在程式端做完，
不能丟給 LLM 現場臨機應變（TASK1.md 1a-2）。

三個實測得到的設計決定（依據 Task1/recon/structure_report.md）：

1. **期間欄要靠「值」認，不能靠「表頭」認**。表2-2 的 A 欄裝的是年度，
   表頭卻寫「首站抵達地 First Destination」——那是在描述其他欄位是什麼，
   不是描述 A 欄自己。信表頭就會把年度整欄當成維度欄。

2. **年度字串有兩種格式**：「53年1964」（無空格）與「66 年 1977」（有空格），
   民國與西元同格並存。抽尾端西元四位數即可，不需要換算民國年。

3. **負數必須分兩類，不可一律標記**。實測有 `O5=-547`（人次類整數）
   與 `D8=-11.759259`（成長率小數）兩種。TASK1.md 原本寫「發現負數即標記」
   會把一整票正常的負成長率誤標成待覆核，把真正的問題淹沒。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .cell_tracker import CellRef, column_range, to_a1
from .structure_detector import (
    ColumnInfo,
    SheetStructure,
    looks_like_period_header,
    normalize_period_code,
)

# 「53年1964」「66 年 1977」「民國106年 2017」→ 取尾端西元四位數
_AD_IN_MIXED = re.compile(r"(1[89]\d{2}|2[01]\d{2})\s*$")
# 純民國年：「106年」「53 年」
_ROC_ONLY = re.compile(r"^(?:民國)?\s*(\d{1,3})\s*年\s*$")

ROC_EPOCH_OFFSET = 1911
"""民國元年 = 西元 1912 年，故西元 = 民國 + 1911。"""

AD_YEAR_MIN, AD_YEAR_MAX = 1900, 2100
"""合理西元年範圍。超出此範圍的四位數多半是金額或人次，不是年份。"""

PERIOD_MATCH_RATIO = 0.7
"""某欄有此比例以上的資料格可解析成年份，即判定為期間欄。

留 30% 餘裕給註腳列、合計列、缺值列——實測每份檔案底部都有雜訊列。"""

PERCENT_ABS_LIMIT = 100.0
"""百分比欄的絕對值上限。用於區分「負成長率」與「異常負人次」。"""

# 表頭出現這些字樣即視為比率欄，負值屬正常
_RATIO_KEYWORDS = ("%", "百分比", "比率", "佔比", "占比", "成長率", "增率", "rate", "ratio", "share")


class ColumnKind(str, Enum):
    """欄位在長表中扮演的角色。"""

    PERIOD = "period"
    """期間欄（年度），melt 時作為 id 欄保留。"""

    LABEL = "label"
    """文字標籤欄，資料區幾乎沒有數值（如表1-3 的「國籍 Nationality」空欄）。"""

    MEASURE = "measure"
    """數值欄，melt 時被攤平成「維度 + 值」。"""

    EMPTY = "empty"
    """整欄無資料或無表頭，略過。"""


def normalize_year(value: Any) -> int | None:
    """
    把儲存格值正規化成西元年。

    支援：「53年1964」「66 年 1977」「2017」「民國106年」、以及純數字 1964。
    無法解析時回傳 None，**絕不猜測**——猜錯年份會讓整個時間序列靜默錯位。
    """
    if value is None:
        return None

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        year = int(value)
        return year if AD_YEAR_MIN <= year <= AD_YEAR_MAX else None

    text = " ".join(str(value).split())
    if not text:
        return None

    # 民國+西元並存時，西元在尾端，直接取用，不必換算
    if m := _AD_IN_MIXED.search(text):
        return int(m.group(1))

    # 只有民國年時才換算
    if m := _ROC_ONLY.match(text):
        year = int(m.group(1)) + ROC_EPOCH_OFFSET
        return year if AD_YEAR_MIN <= year <= AD_YEAR_MAX else None

    return None


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _column_values(structure: SheetStructure, col: int) -> list[Any]:
    """取出某欄在資料區（不含表頭、不含註腳）的所有值。"""
    if structure.data_start_row is None or structure.data_end_row is None:
        return []
    return [
        structure.cell(r, col)
        for r in range(structure.data_start_row, structure.data_end_row + 1)
    ]


def detect_period_column(structure: SheetStructure) -> int | None:
    """
    找出期間欄——靠值判斷，不靠表頭。

    多欄符合時取最左邊那欄：政府報表的年度一律在最左，
    而右側若有其他四位數欄（如某年基準值）通常是量值不是期間。
    """
    for col in range(1, structure.max_column + 1):
        values = [v for v in _column_values(structure, col) if v is not None]
        if not values:
            continue
        parsed = sum(1 for v in values if normalize_year(v) is not None)
        if parsed / len(values) >= PERIOD_MATCH_RATIO:
            return col
    return None


def detect_period_header_columns(structure: SheetStructure) -> dict[int, int]:
    """
    找出「表頭本身就是期間代碼」的欄位，回傳 {欄號: 西元年}。

    這是與旅遊報表相反的版面：

        旅遊（年度為列）  年度 | 日本 | 韓國 …           期間在**欄裡**
        財報（期間為欄）  金融機構名稱 | 11401 | 11402 …   期間在**欄名上**

    兩種都很常見，只支援一種會讓另一種靜默產出 0 筆——實測附件四（信用卡）
    在支援轉置之前正是 0 筆，而且不拋任何例外。
    """
    return {
        column.index: year
        for column in structure.columns
        if (year := normalize_period_code(column.leaf_name)) is not None
    }


def _entity_column(structure: SheetStructure, period_cols: set[int]) -> int | None:
    """
    轉置版面中，哪一欄裝的是實體名稱（機構、國家、類別）。

    取第一個「文字為主」的欄位——政府報表與財報的慣例是實體名稱放最左邊。
    """
    for column in structure.columns:
        if column.index in period_cols:
            continue
        values = [v for v in _column_values(structure, column.index) if v is not None]
        if not values:
            continue
        if sum(1 for v in values if not _is_number(v)) / len(values) > 0.5:
            return column.index
    return None


def _normalize_transposed(
    structure: SheetStructure, result: "NormalizedSheet", period_cols: dict[int, int]
) -> None:
    """
    轉置版面的攤平：一列一個實體、一欄一個期間。

    產出的長表與正常版面完全相同（period / dimension / value / A1 座標），
    因此積木、執行引擎、輸出層一行都不用改——差異被侷限在這裡。
    """
    entity_col = _entity_column(structure, set(period_cols))
    if entity_col is None:
        result.warnings.append("期間在欄名上，但找不到實體名稱欄，無法攤平")
        return

    measure = structure.column_by_index(min(period_cols))
    metric_name = structure.sheet_name

    for row in range(structure.data_start_row, structure.data_end_row + 1):
        entity = structure.cell(row, entity_col)
        if entity is None or _is_number(entity):
            continue
        entity_name = " ".join(str(entity).split())
        if not entity_name:
            continue

        # 實體名稱即維度；量測概念來自工作表名稱（如「P.5預期修正_流通卡數」）
        dimension = entity_name
        cols = sorted(period_cols)
        result.column_ranges.setdefault(
            dimension,
            f"{to_a1(row, cols[0])}:{to_a1(row, cols[-1])}",
        )

        for col in cols:
            value = structure.cell(row, col)
            if value is None or not _is_number(value):
                continue
            record = LongRecord(
                period=period_cols[col],
                dimension=dimension,
                value=float(value),
                cell=CellRef(sheet=structure.sheet_name, row=row, col=col),
            )
            if value < 0:
                record.is_anomalous = True
                record.anomaly_reason = (
                    f"量值出現負數 {value}，疑似小計調整或缺值標記"
                )
            result.records.append(record)

        result.measure_columns.append(
            ColumnInfo(index=row, letter=to_a1(row, cols[0])[:-len(str(row))], layers=[dimension])
        )

    result.warnings.append(
        f"版面為「期間在欄名」，已轉置攤平；量測概念取自工作表名稱「{metric_name}」，"
        f"同一年度的多個月份已併入該年度"
    )


def _looks_like_ratio(column: ColumnInfo, values: list[float]) -> bool:
    """
    此欄是否為比率／百分比欄。

    先看表頭關鍵字（最可靠），表頭沒寫時退回值域判斷：
    比率欄的值全部落在 ±100 且含小數。
    """
    name = column.full_name.lower()
    if any(k in name for k in _RATIO_KEYWORDS):
        return True
    if not values:
        return False
    within_range = all(abs(v) <= PERCENT_ABS_LIMIT for v in values)
    has_fraction = any(v != int(v) for v in values)
    return within_range and has_fraction


def classify_column(structure: SheetStructure, column: ColumnInfo, period_col: int | None) -> ColumnKind:
    """判定欄位角色。"""
    if column.is_empty:
        return ColumnKind.EMPTY
    if period_col is not None and column.index == period_col:
        return ColumnKind.PERIOD

    values = [v for v in _column_values(structure, column.index) if v is not None]
    if not values:
        return ColumnKind.EMPTY

    numeric = [v for v in values if _is_number(v)]
    # 過半是數字才算量值欄；否則是文字標籤欄（如全空的「國籍」欄）
    return ColumnKind.MEASURE if len(numeric) / len(values) > 0.5 else ColumnKind.LABEL


@dataclass
class LongRecord:
    """
    長表的一列：一個數值 + 它的完整血緣座標。

    `cell` 是本模組存在的理由——melt 之後仍能回答「這個 22733 是從哪一格來的」。
    """

    period: int | None
    dimension: str
    value: float | None
    cell: CellRef
    is_anomalous: bool = False
    anomaly_reason: str | None = None


@dataclass
class NormalizedSheet:
    """一張工作表正規化後的結果。"""

    file_name: str
    sheet_name: str
    period_column: int | None
    records: list[LongRecord] = field(default_factory=list)
    measure_columns: list[ColumnInfo] = field(default_factory=list)
    column_ranges: dict[str, str] = field(default_factory=dict)
    """維度名 → 該欄資料區的 A1 範圍（如 'C5:C66'），供 Catalog 的 cell_range 使用。"""

    warnings: list[str] = field(default_factory=list)

    @property
    def anomalies(self) -> list[LongRecord]:
        """需人工覆核的異常值（非阻斷，只標記）。"""
        return [r for r in self.records if r.is_anomalous]


def normalize_sheet(structure: SheetStructure, file_name: str) -> NormalizedSheet:
    """
    把偵測完結構的工作表攤平成長表。

    每個數值都綁上 `CellRef`，melt 不會洗掉來源座標。
    """
    result = NormalizedSheet(
        file_name=file_name,
        sheet_name=structure.sheet_name,
        period_column=None,
    )

    if not structure.is_parsable:
        result.warnings.append("結構偵測失敗，略過正規化")
        return result

    # 先判斷版面方向：期間在欄名上時走轉置路徑
    period_header_cols = detect_period_header_columns(structure)
    if len(period_header_cols) >= 3:
        _normalize_transposed(structure, result, period_header_cols)
        return result

    period_col = detect_period_column(structure)
    result.period_column = period_col
    if period_col is None:
        result.warnings.append(
            "找不到期間欄（無任何一欄有 70% 以上的值可解析成年份），"
            "此表資料仍會攤平，但 period 全為 None，無法做時間序列計算"
        )

    for column in structure.columns:
        kind = classify_column(structure, column, period_col)
        if kind is not ColumnKind.MEASURE:
            continue

        result.measure_columns.append(column)
        result.column_ranges[column.full_name] = column_range(
            column.index, structure.data_start_row, structure.data_end_row
        )

        raw_values = [v for v in _column_values(structure, column.index) if _is_number(v)]
        is_ratio = _looks_like_ratio(column, [float(v) for v in raw_values])

        for row in range(structure.data_start_row, structure.data_end_row + 1):
            value = structure.cell(row, column.index)
            if value is None or not _is_number(value):
                continue

            period = normalize_year(structure.cell(row, period_col)) if period_col else None
            record = LongRecord(
                period=period,
                dimension=column.full_name,
                value=float(value),
                cell=CellRef(sheet=structure.sheet_name, row=row, col=column.index),
            )

            # 負值分類：比率欄的負成長是正常的，量值欄的負數才是異常
            if value < 0 and not is_ratio:
                record.is_anomalous = True
                record.anomaly_reason = (
                    f"量值欄出現負數 {value}，疑似小計調整或缺值標記，"
                    "不應直接納入加總"
                )

            result.records.append(record)

    unparsed_periods = sum(1 for r in result.records if r.period is None)
    if period_col and unparsed_periods:
        result.warnings.append(
            f"{unparsed_periods} 筆記錄的年度無法解析，該筆不參與期間篩選"
        )

    return result