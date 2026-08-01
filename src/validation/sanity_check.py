"""
Sanity Check：計算結果的合理性檢查（TASK1.md Stage 2 step 6）。

這是「數字錯了要被擋下來」的最後一道程式端關卡。檢查的是**結果本身合不合理**，
不是「LLM 講得對不對」——LLM 對自己算錯的數字往往同樣有自信，問它沒有用。

失敗不代表結果一定錯，只代表「不該無聲通過」：由執行引擎回饋 LLM 重組積木
（最多 2 次），仍失敗則標記需人工確認，而非硬把數字塞進簡報。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

PERCENT_UNITS = ("%", "percent", "百分比")

RATIO_MIN, RATIO_MAX = -100.0, 100.0
"""比率的合理範圍。

下界取 −100% 而非 0：成長率為負是正常的（衰退），但「衰退超過 100%」
代表本期變成負數，在人次／金額這類非負量上不可能發生。
上界 100% 只對「占比」成立，成長率可以超過 100%（翻倍以上），
因此上界檢查只套用在 share 類指標。"""


class Severity(str, Enum):
    ERROR = "error"
    """結果不可信，必須重算或標記人工確認。"""

    WARNING = "warning"
    """可疑但不阻斷，寫進 validation_note 供人事後查核。"""


@dataclass
class Issue:
    severity: Severity
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity.value, "code": self.code, "message": self.message}


@dataclass
class SanityReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.severity is Severity.ERROR for i in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def note(self) -> str | None:
        return "；".join(i.message for i in self.issues) or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
        }


def _is_percent(unit: str) -> bool:
    return any(p in (unit or "").lower() for p in PERCENT_UNITS)


def check_metric(
    value: float | None,
    unit: str = "",
    metric_id: str = "",
    is_share: bool = False,
    allow_negative: bool = True,
) -> SanityReport:
    """
    檢查單一指標值。

    Args:
        value: 計算結果，None 代表 N/A（本身不是錯誤，是誠實的答案）
        unit: 單位，用來決定套用哪些規則
        metric_id: 訊息裡標示是哪個指標出問題
        is_share: 是否為占比類（占比才有 0～100% 的上界）
        allow_negative: 該量是否允許為負（人次／金額不允許，成長率允許）
    """
    report = SanityReport()
    tag = f"[{metric_id}] " if metric_id else ""

    # N/A 不是錯誤。系統誠實回報「算不出來」正是我們要的行為（鐵律 8），
    # 把它當成 error 會逼得下游用 0 去填，反而製造假數字。
    if value is None:
        report.issues.append(
            Issue(Severity.WARNING, "value_na", f"{tag}值為 N/A，未參與後續計算")
        )
        return report

    if isinstance(value, float) and math.isnan(value):
        report.issues.append(
            Issue(Severity.ERROR, "value_nan", f"{tag}值為 NaN，計算過程有未處理的缺值")
        )
        return report

    if isinstance(value, float) and math.isinf(value):
        report.issues.append(
            Issue(Severity.ERROR, "value_inf", f"{tag}值為無限大，極可能除以 0")
        )
        return report

    if _is_percent(unit):
        if value < RATIO_MIN:
            report.issues.append(Issue(
                Severity.ERROR, "ratio_below_min",
                f"{tag}比率 {value:.2f}% 低於 {RATIO_MIN:.0f}%，"
                "非負量不可能衰退超過 100%",
            ))
        if is_share and not (0 <= value <= RATIO_MAX):
            report.issues.append(Issue(
                Severity.ERROR, "share_out_of_range",
                f"{tag}占比 {value:.2f}% 超出 0～100% 範圍",
            ))

    if not allow_negative and value < 0:
        report.issues.append(Issue(
            Severity.ERROR, "unexpected_negative",
            f"{tag}單位「{unit}」的量不應為負，實得 {value:,.4g}",
        ))

    return report


def check_denominator(denominator: float | None, metric_id: str = "") -> SanityReport:
    """分母檢查。分母為 0 或缺值時整個比率無意義，不可用 0 或 1 代替。"""
    report = SanityReport()
    tag = f"[{metric_id}] " if metric_id else ""

    if denominator is None:
        report.issues.append(
            Issue(Severity.ERROR, "denominator_missing", f"{tag}分母缺值")
        )
    elif denominator == 0:
        report.issues.append(
            Issue(Severity.ERROR, "denominator_zero", f"{tag}分母為 0，比率無定義")
        )
    return report


def check_components_sum(
    parts_total: float | None,
    reported_total: float | None,
    tolerance: float = 0.005,
    metric_id: str = "",
) -> SanityReport:
    """
    明細加總與報表既有的總計欄對帳。

    **這是最有價值的一項檢查**：它抓得到「明細與小計混算」「殘差欄被誤排除」
    這類不會拋例外、只會讓每個數字都偏一點的錯誤。實測正是靠這項發現
    排除「其他 Others」欄會讓加總少 1.79%。

    Args:
        tolerance: 相對誤差容忍度，預設 0.5%。政府報表偶有四捨五入差異，
                   完全零容忍會產生大量假警報。
    """
    report = SanityReport()
    tag = f"[{metric_id}] " if metric_id else ""

    if parts_total is None or reported_total is None:
        return report
    if reported_total == 0:
        return report

    diff = abs(parts_total - reported_total) / abs(reported_total)
    if diff > tolerance:
        report.issues.append(Issue(
            Severity.ERROR, "components_sum_mismatch",
            f"{tag}明細加總 {parts_total:,.0f} 與報表總計 {reported_total:,.0f} "
            f"相差 {diff:.2%}（容忍 {tolerance:.2%}），"
            "可能漏算某類欄位或誤把彙總欄一起加總",
        ))
    return report