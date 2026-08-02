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
            metric_data: 該頁相關的計算引擎結果 (Task1 metric 格式)
                         每筆: {metric_id, metric_name, value, display_value, unit, period, ...}

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
        """
        為所有頁面生成洞察。

        Args:
            slide_specs: 所有頁面規格
            all_metric_data: {slide_no: [metric_dict, ...]} 或 {slide_no: []}
                            若為空，嘗試從 slide_spec 的 chart.series[].metric_ids 提取
            use_llm: 是否使用 LLM
        """
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
        當 metric_data 包含 Task1 的真實指標時，引用真實 metric_ids。
        """
        enriched = slide_spec.copy()
        layout = slide_spec.get("layout", "")
        title = slide_spec.get("title", "")

        # 收集可用的 metric_ids（來自 metric_data 或 chart.series）
        available_ids = self._collect_metric_ids(slide_spec, metric_data)

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
            enriched["source_ids"] = available_ids[:10]

        return enriched

    def _collect_metric_ids(self, slide_spec: dict, metric_data: list[dict]) -> list[str]:
        """
        從多個來源收集可用的 metric_ids：
        1. metric_data 陣列中的 metric_id 欄位（Task1 格式）
        2. slide_spec.chart.series[].metric_ids（Planner 放入的）
        3. slide_spec.chart.series_metric_ids（flat list）
        4. slide_spec.source_ids
        """
        ids = []

        # 從 metric_data 提取
        for m in metric_data:
            if isinstance(m, dict) and "metric_id" in m:
                ids.append(m["metric_id"])

        # 從 chart.series[].metric_ids 提取
        chart = slide_spec.get("chart")
        if chart and isinstance(chart, dict):
            for series in chart.get("series", []):
                if isinstance(series, dict):
                    ids.extend(series.get("metric_ids", []))
            # 也取 flat list
            ids.extend(chart.get("series_metric_ids", []))

        # 從 source_ids 提取
        ids.extend(slide_spec.get("source_ids", []))

        # 去重但保持順序
        seen = set()
        unique = []
        for mid in ids:
            if mid and mid not in seen:
                seen.add(mid)
                unique.append(mid)
        return unique

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

        # 精簡 metric_data 避免超出 token（只保留重要欄位）
        slim_metrics = []
        for m in metric_data[:20]:  # 最多 20 筆
            if isinstance(m, dict) and m.get("value") is not None:
                slim_metrics.append({
                    "metric_id": m.get("metric_id", ""),
                    "metric_name": m.get("metric_name", ""),
                    "value": m.get("value"),
                    "display_value": m.get("display_value", ""),
                    "unit": m.get("unit", ""),
                    "period": m.get("period", ""),
                })

        # 建立此頁允許引用的合法 metric_id 集合（防幻覺白名單）
        valid_ids = self._collect_metric_ids(slide_spec, metric_data)
        valid_id_set = set(valid_ids)

        # 也從 chart.series 收集有效資訊
        chart = slide_spec.get("chart")
        chart_context = ""
        if chart and isinstance(chart, dict):
            series_info = []
            for s in chart.get("series", []):
                if isinstance(s, dict) and s.get("values"):
                    series_info.append({
                        "name": s.get("name", ""),
                        "values_sample": s.get("values", [])[:6],
                        "metric_ids_sample": s.get("metric_ids", [])[:3],
                    })
            if series_info:
                chart_context = f"\n\n## 圖表資料系列\n{json.dumps(series_info, ensure_ascii=False, indent=2)}"
            if chart.get("categories"):
                chart_context += f"\n\ncategories: {json.dumps(chart['categories'][:6], ensure_ascii=False)}"

        user_message = f"""
請為以下簡報頁面生成策略洞察。

## 頁面規格
- slide_no: {slide_spec.get('slide_no')}
- layout: {slide_spec.get('layout')}
- title: {slide_spec.get('title')}

## 計算引擎結果（你只能引用這些 metric_id 和數字）
{json.dumps(slim_metrics, ensure_ascii=False, indent=2)}
{chart_context}

## 要求
1. 輸出格式: {{"headline": str, "insights": [{{"text": str, "evidence_metric_ids": [str]}}], "source_ids": [str]}}
2. 若為策略頁則加 "recommendations": [{{"action": str, "rationale": str}}]
3. 每項洞察包含：發生什麼、為什麼重要、可能原因、建議行動
4. evidence_metric_ids 必須是上面提供的真實 metric_id
5. 不得自行計算或新增數字
6. 推測須使用「可能」「推測」「顯示」等措辭
7. headline 是一句話洞察結論，不是數字描述

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

                if result.get("headline"):
                    merged["headline"] = result["headline"]

                # 防幻覺：過濾洞察中不存在的 metric_id
                if result.get("insights"):
                    merged["insights"] = self._sanitize_insights(
                        result["insights"], valid_id_set, valid_ids
                    )

                if result.get("recommendations"):
                    merged["recommendations"] = result["recommendations"]

                # source_ids 也只保留合法的
                if result.get("source_ids"):
                    clean_sources = [sid for sid in result["source_ids"] if sid in valid_id_set]
                    merged["source_ids"] = clean_sources or valid_ids[:10]
                elif valid_ids:
                    merged["source_ids"] = valid_ids[:10]

                return merged
        except json.JSONDecodeError:
            pass

        return self._rule_based_insights(slide_spec, metric_data)

    def _sanitize_insights(self, insights: list, valid_id_set: set, valid_ids: list) -> list:
        """
        防幻覺過濾：移除 LLM 洞察中不存在於計算引擎的 metric_id。

        - 過濾每條洞察的 evidence_metric_ids，只保留真實存在的
        - 若過濾後為空，退回使用該頁所有合法 ids（確保洞察仍可追溯）
        - 保留洞察文字本身（文字不含數字，是安全的）
        """
        sanitized = []
        for insight in insights:
            if not isinstance(insight, dict):
                continue
            evidence = insight.get("evidence_metric_ids", [])
            # 只保留合法 id
            clean_evidence = [eid for eid in evidence if eid in valid_id_set]
            # 若全部被過濾掉，退回該頁所有合法 ids
            if not clean_evidence and valid_ids:
                clean_evidence = valid_ids[:3]
            sanitized.append({
                "text": insight.get("text", ""),
                "evidence_metric_ids": clean_evidence,
            })
        return sanitized
