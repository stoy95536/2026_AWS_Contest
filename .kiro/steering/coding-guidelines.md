---
inclusion: always
---

# 程式開發指引

## 資料處理規則
- 讀取 Excel 時使用 openpyxl engine，保留原生結構
- 標準化格式: institution | period | metric | value | unit | source_file | source_sheet | source_cell
- 「總計」行用於市場總計，不參與排名或市占率計算
- 缺少前期資料時，回傳 None 而非自行推算

## 計算引擎規則
- 市占率分母必須是同期間市場總計
- 排名由程式排序，不能由 LLM 排列
- YoY 需有前一年同期資料，否則標示 N/A
- 所有計算須透過 DataLineageTracker.record() 記錄

## PPT 生成規則
- 使用附件一模板的實際 layout:
  - 封面: 2_標題投影片
  - 內容頁: 1_標題及內容
  - 章節分隔: 2_章節標題
  - 結束頁: 3_標題投影片
- 圖表使用 python-pptx 原生 chart，不嵌入圖片
- 移除未使用的 placeholder，避免空白物件
- 座標軸單位須正確，不混用不同量級

## LLM Agent 規則
- LLM 只能引用計算引擎回傳的數字
- 推測性內容須標注 is_speculation: true
- 不得在文字中自行新增數字
- 缺少資料時標示「無法計算」而非猜測
