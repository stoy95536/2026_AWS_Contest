"""
同源輸出測試：三方一致性、精度統一、N/A 不被補值。

驗收標準「chart_data、analysis_result.xlsx 與 metric JSON 三方數值一致」
是靠「圖表值就是 metric 值」的結構保證，不是靠事後比對——這裡釘住這個結構。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calculation_engine.executor import MetricResult  # noqa: E402
from src.export import AnalysisResult, ChartSpec, write_all  # noqa: E402
from src.export.result import VALUE_PRECISION, format_display, serialize_value  # noqa: E402


def _metric(metric_id: str, value: float | None, unit: str = "人次", status: str = "passed"):
    return MetricResult(
        metric_id=metric_id, metric_name=f"{metric_id} 名稱", value=value,
        unit=unit, period="2024", formula="f", block_chain=["group_sum()"],
        source_cells=["S1!C5"], source_range_summary=["S1!C5:C10"],
        source_refs=[{"file": "t.xlsx", "sheet": "S1", "range": "C5:C10"}],
        validation_status=status, assumption_statement="測試假設",
    )


@pytest.fixture
def result() -> AnalysisResult:
    r = AnalysisResult(prompt="測試")
    # 這個值在 Excel 的 15 位有效數字下會被截斷，是實測 35 筆不一致的成因
    r.add(_metric("m_precise", 12.066050672347986, unit="%"))
    r.add(_metric("m_big", 1318372.0))
    r.add(_metric("m_na", None, status="na"))
    r.charts.append(ChartSpec(
        chart_id="c1", chart_type="line", title="趨勢",
        category_metric_map={"系列A": ["m_precise", "m_big", "m_na"]},
        categories=["2022", "2023", "2024"], unit="人次",
    ))
    return r


def test_精度統一後json與excel嚴格相等(result, tmp_path):
    """
    Excel 只存 15 位有效數字，Python float 有 17 位。

    不統一精度的話 12.066050672347986 寫進 Excel 會變 12.06605067234799，
    評審拿 == 比對就會看到不符。
    """
    paths = write_all(result, tmp_path)
    payload = json.loads(paths["analysis_json"].read_text(encoding="utf-8"))
    sheet = pd.read_excel(paths["analysis_excel"], sheet_name="Metrics")

    from_json = {m["metric_id"]: m["value"] for m in payload["metrics"]}
    from_excel = dict(zip(sheet["指標ID"], sheet["數值"]))

    for metric_id, value in from_json.items():
        if value is None:
            continue
        assert value == from_excel[metric_id], f"{metric_id} JSON 與 Excel 不一致"


def test_圖表值就是metric值(result):
    """圖表不另外計算，所以三方一致是結構上的必然。"""
    payload = result.analysis_payload()
    metrics = {m["metric_id"]: m["value"] for m in payload["metrics"]}
    for chart in payload["chart_data"]:
        for series in chart["series"]:
            # values 與 metric_ids 同序等長，成員 C 直接吃 values，
            # 成員 D 用 metric_ids 回溯
            assert len(series["values"]) == len(series["metric_ids"])
            for value, metric_id in zip(series["values"], series["metric_ids"]):
                assert value == metrics[metric_id]


def test_四份輸出的metric數一致(result, tmp_path):
    paths = write_all(result, tmp_path)
    payload = json.loads(paths["analysis_json"].read_text(encoding="utf-8"))
    lineage = json.loads(paths["lineage_json"].read_text(encoding="utf-8"))
    sheet = pd.read_excel(paths["analysis_excel"], sheet_name="Metrics")

    assert len(payload["metrics"]) == len(lineage["records"]) == len(sheet)


def test_na不被補零(result):
    """圖表上的斷點是真實資訊，補 0 會畫出一條假的下探曲線。"""
    payload = result.analysis_payload()
    na_metric = next(m for m in payload["metrics"] if m["metric_id"] == "m_na")
    assert na_metric["value"] is None
    assert na_metric["display_value"] == "N/A"

    series = payload["chart_data"][0]["series"][0]
    assert series["values"][2] is None
    assert series["metric_ids"][2] == "m_na"
    # 整張圖只要有一個點不是 passed，圖的狀態就不該是 passed
    assert payload["chart_data"][0]["validation_status"] != "passed"


def test_血緣沿用舊格式讓組員d不必改程式(result):
    """
    成員 D 的 ppt_reconciler 用 get_record(metric_id).validation_status，
    外層結構若改掉他就得改程式。
    """
    payload = result.lineage_payload()
    assert set(payload) >= {"generated_at", "total_records", "records"}
    record = payload["records"]["m_big"]
    assert record["validation_status"] == "passed"
    # 舊格式的 sources 沒有座標也沒有檔名，新版必須兩者俱全，
    # 否則成員 D 拿到 'S1!C5:C10' 不知道該開 11 份裡的哪一份
    assert record["sources"][0] == {"file": "t.xlsx", "sheet": "S1", "range": "C5:C10"}
    assert record["block_chain"]
    assert record["assumption_statement"]


def test_一致性檢查抓出不存在的metric引用():
    r = AnalysisResult()
    r.add(_metric("exists", 1.0))
    r.charts.append(ChartSpec(
        chart_id="bad", chart_type="line", title="t",
        category_metric_map={"s": ["exists", "ghost"]},
        categories=["a", "b"],
    ))
    problems = r.verify_consistency()
    assert problems and "ghost" in problems[0]


def test_一致性檢查抓出x軸長度不符():
    r = AnalysisResult()
    r.add(_metric("a", 1.0))
    r.charts.append(ChartSpec(
        chart_id="bad", chart_type="line", title="t",
        category_metric_map={"s": ["a"]}, categories=["x", "y", "z"],
    ))
    assert any("x 軸" in p for p in r.verify_consistency())


def test_serialize_value邊界():
    assert serialize_value(None) is None
    assert serialize_value(1 / 3) == round(1 / 3, VALUE_PRECISION)
    assert serialize_value(1318372.0) == 1318372.0


def test_顯示值不參與計算(result):
    """display_value 只影響呈現；下游拿它回頭算會累積四捨五入誤差。"""
    assert format_display(12.066050672347986, "%") == "12.07%"
    payload = result.analysis_payload()
    metric = next(m for m in payload["metrics"] if m["metric_id"] == "m_precise")
    assert metric["value"] != 12.07