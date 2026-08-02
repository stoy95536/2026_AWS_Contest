"""
把 `data_lineage.json` 載回成員 D 的 `DataLineageTracker` 物件。

存在的理由：D 的 `PPTReconciler.__init__(lineage_tracker)` 吃的是**物件**不是
檔案，而 `DataLineageTracker` 只有 `export_json()`、**沒有任何讀檔方法**——
所以他拿到我輸出的 JSON 其實載不進去，這條線在程式層面原本是斷的。

此模組刻意放在 `src/export/` 而不是加進 `src/calculation_engine/data_lineage.py`：
那是 D 正在動的檔案，決賽前一天去改別人正在編輯的檔案只會製造合併衝突。
他只需要多 import 一個函式，自己的類別一行不動。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.calculation_engine.data_lineage import DataLineageTracker


def load_lineage_tracker(path: str | Path) -> DataLineageTracker:
    """
    讀取 `data_lineage.json`，回傳可直接餵給 `PPTReconciler` 的 tracker。

        from src.export.lineage_loader import load_lineage_tracker
        tracker = load_lineage_tracker("outputs/data_lineage.json")
        reconciler = PPTReconciler(tracker)

    只還原 `LineageRecord` 既有的欄位；新架構多出來的 `block_chain` 與
    `assumption_statement` 留在 JSON 裡供人查閱，不硬塞進他的 dataclass——
    那會改動他的型別定義。
    """
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    tracker = DataLineageTracker()

    for metric_id, record in payload.get("records", {}).items():
        tracker.record(
            metric_id=metric_id,
            metric_name=record.get("metric_name", ""),
            value=record.get("value"),
            formula=record.get("formula", ""),
            sources=record.get("sources", []),
            institution=record.get("institution", ""),
            period=record.get("period", ""),
            unit=record.get("unit", ""),
            validation_status=record.get("validation_status", "passed"),
        )

    return tracker


def load_metrics(path: str | Path) -> dict[str, dict[str, Any]]:
    """
    讀取 `analysis_result.json` 的 metrics，回傳 `{metric_id: metric}`。

    給任何需要按 id 查值的人用（成員 B 引用 KPI、成員 D 核對 slide_spec）。
    以 dict 回傳而非 list，是因為下游全部都是「拿 metric_id 找值」的用法。
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {m["metric_id"]: m for m in payload.get("metrics", [])}


def load_chart_series(path: str | Path) -> dict[str, dict[str, Any]]:
    """
    讀取 chart_data，整理成成員 C 的 `chart_factory` 直接可用的形狀。

        for chart_id, chart in load_chart_series("outputs/analysis_result.json").items():
            factory.create_bar_chart(
                ..., categories=chart["categories"], series_data=chart["series_data"]
            )

    `series_data` 就是 `{系列名: [值...]}`，對應 `create_bar_chart` 的參數簽名。
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        chart["chart_data_id"]: {
            "chart_type": chart["chart_type"],
            "title": chart["title"],
            "unit": chart["unit"],
            "categories": chart["categories"],
            "series_data": {s["name"]: s["values"] for s in chart["series"]},
            "metric_ids": {s["name"]: s["metric_ids"] for s in chart["series"]},
            "validation_status": chart["validation_status"],
        }
        for chart in payload.get("chart_data", [])
    }