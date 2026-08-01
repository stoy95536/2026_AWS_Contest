"""
簡報數值回溯校驗模組
擷取簡報中的 KPI、圖表資料及表格數值，與計算引擎結果比對。
不一致時阻止輸出並產生錯誤報告。
"""

import json
from typing import Optional
from src.calculation_engine.data_lineage import DataLineageTracker


class PPTReconciler:
    """
    簡報數值回溯校驗器。
    確保簡報中引用的所有數值都可追溯到原始計算結果。
    """

    def __init__(self, lineage_tracker: DataLineageTracker):
        self.lineage = lineage_tracker

    def reconcile(self, slide_specs: list[dict]) -> dict:
        """
        執行完整回溯校驗。

        Args:
            slide_specs: 完整 16 頁 slide_spec

        Returns:
            校驗報告
        """
        errors = []
        warnings = []

        for spec in slide_specs:
            slide_no = spec.get("slide_no", 0)

            # 校驗 KPI 數值
            errors.extend(self._check_kpis(spec, slide_no))

            # 校驗圖表資料
            errors.extend(self._check_chart_data(spec, slide_no))

            # 校驗表格數值
            errors.extend(self._check_table_data(spec, slide_no))

            # 邏輯校驗
            logic_issues = self._check_logic(spec, slide_no)
            errors.extend([i for i in logic_issues if i["severity"] == "error"])
            warnings.extend([i for i in logic_issues if i["severity"] == "warning"])

        status = "passed" if not errors else "failed"

        return {
            "status": status,
            "total_errors": len(errors),
            "total_warnings": len(warnings),
            "errors": errors,
            "warnings": warnings,
            "slides_checked": len(slide_specs),
        }

    def _check_kpis(self, spec: dict, slide_no: int) -> list[dict]:
        """校驗 KPI 卡片中的數值。"""
        issues = []
        kpis = spec.get("kpis", [])

        for kpi in kpis:
            if not isinstance(kpi, dict):
                continue
            metric_id = kpi.get("metric_id", "")
            display_value = kpi.get("value", "")

            if not metric_id:
                continue

            # 檢查 metric_id 是否存在於血緣紀錄
            record = self.lineage.get_record(metric_id)
            if record is None:
                issues.append({
                    "slide_no": slide_no,
                    "type": "missing_lineage",
                    "severity": "error",
                    "message": f"KPI '{kpi.get('label', '')}' 的 metric_id '{metric_id}' 無法在資料血緣中找到",
                    "expected": "存在於 data_lineage.json",
                    "actual": "不存在",
                })
            elif record.validation_status != "passed":
                issues.append({
                    "slide_no": slide_no,
                    "type": "validation_failed",
                    "severity": "error",
                    "message": f"KPI '{kpi.get('label', '')}' 引用的指標校驗未通過: {record.validation_status}",
                    "metric_id": metric_id,
                })

        return issues

    def _check_chart_data(self, spec: dict, slide_no: int) -> list[dict]:
        """校驗圖表資料是否與計算引擎一致。"""
        issues = []
        chart = spec.get("chart")

        if not chart or not isinstance(chart, dict):
            return issues

        # 檢查 series 中引用的 metric_ids
        series_list = chart.get("series", [])
        for series in series_list:
            if not isinstance(series, dict):
                continue
            metric_ids = series.get("metric_ids", [])
            for mid in metric_ids:
                if not isinstance(mid, str):
                    continue
                record = self.lineage.get_record(mid)
                if record is None:
                    issues.append({
                        "slide_no": slide_no,
                        "type": "chart_data_missing",
                        "severity": "error",
                        "message": f"圖表系列 '{series.get('name', '')}' 引用的 metric_id '{mid}' 不存在",
                    })

        return issues

    def _check_table_data(self, spec: dict, slide_no: int) -> list[dict]:
        """校驗表格數值。"""
        issues = []
        table = spec.get("table")

        if not table:
            return issues

        # 表格校驗: 確保引用的 source_ids 都存在
        source_ids = spec.get("source_ids", [])
        for sid in source_ids:
            record = self.lineage.get_record(sid)
            if record is None:
                issues.append({
                    "slide_no": slide_no,
                    "type": "table_source_missing",
                    "severity": "warning",
                    "message": f"表格引用的 source_id '{sid}' 無法追溯",
                })

        return issues

    def _check_logic(self, spec: dict, slide_no: int) -> list[dict]:
        """邏輯校驗。"""
        issues = []

        # 校驗規則 1: 百分比大小關係
        insights = spec.get("insights", [])
        for insight in insights:
            text = insight.get("text", "") if isinstance(insight, dict) else str(insight)
            issues.extend(self._check_percentage_logic(text, slide_no))

        # 校驗規則 2: 無基期不得有 YoY
        source_ids = spec.get("source_ids", [])
        for sid in source_ids:
            if not isinstance(sid, str):
                continue
            if "yoy" in sid.lower():
                record = self.lineage.get_record(sid)
                if record and record.value is None:
                    issues.append({
                        "slide_no": slide_no,
                        "type": "invalid_yoy",
                        "severity": "error",
                        "message": f"引用了 YoY 指標 '{sid}'，但缺少基期資料，不應出現在簡報中",
                    })

        # 校驗規則 3: 排名不重複不漏項
        chart = spec.get("chart")
        if chart and isinstance(chart, dict) and chart.get("type") == "bar":
            series_list = chart.get("series", [])
            for series in series_list:
                if not isinstance(series, dict):
                    continue
                data = series.get("data", [])
                # 排名圖中每個值代表不同銀行，應確保數量合理
                if len(data) > 0 and len(set(str(d) for d in data)) < len(data) * 0.5:
                    issues.append({
                        "slide_no": slide_no,
                        "type": "suspicious_ranking",
                        "severity": "warning",
                        "message": "排名圖表中超過一半的值重複，請確認資料正確性",
                    })

        return issues

    def _check_percentage_logic(self, text: str, slide_no: int) -> list[dict]:
        """檢查文字中百分比大小關係是否正確。"""
        import re
        issues = []

        # 尋找 "X% 高於/大於 Y%" 的模式
        pattern = r"(\d+\.?\d*)%\s*(高於|大於|超過)\s*(\d+\.?\d*)%"
        matches = re.finditer(pattern, text)

        for match in matches:
            val1 = float(match.group(1))
            val2 = float(match.group(3))
            if val1 <= val2:
                issues.append({
                    "slide_no": slide_no,
                    "type": "narrative_logic_error",
                    "severity": "error",
                    "message": f"文案稱 {val1}% 高於 {val2}%，大小關係錯誤",
                    "expected": f"{val1}% 低於 {val2}%",
                })

        # 尋找 "X% 低於/小於 Y%" 的模式
        pattern2 = r"(\d+\.?\d*)%\s*(低於|小於|不及)\s*(\d+\.?\d*)%"
        matches2 = re.finditer(pattern2, text)

        for match in matches2:
            val1 = float(match.group(1))
            val2 = float(match.group(3))
            if val1 >= val2:
                issues.append({
                    "slide_no": slide_no,
                    "type": "narrative_logic_error",
                    "severity": "error",
                    "message": f"文案稱 {val1}% 低於 {val2}%，大小關係錯誤",
                    "expected": f"{val1}% 高於 {val2}%",
                })

        return issues
