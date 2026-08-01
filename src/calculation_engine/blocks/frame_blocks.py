"""
表格類積木：長表進、長表出。

全部是純函式——同輸入必得同輸出，不讀全域狀態、不寫檔案。這是驗收標準
「同一 Prompt 重跑結果一致」的基礎，也讓每個積木都能被單元測試釘死。
"""

from __future__ import annotations

from typing import Any, Callable, Literal

import pandas as pd

from .types import (
    AGGREGATE_ROLES,
    COL_DIMENSION,
    COL_PERIOD,
    COL_ROLE,
    COL_VALUE,
    BlockError,
    require_columns,
)

Comparison = Literal["==", "!=", ">", ">=", "<", "<=", "in", "contains"]

_OPERATORS: dict[str, Callable[[pd.Series, Any], pd.Series]] = {
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    "in": lambda s, v: s.isin(v if isinstance(v, (list, tuple, set)) else [v]),
    "contains": lambda s, v: s.astype(str).str.contains(str(v), na=False),
}


def filter(  # noqa: A001 — 名稱由 TASK1.md 積木清單指定
    data: pd.DataFrame, column: str, operator: Comparison, value: Any
) -> pd.DataFrame:
    """
    依條件篩選列。

    運算子走白名單而非 `DataFrame.query()`：query 會執行任意運算式字串，
    等於給了 LLM 一條繞過白名單的路（鐵律 5）。
    """
    require_columns(data, column)
    if operator not in _OPERATORS:
        raise BlockError(
            f"不支援的運算子 '{operator}'；可用：{sorted(_OPERATORS)}"
        )
    return data[_OPERATORS[operator](data[column], value)].copy()


def filter_by_period(
    data: pd.DataFrame, start: int | None = None, end: int | None = None
) -> pd.DataFrame:
    """
    依期間區間篩選（含頭含尾）。

    period 為空的列一律排除：期間不明的資料混進時間序列計算會靜默污染結果，
    寧可少算也不能錯算。
    """
    require_columns(data, COL_PERIOD)
    if start is not None and end is not None and start > end:
        raise BlockError(f"期間區間顛倒：start={start} 大於 end={end}")

    result = data[data[COL_PERIOD].notna()].copy()
    if start is not None:
        result = result[result[COL_PERIOD] >= start]
    if end is not None:
        result = result[result[COL_PERIOD] <= end]
    return result


def exclude_aggregates(data: pd.DataFrame) -> pd.DataFrame:
    """
    濾掉小計與總計欄，保留明細與殘差。

    **加總前一律先過這一關**。實測表1-3 東南亞群組有 6 個國家明細 + 1 個小計欄，
    不濾掉小計就會重複計算整個群組。

    殘差欄（「其他 Others」「未列明 Unstated」）**刻意保留**：它記的是真實
    旅客人數，只是歸不進具名分類。實測排除後加總比官方總計少 1.79%，
    保留後 6 個年度逐格相符。詳見 `types.AGGREGATE_ROLES`。
    """
    if COL_ROLE not in data.columns:
        return data.copy()
    return data[~data[COL_ROLE].isin(AGGREGATE_ROLES)].copy()


def _grouped(
    data: pd.DataFrame,
    group_col: str,
    value_col: str,
    how: Literal["sum", "mean"],
    detail_only: bool,
) -> pd.DataFrame:
    require_columns(data, group_col, value_col)
    source = exclude_aggregates(data) if detail_only else data
    if source.empty:
        return pd.DataFrame(columns=[group_col, value_col])

    aggregated = (
        source.groupby(group_col, dropna=True)[value_col]
        .agg(how)
        .reset_index()
        .sort_values(group_col)
        .reset_index(drop=True)
    )
    return aggregated


def group_sum(
    data: pd.DataFrame,
    group_col: str = COL_PERIOD,
    value_col: str = COL_VALUE,
    detail_only: bool = True,
) -> pd.DataFrame:
    """
    分組加總。

    `detail_only` 預設為 True——加總的預設語意是「把明細加起來」，
    把小計也加進去幾乎一定是錯的。需要直接取用官方小計時明確關掉它。
    """
    return _grouped(data, group_col, value_col, "sum", detail_only)


def group_mean(
    data: pd.DataFrame,
    group_col: str = COL_PERIOD,
    value_col: str = COL_VALUE,
    detail_only: bool = True,
) -> pd.DataFrame:
    """
    分組平均。

    NaN 由 pandas 自動略過（不計入分母），與「補 0 再平均」不同——
    後者會把缺值當成真實的 0 拉低平均值。
    """
    return _grouped(data, group_col, value_col, "mean", detail_only)


def rank_top_n(
    data: pd.DataFrame,
    value_col: str = COL_VALUE,
    n: int = 5,
    ascending: bool = False,
) -> pd.DataFrame:
    """
    取前 N 名並附上名次。

    名次用 `method='min'`：並列第 1 時兩者都是 1，下一名是 3。
    這是排名的通用慣例，也避免「並列卻顯示不同名次」這種一眼可見的錯誤。
    """
    require_columns(data, value_col)
    if n <= 0:
        raise BlockError(f"n 必須為正整數，收到 {n}")

    ranked = data.dropna(subset=[value_col]).copy()
    if ranked.empty:
        return ranked.assign(rank=pd.Series(dtype="int64"))

    ranked["rank"] = ranked[value_col].rank(
        ascending=ascending, method="min"
    ).astype(int)
    return (
        ranked.sort_values([value_col], ascending=ascending)
        .head(n)
        .reset_index(drop=True)
    )


def pivot(
    data: pd.DataFrame,
    index: str = COL_PERIOD,
    columns: str = COL_DIMENSION,
    values: str = COL_VALUE,
    detail_only: bool = True,
) -> pd.DataFrame:
    """
    長表轉寬表，供圖表使用。

    重複的 (index, columns) 組合以加總合併——長表本來就可能同一年同一維度
    有多列（來自不同檔案）。`aggfunc='sum'` 讓行為明確可預期，
    而非 pandas 預設的 mean。
    """
    require_columns(data, index, columns, values)
    source = exclude_aggregates(data) if detail_only else data
    if source.empty:
        return pd.DataFrame()
    return (
        source.pivot_table(
            index=index, columns=columns, values=values, aggfunc="sum"
        )
        .sort_index()
    )


def join(
    data_a: pd.DataFrame,
    data_b: pd.DataFrame,
    on: str | list[str],
    how: Literal["inner", "left", "outer"] = "inner",
    suffixes: tuple[str, str] = ("_a", "_b"),
) -> pd.DataFrame:
    """
    跨檔案關聯。

    只開放 inner／left／outer：`cross` join 會產生笛卡兒積，在幾千列的長表上
    足以撐爆記憶體，而且沒有任何統計意義。
    """
    keys = [on] if isinstance(on, str) else list(on)
    require_columns(data_a, *keys)
    require_columns(data_b, *keys)
    if how not in ("inner", "left", "outer"):
        raise BlockError(f"不支援的 join 方式 '{how}'")
    return data_a.merge(data_b, on=keys, how=how, suffixes=suffixes)


def cumulative_sum(
    data: pd.DataFrame,
    value_col: str = COL_VALUE,
    order_by: str = COL_PERIOD,
) -> pd.DataFrame:
    """
    累計加總。

    先依 `order_by` 排序才累計——長表的列序取決於解析順序，
    直接 cumsum 會得到一個順序隨機、看似合理實則無意義的序列。
    """
    require_columns(data, value_col, order_by)
    result = data.sort_values(order_by).copy()
    result["cumulative"] = result[value_col].cumsum()
    return result.reset_index(drop=True)