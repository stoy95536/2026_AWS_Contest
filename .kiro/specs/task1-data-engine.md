# Task 1: Excel 資料解析、指標計算與資料血緣

## 需求
建立可靠的資料層，確保所有簡報數值由程式從原始 Excel 精確計算。

## 規格

### 輸入
- 附件四_預期修正參照資料.xlsx
- 工作表: P.5預期修正_流通卡數, P.5預期修正_當月簽帳金額, P.7預期修正_流通卡數, P.7預期修正_當月簽帳金額

### 資料格式
- Row 0: header (金融機構名稱, 11401-11412)
- Rows 1-32: 各銀行
- Row 33: 總計
- P.7 工作表多一欄「市佔率」

### 標準化輸出格式
```
institution | period | metric | value | unit | source_file | source_sheet | source_cell
```

### 指標計算
- 有效卡率 = 有效卡數 / 流通卡數 * 100
- 市占率 = 機構值 / 總計 * 100
- MoM = (本期 - 前期) / 前期 * 100
- YoY = (本期 - 去年同期) / 去年同期 * 100（需有基期資料）
- 排名 = 程式排序（排除「總計」）

### 交付成果
- [x] src/data_loader/excel_loader.py
- [x] src/data_loader/data_standardizer.py
- [x] src/calculation_engine/metrics.py
- [x] src/calculation_engine/data_lineage.py
- [x] src/validation/data_validator.py

### 驗收標準
- [x] 市場流通卡數 = 60,485,911 (6,049 萬張)
- [x] 台新市占率 = 11.0%
- [x] 排名: 中信 > 玉山 > 北富邦 > 國泰 > 台新
- [x] 無113年資料時 YoY = N/A
