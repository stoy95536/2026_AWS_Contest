"""
圖表工廠
建立 PowerPoint 原生可編輯圖表。
所有圖表為原生物件，不以圖片嵌入。
"""

from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.util import Inches, Pt, Cm, Emu
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
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
    ):
        """
        建立橫條/直條圖。

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

        # 設定顏色
        for i, series in enumerate(chart.series):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = self.colors[i % len(self.colors)]

        # Y 軸設定
        value_axis = chart.value_axis
        if y_axis_label:
            value_axis.has_title = True
            value_axis.axis_title.text_frame.text = f"{y_axis_label} ({y_axis_unit})" if y_axis_unit else y_axis_label

        return chart_frame

    def create_line_chart(
        self,
        slide: Slide,
        categories: list[str],
        series_data: dict[str, list[float]],
        title: str = "",
        position: dict = None,
    ):
        """建立折線圖。"""
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

        return chart_frame

    def create_combo_chart(
        self,
        slide: Slide,
        categories: list[str],
        bar_series: dict[str, list[float]],
        line_series: dict[str, list[float]],
        title: str = "",
        position: dict = None,
    ):
        """建立組合圖（直條 + 折線）。"""
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

        # 將折線系列改為折線類型
        bar_count = len(bar_series)
        for i in range(bar_count, bar_count + len(line_series)):
            if i < len(chart.series):
                plot = chart.plots[0]
                # Note: python-pptx 對組合圖的支援有限
                # 實作上可能需要直接操作 XML

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
        建立散佈圖。

        Args:
            data_points: [{"name": str, "x": float, "y": float}, ...]
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

        return chart_frame

    def create_stacked_bar_chart(
        self,
        slide: Slide,
        categories: list[str],
        series_data: dict[str, list[float]],
        title: str = "",
        position: dict = None,
    ):
        """建立堆疊直條圖。"""
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

        return chart_frame

    def create_pie_chart(
        self,
        slide: Slide,
        categories: list[str],
        values: list[float],
        title: str = "",
        position: dict = None,
    ):
        """建立圓餅圖。"""
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
