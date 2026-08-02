"""
單值類積木：數字進、ScalarResult 出。

這兩個積木是最容易「悄悄算錯」的地方——分母為 0、缺基期，若隨手回傳 0
或沿用前期值，錯誤會一路流進 KPI 卡片而沒人察覺。因此它們一律回傳
帶原因的 N/A（鐵律 8：寧可 N/A 也不估算）。
"""

from __future__ import annotations

import math

from .types import ScalarResult

PERCENT_SCALE = 100.0


def _is_usable(value: float | None) -> bool:
    """None 與 NaN 都不可用。NaN 特別危險：它參與任何運算都不報錯，只是靜靜傳染。"""
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def ratio(
    numerator: float | None,
    denominator: float | None,
    as_percent: bool = True,
    label: str = "",
) -> ScalarResult:
    """
    比率／占比。

    分母為 0 回傳 N/A 而非 0 或無限大——「日本旅客占比 0%」與
    「當年沒有任何旅客所以占比無意義」是兩件完全不同的事，
    前者會被寫進簡報當成結論，後者才是事實。
    """
    formula = f"{label or 'ratio'} = 分子 / 分母" + (" × 100%" if as_percent else "")

    if not _is_usable(numerator) or not _is_usable(denominator):
        return ScalarResult.na(formula, "分子或分母缺值，無法計算比率")
    if denominator == 0:
        return ScalarResult.na(formula, "分母為 0，比率無定義")

    value = numerator / denominator
    return ScalarResult(
        value=value * PERCENT_SCALE if as_percent else value,
        formula=f"{formula}（{numerator:,.4g} / {denominator:,.4g}）",
    )


def growth_rate(
    current: float | None,
    previous: float | None,
    label: str = "",
) -> ScalarResult:
    """
    成長率 (current − previous) / previous × 100%。

    三種情況一律 N/A 並說明原因：
      - 缺基期：實測表2-3 只有 1994 年起的資料，問 1993 年的 YoY 無從算起
      - 基期為 0：從 0 成長的百分比在數學上無定義，不是「成長 100%」
      - 基期為負：分母帶號會讓成長率的正負號失去意義
    """
    formula = f"{label or 'growth_rate'} = (本期 − 基期) / 基期 × 100%"

    if not _is_usable(current):
        return ScalarResult.na(formula, "本期缺值，無法計算成長率")
    if not _is_usable(previous):
        return ScalarResult.na(formula, "缺少基期資料，無法計算成長率")
    if previous == 0:
        return ScalarResult.na(formula, "基期為 0，成長率無定義")
    if previous < 0:
        return ScalarResult.na(
            formula, f"基期為負數（{previous:,.4g}），成長率正負號無意義"
        )

    value = (current - previous) / previous * PERCENT_SCALE
    return ScalarResult(
        value=value,
        formula=f"{formula}（({current:,.4g} − {previous:,.4g}) / {previous:,.4g}）",
    )