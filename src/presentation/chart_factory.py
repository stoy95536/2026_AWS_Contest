"""
圖表工廠
建立 PowerPoint 原生可編輯圖表。
所有圖表為原生物件，不以圖片嵌入。
"""

import copy

from lxml import etree

from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.util import Inches, Pt, Cm, Emu
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.oxml.ns import qn
from pptx.slide import Slide


# 台新品牌配色
TAISHIN_COLORS = [
    RGBColor(0x00, 0x33, 0x66),  # 深藍
    RGBColor(0x00, 0x66, 0xCC),  # 亮藍
    RGBColor(0xFF, 0x66, 0x00),  # 橘色
    RGBColor(0x33, 0x99, 0x33),  # 綠色
    RGBColor(0xCC, 0x33, 0x33),  # 紅色
    RGBColor(0x99, 0x66, 0xCC),  # 紫色
    RGBColor(0xFF, 0xCC, 0x00),  # 黃色
    RGBColor(0x66, 0x99, 0x99),  # 青色
]


class ChartFactory:
    """建立 PowerPoint 原生可編輯圖表。"""

    def __init__(self):
        self.colors = TAISHIN_COLORS

    def create_bar_chart(
        self,
        slide: Slide,
        categories: list[str],
        series_data: dict[str, list[float]],
        title: str = "",
        position: dict = None,
        y_axis_label: str = "",
        y_axis_unit: str = "",
        highlight_first: bool = True,
        highlight_institution: str = "",
    ):
        """
        建立橫條/直條圖。
        支援條件式格式：排名第一金色、目標機構深藍高亮。

        Args:
            slide: 目標投影片
            categories: X 軸類別
            series_data: {系列名稱: [值...]}
            title: 圖表標題
            position: 位置 dict (left, top, width, height)
            y_axis_label: Y 軸標籤
            y_axis_unit: Y 軸單位
            highlight_first: 是否將排名第一的長條標為金色
            highlight_institution: 目標機構名稱（深藍高亮）
        """
        if position is None:
            position = {"left": Cm(2), "top": Cm(4), "width": Cm(22), "height": Cm(12)}

        chart_data = CategoryChartData()
        chart_data.categories = categories

        for name, values in series_data.items():
            chart_data.add_series(name, values)

        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED,
            position["left"],
            position["top"],
            position["width"],
            position["height"],
            chart_data,
        )

        chart = chart_frame.chart
        if title:
            chart.has_title = True
            chart.chart_title.text_frame.text = title

        # 設定顏色 — 條件式格式
        for i, series in enumerate(chart.series):
            base_color = self.colors[i % len(self.colors)]
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = base_color

            # 條件式格式：逐點上色（排名第一金色、目標機構深藍）
            if len(series_data) == 1:  # 單系列才做逐點高亮
                for pt_idx, cat in enumerate(categories):
                    point = series.points[pt_idx]
                    if highlight_first and pt_idx == 0:
                        # 排名第一：金色
                        point.format.fill.solid()
                        point.format.fill.fore_color.rgb = RGBColor(0xFF, 0xCC, 0x00)
                    elif highlight_institution and highlight_institution in cat:
                        # 目標機構：台新深藍
                        point.format.fill.solid()
                        point.format.fill.fore_color.rgb = RGBColor(0x00, 0x33, 0x66)

        # Y 軸設定
        self._set_value_axis_title(chart.value_axis, y_axis_label, y_axis_unit)

        return chart_frame

    def create_line_chart(
        self,
        slide: Slide,
        categories: list[str],
        series_data: dict[str, list[float]],
        title: str = "",
        position: dict = None,
        y_axis_label: str = "",
        y_axis_unit: str = "",
    ):
        """
        建立折線圖。

        Args:
            slide: 目標投影片
            categories: X 軸類別
            series_data: {系列名稱: [值...]}
            title: 圖表標題
            position: 位置 dict (left, top, width, height)
            y_axis_label: Y 軸標籤
            y_axis_unit: Y 軸單位
        """
        if position is None:
            position = {"left": Cm(2), "top": Cm(4), "width": Cm(22), "height": Cm(12)}

        chart_data = CategoryChartData()
        chart_data.categories = categories

        for name, values in series_data.items():
            chart_data.add_series(name, values)

        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.LINE_MARKERS,
            position["left"],
            position["top"],
            position["width"],
            position["height"],
            chart_data,
        )

        chart = chart_frame.chart
        if title:
            chart.has_title = True
            chart.chart_title.text_frame.text = title

        for i, series in enumerate(chart.series):
            series.format.line.color.rgb = self.colors[i % len(self.colors)]
            series.format.line.width = Pt(2.5)

        # Y 軸設定
        self._set_value_axis_title(chart.value_axis, y_axis_label, y_axis_unit)

        return chart_frame

    def create_combo_chart(
        self,
        slide: Slide,
        categories: list[str],
        bar_series: dict[str, list[float]],
        line_series: dict[str, list[float]],
        title: str = "",
        position: dict = None,
        y_axis_label: str = "",
        y_axis_unit: str = "",
    ):
        """
        建立組合圖（直條 + 折線）。
        透過操作底層 XML，將折線系列從 barChart plot 移至獨立的 lineChart plot，
        實現真正的組合圖效果。

        Args:
            slide: 目標投影片
            categories: X 軸類別
            bar_series: 直條系列 {系列名稱: [值...]}
            line_series: 折線系列 {系列名稱: [值...]}
            title: 圖表標題
            position: 位置 dict (left, top, width, height)
            y_axis_label: Y 軸標籤
            y_axis_unit: Y 軸單位
        """
        if position is None:
            position = {"left": Cm(2), "top": Cm(4), "width": Cm(22), "height": Cm(12)}

        chart_data = CategoryChartData()
        chart_data.categories = categories

        # 先加直條系列
        for name, values in bar_series.items():
            chart_data.add_series(name, values)
        # 再加折線系列
        for name, values in line_series.items():
            chart_data.add_series(name, values)

        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED,
            position["left"],
            position["top"],
            position["width"],
            position["height"],
            chart_data,
        )

        chart = chart_frame.chart
        if title:
            chart.has_title = True
            chart.chart_title.text_frame.text = title

        # --- 透過 XML 操作將折線系列移至獨立 lineChart plot ---
        bar_count = len(bar_series)
        if line_series and bar_count < len(chart.series):
            plot_area = chart._chartSpace.find(qn("c:chart")).find(qn("c:plotArea"))
            bar_chart_elem = plot_area.find(qn("c:barChart"))

            if bar_chart_elem is not None:
                # 建立 lineChart 元素
                line_chart_elem = etree.SubElement(plot_area, qn("c:lineChart"))
                # 設定 grouping 為 standard
                grouping = etree.SubElement(line_chart_elem, qn("c:grouping"))
                grouping.set("val", "standard")

                # 從 barChart 中取出折線系列，移至 lineChart
                all_ser = bar_chart_elem.findall(qn("c:ser"))
                for i in range(bar_count, bar_count + len(line_series)):
                    if i < len(all_ser):
                        ser_elem = all_ser[i]
                        bar_chart_elem.remove(ser_elem)
                        line_chart_elem.append(ser_elem)

                # 為 lineChart 加入 marker 設定（顯示標記點）
                marker = etree.SubElement(line_chart_elem, qn("c:marker"))
                marker_val = etree.SubElement(marker, qn("c:val"))
                marker_val.text = "1"

                # 設定折線系列使用副Y軸 (axId 對應)
                # 複製主軸 axId 引用到 lineChart
                for ax_id in bar_chart_elem.findall(qn("c:axId")):
                    new_ax_id = copy.deepcopy(ax_id)
                    line_chart_elem.append(new_ax_id)

        # 設定直條系列顏色
        for i, series in enumerate(chart.series):
            if i < bar_count:
                series.format.fill.solid()
                series.format.fill.fore_color.rgb = self.colors[i % len(self.colors)]
            else:
                # 折線系列設定線條顏色
                color_idx = i % len(self.colors)
                series.format.line.color.rgb = self.colors[color_idx]
                series.format.line.width = Pt(2.5)

        # Y 軸設定
        self._set_value_axis_title(chart.value_axis, y_axis_label, y_axis_unit)

        return chart_frame

    def create_scatter_chart(
        self,
        slide: Slide,
        data_points: list[dict],
        title: str = "",
        x_label: str = "",
        y_label: str = "",
        position: dict = None,
    ):
        """
        建立散佈圖，並為每個資料點加上名稱標籤。

        Args:
            data_points: [{"name": str, "x": float, "y": float}, ...]
            title: 圖表標題
            x_label: X 軸標籤
            y_label: Y 軸標籤
            position: 位置 dict (left, top, width, height)
        """
        if position is None:
            position = {"left": Cm(2), "top": Cm(4), "width": Cm(22), "height": Cm(12)}

        chart_data = XyChartData()

        series = chart_data.add_series("銀行")
        for point in data_points:
            series.add_data_point(point["x"], point["y"])

        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.XY_SCATTER,
            position["left"],
            position["top"],
            position["width"],
            position["height"],
            chart_data,
        )

        chart = chart_frame.chart
        if title:
            chart.has_title = True
            chart.chart_title.text_frame.text = title

        # X 軸標籤
        if x_label:
            chart.category_axis.has_title = True
            chart.category_axis.axis_title.text_frame.text = x_label

        # Y 軸標籤
        if y_label:
            chart.value_axis.has_title = True
            chart.value_axis.axis_title.text_frame.text = y_label

        # 將 X 軸刻度移到底部（Y 軸在最小值處交叉），避免與資料點重疊
        # python-pptx 的 crosses 屬性在散佈圖上不一定生效，直接操作 XML
        plot_area = chart._chartSpace.find(qn("c:chart")).find(qn("c:plotArea"))
        # 找到 Y 軸 (valAx)，設定它在 X 軸最小值處交叉
        for val_ax in plot_area.findall(qn("c:valAx")):
            # 找到 crossesAt 或 crosses 元素
            crosses = val_ax.find(qn("c:crosses"))
            if crosses is not None:
                crosses.set("val", "min")
            else:
                crosses = etree.SubElement(val_ax, qn("c:crosses"))
                crosses.set("val", "min")

        # --- 透過 XML 為每個資料點加上名稱標籤 ---
        self._add_scatter_data_labels(chart, data_points)

        return chart_frame

    def _add_scatter_data_labels(self, chart, data_points: list[dict]):
        """
        為散佈圖的每個資料點加入自訂文字標籤（銀行名稱）。
        標籤放置於資料點上方，避免與軸刻度重疊。
        """
        plot_area = chart._chartSpace.find(qn("c:chart")).find(qn("c:plotArea"))
        scatter_chart = plot_area.find(qn("c:scatterChart"))
        if scatter_chart is None:
            return

        ser_elem = scatter_chart.find(qn("c:ser"))
        if ser_elem is None:
            return

        # 建立 dLbls 容器
        d_lbls = etree.SubElement(ser_elem, qn("c:dLbls"))

        for idx, point in enumerate(data_points):
            name = point.get("name", "")
            if not name:
                continue

            d_lbl = etree.SubElement(d_lbls, qn("c:dLbl"))

            # 指定 data point index
            idx_elem = etree.SubElement(d_lbl, qn("c:idx"))
            idx_elem.set("val", str(idx))

            # 標籤位置設為上方 (t = top)，避免跟軸線重疊
            d_lbl_pos = etree.SubElement(d_lbl, qn("c:dLblPos"))
            d_lbl_pos.set("val", "t")

            # 使用 tx (rich text) 設定自訂標籤文字
            tx = etree.SubElement(d_lbl, qn("c:tx"))
            rich = etree.SubElement(tx, qn("c:rich"))

            # body properties
            etree.SubElement(rich, qn("a:bodyPr"))
            etree.SubElement(rich, qn("a:lstStyle"))

            # paragraph
            p = etree.SubElement(rich, qn("a:p"))
            r = etree.SubElement(p, qn("a:r"))

            # 設定字體大小（10pt 清楚可見）
            r_pr = etree.SubElement(r, qn("a:rPr"))
            r_pr.set("lang", "zh-TW")
            r_pr.set("sz", "1000")  # 10pt

            t = etree.SubElement(r, qn("a:t"))
            t.text = name

            # 顯示設定：只顯示自訂文字，不顯示值
            show_val = etree.SubElement(d_lbl, qn("c:showVal"))
            show_val.set("val", "0")
            show_cat = etree.SubElement(d_lbl, qn("c:showCatName"))
            show_cat.set("val", "0")
            show_ser = etree.SubElement(d_lbl, qn("c:showSerName"))
            show_ser.set("val", "0")

    def create_stacked_bar_chart(
        self,
        slide: Slide,
        categories: list[str],
        series_data: dict[str, list[float]],
        title: str = "",
        position: dict = None,
        y_axis_label: str = "",
        y_axis_unit: str = "",
    ):
        """
        建立堆疊直條圖。

        Args:
            slide: 目標投影片
            categories: X 軸類別
            series_data: {系列名稱: [值...]}
            title: 圖表標題
            position: 位置 dict (left, top, width, height)
            y_axis_label: Y 軸標籤
            y_axis_unit: Y 軸單位
        """
        if position is None:
            position = {"left": Cm(2), "top": Cm(4), "width": Cm(22), "height": Cm(12)}

        chart_data = CategoryChartData()
        chart_data.categories = categories

        for name, values in series_data.items():
            chart_data.add_series(name, values)

        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_STACKED,
            position["left"],
            position["top"],
            position["width"],
            position["height"],
            chart_data,
        )

        chart = chart_frame.chart
        if title:
            chart.has_title = True
            chart.chart_title.text_frame.text = title

        for i, series in enumerate(chart.series):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = self.colors[i % len(self.colors)]

        # Y 軸設定
        self._set_value_axis_title(chart.value_axis, y_axis_label, y_axis_unit)

        return chart_frame

    def create_pie_chart(
        self,
        slide: Slide,
        categories: list[str],
        values: list[float],
        title: str = "",
        position: dict = None,
    ):
        """
        建立圓餅圖。
        圓餅圖無座標軸，不設定軸標籤。
        """
        if position is None:
            position = {"left": Cm(2), "top": Cm(4), "width": Cm(22), "height": Cm(12)}

        chart_data = CategoryChartData()
        chart_data.categories = categories
        chart_data.add_series("市占率", values)

        chart_frame = slide.shapes.add_chart(
            XL_CHART_TYPE.PIE,
            position["left"],
            position["top"],
            position["width"],
            position["height"],
            chart_data,
        )

        chart = chart_frame.chart
        if title:
            chart.has_title = True
            chart.chart_title.text_frame.text = title

        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM

        return chart_frame

    # ========== 共用工具方法 ==========

    def _set_value_axis_title(self, value_axis, label: str, unit: str = ""):
        """
        統一設定 Y 軸（數值軸）標題。
        格式：「標籤 (單位)」或僅「標籤」。
        座標軸單位須正確，不混用不同量級。
        """
        if not label:
            return
        value_axis.has_title = True
        axis_text = f"{label} ({unit})" if unit else label
        value_axis.axis_title.text_frame.text = axis_text
