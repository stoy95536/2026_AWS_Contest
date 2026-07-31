"""
Task 3: PowerPoint 模板解析、原生圖表與版面生成
主要功能模組位於:
  - src/presentation/template_parser.py — 模板解析
  - src/presentation/chart_factory.py   — 圖表工廠
  - src/presentation/ppt_generator.py   — 簡報生成器
  - src/presentation/components/        — 頁面元件

本檔為 Task 3 獨立執行入口，可單獨測試 PPT 生成流程。
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.presentation import TemplateParser, ChartFactory, PPTGenerator
from src.agents.planner_agent import DEFAULT_SLIDE_STRUCTURE


def run_task3(
    slide_spec_path: str = None,
    template_path: str = None,
    output_dir: str = "outputs",
):
    """
    獨立執行 Task 3: 模板解析 + PPT 生成。

    Args:
        slide_spec_path: slide_spec.json 路徑 (若無則使用預設結構)
        template_path: PowerPoint 模板路徑
        output_dir: 輸出目錄
    """
    print("[Task 3] 開始 PowerPoint 生成...")

    # 載入 slide_spec
    if slide_spec_path and os.path.exists(slide_spec_path):
        with open(slide_spec_path, "r", encoding="utf-8") as f:
            slide_specs = json.load(f)
        print(f"  載入 slide_spec: {len(slide_specs)} 頁")
    else:
        # 使用預設結構生成範例
        print("  使用預設結構...")
        slide_specs = _build_demo_specs()

    # 解析模板
    print("[Task 3] 解析模板...")
    parser = TemplateParser(template_path)
    style = parser.get_style()
    print(f"  投影片尺寸: {style.slide_width} x {style.slide_height} EMU")
    print(f"  主題色: #{style.primary_color}")

    # 生成 PPT
    print("[Task 3] 生成 PowerPoint...")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "final_presentation.pptx")

    generator = PPTGenerator(template_path)
    result_path = generator.generate(slide_specs, output_path)
    print(f"  輸出: {result_path}")

    print("[Task 3] 完成!")
    return result_path


def _build_demo_specs() -> list[dict]:
    """建立示範用 slide_spec。"""
    specs = []
    for template in DEFAULT_SLIDE_STRUCTURE:
        spec = template.copy()
        spec["headline"] = ""
        spec["kpis"] = []
        spec["chart"] = None
        spec["table"] = None
        spec["insights"] = []
        spec["recommendations"] = []
        spec["source_ids"] = []

        # 為部分頁面加入範例資料
        if spec["layout"] == "executive_summary":
            spec["headline"] = "市場關鍵指標摘要"
            spec["kpis"] = [
                {"label": "市場流通卡數", "value": "6,049 萬張", "metric_id": "demo_1"},
                {"label": "台新市占率", "value": "8.5%", "metric_id": "demo_2"},
                {"label": "台新有效卡率", "value": "72.3%", "metric_id": "demo_3"},
            ]

        elif spec["layout"] == "ranking_chart":
            spec["headline"] = "各銀行流通卡數市占率"
            spec["chart"] = {
                "type": "bar",
                "title": "流通卡數市占率排名",
                "categories": ["中國信託", "國泰世華", "台新銀行", "玉山銀行", "台北富邦"],
                "series": [{"name": "市占率(%)", "data": [18.5, 15.2, 8.5, 7.8, 7.2]}],
            }

        elif spec["layout"] == "strategy":
            spec["headline"] = "台新信用卡業務策略建議"
            spec["recommendations"] = [
                {"action": "提升有效卡率至 75% 以上", "rationale": "降低無效卡管理成本", "priority": "high"},
                {"action": "拓展高消費力客群", "rationale": "提升每卡簽帳金額", "priority": "high"},
                {"action": "優化分期產品組合", "rationale": "把握分期消費趨勢", "priority": "medium"},
            ]

        specs.append(spec)
    return specs


if __name__ == "__main__":
    spec_path = sys.argv[1] if len(sys.argv) > 1 else None
    template_path = sys.argv[2] if len(sys.argv) > 2 else None
    run_task3(slide_spec_path=spec_path, template_path=template_path)
