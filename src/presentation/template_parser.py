"""
PowerPoint 模板解析器
解析台新新光金控模板（附件一），提取版面配置、字型、色彩及座標設定。

附件一模板結構：
- Layout [0] 標題投影片: TITLE + BODY (封面用)
- Layout [1] 2_標題投影片: TITLE only (章節分隔用)
- Layout [2] 3_標題投影片: TITLE only (結束頁用)
- Layout [3] 1_標題及內容: BODY + TITLE + SLIDE_NUMBER (內容頁用)
- Layout [4] 2_章節標題: TITLE only (章節標題用)
- Layout [5] 1_標題投影片: CENTER_TITLE + SUBTITLE

模板 5 頁範例：
- Slide 1: 封面 (layout: 2_標題投影片)
- Slide 2: 內容頁 (layout: 1_標題及內容)
- Slide 3: 章節分隔 (layout: 2_章節標題)
- Slide 4: 內容頁 (layout: 1_標題及內容)
- Slide 5: 結束頁 (layout: 3_標題投影片)
"""

import os
from dataclasses import dataclass
from typing import Optional

from pptx import Presentation
from pptx.util import Cm, Pt, Emu
from pptx.dml.color import RGBColor


@dataclass
class TemplateStyle:
    """模板樣式設定。"""
    slide_width: int = 12192000  # 33.9 cm (16:9)
    slide_height: int = 6858000  # 19.1 cm
    title_font: str = "微軟正黑體"
    title_size: int = 28
    body_font: str = "微軟正黑體"
    body_size: int = 14
    primary_color: str = "003366"  # 台新深藍
    secondary_color: str = "0066CC"
    accent_color: str = "FF6600"
    # 內容頁 (1_標題及內容) 的座標
    content_title_left: float = 1.0   # cm
    content_title_top: float = 0.7
    content_title_width: float = 31.3
    content_title_height: float = 2.1
    content_body_left: float = 1.0
    content_body_top: float = 3.5
    content_body_width: float = 31.2
    content_body_height: float = 13.6
    slide_number_left: float = 31.7
    slide_number_top: float = 17.8


# 模板 Layout 名稱對應
LAYOUT_COVER = "2_標題投影片"          # 封面、章節分隔頁
LAYOUT_CONTENT = "1_標題及內容"        # 標題+內容+頁碼的內容頁
LAYOUT_CHAPTER = "2_章節標題"          # 章節標題頁 (文字置中偏下)
LAYOUT_THANKYOU = "3_標題投影片"       # 結束頁
LAYOUT_TITLE_BODY = "標題投影片"       # 標題+正文 (封面用)
LAYOUT_CENTER = "1_標題投影片"         # 置中標題+副標題


class TemplateParser:
    """解析 PowerPoint 模板，提取版面資訊。"""

    def __init__(self, template_path: Optional[str] = None):
        self.template_path = template_path
        self.style = TemplateStyle()
        self._layout_map: dict[str, int] = {}

        if template_path and os.path.exists(template_path):
            self._parse_template()

    def _parse_template(self):
        """解析模板檔案，建立 layout 名稱索引。"""
        prs = Presentation(self.template_path)
        self.style.slide_width = prs.slide_width
        self.style.slide_height = prs.slide_height

        for i, layout in enumerate(prs.slide_layouts):
            self._layout_map[layout.name] = i

    def get_style(self) -> TemplateStyle:
        """取得模板樣式。"""
        return self.style

    def get_layout_index(self, layout_name: str) -> int:
        """取得指定 layout 的索引。"""
        return self._layout_map.get(layout_name, 0)

    def create_presentation(self) -> Presentation:
        """
        建立簡報（基於模板）。
        會清除模板中既有的範例投影片，只保留 layout 定義。
        """
        if self.template_path and os.path.exists(self.template_path):
            prs = Presentation(self.template_path)
            # 清除模板中既有的範例投影片
            while len(prs.slides) > 0:
                rId = prs.slides._sldIdLst[0].rId
                prs.part.drop_rel(rId)
                del prs.slides._sldIdLst[0]
            return prs
        else:
            prs = Presentation()
            prs.slide_width = self.style.slide_width
            prs.slide_height = self.style.slide_height
            return prs

    def get_layout_for_page_type(self, page_type: str) -> str:
        """
        根據頁面類型回傳對應的 layout 名稱。

        Page types:
            cover       → 2_標題投影片
            content     → 1_標題及內容
            chapter     → 2_章節標題
            thank_you   → 3_標題投影片
        """
        mapping = {
            "cover": LAYOUT_COVER,
            "content": LAYOUT_CONTENT,
            "chapter": LAYOUT_CHAPTER,
            "thank_you": LAYOUT_THANKYOU,
        }
        return mapping.get(page_type, LAYOUT_CONTENT)
