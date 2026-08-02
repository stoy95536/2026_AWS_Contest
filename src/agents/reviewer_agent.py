"""
Reviewer Agent — 品質審核

完全不含任何產業特定邏輯。審核規則適用於任何業務資料。
輸出格式嚴格遵循 README 5.3：
  {"status": "passed|failed", "errors": [{slide_no, type, message, expected}]}
"""

import json
import os
import re
from typing import Optional

import boto3


class ReviewerAgent:
    """
    品質審核 Agent。

    審核維度（通用，不綁定產業）：
    1. metric_id 引用是否存在於計算引擎結果
    2. 百分比大小關係邏輯
    3. 洞察品質（非純數字描述）
    4. YoY/MoM 有效性
    5. 16 頁結構完整性
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

    # ─── 公開介面 ───────────────────────────────────────────

    def review(
        self,
        slide_specs: list[dict],
        verified_metrics: dict,
        use_llm: bool = False,
        expected_pages: int = None,
    ) -> dict:
        """
        審核簡報規格。

        Args:
            slide_specs: 完整簡報規格
            verified_metrics: {metric_id: value} 已驗證的計算結果
            use_llm: 是否使用 LLM 輔助
            expected_pages: 預期頁數（None 則不檢查頁數）

        Returns:
            README 5.3 格式: {"status": "passed|failed", "errors": [...]}
        """
        errors = []

        for spec in slide_specs:
            errors.extend(self._review_slide(spec, verified_metrics))

        errors.extend(self._review_global_structure(slide_specs, expected_pages))

        if use_llm:
            try:
                errors.extend(self._llm_review(slide_specs, verified_metrics))
            except Exception as e:
                print(f"[ReviewerAgent] LLM 審核失敗: {e}")

        # 判定 status
        blocking = {"data_mismatch", "narrative_logic_error", "missing_source"}
        has_blocking = any(e["type"] in blocking for e in errors)

        return {
            "status": "failed" if has_blocking else "passed",
            "errors": errors,
        }

    # ─── 單頁審核 ────────────────────────────────────────────

    def _review_slide(self, spec: dict, verified_metrics: dict) -> list[dict]:
        errors = []
        slide_no = spec.get("slide_no", 0)
        layout = spec.get("layout", "")

        # 非分析頁跳過
        if layout in ("cover", "toc", "chapter_divider", "thank_you"):
            return errors

        # 1. metric_id 引用檢查
        if verified_metrics:
            errors.extend(self._check_references(spec, verified_metrics, slide_no))

        # 2. 百分比邏輯檢查
        errors.extend(self._check_percentage_logic(spec, slide_no))

        # 3. 洞察品質檢查
        errors.extend(self._check_insight_quality(spec, slide_no))

        # 4. YoY 有效性
        if verified_metrics:
            errors.extend(self._check_yoy(spec, verified_metrics, slide_no))

        return errors

    def _check_references(self, spec: dict, verified: dict, slide_no: int) -> list[dict]:
        """檢查所有 metric_id 引用是否存在於計算引擎。"""
        errors = []

        # KPI metric_ids
        for kpi in spec.get("kpis", []):
            mid = kpi.get("metric_id", "")
            if mid and mid not in verified:
                errors.append({
                    "slide_no": slide_no,
                    "type": "missing_source",
                    "message": f"KPI '{kpi.get('label', '')}' 引用 metric_id '{mid}' 不存在於計算引擎",
                })

        # chart series_metric_ids
        chart = spec.get("chart")
        if chart and isinstance(chart, dict):
            for mid in chart.get("series_metric_ids", []):
                if mid and mid not in verified:
                    errors.append({
                        "slide_no": slide_no,
                        "type": "missing_source",
                        "message": f"圖表引用 metric_id '{mid}' 不存在於計算引擎",
                    })

        # insights evidence_metric_ids
        for insight in spec.get("insights", []):
            for mid in insight.get("evidence_metric_ids", []):
                if mid and mid not in verified:
                    errors.append({
                        "slide_no": slide_no,
                        "type": "missing_source",
                        "message": f"洞察 evidence '{mid}' 不存在於計算引擎",
                    })

        return errors

    def _check_percentage_logic(self, spec: dict, slide_no: int) -> list[dict]:
        """檢查文案中百分比大小關係。"""
        errors = []

        texts = [spec.get("headline", "")]
        texts.extend(ins.get("text", "") for ins in spec.get("insights", []))

        for text in texts:
            if not text:
                continue
            # X% 高於 Y% — 但 X < Y
            for match in re.finditer(r'(\d+\.?\d*)%\s*高於\s*(\d+\.?\d*)%', text):
                a, b = float(match.group(1)), float(match.group(2))
                if a < b:
                    errors.append({
                        "slide_no": slide_no,
                        "type": "narrative_logic_error",
                        "message": f"文案稱 {a}% 高於 {b}%，大小關係錯誤",
                        "expected": f"{a}% 低於 {b}%",
                    })
            # X% 低於 Y% — 但 X > Y
            for match in re.finditer(r'(\d+\.?\d*)%\s*低於\s*(\d+\.?\d*)%', text):
                a, b = float(match.group(1)), float(match.group(2))
                if a > b:
                    errors.append({
                        "slide_no": slide_no,
                        "type": "narrative_logic_error",
                        "message": f"文案稱 {a}% 低於 {b}%，大小關係錯誤",
                        "expected": f"{a}% 高於 {b}%",
                    })

        return errors

    def _check_insight_quality(self, spec: dict, slide_no: int) -> list[dict]:
        """檢查洞察品質。"""
        errors = []
        layout = spec.get("layout", "")

        analysis_layouts = {"trend_chart", "ranking_chart", "scatter_chart",
                          "comparison_chart", "stacked_chart", "risk_chart",
                          "executive_summary", "strategy"}

        if layout in analysis_layouts:
            insights = spec.get("insights", [])
            if not insights and layout != "strategy":
                errors.append({
                    "slide_no": slide_no,
                    "type": "weak_insight",
                    "message": "分析頁缺少洞察，每頁應有明確核心訊息與管理意涵",
                })

            if not spec.get("headline"):
                errors.append({
                    "slide_no": slide_no,
                    "type": "weak_insight",
                    "message": "分析頁缺少 headline（核心訊息）",
                })

            for insight in insights:
                if not insight.get("evidence_metric_ids"):
                    errors.append({
                        "slide_no": slide_no,
                        "type": "missing_source",
                        "message": f"洞察缺少 evidence_metric_ids: {insight.get('text', '')[:30]}...",
                    })

        return errors

    def _check_yoy(self, spec: dict, verified: dict, slide_no: int) -> list[dict]:
        """檢查 YoY 引用是否有前期資料。"""
        errors = []
        all_ids = set()
        for kpi in spec.get("kpis", []):
            if kpi.get("metric_id"):
                all_ids.add(kpi["metric_id"])
        for ins in spec.get("insights", []):
            all_ids.update(ins.get("evidence_metric_ids", []))
        all_ids.update(spec.get("source_ids", []))

        for mid in all_ids:
            if ("yoy" in mid.lower() or "年增" in mid) and mid in verified and verified[mid] is None:
                errors.append({
                    "slide_no": slide_no,
                    "type": "data_mismatch",
                    "message": f"引用 YoY 指標 '{mid}' 但缺少前期資料",
                    "expected": "移除 YoY 引用或標示無法計算",
                })

        return errors

    # ─── 全局結構審核 ────────────────────────────────────────

    def _review_global_structure(self, specs: list[dict], expected_pages: int = None) -> list[dict]:
        errors = []

        # 如果有指定頁數，檢查是否符合
        if expected_pages is not None and len(specs) != expected_pages:
            errors.append({
                "slide_no": 0,
                "type": "logic_error",
                "message": f"簡報應為 {expected_pages} 頁，實際 {len(specs)} 頁",
                "expected": f"{expected_pages} 頁",
            })

        if not any(s.get("layout") == "executive_summary" for s in specs):
            errors.append({
                "slide_no": 0,
                "type": "logic_error",
                "message": "缺少 Executive Summary 頁",
            })

        if not any(s.get("layout") == "strategy" for s in specs):
            errors.append({
                "slide_no": 0,
                "type": "logic_error",
                "message": "缺少策略建議頁",
            })

        return errors

    # ─── LLM 增強審核 ────────────────────────────────────────

    def _llm_review(self, slide_specs: list[dict], verified_metrics: dict) -> list[dict]:
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "prompts", "insight_reviewer.md"
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        else:
            system_prompt = "你是品質審核專家。"

        sample_specs = slide_specs[:5]
        sample_metrics = dict(list(verified_metrics.items())[:20]) if verified_metrics else {}

        user_message = f"""
審核以下簡報規格。輸出格式：
{{"errors": [{{"slide_no": int, "type": str, "message": str, "expected": str}}]}}

## 簡報（前5頁）
{json.dumps(sample_specs, ensure_ascii=False, indent=2)}

## 計算引擎結果（部分）
{json.dumps(sample_metrics, ensure_ascii=False, indent=2)}
"""

        response = self.bedrock_client.converse(
            modelId=self.model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 2048, "temperature": 0.2},
        )

        text = response["output"]["message"]["content"][0]["text"]
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end]).get("errors", [])
        except json.JSONDecodeError:
            pass
        return []
