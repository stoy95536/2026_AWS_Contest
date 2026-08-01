"""
Planner Agent — 簡報結構規劃器
負責規劃 16 頁簡報的整體架構，包含每頁類型、標題及所需資料。
"""

import json
import os
import warnings
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

import boto3


# 16 頁簡報的預設結構
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


class PlannerAgent:
    """
    規劃 16 頁簡報結構的 Agent。
    可使用 LLM 或基於規則的方式產生結構。
    """

    def __init__(self, model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0", region: str = "us-east-1"):
        self.model_id = model_id
        self.region = region
        self._client = None

    @property
    def bedrock_client(self):
        """Lazy initialization of Bedrock client."""
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                verify=False,
            )
        return self._client

    def _load_prompt(self) -> str:
        """載入 Planner 的 system prompt。"""
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "prompts", "slide_planner.md"
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "你是一個簡報規劃專家，請規劃 16 頁信用卡市場分析簡報結構。"

    def plan_structure(self, data_summary: dict, use_llm: bool = True) -> list[dict]:
        """
        規劃 16 頁簡報結構。

        Args:
            data_summary: 資料引擎的摘要，含有可用指標、期間、機構等
            use_llm: 是否使用 LLM 增強規劃（否則使用預設結構）

        Returns:
            16 頁 slide_spec 陣列
        """
        if not use_llm:
            return self._rule_based_plan(data_summary)

        try:
            return self._llm_plan(data_summary)
        except Exception as e:
            print(f"[PlannerAgent] LLM 規劃失敗，使用預設結構: {type(e).__name__}: {e}")
            return self._rule_based_plan(data_summary)

    def _rule_based_plan(self, data_summary: dict) -> list[dict]:
        """基於規則的簡報結構規劃。"""
        slides = []
        available_metrics = data_summary.get("metrics", [])
        available_periods = data_summary.get("periods", [])
        institutions = data_summary.get("institutions", [])
        latest_period = available_periods[-1] if available_periods else ""

        for template in DEFAULT_SLIDE_STRUCTURE:
            slide = template.copy()
            slide["headline"] = ""
            slide["kpis"] = []
            slide["chart"] = None
            slide["table"] = None
            slide["insights"] = []
            slide["recommendations"] = []
            slide["source_ids"] = []

            # 根據頁面類型填充細節
            if slide["layout"] == "executive_summary":
                slide["headline"] = "市場關鍵指標摘要"
                slide["kpis"] = self._build_executive_kpis(data_summary)

            elif slide["layout"] == "trend_chart":
                slide["headline"] = "市場卡數與簽帳金額走勢"
                slide["chart"] = {
                    "type": "combo",
                    "title": "市場規模趨勢 — 流通卡數與簽帳金額",
                    "x_axis": {"label": "月份", "unit": ""},
                    "y_axis": {"label": "金額/卡數", "unit": ""},
                    "series_metric_ids": [
                        f"market_total_cards_{p}" for p in available_periods
                    ],
                }

            elif slide["layout"] == "ranking_chart":
                slide["headline"] = "各銀行市占率排名"
                slide["chart"] = {
                    "type": "bar",
                    "title": "流通卡數市占率排名",
                    "x_axis": {"label": "銀行", "unit": ""},
                    "y_axis": {"label": "市占率", "unit": "%"},
                }

            elif slide["layout"] == "scatter_chart":
                slide["headline"] = "規模與成長象限分析"
                slide["chart"] = {
                    "type": "scatter",
                    "title": "規模 vs 成長率散佈圖",
                    "x_axis": {"label": "流通卡數（規模）", "unit": "萬張"},
                    "y_axis": {"label": "月增率", "unit": "%"},
                }

            elif slide["layout"] == "comparison_chart" and slide["slide_no"] == 9:
                slide["headline"] = "有效卡率同業比較"
                slide["chart"] = {
                    "type": "bar",
                    "title": "有效卡率比較",
                    "x_axis": {"label": "銀行", "unit": ""},
                    "y_axis": {"label": "有效卡率", "unit": "%"},
                }

            elif slide["layout"] == "comparison_chart" and slide["slide_no"] == 11:
                slide["headline"] = "每卡消費力分析"
                slide["chart"] = {
                    "type": "bar",
                    "title": "平均每卡簽帳金額比較",
                    "x_axis": {"label": "銀行", "unit": ""},
                    "y_axis": {"label": "平均每卡簽帳金額", "unit": "元"},
                }

            elif slide["layout"] == "stacked_chart":
                slide["headline"] = "信用結構分析"
                slide["chart"] = {
                    "type": "stacked_bar",
                    "title": "循環信用與分期付款餘額",
                    "x_axis": {"label": "銀行", "unit": ""},
                    "y_axis": {"label": "餘額", "unit": "億元"},
                }

            elif slide["layout"] == "risk_chart":
                slide["headline"] = "風險指標總覽"
                slide["chart"] = {
                    "type": "bar",
                    "title": "逾期率與呆帳率比較",
                    "x_axis": {"label": "銀行", "unit": ""},
                    "y_axis": {"label": "比率", "unit": "%"},
                }

            elif slide["layout"] == "strategy":
                slide["headline"] = "台新信用卡業務策略建議"
                slide["recommendations"] = [
                    {"action": "提升有效卡率", "rationale": "依據市場數據分析", "priority": "high"},
                    {"action": "拓展高消費客群", "rationale": "提升每卡簽帳金額", "priority": "high"},
                    {"action": "強化風險控管", "rationale": "維持資產品質", "priority": "medium"},
                ]

            slides.append(slide)

        return slides

    def _build_executive_kpis(self, data_summary: dict) -> list[dict]:
        """建立 Executive Summary 的 KPI 清單。"""
        return [
            {"label": "市場流通卡數", "value": "", "metric_id": "market_total_cards"},
            {"label": "台新市占率", "value": "", "metric_id": "taishin_market_share"},
            {"label": "台新有效卡率", "value": "", "metric_id": "taishin_effective_rate"},
            {"label": "台新每卡簽帳金額", "value": "", "metric_id": "taishin_avg_purchase"},
        ]

    def _llm_plan(self, data_summary: dict) -> list[dict]:
        """使用 LLM 增強的簡報規劃。"""
        system_prompt = self._load_prompt()

        user_message = f"""
根據以下資料摘要，規劃 16 頁信用卡市場分析簡報的結構。

## 可用資料摘要
- 機構列表: {data_summary.get('institutions', [])}
- 可用指標: {data_summary.get('metrics', [])}
- 期間範圍: {data_summary.get('periods', [])}
- 資料筆數: {data_summary.get('record_count', 0)}

請輸出 JSON 陣列，每個元素代表一頁的規格。
"""

        response = self.bedrock_client.converse(
            modelId=self.model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.3},
        )

        response_text = response["output"]["message"]["content"][0]["text"]

        # 嘗試解析 JSON
        try:
            # 找出 JSON 陣列部分
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start != -1 and end > start:
                slides = json.loads(response_text[start:end])
                return slides
        except json.JSONDecodeError:
            pass

        # 解析失敗，回退到規則方式
        return self._rule_based_plan(data_summary)
