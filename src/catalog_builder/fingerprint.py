"""
Layer 0：表頭指紋比對（runtime 動態建立，非開發期預建樣板庫）。

TASK1.md 原本設計是「命中開發期已知樣板則直接套用預定義 mapping」。但決賽
當天的 11 份檔案在開發期沒見過，預建的樣板庫命中率是 0——為這些測試檔算指紋
寫死 mapping 完全是白工。

改成 **runtime 建指紋**：跑第一張表時把表頭結構存進快取，同批次後續工作表
若結構完全相同就直接複用比對結果。決賽的 11 份裡「表1-2 按居住地」與
「表1-3 按國籍」這類同源報表結構高度雷同，複用能省下重複比對；而就算全部
都不相同，代價也只是快取全 miss，不會比沒有 Layer 0 更差。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .structure_detector import SheetStructure

T = TypeVar("T")


def sheet_fingerprint(structure: SheetStructure) -> str:
    """
    以「欄名序列 + 表頭層數」計算工作表結構指紋。

    刻意**不含**檔名、工作表名、資料列數——同一份報表的不同年度版本
    列數會變、檔名會變，但欄位結構不變，那才是能複用比對結果的部分。
    """
    payload = "\x1f".join(
        [str(len(structure.header_rows))]
        + [c.full_name for c in structure.columns]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class FingerprintCache(Generic[T]):
    """
    runtime 指紋快取。

    只在單次 Catalog 建置的生命週期內有效，不落地成檔案——落地的快取會在
    換一批輸入檔時變成過期的錯誤答案，風險遠大於省下的那點時間。
    """

    _store: dict[str, T] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, fingerprint: str) -> T | None:
        value = self._store.get(fingerprint)
        if value is None:
            self.misses += 1
        else:
            self.hits += 1
        return value

    def put(self, fingerprint: str, value: T) -> None:
        self._store.setdefault(fingerprint, value)

    @property
    def summary(self) -> dict:
        total = self.hits + self.misses
        return {
            "distinct_structures": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }