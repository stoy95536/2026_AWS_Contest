"""
Task 1 端到端執行：多份 Excel → Data Catalog → 積木計算 → 同源三輸出。

    python Task1/run_task1.py --prompt "我要 2024 各國來臺旅客市占率"
    python Task1/run_task1.py --no-llm                    # 強制走規則式
    python Task1/run_task1.py --data <目錄> --out <目錄>

**兩種指標來源，輸出格式完全相同：**

  有 Prompt → LLM 讀 Data Catalog，用 Function Calling 組出積木配方
  無 Prompt → 規則式後備：依各欄位在最新年度的量級自動挑選

後備不只是備胎——決賽現場憑證失效、Bedrock 逾時、額度用盡都可能發生。
LLM 掛掉時系統仍能產出可追溯的數字，比整個停擺好。

指標選擇**完全由資料驅動**，不預設任何業務概念。換成金融、零售、製造的
Excel 一樣跑得動——這正是與舊架構（一個業務指標一個寫死函式）的根本差異。

Windows 主控台預設 cp950 打不出部分字元，此處統一切成 UTF-8，
避免在評審面前因為一個符號就整個腳本崩潰。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# 憑證與 SSL 必須在 import boto3 之前設好，否則 client 會沿用錯的設定。
# 用 certifi 的正規 CA bundle，不停用憑證驗證——關掉驗證能讓程式跑起來，
# 但那是在替真正的連線問題蓋上蓋子。
try:
    import certifi
    from dotenv import load_dotenv

    for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE"):
        os.environ.setdefault(_var, certifi.where())
    load_dotenv(_ROOT / ".env", override=True)
except ImportError:
    pass  # 沒裝也不該擋住規則式路線

from src.calculation_engine.dataset import Dataset, build_dataset  # noqa: E402
from src.calculation_engine.executor import (  # noqa: E402
    ExecutionError,
    Executor,
    MetricRecipe,
)
from src.calculation_engine.llm_planner import (  # noqa: E402
    LLMPlanner,
    LLMPlannerError,
)
from src.calculation_engine.recipe_factory import (  # noqa: E402
    find_total_field,
    growth_recipe,
    latest_common_year,
    rank_fields_by_latest_value,
    share_recipe,
    value_recipe,
)
from src.catalog_builder import build_catalog, write_catalog  # noqa: E402
from src.export import AnalysisResult, ChartSpec, write_all  # noqa: E402

TREND_YEARS = 6
"""趨勢圖回溯幾個年度。取 6 年是為了讓折線看得出趨勢又不至於擠爆 x 軸。"""

TOP_N = 5
"""規則式後備每份檔案挑幾個量級最大的欄位。"""

LLM_MAX_RETRIES = 2
"""LLM 計畫執行失敗後重新規劃的次數上限（TASK1.md Stage 2 step 6）。

