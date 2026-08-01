"""
積木單元測試。

積木是所有簡報數字的源頭——這裡錯了，下游的 metric、圖表、PPT 全部跟著錯，
而且錯得很難察覺。因此測試重點放在**邊界條件**（分母 0、缺基期、NaN、
明細與小計混算），而非「正常情況能不能跑」。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calculation_engine.blocks import (  # noqa: E402
    BlockError,
    cumulative_sum,
    exclude_aggregates,
    filter,
    filter_by_period,
    group_mean,
    group_sum,
    growth_rate,
    join,
    pivot,
    rank_top_n,
    ratio,
)


@pytest.fixture
def long_table() -> pd.DataFrame:
    """
    模擬表1-3 東南亞群組：明細欄 + 殘差欄 + 小計欄並存。

    數字關係取自實測——小計 = 明細 + 殘差，這是政府統計報表的通例。
    """
    return pd.DataFrame(
        [
            # period, dimension,   value,  role
            (2023, "馬來西亞", 100.0, "detail"),
            (2023, "新加坡", 200.0, "detail"),
            (2023, "東南亞其他", 30.0, "residual"),
            (2023, "東南亞小計", 330.0, "subtotal"),
            (2024, "馬來西亞", 150.0, "detail"),
            (2024, "新加坡", 250.0, "detail"),
            (2024, "東南亞其他", 40.0, "residual"),
            (2024, "東南亞小計", 440.0, "subtotal"),
        ],
        columns=["period", "dimension", "value", "aggregation_role"],
    ).assign(file="t.xlsx", sheet="S1", row=1, col=1)


# --------------------------------------------------------------------------
# 明細與彙總混算：本專案最容易「悄悄算錯」的地方
# --------------------------------------------------------------------------

def test_group_sum_排除小計但保留殘差(long_table):
    """
    殘差（「其他」「未列明」）是真實人數，必須算進去。

    實測表1-3：排除殘差後加總比官方總計少 1.79%，保留後 6 個年度逐格相符。
    """
    result = group_sum(long_table, "period", "value")
    by_year = dict(zip(result["period"], result["value"]))
    # 明細 + 殘差：100+200+30=330、150+250+40=440，正好等於官方小計
    assert by_year == {2023: 330.0, 2024: 440.0}


def test_group_sum_若不排除小計會重複計算(long_table):
    """釘住這個行為：關掉防護就是會把小計重複算一次。"""
    result = group_sum(long_table, "period", "value", detail_only=False)
    by_year = dict(zip(result["period"], result["value"]))
    # 330 + 小計 330 = 660，整整多算一倍
    assert by_year == {2023: 660.0, 2024: 880.0}


def test_group_sum_加總結果應等於官方小計(long_table):
    """對照組：我們自己加出來的數字要能對上報表原本就有的小計欄。"""
    computed = group_sum(long_table, "period", "value")
    official = long_table[long_table["aggregation_role"] == "subtotal"]
    for year, value in zip(computed["period"], computed["value"]):
        expected = official[official["period"] == year]["value"].iloc[0]
        assert value == expected


def test_exclude_aggregates_保留明細與殘差(long_table):
    assert set(exclude_aggregates(long_table)["aggregation_role"]) == {
        "detail",
        "residual",
    }


def test_exclude_aggregates_無角色欄時原樣回傳():
    data = pd.DataFrame({"value": [1.0, 2.0]})
    assert len(exclude_aggregates(data)) == 2


# --------------------------------------------------------------------------
# ratio：分母為 0 必須是 N/A，不是 0
# --------------------------------------------------------------------------

def test_ratio_正常計算():
    result = ratio(25.0, 100.0)
    assert result.value == pytest.approx(25.0)
    assert result.status == "passed"


def test_ratio_分母為零回傳na附原因():
    result = ratio(25.0, 0.0)
    assert result.is_na
    assert result.status == "na"
    assert "分母為 0" in result.reason


def test_ratio_分子缺值回傳na():
    assert ratio(None, 100.0).is_na
    assert ratio(float("nan"), 100.0).is_na


def test_ratio_不轉百分比():
    assert ratio(1.0, 4.0, as_percent=False).value == pytest.approx(0.25)


# --------------------------------------------------------------------------
# growth_rate：缺基期是 N/A，絕不用 0 或前期值填補
# --------------------------------------------------------------------------

def test_growth_rate_正常計算():
    assert growth_rate(120.0, 100.0).value == pytest.approx(20.0)


def test_growth_rate_負成長():
    assert growth_rate(80.0, 100.0).value == pytest.approx(-20.0)


def test_growth_rate_缺基期回傳na附原因():
    result = growth_rate(120.0, None)
    assert result.is_na
    assert "缺少基期" in result.reason


def test_growth_rate_基期為零無定義():
    result = growth_rate(120.0, 0.0)
    assert result.is_na
    assert "基期為 0" in result.reason


def test_growth_rate_基期為負時正負號無意義():
    result = growth_rate(120.0, -50.0)
    assert result.is_na
    assert "正負號" in result.reason


def test_growth_rate_nan不被吞掉():
    assert growth_rate(float("nan"), 100.0).is_na
    assert growth_rate(100.0, float("nan")).is_na


# --------------------------------------------------------------------------
# filter / filter_by_period
# --------------------------------------------------------------------------

def test_filter_各運算子(long_table):
    assert len(filter(long_table, "period", "==", 2023)) == 4
    assert len(filter(long_table, "period", ">=", 2024)) == 4
    assert len(filter(long_table, "dimension", "in", ["馬來西亞", "新加坡"])) == 4
    assert len(filter(long_table, "dimension", "contains", "小計")) == 2


def test_filter_未知運算子當場炸掉(long_table):
    """不合法的運算子是呼叫方的錯，必須報錯而非回傳空表。"""
    with pytest.raises(BlockError, match="不支援的運算子"):
        filter(long_table, "period", "=~", 2023)


def test_filter_未知欄位當場炸掉(long_table):
    with pytest.raises(BlockError, match="缺少必要欄位"):
        filter(long_table, "不存在的欄", "==", 1)


def test_filter_by_period_含頭含尾(long_table):
    assert set(filter_by_period(long_table, 2023, 2023)["period"]) == {2023}
    assert set(filter_by_period(long_table, 2023, 2024)["period"]) == {2023, 2024}


def test_filter_by_period_排除期間為空的列():
    data = pd.DataFrame({"period": [2023, None, 2024], "value": [1.0, 2.0, 3.0]})
    assert len(filter_by_period(data, 2000, 2030)) == 2


def test_filter_by_period_區間顛倒當場炸掉(long_table):
    with pytest.raises(BlockError, match="顛倒"):
        filter_by_period(long_table, 2024, 2023)


# --------------------------------------------------------------------------
# group_mean / rank_top_n / pivot / join / cumulative_sum
# --------------------------------------------------------------------------

def test_group_mean_略過nan不當成零():
    """補 0 再平均會把缺值當成真實的 0，把平均值拉低。"""
    data = pd.DataFrame(
        {
            "period": [2023, 2023, 2023],
            "value": [100.0, 200.0, float("nan")],
            "aggregation_role": ["detail"] * 3,
        }
    )
    assert group_mean(data)["value"].iloc[0] == pytest.approx(150.0)


def test_rank_top_n_並列名次用min():
    data = pd.DataFrame({"value": [100.0, 100.0, 50.0]})
    ranked = rank_top_n(data, n=3)
    assert list(ranked["rank"]) == [1, 1, 3]


def test_rank_top_n_取前n名(long_table):
    assert len(rank_top_n(long_table, n=2)) == 2


def test_rank_top_n_n非正數當場炸掉(long_table):
    with pytest.raises(BlockError, match="正整數"):
        rank_top_n(long_table, n=0)


def test_pivot_排除小計欄但保留殘差(long_table):
    """圖表資料同樣不能含小計，否則堆疊圖會出現一根等於總和的柱子。"""
    wide = pivot(long_table)
    assert set(wide.columns) == {"馬來西亞", "新加坡", "東南亞其他"}
    assert wide.loc[2023, "馬來西亞"] == 100.0
    assert "東南亞小計" not in wide.columns


def test_join_合併鍵(long_table):
    left = pd.DataFrame({"period": [2023, 2024], "a": [1.0, 2.0]})
    right = pd.DataFrame({"period": [2023, 2024], "b": [3.0, 4.0]})
    merged = join(left, right, on="period")
    assert list(merged.columns) == ["period", "a", "b"]
    assert len(merged) == 2


def test_join_禁止cross(long_table):
    left = pd.DataFrame({"period": [2023], "a": [1.0]})
    with pytest.raises(BlockError, match="不支援的 join"):
        join(left, left, on="period", how="cross")


def test_cumulative_sum_先排序再累計():
    """列序若隨解析順序而定，直接 cumsum 會得到無意義的序列。"""
    data = pd.DataFrame({"period": [2024, 2023, 2025], "value": [10.0, 20.0, 30.0]})
    result = cumulative_sum(data)
    assert list(result["period"]) == [2023, 2024, 2025]
    assert list(result["cumulative"]) == [20.0, 30.0, 60.0]


# --------------------------------------------------------------------------
# 可重現性：驗收標準「同一 Prompt 重跑結果一致」
# --------------------------------------------------------------------------

def test_積木為純函式重跑結果一致(long_table):
    first = group_sum(long_table, "period", "value")
    second = group_sum(long_table, "period", "value")
    pd.testing.assert_frame_equal(first, second)


def test_積木不修改輸入資料(long_table):
    before = long_table.copy(deep=True)
    group_sum(long_table)
    filter(long_table, "period", "==", 2023)
    cumulative_sum(long_table)
    pd.testing.assert_frame_equal(long_table, before)