"""
Task 3 端到端測試腳本
讀取附件四 Excel → 生成 slide_spec（含真實資料） → 輸出 PPT（使用附件一模板）
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

from src.data_loader import ExcelLoader, DataStandardizer
from src.presentation import TemplateParser, ChartFactory, PPTGenerator

# 直接定義 16 頁結構，避免 import planner_agent 需要 boto3
DEFAULT_SLIDE_STRUCTURE = [
    {"slide_no": 1, "layout": "cover", "title": "銀行信用卡市場分析與經營洞察簡報"},
    {"slide_no": 2, "layout": "toc", "title": "目錄"},
    {"slide_no": 3, "layout": "executive_summary", "title": "Executive Summary"},
    {"slide_no": 4, "layout": "chapter_divider", "title": "Chapter 01 市場整體概況"},
    {"slide_no": 5, "layout": "trend_chart", "title": "市場規模趨勢"},
    {"slide_no": 6, "layout": "ranking_chart", "title": "市占率排名"},
    {"slide_no": 7, "layout": "chapter_divider", "title": "Chapter 02 同業競爭分析"},
    {"slide_no": 8, "layout": "scatter_chart", "title": "規模 vs 成長"},
    {"slide_no": 9, "layout": "comparison_chart", "title": "有效卡率比較"},
    {"slide_no": 10, "layout": "chapter_divider", "title": "Chapter 03 客戶活躍度與獲利能力"},
    {"slide_no": 11, "layout": "comparison_chart", "title": "每卡簽帳金額"},
    {"slide_no": 12, "layout": "stacked_chart", "title": "循環信用與分期"},
    {"slide_no": 13, "layout": "chapter_divider", "title": "Chapter 04 風險與警訊"},
    {"slide_no": 14, "layout": "risk_chart", "title": "風險指標比較"},
    {"slide_no": 15, "layout": "strategy", "title": "Chapter 05 台新策略建議"},
    {"slide_no": 16, "layout": "thank_you", "title": "感謝頁"},
]


# 路徑設定
EXCEL_PATH = "附件四_預期修正參照資料.xlsx"
TEMPLATE_PATH = "附件一_台新新光金控簡報版型.pptx"
OUTPUT_DIR = "outputs"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "test_presentation_v6.pptx")


def load_excel_data():
    """讀取附件四 Excel 並標準化。"""
    print("[Step 1] 讀取 Excel 資料...")
    loader = ExcelLoader(EXCEL_PATH)
    print(f"  工作表: {loader.get_sheet_names()}")

    standardizer = DataStandardizer(EXCEL_PATH)

    for sheet_name in loader.get_sheet_names():
        df = loader.read_sheet_to_dataframe(sheet_name)
        records = standardizer.standardize_sheet(df, sheet_name)
        if records:
            print(f"  {sheet_name}: {len(records)} 筆記錄")

    loader.close()

    std_df = standardizer.to_dataframe()
    print(f"  總計: {len(std_df)} 筆標準化記錄")
    print(f"  機構: {standardizer.get_institutions()[:5]}... 共 {len(standardizer.get_institutions())} 家")
    print(f"  期間: {standardizer.get_periods()[:3]}...{standardizer.get_periods()[-1:]}")

    return std_df, standardizer


def build_slide_specs(std_df, standardizer):
    """根據真實資料建立 16 頁 slide_spec。"""
    print("\n[Step 2] 建立 slide_spec...")

    institutions = standardizer.get_institutions()
    periods = standardizer.get_periods()
    latest_period = periods[-1] if periods else "11412"

    # 找到台新銀行的名稱
    taishin_name = None
    for inst in institutions:
        if "台新" in inst:
            taishin_name = inst
            break
    taishin_name = taishin_name or "台新國際商業銀行"

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

        layout = spec["layout"]

        if layout == "executive_summary":
            spec["headline"] = "市場關鍵指標摘要"
            # 從真實資料計算 KPI
            spec["kpis"] = _build_kpis(std_df, taishin_name, latest_period)

        elif layout == "toc":
            pass  # 目錄頁不需要資料

        elif layout in ("trend_chart",):
            # 市場規模趨勢：流通卡數逐月走勢（總計）
            spec["headline"] = "市場卡數與簽帳金額走勢"
            spec["chart"] = _build_trend_chart(std_df, periods)

        elif layout == "ranking_chart":
            # 市占率排名
            spec["headline"] = "各銀行流通卡數市占率"
            spec["chart"] = _build_ranking_chart(std_df, latest_period)

        elif layout == "scatter_chart":
            # 規模 vs 成長
            spec["headline"] = "規模與成長象限分析"
            spec["chart"] = _build_scatter_chart(std_df, periods)

        elif layout == "comparison_chart" and spec["slide_no"] == 9:
            # 有效卡率比較 — 用簽帳金額做替代
            spec["headline"] = "各銀行簽帳金額比較"
            spec["chart"] = _build_comparison_chart(std_df, latest_period, "當月簽帳金額", "簽帳金額 (千元)")

        elif layout == "comparison_chart" and spec["slide_no"] == 11:
            spec["headline"] = "各銀行流通卡數比較"
            spec["chart"] = _build_comparison_chart(std_df, latest_period, "流通卡數", "流通卡數 (張)")

        elif layout == "stacked_chart":
            spec["headline"] = "簽帳金額逐月變化"
            spec["chart"] = _build_stacked_chart(std_df, periods)

        elif layout == "risk_chart":
            spec["headline"] = "風險指標總覽"
            # 用 table 替代（若無風險指標資料）
            spec["table"] = _build_summary_table(std_df, latest_period)

        elif layout == "strategy":
            spec["headline"] = "台新信用卡業務策略建議"
            spec["recommendations"] = [
                {"action": "提升有效卡率至 75% 以上", "rationale": "根據流通卡數與簽帳金額比較，台新有提升空間", "priority": "high"},
                {"action": "拓展高消費力客群", "rationale": "提升每卡簽帳金額以追趕同業", "priority": "high"},
                {"action": "優化分期產品組合", "rationale": "把握分期消費趨勢，增加中間業務收入", "priority": "medium"},
            ]

        specs.append(spec)

    print(f"  已建立 {len(specs)} 頁 slide_spec")
    return specs


def _build_kpis(std_df, taishin_name, latest_period):
    """從真實資料建立 KPI 卡片。"""
    kpis = []

    # 市場流通卡數（總計）
    total_cards = std_df[
        (std_df["institution"] == "總計") &
        (std_df["period"] == latest_period) &
        (std_df["metric"] == "流通卡數")
    ]["value"]
    if not total_cards.empty:
        val = total_cards.iloc[0]
        kpis.append({"label": "市場流通卡數", "value": f"{val/10000:.0f} 萬張", "metric_id": "market_total_cards"})

    # 台新流通卡數
    taishin_cards = std_df[
        (std_df["institution"] == taishin_name) &
        (std_df["period"] == latest_period) &
        (std_df["metric"] == "流通卡數")
    ]["value"]
    if not taishin_cards.empty:
        val = taishin_cards.iloc[0]
        kpis.append({"label": "台新流通卡數", "value": f"{val/10000:.0f} 萬張", "metric_id": "taishin_cards"})

    # 台新市佔率
    taishin_share = std_df[
        (std_df["institution"] == taishin_name) &
        (std_df["metric"] == "流通卡數_市佔率")
    ]["value"]
    if not taishin_share.empty:
        val = taishin_share.iloc[0]
        kpis.append({"label": "台新市佔率", "value": f"{val:.1f}%", "metric_id": "taishin_share"})

    # 台新當月簽帳金額
    taishin_spend = std_df[
        (std_df["institution"] == taishin_name) &
        (std_df["period"] == latest_period) &
        (std_df["metric"] == "當月簽帳金額")
    ]["value"]
    if not taishin_spend.empty:
        val = taishin_spend.iloc[0]
        kpis.append({"label": "台新當月簽帳金額", "value": f"{val/1000:.0f} 百萬元", "metric_id": "taishin_spend"})

    return kpis


def _build_trend_chart(std_df, periods):
    """市場總計流通卡數趨勢折線圖。"""
    total_data = std_df[
        (std_df["institution"] == "總計") &
        (std_df["metric"] == "流通卡數") &
        (std_df["period"].isin(periods))
    ].sort_values("period")

    if total_data.empty:
        return None

    categories = [p[-2:] + "月" for p in total_data["period"].tolist()]
    values = [v / 10000 for v in total_data["value"].tolist()]  # 轉萬張

    return {
        "type": "line",
        "title": "市場流通卡數趨勢（萬張）",
        "categories": categories,
        "series": [{"name": "流通卡數（萬張）", "data": values}],
        "y_axis": {"label": "流通卡數", "unit": "萬張"},
    }


def _build_ranking_chart(std_df, latest_period):
    """市佔率排名長條圖。"""
    share_data = std_df[
        (std_df["metric"] == "流通卡數_市佔率") &
        (std_df["institution"] != "總計")
    ].sort_values("value", ascending=False).head(10)

    if share_data.empty:
        return None

    categories = share_data["institution"].tolist()
    values = [round(v, 2) for v in share_data["value"].tolist()]

    return {
        "type": "bar",
        "title": "流通卡數市佔率排名 TOP10",
        "categories": categories,
        "series": [{"name": "市佔率(%)", "data": values}],
        "y_axis": {"label": "市佔率", "unit": "%"},
    }


def _build_scatter_chart(std_df, periods):
    """散佈圖：流通卡數規模 vs 成長率。"""
    latest = periods[-1] if periods else None
    prev = periods[-2] if len(periods) > 1 else None
    if not latest or not prev:
        return None

    # 取各銀行最新期間的流通卡數
    latest_cards = std_df[
        (std_df["metric"] == "流通卡數") &
        (std_df["period"] == latest) &
        (std_df["institution"] != "總計")
    ].set_index("institution")["value"]

    prev_cards = std_df[
        (std_df["metric"] == "流通卡數") &
        (std_df["period"] == prev) &
        (std_df["institution"] != "總計")
    ].set_index("institution")["value"]

    data_points = []
    for inst in latest_cards.index:
        if inst in prev_cards.index and prev_cards[inst] and prev_cards[inst] > 0:
            x_val = latest_cards[inst] / 10000  # 萬張
            growth = (latest_cards[inst] - prev_cards[inst]) / prev_cards[inst] * 100
            data_points.append({"name": inst, "x": round(x_val, 1), "y": round(growth, 2)})

    if not data_points:
        return None

    # 取前10家（避免太擠）
    data_points.sort(key=lambda p: p["x"], reverse=True)
    data_points = data_points[:10]

    return {
        "type": "scatter",
        "title": "規模 vs 月增率",
        "data_points": data_points,
        "x_axis": {"label": "流通卡數（萬張）"},
        "y_axis": {"label": "月增率（%）"},
    }


def _build_comparison_chart(std_df, latest_period, metric, y_label):
    """Top 10 比較長條圖。"""
    data = std_df[
        (std_df["metric"] == metric) &
        (std_df["period"] == latest_period) &
        (std_df["institution"] != "總計")
    ].sort_values("value", ascending=False).head(10)

    if data.empty:
        return None

    categories = data["institution"].tolist()
    values = data["value"].tolist()

    return {
        "type": "bar",
        "title": f"{metric} TOP10",
        "categories": categories,
        "series": [{"name": metric, "data": values}],
        "y_axis": {"label": y_label, "unit": ""},
    }


def _build_stacked_chart(std_df, periods):
    """簽帳金額 — 取前 5 大銀行做堆疊圖。"""
    latest = periods[-1] if periods else None
    if not latest:
        return None

    # 找前5大
    top5 = std_df[
        (std_df["metric"] == "當月簽帳金額") &
        (std_df["period"] == latest) &
        (std_df["institution"] != "總計")
    ].sort_values("value", ascending=False).head(5)["institution"].tolist()

    if not top5:
        return None

    # 取最近6個月
    recent_periods = periods[-6:]
    categories = [p[-2:] + "月" for p in recent_periods]

    series_list = []
    for inst in top5:
        inst_data = std_df[
            (std_df["metric"] == "當月簽帳金額") &
            (std_df["institution"] == inst) &
            (std_df["period"].isin(recent_periods))
        ].sort_values("period")
        values = [v / 1000 for v in inst_data["value"].tolist()]  # 轉百萬
        if values:
            series_list.append({"name": inst, "data": values})

    if not series_list:
        return None

    return {
        "type": "stacked_bar",
        "title": "簽帳金額 TOP5 近 6 月趨勢（百萬元）",
        "categories": categories,
        "series": series_list,
        "y_axis": {"label": "簽帳金額", "unit": "百萬元"},
    }


def _build_summary_table(std_df, latest_period):
    """建立摘要表格（前10大銀行的關鍵指標）。"""
    # 取流通卡數前10大
    top10 = std_df[
        (std_df["metric"] == "流通卡數") &
        (std_df["period"] == latest_period) &
        (std_df["institution"] != "總計")
    ].sort_values("value", ascending=False).head(10)

    if top10.empty:
        return None

    headers = ["銀行", "流通卡數(萬張)", "簽帳金額(百萬元)", "市佔率(%)"]
    rows = []
    for _, row in top10.iterrows():
        inst = row["institution"]
        cards = row["value"] / 10000  # 萬張

        # 取簽帳金額
        spend_row = std_df[
            (std_df["metric"] == "當月簽帳金額") &
            (std_df["period"] == latest_period) &
            (std_df["institution"] == inst)
        ]["value"]
        spend = spend_row.iloc[0] / 1000 if not spend_row.empty else None  # 百萬

        # 取市佔率
        share_row = std_df[
            (std_df["metric"] == "流通卡數_市佔率") &
            (std_df["institution"] == inst)
        ]["value"]
        share = share_row.iloc[0] if not share_row.empty else None

        rows.append([
            inst,
            f"{cards:.1f}",
            f"{spend:.0f}" if spend else "N/A",
            f"{share:.2f}" if share else "N/A",
        ])

    return {"headers": headers, "rows": rows}


def generate_ppt(slide_specs):
    """生成 PPT。"""
    print(f"\n[Step 3] 生成 PowerPoint...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    generator = PPTGenerator(TEMPLATE_PATH)
    result_path = generator.generate(slide_specs, OUTPUT_FILE)
    print(f"  輸出: {result_path}")
    return result_path


def main():
    print("=" * 60)
    print("  Task 3 端到端測試：Excel → slide_spec → PPT")
    print("=" * 60)

    # Step 1: 讀取 Excel
    std_df, standardizer = load_excel_data()

    # Step 2: 建立 slide_spec
    slide_specs = build_slide_specs(std_df, standardizer)

    # 存一份 slide_spec.json 供檢視
    spec_path = os.path.join(OUTPUT_DIR, "slide_spec.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(slide_specs, f, ensure_ascii=False, indent=2)
    print(f"  slide_spec 已存: {spec_path}")

    # Step 3: 生成 PPT
    result = generate_ppt(slide_specs)

    print("\n" + "=" * 60)
    print(f"  完成！請開啟: {result}")
    print("=" * 60)


if __name__ == "__main__":
    main()
