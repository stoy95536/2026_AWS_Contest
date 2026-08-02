"""
Stage 1 總成：把多份 Excel 建成 Data Catalog。

Data Catalog 是**給 Stage 2 的 LLM 讀的**（TASK1.md 1e），不是交付組員的成果——
組員拿到的是 analysis_result.json / .xlsx / data_lineage.json。因此這份 JSON
的設計目標只有一個：讓 LLM 用最少 token 知道「有哪些欄位、在哪裡、什麼意思」，
好挑選積木參數，而不必讀 11 份原始 Excel。

**一欄一張卡，不是一格一張卡**：不記錄任何「列」的實際數值，只留 3 筆樣本值
供 LLM 判斷語意。真正的數字永遠在計算時由積木回原始 Excel 讀。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .field_matcher import (
    CONFIDENCE_AUTO,
    CONFIDENCE_MIN,
    FieldCard,
    build_field_cards,
    build_field_dictionary,
    chinese_part,
)
from .fingerprint import FingerprintCache, sheet_fingerprint
from .loaders import iter_workbooks
from .normalizer import NormalizedSheet, normalize_sheet
from .structure_detector import detect_structure

CATALOG_VERSION = "1.0"


PERIOD_DIMENSION = "年度"
"""期間維度的統一名稱。

**刻意不沿用原始表頭文字**：表1-2 的期間欄表頭最下層是「Year」、其他檔案是
「年度 Year」，照抄會產生「Year」與「年度」兩個不同的關聯鍵，跨檔案 join
就接不起來。期間欄是靠數值特徵認出來的（normalizer.detect_period_column），
既然是結構性識別，就該給結構性名稱。"""


def _dimension_columns(normalized: NormalizedSheet, structure) -> list[str]:
    """期間欄與文字標籤欄——LLM 用來做 filter／group 的維度。"""
    return [PERIOD_DIMENSION] if normalized.period_column is not None else []


def _join_keys(sheet_dimensions: list[tuple[str, list[str]]]) -> list[dict[str, Any]]:
    """
    推斷跨檔案關聯鍵（TASK1.md 1d）。

    共同維度出現在兩份以上檔案才算關聯鍵——只出現在一份的維度無從 join。
    """
    by_dimension: dict[str, set[str]] = defaultdict(set)
    for file_name, dimensions in sheet_dimensions:
        for dim in dimensions:
            by_dimension[dim].add(file_name)

    return [
        {"dimension": dim, "files": sorted(files)}
        for dim, files in sorted(by_dimension.items())
        if len(files) >= 2
    ]


def build_catalog(data_dir: str | Path) -> dict[str, Any]:
    """
    掃描目錄下所有 Excel，建出完整 Data Catalog。

    Layer 0 指紋在此生效：結構完全相同的工作表直接複用欄位卡的比對結果，
    不重跑 Layer 1。
    """
    cache: FingerprintCache[list[FieldCard]] = FingerprintCache()
    catalog_files: list[dict[str, Any]] = []
    all_cards: list[FieldCard] = []
    sheet_dimensions: list[tuple[str, list[str]]] = []
    review: list[dict[str, Any]] = []

    for path, workbook, loader_warnings in iter_workbooks(data_dir):
        for message in loader_warnings:
            review.append({"file": "(輸入檔)", "sheet": "", "reason": message})
        try:
            sheets_out: list[dict[str, Any]] = []

            for sheet_name in workbook.sheetnames:
                structure = detect_structure(workbook[sheet_name])
                if not structure.is_parsable:
                    review.append({
                        "file": path.name,
                        "sheet": sheet_name,
                        "reason": "；".join(structure.warnings) or "結構偵測失敗",
                    })
                    continue

                normalized = normalize_sheet(structure, path.name)
                fingerprint = sheet_fingerprint(structure)

                # Layer 0：結構指紋命中則複用比對方法，省下重複的 Layer 1
                cached = cache.get(fingerprint)
                method = "fingerprint" if cached else "rule"
                cards = build_field_cards(normalized, alignment_method=method)
                if cached is None:
                    cache.put(fingerprint, cards)

                all_cards.extend(cards)
                dimensions = _dimension_columns(normalized, structure)
                sheet_dimensions.append((path.name, dimensions))

                for card in cards:
                    if card.needs_review:
                        review.append({
                            "canonical_name_guess": card.canonical_name,
                            "source_column": card.source_column,
                            "file": card.file_name,
                            "sheet": card.sheet_name,
                            "confidence": round(card.confidence, 3),
                            "reason": "；".join(card.notes) or "信心低於門檻",
                        })

                # 異常值按「欄」彙總，不按「格」逐筆列。同一欄裡 40 個負數是
                # 一個待確認的欄位語意問題，不是 40 個獨立問題——逐格列出只會
                # 讓真正需要人看的其他問題被洗掉。
                by_column: dict[str, list[str]] = defaultdict(list)
                for record in normalized.anomalies:
                    by_column[record.dimension].append(record.cell.a1)
                for dimension, cells in by_column.items():
                    review.append({
                        "canonical_name_guess": dimension,
                        "source_column": dimension,
                        "file": path.name,
                        "sheet": sheet_name,
                        "cells": cells[:5],
                        "affected_cell_count": len(cells),
                        "reason": "量值欄含負數，疑似小計調整或缺值標記，不應直接納入加總",
                    })

                sheets_out.append({
                    "sheet_name": structure.sheet_name,
                    "fingerprint": fingerprint,
                    "header_rows": structure.header_rows,
                    "data_start_row": structure.data_start_row,
                    "data_end_row": structure.data_end_row,
                    "canonical_fields": [
                        c.to_dict() for c in cards if not c.needs_review
                    ],
                    "dimension_columns": dimensions,
                    "warnings": structure.warnings + normalized.warnings,
                })

            if sheets_out:
                catalog_files.append({
                    "file_name": path.name,
                    "sheet_topic": chinese_part(path.stem),
                    "sheets": sheets_out,
                })
        finally:
            workbook.close()

    usable = [c for c in all_cards if not c.needs_review]
    return {
        "catalog_version": CATALOG_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "confidence_thresholds": {"auto": CONFIDENCE_AUTO, "minimum": CONFIDENCE_MIN},
        "summary": {
            "file_count": len(catalog_files),
            "field_count": len(usable),
            "high_confidence_field_count": sum(1 for c in usable if c.is_auto),
            "needs_manual_review_count": len(review),
            "fingerprint_cache": cache.summary,
        },
        "files": catalog_files,
        # 詞典只留「同一概念出現在多份檔案」的條目——單一來源的欄位資訊已經
        # 完整記在 files[].sheets[].canonical_fields，重複一遍只是灌爆 LLM context。
        # 詞典的價值在於告訴 LLM「這兩欄是同一件事，可以 join 或比較」。
        "field_dictionary": {
            k: v for k, v in build_field_dictionary(usable).items() if len(v) > 1
        },
        "join_keys": _join_keys(sheet_dimensions),
        "needs_manual_review": review,
    }


def write_catalog(catalog: dict[str, Any], output_path: str | Path) -> Path:
    """輸出 Catalog JSON。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path