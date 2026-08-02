"""
LLM 規劃器測試（全部以 mock 進行，不呼叫 AWS）。

決賽當天憑證才會換發，開發期無法對真實 Bedrock 驗證，因此這裡把「回應解析」
與「白名單約束」用 mock 釘死。真正連得上時只有網路層是新的，
其餘邏輯已經被這些測試涵蓋。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calculation_engine.blocks import BLOCK_REGISTRY  # noqa: E402
from src.calculation_engine.blocks.types import LONG_COLUMNS  # noqa: E402
from src.calculation_engine.dataset import Dataset, FieldMeta  # noqa: E402
from src.calculation_engine.executor import Executor  # noqa: E402
from src.calculation_engine.llm_planner import (  # noqa: E402
    TOOL_NAME,
    LLMPlanner,
    LLMPlannerError,
    build_tool_config,
    compact_catalog,
)


@pytest.fixture
def dataset() -> Dataset:
    rows = [
        {"period": 2024, "canonical": "來臺旅客_日本", "dimension": "日本 Japan",
         "value": 1300.0, "file": "f1.xlsx", "sheet": "S1", "row": 5, "col": 3,
         "aggregation_role": "detail"},
        {"period": 2024, "canonical": "來臺旅客_總計", "dimension": "總計 Total",
         "value": 2000.0, "file": "f1.xlsx", "sheet": "S1", "row": 5, "col": 4,
         "aggregation_role": "total"},
    ]
    frame = pd.DataFrame(rows, columns=LONG_COLUMNS)
    frame["period"] = frame["period"].astype("Int64")
    fields = {
        "來臺旅客_日本": FieldMeta(
            "來臺旅客_日本", "日本 Japan", "人次", "C5", "detail", "f1.xlsx", "S1", 0.9),
        "來臺旅客_總計": FieldMeta(
            "來臺旅客_總計", "總計 Total", "人次", "D5", "total", "f1.xlsx", "S1", 0.9),
    }
    return Dataset(frame=frame, fields=fields)


def _response(payload: dict) -> dict:
    """組出 Bedrock Converse 的 toolUse 回應。"""
    return {"output": {"message": {"content": [{"toolUse": {
        "name": TOOL_NAME, "input": payload,
    }}]}}}


def _planner_with(response: dict) -> LLMPlanner:
    planner = LLMPlanner(model_id="test-model", region="us-west-2")
    client = MagicMock()
    client.converse.return_value = response
    planner._client = client
    return planner


VALID_PLAN = {
    "metrics": [{
        "metric_id": "japan_2024",
        "metric_name": "2024 日本旅客",
        "unit": "人次",
        "period": "2024",
        "assumption_statement": "取自 f1.xlsx 的日本欄 2024 年度值",
        "steps": [
            {"id": "f", "block": "filter", "input": "dataset",
             "params": {"column": "file", "operator": "==", "value": "f1.xlsx"}},
            {"id": "c", "block": "filter", "input": "f",
             "params": {"column": "canonical", "operator": "==", "value": "來臺旅客_日本"}},
            {"id": "s", "block": "group_sum", "input": "c",
             "params": {"group_col": "period", "detail_only": False}},
        ],
        "output": "s",
    }],
    "charts": [{
        "chart_id": "c1", "chart_type": "bar", "title": "測試",
        "categories": ["2024"],
        "series": [{"name": "日本", "metric_ids": ["japan_2024"]}],
    }],
}


# --------------------------------------------------------------------------
# Catalog 壓縮：LLM 看得到語意線索，但看不到整欄資料
# --------------------------------------------------------------------------

def test_壓縮後含判斷語意所需的四項(dataset):
    text = compact_catalog(dataset)
    assert "來臺旅客_日本" in text      # canonical，供 LLM 指定欄位
    assert "人次" in text               # 單位，避免拿人次除以百分比
    assert "detail" in text and "total" in text  # 角色，避免明細與彙總混算
    assert "f1.xlsx" in text            # 檔名，同名欄位跨檔時必須指定


def test_壓縮後不含整欄資料(dataset):
    """
    Catalog 是「一欄一張卡」不是「一格一張卡」。

    給整欄數值等於讓 LLM 有機會直接抄數字，「LLM 不碰數字」就破功了。
    """
    text = compact_catalog(dataset)
    assert text.count("1,300") + text.count("1300") <= 1  # 至多一個樣本值


def test_欄位過多時截斷並明說(dataset):
    text = compact_catalog(dataset, limit=1)
    assert "已截斷" in text  # 不能讓 LLM 以為看到的是全部


# --------------------------------------------------------------------------
# Tool schema：結構上就點不到白名單以外的積木
# --------------------------------------------------------------------------

def test_積木名以enum鎖死():
    """鐵律 12：LLM 端用 structured output 約束只能點白名單積木。"""
    schema = build_tool_config()["tools"][0]["toolSpec"]["inputSchema"]["json"]
    step = schema["properties"]["metrics"]["items"]["properties"]["steps"]["items"]
    assert set(step["properties"]["block"]["enum"]) == set(BLOCK_REGISTRY)


def test_強制呼叫工具不給自由發揮():
    assert build_tool_config()["toolChoice"] == {"tool": {"name": TOOL_NAME}}


def test_假設聲明列為必填():
    """鐵律 6：模糊語意要寫下假設繼續，不是停下來問使用者。"""
    schema = build_tool_config()["tools"][0]["toolSpec"]["inputSchema"]["json"]
    required = schema["properties"]["metrics"]["items"]["required"]
    assert "assumption_statement" in required


# --------------------------------------------------------------------------
# 回應解析
# --------------------------------------------------------------------------

def test_解析合法計畫(dataset):
    plan = _planner_with(_response(VALID_PLAN)).plan("測試", dataset)
    assert len(plan.recipes) == 1
    recipe = plan.recipes[0]
    assert recipe.metric_id == "japan_2024"
    assert recipe.assumption_statement
    assert len(recipe.steps) == 3
    assert len(plan.charts) == 1


def test_計畫可直接餵給執行引擎(dataset):
    """LLM 產的配方必須是執行引擎吃得下的形狀，否則整條鏈是斷的。"""
    plan = _planner_with(_response(VALID_PLAN)).plan("測試", dataset)
    result = Executor(dataset).execute(plan.recipes[0])
    assert result.value == 1300.0
    assert result.validation_status == "passed"
    assert result.assumption_statement


def test_llm未呼叫工具時報錯(dataset):
    response = {"output": {"message": {"content": [{"text": "我覺得應該是 1300"}]}}}
    with pytest.raises(LLMPlannerError, match="未呼叫工具"):
        _planner_with(response).plan("測試", dataset)


def test_空計畫報錯(dataset):
    with pytest.raises(LLMPlannerError, match="沒有任何指標"):
        _planner_with(_response({"metrics": []})).plan("測試", dataset)


def test_配方缺必要欄位時報錯(dataset):
    bad = {"metrics": [{"metric_id": "x", "steps": []}]}
    with pytest.raises(LLMPlannerError, match="格式錯誤"):
        _planner_with(_response(bad)).plan("測試", dataset)


def test_bedrock異常包裝成規劃錯誤(dataset):
    """憑證過期、逾時、額度用盡都走這條，由呼叫方決定是否落回規則式。"""
    planner = LLMPlanner(model_id="test", region="us-west-2")
    client = MagicMock()
    client.converse.side_effect = RuntimeError("ExpiredTokenException")
    planner._client = client
    with pytest.raises(LLMPlannerError, match="Bedrock 呼叫失敗"):
        planner.plan("測試", dataset)


# --------------------------------------------------------------------------
# 白名單防護：LLM 亂寫時執行引擎要擋下來
# --------------------------------------------------------------------------

def test_llm捏造欄位會被執行引擎擋下(dataset):
    plan_payload = {"metrics": [{
        "metric_id": "x", "metric_name": "x", "unit": "人次", "period": "2024",
        "assumption_statement": "a",
        "steps": [{"id": "c", "block": "filter", "input": "dataset",
                   "params": {"column": "canonical", "operator": "==",
                              "value": "來臺旅客_瓦干達"}}],
        "output": "c",
    }]}
    plan = _planner_with(_response(plan_payload)).plan("測試", dataset)
    from src.calculation_engine.executor import ExecutionError

    with pytest.raises(ExecutionError, match="不存在於 Data Catalog"):
        Executor(dataset).execute(plan.recipes[0])


def test_重試時把失敗原因帶給llm(dataset):
    planner = _planner_with(_response(VALID_PLAN))
    planner.plan("測試", dataset, feedback="上次分母抓錯了")
    sent = planner._client.converse.call_args.kwargs["messages"][0]["content"][0]["text"]
    assert "上次分母抓錯了" in sent
    assert "重新輸出完整計畫" in sent


def test_溫度為零確保可重現(dataset):
    """驗收標準：同一 Prompt 重跑結果一致。"""
    planner = _planner_with(_response(VALID_PLAN))
    planner.plan("測試", dataset)
    config = planner._client.converse.call_args.kwargs["inferenceConfig"]
    assert config["temperature"] == 0.0