"""
積木的共用型別與長表 schema。

積木是**領域無關**的通用統計運算（鐵律 3）。任何業務指標——市占率、YoY、
平均消費額——都是積木的組合結果，換領域不需新增函式。因此積木裡不會出現
任何「旅客」「卡數」之類的業務詞彙。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# --- 長表欄位契約：normalizer 產出、積木消費 ---

COL_PERIOD = "period"
"""期間（西元年整數）。可為空——找不到期間欄的工作表仍會攤平。"""

COL_DIMENSION = "dimension"
"""維度值（原始欄位的完整表頭，如「亞洲地區 > 日本 Japan」）。"""

COL_CANONICAL = "canonical"
"""統一欄位名（如「來臺旅客_亞洲地區_日本」）。

LLM 只認得 canonical 名稱——它讀的是 Data Catalog，看不到原始表頭。
長表同時帶兩者：`canonical` 供 LLM 指定參數，`dimension` 保留原始表頭
供人核對時能對回 Excel 上實際看到的文字。"""

COL_VALUE = "value"
"""數值。"""

COL_FILE = "file"
COL_SHEET = "sheet"
COL_ROW = "row"
COL_COL = "col"
"""血緣座標：melt 之後仍能回答「這個數字來自哪一格」。"""

COL_ROLE = "aggregation_role"
"""detail／subtotal／total／residual。

積木必須看得到這欄，否則 `group_sum` 會把明細欄與小計欄一起加總，
造成重複計算——實測表1-3 東南亞群組就是這種結構。"""

LONG_COLUMNS = [
    COL_PERIOD, COL_CANONICAL, COL_DIMENSION, COL_VALUE,
    COL_FILE, COL_SHEET, COL_ROW, COL_COL, COL_ROLE,
]

DETAIL_ROLE = "detail"

AGGREGATE_ROLES = ("subtotal", "total")
"""加總時必須排除的角色——只有小計與總計，**不含 residual**。

「其他 Others」「未列明 Unstated」原本被誤列進來，導致加總少算。實測表1-3
以 6 個年度驗證：

    明細加總        = 7,717,188   比官方總計少 140,498（-1.79%）
    明細 + 殘差加總 = 7,857,686   與官方總計逐格相符

殘差欄記的是真實的旅客人數，只是歸不進任何具名分類，本質上是**明細**，
不是會造成重複計算的彙總。排除它等於憑空蒸發 1.8% 的人。

`aggregation_role` 仍保留 "residual" 標籤——它對 LLM 有意義（知道這是
「其他」類、不宜單獨拿來下結論），只是不該從加總中剔除。"""


class BlockError(ValueError):
    """積木的輸入不合法。

    刻意用例外而非回傳 None：欄位名打錯、資料表缺欄位，這些是**呼叫方的錯**，
    必須當場炸掉讓人看到。只有「資料本身無法支撐計算」（分母為 0、缺基期）
    才回傳 N/A——那不是錯誤，是誠實的答案（鐵律 8）。"""


@dataclass(frozen=True)
class ScalarResult:
    """
    單值運算的結果。

    `value` 為 None 時代表 N/A，且 `reason` 必定說明為什麼——
    絕不用 0 或前期值填補，那會讓錯誤悄悄流進簡報（鐵律 8）。
    """

    value: float | None
    formula: str
    status: str = "passed"
    reason: str | None = None
    source_cells: list[str] = field(default_factory=list)

    @property
    def is_na(self) -> bool:
        return self.value is None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "value": self.value,
            "formula": self.formula,
            "validation_status": self.status,
        }
        if self.reason:
            payload["validation_note"] = self.reason
        if self.source_cells:
            payload["source_cells"] = self.source_cells
        return payload

    @classmethod
    def na(cls, formula: str, reason: str) -> "ScalarResult":
        """建立一個帶原因的 N/A 結果。"""
        return cls(value=None, formula=formula, status="na", reason=reason)


def require_columns(data: pd.DataFrame, *columns: str) -> None:
    """檢查必要欄位存在，缺了就當場炸掉而非回傳空結果。"""
    missing = [c for c in columns if c not in data.columns]
    if missing:
        raise BlockError(
            f"資料表缺少必要欄位 {missing}；現有欄位為 {list(data.columns)}"
        )


def a1_cells(data: pd.DataFrame, limit: int = 50) -> list[str]:
    """
    從長表取出血緣座標，格式 'Sheet!C5'。

    上限存在的理由：一次 group_sum 可能涵蓋上千格，全部塞進血緣會讓
    data_lineage.json 爆掉。超過上限時改記錄範圍摘要（由呼叫方處理）。
    """
    if not {COL_SHEET, COL_ROW, COL_COL}.issubset(data.columns):
        return []
    from src.catalog_builder.cell_tracker import to_a1

    return [
        f"{r[COL_SHEET]}!{to_a1(int(r[COL_ROW]), int(r[COL_COL]))}"
        for _, r in data.head(limit).iterrows()
    ]