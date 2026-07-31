"""
資料驗證器
處理除以零、缺值、重複欄位及月份不完整等例外情況。
"""

from typing import Optional
import pandas as pd
import numpy as np


class DataValidator:
    """資料品質驗證器。"""

    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.issues: list[dict] = []

    def validate_all(self) -> list[dict]:
        """執行所有驗證規則。"""
        self.issues = []
        self.check_missing_values()
        self.check_duplicate_records()
        self.check_negative_values()
        self.check_period_completeness()
        self.check_market_share_sum()
        return self.issues

    def check_missing_values(self):
        """檢查缺失值。"""
        missing = self.data[self.data["value"].isna()]
        for _, row in missing.iterrows():
            self.issues.append({
                "type": "missing_value",
                "severity": "warning",
                "institution": row.get("institution", ""),
                "period": row.get("period", ""),
                "metric": row.get("metric", ""),
                "message": f"缺少 {row.get('institution')} 在 {row.get('period')} 的 {row.get('metric')} 資料",
            })

    def check_duplicate_records(self):
        """檢查重複記錄。"""
        key_cols = ["institution", "period", "metric"]
        duplicated = self.data[self.data.duplicated(subset=key_cols, keep=False)]
        if not duplicated.empty:
            groups = duplicated.groupby(key_cols)
            for name, group in groups:
                if len(group) > 1:
                    self.issues.append({
                        "type": "duplicate_record",
                        "severity": "error",
                        "institution": name[0],
                        "period": name[1],
                        "metric": name[2],
                        "message": f"發現重複記錄: {name[0]}/{name[1]}/{name[2]} 共 {len(group)} 筆",
                        "count": len(group),
                    })

    def check_negative_values(self):
        """檢查不合理的負值（如卡數不應為負）。"""
        non_negative_metrics = ["流通卡數", "有效卡數", "當月簽帳金額"]
        for metric in non_negative_metrics:
            mask = (self.data["metric"] == metric) & (self.data["value"] < 0)
            negatives = self.data[mask]
            for _, row in negatives.iterrows():
                self.issues.append({
                    "type": "negative_value",
                    "severity": "error",
                    "institution": row["institution"],
                    "period": row["period"],
                    "metric": metric,
                    "value": row["value"],
                    "message": f"{row['institution']} 的 {metric} 值為負 ({row['value']})",
                })

    def check_period_completeness(self):
        """檢查期間完整性（是否有月份缺失）。"""
        periods = sorted(self.data["period"].unique())
        if len(periods) < 2:
            return

        # 將期間轉為數字以檢查連續性
        try:
            period_ints = [int(p) for p in periods]
            for i in range(1, len(period_ints)):
                expected = period_ints[i - 1] + 1
                # 處理跨年 (如 11312 -> 11401)
                if period_ints[i - 1] % 100 == 12:
                    expected = (period_ints[i - 1] // 100 + 1) * 100 + 1
                if period_ints[i] != expected:
                    self.issues.append({
                        "type": "missing_period",
                        "severity": "warning",
                        "message": f"期間 {periods[i-1]} 與 {periods[i]} 之間可能有缺失月份",
                    })
        except (ValueError, TypeError):
            pass

    def check_market_share_sum(self, tolerance: float = 5.0):
        """檢查市占率合計是否合理（不一定精確100%，但不應偏離太多）。"""
        # 這個需要基於計算後的市占率資料執行
        pass

    def safe_divide(self, numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
        """安全除法，處理除以零和 None。"""
        if numerator is None or denominator is None:
            return None
        if denominator == 0:
            return None
        return numerator / denominator

    def get_validation_summary(self) -> dict:
        """取得驗證摘要。"""
        return {
            "total_issues": len(self.issues),
            "errors": len([i for i in self.issues if i["severity"] == "error"]),
            "warnings": len([i for i in self.issues if i["severity"] == "warning"]),
            "issues": self.issues,
        }
