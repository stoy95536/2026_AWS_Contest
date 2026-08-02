"""
同源分析結果（TASK1.md 鐵律 13）。

**一份計算結果，三種序列化**：metric JSON、chart_data、Excel 全部從同一個
`AnalysisResult` 物件產出，不各算各的。兩份各自計算是「簡報數字與 Excel
不符」的最常見成因——命題文件點名的痛點——因為兩邊的四捨五入、篩選條件、
排序會慢慢分岔，而且沒有任何地方會報錯。

圖表資料**由 metric 組成**，不另外計算：一條折線就是 N 個 metric 的值。
這讓「chart_data、Excel、metric JSON 三方一致」（驗收標準）成為結構上的
必然，而不是靠事後比對去維持。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.calculation_engine.executor import MetricResult

SCHEMA_VERSION = "1.0"

VALUE_PRECISION = 10
"""序列化前統一保留的小數位數。

**存在的理由是 Excel 只保存 15 位有效數字**，而 Python float 有 17 位。
不統一的話 `12.066050672347986` 寫進 Excel 會變成 `12.06605067234799`，
JSON 與 Excel 就對不起來——實測 177 個指標裡有 35 個出現這種差異。

差異量級只有 1e-15（相對差 3e-16，機器精度等級），對任何結論都毫無影響，
但驗收標準要求「chart_data、analysis_result.xlsx 與 metric JSON 三方數值
一致」，評審拿 `==` 比對就會看到不符。與其解釋浮點誤差，不如從源頭統一。

