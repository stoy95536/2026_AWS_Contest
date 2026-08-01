# Task 3: PowerPoint 模板解析、原生圖表與版面生成

## 需求
依台新新光金控模板產生 16 頁專業簡報，所有物件可在 PowerPoint 中再次編輯。

## 規格

### 模板 (附件一)
- 尺寸: 12192000 x 6858000 EMU (33.9 x 19.1 cm, 16:9)
- Layout [0] 標題投影片: TITLE + BODY
- Layout [1] 2_標題投影片: TITLE only → 封面/章節
- Layout [2] 3_標題投影片: TITLE only → 結束頁
- Layout [3] 1_標題及內容: BODY + TITLE + SLIDE_NUMBER → 內容頁
- Layout [4] 2_章節標題: TITLE (下方) → 章節分隔

### 圖表類型 (原生 python-pptx)
- 直條圖 (COLUMN_CLUSTERED)
- 折線圖 (LINE_MARKERS)
- 組合圖 (Combo)
- 散佈圖 (XY_SCATTER)
- 堆疊直條圖 (COLUMN_STACKED)
- 圓餅圖 (PIE)

### 16 頁結構
| 頁 | Layout | 內容 |
|---|---|---|
| 1 | 2_標題投影片 | 封面 |
| 2 | 1_標題及內容 | 目錄 |
| 3 | 1_標題及內容 | Executive Summary |
| 4 | 2_章節標題 | Ch.01 市場整體概況 |
| 5 | 1_標題及內容 | 趨勢圖 (combo) |
| 6 | 1_標題及內容 | 排名圖 (bar) |
| 7 | 2_章節標題 | Ch.02 同業競爭 |
| 8 | 1_標題及內容 | 散佈圖 (scatter) |
| 9 | 1_標題及內容 | 比較圖 (bar) |
| 10 | 2_章節標題 | Ch.03 活躍度 |
| 11 | 1_標題及內容 | 每卡簽帳 (bar) |
| 12 | 1_標題及內容 | 堆疊圖 (stacked) |
| 13 | 2_章節標題 | Ch.04 風險 |
| 14 | 1_標題及內容 | 風險圖 (bar) |
| 15 | 1_標題及內容 | 策略建議 |
| 16 | 3_標題投影片 | 感謝頁 |

### 交付成果
- [x] src/presentation/template_parser.py
- [x] src/presentation/chart_factory.py
- [x] src/presentation/ppt_generator.py

### 驗收標準
- [x] 16 頁使用正確 layout
- [x] 7 頁含原生可編輯圖表
- [x] 無空白 placeholder
- [x] 圖表可右鍵「編輯資料」
