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
        model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0",
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
        """載入並解析 Excel。"""
        loader = ExcelLoader(self.config.excel_path)
        standardizer = DataStandardizer(self.config.excel_path)

        for sheet_name in loader.get_sheet_names():
            try:
                header_row = loader.detect_header_row(sheet_name)
                df = loader.read_sheet_to_dataframe(sheet_name, header_row=header_row)
                if not df.empty:
                    standardizer.standardize_dataframe(df, sheet_name)
            except Exception as e:
                print(f"  [Warning] 工作表 '{sheet_name}' 解析失敗: {e}")

        loader.close()
        return standardizer.to_dataframe()

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
        """規劃簡報結構。"""
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
        return planner.plan_structure(data_summary, use_llm=self.config.use_llm)

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

        # 匯出 slide_spec JSON
        spec_output = os.path.join(self.config.output_dir, "slide_spec.json")
        with open(spec_output, "w", encoding="utf-8") as f:
            json.dump(slide_specs, f, ensure_ascii=False, indent=2)
        self.result.slide_spec_path = spec_output

        # 匯出 QA 報告
        qa_output = os.path.join(self.config.output_dir, "qa_report.json")
        with open(qa_output, "w", encoding="utf-8") as f:
            json.dump(qa_report, f, ensure_ascii=False, indent=2)
        self.result.qa_report_path = qa_output
