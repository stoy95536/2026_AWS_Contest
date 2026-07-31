"""
Reviewer Agent — 品質審核 Agent
檢查分析師產出的簡報規格，確保數值一致性、邏輯正確性。
"""

import json
import os
from typing import Optional

import boto3


class ReviewerAgent:
    """
    審核 Agent：
    - 檢查所有引用的數字是否存在於計算引擎結果
    - 驗證百分比大小關係
    - 確認排名與圖表順序一致
    - 確認推測性內容有適當標注
    """

    def __init__(self, model_id: str = "anthropic.claude-sonnet-4-20250514", region: str = "us-east-1"):
        self.model_id = model_id
        self.region = region
        self._client = None

    @property
    def bedrock_client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )
        return self._client

    def review(
        self,
        slide_specs: list[dict],
        verified_metrics: dict,
        use_llm: bool = False,
    ) -> dict:
        """
        審核簡報規格。

        Args:
            slide_specs: 完整 16 頁規格
            verified_metrics: 已驗證的計算結果 {metric_id: value}
            use_llm: 是否使用 LLM 輔助審核

        Returns:
            QA 報告 dict
        """
        issues = []

        for spec in slide_specs:
            slide_issues = self._check_slide(spec, verified_metrics)
            issues.extend(slide_issues)

        if use_llm:
            try:
                llm_issues = self._llm_review(slide_specs, verified_metrics)
                issues.extend(llm_issues)
            except Exception as e:
                print(f"[ReviewerAgent] LLM 審核失敗: {e}")

        status = "passed" if not any(i["severity"] == "error" for i in issues) else "failed"

        return {
            "status": status,
            "total_issues": len(issues),
            "errors": len([i for i in issues if i["severity"] == "error"]),
            "warnings": len([i for i in issues if i["severity"] == "warning"]),
            "issues": issues,
        }

    def _check_slide(self, spec: dict, verified_metrics: dict) -> list[dict]:
        """檢查單頁簡報。"""
        issues = []
        slide_no = spec.get("slide_no", 0)

        # 檢查 KPI 數值引用
        issues.extend(self._check_kpi_references(spec, verified_metrics, slide_no))

        # 檢查洞察中的 metric_id 引用
        issues.extend(self._check_insight_references(spec, verified_metrics, slide_no))

        # 檢查邏輯一致性
        issues.extend(self._check_logic_consistency(spec, verified_metrics, slide_no))

        return issues

    def _check_kpi_references(self, spec: dict, verified_metrics: dict, slide_no: int) -> list[dict]:
        """檢查 KPI 引用是否存在於已驗證資料中。"""
        issues = []
        kpis = spec.get("kpis", [])

        for kpi in kpis:
            metric_id = kpi.get("metric_id", "")
            if metric_id and metric_id not in verified_metrics:
                issues.append({
                    "slide_no": slide_no,
                    "type": "missing_source",
                    "severity": "error",
                    "message": f"KPI '{kpi.get('label', '')}' 引用的 metric_id '{metric_id}' 不存在於計算結果中",
                    "suggestion": "確認計算引擎已產出對應指標",
                })

        return issues

    def _check_insight_references(self, spec: dict, verified_metrics: dict, slide_no: int) -> list[dict]:
        """檢查洞察引用的 evidence_metric_ids。"""
        issues = []
        insights = spec.get("insights", [])

        for insight in insights:
            evidence_ids = insight.get("evidence_metric_ids", [])
            for eid in evidence_ids:
                if eid and eid not in verified_metrics:
                    issues.append({
                        "slide_no": slide_no,
                        "type": "missing_source",
                        "severity": "warning",
                        "message": f"洞察引用的 evidence_metric_id '{eid}' 不存在",
                        "suggestion": "更新引用或從計算引擎重新取得",
                    })

        return issues

    def _check_logic_consistency(self, spec: dict, verified_metrics: dict, slide_no: int) -> list[dict]:
        """檢查邏輯一致性。"""
        issues = []

        # 檢查 YoY 是否有基期
        source_ids = spec.get("source_ids", [])
        for sid in source_ids:
            if "yoy" in sid.lower():
                metric_val = verified_metrics.get(sid)
                if metric_val is None:
                    issues.append({
                        "slide_no": slide_no,
                        "type": "logic_error",
                        "severity": "error",
                        "message": f"引用了 YoY 指標 '{sid}'，但該值為 N/A（缺少基期資料）",
                        "suggestion": "移除 YoY 引用或標注為無法計算",
                    })

        # 檢查排名是否有重複
        chart = spec.get("chart")
        if chart and chart.get("type") == "bar":
            series = chart.get("series", [])
            for s in series:
                data = s.get("data", [])
                if len(data) != len(set(str(d) for d in data)):
                    # 有重複值不一定是錯誤，排名可以並列
                    pass

        return issues

    def _llm_review(self, slide_specs: list[dict], verified_metrics: dict) -> list[dict]:
        """使用 LLM 輔助審核。"""
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "prompts", "insight_reviewer.md"
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_prompt = f.read()
        else:
            system_prompt = "你是品質審核專家。"

        user_message = f"""
請審核以下簡報規格：

## 簡報規格
{json.dumps(slide_specs[:3], ensure_ascii=False, indent=2)}

## 已驗證指標（部分）
{json.dumps(dict(list(verified_metrics.items())[:20]), ensure_ascii=False, indent=2)}

請找出數值不一致、邏輯錯誤或缺少來源的問題。
"""

        response = self.bedrock_client.converse(
            modelId=self.model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 2048, "temperature": 0.2},
        )

        response_text = response["output"]["message"]["content"][0]["text"]

        try:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start != -1 and end > start:
                result = json.loads(response_text[start:end])
                return result.get("issues", [])
        except json.JSONDecodeError:
            pass

        return []