不設無限重試：連錯兩次通常代表問題出在資料或提問本身，再問下去只是燒錢
燒時間。仍失敗就落回規則式後備，至少產出得了東西。"""


def metric_slug(canonical: str, file_name: str) -> str:
    """
    產生唯一的 metric_id 前綴。

    **必須含檔名**：同一個 canonical 常橫跨多份檔案（「來臺旅客_亞洲地區_日本」
    同時存在於表1-2 按居住地與表1-3 按國籍），兩者是同一批旅客的不同統計口徑，
    數值不同（1,483,176 vs 1,479,392）。只用 canonical 當 id 會讓兩個不同的
    數字共用同一個 metric_id——成員 B 引用它做 KPI、成員 D 回溯血緣，
    兩邊可能拿到不同的值，正是本專案要消滅的「簡報數字與 Excel 不符」。

    取檔名開頭的表號（「表1-2」）而非完整檔名，是為了讓 metric_id 保持可讀。
    """
    stem = Path(file_name).stem
    token = re.match(r"^[^-]+-[^-]+", stem)
    prefix = (token.group(0) if token else stem[:8]).replace(" ", "")
    return f"{prefix}_{canonical}".replace(" ", "")


def _safe(executor: Executor, payload: dict) -> object | None:
    """
    執行單一配方，失敗只記錄不中斷。

    一個指標算不出來，不該讓整份簡報生不出來——這是 pipeline 層級的
    「非阻斷」原則，與積木層的 N/A 同一個精神。
    """
    try:
        return executor.execute(MetricRecipe.from_dict(payload))
    except ExecutionError as e:
        print(f"    [skip] {payload.get('metric_id')}: {e}")
        return None


# --------------------------------------------------------------------------
# LLM 路線
# --------------------------------------------------------------------------

def plan_with_llm(
    executor: Executor, dataset: Dataset, result: AnalysisResult, prompt: str,
) -> bool:
    """
    LLM 規劃 → 執行 → 失敗回饋重新規劃（最多兩次）。

    以「整批」為單位重試而非逐一指標重試：一次失敗通常源自同一種誤解
    （例如忘了指定 file），把所有錯誤一起回饋，LLM 改一次就能全部修好，
    比一個一個問省下大量往返。

    回傳是否產出任何指標；False 時由呼叫方落回規則式後備。
    """
    planner = LLMPlanner()
    print(f"  模型 {planner.model_id} @ {planner.region}")

    feedback: str | None = None
    produced: list = []

    for attempt in range(1, LLM_MAX_RETRIES + 2):
        try:
            plan = planner.plan(prompt, dataset, feedback=feedback)
        except LLMPlannerError as e:
            print(f"  [warn] 第 {attempt} 次規劃失敗：{e}")
            return False

        print(f"  第 {attempt} 次規劃：{len(plan.recipes)} 個指標、"
              f"{len(plan.charts)} 張圖表")

        produced, failures = [], []
        for recipe in plan.recipes:
            try:
                metric = executor.execute(recipe)
            except ExecutionError as e:
                failures.append(f"配方 '{recipe.metric_id}' 執行失敗：{e}")
                continue
            if metric.validation_status == "failed":
                failures.append(
                    f"指標 '{recipe.metric_id}' 未通過合理性檢查："
                    f"{metric.validation_note}"
                )
                continue
            produced.append(metric)

        if not failures:
            for metric in produced:
                result.add(metric)
            add_llm_charts(result, plan.charts)
            print(f"  全部通過：{len(produced)} 個指標")
            return bool(produced)

        print(f"  {len(failures)} 個配方有問題，回饋 LLM 重新規劃")
        for message in failures[:3]:
            print(f"    - {message[:110]}")
        feedback = "\n".join(failures[:10])

    # 重試耗盡：保留這一輪算得出來的部分，不整批丟棄
    for metric in produced:
        result.add(metric)
    print(f"  [warn] 重試 {LLM_MAX_RETRIES} 次仍有失敗，"
          f"保留 {len(produced)} 個通過的指標")
    return bool(produced)


def add_llm_charts(result: AnalysisResult, charts: list[dict]) -> None:
    """
    把 LLM 規劃的圖表轉成 ChartSpec。

    LLM 只指定「這張圖由哪些 metric_id 組成」，數值仍由程式從 metric 查表
    填入——鐵律 12：只要有一個數字是 LLM 生的，防線就破功。
    """
    for chart in charts:
        series = {
            s["name"]: s.get("metric_ids", [])
            for s in chart.get("series", [])
            if s.get("metric_ids")
        }
        if not series:
            continue
        result.charts.append(ChartSpec(
            chart_id=chart.get("chart_id") or f"chart_{len(result.charts) + 1}",
            chart_type=chart.get("chart_type", "bar"),
            title=chart.get("title", ""),
            category_metric_map=series,
            categories=chart.get("categories", []),
            unit=chart.get("unit", ""),
            note="由 LLM 依 Prompt 規劃",
        ))


# --------------------------------------------------------------------------
# 規則式後備
# --------------------------------------------------------------------------

def plan_by_rules(
    executor: Executor, dataset: Dataset, result: AnalysisResult,
) -> None:
    """依資料量級自動挑選指標，不需要 LLM。"""
    for file_name in sorted({m.file_name for m in dataset.fields.values()}):
        year = latest_common_year(dataset, file_name)
        if year is None:
            continue

        fields = rank_fields_by_latest_value(dataset, file_name, year, TOP_N)
        if not fields:
            continue

        print(f"  {Path(file_name).stem[:14]} ({year})")

        for canonical in fields:
            meta = dataset.fields[canonical]
            # 總計欄必須取自「同一張工作表」——一個檔案常有多張表量測不同的
            # 東西，跨表相除會得到毫無意義的比率
            total_field = find_total_field(dataset, file_name, meta.sheet_name)
            slug = metric_slug(canonical, file_name)

            if m := _safe(executor, value_recipe(
                f"{slug}_{year}", f"{canonical} {year}",
                canonical, file_name, year, meta.unit,
            )):
                result.add(m)

            if m := _safe(executor, growth_recipe(
                f"{slug}_yoy_{year}", f"{canonical} 年增率",
                canonical, file_name, year, year - 1,
            )):
                result.add(m)

            if total_field and canonical != total_field:
                if m := _safe(executor, share_recipe(
                    f"{slug}_share_{year}", f"{canonical} 占比",
                    canonical, total_field, file_name, year,
                )):
                    result.add(m)

        add_trend_chart(executor, result, dataset, file_name, fields[0], year)


def add_trend_chart(
    executor: Executor, result: AnalysisResult, dataset: Dataset,
    file_name: str, canonical: str, year: int,
) -> None:
    """為量級最大的欄位做一張趨勢圖。圖表值直接引用 metric，不另外計算。"""
    meta = dataset.fields[canonical]
    slug = metric_slug(canonical, file_name)
    years, metric_ids = [], []

    for y in range(year - TREND_YEARS + 1, year + 1):
        metric_id = f"{slug}_{y}"
        if result.metric(metric_id) is None:
            m = _safe(executor, value_recipe(
                metric_id, f"{canonical} {y}", canonical, file_name, y, meta.unit,
            ))
            if m is None:
                continue
            result.add(m)
        years.append(str(y))
        metric_ids.append(metric_id)

    if len(metric_ids) >= 2:
        result.charts.append(ChartSpec(
            chart_id=f"trend_{slug}",
            chart_type="line",
            title=f"{canonical} 歷年趨勢",
            category_metric_map={canonical: metric_ids},
            categories=years,
            unit=meta.unit,
            note=f"資料來源：{file_name}",
        ))


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def run(
    data_dir: str,
    output_dir: str,
    prompt: str | None = None,
    use_llm: bool = True,
) -> AnalysisResult:
    print("=" * 68)
    print("  Task 1：Excel → Data Catalog → 積木計算 → 同源輸出")
    print("=" * 68)

    print("\n[1/4] 建立 Data Catalog")
    catalog = build_catalog(data_dir)
    catalog_path = write_catalog(catalog, Path(output_dir) / "data_catalog.json")
    summary = catalog["summary"]
    print(f"  檔案 {summary['file_count']}、欄位 {summary['field_count']}、"
          f"待覆核 {summary['needs_manual_review_count']}")
    print(f"  -> {catalog_path}")

    print("\n[2/4] 載入資料集")
    dataset = build_dataset(data_dir)
    info = dataset.describe()
    print(f"  記錄 {info['record_count']:,}、canonical 欄位 {info['field_count']}、"
          f"年度 {info['period_range']}")

    print("\n[3/4] 計算指標")
    executor = Executor(dataset)
    result = AnalysisResult(
        catalog_summary=summary,
        data_summary=dataset.to_data_summary(),
    )

    planned = False
    if prompt and use_llm:
        print(f"  LLM 規劃，Prompt：「{prompt}」")
        planned = plan_with_llm(executor, dataset, result, prompt)
        if planned:
            result.prompt = prompt
        else:
            print("  [warn] LLM 路線未產出指標，落回規則式後備")

    if not planned:
        reason = "未提供 Prompt" if not prompt else ("已停用 LLM" if not use_llm else "LLM 不可用")
        print(f"  規則式後備（{reason}）：依資料量級自動挑選指標")
        plan_by_rules(executor, dataset, result)
        result.prompt = prompt or f"（規則式後備：{reason}）"

    print("\n[4/4] 同源輸出")
    problems = result.verify_consistency()
    if problems:
        print("  [warn] 三方一致性問題：")
        for problem in problems:
            print(f"    - {problem}")

    paths = write_all(result, output_dir)
    payload = result.analysis_payload()["summary"]
    print(f"  指標 {payload['metric_count']}"
          f"（通過 {payload['passed']}、N/A {payload['na']}、"
          f"待人工 {payload['needs_manual_review']}）、圖表 {payload['chart_count']}")
    for name, path in paths.items():
        print(f"  {name:<16} -> {path}")

    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Task 1 端到端執行")
    parser.add_argument("--data", default=str(root / "Task1" / "data"), help="Excel 目錄")
    # 開發期曾暫寫 outputs/v2/ 以免蓋掉成員 D 的 demo 素材；
    # 端到端驗證通過後切回正式路徑，成員 B/C/D 讀的就是這裡
    parser.add_argument("--out", default=str(root / "outputs"), help="輸出目錄")
    parser.add_argument("--prompt", default=None, help="使用者提問；未給則走規則式後備")
    parser.add_argument(
        "--prompt-file", default=None,
        help="從檔案讀取提問（成員 D 的 pipeline 傳的是 user_prompt.txt 路徑）",
    )
    parser.add_argument("--no-llm", action="store_true", help="停用 LLM，強制走規則式")
    args = parser.parse_args()

    prompt = args.prompt
    if not prompt and args.prompt_file:
        path = Path(args.prompt_file)
        if path.is_file():
            prompt = path.read_text(encoding="utf-8").strip()

    run(args.data, args.out, prompt=prompt, use_llm=not args.no_llm)


if __name__ == "__main__":
    main()