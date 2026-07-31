"""
指標計算引擎
所有數值計算由本模組以確定性方式完成，LLM 不直接負責精確計算。
支援指標：
- 流通卡數、有效卡數、有效卡率
- 當月簽帳金額、平均每卡簽帳金額
- 月增率 MoM、年增率 YoY
- 市占率、市占率變化
- 循環信用餘額、分期付款餘額
- 逾期率、呆帳率、備抵呆帳提足率
- 排名、Top N
"""

from typing import Optional
import pandas as pd
import numpy as np

from .data_lineage import DataLineageTracker


class MetricCalculator:
    """確定性指標計算引擎。"""

    def __init__(self, data: pd.DataFrame, lineage_tracker: Optional[DataLineageTracker] = None):
        """
        Args:
            data: 標準化後的資料 DataFrame，需含:
                  institution, period, metric, value, unit, source_file, source_sheet, source_cell
            lineage_tracker: 資料血緣追蹤器
        """
        self.data = data.copy()
        self.lineage = lineage_tracker or DataLineageTracker()

    def _get_value(self, institution: str, period: str, metric: str) -> Optional[float]:
        """取得指定機構/期間/指標的值。"""
        mask = (
            (self.data["institution"] == institution)
            & (self.data["period"] == period)
            & (self.data["metric"] == metric)
        )
        result = self.data.loc[mask, "value"]
        if result.empty or result.isna().all():
            return None
        return float(result.iloc[0])

    def _get_market_total(self, period: str, metric: str) -> Optional[float]:
        """
        取得某指標在特定期間的市場總計。
        優先使用 '總計' 行的值，避免重複加總。
        """
        # 優先使用已有的 '總計' 資料
        total = self._get_value("總計", period, metric)
        if total is not None:
            return total

        # 若無總計行，手動加總（排除 '總計' 本身）
        mask = (
            (self.data["period"] == period)
            & (self.data["metric"] == metric)
            & (self.data["institution"] != "總計")
        )
        values = self.data.loc[mask, "value"].dropna()
        if values.empty:
            return None
        return float(values.sum())

    def effective_card_rate(self, institution: str, period: str) -> Optional[float]:
        """
        有效卡率 = 有效卡數 / 流通卡數 * 100

        Returns:
            百分比值 或 None (若缺資料)
        """
        effective = self._get_value(institution, period, "有效卡數")
        circulating = self._get_value(institution, period, "流通卡數")

        if effective is None or circulating is None or circulating == 0:
            return None

        result = effective / circulating * 100
        self.lineage.record(
            metric_id=f"effective_card_rate_{institution}_{period}",
            metric_name="有效卡率",
            value=result,
            formula="有效卡數 / 流通卡數 * 100",
            sources=[
                {"metric": "有效卡數", "value": effective},
                {"metric": "流通卡數", "value": circulating},
            ],
            institution=institution,
            period=period,
        )
        return round(result, 2)

    def avg_purchase_per_card(
        self, institution: str, period: str, denominator: str = "有效卡數"
    ) -> Optional[float]:
        """
        平均每卡簽帳金額 = 當月簽帳金額 / 有效卡數(或流通卡數)

        Args:
            denominator: "有效卡數" 或 "流通卡數"
        """
        purchase = self._get_value(institution, period, "當月簽帳金額")
        cards = self._get_value(institution, period, denominator)

        if purchase is None or cards is None or cards == 0:
            return None

        result = purchase / cards
        self.lineage.record(
            metric_id=f"avg_purchase_per_card_{institution}_{period}",
            metric_name="平均每卡簽帳金額",
            value=result,
            formula=f"當月簽帳金額 / {denominator}",
            sources=[
                {"metric": "當月簽帳金額", "value": purchase},
                {"metric": denominator, "value": cards},
            ],
            institution=institution,
            period=period,
        )
        return round(result, 2)

    def mom_growth(self, institution: str, current_period: str, prev_period: str, metric: str) -> Optional[float]:
        """
        月增率 MoM = (本期 - 前期) / 前期 * 100

        若無前期資料則回傳 None（不自行產生）。
        """
        current = self._get_value(institution, current_period, metric)
        previous = self._get_value(institution, prev_period, metric)

        if current is None or previous is None or previous == 0:
            return None

        result = (current - previous) / previous * 100
        self.lineage.record(
            metric_id=f"mom_{metric}_{institution}_{current_period}",
            metric_name=f"{metric}_月增率",
            value=result,
            formula="(本期 - 前期) / 前期 * 100",
            sources=[
                {"metric": metric, "period": current_period, "value": current},
                {"metric": metric, "period": prev_period, "value": previous},
            ],
            institution=institution,
            period=current_period,
        )
        return round(result, 2)

    def yoy_growth(self, institution: str, current_period: str, prev_year_period: str, metric: str) -> Optional[float]:
        """
        年增率 YoY = (本期 - 去年同期) / 去年同期 * 100

        重要：若沒有提供前一年同期資料，不得自行產生 YoY，回傳 None。
        """
        current = self._get_value(institution, current_period, metric)
        prev_year = self._get_value(institution, prev_year_period, metric)

        if current is None or prev_year is None:
            self.lineage.record(
                metric_id=f"yoy_{metric}_{institution}_{current_period}",
                metric_name=f"{metric}_年增率",
                value=None,
                formula="(本期 - 去年同期) / 去年同期 * 100",
                sources=[],
                institution=institution,
                period=current_period,
                validation_status="N/A - 缺少去年同期資料",
            )
            return None

        if prev_year == 0:
            return None

        result = (current - prev_year) / prev_year * 100
        self.lineage.record(
            metric_id=f"yoy_{metric}_{institution}_{current_period}",
            metric_name=f"{metric}_年增率",
            value=result,
            formula="(本期 - 去年同期) / 去年同期 * 100",
            sources=[
                {"metric": metric, "period": current_period, "value": current},
                {"metric": metric, "period": prev_year_period, "value": prev_year},
            ],
            institution=institution,
            period=current_period,
        )
        return round(result, 2)

    def market_share(self, institution: str, period: str, metric: str) -> Optional[float]:
        """
        市占率 = 該機構值 / 市場總計 * 100

        分母必須是同期間市場總計。
        不計算 '總計' 行的市占率。
        """
        if institution == "總計":
            return None

        inst_value = self._get_value(institution, period, metric)
        total = self._get_market_total(period, metric)

        if inst_value is None or total is None or total == 0:
            return None

        result = inst_value / total * 100
        self.lineage.record(
            metric_id=f"market_share_{metric}_{institution}_{period}",
            metric_name=f"{metric}_市占率",
            value=result,
            formula="機構值 / 市場總計 * 100",
            sources=[
                {"metric": metric, "institution": institution, "value": inst_value},
                {"metric": f"{metric}_市場總計", "value": total},
            ],
            institution=institution,
            period=period,
        )
        return round(result, 2)

    def market_share_change(
        self, institution: str, current_period: str, prev_period: str, metric: str
    ) -> Optional[float]:
        """市占率變化 = 本期市占率 - 前期市占率 (百分點)。"""
        current_share = self.market_share(institution, current_period, metric)
        prev_share = self.market_share(institution, prev_period, metric)

        if current_share is None or prev_share is None:
            return None

        result = current_share - prev_share
        self.lineage.record(
            metric_id=f"market_share_change_{metric}_{institution}_{current_period}",
            metric_name=f"{metric}_市占率變化",
            value=result,
            formula="本期市占率 - 前期市占率",
            sources=[
                {"metric": f"{metric}_市占率", "period": current_period, "value": current_share},
                {"metric": f"{metric}_市占率", "period": prev_period, "value": prev_share},
            ],
            institution=institution,
            period=current_period,
        )
        return round(result, 4)

    def ranking(self, period: str, metric: str, top_n: Optional[int] = None, ascending: bool = False) -> pd.DataFrame:
        """
        排名計算（由程式排序，不能由 LLM 憑語意排列）。

        Args:
            period: 期間
            metric: 指標
            top_n: 取前 N 名
            ascending: 是否升序

        Returns:
            含 institution, value, rank 的 DataFrame
        """
        mask = (
            (self.data["period"] == period)
            & (self.data["metric"] == metric)
            & (self.data["institution"] != "總計")  # 排除總計
        )
        subset = self.data.loc[mask, ["institution", "value"]].dropna(subset=["value"]).copy()
        subset = subset.sort_values("value", ascending=ascending).reset_index(drop=True)
        subset["rank"] = range(1, len(subset) + 1)

        if top_n:
            subset = subset.head(top_n)

        return subset

    def scale_vs_growth_quadrant(
        self, period: str, prev_period: str, scale_metric: str, growth_metric: str
    ) -> pd.DataFrame:
        """
        計算規模 vs 成長象限資料。

        Returns:
            含 institution, scale, growth, quadrant 的 DataFrame
        """
        institutions = self.data["institution"].unique()
        results = []

        for inst in institutions:
            scale = self._get_value(inst, period, scale_metric)
            current = self._get_value(inst, period, growth_metric)
            prev = self._get_value(inst, prev_period, growth_metric)

            if scale is None or current is None or prev is None or prev == 0:
                continue

            growth = (current - prev) / prev * 100
            results.append({
                "institution": inst,
                "scale": scale,
                "growth": round(growth, 2),
            })

        df = pd.DataFrame(results)
        if df.empty:
            return df

        # 用中位數劃分象限
        scale_median = df["scale"].median()
        growth_median = df["growth"].median()

        def assign_quadrant(row):
            if row["scale"] >= scale_median and row["growth"] >= growth_median:
                return "高規模高成長"
            elif row["scale"] >= scale_median and row["growth"] < growth_median:
                return "高規模低成長"
            elif row["scale"] < scale_median and row["growth"] >= growth_median:
                return "低規模高成長"
            else:
                return "低規模低成長"

        df["quadrant"] = df.apply(assign_quadrant, axis=1)
        return df

    def get_all_periods(self) -> list[str]:
        """取得資料中所有期間。"""
        return sorted(self.data["period"].unique().tolist())

    def get_all_institutions(self) -> list[str]:
        """取得資料中所有機構。"""
        return sorted(self.data["institution"].unique().tolist())

    def get_all_metrics(self) -> list[str]:
        """取得資料中所有指標。"""
        return sorted(self.data["metric"].unique().tolist())

    def compute_prev_period(self, period: str) -> str:
        """計算前一個月的期間。"""
        year = int(period[:3])
        month = int(period[3:])
        if month == 1:
            return f"{year - 1}12"
        return f"{year}{month - 1:02d}"

    def compute_prev_year_period(self, period: str) -> str:
        """計算去年同期。"""
        year = int(period[:3])
        month = period[3:]
        return f"{year - 1}{month}"