取 10 位小數（約 12 位有效數字）遠超這些指標的實際精度需求，
又安全落在 Excel 能精確表示的範圍內。"""


def serialize_value(value: float | None) -> float | None:
    """
    所有輸出路徑的唯一取值入口。

    JSON、chart_data、Excel 一律經過這裡，三者才不可能分岔——
    任何繞過它直接取 `m.value` 的地方都會重新引入精度不一致。
    """
    if value is None:
        return None
    return round(float(value), VALUE_PRECISION)


def format_display(value: float | None, unit: str) -> str:
    """
    產生給人看的顯示值。

    **顯示值只影響呈現，不影響計算**：下游一律用 `value` 原始精度做運算，
    絕不拿 display_value 回頭參與計算，否則四捨五入誤差會層層累積。
    """
    if value is None:
        return "N/A"
    if unit in ("%", "percent"):
        return f"{value:.2f}%"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


@dataclass
class ChartSpec:
    """
    圖表規格：宣告「這張圖由哪些 metric 組成」，不含任何自行計算的數字。

    成員 C 拿 chart_data 畫原生圖表；每個資料點都能回指到一個 metric_id，
    成員 D 做回溯校驗時就能一路查到原始儲存格。
    """

    chart_id: str
    chart_type: str
    title: str
    category_metric_map: dict[str, list[str]]
    """系列名 → metric_id 清單。清單順序即 x 軸順序。"""

    categories: list[str] = field(default_factory=list)
    """x 軸標籤，長度須與每個系列的 metric_id 數相同。"""

    unit: str = ""
    note: str = ""


@dataclass
class AnalysisResult:
    """整份分析結果，所有輸出的唯一來源。"""

    metrics: list[MetricResult] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    prompt: str = ""
    catalog_summary: dict[str, Any] = field(default_factory=dict)
    data_summary: dict[str, Any] = field(default_factory=dict)
    """給成員 B 的 `PlannerAgent.plan_structure(data_summary)` 直接使用。

    鍵名 `{institutions, metrics, periods, record_count}` 沿用他既有的簽名，
    他一行程式都不必改。`institutions` 這個名字是信用卡時代留下的，在旅遊
    資料裡裝的是維度值（國家、年齡層、交通工具）——與其要他改欄位名，
    不如由我這邊填成他預期的形狀，決賽前一天不是重構介面的時機。"""

    generated_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        self._index = {m.metric_id: m for m in self.metrics}

    def metric(self, metric_id: str) -> MetricResult | None:
        return self._index.get(metric_id)

    def add(self, result: MetricResult) -> None:
        self.metrics.append(result)
        self._index[result.metric_id] = result

    # ---------- 序列化 ----------

    def metric_payloads(self) -> list[dict[str, Any]]:
        """
        metric JSON（TASK1.md 5.2）。

        欄位名對齊組員既有的 `schemas/metric.schema.json`，並補上該 schema
        尚未涵蓋、但 TASK1.md 明文要求的 `block_chain` 與 `assumption_statement`。
        多給欄位不會讓組員的程式壞掉（該 schema 未鎖 additionalProperties）。
        """
        payloads = []
        for m in self.metrics:
            payload: dict[str, Any] = {
                "metric_id": m.metric_id,
                "metric_name": m.metric_name,
                "value": serialize_value(m.value),
                "display_value": format_display(m.value, m.unit),
                "unit": m.unit,
                "period": m.period,
                "formula": m.formula,
                "validation_status": m.validation_status,
                "block_chain": m.block_chain,
                "source": self._source_refs(m),
            }
            if m.validation_note:
                payload["validation_note"] = m.validation_note
            if m.assumption_statement:
                payload["assumption_statement"] = m.assumption_statement
            payloads.append(payload)
        return payloads

    def chart_payloads(self) -> list[dict[str, Any]]:
        """
        chart_data，格式依 CLAUDE.md「對外介面」第（二）節。

        `series` 是**扁平**的 `{name, values}`——成員 C 的
        `chart_factory.create_bar_chart(categories, series_data)` 直接吃得下，
        不需要他再攤平一次。

        每個系列額外附 `metric_ids`，與 `values` 同序等長。這一欄同時服務兩個人：
        成員 D 的 `ppt_reconciler._check_chart_data` 讀的正是
        `chart["series"][i]["metric_ids"]`；而它也讓圖上任何一個數字都能回查
        到 metric 與原始儲存格。

        N/A 照實輸出 null，不補 0——圖表上的斷點是真實資訊，
        補 0 會畫出一條假的下探曲線。
        """
        payloads = []
        for chart in self.charts:
            series = []
            sources: list[dict[str, str]] = []
            statuses: list[str] = []

            for name, metric_ids in chart.category_metric_map.items():
                values, ids = [], []
                for mid in metric_ids:
                    m = self.metric(mid)
                    values.append(serialize_value(m.value) if m else None)
                    ids.append(mid)
                    if m:
                        statuses.append(m.validation_status)
                        for ref in m.source_refs:
                            if ref not in sources:
                                sources.append(ref)
                series.append({"name": name, "values": values, "metric_ids": ids})

            payloads.append({
                "chart_data_id": chart.chart_id,
                "chart_type": chart.chart_type,
                "title": chart.title,
                "unit": chart.unit,
                "categories": chart.categories,
                "series": series,
                "source": sources,
                # 整張圖的狀態取最差值：只要有一個點沒過，這張圖就不該被當成
                # 完全可信——把它藏起來只會讓錯誤數字更容易被畫進簡報
                "validation_status": (
                    "passed" if statuses and set(statuses) == {"passed"}
                    else ("na" if statuses else "missing")
                ),
                "note": chart.note,
            })
        return payloads

    def analysis_payload(self) -> dict[str, Any]:
        """`outputs/analysis_result.json` 的完整內容。"""
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "prompt": self.prompt,
            "summary": {
                "metric_count": len(self.metrics),
                "chart_count": len(self.charts),
                "passed": sum(1 for m in self.metrics if m.validation_status == "passed"),
                "na": sum(1 for m in self.metrics if m.validation_status == "na"),
                "needs_manual_review": sum(
                    1 for m in self.metrics
                    if m.validation_status == "needs_manual_review"
                ),
                "catalog": self.catalog_summary,
            },
            "data_summary": self.data_summary,
            "metrics": self.metric_payloads(),
            "chart_data": self.chart_payloads(),
        }

    def lineage_payload(self) -> dict[str, Any]:
        """
        `outputs/data_lineage.json`。

        **外層結構刻意沿用舊格式**（`generated_at` / `total_records` /
        `records` 以 metric_id 為鍵），讓成員 D 的 `ppt_reconciler` 不必改
        程式就能繼續用 `get_record(metric_id).validation_status`。

        差別在 `sources`：舊格式是 `{metric, institution, value}`，沒有任何
        儲存格座標，人無法打開 Excel 逐格核對。新版每筆都帶 `file / sheet /
        range`，這是「可追溯」四個字的實質內容。
        """
        records = {}
        for m in self.metrics:
            records[m.metric_id] = {
                "metric_id": m.metric_id,
                "metric_name": m.metric_name,
                "value": serialize_value(m.value),
                "display_value": format_display(m.value, m.unit),
                "unit": m.unit,
                "period": m.period,
                "formula": m.formula,
                "block_chain": m.block_chain,
                "assumption_statement": m.assumption_statement,
                "sources": self._source_refs(m),
                "source_cells": m.source_cells,
                "validation_status": m.validation_status,
                "validation_note": m.validation_note,
                "attempts": m.attempts,
                "timestamp": self.generated_at,
            }
        return {
            "generated_at": self.generated_at,
            "total_records": len(records),
            "records": records,
        }

    @staticmethod
    def _source_refs(m: MetricResult) -> list[dict[str, str]]:
        """符合 metric.schema.json 的 source 結構：{file, sheet, range}。

        直接取執行引擎產出的結構化來源，不從顯示字串反解——
        檔名可能含 `!`，反解會拆錯。"""
        return m.source_refs

    # ---------- 三方一致性 ----------

    def verify_consistency(self) -> list[str]:
        """
        檢查 chart_data 引用的 metric 是否都存在（驗收標準：三方數值一致）。

        因為圖表值是從 metric 查表得來、不是另外算的，數值不可能不一致；
        真正會出錯的是**引用了不存在的 metric_id**——那會讓圖上出現空洞。
        """
        problems = []

        # 重複 metric_id 是「同一個 id 對應兩個不同數字」的靜默錯誤：
        # 實測兩份檔案的同名欄位曾產生重複 id，值相差 3,784 人。
        # 下游按 id 查值時拿到哪一個取決於寫入順序，無法預期。
        from collections import Counter

        counts = Counter(m.metric_id for m in self.metrics)
        for metric_id, count in counts.items():
            if count > 1:
                values = {m.value for m in self.metrics if m.metric_id == metric_id}
                problems.append(
                    f"metric_id '{metric_id}' 重複 {count} 次"
                    + (f"，且數值不同：{sorted(v for v in values if v is not None)}"
                       if len(values) > 1 else "")
                )

        for chart in self.charts:
            for name, metric_ids in chart.category_metric_map.items():
                missing = [mid for mid in metric_ids if mid not in self._index]
                if missing:
                    problems.append(
                        f"圖表 '{chart.chart_id}' 的系列 '{name}' 引用了不存在的 "
                        f"metric_id：{missing}"
                    )
                if chart.categories and len(metric_ids) != len(chart.categories):
                    problems.append(
                        f"圖表 '{chart.chart_id}' 的系列 '{name}' 有 "
                        f"{len(metric_ids)} 個資料點，但 x 軸有 "
                        f"{len(chart.categories)} 個標籤"
                    )
        return problems