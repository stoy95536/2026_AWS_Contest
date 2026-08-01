"""
Analyst Agent — 分析師 Agent
選擇指標與比較對象，根據已驗證資料產生具商業價值的策略洞察。
"""

import json
import os
import warnings
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

import boto3


class AnalystAgent:
    """
    分析師 Agent：
    - 選擇適合的指標、圖表及比較對象
    - 根據已驗證的計算結果撰寫商業洞察
    - 產生標題、摘要及策略建議
    - 不自行計算數值，只引用計算引擎結果
    """

    def __init__(self, model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0", region: str = "us-east-1"):
        self.model_id = model_id
        self.region = region
        self._client = None

    @property
    def bedrock_client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                verify=False,
            )
        return self._client

    def _load_system_prompt(self) -> str:
        """載入系統提示詞。"""
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "prompts", "system_prompt.md"
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "你是專業金融分析師 AI。"

    def generate_insights(
        self,
        slide_spec: dict,
        metric_data: list[dict],
        use_llm: bool = True,
    ) -> dict:
        """
        為單頁簡報生成洞察內容。

        Args:
            slide_spec: 該頁的規格（來自 PlannerAgent）
            metric_data: 與該頁相關的計算引擎結果
            use_llm: 是否使用 LLM

        Returns:
            enriched slide_spec with insights, headlines, recommendations
        """
        if not use_llm:
            return self._rule_based_insights(slide_spec, metric_data)

        try:
            return self._llm_insights(slide_spec, metric_data)
        except Exception as e:
            print(f"[AnalystAgent] LLM 洞察生成失敗: {type(e).__name__}: {e}")
            return self._rule_based_insights(slide_spec, metric_data)

    def _rule_based_insights(self, slide_spec: dict, metric_data: list[dict]) -> dict:
        """基於規則的洞察生成。"""
        enriched = slide_spec.copy()
        layout = slide_spec.get("layout", "")

        if layout == "trend_chart":
            enriched["insights"] = self._trend_insights(metric_data)
        elif layout == "ranking_chart":
            enriched["insights"] = self._ranking_insights(metric_data)
        elif layout == "scatter_chart":
            enriched["insights"] = self._quadrant_insights(metric_data)
        elif layout == "comparison_chart":
            enriched["insights"] = self._comparison_insights(metric_data)
        elif layout == "stacked_chart":
            enriched["insights"] = self._credit_insights(metric_data)
        elif layout == "risk_chart":
            enriched["insights"] = self._risk_insights(metric_data)
        elif layout == "strategy":
            enriched["recommendations"] = self._strategy_recommendations(metric_data)

        # 確保所有洞察都有 source_ids
        source_ids = []
        for item in metric_data:
            if "metric_id" in item:
                source_ids.append(item["metric_id"])
        enriched["source_ids"] = source_ids

        return enriched

    def _trend_insights(self, metric_data: list[dict]) -> list[dict]:
        """市場趨勢洞察。"""
        insights = []
        if metric_data:
            insights.append({
                "text": "市場卡數維持穩定成長，簽帳金額波動幅度相對較大，顯示消費行為有季節性影響。",
                "evidence_metric_ids": [m.get("metric_id", "") for m in metric_data[:2]],
                "is_speculation": False,
            })
            insights.append({
                "text": "簽帳金額的變動幅度明顯高於卡數，顯示市場競爭重點可能已由發卡規模逐步轉向卡戶活躍度。",
                "evidence_metric_ids": [m.get("metric_id", "") for m in metric_data[:2]],
                "is_speculation": True,
            })
        return insights

    def _ranking_insights(self, metric_data: list[dict]) -> list[dict]:
        """排名洞察。"""
        return [{
            "text": "市場集中度維持在前五大銀行，市占率結構相對穩定。",
            "evidence_metric_ids": [m.get("metric_id", "") for m in metric_data[:5]],
            "is_speculation": False,
        }]

    def _quadrant_insights(self, metric_data: list[dict]) -> list[dict]:
        """象限分析洞察。"""
        return [{
            "text": "規模較大的銀行成長速度趨緩，中小型銀行則展現較高的成長動能。",
            "evidence_metric_ids": [m.get("metric_id", "") for m in metric_data],
            "is_speculation": True,
        }]

    def _comparison_insights(self, metric_data: list[dict]) -> list[dict]:
        """比較分析洞察。"""
        return [{
            "text": "各銀行在該指標上存在顯著差異，反映不同的客群經營策略。",
            "evidence_metric_ids": [m.get("metric_id", "") for m in metric_data],
            "is_speculation": False,
        }]

    def _credit_insights(self, metric_data: list[dict]) -> list[dict]:
        """信用結構洞察。"""
        return [{
            "text": "分期付款餘額佔比逐漸提升，反映消費者偏好分期消費模式。",
            "evidence_metric_ids": [m.get("metric_id", "") for m in metric_data],
            "is_speculation": True,
        }]

    def _risk_insights(self, metric_data: list[dict]) -> list[dict]:
        """風險洞察。"""
        return [{
            "text": "整體逾期率維持低檔，但個別銀行的風險指標須持續關注。",
            "evidence_metric_ids": [m.get("metric_id", "") for m in metric_data],
            "is_speculation": False,
        }]

    def _strategy_recommendations(self, metric_data: list[dict]) -> list[dict]:
        """策略建議。"""
        return [
            {"action": "提升有效卡率至市場前段水準", "rationale": "降低無效卡管理成本", "priority": "high"},
            {"action": "拓展高消費力客群", "rationale": "提升每卡簽帳金額表現", "priority": "high"},
            {"action": "優化分期產品組合", "rationale": "把握分期消費趨勢", "priority": "medium"},
            {"action": "強化風險預警機制", "rationale": "維持資產品質穩定", "priority": "medium"},
        ]

    def _llm_insights(self, slide_spec: dict, metric_data: list[dict]) -> dict:
        """使用 LLM 生成洞察。"""
        system_prompt = self._load_system_prompt()

        user_message = f"""
請為以下簡報頁面生成商業洞察。

## 頁面規格
{json.dumps(slide_spec, ensure_ascii=False, indent=2)}

## 已驗證的計算結果（只能引用這些數字）
{json.dumps(metric_data, ensure_ascii=False, indent=2)}

## 要求
1. 只能引用上方提供的數字，不得自行計算或新增
2. 每項洞察包含：發生什麼、為什麼重要、可能原因、建議行動
3. 推測性內容標注 is_speculation: true
4. 輸出 JSON 格式的 enriched slide_spec

請輸出完整的 slide_spec JSON。
"""

        response = self.bedrock_client.converse(
            modelId=self.model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 2048, "temperature": 0.4},
        )

        response_text = response["output"]["message"]["content"][0]["text"]

        try:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start != -1 and end > start:
                result = json.loads(response_text[start:end])
                return result
        except json.JSONDecodeError:
            pass

        return self._rule_based_insights(slide_spec, metric_data)

    def generate_all_slides(
        self,
        slide_specs: list[dict],
        all_metric_data: dict,
        use_llm: bool = True,
    ) -> list[dict]:
        """
        為所有簡報頁面生成洞察。

        Args:
            slide_specs: 所有頁面規格（來自 PlannerAgent）
            all_metric_data: 所有計算結果，以 slide_no 為 key
            use_llm: 是否使用 LLM

        Returns:
            enriched slide_specs 陣列
        """
        enriched_slides = []
        for spec in slide_specs:
            slide_no = spec.get("slide_no", 0)
            metric_data = all_metric_data.get(slide_no, [])
            enriched = self.generate_insights(spec, metric_data, use_llm=use_llm)
            enriched_slides.append(enriched)
        return enriched_slides
