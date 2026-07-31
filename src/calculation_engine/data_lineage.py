"""
資料血緣追蹤模組
紀錄每個衍生數值的來源與公式，確保簡報中的數值可追溯。
"""

import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class LineageRecord:
    """單一數值的血緣紀錄。"""
    metric_id: str
    metric_name: str
    value: Optional[float]
    display_value: str = ""
    unit: str = ""
    period: str = ""
    institution: str = ""
    formula: str = ""
    sources: list[dict] = field(default_factory=list)
    validation_status: str = "passed"
    timestamp: str = ""
    rounding_rule: str = "四捨五入至小數第二位"


class DataLineageTracker:
    """
    資料血緣追蹤器。
    記錄所有計算過程的來源、公式與校驗狀態。
    """

    def __init__(self):
        self.records: dict[str, LineageRecord] = {}

    def record(
        self,
        metric_id: str,
        metric_name: str,
        value: Optional[float],
        formula: str,
        sources: list[dict],
        institution: str = "",
        period: str = "",
        unit: str = "",
        validation_status: str = "passed",
        rounding_rule: str = "四捨五入至小數第二位",
    ):
        """記錄一筆資料血緣。"""
        display_value = self._format_display_value(value, unit)

        record = LineageRecord(
            metric_id=metric_id,
            metric_name=metric_name,
            value=value,
            display_value=display_value,
            unit=unit,
            period=period,
            institution=institution,
            formula=formula,
            sources=sources,
            validation_status=validation_status,
            timestamp=datetime.now().isoformat(),
            rounding_rule=rounding_rule,
        )
        self.records[metric_id] = record

    def _format_display_value(self, value: Optional[float], unit: str) -> str:
        """格式化顯示值。"""
        if value is None:
            return "N/A"
        if unit == "%":
            return f"{value:.2f}%"
        if abs(value) >= 100_000_000:
            return f"{value / 100_000_000:.2f} 億{unit}"
        if abs(value) >= 10_000:
            return f"{value / 10_000:.1f} 萬{unit}"
        return f"{value:,.0f} {unit}"

    def get_record(self, metric_id: str) -> Optional[LineageRecord]:
        """查詢特定指標的血緣紀錄。"""
        return self.records.get(metric_id)

    def validate_value(self, metric_id: str, expected_value: float, tolerance: float = 0.01) -> bool:
        """校驗數值是否在允許誤差範圍內。"""
        record = self.records.get(metric_id)
        if record is None or record.value is None:
            return False
        return abs(record.value - expected_value) <= tolerance

    def export_json(self, output_path: str):
        """匯出資料血緣為 JSON 檔案。"""
        export_data = {
            "generated_at": datetime.now().isoformat(),
            "total_records": len(self.records),
            "records": {k: asdict(v) for k, v in self.records.items()},
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

    def export_summary(self) -> list[dict]:
        """匯出摘要供其他模組使用。"""
        return [
            {
                "metric_id": r.metric_id,
                "metric_name": r.metric_name,
                "value": r.value,
                "display_value": r.display_value,
                "institution": r.institution,
                "period": r.period,
                "validation_status": r.validation_status,
            }
            for r in self.records.values()
        ]

    def get_failed_validations(self) -> list[LineageRecord]:
        """取得未通過校驗的記錄。"""
        return [r for r in self.records.values() if r.validation_status != "passed"]
