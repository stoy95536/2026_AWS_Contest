"""
執行引擎測試：白名單防護、血緣、Sanity Check 重試。

重點在「LLM 亂寫時會不會被擋下來」——這些防護若失效，錯誤不會拋例外，
只會安靜地算出一個看似合理的數字。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calculation_engine.blocks.types import LONG_COLUMNS  # noqa: E402
from src.calculation_engine.dataset import Dataset, FieldMeta  # noqa: E402
from src.calculation_engine.executor import (  # noqa: E402
    ExecutionError,
    Executor,
    MetricRecipe,
    execute_with_retry,
)
from src.validation.sanity_check import (  # noqa: E402
    check_components_sum,
    check_denominator,
    check_metric,
)


@pytest.fixture
def dataset() -> Dataset:
    """兩個國家 × 兩年 + 一個總計欄。"""
    rows = []
    data = {
        ("來臺旅客_日本", "日本 Japan", "detail"): {2023: 900.0, 2024: 1300.0},
        ("來臺旅客_韓國", "韓國 Korea", "detail"): {2023: 600.0, 2024: 700.0},
        ("來臺旅客_總計", "總計 Grand Total", "total"): {2023: 1500.0, 2024: 2000.0},
    }
    col = 2
    for (canonical, source, role), by_year in data.items():
        for i, (year, value) in enumerate(by_year.items()):
            rows.append({
                "period": year, "canonical": canonical, "dimension": source,
                "value": value, "file": "t.xlsx", "sheet": "S1",
                "row": 5 + i, "col": col, "aggregation_role": role,
            })
        col += 1

    frame = pd.DataFrame(rows, columns=LONG_COLUMNS)
    frame["period"] = frame["period"].astype("Int64")
    fields = {
        c: FieldMeta(c, s, "人次", "B5:B6", r, "t.xlsx", "S1", 0.9)
        for c, s, r in data
    }
    return Dataset(frame=frame, fields=fields)


def _recipe(**overrides) -> MetricRecipe:
    payload = {
        "metric_id": "japan_2024",
        "metric_name": "2024 日本旅客人次",
        "unit": "人次",
        "period": "2024",
        "steps": [
            {"id": "jp", "block": "filter", "input": "dataset",
             "params": {"column": "canonical", "operator": "==", "value": "來臺旅客_日本"}},
            {"id": "jp24", "block": "filter_by_period", "input": "jp",
             "params": {"start": 2024, "end": 2024}},
            {"id": "total", "block": "group_sum", "input": "jp24",
             "params": {"group_col": "period"}},
        ],
        "output": "total",
    }
    payload.update(overrides)
    return MetricRecipe.from_dict(payload)


# --------------------------------------------------------------------------
# 白名單：LLM 亂寫時必須當場擋下
# --------------------------------------------------------------------------

def test_拒絕白名單外的積木(dataset):
    recipe = _recipe(steps=[
        {"id": "x", "block": "eval_pandas", "input": "dataset", "params": {}}
    ], output="x")
    with pytest.raises(ExecutionError, match="不在白名單"):
        Executor(dataset).execute(recipe)


def test_拒絕不存在的欄位名(dataset):
    """LLM 幻覺出的欄位若不擋，filter 會安靜回傳 0 列而非報錯。"""
    recipe = _recipe(steps=[
        {"id": "x", "block": "filter", "input": "dataset",
         "params": {"column": "canonical", "operator": "==", "value": "來臺旅客_火星"}},
    ], output="x")
    with pytest.raises(ExecutionError, match="不存在於 Data Catalog"):
        Executor(dataset).execute(recipe)


def test_拒絕清單中夾帶不存在的欄位(dataset):
    recipe = _recipe(steps=[
        {"id": "x", "block": "filter", "input": "dataset",
         "params": {"column": "canonical", "operator": "in",
                    "value": ["來臺旅客_日本", "來臺旅客_火星"]}},
    ], output="x")
    with pytest.raises(ExecutionError, match="來臺旅客_火星"):
        Executor(dataset).execute(recipe)


def test_拒絕指向不存在步驟的output(dataset):
    with pytest.raises(ExecutionError, match="output 指向不存在"):
        Executor(dataset).execute(_recipe(output="nope"))


def test_拒絕引用不存在的步驟(dataset):
    recipe = _recipe(steps=[
        {"id": "r", "block": "ratio",
         "params": {"numerator": {"$ref": "ghost"}, "denominator": 100}},
    ], output="r")
    with pytest.raises(ExecutionError, match="不存在的步驟"):
        Executor(dataset).execute(recipe)


def test_多列結果不可當單值使用(dataset):
    """少做一次彙總時取第一列會得到看似合理的錯誤數字，必須報錯。"""
    recipe = _recipe(steps=[
        {"id": "jp", "block": "filter", "input": "dataset",
         "params": {"column": "canonical", "operator": "==", "value": "來臺旅客_日本"}},
    ], output="jp")
    with pytest.raises(ExecutionError, match="無法當成單一數值"):
        Executor(dataset).execute(recipe)


# --------------------------------------------------------------------------
# 正常執行與血緣
# --------------------------------------------------------------------------

def test_執行成功並帶血緣(dataset):
    result = Executor(dataset).execute(_recipe())
    assert result.value == 1300.0
    assert result.validation_status == "passed"
    assert result.block_chain[0].startswith("filter(")
    assert len(result.block_chain) == 3
    assert result.source_cells and "!" in result.source_cells[0]
    assert result.source_range_summary


def test_跨步驟引用計算占比(dataset):
    recipe = _recipe(
        metric_id="japan_share_2024", metric_name="2024 日本占比",
        unit="%", is_share=True,
        assumption_statement="以總計欄為分母",
        steps=[
            {"id": "jp", "block": "filter", "input": "dataset",
             "params": {"column": "canonical", "operator": "==", "value": "來臺旅客_日本"}},
            {"id": "jp24", "block": "filter_by_period", "input": "jp",
             "params": {"start": 2024, "end": 2024}},
            {"id": "jp_sum", "block": "group_sum", "input": "jp24",
             "params": {"group_col": "period"}},
            {"id": "tot", "block": "filter", "input": "dataset",
             "params": {"column": "canonical", "operator": "==", "value": "來臺旅客_總計"}},
            {"id": "tot24", "block": "filter_by_period", "input": "tot",
             "params": {"start": 2024, "end": 2024}},
            {"id": "tot_sum", "block": "group_sum", "input": "tot24",
             "params": {"group_col": "period", "detail_only": False}},
            {"id": "share", "block": "ratio",
             "params": {"numerator": {"$ref": "jp_sum"}, "denominator": {"$ref": "tot_sum"}}},
        ],
        output="share",
    )
    result = Executor(dataset).execute(recipe)
    assert result.value == pytest.approx(65.0)  # 1300 / 2000
    assert result.assumption_statement == "以總計欄為分母"


def test_na結果不算失敗(dataset):
    """算不出來是誠實的答案，不該被當成錯誤（鐵律 8）。"""
    recipe = _recipe(steps=[
        {"id": "r", "block": "ratio", "params": {"numerator": 10, "denominator": 0}},
    ], output="r", unit="%")
    result = Executor(dataset).execute(recipe)
    assert result.value is None
    assert result.validation_status == "na"
    assert "分母為 0" in result.validation_note


# --------------------------------------------------------------------------
# 跨檔案重複計算：不會拋例外、比率還會正常，只有絕對值悄悄變兩倍
# --------------------------------------------------------------------------

@pytest.fixture
def two_file_dataset() -> Dataset:
    """同一個 canonical 出現在兩份檔案——實測表1-2 與表1-3 的日本欄就是如此。"""
    rows = [
        {"period": 2024, "canonical": "來臺旅客_日本", "dimension": "日本 Japan",
         "value": 1300.0, "file": "按國籍.xlsx", "sheet": "S1", "row": 5, "col": 3,
         "aggregation_role": "detail"},
        {"period": 2024, "canonical": "來臺旅客_日本", "dimension": "日本 Japan",
         "value": 1301.0, "file": "按居住地.xlsx", "sheet": "S2", "row": 5, "col": 3,
         "aggregation_role": "detail"},
    ]
    frame = pd.DataFrame(rows, columns=LONG_COLUMNS)
    frame["period"] = frame["period"].astype("Int64")
    fields = {
        "來臺旅客_日本": FieldMeta(
            "來臺旅客_日本", "日本 Japan", "人次", "C5:C6", "detail",
            "按國籍.xlsx", "S1", 0.9,
        )
    }
    return Dataset(frame=frame, fields=fields)


def _japan_recipe(with_file: str | None) -> MetricRecipe:
    steps = []
    previous = "dataset"
    if with_file:
        steps.append({"id": "f", "block": "filter", "input": "dataset",
                      "params": {"column": "file", "operator": "==", "value": with_file}})
        previous = "f"
    steps += [
        {"id": "jp", "block": "filter", "input": previous,
         "params": {"column": "canonical", "operator": "==", "value": "來臺旅客_日本"}},
        {"id": "s", "block": "group_sum", "input": "jp", "params": {"group_col": "period"}},
    ]
    return MetricRecipe.from_dict({
        "metric_id": "jp", "metric_name": "日本旅客", "unit": "人次",
        "steps": steps, "output": "s",
    })


def test_跨檔案同名欄位加總被攔下(two_file_dataset):
    """1300 + 1301 = 2601，是同一批人的兩種口徑，不是兩批人。"""
    result = Executor(two_file_dataset).execute(_japan_recipe(None))
    assert result.value == 2601.0
    assert result.validation_status == "failed"
    assert "同時存在於 2 份檔案" in result.validation_note


def test_指定單一檔案後通過(two_file_dataset):
    result = Executor(two_file_dataset).execute(_japan_recipe("按國籍.xlsx"))
    assert result.value == 1300.0
    assert result.validation_status == "passed"


def test_跨檔案重複計算在比率中會被抵銷而看不出來(two_file_dataset):
    """
    釘住這個危險特性：分子分母同時加倍，比率完全正常。

    沒有 ambiguous_source 檢查的話，這種錯誤永遠不會被發現。
    """
    from src.calculation_engine.blocks import ratio
    assert ratio(2601.0, 5202.0).value == ratio(1300.0, 2600.0).value


# --------------------------------------------------------------------------
# Sanity Check
# --------------------------------------------------------------------------

def test_sanity_攔截超出範圍的占比():
    report = check_metric(150.0, unit="%", is_share=True, metric_id="m1")
    assert not report.passed
    assert report.errors[0].code == "share_out_of_range"


def test_sanity_允許負成長率():
    assert check_metric(-20.0, unit="%", is_share=False).passed


def test_sanity_攔截衰退超過百分之百():
    report = check_metric(-150.0, unit="%")
    assert not report.passed
    assert report.errors[0].code == "ratio_below_min"


def test_sanity_攔截nan與inf():
    assert check_metric(float("nan")).errors[0].code == "value_nan"
    assert check_metric(float("inf")).errors[0].code == "value_inf"


def test_sanity_na是警告不是錯誤():
    report = check_metric(None)
    assert report.passed
    assert report.issues[0].code == "value_na"


def test_sanity_人次不可為負():
    report = check_metric(-5.0, unit="人次", allow_negative=False)
    assert not report.passed
    assert report.errors[0].code == "unexpected_negative"


def test_sanity_分母檢查():
    assert not check_denominator(0).passed
    assert not check_denominator(None).passed
    assert check_denominator(100).passed


def test_sanity_明細加總對帳():
    """實測正是靠這項發現排除「其他」欄會讓加總少 1.79%。"""
    assert check_components_sum(7_857_686, 7_857_686).passed
    report = check_components_sum(7_717_188, 7_857_686)
    assert not report.passed
    assert report.errors[0].code == "components_sum_mismatch"
    # 四捨五入等級的小差異不該產生假警報
    assert check_components_sum(1000.0, 1002.0, tolerance=0.005).passed


# --------------------------------------------------------------------------
# 重試
# --------------------------------------------------------------------------

def test_重試後成功(dataset):
    """第一次配方壞掉，回饋錯誤後第二次修好。"""
    attempts = []

    def provider(feedback):
        attempts.append(feedback)
        if feedback is None:
            return _recipe(steps=[
                {"id": "x", "block": "not_a_block", "input": "dataset", "params": {}}
            ], output="x")
        return _recipe()

    result = execute_with_retry(dataset, provider)
    assert result.value == 1300.0
    assert result.attempts == 2
    assert attempts[0] is None
    assert "不在白名單" in attempts[1]


def test_重試耗盡標記需人工確認(dataset):
    def provider(feedback):
        return _recipe(steps=[
            {"id": "x", "block": "not_a_block", "input": "dataset", "params": {}}
        ], output="x")

    result = execute_with_retry(dataset, provider, max_retries=2)
    assert result.validation_status == "needs_manual_review"
    assert "重試 2 次仍未通過" in result.validation_note
    assert result.attempts == 3


def test_重試不因單一指標失敗而中斷(dataset):
    """一個指標算不出來，不該讓整份簡報生不出來。"""
    result = execute_with_retry(
        dataset, lambda f: _recipe(steps=[
            {"id": "x", "block": "ghost", "input": "dataset", "params": {}}
        ], output="x")
    )
    assert result is not None
    assert result.value is None