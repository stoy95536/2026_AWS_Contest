"""
積木執行引擎（TASK1.md Stage 2 step 4~6）。

LLM 不生成程式碼，只輸出一份「配方」——要依序呼叫哪些白名單積木、參數是什麼。
本模組負責把配方變成數字，並在過程中守三條線：

  1. **積木白名單**：不在 `BLOCK_REGISTRY` 裡的名稱一律拒絕派發，
     杜絕「LLM 生成任意 pandas 程式碼」這條路（鐵律 5）
  2. **欄位白名單**：欄位參數只能取自 Data Catalog 的 canonical 名稱，
     LLM 憑空捏造的欄位名會當場被擋下，而不是安靜地篩出 0 列
  3. **血緣**：每一步都記進 block_chain，每個數字都留得住 A1 座標

Sanity Check 失敗時回饋 LLM 重組積木（最多 2 次），仍失敗則標記需人工確認，
不硬把可疑數字塞進簡報。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from src.validation.sanity_check import Issue, SanityReport, Severity, check_metric

from .blocks import BLOCK_REGISTRY, SCALAR_BLOCKS, ScalarResult
from .blocks.types import (
    COL_CANONICAL,
    COL_COL,
    COL_FILE,
    COL_ROW,
    COL_SHEET,
    COL_VALUE,
)
from .dataset import Dataset

MAX_RETRIES = 2
"""Sanity Check 失敗後回饋 LLM 重組積木的次數上限（TASK1.md Stage 2 step 6）。

不設無限重試：LLM 連錯兩次通常代表問題出在資料本身或提問本身，
再問下去只是燒錢燒時間，該讓人介入了。"""

MAX_LINEAGE_CELLS = 30
"""單一指標最多記錄幾個來源儲存格。

