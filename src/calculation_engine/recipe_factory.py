"""
配方工廠：用程式組出標準指標配方。

兩個用途：
  1. **LLM 的參考範本**——這些配方就是 Function Calling 該輸出的形狀
  2. **LLM 不可用時的後備**——決賽現場憑證失效、Bedrock 逾時、額度用盡都
     可能發生。有規則式後備，系統至少還能產出可追溯的數字，而不是整個停擺。

配方一律指定 `file`：同一個 canonical 欄位常橫跨多份檔案（實測「日本」同時
存在於按居住地與按國籍兩份），不指定會把同一批對象重複計算，且比率型指標
的分子分母會同時加倍而互相抵銷，看起來完全正常（見 executor 的
ambiguous_source 檢查）。
"""

from __future__ import annotations

from typing import Any

from .blocks.types import COL_CANONICAL, COL_FILE
from .dataset import Dataset


def _scope(step_id: str, file_name: str, canonical: str) -> list[dict[str, Any]]:
    """指定單一檔案 + 單一欄位的兩步前置，所有配方共用。"""
    return [
        {"id": f"{step_id}_f", "block": "filter", "input": "dataset",
         "params": {"column": COL_FILE, "operator": "==", "value": file_name}},
        {"id": f"{step_id}_c", "block": "filter", "input": f"{step_id}_f",
         "params": {"column": COL_CANONICAL, "operator": "==", "value": canonical}},
    ]


def _period_sum(step_id: str, source: str, year: int) -> list[dict[str, Any]]:
    """篩出某一年並收斂成單一數值。

    `detail_only=False`：此處已用 canonical 鎖定單一欄位，不需要再排除彙總欄；
    若該欄本身就是總計欄（如「總計 Grand Total」），開著反而會把它濾光。
    """
    return [
        {"id": f"{step_id}_y", "block": "filter_by_period", "input": source,
         "params": {"start": year, "end": year}},
        {"id": f"{step_id}_s", "block": "group_sum", "input": f"{step_id}_y",
         "params": {"group_col": "period", "detail_only": False}},
    ]


def value_recipe(
    metric_id: str, metric_name: str, canonical: str, file_name: str,
    year: int, unit: str,
) -> dict[str, Any]:
    """單一年度的數值。"""
    return {
        "metric_id": metric_id,
        "metric_name": metric_name,
        "unit": unit,
        "period": str(year),
        "assumption_statement": f"取自「{file_name}」的「{canonical}」欄 {year} 年度值",
        "steps": _scope("v", file_name, canonical) + _period_sum("v", "v_c", year),
        "output": "v_s",
    }


def growth_recipe(
    metric_id: str, metric_name: str, canonical: str, file_name: str,
    year: int, base_year: int,
) -> dict[str, Any]:
    """
    年增率。

    基期不存在時 `growth_rate` 會回傳帶原因的 N/A，不會估算——
    實測表2-3 只有 1994 年起的資料，問更早的 YoY 就是這種情況。
    """
    return {
        "metric_id": metric_id,
        "metric_name": metric_name,
        "unit": "%",
        "period": str(year),
        "assumption_statement": (
            f"以「{file_name}」的「{canonical}」欄 {base_year} 年為基期；"
            "基期缺值時輸出 N/A，不以任何方式估算"
        ),
        "steps": (
            _scope("cur", file_name, canonical)
            + _period_sum("cur", "cur_c", year)
            + _scope("base", file_name, canonical)
            + _period_sum("base", "base_c", base_year)
            + [{"id": "g", "block": "growth_rate",
                "params": {"current": {"$ref": "cur_s"},
                           "previous": {"$ref": "base_s"},
                           "label": metric_name}}]
        ),
        "output": "g",
    }


def share_recipe(
    metric_id: str, metric_name: str, canonical: str, total_canonical: str,
    file_name: str, year: int,
) -> dict[str, Any]:
    """
    占比。分母用報表原本就有的總計欄，而非自行加總——

    自行加總得再決定「哪些欄算進去」，那是業務判斷；直接用官方總計欄
    可讓數字與報表原文一致，也讓評審能直接核對。
    """
    return {
        "metric_id": metric_id,
        "metric_name": metric_name,
        "unit": "%",
        "period": str(year),
        "is_share": True,
        "assumption_statement": (
            f"分母採用「{file_name}」的「{total_canonical}」欄，"
            "即報表既有的官方總計，非自行加總明細"
        ),
        "steps": (
            _scope("num", file_name, canonical)
            + _period_sum("num", "num_c", year)
            + _scope("den", file_name, total_canonical)
            + _period_sum("den", "den_c", year)
            + [{"id": "r", "block": "ratio",
                "params": {"numerator": {"$ref": "num_s"},
                           "denominator": {"$ref": "den_s"},
                           "label": metric_name}}]
        ),
        "output": "r",
    }


def rank_fields_by_latest_value(
    dataset: Dataset, file_name: str, year: int, limit: int = 5
) -> list[str]:
    """
    找出某檔案在指定年度數值最大的前 N 個明細欄位。

    用於自動挑選「值得放進簡報」的欄位——**依資料本身的量級決定**，
    不預設任何業務概念，換領域一樣適用。
    """
    frame = dataset.frame
    subset = frame[
        (frame[COL_FILE] == file_name)
        & (frame["period"] == year)
        & (frame["aggregation_role"] == "detail")
    ]
    if subset.empty:
        return []
    return (
        subset.groupby(COL_CANONICAL)["value"].sum()
        .sort_values(ascending=False)
        .head(limit)
        .index.tolist()
    )


def find_total_field(
    dataset: Dataset, file_name: str, sheet_name: str | None = None
) -> str | None:
    """
    找出官方總計欄，供占比計算當分母。

    **必須同時比對工作表**：一個檔案常有多張表量測不同的東西（附件四同時有
    「流通卡數」與「當月簽帳金額」四張表）。只比對檔名會拿到別張表的總計，
    變成「簽帳金額 ÷ 流通卡數」——實測算出 124.11% 的占比。

    Sanity Check 會攔下超過 100% 的占比，但那是最後一道防線；若兩張表的量級
    碰巧接近，錯誤比率會落在合理區間而**完全不被發現**。
    """
    for canonical, meta in dataset.fields.items():
        if meta.file_name != file_name or meta.aggregation_role != "total":
            continue
        if sheet_name is not None and meta.sheet_name != sheet_name:
            continue
        return canonical
    return None


def latest_common_year(dataset: Dataset, file_name: str) -> int | None:
    """
    該檔案最新的「有資料」年度。

    不直接取 max：政府報表常在最後一列預留當年度但尚未填值，
    取到那一列會得到一整排 N/A。
    """
    frame = dataset.frame
    subset = frame[
        (frame[COL_FILE] == file_name)
        & frame["value"].notna()
        & frame["period"].notna()
    ]
    if subset.empty:
        return None
    max_period = subset["period"].max()
    if max_period is None or (hasattr(max_period, '__class__') and 'NAType' in type(max_period).__name__):
        return None
    return int(max_period)