"""
三個 schema 共用的基礎型別。

SourceRef 被 DataCatalog / Metric / ChartData 共用，避免血緣欄位在三處各寫一份，
日後改動時漏改其中之一。
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- TASK1.md 5.4 信心分數門檻 ---
CONFIDENCE_AUTO_ACCEPT = 0.85
"""confidence >= 此值：自動採用。"""

CONFIDENCE_MIN_USABLE = 0.60
"""CONFIDENCE_MIN_USABLE <= confidence < CONFIDENCE_AUTO_ACCEPT：採用但註記 best-effort。
低於此值不猜，輸出 N/A + 原因。"""


class ValidationStatus(str, Enum):
    """
    數值的校驗狀態。

    非阻斷式設計（TASK1.md 5.4）：失敗不中斷 pipeline，而是標記狀態讓下游知情。
    """

    PASSED = "passed"
    """通過 Sanity Check，可直接使用。"""

    BEST_EFFORT = "best_effort"
    """欄位比對信心中等（0.6–0.85），數值可用但建議人工覆核。"""

    FAILED = "failed"
    """Sanity Check 未通過（如比率超出 0–100%），不應上簡報。"""

    NOT_AVAILABLE = "N/A"
    """無法計算（缺基期資料、分母為 0、信心過低），必須附 na_reason。"""


class AlignmentMethod(str, Enum):
    """欄位語意比對是由哪一層漏斗決定的（TASK1.md 1b）。"""

    FINGERPRINT = "fingerprint"
    """Layer 0：表頭指紋命中已知樣板。"""

    RULE = "rule"
    """Layer 1：規則式比對（字串相似度 + 數值結構特徵）。"""

    EMBEDDING = "embedding"
    """Layer 2：embedding 相似度。"""

    LLM = "llm"
    """Layer 3：LLM 仲裁。"""

    MANUAL = "manual"
    """人工指定。"""


class DType(str, Enum):
    """欄位資料型別。"""

    NUMBER = "number"
    STRING = "string"
    DATE = "date"
    PERCENT = "percent"


# A1 表示法：C6、B2:M34、AA1:AB100
_A1_PATTERN = re.compile(r"^[A-Z]{1,3}\d{1,7}(:[A-Z]{1,3}\d{1,7})?$")


class SourceRef(BaseModel):
    """
    指向原始 Excel 的血緣座標。

    range 強制使用真正的 A1 表示法（如 "C6:C67"），不接受
    "台新銀行@11401" 這種偽座標 —— 那種寫法無法讓人打開 Excel 逐格核對，
    等於沒有血緣（TASK1.md 第 7 節）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str = Field(min_length=1, description="原始 Excel 檔名")
    sheet: str = Field(min_length=1, description="工作表名稱")
    range: str = Field(min_length=2, description="儲存格範圍，A1 表示法，如 C6:C67")

    @field_validator("range")
    @classmethod
    def _validate_a1(cls, v: str) -> str:
        v = v.strip().upper()
        if not _A1_PATTERN.match(v):
            raise ValueError(
                f"range 必須為 A1 表示法（如 C6 或 B2:M34），收到: {v!r}。"
                "偽座標（如 '機構名@期間'）無法回溯，不予接受。"
            )
        return v

    def __str__(self) -> str:
        return f"{self.file}!{self.sheet}!{self.range}"
