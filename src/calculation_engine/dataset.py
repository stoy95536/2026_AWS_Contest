"""
資料集：把多份 Excel 攤平成單一長表，供積木運算。

Data Catalog 只記「欄位的地址與意思」，不含任何列的數值（TASK1.md 1e）；
真正的數字由本模組直接回原始 Excel 讀取，一次讀入記憶體供整個 session 使用。
LLM 永遠讀 Catalog、永遠不碰這張長表——它只負責指定要對哪個 canonical 欄位
做什麼運算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.catalog_builder.field_matcher import build_field_cards
from src.catalog_builder.loaders import iter_workbooks
from src.catalog_builder.normalizer import normalize_sheet
from src.catalog_builder.structure_detector import detect_structure

from .blocks.types import (
    COL_CANONICAL,
    COL_COL,
    COL_DIMENSION,
    COL_FILE,
    COL_PERIOD,
    COL_ROLE,
    COL_ROW,
    COL_SHEET,
    COL_VALUE,
    LONG_COLUMNS,
)


@dataclass
class FieldMeta:
    """canonical 欄位的中繼資料，執行引擎用來驗證參數與組血緣。"""

    canonical_name: str
    source_column: str
    unit: str
    cell_range: str
    aggregation_role: str
    file_name: str
    sheet_name: str
    confidence: float


@dataclass
class Dataset:
    """整批 Excel 的長表 + canonical 欄位索引。"""

    frame: pd.DataFrame
    fields: dict[str, FieldMeta] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def canonical_names(self) -> set[str]:
        """白名單：執行引擎只接受這些欄位名（鐵律 5，防欄位幻覺）。"""
        return set(self.fields)

    def periods(self) -> list[int]:
        values = self.frame[COL_PERIOD].dropna().unique()
        return sorted(int(v) for v in values)

    def to_data_summary(self) -> dict[str, Any]:
        """
        組出成員 B 的 `PlannerAgent.plan_structure(data_summary)` 預期的形狀。

        鍵名沿用他既有的簽名 `{institutions, metrics, periods, record_count}`，
        讓他一行程式都不用改：

          metrics      量測概念（來臺旅客、觀光外匯收入…），即 canonical 名稱的
                       前綴——「這份資料在量什麼」
          institutions 維度值（日本、韓國、30至39歲…），即 canonical 名稱的末段
                       ——「按什麼拆分」。這個鍵名是信用卡時代留下的，在旅遊
                       資料裡裝的是國家與分類；決賽前一天不是重構共用介面的時機

        他的 `classify_data` 用關鍵字把 metrics 分成量能／比率／風險類，
        `_infer_domain` 把兩者併成文字猜領域——兩者都吃字串清單，
        所以這裡給的是名稱不是數值。
        """
        concepts: list[str] = []
        dimensions: list[str] = []
        for canonical in self.fields:
            head, _, tail = canonical.partition("_")
            if head and head not in concepts:
                concepts.append(head)
            leaf = tail.rsplit("_", 1)[-1].strip() if tail else ""
            if leaf and leaf not in dimensions:
                dimensions.append(leaf)

        return {
            "metrics": concepts,
            "institutions": dimensions,
            "periods": [str(p) for p in self.periods()],
            "record_count": len(self.frame),
            "field_count": len(self.fields),
            "files": sorted({m.file_name for m in self.fields.values()}),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "record_count": len(self.frame),
            "field_count": len(self.fields),
            "period_range": (
                [self.periods()[0], self.periods()[-1]] if self.periods() else []
            ),
            "file_count": self.frame[COL_FILE].nunique(),
        }


def build_dataset(data_dir: str | Path) -> Dataset:
    """
    掃描目錄下所有 Excel，建出長表與欄位索引。

    與 `catalog_builder.build_catalog` 走同一條解析路徑（同一個
    structure_detector / normalizer / field_matcher），確保 Catalog 描述的
    欄位與長表裡的資料是同一批東西——兩邊各解析一次會產生對不上的風險。
    """
    rows: list[dict[str, Any]] = []
    fields: dict[str, FieldMeta] = {}
    warnings: list[str] = []

    for path, workbook, loader_warnings in iter_workbooks(data_dir):
        warnings.extend(loader_warnings)
        try:
            for sheet_name in workbook.sheetnames:
                structure = detect_structure(workbook[sheet_name])
                if not structure.is_parsable:
                    warnings.append(f"{path.name}!{sheet_name}: 結構偵測失敗，略過")
                    continue

                normalized = normalize_sheet(structure, path.name)
                cards = {c.source_column: c for c in build_field_cards(normalized)}

                for record in normalized.records:
                    card = cards.get(record.dimension)
                    if card is None:
                        continue

                    # 同名 canonical 出現在多份檔案時保留第一個中繼資料，
                    # 但長表照樣收兩份資料——跨檔比較正是 join 的用途。
                    fields.setdefault(
                        card.canonical_name,
                        FieldMeta(
                            canonical_name=card.canonical_name,
                            source_column=card.source_column,
                            unit=card.unit,
                            cell_range=card.cell_range,
                            aggregation_role=card.aggregation_role,
                            file_name=card.file_name,
                            sheet_name=card.sheet_name,
                            confidence=card.confidence,
                        ),
                    )

                    rows.append({
                        COL_PERIOD: record.period,
                        COL_CANONICAL: card.canonical_name,
                        COL_DIMENSION: record.dimension,
                        COL_VALUE: record.value,
                        COL_FILE: path.name,
                        COL_SHEET: record.cell.sheet,
                        COL_ROW: record.cell.row,
                        COL_COL: record.cell.col,
                        COL_ROLE: card.aggregation_role,
                    })
        finally:
            workbook.close()

    frame = pd.DataFrame(rows, columns=LONG_COLUMNS)
    if not frame.empty:
        # period 用可為空的整數型別：找不到期間欄的工作表仍要能進長表，
        # 用 float 會讓 2024 顯示成 2024.0，寫進血緣與簡報都很難看
        frame[COL_PERIOD] = frame[COL_PERIOD].astype("Int64")

    return Dataset(frame=frame, fields=fields, warnings=warnings)