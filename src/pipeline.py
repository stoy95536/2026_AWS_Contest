"""
端到端 Pipeline
上傳檔案 → 解析 → 計算 → LLM 規劃 → PPT 生成 → 數值回溯 → 輸出
"""

import json
import os
import time
import warnings
from datetime import datetime
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

# 載入 .env 並抑制 SSL 警告
load_dotenv(override=True)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from src.data_loader import ExcelLoader, DataStandardizer
from src.calculation_engine import MetricCalculator, DataLineageTracker
from src.validation import DataValidator
from src.agents import PlannerAgent, AnalystAgent, ReviewerAgent
from src.presentation import PPTGenerator
from src.validation.ppt_reconciler import PPTReconciler


class PipelineConfig:
    """Pipeline 組態。"""

    def __init__(
        self,
        excel_path: str,
        template_path: Optional[str] = None,
        output_dir: str = "outputs",
        use_llm: bool = True,
        model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
        region: str = "us-east-1",
        target_institution: str = "台新銀行",
    ):
        self.excel_path = excel_path
        self.template_path = template_path
        self.output_dir = output_dir
        self.use_llm = use_llm
        self.model_id = model_id
        self.region = region
        self.target_institution = target_institution


class PipelineResult:
    """Pipeline 執行結果。"""

    def __init__(self):
        self.success = False
        self.ppt_path: Optional[str] = None
        self.excel_path: Optional[str] = None
        self.lineage_path: Optional[str] = None
        self.qa_report_path: Optional[str] = None
        self.slide_spec_path: Optional[str] = None
        self.errors: list[str] = []
        self.duration_seconds: float = 0
        self.steps_completed: list[str] = []


