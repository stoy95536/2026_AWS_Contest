"""
PowerPoint 簡報生成器
根據 slide_spec 和台新新光金控模板（附件一）生成 16 頁簡報。
所有圖表、表格、文字均為可編輯原生物件，不以圖片嵌入。

模板 Layout 對應：
- 封面/章節分隔: 2_標題投影片 (title only, 居中大字)
- 內容頁(含圖表): 1_標題及內容 (title + body area + page number)
- 章節標題:       2_章節標題 (title 置於下方)
- 結束頁:         3_標題投影片 (title only)
"""

import json
import os
from typing import Optional

from pptx import Presentation
from pptx.util import Inches, Pt, Cm, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.slide import Slide

from .template_parser import (
    TemplateParser, TemplateStyle,
    LAYOUT_COVER, LAYOUT_CONTENT, LAYOUT_CHAPTER, LAYOUT_THANKYOU,
)
from .chart_factory import ChartFactory


class PPTGenerator:
    """根據 slide_spec 生成完整 PowerPoint 簡報。"""

    def __init__(self, template_path: Optional[str] = None):
        self.template_parser = TemplateParser(template_path)
        self.chart_factory = ChartFactory()
        self.style = self.template_parser.get_style()
        self.template_path = template_path

    def generate(self, slide_specs: list[dict], output_path: str) -> str:
        """
        生成完整 16 頁簡報。

        Args:
            slide_specs: 16 頁 slide_spec 陣列
            output_path: 輸出路徑

        Returns:
            輸出檔案路徑
        """
        prs = self.template_parser.create_presentation()

        for spec in slide_specs:
            layout_type = self._resolve_layout_type(spec)
            layout_name = self.template_parser.get_layout_for_page_type(layout_type)
            slide = self._add_slide(prs, layout_name)

            if layout_type == "cover":
                self._build_cover(slide, spec)
            elif layout_type == "chapter":
                self._build_chapter(slide, spec)
            elif layout_type == "thank_you":
                self._build_thank_you(slide, spec)
            elif layout_type == "content":
                self._build_content(slide, spec)

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        prs.save(output_path)
        return output_path

    def _resolve_layout_type(self, spec: dict) -> str:
        """根據 slide_spec 的 layout 欄位判斷模板 layout 類型。"""
        layout = spec.get("layout", "")
        if layout == "cover":
            return "cover"
        elif layout == "toc":
            return "content"
        elif layout == "chapter_divider":
            return "chapter"
        elif layout == "thank_you":
            return "thank_you"
        elif layout == "executive_summary":
            return "content"
        elif layout == "strategy":
            return "content"
        else:
            # trend_chart, ranking_chart, scatter_chart, comparison_chart, etc.
            return "content"

    def _add_slide(self, prs: Presentation, layout_name: str) -> Slide:
        """新增投影片，使用指定的 layout。"""
        # 尋找對應的 layout
        target_layout = None
        for layout in prs.slide_layouts:
            if layout.name == layout_name:
                target_layout = layout
                break

        if target_layout is None:
            # 回退到第一個 layout
            target_layout = prs.slide_layouts[0]

        return prs.slides.add_slide(target_layout)

    def _remove_placeholder(self, slide: Slide, idx: int):
        """從投影片中移除指定的 placeholder（避免顯示空白框）。"""
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == idx:
                sp = ph._element
                sp.getparent().remove(sp)
                return

    # ========== 封面頁 ==========
    def _build_cover(self, slide: Slide, spec: dict):
        """封面頁 — 使用 2_標題投影片 layout (title placeholder 居中)。"""
        # 移除空的 title placeholder，改用 textbox
        self._remove_placeholder(slide, 0)

        # 主標題
        txBox = slide.shapes.add_textbox(Cm(3.1), Cm(4.0), Cm(27.7), Cm(2.5))
        tf = txBox.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = spec.get("title", "信用卡市場分析與經營洞察")
        p.font.size = Pt(32)
        p.font.bold = True
        p.font.color.rgb = RGBColor(0x00, 0x33, 0x66)
        p.alignment = PP_ALIGN.CENTER

        # 副標題
        txBox2 = slide.shapes.add_textbox(Cm(3.1), Cm(7.0), Cm(27.7), Cm(1.5))
        tf2 = txBox2.text_frame
        p2 = tf2.paragraphs[0]
        p2.text = "114 年 1-12 月信用卡業務數據深度解析"
        p2.font.size = Pt(18)
        p2.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        p2.alignment = PP_ALIGN.CENTER

        # 機構名稱
        txBox3 = slide.shapes.add_textbox(Cm(3.1), Cm(9.5), Cm(27.7), Cm(1.5))
        tf3 = txBox3.text_frame
        p3 = tf3.paragraphs[0]
        p3.text = "台新國際商業銀行"
        p3.font.size = Pt(16)
        p3.font.color.rgb = RGBColor(0x00, 0x66, 0xCC)
        p3.alignment = PP_ALIGN.CENTER

    # ========== 章節分隔頁 ==========
    def _build_chapter(self, slide: Slide, spec: dict):
        """章節分隔頁 — 使用 2_章節標題 layout (title 在下方)。"""
        title = spec.get("title", "")
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == 0:
                tf = ph.text_frame
                tf.paragraphs[0].text = title
                tf.paragraphs[0].font.size = Pt(28)
                tf.paragraphs[0].font.bold = True
                tf.paragraphs[0].font.color.rgb = RGBColor(0x00, 0x33, 0x66)

        # 加入頁碼
        slide_no = spec.get("slide_no", 0)
        txBox = slide.shapes.add_textbox(Cm(31.7), Cm(17.8), Cm(1.8), Cm(0.9))
        tf = txBox.text_frame
        p = tf.paragraphs[0]
        p.text = str(slide_no)
        p.font.size = Pt(10)
        p.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
        p.alignment = PP_ALIGN.RIGHT

    # ========== 結束頁 ==========
    def _build_thank_you(self, slide: Slide, spec: dict):
        """結束頁 — 使用 3_標題投影片 layout。"""
        # 移除空的 title placeholder
        self._remove_placeholder(slide, 0)

        txBox = slide.shapes.add_textbox(Cm(3.1), Cm(5.0), Cm(27.7), Cm(2.5))
        tf = txBox.text_frame
        p = tf.paragraphs[0]
        p.text = "感謝聆聽"
        p.font.size = Pt(36)
        p.font.bold = True
        p.font.color.rgb = RGBColor(0x00, 0x33, 0x66)
        p.alignment = PP_ALIGN.CENTER

        txBox2 = slide.shapes.add_textbox(Cm(3.1), Cm(8.5), Cm(27.7), Cm(2.0))
        tf2 = txBox2.text_frame
        p2 = tf2.paragraphs[0]
        p2.text = "台新國際商業銀行 — 信用卡市場分析與經營洞察"
        p2.font.size = Pt(14)
        p2.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        p2.alignment = PP_ALIGN.CENTER

        p3 = tf2.add_paragraph()
        p3.text = "資料來源：各金融機構信用卡重要資訊揭露（114年1-12月）"
        p3.font.size = Pt(11)
        p3.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        p3.alignment = PP_ALIGN.CENTER

    # ========== 內容頁 ==========
    def _build_content(self, slide: Slide, spec: dict):
        """
        內容頁 — 使用 1_標題及內容 layout。
        Placeholders:
          idx=0 TITLE: left=1.0 top=0.7 w=31.3 h=2.1
          idx=1 BODY:  left=1.0 top=3.5 w=31.2 h=13.6
          idx=12 SLIDE_NUMBER: left=31.7 top=17.8
        """
        title = spec.get("title", "")
        headline = spec.get("headline", "")
        slide_no = spec.get("slide_no", 0)

        # 填入 TITLE placeholder
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == 0:
                ph.text = title
                for para in ph.text_frame.paragraphs:
                    para.font.size = Pt(22)
                    para.font.bold = True
                    para.font.color.rgb = RGBColor(0x00, 0x33, 0x66)
            elif ph.placeholder_format.idx == 12:
                ph.text = str(slide_no)

        # 移除 BODY placeholder（我們用自訂 shapes 取代）
        self._remove_placeholder(slide, 1)

        # Headline (核心訊息)
        if headline:
            txBox = slide.shapes.add_textbox(Cm(1.0), Cm(2.9), Cm(31.2), Cm(1.0))
            tf = txBox.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = f"◆ {headline}"
            p.font.size = Pt(12)
            p.font.bold = True
            p.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

        # 根據頁面內容類型決定如何填充
        layout = spec.get("layout", "")

        if layout == "executive_summary":
            self._fill_executive_summary(slide, spec)
        elif layout == "toc":
            self._fill_toc(slide, spec)
        elif layout == "strategy":
            self._fill_strategy(slide, spec)
        elif spec.get("chart"):
            self._fill_chart(slide, spec)
        elif spec.get("table"):
            self._fill_table(slide, spec)
        else:
            self._fill_insights_only(slide, spec)

    def _fill_executive_summary(self, slide: Slide, spec: dict):
        """填充 Executive Summary 頁 — KPI 卡片 + 洞察。"""
        kpis = spec.get("kpis", [])

        # KPI cards (排成一行，最多4個)
        card_width = Cm(7.5)
        start_x = Cm(1.0)
        y = Cm(4.0)

        for i, kpi in enumerate(kpis[:4]):
            x = start_x + Cm(i * 7.8)
            # 標籤
            txBox = slide.shapes.add_textbox(x, y, card_width, Cm(0.8))
            tf = txBox.text_frame
            p = tf.paragraphs[0]
            p.text = kpi.get("label", "")
            p.font.size = Pt(10)
            p.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

            # 數值
            txBox2 = slide.shapes.add_textbox(x, y + Cm(0.9), card_width, Cm(1.3))
            tf2 = txBox2.text_frame
            p2 = tf2.paragraphs[0]
            p2.text = kpi.get("value", "—")
            p2.font.size = Pt(22)
            p2.font.bold = True
            p2.font.color.rgb = RGBColor(0x00, 0x33, 0x66)

            # 變化
            change = kpi.get("change", "")
            if change:
                txBox3 = slide.shapes.add_textbox(x, y + Cm(2.3), card_width, Cm(0.7))
                tf3 = txBox3.text_frame
                p3 = tf3.paragraphs[0]
                p3.text = change
                p3.font.size = Pt(9)
                direction = kpi.get("change_direction", "flat")
                if direction == "up":
                    p3.font.color.rgb = RGBColor(0x33, 0x99, 0x33)
                elif direction == "down":
                    p3.font.color.rgb = RGBColor(0xCC, 0x33, 0x33)
                else:
                    p3.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        # 洞察區域
        insights = spec.get("insights", [])
        if insights:
            insight_y = Cm(8.0)
            # 洞察標題
            txH = slide.shapes.add_textbox(Cm(1.0), insight_y, Cm(31.2), Cm(0.8))
            tfH = txH.text_frame
            pH = tfH.paragraphs[0]
            pH.text = "四大關鍵洞察"
            pH.font.size = Pt(12)
            pH.font.bold = True
            pH.font.color.rgb = RGBColor(0x00, 0x33, 0x66)

            insight_y += Cm(1.0)
            for insight in insights[:4]:
                text = insight.get("text", "") if isinstance(insight, dict) else str(insight)
                txBox = slide.shapes.add_textbox(Cm(1.5), insight_y, Cm(30.0), Cm(1.5))
                tf = txBox.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = f"• {text}"
                p.font.size = Pt(10)
                insight_y += Cm(1.5)

    def _fill_toc(self, slide: Slide, spec: dict):
        """填充目錄頁。"""
        chapters = [
            "01  市場整體概況",
            "02  同業競爭分析",
            "03  客戶活躍度與獲利能力",
            "04  風險與警訊",
            "05  對台新的策略建議",
        ]
        y = Cm(4.5)
        for ch in chapters:
            txBox = slide.shapes.add_textbox(Cm(3.0), y, Cm(25.0), Cm(1.5))
            tf = txBox.text_frame
            p = tf.paragraphs[0]
            p.text = f"CHAPTER {ch}"
            p.font.size = Pt(16)
            p.font.color.rgb = RGBColor(0x00, 0x33, 0x66)
            y += Cm(2.0)

    def _fill_strategy(self, slide: Slide, spec: dict):
        """填充策略建議頁。"""
        recommendations = spec.get("recommendations", [])
        y = Cm(4.0)

        for i, rec in enumerate(recommendations[:4]):
            action = rec.get("action", "")
            rationale = rec.get("rationale", "")
            priority = rec.get("priority", "medium")

            # 編號
            txNum = slide.shapes.add_textbox(Cm(1.5), y, Cm(2.0), Cm(1.5))
            tfNum = txNum.text_frame
            pNum = tfNum.paragraphs[0]
            pNum.text = f"0{i+1}"
            pNum.font.size = Pt(24)
            pNum.font.bold = True
            pNum.font.color.rgb = RGBColor(0x00, 0x66, 0xCC)

            # 標題
            txTitle = slide.shapes.add_textbox(Cm(4.0), y, Cm(27.0), Cm(0.8))
            tfTitle = txTitle.text_frame
            pTitle = tfTitle.paragraphs[0]
            pTitle.text = action
            pTitle.font.size = Pt(13)
            pTitle.font.bold = True
            pTitle.font.color.rgb = RGBColor(0x00, 0x33, 0x66)

            # 理由
            if rationale:
                txR = slide.shapes.add_textbox(Cm(4.0), y + Cm(0.9), Cm(27.0), Cm(1.5))
                tfR = txR.text_frame
                tfR.word_wrap = True
                pR = tfR.paragraphs[0]
                pR.text = rationale
                pR.font.size = Pt(10)
                pR.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

            y += Cm(3.0)

    def _fill_chart(self, slide: Slide, spec: dict):
        """填充含圖表的頁面 — 使用 python-pptx 原生圖表。"""
        chart_spec = spec.get("chart", {})
        chart_type = chart_spec.get("type", "bar")
        categories = chart_spec.get("categories", [])
        series_list = chart_spec.get("series", [])
        data_points = chart_spec.get("data_points", [])

        # 圖表位置 (在 1_標題及內容 的 body 區域內)
        position = {
            "left": Cm(1.5),
            "top": Cm(4.5),
            "width": Cm(30.0),
            "height": Cm(10.0),
        }

        chart_created = False

        # 散佈圖使用 data_points
        if chart_type == "scatter" and data_points:
            self.chart_factory.create_scatter_chart(
                slide, data_points,
                title=chart_spec.get("title", ""),
                x_label=chart_spec.get("x_axis", {}).get("label", ""),
                y_label=chart_spec.get("y_axis", {}).get("label", ""),
                position=position,
            )
            chart_created = True

        # 其他圖表使用 categories + series
        elif series_list and categories:
            series_data = {}
            for s in series_list:
                if "data" in s and s["data"]:
                    series_data[s.get("name", "Series")] = s["data"]

            if series_data:
                if chart_type == "bar":
                    self.chart_factory.create_bar_chart(
                        slide, categories, series_data,
                        title=chart_spec.get("title", ""),
                        position=position,
                        y_axis_label=chart_spec.get("y_axis", {}).get("label", ""),
                        y_axis_unit=chart_spec.get("y_axis", {}).get("unit", ""),
                    )
                    chart_created = True
                elif chart_type == "line":
                    self.chart_factory.create_line_chart(
                        slide, categories, series_data,
                        title=chart_spec.get("title", ""),
                        position=position,
                    )
                    chart_created = True
                elif chart_type == "combo":
                    keys = list(series_data.keys())
                    bar_data = {keys[0]: series_data[keys[0]]} if keys else {}
                    line_data = {k: series_data[k] for k in keys[1:]} if len(keys) > 1 else {}
                    self.chart_factory.create_combo_chart(
                        slide, categories, bar_data, line_data,
                        title=chart_spec.get("title", ""),
                        position=position,
                    )
                    chart_created = True
                elif chart_type == "stacked_bar":
                    self.chart_factory.create_stacked_bar_chart(
                        slide, categories, series_data,
                        title=chart_spec.get("title", ""),
                        position=position,
                    )
                    chart_created = True
                elif chart_type == "pie":
                    first_series = series_list[0] if series_list else {}
                    values = first_series.get("data", [])
                    if values:
                        self.chart_factory.create_pie_chart(
                            slide, categories, values,
                            title=chart_spec.get("title", ""),
                            position=position,
                        )
                        chart_created = True

        # 如果沒有生成圖表，顯示提示
        if not chart_created:
            txBox = slide.shapes.add_textbox(Cm(5), Cm(7), Cm(23), Cm(3))
            tf = txBox.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = f"[圖表區域 — {chart_spec.get('title', '待補充資料')}]"
            p.font.size = Pt(14)
            p.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
            p.alignment = PP_ALIGN.CENTER

        # 洞察文字 (圖表下方)
        insights = spec.get("insights", [])
        if insights:
            insight_y = Cm(15.0)
            for ins in insights[:2]:
                text = ins.get("text", "") if isinstance(ins, dict) else str(ins)
                is_spec = ins.get("is_speculation", False) if isinstance(ins, dict) else False
                prefix = "（推測）" if is_spec else ""
                txBox = slide.shapes.add_textbox(Cm(1.5), insight_y, Cm(30.0), Cm(1.2))
                tf = txBox.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = f"◆ {prefix}{text}"
                p.font.size = Pt(9)
                p.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
                insight_y += Cm(1.3)

    def _fill_table(self, slide: Slide, spec: dict):
        """填充含原生表格的頁面。"""
        table_spec = spec.get("table", {})
        headers = table_spec.get("headers", [])
        rows = table_spec.get("rows", [])

        if not headers or not rows:
            return

        n_rows = min(len(rows) + 1, 15)  # 限制行數避免溢出
        n_cols = len(headers)

        tbl_shape = slide.shapes.add_table(
            n_rows, n_cols,
            Cm(1.5), Cm(4.5), Cm(30.0), Cm(11.0),
        )
        table = tbl_shape.table

        # Header
        for col_idx, header in enumerate(headers):
            cell = table.cell(0, col_idx)
            cell.text = str(header)
            for para in cell.text_frame.paragraphs:
                para.font.bold = True
                para.font.size = Pt(9)

        # Data rows
        for row_idx, row_data in enumerate(rows[:n_rows - 1]):
            for col_idx, value in enumerate(row_data):
                if col_idx < n_cols:
                    cell = table.cell(row_idx + 1, col_idx)
                    cell.text = str(value) if value is not None else ""
                    for para in cell.text_frame.paragraphs:
                        para.font.size = Pt(8)

    def _fill_insights_only(self, slide: Slide, spec: dict):
        """只有洞察文字的頁面。"""
        insights = spec.get("insights", [])
        y = Cm(4.5)
        for ins in insights[:6]:
            text = ins.get("text", "") if isinstance(ins, dict) else str(ins)
            txBox = slide.shapes.add_textbox(Cm(1.5), y, Cm(30.0), Cm(1.5))
            tf = txBox.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = f"• {text}"
            p.font.size = Pt(11)
            y += Cm(1.8)
