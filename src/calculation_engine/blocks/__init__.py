"""
白名單通用運算積木（TASK1.md 3 / 4.2）。

10 個領域無關的統計函式，任何業務指標都是它們的組合結果：

    整年度市占率     filter_by_period → group_sum(by=維度) → ratio
    哪個成長最快     filter_by_period ×2 → group_sum → growth_rate → rank_top_n

換領域不需新增函式——這是本專案能吃「未知領域的 11 份 Excel」的關鍵，
也是與舊架構（一個業務指標一個寫死函式）的根本差異。

**LLM 只能點這張表裡的名字**。註冊表就是白名單本身：不在 `BLOCK_REGISTRY`
裡的名稱，執行引擎一律拒絕派發（鐵律 5），杜絕「LLM 生成任意 pandas 程式碼」
這條路。
"""

from .frame_blocks import (
    cumulative_sum,
    exclude_aggregates,
    filter,  # noqa: A004 — 名稱由 TASK1.md 積木清單指定
    filter_by_period,
    group_mean,
    group_sum,
    join,
    pivot,
    rank_top_n,
)
from .scalar_blocks import growth_rate, ratio
from .types import (
    AGGREGATE_ROLES,
    COL_DIMENSION,
    COL_FILE,
    COL_PERIOD,
    COL_ROLE,
    COL_SHEET,
    COL_VALUE,
    DETAIL_ROLE,
    LONG_COLUMNS,
    BlockError,
    ScalarResult,
    a1_cells,
    require_columns,
)

BLOCK_REGISTRY = {
    "filter": filter,
    "filter_by_period": filter_by_period,
    "group_sum": group_sum,
    "group_mean": group_mean,
    "ratio": ratio,
    "growth_rate": growth_rate,
    "rank_top_n": rank_top_n,
    "pivot": pivot,
    "join": join,
    "cumulative_sum": cumulative_sum,
}
"""積木白名單：名稱 → 函式。執行引擎的唯一派發來源。

`exclude_aggregates` 刻意不列入——它是 group_sum／pivot 的內建防護，
不是給 LLM 自由呼叫的步驟，暴露出去只會多一個被誤用的旋鈕。"""

SCALAR_BLOCKS = frozenset({"ratio", "growth_rate"})
"""回傳 ScalarResult 而非 DataFrame 的積木，執行引擎據此決定如何串接。"""

__all__ = [
    "AGGREGATE_ROLES",
    "BLOCK_REGISTRY",
    "COL_DIMENSION",
    "COL_FILE",
    "COL_PERIOD",
    "COL_ROLE",
    "COL_SHEET",
    "COL_VALUE",
    "DETAIL_ROLE",
    "LONG_COLUMNS",
    "SCALAR_BLOCKS",
    "BlockError",
    "ScalarResult",
    "a1_cells",
    "cumulative_sum",
    "exclude_aggregates",
    "filter",
    "filter_by_period",
    "group_mean",
    "group_sum",
    "growth_rate",
    "join",
    "pivot",
    "rank_top_n",
    "ratio",
    "require_columns",
]