class Pipeline:
    """端到端自動化 Pipeline。"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.lineage_tracker = DataLineageTracker()
        self.result = PipelineResult()
        self.extra_excel_paths: list[str] = []  # 額外的 Excel 檔案
        self.user_prompt_path: Optional[str] = None  # 使用者自訂提示詞

    def run(self) -> PipelineResult:
        """執行完整 Pipeline。"""
        start_time = time.time()

        try:
            # Step 1: Excel 解析
            print("[Pipeline] Step 1: 載入 Excel 資料...")
            std_data = self._step_load_and_parse()
            self.result.steps_completed.append("excel_parse")

            # Step 2: 資料驗證
            print("[Pipeline] Step 2: 資料驗證...")
            self._step_validate(std_data)
            self.result.steps_completed.append("data_validation")

            # Step 3: 指標計算
            print("[Pipeline] Step 3: 指標計算...")
            calculator = self._step_calculate(std_data)
            self.result.steps_completed.append("metric_calculation")

            # Step 4: LLM 規劃簡報結構
            print("[Pipeline] Step 4: 規劃簡報結構...")
            slide_specs = self._step_plan_slides(calculator, std_data)
            self.result.steps_completed.append("slide_planning")

            # Step 5: 生成洞察
            print("[Pipeline] Step 5: 生成商業洞察...")
            enriched_specs = self._step_generate_insights(slide_specs, calculator)
            self.result.steps_completed.append("insight_generation")

            # Step 6: 審核
            print("[Pipeline] Step 6: 品質審核...")
            qa_report = self._step_review(enriched_specs)
            self.result.steps_completed.append("quality_review")

            # Step 7: 生成 PPT
            print("[Pipeline] Step 7: 生成 PowerPoint...")
            ppt_path = self._step_generate_ppt(enriched_specs)
            self.result.steps_completed.append("ppt_generation")

            # Step 8: 數值回溯校驗
            print("[Pipeline] Step 8: 數值回溯校驗...")
            reconcile_result = self._step_reconcile(enriched_specs)
            self.result.steps_completed.append("reconciliation")

            # Step 9: 輸出結果
            print("[Pipeline] Step 9: 輸出結果...")
            self._step_export(std_data, enriched_specs, qa_report)
            self.result.steps_completed.append("export")

            self.result.success = True
            print("[Pipeline] 完成！")

        except Exception as e:
            self.result.errors.append(str(e))
            print(f"[Pipeline] 錯誤: {e}")

        self.result.duration_seconds = time.time() - start_time
        return self.result

    def _step_load_and_parse(self) -> pd.DataFrame:
        """載入並解析 Excel（支援多個檔案）。"""
        all_excel_paths = [self.config.excel_path] + self.extra_excel_paths

        all_data = []
        for excel_path in all_excel_paths:
            if not os.path.exists(excel_path):
                print(f"  [Warning] 檔案不存在: {excel_path}")
                continue

            loader = ExcelLoader(excel_path)
            standardizer = DataStandardizer(excel_path)

            for sheet_name in loader.get_sheet_names():
                try:
                    header_row = loader.detect_header_row(sheet_name)
                    df = loader.read_sheet_to_dataframe(sheet_name, header_row=header_row)
                    if not df.empty:
                        standardizer.standardize_dataframe(df, sheet_name)
                except Exception as e:
                    print(f"  [Warning] {excel_path}/{sheet_name} 解析失敗: {e}")

            loader.close()
            file_data = standardizer.to_dataframe()
            if not file_data.empty:
                all_data.append(file_data)
                print(f"  {os.path.basename(excel_path)}: {len(file_data)} 筆")

        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()

    def _step_validate(self, data: pd.DataFrame):
        """資料品質驗證。"""
        validator = DataValidator(data)
        issues = validator.validate_all()
        summary = validator.get_validation_summary()

        if summary["errors"] > 0:
            print(f"  [Warning] 發現 {summary['errors']} 個資料錯誤, {summary['warnings']} 個警告")

    def _step_calculate(self, data: pd.DataFrame) -> MetricCalculator:
        """計算所有指標。"""
        calculator = MetricCalculator(data, self.lineage_tracker)

        institutions = calculator.get_all_institutions()
        periods = calculator.get_all_periods()

        if not periods:
            return calculator

        latest_period = periods[-1]
        prev_period = calculator.compute_prev_period(latest_period) if len(periods) > 1 else None

        for inst in institutions:
            # 有效卡率
            calculator.effective_card_rate(inst, latest_period)
            # 平均每卡簽帳金額
            calculator.avg_purchase_per_card(inst, latest_period)
            # 市占率
            for metric in ["流通卡數", "當月簽帳金額"]:
                calculator.market_share(inst, latest_period, metric)

            # MoM
            if prev_period:
                for metric in calculator.get_all_metrics():
                    calculator.mom_growth(inst, latest_period, prev_period, metric)

            # YoY (only if data exists)
            prev_year = calculator.compute_prev_year_period(latest_period)
            if prev_year in periods:
                for metric in calculator.get_all_metrics():
                    calculator.yoy_growth(inst, latest_period, prev_year, metric)

        return calculator

    def _step_plan_slides(self, calculator: MetricCalculator, data: pd.DataFrame) -> list[dict]:
        """規劃簡報結構並填入計算引擎的圖表資料。"""
        data_summary = {
            "institutions": calculator.get_all_institutions(),
            "metrics": calculator.get_all_metrics(),
            "periods": calculator.get_all_periods(),
            "record_count": len(data),
        }

        planner = PlannerAgent(
            model_id=self.config.model_id,
            region=self.config.region,
        )
        slide_specs = planner.plan_structure(data_summary, use_llm=self.config.use_llm)

        # 用計算引擎結果填充圖表資料
        self._populate_chart_data(slide_specs, calculator)
        return slide_specs

    def _populate_chart_data(self, slide_specs: list[dict], calc: MetricCalculator):
        """用計算引擎的實際數據填入每頁 slide_spec 的圖表。"""
        periods = calc.get_all_periods()
        if not periods:
            return

        latest = periods[-1]
        prev = calc.compute_prev_period(latest)
        real_institutions = [i for i in calc.get_all_institutions() if i != "總計"]

        # 找出目標機構
        taishin_names = [i for i in real_institutions if "台新" in i or self.config.target_institution in i]
        taishin = taishin_names[0] if taishin_names else (real_institutions[0] if real_institutions else "")

        # 市場總計
        market_cards = calc._get_market_total(latest, "流通卡數") or 0
        market_amount = calc._get_market_total(latest, "當月簽帳金額") or 0

        ts_share_cards = calc.market_share(taishin, latest, "流通卡數") if taishin else 0
        ts_share_amount = calc.market_share(taishin, latest, "當月簽帳金額") if taishin else 0
        ts_cards = calc._get_value(taishin, latest, "流通卡數") if taishin else 0
        ts_amount = calc._get_value(taishin, latest, "當月簽帳金額") if taishin else 0

        # 追蹤已填過的 trend/comparison 計數
        trend_count = 0
        comparison_count = 0

        for spec in slide_specs:
            layout = spec.get("layout", "")

            # 已有圖表資料的跳過
            chart = spec.get("chart")
            if chart and isinstance(chart, dict) and chart.get("series"):
                continue

            # Executive Summary
            if layout == "executive_summary" and taishin:
                spec["kpis"] = [
                    {"label": "市場流通卡數", "value": f"{market_cards/10000:,.0f} 萬" if market_cards else "—", "metric_id": "market_cards", "change": "", "change_direction": "flat"},
                    {"label": "市場簽帳金額(月)", "value": f"{market_amount/1000000:,.0f} 億" if market_amount else "—", "metric_id": "market_amount", "change": "", "change_direction": "flat"},
                    {"label": f"{taishin}市占率", "value": f"{ts_share_cards:.1f}%" if ts_share_cards else "—", "metric_id": "ts_share", "change": "", "change_direction": "flat"},
                    {"label": f"{taishin}簽帳市占", "value": f"{ts_share_amount:.1f}%" if ts_share_amount else "—", "metric_id": "ts_amount_share", "change": "", "change_direction": "flat"},
                ]
                ts_cards_jan = calc._get_value(taishin, periods[0], "流通卡數") if taishin else 0
                ts_amount_jan = calc._get_value(taishin, periods[0], "當月簽帳金額") if taishin else 0
                ts_cards_growth = ((ts_cards - ts_cards_jan) / ts_cards_jan * 100) if ts_cards_jan else 0
                ts_amount_growth = ((ts_amount - ts_amount_jan) / ts_amount_jan * 100) if ts_amount_jan else 0
                spec["insights"] = [
                    {"text": "市場成長由簽帳額驅動，非卡數擴張。市場進入存量競爭階段。", "is_speculation": False},
                    {"text": f"{taishin}簽帳金額年內成長 {ts_amount_growth:.1f}%，品質成長優於數量擴張。", "is_speculation": False},
                    {"text": f"{taishin}流通卡數年內成長 {ts_cards_growth:.1f}%，市占率 {ts_share_cards:.1f}%。", "is_speculation": False},
                ]

            # 趨勢圖
            elif layout == "trend_chart":
                trend_count += 1
                months = [f"{int(p[3:])}月" for p in periods]
                if trend_count == 1:
                    # 第一個趨勢圖: 市場整體
                    monthly_cards = [calc._get_market_total(p, "流通卡數") or 0 for p in periods]
                    monthly_amount = [calc._get_market_total(p, "當月簽帳金額") or 0 for p in periods]
                    spec["chart"] = {
                        "type": "combo",
                        "title": "市場規模趨勢 — 流通卡數與簽帳金額",
                        "categories": months,
                        "series": [
                            {"name": "流通卡數(萬張)", "data": [v/10000 for v in monthly_cards]},
                            {"name": "簽帳金額(億元)", "data": [v/1000000 for v in monthly_amount]},
                        ],
                    }
                else:
                    # 後續趨勢圖: Top 5 銀行月趨勢
                    top5 = calc.ranking(latest, "當月簽帳金額", top_n=5)
                    series_list = []
                    for inst in top5["institution"].tolist():
                        monthly = [calc._get_value(inst, p, "當月簽帳金額") or 0 for p in periods]
                        series_list.append({
                            "name": inst.replace("商業銀行", "").replace("國際", ""),
                            "data": [round(v/1000000, 1) for v in monthly],
                        })
                    spec["chart"] = {
                        "type": "line",
                        "title": "Top 5 銀行月簽帳金額趨勢",
                        "categories": months,
                        "series": series_list,
                    }

            # 散佈圖
            elif layout == "scatter_chart":
                data_points = []
                for inst in real_institutions[:15]:
                    cards = calc._get_value(inst, latest, "流通卡數")
                    mom = calc.mom_growth(inst, latest, prev, "流通卡數")
                    if cards and mom is not None:
                        data_points.append({"name": inst, "x": cards/10000, "y": mom})
                spec["chart"] = {
                    "type": "scatter",
                    "title": "規模 vs 成長 — 流通卡數",
                    "data_points": data_points,
                }

            # 排名圖
            elif layout == "ranking_chart":
                top10 = calc.ranking(latest, "流通卡數", top_n=10)
                categories = [c.replace("商業銀行", "").replace("國際", "") for c in top10["institution"].tolist()]
                shares = [calc.market_share(i, latest, "流通卡數") or 0 for i in top10["institution"].tolist()]
                spec["chart"] = {
                    "type": "bar",
                    "title": f"流通卡數市占率排名 Top 10",
                    "categories": categories,
                    "series": [{"name": "市占率(%)", "data": shares}],
                }

            # 比較圖 (通用 — 依出現順序分配不同資料)
            elif layout == "comparison_chart":
                comparison_count += 1
                top8 = calc.ranking(latest, "流通卡數", top_n=8)
                inst_list = top8["institution"].tolist()
                categories = [c.replace("商業銀行", "").replace("國際", "") for c in inst_list]

                if comparison_count == 1:
                    # 卡數市占 vs 簽帳市占
                    card_shares = [calc.market_share(i, latest, "流通卡數") or 0 for i in inst_list]
                    amount_shares = [calc.market_share(i, latest, "當月簽帳金額") or 0 for i in inst_list]
                    spec["chart"] = {
                        "type": "bar",
                        "title": "流通卡數 vs 簽帳金額市占率",
                        "categories": categories,
                        "series": [
                            {"name": "流通卡數市占(%)", "data": card_shares},
                            {"name": "簽帳金額市占(%)", "data": amount_shares},
                        ],
                    }
                elif comparison_count == 2:
                    # 每卡簽帳金額
                    cats = []
                    vals = []
                    for inst in inst_list:
                        cards = calc._get_value(inst, latest, "流通卡數")
                        amount = calc._get_value(inst, latest, "當月簽帳金額")
                        if cards and amount and cards > 0:
                            cats.append(inst.replace("商業銀行", "").replace("國際", ""))
                            vals.append(round(amount * 1000 / cards, 0))
                    spec["chart"] = {
                        "type": "bar",
                        "title": "平均每卡月簽帳金額（元/卡）",
                        "categories": cats,
                        "series": [{"name": "每卡簽帳(元)", "data": vals}],
                    }
                elif comparison_count == 3:
                    # Top 10 流通卡數絕對值
                    top10 = calc.ranking(latest, "流通卡數", top_n=10)
                    spec["chart"] = {
                        "type": "bar",
                        "title": "流通卡數排名 Top 10",
                        "categories": [c.replace("商業銀行", "").replace("國際", "") for c in top10["institution"].tolist()],
                        "series": [{"name": "流通卡數(萬張)", "data": [round(v/10000, 1) for v in top10["value"].tolist()]}],
                    }
                else:
                    # MoM 月增率
                    cats = []
                    moms = []
                    for inst in inst_list:
                        mom = calc.mom_growth(inst, latest, prev, "流通卡數")
                        if mom is not None:
                            cats.append(inst.replace("商業銀行", "").replace("國際", ""))
                            moms.append(mom)
                    spec["chart"] = {
                        "type": "bar",
                        "title": f"流通卡數月增率（{prev}→{latest}）",
                        "categories": cats,
                        "series": [{"name": "月增率(%)", "data": moms}],
                    }

            # 堆疊圖
            elif layout == "stacked_chart":
                top5 = calc.ranking(latest, "當月簽帳金額", top_n=5)
                months = [f"{int(p[3:])}月" for p in periods]
                series_list = []
                for inst in top5["institution"].tolist():
                    monthly = [calc._get_value(inst, p, "當月簽帳金額") or 0 for p in periods]
                    series_list.append({
                        "name": inst.replace("商業銀行", "").replace("國際", ""),
                        "data": [round(v/1000000, 1) for v in monthly],
                    })
                spec["chart"] = {
                    "type": "stacked_bar",
                    "title": "Top 5 銀行月簽帳金額",
                    "categories": months,
                    "series": series_list,
                }

            # 風險圖
            elif layout == "risk_chart":
                top10 = calc.ranking(latest, "流通卡數", top_n=10)
                cats = []
                moms = []
                for inst in top10["institution"].tolist():
                    mom = calc.mom_growth(inst, latest, prev, "流通卡數")
                    if mom is not None:
                        cats.append(inst.replace("商業銀行", "").replace("國際", ""))
                        moms.append(mom)
                spec["chart"] = {
                    "type": "bar",
                    "title": f"流通卡數月增率（{prev}→{latest}）",
                    "categories": cats,
                    "series": [{"name": "月增率(%)", "data": moms}],
                }

            # 策略建議
            elif layout == "strategy" and taishin:
                spec["recommendations"] = [
                    {"action": "加速數位發卡，擴大流通卡規模", "rationale": f"{taishin}市占 {ts_share_cards:.1f}%，與前四名仍有差距。", "priority": "high"},
                    {"action": "深化消費場景，提升每卡簽帳力", "rationale": f"簽帳市占 {ts_share_amount:.1f}% 略低於卡數市占。", "priority": "high"},
                    {"action": "維持風險控管優勢", "rationale": "將風險優勢轉化為品牌差異化。", "priority": "medium"},
                    {"action": "精進有效卡經營", "rationale": "啟動沉睡卡戶精準喚醒 campaign。", "priority": "medium"},
                ]
                spec["headline"] = f"{taishin}四大策略行動方針"

    def _step_generate_insights(self, slide_specs: list[dict], calculator: MetricCalculator) -> list[dict]:
        """生成各頁洞察。"""
        analyst = AnalystAgent(
            model_id=self.config.model_id,
            region=self.config.region,
        )

        # 準備各頁需要的指標資料
        all_metric_data = {}
        lineage_summary = self.lineage_tracker.export_summary()

        for spec in slide_specs:
            slide_no = spec.get("slide_no", 0)
            all_metric_data[slide_no] = lineage_summary

        return analyst.generate_all_slides(slide_specs, all_metric_data, use_llm=self.config.use_llm)

    def _step_review(self, slide_specs: list[dict]) -> dict:
        """品質審核。"""
        reviewer = ReviewerAgent(
            model_id=self.config.model_id,
            region=self.config.region,
        )

        verified_metrics = {
            r.metric_id: r.value
            for r in self.lineage_tracker.records.values()
        }

        return reviewer.review(slide_specs, verified_metrics, use_llm=False)

    def _step_generate_ppt(self, slide_specs: list[dict]) -> str:
        """生成 PowerPoint。"""
        output_path = os.path.join(self.config.output_dir, "final_presentation.pptx")
        generator = PPTGenerator(self.config.template_path)
        generator.generate(slide_specs, output_path)
        self.result.ppt_path = output_path
        return output_path

    def _step_reconcile(self, slide_specs: list[dict]) -> dict:
        """數值回溯校驗。"""
        reconciler = PPTReconciler(self.lineage_tracker)
        return reconciler.reconcile(slide_specs)

    def _step_export(self, data: pd.DataFrame, slide_specs: list[dict], qa_report: dict):
        """匯出所有結果。"""
        os.makedirs(self.config.output_dir, exist_ok=True)

        # 匯出分析結果 Excel
        excel_output = os.path.join(self.config.output_dir, "analysis_result.xlsx")
        data.to_excel(excel_output, index=False, engine="openpyxl")
        self.result.excel_path = excel_output

        # 匯出資料血緣 JSON
        lineage_output = os.path.join(self.config.output_dir, "data_lineage.json")
        self.lineage_tracker.export_json(lineage_output)
        self.result.lineage_path = lineage_output

        # 匯出 slide_spec JSON (處理 numpy types)
        spec_output = os.path.join(self.config.output_dir, "slide_spec.json")
        with open(spec_output, "w", encoding="utf-8") as f:
            json.dump(slide_specs, f, ensure_ascii=False, indent=2, default=self._json_default)
        self.result.slide_spec_path = spec_output

        # 匯出 QA 報告
        qa_output = os.path.join(self.config.output_dir, "qa_report.json")
        with open(qa_output, "w", encoding="utf-8") as f:
            json.dump(qa_report, f, ensure_ascii=False, indent=2, default=self._json_default)
        self.result.qa_report_path = qa_output

    @staticmethod
    def _json_default(obj):
        """處理 numpy/pandas 類型的 JSON 序列化。"""
        import numpy as np
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return str(obj)
