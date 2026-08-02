"""
Layer 1：規則式欄位語意比對。

TASK1.md 1b 的核心主張——**比對「數值的結構特徵」而非欄名字串本身**：
即使欄名亂寫、順序打亂、中英夾雜，只要數值統計特徵不變，信心分數就穩定。
這是「換領域也能用」的關鍵，不是死背這 11 份的欄名。

因此本模組的比對訊號有三路，字串只佔其一：
  1. 數值結構特徵（值域、量級、整數性、單調性）——最穩，欄名怎麼寫都不影響
  2. 單位關鍵字（人次／美元／%／夜）——中英雙語表頭的通用線索
  3. 字串相似度（rapidfuzz）——只用來合併「同義但寫法略異」的欄名

不讓 LLM 當第一線的理由見 TASK1.md 1b：成本、可重現性、錯誤可見性。
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from rapidfuzz import fuzz

from .normalizer import NormalizedSheet
from .structure_detector import ColumnInfo

# --- 信心門檻（TASK1.md 5.4 兩道門檻）---

CONFIDENCE_AUTO = 0.85
"""達此信心自動採用，不需人工介入。"""

CONFIDENCE_MIN = 0.6
"""低於此信心不採用，改列入 needs_manual_review。

介於 0.6～0.85 之間者採用但標記，讓人事後抽查——這是「非阻斷式」設計：
不中斷流程問使用者，但把不確定性攤開來（鐵律 11）。"""

FUZZY_MERGE_THRESHOLD = 92
"""rapidfuzz 相似度達此值才合併成同一個 canonical 欄位。

刻意訂高：合併錯了會讓兩個不同國家的數字被當成同一欄加總，
是「悄悄算錯」型的錯誤，比不合併嚴重得多。"""

BASE_FIELD_CONFIDENCE = 0.9
"""欄位識別基準分：有明確欄名、有儲存格範圍、有充足樣本。

