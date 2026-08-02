"""
輸出寫檔：JSON × 2 + Excel × 1，全部由同一個 AnalysisResult 產出。

Excel 不是「另一份報表」，而是同一份資料的另一種呈現。因此這裡不做任何
重新計算、重新篩選、重新排序——只是把 `AnalysisResult` 的內容排進儲存格。
任何在此處新增的運算邏輯都會讓 Excel 與 JSON 開始分岔。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .result import AnalysisResult, format_display, serialize_value

METRIC_SHEET = "Metrics"
CHART_SHEET = "ChartData"
LINEAGE_SHEET = "Lineage"
REVIEW_SHEET = "NeedsReview"


def _write_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_analysis_json(result: AnalysisResult, path: str | Path) -> Path:
    """`analysis_result.json`：metric + chart_data，交付成員 B 與 C。"""
    return _write_json(result.analysis_payload(), Path(path))


def write_lineage_json(result: AnalysisResult, path: str | Path) -> Path:
    """`data_lineage.json`：交付成員 D 做數值回溯校驗。"""
    return _write_json(result.lineage_payload(), Path(path))


def _metric_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "指標ID": m.metric_id,
            "指標名稱": m.metric_name,
            "數值": serialize_value(m.value),
            "顯示值": format_display(m.value, m.unit),
            "單位": m.unit,
            "期間": m.period,
            "計算公式": m.formula,
            "校驗狀態": m.validation_status,
            "校驗說明": m.validation_note or "",
            "計算假設": m.assumption_statement or "",
            "來源範圍": "; ".join(m.source_range_summary),
        }
        for m in result.metrics
    ])


def _chart_frame(result: AnalysisResult) -> pd.DataFrame:
    """
    圖表資料攤平成長表，一列一個資料點。

    每列都帶 `指標ID`——評審或組員在 Excel 上看到某個資料點覺得可疑，
    可以直接拿這個 ID 去 Lineage 分頁查它的積木鏈與原始儲存格。
    """
    rows = []
    for chart in result.charts:
        for name, metric_ids in chart.category_metric_map.items():
            for index, metric_id in enumerate(metric_ids):
                m = result.metric(metric_id)
                rows.append({
                    "圖表ID": chart.chart_id,
                    "圖表標題": chart.title,
                    "圖表類型": chart.chart_type,
                    "系列": name,
                    "X軸標籤": (
                        chart.categories[index]
                        if index < len(chart.categories) else ""
                    ),
                    "指標ID": metric_id,
                    "數值": serialize_value(m.value) if m else None,
                    "單位": chart.unit,
                    "校驗狀態": m.validation_status if m else "missing",
                })
    return pd.DataFrame(rows)


def _lineage_frame(result: AnalysisResult) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "指標ID": m.metric_id,
            "積木鏈": " → ".join(m.block_chain),
            "來源範圍": "; ".join(m.source_range_summary),
            "來源儲存格": "; ".join(m.source_cells[:10]),
            "計算假設": m.assumption_statement or "",
            "重試次數": m.attempts,
            "校驗狀態": m.validation_status,
        }
        for m in result.metrics
    ])


def _review_frame(result: AnalysisResult) -> pd.DataFrame:
    """
    待人工確認清單。

    刻意獨立成一個分頁而不是混在 Metrics 裡：不確定的東西攤在最顯眼的地方，
    比藏在某一欄的狀態碼裡誠實得多（鐵律 11）。
    """
    flagged = [
        m for m in result.metrics
        if m.validation_status in ("needs_manual_review", "failed", "na")
    ]
    return pd.DataFrame([
        {
            "指標ID": m.metric_id,
            "指標名稱": m.metric_name,
            "狀態": m.validation_status,
            "原因": m.validation_note or "",
            "來源範圍": "; ".join(m.source_range_summary),
        }
        for m in flagged
    ])


def write_analysis_excel(result: AnalysisResult, path: str | Path) -> Path:
    """
    `analysis_result.xlsx`：交付評審的「與簡報同步的分析結果 Excel」。

    四個分頁對應四種讀者：Metrics 給看結論的、ChartData 給對圖的、
    Lineage 給查來源的、NeedsReview 給挑毛病的。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    frames = {
        METRIC_SHEET: _metric_frame(result),
        CHART_SHEET: _chart_frame(result),
        LINEAGE_SHEET: _lineage_frame(result),
        REVIEW_SHEET: _review_frame(result),
    }

    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        for sheet_name, frame in frames.items():
            # 空 DataFrame 直接寫會產生沒有表頭的空分頁，補一列說明比較好讀
            if frame.empty:
                frame = pd.DataFrame([{"說明": "無資料"}])
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
            _autofit(writer.sheets[sheet_name], frame)

    return target


def _autofit(worksheet, frame: pd.DataFrame, max_width: int = 60) -> None:
    """粗略調整欄寬。評審要一眼看懂，擠成一團的表格會扣印象分。"""
    from openpyxl.utils import get_column_letter

    for index, column in enumerate(frame.columns, start=1):
        longest = max(
            [len(str(column))] + [len(str(v)) for v in frame[column].head(200)]
        )
        worksheet.column_dimensions[get_column_letter(index)].width = min(
            longest + 4, max_width
        )


def write_all(result: AnalysisResult, output_dir: str | Path) -> dict[str, Path]:
    """一次輸出三份檔案，回傳各自路徑。"""
    out = Path(output_dir)
    return {
        "analysis_json": write_analysis_json(result, out / "analysis_result.json"),
        "analysis_excel": write_analysis_excel(result, out / "analysis_result.xlsx"),
        "lineage_json": write_lineage_json(result, out / "data_lineage.json"),
    }