一次 group_sum 可能涵蓋上千格，全記會讓 data_lineage.json 膨脹到無法閱讀。
超過上限時改記欄位範圍摘要——人要核對時看範圍就夠了。"""

REF_KEY = "$ref"
"""參數引用前一步結果的標記，如 {"numerator": {"$ref": "japan_sum"}}。"""


class ExecutionError(Exception):
    """配方不合法或執行失敗。訊息會被回饋給 LLM 作為重試的依據。"""


@dataclass
class StepSpec:
    """配方裡的一步。"""

    id: str
    block: str
    params: dict[str, Any] = field(default_factory=dict)
    input: str | None = None
    """上一步的 id，或 'dataset' 表示原始長表。純量積木可為 None。"""


@dataclass
class MetricRecipe:
    """一個指標的完整計算配方——LLM Function Calling 的輸出格式。"""

    metric_id: str
    metric_name: str
    steps: list[StepSpec]
    output: str
    """取哪一步的結果作為最終值。"""

    unit: str = ""
    period: str = ""
    is_share: bool = False
    assumption_statement: str = ""
    """LLM 對業務定義的理解說明（TASK1.md 鐵律 11）。

    非阻斷式：遇到模糊語意不中斷詢問使用者，而是把假設寫下來供人事後核對。
    例：「市占率以來臺旅客總計為分母，不含未列明」。"""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MetricRecipe":
        try:
            steps = [
                StepSpec(
                    id=s["id"],
                    block=s["block"],
                    params=s.get("params", {}),
                    input=s.get("input"),
                )
                for s in payload["steps"]
            ]
            return cls(
                metric_id=payload["metric_id"],
                metric_name=payload["metric_name"],
                steps=steps,
                output=payload["output"],
                unit=payload.get("unit", ""),
                period=payload.get("period", ""),
                is_share=payload.get("is_share", False),
                assumption_statement=payload.get("assumption_statement", ""),
            )
        except KeyError as e:
            raise ExecutionError(f"配方缺少必要欄位：{e}") from e


@dataclass
class MetricResult:
    """執行結果，含完整血緣。"""

    metric_id: str
    metric_name: str
    value: float | None
    unit: str
    period: str
    formula: str
    block_chain: list[str]
    source_cells: list[str]
    source_range_summary: list[str]
    validation_status: str
    validation_note: str | None = None
    assumption_statement: str = ""
    sanity: SanityReport | None = None
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "metric_id": self.metric_id,
            "metric_name": self.metric_name,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
            "formula": self.formula,
            "block_chain": self.block_chain,
            "validation_status": self.validation_status,
        }
        if self.validation_note:
            payload["validation_note"] = self.validation_note
        if self.assumption_statement:
            payload["assumption_statement"] = self.assumption_statement
        if self.source_cells:
            payload["source_cells"] = self.source_cells
        if self.source_range_summary:
            payload["source_ranges"] = self.source_range_summary
        return payload


def _describe(block: str, params: dict[str, Any]) -> str:
    """把一步積木呼叫寫成人可讀的字串，構成 block_chain。"""
    shown = {
        k: v for k, v in params.items()
        if not (isinstance(v, dict) and REF_KEY in v)
    }
    args = ", ".join(f"{k}={v!r}" for k, v in shown.items())
    return f"{block}({args})" if args else f"{block}()"


def _as_scalar(result: Any, step_id: str) -> float | None:
    """
    從一步的結果取出單一數值。

    DataFrame 必須恰好一列——多列代表 LLM 少做了一次彙總，
    這時取第一列會得到一個「看起來合理但其實只是某一列」的數字，
    比直接報錯危險得多。
    """
    if isinstance(result, ScalarResult):
        return result.value
    if isinstance(result, (int, float)):
        return None if isinstance(result, float) and math.isnan(result) else float(result)
    if isinstance(result, pd.DataFrame):
        if result.empty:
            return None
        if COL_VALUE not in result.columns:
            raise ExecutionError(f"步驟 '{step_id}' 的結果沒有 {COL_VALUE} 欄，無法取值")
        if len(result) != 1:
            raise ExecutionError(
                f"步驟 '{step_id}' 產生 {len(result)} 列，無法當成單一數值使用；"
                "請先用 group_sum 或 filter 收斂成一列"
            )
        value = result[COL_VALUE].iloc[0]
        return None if pd.isna(value) else float(value)
    raise ExecutionError(f"步驟 '{step_id}' 的結果型別 {type(result).__name__} 無法取值")


class Executor:
    """把 MetricRecipe 變成帶血緣的 MetricResult。"""

    def __init__(self, dataset: Dataset):
        self.dataset = dataset

    # ---------- 白名單驗證 ----------

    def _validate_block(self, name: str) -> Callable:
        if name not in BLOCK_REGISTRY:
            raise ExecutionError(
                f"積木 '{name}' 不在白名單中；可用積木：{sorted(BLOCK_REGISTRY)}"
            )
        return BLOCK_REGISTRY[name]

    def _validate_field_params(self, block: str, params: dict[str, Any]) -> None:
        """
        欄位參數必須是 Catalog 裡真實存在的 canonical 名稱。

        少了這道檢查，LLM 捏造一個不存在的欄位名時，`filter` 會安靜地回傳
        0 列，一路往下算出 N/A 或 0——沒有任何地方會說「這個欄位根本不存在」。
        """
        if block != "filter" or params.get("column") != COL_CANONICAL:
            return

        value = params.get("value")
        candidates = value if isinstance(value, (list, tuple, set)) else [value]
        unknown = [
            c for c in candidates
            if isinstance(c, str) and c not in self.dataset.canonical_names
        ]
        if unknown:
            raise ExecutionError(
                f"欄位 {unknown} 不存在於 Data Catalog；"
                f"請只使用 catalog 提供的 canonical_name（共 "
                f"{len(self.dataset.canonical_names)} 個）"
            )

    def _resolve_params(
        self, params: dict[str, Any], results: dict[str, Any]
    ) -> dict[str, Any]:
        """把 {"$ref": "step_id"} 換成該步驟的實際數值。"""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, dict) and REF_KEY in value:
                ref = value[REF_KEY]
                if ref not in results:
                    raise ExecutionError(f"參數 '{key}' 引用了不存在的步驟 '{ref}'")
                resolved[key] = _as_scalar(results[ref], ref)
            else:
                resolved[key] = value
        return resolved

    # ---------- 執行 ----------

    def execute(self, recipe: MetricRecipe) -> MetricResult:
        """執行配方。任何違反白名單的行為都會拋 ExecutionError。"""
        if not recipe.steps:
            raise ExecutionError("配方沒有任何步驟")

        results: dict[str, Any] = {}
        chain: list[str] = []

        for step in recipe.steps:
            fn = self._validate_block(step.block)
            self._validate_field_params(step.block, step.params)
            params = self._resolve_params(step.params, results)

            if step.block in SCALAR_BLOCKS:
                outcome = fn(**params)
            else:
                source = self._resolve_input(step, results)
                outcome = fn(source, **params)

            results[step.id] = outcome
            chain.append(_describe(step.block, step.params))

        if recipe.output not in results:
            raise ExecutionError(
                f"output 指向不存在的步驟 '{recipe.output}'；"
                f"可用步驟：{sorted(results)}"
            )

        return self._finalize(recipe, results, chain)

    def _resolve_input(self, step: StepSpec, results: dict[str, Any]) -> pd.DataFrame:
        if step.input in (None, "dataset"):
            return self.dataset.frame
        if step.input not in results:
            raise ExecutionError(
                f"步驟 '{step.id}' 的 input '{step.input}' 不存在；"
                f"可用：dataset、{sorted(results)}"
            )
        source = results[step.input]
        if not isinstance(source, pd.DataFrame):
            raise ExecutionError(
                f"步驟 '{step.id}' 的 input '{step.input}' 是單一數值，"
                "不能餵給表格類積木"
            )
        return source

    def _finalize(
        self, recipe: MetricRecipe, results: dict[str, Any], chain: list[str]
    ) -> MetricResult:
        final = results[recipe.output]
        value = _as_scalar(final, recipe.output)

        formula = final.formula if isinstance(final, ScalarResult) else " → ".join(chain)
        note = final.reason if isinstance(final, ScalarResult) else None

        cells, ranges = self._collect_lineage(results)
        sanity = check_metric(
            value,
            unit=recipe.unit,
            metric_id=recipe.metric_id,
            is_share=recipe.is_share,
            allow_negative=recipe.unit not in ("人次", "元", "美元", "夜"),
        )
        sanity.issues.extend(
            self._check_source_ambiguity(results, recipe.metric_id).issues
        )

        status = "passed"
        if value is None:
            status = "na"
        elif not sanity.passed:
            status = "failed"

        notes = [n for n in (note, sanity.note) if n]
        return MetricResult(
            metric_id=recipe.metric_id,
            metric_name=recipe.metric_name,
            value=value,
            unit=recipe.unit,
            period=recipe.period,
            formula=formula,
            block_chain=chain,
            source_cells=cells,
            source_range_summary=ranges,
            validation_status=status,
            validation_note="；".join(notes) or None,
            assumption_statement=recipe.assumption_statement,
            sanity=sanity,
        )

    def _check_source_ambiguity(
        self, results: dict[str, Any], metric_id: str
    ) -> SanityReport:
        """
        偵測「同一個 canonical 欄位橫跨多份檔案卻被一起加總」。

        實測案例：`來臺旅客_亞洲地區_日本` 同時存在於表1-2（按居住地）與
        表1-3（按國籍）——這是同一批旅客的兩種統計口徑，不是兩批人。
        `group_sum` 若把兩份都加進去，得到的 2,638,000 正好是真值 1,318,372
        的兩倍，而且**不會拋任何例外**。

        比率型指標特別危險：分子分母同時加倍會互相抵銷，比率看起來完全正常，
        只有絕對值是錯的——沒有這道檢查根本發現不了。

        修法是請 LLM 用 `filter(column='file', ...)` 指定單一來源，
        而不是由程式自動挑一份（挑哪份是業務判斷，不是技術判斷）。
        """
        report = SanityReport()
        frames = [
            r for r in results.values()
            if isinstance(r, pd.DataFrame)
            and not r.empty
            and {COL_FILE, COL_CANONICAL}.issubset(r.columns)
        ]
        if not frames:
            return report

        source = frames[-1]
        spread = source.groupby(COL_CANONICAL)[COL_FILE].nunique()
        tag = f"[{metric_id}] " if metric_id else ""

        for canonical, file_count in spread[spread > 1].items():
            files = sorted(source[source[COL_CANONICAL] == canonical][COL_FILE].unique())
            report.issues.append(Issue(
                Severity.ERROR, "ambiguous_source",
                f"{tag}欄位「{canonical}」同時存在於 {file_count} 份檔案"
                f"（{'、'.join(files)}），加總會把同一批對象重複計算；"
                "請用 filter(column='file', operator='==', value='檔名') 指定單一來源",
            ))
        return report

    def _collect_lineage(self, results: dict[str, Any]) -> tuple[list[str], list[str]]:
        """
        從所有中間結果蒐集來源儲存格。

        取「最後一個仍帶座標欄的 DataFrame」——group_sum 之後座標就沒了，
        所以要往回找到彙總前那一步，那才是真正被讀取的原始格子。
        """
        from src.catalog_builder.cell_tracker import to_a1

        frames = [
            r for r in results.values()
            if isinstance(r, pd.DataFrame)
            and not r.empty
            and {COL_SHEET, COL_ROW, COL_COL}.issubset(r.columns)
        ]
        if not frames:
            return [], []

        source = frames[-1]
        cells = [
            f"{r[COL_SHEET]}!{to_a1(int(r[COL_ROW]), int(r[COL_COL]))}"
            for _, r in source.head(MAX_LINEAGE_CELLS).iterrows()
        ]
        ranges = self._summarize_ranges(source)
        return cells, ranges

    @staticmethod
    def _summarize_ranges(frame: pd.DataFrame) -> list[str]:
        """每個工作表+欄位壓成一個 A1 範圍，如 '歷年來臺旅客-按國籍!C5:C66'。"""
        from src.catalog_builder.cell_tracker import to_a1_range

        summary = []
        for (sheet, col), group in frame.groupby([COL_SHEET, COL_COL]):
            rows = group[COL_ROW].astype(int)
            summary.append(
                f"{sheet}!{to_a1_range(rows.min(), int(col), rows.max(), int(col))}"
            )
        return sorted(summary)


def execute_with_retry(
    dataset: Dataset,
    recipe_provider: Callable[[str | None], MetricRecipe],
    max_retries: int = MAX_RETRIES,
) -> MetricResult:
    """
    執行配方，失敗時回饋錯誤給 LLM 重組積木（TASK1.md Stage 2 step 6）。

    Args:
        recipe_provider: 接受「上一次的失敗原因」（首次為 None）並回傳新配方。
                         實務上就是包了 LLM Function Calling 的函式。

    重試耗盡後回傳最後一次結果並標記 needs_manual_review——
    不拋例外中斷整條 pipeline，一個指標算不出來不該讓整份簡報生不出來。
    """
    executor = Executor(dataset)
    feedback: str | None = None
    last: MetricResult | None = None

    for attempt in range(1, max_retries + 2):
        try:
            recipe = recipe_provider(feedback)
            result = executor.execute(recipe)
            result.attempts = attempt
            if result.validation_status != "failed":
                return result
            last = result
            feedback = (
                f"第 {attempt} 次計算未通過合理性檢查："
                f"{result.validation_note}。請檢查積木組合與欄位選擇後重新輸出配方。"
            )
        except ExecutionError as e:
            feedback = f"第 {attempt} 次配方執行失敗：{e}。請修正後重新輸出配方。"
            last = MetricResult(
                metric_id=getattr(recipe, "metric_id", "unknown") if "recipe" in dir() else "unknown",
                metric_name="",
                value=None,
                unit="",
                period="",
                formula="",
                block_chain=[],
                source_cells=[],
                source_range_summary=[],
                validation_status="failed",
                validation_note=str(e),
                attempts=attempt,
            )

    if last is not None:
        last.validation_status = "needs_manual_review"
        last.validation_note = (
            f"重試 {max_retries} 次仍未通過：{last.validation_note}"
        )
        last.attempts = max_retries + 1
        return last

    raise ExecutionError("重試耗盡且沒有任何可回傳的結果")