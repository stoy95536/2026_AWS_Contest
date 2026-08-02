"""
Analyst Agent — 策略洞察生成器

完全由資料驅動，不內建任何特定產業的洞察文字。
- LLM 模式：由 LLM 根據計算引擎結果動態撰寫洞察
- 規則模式：產出結構化的洞察骨架，由 LLM 或人工補全具體內容

輸出遵循 README 5.2：
  insights: [{"text": str, "evidence_metric_ids": [str]}]
"""

import json
import os
from typing import Optional

import boto3


class AnalystAgent:
    """
    分析師 Agent。

    設計原則：
    - 不內建任何特定產業的洞察文字
    - 規則模式下產出「洞察骨架」（結構正確但文字為通用模板）
    - LLM 模式下由 LLM 根據實際數據撰寫具體洞察
    - 所有數值引用透過 evidence_metric_ids 追溯
    """

    def __init__(self, model_id: str = None, region: str = None):
        self.model_id = model_id or os.environ.get("MODEL_ID", "anthropic.claude-sonnet-4-20250514")
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self._client = None

    @property
    def bedrock_client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )
        return self._client

    def _load_system_prompt(self) -> str:
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "prompts", "system_prompt.md"
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "你是策略顧問 AI，根據計算引擎結果產出商業洞察。不得自行計算數值。"

    # ─── 公開介面 ───────────────────────────────────────────

    def generate_insights(
        self,
        slide_spec: dict,
        metric_data: list[dict],
        use_llm: bool = True,
    ) -> dict:
        """
        為單頁簡報生成洞察。

        Args:
            slide_spec: 該頁規格（來自 PlannerAgent）
            metric_data: 該頁相關的計算引擎結果 (README 5.1 格式)

        Returns:
            enriched slide_spec (README 5.2 格式)
        """
        if not use_llm:
            return self._rule_based_insights(slide_spec, metric_data)
        try:
            return self._llm_insights(slide_spec, metric_data)
        except Exception as e:
            print(f"[AnalystAgent] LLM 洞察生成失敗: {e}")
            return self._rule_based_insights(slide_spec, metric_data)

    def generate_all_slides(
        self,
        slide_specs: list[dict],
        all_metric_data: dict,
        use_llm: bool = True,
    ) -> list[dict]:
        """為所有頁面生成洞察。"""
        enriched = []
        for spec in slide_specs:
            slide_no = spec.get("slide_no", 0)
            data = all_metric_data.get(slide_no, [])
            enriched.append(self.generate_insights(spec, data, use_llm=use_llm))
        return enriched

    # ─── 規則引擎：產出洞察骨架 ────────────────────────────────

    def _rule_based_insights(self, slide_spec: dict, metric_data: list[dict]) -> dict:
        """
        根據 layout 類型產出通用洞察骨架。
        文字不含任何產業特定用語，而是用通用的分析語言。
        """
        enriched = slide_spec.copy()
        layout = slide_spec.get("layout", "")
        title = slide_spec.get("title", "")
        available_ids = [m["metric_id"] for m in metric_data if isinstance(m, dict) and "metric_id" in m]

        # layout 到分析方法的映射
        insight_generators = {
            "trend_chart": self._gen_trend,
            "ranking_chart": self._gen_ranking,
            "scatter_chart": self._gen_scatter,
            "comparison_chart": self._gen_comparison,
            "stacked_chart": self._gen_composition,
            "risk_chart": self._gen_risk,
            "strategy": self._gen_strategy,
            "executive_summary": self._gen_summary,
        }

        generator = insight_generators.get(layout)
        if generator:
            result = generator(title, available_ids)
            enriched.update(result)

        # 確保 source_ids
        if not enriched.get("source_ids") and available_ids:
            enriched["source_ids"] = available_ids[:5]

        return enriched

    # ─── 通用洞察模板（不含任何產業特定用語）─────────────────────

    def _gen_trend(self, title: str, ids: list) -> dict:
        """趨勢分析：觀察方向、動能、轉折。"""
        return {"insights": [
            {
                "text": f"從趨勢觀察，{title}呈現階段性變化：近期動能與前期相比有明顯差異，反映外部環境或內部策略調整的影響，建議關注轉折點前後的驅動因素。",
                "evidence_metric_ids": ids[:3] if ids else [],
            },
            {
                "text": f"波動幅度的變化顯示市場活躍度正在調整中，推測與政策環境變動或季節性因素有關，建議對照同期歷史數據確認是否為結構性轉變。",
                "evidence_metric_ids": ids[:2] if ids else [],
            },
        ]}

    def _gen_ranking(self, title: str, ids: list) -> dict:
        """排名分析：集中度、位次變動、差距。"""
        return {"insights": [
            {
                "text": f"排名結構顯示市場呈現一定程度的集中，前段主體佔據主要份額。中段競爭激烈，位次互有消長，差異化能力成為突圍關鍵。",
                "evidence_metric_ids": ids[:5] if ids else [],
            },
        ]}

    def _gen_scatter(self, title: str, ids: list) -> dict:
        """象限分析：雙維度定位。"""
        return {"insights": [
            {
                "text": f"雙維度交叉分析呈現典型的分布特徵：規模大者動能趨緩（成熟態），規模小者展現較高成長潛力（成長態），存在差異化策略空間。",
                "evidence_metric_ids": ids[:5] if ids else [],
            },
            {
                "text": f"少數主體同時達成規模與動能的雙優表現，推測與其獨特策略或資源優勢有關，值得深入分析其成功要素。",
                "evidence_metric_ids": ids[:3] if ids else [],
            },
        ]}

    def _gen_comparison(self, title: str, ids: list) -> dict:
        """比較分析：同業對標、差距辨識。"""
        return {"insights": [
            {
                "text": f"各主體在此指標上存在明顯差距，領先者與落後者之間的差異反映不同的資源配置與經營策略選擇，標竿學習與差距分析可作為改善的起點。",
                "evidence_metric_ids": ids[:5] if ids else [],
            },
        ]}

    def _gen_composition(self, title: str, ids: list) -> dict:
        """結構分析：佔比、組成變遷。"""
        return {"insights": [
            {
                "text": f"結構組成正在發生遷移，新興區塊佔比逐步提升，傳統核心比重相對下降。這反映需求端的偏好變化，推測與環境趨勢或政策引導有關，建議順應結構變遷方向調整資源配置。",
                "evidence_metric_ids": ids[:3] if ids else [],
            },
        ]}

    def _gen_risk(self, title: str, ids: list) -> dict:
        """風險分析：閾值、預警。"""
        return {"insights": [
            {
                "text": f"整體風險指標維持在可接受範圍，但個別主體的指標接近或超出警戒水位，需建立分級監控機制並預備因應方案，避免局部風險擴散。",
                "evidence_metric_ids": ids[:5] if ids else [],
            },
        ]}

    def _gen_strategy(self, title: str, ids: list) -> dict:
        """策略建議：從前面的分析推導行動方案。"""
        return {
            "insights": [
                {
                    "text": "綜合前述分析，建議以「效率提升」與「結構優化」為雙主軸推動改善，同時強化風險底線管理，確保在追求成長的同時維持穩健。",
                    "evidence_metric_ids": ids if ids else [],
                },
            ],
            "recommendations": [
                {"action": "聚焦高成長潛力區塊，加速資源投入", "rationale": "數據顯示該區塊具備結構性成長空間"},
                {"action": "提升核心效率指標至同業前段水準", "rationale": "與標竿的差距代表可量化的改善機會"},
                {"action": "建立風險分級預警機制", "rationale": "部分指標趨近警戒線，需預防性干預"},
                {"action": "探索跨域合作與新場景佈局", "rationale": "單一維度成長空間有限，需開拓新價值來源"},
            ],
        }

    def _gen_summary(self, title: str, ids: list) -> dict:
        """Executive Summary。"""
        return {"insights": [
            {
                "text": "本次分析涵蓋多維度數據，揭示三大關鍵發現：整體量能維持穩定但動能分化、效率指標差距反映策略選擇差異、部分風險信號需持續關注。後續各章節將逐一深入分析。",
                "evidence_metric_ids": ids[:4] if ids else [],
            },
        ]}

    # ─── LLM 動態洞察 ────────────────────────────────────────

    def _llm_insights(self, slide_spec: dict, metric_data: list[dict]) -> dict:
        """使用 LLM 根據實際數據撰寫洞察。"""
        system_prompt = self._load_system_prompt()

        user_message = f"""
請為以下簡報頁面生成策略洞察。

## 頁面規格
{json.dumps(slide_spec, ensure_ascii=False, indent=2)}

## 計算引擎結果（你只能引用這些數字）
{json.dumps(metric_data, ensure_ascii=False, indent=2)}

## 要求
1. 輸出格式: {{"headline": str, "insights": [{{"text": str, "evidence_metric_ids": [str]}}], "source_ids": [str]}}
2. 若為策略頁則加 "recommendations": [{{"action": str, "rationale": str}}]
3. 每項洞察包含：發生什麼、為什麼重要、可能原因、建議行動
4. 不得自行計算或新增數字
5. 推測須使用「可能」「推測」「顯示」等措辭
6. headline 是一句話洞察結論，不是數字描述
7. 不要假設特定產業——根據提供的資料內容撰寫

輸出 JSON。
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
                merged = slide_spec.copy()
                for key in ("headline", "insights", "recommendations", "source_ids"):
                    if result.get(key):
                        merged[key] = result[key]
                return merged
        except json.JSONDecodeError:
            pass

        return self._rule_based_insights(slide_spec, metric_data)
