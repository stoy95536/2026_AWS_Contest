"""Executive Summary 頁面元件 — KPI 卡片 + 洞察。"""

from pptx.util import Pt, Cm
from pptx.dml.color import RGBColor
from pptx.slide import Slide


def fill_executive_summary(slide: Slide, spec: dict):
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
