"""
資料標準化模組
將附件四的 Excel 工作表轉為統一格式：
institution | period | metric | value | unit | source_file | source_sheet | source_cell

附件四結構：
  - Sheet 'P.5預期修正_流通卡數':     34 rows x 13 cols (金融機構名稱, 11401-11412)
  - Sheet 'P.5預期修正_當月簽帳金額': 34 rows x 13 cols
  - Sheet 'P.7預期修正_流通卡數':     34 rows x 14 cols (多一欄 流通卡數市佔率)
  - Sheet 'P.7預期修正_當月簽帳金額': 34 rows x 14 cols (多一欄 簽帳金額市佔率)

  Row 0: header (金融機構名稱, 11401, 11402, ..., 11412, [市佔率])
  Rows 1-32: 各銀行資料
  Row 33: 總計
"""

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd


@dataclass
class StandardRecord:
    """標準化資料紀錄。"""
    institution: str
    period: str  # 民國年月格式，如 "11401"
    metric: str
    value: Optional[float]
    unit: str
    source_file: str
    source_sheet: str
    source_cell: str
    raw_value: Optional[str] = None


class DataStandardizer:
    """將附件四 Excel 資料轉換為標準格式。"""

    # 工作表名稱到指標/單位的對應
    # P.7 含市佔率排名，優先使用；P.5 是原始資料
    SHEET_METRIC_MAP = {
        "P.5預期修正_流通卡數": ("流通卡數", "張"),
        "P.5預期修正_當月簽帳金額": ("當月簽帳金額", "千元"),
        "P.7預期修正_流通卡數": ("流通卡數", "張"),
        "P.7預期修正_當月簽帳金額": ("當月簽帳金額", "千元"),
    }

    # P.5 和 P.7 有相同指標但不同排序。
    # 載入策略：若同一指標 P.7 已經載入，則跳過 P.5 避免重複
    PREFERRED_SHEETS = {
        "流通卡數": "P.7預期修正_流通卡數",
        "當月簽帳金額": "P.7預期修正_當月簽帳金額",
    }

    # 單位倍率轉換（統一到基礎單位）
    UNIT_MULTIPLIER = {
        "張": 1,
        "萬張": 10000,
        "元": 1,
        "千元": 1000,
        "百萬元": 1_000_000,
        "億元": 100_000_000,
        "%": 0.01,
    }

    def __init__(self, source_file: str):
        self.source_file = source_file
        self.records: list[StandardRecord] = []
        self._loaded_metrics: set[str] = set()  # 追蹤已載入的指標

    def detect_metric_from_sheet_name(self, sheet_name: str) -> tuple[str, str]:
        """
        從工作表名稱偵測指標和單位。

        Returns:
            (metric_name, unit)
        """
        if sheet_name in self.SHEET_METRIC_MAP:
            return self.SHEET_METRIC_MAP[sheet_name]

        # 通用偵測
        if "流通卡數" in sheet_name:
            return ("流通卡數", "張")
        elif "有效卡數" in sheet_name:
            return ("有效卡數", "張")
        elif "簽帳金額" in sheet_name:
            return ("當月簽帳金額", "千元")
        elif "循環信用" in sheet_name:
            return ("循環信用餘額", "千元")
        elif "分期付款" in sheet_name:
            return ("分期付款餘額", "千元")
        elif "逾期" in sheet_name:
            return ("逾期放款比率", "%")
        elif "呆帳" in sheet_name:
            return ("呆帳比率", "%")
        elif "備抵" in sheet_name:
            return ("備抵呆帳提足率", "%")
        return (sheet_name, "未知")

    def standardize_sheet(
        self,
        df: pd.DataFrame,
        sheet_name: str,
        metric: str = None,
        unit: str = None,
    ) -> list[StandardRecord]:
        """
        將單一工作表 DataFrame 轉為標準記錄。

        附件四格式：
        - 第一欄: 金融機構名稱
        - 後續欄位: 11401, 11402, ..., 11412 (月份期間)
        - 可能有額外欄位如 '流通卡數市佔率'

        Args:
            df: 原始 DataFrame (header=row 0)
            sheet_name: 工作表名稱
            metric: 指標名稱 (若不指定則從工作表名偵測)
            unit: 單位

        Returns:
            標準化記錄清單
        """
        if metric is None or unit is None:
            detected_metric, detected_unit = self.detect_metric_from_sheet_name(sheet_name)
            metric = metric or detected_metric
            unit = unit or detected_unit

        # 避免 P.5/P.7 重複：若該指標已從 P.7 載入，跳過 P.5
        preferred = self.PREFERRED_SHEETS.get(metric)
        if preferred and preferred != sheet_name and metric in self._loaded_metrics:
            # 已經從優先的 P.7 工作表載入過了
            return []

        # 若是 P.5 但 P.7 尚未載入，也跳過（等 P.7 載入）
        if "P.5" in sheet_name and preferred and preferred != sheet_name:
            return []

        self._loaded_metrics.add(metric)

        records = []

        # 第一欄是機構名稱
        institution_col = df.columns[0]

        # 找出期間欄位 (格式: 5-6位數字如 11401)
        period_cols = []
        market_share_col = None
        for col in df.columns[1:]:
            col_str = str(col).strip()
            if re.match(r"^\d{5,6}$", col_str):
                period_cols.append(col)
            elif "市佔率" in col_str or "市占率" in col_str:
                market_share_col = col

        for _, row in df.iterrows():
            institution = str(row[institution_col]).strip() if pd.notna(row[institution_col]) else None
            if not institution or institution in ("None", "nan", ""):
                continue

            # 處理每個期間的值
            for period_col in period_cols:
                raw_value = row.get(period_col)
                period = str(int(period_col)) if isinstance(period_col, (int, float)) else str(period_col).strip()

                value = None
                if pd.notna(raw_value):
                    try:
                        value = float(raw_value)
                    except (ValueError, TypeError):
                        value = None

                record = StandardRecord(
                    institution=institution,
                    period=period,
                    metric=metric,
                    value=value,
                    unit=unit,
                    source_file=self.source_file,
                    source_sheet=sheet_name,
                    source_cell=f"{institution}@{period}",
                    raw_value=str(raw_value) if raw_value is not None else None,
                )
                records.append(record)

            # P.7 的工作表包含市佔率欄位，也要解析
            if market_share_col is not None:
                share_value = row.get(market_share_col)
                if pd.notna(share_value) and institution != "總計":
                    try:
                        share_float = float(share_value)
                        # 市佔率以小數表示 (0.153733 = 15.37%)
                        share_record = StandardRecord(
                            institution=institution,
                            period="11412",  # P.7 的市佔率是最新一期
                            metric=f"{metric}_市佔率",
                            value=share_float * 100,  # 轉為百分比
                            unit="%",
                            source_file=self.source_file,
                            source_sheet=sheet_name,
                            source_cell=f"{institution}@市佔率",
                            raw_value=str(share_value),
                        )
                        records.append(share_record)
                    except (ValueError, TypeError):
                        pass

        self.records.extend(records)
        return records

    def standardize_dataframe(
        self,
        df: pd.DataFrame,
        sheet_name: str,
        metric: str = None,
        unit: str = None,
    ) -> list[StandardRecord]:
        """統一介面：standardize_sheet 的別名。"""
        return self.standardize_sheet(df, sheet_name, metric, unit)

    def to_dataframe(self) -> pd.DataFrame:
        """將所有標準化記錄轉為 DataFrame。"""
        if not self.records:
            return pd.DataFrame(columns=[
                "institution", "period", "metric", "value", "unit",
                "source_file", "source_sheet", "source_cell", "raw_value",
            ])
        return pd.DataFrame([asdict(r) for r in self.records])

    def convert_unit(self, value: float, from_unit: str, to_unit: str) -> float:
        """單位轉換。"""
        if from_unit == to_unit:
            return value
        from_mult = self.UNIT_MULTIPLIER.get(from_unit, 1)
        to_mult = self.UNIT_MULTIPLIER.get(to_unit, 1)
        return value * from_mult / to_mult

    def get_institutions(self) -> list[str]:
        """取得所有機構名稱（排除總計）。"""
        institutions = set()
        for r in self.records:
            if r.institution != "總計":
                institutions.add(r.institution)
        return sorted(institutions)

    def get_periods(self) -> list[str]:
        """取得所有期間。"""
        periods = set()
        for r in self.records:
            if re.match(r"^\d{5,6}$", r.period):
                periods.add(r.period)
        return sorted(periods)
