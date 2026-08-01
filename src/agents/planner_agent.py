"""
Planner Agent — 簡報結構規劃器

完全由資料驅動，不內建任何特定產業假設。
收到資料摘要後，自動判別業務情境並規劃簡報結構。

頁數規則：
- 使用者明確指定頁數 → 依指定
- 未指定 → 預設 16 頁

輸出遵循 README 5.2 slide_spec 格式。
"""

import json
import os
from typing import Optional

import boto3


class PlannerAgent:
    """
    簡報結構規劃 Agent。

    設計原則：
    - 不內建任何特定產業的標題或結構
    - 所有 Chapter 名稱、頁面標題、headline 由資料特性推導
    - LLM 模式下完全動態生成；規則模式下用通用邏輯推導
    - 頁數由使用者指定，未指定則預設 16 頁
    - 格式遵循 README 5.2
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

    def _load_prompt(self) -> str:
        prompt_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "prompts", "slide_planner.md"
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        return "你是簡報規劃專家，請根據資料內容規劃 16 頁簡報結構。"

    # ─── 公開介面 ───────────────────────────────────────────

    def plan_structure(self, data_summary: dict, use_llm: bool = True, total_pages: int = None) -> list[dict]:
        """
        規劃簡報結構。

        頁數由使用者決定：
        - total_pages 有值 → 依使用者指定
        - total_pages = None → 預設 16 頁

        Args:
            data_summary: {institutions, metrics, periods, record_count}
            use_llm: 是否使用 LLM
            total_pages: 使用者指定的頁數（None 表示未指定，預設 16）

        Returns:
            slide_spec 陣列 (README 5.2 格式)
        """
        pages = total_pages if total_pages is not None else 16

        if not use_llm:
            return self._rule_based_plan(data_summary, pages)
        try:
            return self._llm_plan(data_summary, pages)
        except Exception as e:
            print(f"[PlannerAgent] LLM 規劃失敗，使用規則引擎: {e}")
            return self._rule_based_plan(data_summary, pages)

    def classify_data(self, data_summary: dict) -> dict:
        """
        資料分類：判定數據維度、可用分析類型、推測業務情境。
        不做任何硬編碼假設，純粹根據指標名稱特徵判斷。
        """
        metrics = data_summary.get("metrics", [])
        periods = data_summary.get("periods", [])
        institutions = data_summary.get("institutions", [])

        # 數據維度
        has_time_series = len(periods) >= 3
        has_cross_section = len(institutions) >= 3
        metric_count = len(metrics)

        # 分析可用的數據類型
        data_types = []
        if has_time_series:
            data_types.append("time_series")
        if has_cross_section:
            data_types.append("cross_section")

        # 指標分類（通用關鍵字匹配，不綁定特定產業）
        ratio_keywords = ["率", "比", "佔", "占", "%", "rate", "ratio", "share", "percentage"]
        risk_keywords = ["逾期", "呆帳", "損失", "風險", "違約", "異常", "risk", "loss", "overdue", "default", "bad"]
        volume_keywords = ["數", "量", "額", "人次", "金額", "筆數", "件數", "count", "amount", "volume", "total", "number"]
        efficiency_keywords = ["平均", "均", "每", "率", "效", "avg", "per", "efficiency"]

        ratio_metrics = [m for m in metrics if any(k in m.lower() for k in ratio_keywords)]
        risk_metrics = [m for m in metrics if any(k in m.lower() for k in risk_keywords)]
        volume_metrics = [m for m in metrics if any(k in m.lower() for k in volume_keywords)]
        efficiency_metrics = [m for m in metrics if any(k in m.lower() for k in efficiency_keywords) and m not in ratio_metrics]

        if ratio_metrics:
            data_types.append("composition")
        if risk_metrics:
            data_types.append("risk")
        if len(volume_metrics) >= 2 and has_cross_section:
            data_types.append("dual_variable")

        # 推測業務情境（僅供標題參考，不影響邏輯）
        domain = self._infer_domain(metrics, institutions)

        # 自動分群為分析主題
        theme_groups = self._auto_group_themes(metrics, volume_metrics, ratio_metrics, risk_metrics, efficiency_metrics)

        return {
            "domain": domain,
            "data_types": list(set(data_types)),
            "theme_groups": theme_groups,
            "has_time_series": has_time_series,
            "has_cross_section": has_cross_section,
            "metric_count": metric_count,
        }

    # ─── 業務情境推斷（僅影響標題措辭）──────────────────────

    def _infer_domain(self, metrics: list, institutions: list) -> str:
        """從指標與主體名稱推測業務情境。僅用於標題生成，不影響結構邏輯。"""
        all_text = " ".join(metrics + institutions)

        # 純粹根據出現的關鍵字推測，找不到就回傳通用描述
        hints = {
            "信用卡": ["信用卡", "卡數", "簽帳", "有效卡", "循環信用", "分期"],
            "旅遊觀光": ["旅客", "航班", "住房率", "觀光", "旅遊", "景點", "飯店"],
            "財富管理": ["AUM", "手續費", "基金", "理財"],
            "放款業務": ["放款", "授信", "利差", "核貸"],
            "零售通路": ["門店", "坪效", "客單價", "來客數"],
            "保險業務": ["保費", "理賠", "保單", "件數"],
            "支付業務": ["交易筆數", "支付", "轉帳", "電子支付"],
        }

        for domain, keywords in hints.items():
            if any(kw in all_text for kw in keywords):
                return domain

        return "業務數據"

    # ─── 指標自動分群 ────────────────────────────────────────

    def _auto_group_themes(self, all_metrics, volume, ratio, risk, efficiency) -> list[dict]:
        """將指標自動分為 4 個分析主題（不使用任何產業特定名稱）。"""
        themes = []

        if volume:
            themes.append({"name": "規模與量能", "metrics": volume, "focus": "整體量能趨勢"})
        if ratio or efficiency:
            combined = list(set(ratio + efficiency))
            themes.append({"name": "效率與結構", "metrics": combined, "focus": "營運品質與結構"})
        if risk:
            themes.append({"name": "風險與預警", "metrics": risk, "focus": "風險監控與早期警示"})

        # 未歸類的放入補充主題
        assigned = set(m for t in themes for m in t["metrics"])
        remaining = [m for m in all_metrics if m not in assigned]
        if remaining:
            themes.append({"name": "延伸分析", "metrics": remaining, "focus": "補充維度分析"})

        # 確保至少有 2 個主題（讓結構有內容）
        if len(themes) < 2:
            # 把第一個主題拆成兩個
            if themes and len(themes[0]["metrics"]) >= 2:
                ms = themes[0]["metrics"]
                mid = len(ms) // 2
                themes = [
                    {"name": "趨勢分析", "metrics": ms[:mid], "focus": "動態變化"},
                    {"name": "比較分析", "metrics": ms[mid:], "focus": "橫向對標"},
                ]

        return themes[:4]  # 最多 4 個 Chapter

    # ─── 規則引擎規劃 ────────────────────────────────────────

    def _rule_based_plan(self, data_summary: dict, total_pages: int = 16) -> list[dict]:
        """完全由資料驅動的結構規劃。頁數依使用者指定。"""
        classification = self.classify_data(data_summary)
        domain = classification["domain"]
        themes = classification["theme_groups"]
        data_types = classification["data_types"]
        metrics = data_summary.get("metrics", [])
        institutions = data_summary.get("institutions", [])
        periods = data_summary.get("periods", [])

        slides = []

        # 固定頁面：封面 + 目錄 + Summary + 策略 + 感謝 = 5
        FIXED_PAGES = 5
        available_for_chapters = total_pages - FIXED_PAGES

        # P1: 封面
        slides.append(self._make_slide(1, "cover", f"{domain}分析與經營洞察簡報"))

        # P2: 目錄
        slides.append(self._make_slide(2, "toc", "目錄"))

        # P3: Executive Summary
        s3 = self._make_slide(3, "executive_summary", "Executive Summary")
        s3["headline"] = "關鍵發現摘要"
        s3["kpis"] = [{"label": m, "metric_id": f"summary_{self._safe_id(m)}"} for m in metrics[:5]]
        slides.append(s3)

        # 中間頁面：分配給 Chapters
        slide_no = 4
        last_analysis_page = total_pages - 2  # 倒數第二頁前都給 Chapter

        # 計算每個 Chapter 可分配的頁數
        num_chapters = min(len(themes), max(2, available_for_chapters // 3))
        themes_to_use = themes[:num_chapters]

        # 平均分配剩餘頁面給各 Chapter
        pages_per_chapter = available_for_chapters // num_chapters if num_chapters > 0 else 0

        for ch_idx, theme in enumerate(themes_to_use, 1):
            if slide_no > last_analysis_page:
                break

            # Chapter 分隔頁
            slides.append(self._make_slide(slide_no, "chapter_divider",
                                          f"Chapter {ch_idx:02d} {theme['name']}"))
            slide_no += 1

            # 該 Chapter 的分析頁（分隔頁佔 1，剩餘給分析）
            analysis_count = pages_per_chapter - 1
            theme_metrics = theme["metrics"]
            pages = self._generate_analysis_pages(
                theme_metrics, data_types, institutions, periods, slide_no
            )

            for page in pages[:analysis_count]:
                if slide_no > last_analysis_page:
                    break
                page["slide_no"] = slide_no
                slides.append(page)
                slide_no += 1

        # 補齊到 last_analysis_page（如果 Chapter 不夠）
        while slide_no <= last_analysis_page:
            remaining_metrics = [m for m in metrics if not any(
                m in s.get("title", "") for s in slides
            )]
            fill_metric = remaining_metrics[0] if remaining_metrics else metrics[0] if metrics else "補充指標"
            layout = "comparison_chart" if "cross_section" in data_types else "trend_chart"
            s = self._make_slide(slide_no, layout, f"{fill_metric}分析")
            s["headline"] = f"{fill_metric}深度分析"
            slides.append(s)
            slide_no += 1

        # 倒數第二頁：策略建議
        s_strategy = self._make_slide(total_pages - 1, "strategy", "策略建議與行動方案")
        s_strategy["headline"] = "基於數據分析的策略方向"
        slides.append(s_strategy)

        # 最後一頁：感謝頁
        slides.append(self._make_slide(total_pages, "thank_you", "感謝頁"))

        return slides

    def _generate_analysis_pages(self, metrics: list, data_types: list,
                                  institutions: list, periods: list, start_no: int) -> list[dict]:
        """為一個主題生成 1-2 頁分析頁。Layout 由數據類型驅動。"""
        pages = []

        if not metrics:
            return pages

        # 第一頁：趨勢或比較
        primary = metrics[0]
        if "time_series" in data_types:
            p = self._make_slide(0, "trend_chart", f"{primary}趨勢分析")
            p["headline"] = f"{primary}動態變化與走勢"
            p["chart"] = {
                "type": "line",
                "series_metric_ids": [f"{self._safe_id(primary)}_{per}" for per in periods[-6:]],
            }
        elif "cross_section" in data_types:
            p = self._make_slide(0, "ranking_chart", f"{primary}排名比較")
            p["headline"] = f"各主體{primary}差距與定位"
            p["chart"] = {
                "type": "horizontal_bar",
                "series_metric_ids": [f"{self._safe_id(inst)}_{self._safe_id(primary)}" for inst in institutions[:10]],
            }
        else:
            p = self._make_slide(0, "comparison_chart", f"{primary}分析")
            p["headline"] = f"{primary}現況與變化"
            p["chart"] = {"type": "bar", "series_metric_ids": [f"{self._safe_id(primary)}_latest"]}
        pages.append(p)

        # 第二頁：如果有第二個指標
        if len(metrics) >= 2:
            secondary = metrics[1]
            if "dual_variable" in data_types and "cross_section" in data_types:
                p2 = self._make_slide(0, "scatter_chart", f"{primary} vs {secondary}")
                p2["headline"] = f"雙維度交叉分析"
                p2["chart"] = {
                    "type": "scatter",
                    "series_metric_ids": [f"{self._safe_id(inst)}_scatter" for inst in institutions[:10]],
                }
            elif "cross_section" in data_types:
                p2 = self._make_slide(0, "comparison_chart", f"{secondary}比較分析")
                p2["headline"] = f"各主體{secondary}對標"
                p2["chart"] = {
                    "type": "bar",
                    "series_metric_ids": [f"{self._safe_id(inst)}_{self._safe_id(secondary)}" for inst in institutions[:10]],
                }
            else:
                p2 = self._make_slide(0, "trend_chart", f"{secondary}趨勢")
                p2["headline"] = f"{secondary}走勢觀察"
                p2["chart"] = {
                    "type": "line",
                    "series_metric_ids": [f"{self._safe_id(secondary)}_{per}" for per in periods[-6:]],
                }
            pages.append(p2)

        return pages[:2]

    # ─── 工具 ─────────────────────────────────────────────────

    def _make_slide(self, slide_no: int, layout: str, title: str) -> dict:
        """建立一頁空白 slide_spec（README 5.2 所有欄位）。"""
        return {
            "slide_no": slide_no,
            "layout": layout,
            "title": title,
            "headline": "",
            "chart": None,
            "kpis": [],
            "insights": [],
            "recommendations": [],
            "source_ids": [],
        }

    def _safe_id(self, text: str) -> str:
        """將中文名稱轉為安全的 metric_id 片段。"""
        return text.replace(" ", "_").replace("/", "_").replace("（", "").replace("）", "")

    # ─── LLM 增強規劃 ────────────────────────────────────────

    def _llm_plan(self, data_summary: dict, total_pages: int = 16) -> list[dict]:
        """使用 LLM 動態規劃——完全從資料推導結構，無預設假設。"""
        system_prompt = self._load_prompt()
        classification = self.classify_data(data_summary)

        user_message = f"""