再乘上單位可靠度得到最終信心。上限刻意壓在 0.9 而非 1.0——
規則式比對再穩也不該宣稱百分之百，留一格給人的判斷。"""

MIN_SAMPLE_COUNT = 3
"""少於此筆數值的欄位不足以判定語意，信心壓到門檻以下。"""

# 單位關鍵字 → 標準單位。中英並列，因為政府報表一律雙語表頭。
_UNIT_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("%", "百分比", "比率", "佔比", "占比", "成長率", "增率", "rate", "ratio", "share"), "%"),
    (("美元", "us$", "usd", "expenditure"), "美元"),
    (("夜", "night"), "夜"),
    (("人次", "人數", "旅客", "遊客", "visitor", "arrival", "departure", "persons", "person"), "人次"),
    (("元", "金額", "amount"), "元"),
]

# 彙總欄關鍵字。順序有意義：先判總計再判小計，「總計」含「計」字容易互相誤判。
_AGGREGATION_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("總計", "grand total"), "total"),
    (("小計", "sub-total", "sub total", "subtotal"), "subtotal"),
    (("合計", "total"), "total"),
    (("其他", "其它", "未列明", "others", "unstated", "other"), "residual"),
]

# 「日本 Japan」→「日本」：切在第一個純英文詞之前
_ASCII_WORD = re.compile(r"(?:^|\s)[A-Za-z][A-Za-z.\-'&/()]*")
# 沖掉表名裡的流水編號：「表1-3-歷年來臺旅客按國籍分」→「歷年來臺旅客按國籍分」
_TABLE_PREFIX = re.compile(r"^表?\s*\d+[-–]\d+[-–]?\s*")
_LEADING_YEARS = re.compile(r"^歷年\s*")


def chinese_part(text: str) -> str:
    """
    取出中英並列表頭的中文部分。

    「日本 Japan」→「日本」、「9歲及以下 9 years and Under」→「9歲及以下」、
    「成長率 Rate of increase(%)」→「成長率」。

    切在第一個「以空白起頭的純英文詞」之前，因此像「9歲」開頭的數字會被保留，
    不會被當成英文切掉。若整串都是英文（如純英文表頭），原樣回傳。
    """
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return ""
    if m := _ASCII_WORD.search(cleaned):
        head = cleaned[: m.start()].strip()
        if head:
            return head
    return cleaned


@dataclass
class NumericProfile:
    """
    欄位的數值結構特徵——比欄名可靠的那一路訊號。

    這些特徵在換領域後依然成立：百分比欄永遠落在 0–100，人次欄永遠是大整數，
    所以拿它們做比對，決賽當天遇到沒見過的欄名也不會失效。
    """

    count: int
    min_value: float
    max_value: float
    median_value: float
    all_integer: bool
    within_percent_range: bool
    magnitude: int
    """量級，log10(中位數絕對值) 取整。人次類約 5～7，百分比類約 0～2。"""

    has_negative: bool

    @classmethod
    def from_values(cls, values: list[float]) -> "NumericProfile | None":
        clean = [v for v in values if v is not None]
        if not clean:
            return None
        med = median(abs(v) for v in clean) or 0.0
        return cls(
            count=len(clean),
            min_value=min(clean),
            max_value=max(clean),
            median_value=median(clean),
            all_integer=all(float(v).is_integer() for v in clean),
            within_percent_range=all(abs(v) <= 100 for v in clean),
            magnitude=int(math.log10(med)) if med > 0 else 0,
            has_negative=any(v < 0 for v in clean),
        )

    def compatibility(self, other: "NumericProfile") -> float:
        """
        兩欄的數值特徵相容度 0～1。

        量級差距是主訊號：人次欄（量級 5）與百分比欄（量級 1）就算欄名相同
        也絕不該合併——那會把「日本旅客人次」和「日本佔比」混為一談。
        """
        score = 1.0
        score -= min(abs(self.magnitude - other.magnitude) * 0.25, 0.6)
        if self.within_percent_range != other.within_percent_range:
            score -= 0.25
        if self.all_integer != other.all_integer:
            score -= 0.1
        return max(score, 0.0)


def _match_unit_keyword(text: str) -> str | None:
    haystack = text.lower()
    for keywords, unit in _UNIT_KEYWORDS:
        if any(k in haystack for k in keywords):
            return unit
    return None


def infer_unit(
    column: ColumnInfo, profile: NumericProfile | None, sheet_context: str = ""
) -> tuple[str, float]:
    """
    推斷欄位單位，回傳 (單位, 可靠度 0～1)。

    三段式：欄位表頭關鍵字 → 工作表／檔名關鍵字 → 數值結構特徵。

    第二段是必要的：「日本 Japan」這種欄名本身沒有任何單位線索，但它所在的
    工作表叫「歷年來臺旅客-按國籍」，單位顯然是人次。少了這段，整份報表裡
    所有以「分類值」命名的欄位（國家、年齡層、交通工具）全都會判不出單位。

    第三段只給結構性描述（「整數計數」而非「人次」），不硬掰領域單位——
    大整數在旅遊資料是人次，換個領域可能是金額（鐵律 11：寧可標示不確定）。
    """
    if unit := _match_unit_keyword(column.full_name):
        return unit, 1.0
    if sheet_context and (unit := _match_unit_keyword(sheet_context)):
        return unit, 0.95

    if profile is None:
        return "未知", 0.3
    if profile.within_percent_range and not profile.all_integer:
        return "%", 0.8
    if profile.all_integer and profile.magnitude >= 3:
        return "整數計數", 0.7
    return "未知", 0.3


def infer_aggregation_role(column: ColumnInfo) -> str:
    """
    判定欄位是明細還是彙總，回傳 detail／subtotal／total／residual。

    **這是防止「悄悄算錯」的關鍵標記**。表1-3 的東南亞群組有 6 個國家明細欄
    （G~L）、1 個殘差欄（M 東南亞其他地區）、1 個小計欄（N 東南亞小計）。
    若積木把整個群組加總，會變成「六國 + 殘差 + 小計」——小計重複計、殘差又
    倒扣，答案錯得無跡可循。少了這個標記，執行引擎沒有任何依據能擋下來。

    residual（殘差欄）另有陷阱：實測 M 欄 = 小計 − 已列名加總，而小計早年
    未填為 0，導致殘差變成整個加總的負值。這種欄位不是資料，是公式副產物。
    """
    haystack = column.leaf_name.lower()
    for keywords, role in _AGGREGATION_KEYWORDS:
        if any(k in haystack for k in keywords):
            return role
    return "detail"


def sheet_measure_concept(sheet_name: str, file_name: str) -> str:
    """
    從工作表／檔名推出「這張表在量什麼」，作為 canonical 名稱的前綴。

    「歷年來臺旅客-按國籍」→「來臺旅客」、「歷年觀光外匯收入」→「觀光外匯收入」。
    規則：去掉表號與「歷年」，再切在「按」或「-」之前——中文統計報表的命名
    慣例是「{量測概念}按{分類維度}分」，這個切法不綁任何特定領域。
    """
    raw = sheet_name or file_name
    raw = _TABLE_PREFIX.sub("", str(raw).replace(".xlsx", ""))
    raw = _LEADING_YEARS.sub("", raw).strip()
    for sep in ("-", "按"):
        if sep in raw:
            head = raw.split(sep)[0].strip()
            if head:
                return head
    return raw or "數值"


@dataclass
class FieldCard:
    """Data Catalog 的「一欄一張卡」（TASK1.md 1e）。只記欄位的地址與意思，不記任何列的數值。"""

    canonical_name: str
    source_column: str
    unit: str
    dtype: str
    cell_range: str
    sample_values: list[float]
    confidence: float
    alignment_method: str
    file_name: str
    sheet_name: str
    aggregation_role: str = "detail"
    profile: NumericProfile | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_auto(self) -> bool:
        return self.confidence >= CONFIDENCE_AUTO

    @property
    def needs_review(self) -> bool:
        return self.confidence < CONFIDENCE_MIN

    def to_dict(self) -> dict[str, Any]:
        """輸出成 Catalog JSON 的欄位卡。刻意不含 profile，避免灌爆 LLM context。"""
        card = {
            "canonical_name": self.canonical_name,
            "source_column": self.source_column,
            "unit": self.unit,
            "dtype": self.dtype,
            "cell_range": self.cell_range,
            "sample_values": self.sample_values,
            "confidence": round(self.confidence, 3),
            "alignment_method": self.alignment_method,
            # 給 LLM 與執行引擎判斷「這欄能不能跟同群組其他欄一起加總」
            "aggregation_role": self.aggregation_role,
        }
        if self.notes:
            card["notes"] = self.notes
        return card


def build_field_cards(
    normalized: NormalizedSheet, alignment_method: str = "rule"
) -> list[FieldCard]:
    """把一張正規化後的工作表轉成欄位卡清單。"""
    concept = sheet_measure_concept(normalized.sheet_name, normalized.file_name)
    by_dimension: dict[str, list[float]] = defaultdict(list)
    for record in normalized.records:
        if record.value is not None:
            by_dimension[record.dimension].append(record.value)

    sheet_context = f"{normalized.sheet_name} {normalized.file_name}"

    cards = []
    for column in normalized.measure_columns:
        values = by_dimension.get(column.full_name, [])
        profile = NumericProfile.from_values(values)
        unit, unit_reliability = infer_unit(column, profile, sheet_context)

        # canonical 名稱 = 量測概念 + 各層表頭的中文部分
        parts = [chinese_part(layer) for layer in column.layers]
        parts = [p for p in parts if p]
        canonical = "_".join([concept] + parts) if parts else concept

        # 信心 = 欄位識別基準 × 單位可靠度。
        # 刻意讓「單位不確定」只是扣分，不是否決：一個有明確欄名、明確儲存格
        # 範圍、充足樣本的欄位，就算單位判不出來，它仍是一個被正確識別的欄位。
        # 先前把 unit_confidence 直接當成 confidence，導致 190 個欄位裡有 177 個
        # 只因為欄名沒寫單位就被丟進 needs_manual_review，等於整份 Catalog 廢掉。
        notes: list[str] = []
        confidence = BASE_FIELD_CONFIDENCE * unit_reliability

        if profile is None:
            confidence = 0.2
            notes.append("欄位無任何數值，無法判定語意")
        elif profile.count < MIN_SAMPLE_COUNT:
            confidence = min(confidence, 0.55)
            notes.append(f"僅 {profile.count} 筆數值，樣本過少不足以判定語意")

        role = infer_aggregation_role(column)
        if unit_reliability < 0.9:
            notes.append(f"單位「{unit}」由數值特徵推得，非表頭明示")
        if role != "detail":
            notes.append(f"彙總欄（{role}），不可與同群組明細欄一起加總")
        if profile and profile.has_negative and unit != "%":
            notes.append("量值欄含負數，疑似小計調整或缺值標記")

        cards.append(
            FieldCard(
                canonical_name=canonical,
                source_column=column.full_name,
                unit=unit,
                dtype="number",
                cell_range=normalized.column_ranges.get(column.full_name, ""),
                sample_values=[round(v, 4) for v in values[:3]],
                confidence=confidence,
                alignment_method=alignment_method,
                file_name=normalized.file_name,
                sheet_name=normalized.sheet_name,
                aggregation_role=role,
                profile=profile,
                notes=notes,
            )
        )
    return cards


def build_field_dictionary(cards: list[FieldCard]) -> dict[str, list[dict[str, str]]]:
    """
    統一欄位詞典（TASK1.md 1c）：`canonical_field → 各檔案實際欄位名稱`。

    合併條件三個都要成立：
      1. **不同工作表** —— 同一張表的兩個欄位，按定義就是兩個不同欄位，
         再像也不能合併。少了這條，「停留夜數 1／2／3／4／5」會因為字串
         只差一個字元而被併成一欄，1 夜到 5 夜的人次全部混在一起加總——
         典型的「悄悄算錯」，比欄位漏建嚴重得多。
      2. **字串夠像**（rapidfuzz ≥ 92）
      3. **數值特徵相容** —— 擋掉「日本人次」與「日本佔比」這種名字像、
         量級差三個數量級的組合。
    """
    groups: dict[str, list[FieldCard]] = {}

    for card in cards:
        origin = (card.file_name, card.sheet_name)
        target = None

        for key, members in groups.items():
            # 同表欄位一律不合併
            if any((m.file_name, m.sheet_name) == origin for m in members):
                continue
            if fuzz.ratio(card.canonical_name, key) < FUZZY_MERGE_THRESHOLD:
                continue
            reference = members[0]
            if card.profile and reference.profile:
                if card.profile.compatibility(reference.profile) < 0.7:
                    continue
            target = key
            break

        groups.setdefault(target or card.canonical_name, []).append(card)

    return {
        key: [
            {
                "file": m.file_name,
                "sheet": m.sheet_name,
                "column": m.source_column,
                "cell_range": m.cell_range,
            }
            for m in members
        ]
        for key, members in sorted(groups.items())
    }