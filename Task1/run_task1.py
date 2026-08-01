"""
Task 1 端到端執行：多份 Excel → Data Catalog → 積木計算 → 同源三輸出。

    python Task1/run_task1.py [資料目錄] [輸出目錄]

指標選擇**完全由資料驅動**：依各欄位在最新年度的量級自動挑出前幾名，
不預設任何業務概念。換成金融、零售、製造的 Excel 一樣跑得動——
這正是與舊架構（一個業務指標一個寫死函式）的根本差異。

Windows 主控台預設 cp950 打不出部分字元，此處統一切成 UTF-8，
避免在評審面前因為一個符號就整個腳本崩潰。
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog_builder import build_catalog, write_catalog  # noqa: E402
from src.calculation_engine.dataset import build_dataset  # noqa: E402
from src.calculation_engine.executor import (  # noqa: E402
    ExecutionError,
    Executor,
    MetricRecipe,
)
from src.calculation_engine.recipe_factory import (  # noqa: E402
    find_total_field,
    growth_recipe,
    latest_common_year,
    rank_fields_by_latest_value,
    share_recipe,
    value_recipe,
)
from src.export import AnalysisResult, ChartSpec, write_all  # noqa: E402

TREND_YEARS = 6
"""趨勢圖回溯幾個年度。取 6 年是為了讓折線看得出趨勢又不至於擠爆 x 軸。"""

TOP_N = 5
"""每份檔案挑幾個量級最大的欄位進簡報。"""


def _safe(executor: Executor, payload: dict) -> object | None:
    """
    執行單一配方，失敗只記錄不中斷。

    一個指標算不出來，不該讓整份簡報生不出來——這是 pipeline 層級的
    「非阻斷」原則，與積木層的 N/A 是同一個精神。
    """
    try:
        return executor.execute(MetricRecipe.from_dict(payload))
    except ExecutionError as e:
        print(f"    [skip] {payload.get('metric_id')}: {e}")
        return None


def run(data_dir: str, output_dir: str) -> AnalysisResult:
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
        prompt="（規則式後備配方：依資料量級自動挑選指標）",
        catalog_summary=summary,
    )

    for file_name in sorted({m.file_name for m in dataset.fields.values()}):
        year = latest_common_year(dataset, file_name)
        if year is None:
            continue

        fields = rank_fields_by_latest_value(dataset, file_name, year, TOP_N)
        if not fields:
            continue

        total_field = find_total_field(dataset, file_name)
        stem = Path(file_name).stem[:14]
        print(f"  {stem} ({year})")

        for canonical in fields:
            meta = dataset.fields[canonical]
            slug = canonical.replace(" ", "")

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

        _add_trend_chart(executor, result, dataset, file_name, fields[0], year)

    print("\n[4/4] 同源輸出")
    problems = result.verify_consistency()
    if problems:
        print("  [warn] 三方一致性問題：")
        for p in problems:
            print(f"    - {p}")

    paths = write_all(result, output_dir)
    payload = result.analysis_payload()["summary"]
    print(f"  指標 {payload['metric_count']}"
          f"（通過 {payload['passed']}、N/A {payload['na']}、"
          f"待人工 {payload['needs_manual_review']}）、圖表 {payload['chart_count']}")
    for name, path in paths.items():
        print(f"  {name:<16} -> {path}")

    return result


def _add_trend_chart(
    executor: Executor, result: AnalysisResult, dataset,
    file_name: str, canonical: str, year: int,
) -> None:
    """為量級最大的欄位做一張趨勢圖。圖表值直接引用 metric，不另外計算。"""
    meta = dataset.fields[canonical]
    slug = canonical.replace(" ", "")
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


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    data = sys.argv[1] if len(sys.argv) > 1 else str(root / "Task1" / "data")
    out = sys.argv[2] if len(sys.argv) > 2 else str(root / "outputs" / "v2")
    run(data, out)