根據以下資料摘要，規劃 {total_pages} 頁策略分析簡報結構。

注意：不要假設資料屬於哪個特定產業。所有標題、Chapter 名稱必須從資料內容推導。

## 資料摘要
- 主體列表: {json.dumps(data_summary.get('institutions', []), ensure_ascii=False)}
- 指標列表: {json.dumps(data_summary.get('metrics', []), ensure_ascii=False)}
- 時間期間: {json.dumps(data_summary.get('periods', []), ensure_ascii=False)}
- 資料筆數: {data_summary.get('record_count', 0)}

## 自動分類結果（參考）
- 推測情境: {classification['domain']}
- 數據類型: {json.dumps(classification['data_types'], ensure_ascii=False)}
- 主題分群: {json.dumps([t['name'] for t in classification['theme_groups']], ensure_ascii=False)}

## 要求
1. 恰好 {total_pages} 頁
2. 每頁欄位: slide_no, layout, title, headline, chart, kpis, insights, recommendations, source_ids
3. chart: {{"type": str, "series_metric_ids": [str]}}
4. insights: [{{"text": str, "evidence_metric_ids": [str]}}]
5. headline 必須是洞察結論，不是數字描述
6. 標題和內容完全由資料驅動，不要寫死特定產業用語

請輸出 JSON 陣列。
"""

        response = self.bedrock_client.converse(
            modelId=self.model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.3},
        )

        response_text = response["output"]["message"]["content"][0]["text"]

        try:
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start != -1 and end > start:
                slides = json.loads(response_text[start:end])
                return self._ensure_page_count(slides, total_pages)
        except json.JSONDecodeError:
            pass

        return self._rule_based_plan(data_summary, total_pages)

    def _ensure_page_count(self, slides: list[dict], total_pages: int) -> list[dict]:
        """確保 LLM 產出恰好指定頁數且包含所有必要欄位。"""
        normalized = []
        for i, slide in enumerate(slides[:total_pages], 1):
            norm = self._make_slide(i, slide.get("layout", "comparison_chart"), slide.get("title", ""))
            for key in ("headline", "chart", "kpis", "insights", "recommendations", "source_ids"):
                if slide.get(key):
                    norm[key] = slide[key]
            normalized.append(norm)

        while len(normalized) < total_pages:
            n = len(normalized) + 1
            normalized.append(self._make_slide(n, "comparison_chart", "補充分析"))

        return normalized
