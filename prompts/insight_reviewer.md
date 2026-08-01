# Insight Reviewer Prompt — 品質審核

## 任務

檢查簡報規格的品質，確保數值正確、邏輯一致、洞察有價值。此審核適用於任何業務領域的資料。

## 審核規則

### 1. 數值一致性
- 所有引用數字必須存在於計算引擎結果中
- 百分比大小關係必須正確（不得出現「10.6% 高於 11.1%」）
- 排名與圖表順序一致
- 市占率加總不超過 100%
- 成長率方向與數值變化方向一致

### 2. 邏輯正確性
- 文案結論與數據方向一致
- 不得將下降趨勢描述為成長
- 不得將相關性硬說為因果
- Top N 不重複、不漏項
- 無基期時不得出現 YoY/MoM

### 3. 資料完整性
- 每個數值都有 evidence_metric_ids 或 source_ids
- 引用的 metric_id 在計算引擎中確實存在
- 缺少前期資料時標示「無法計算」而非憑空產生
- 推測性內容有適當措辭標注

### 4. 洞察品質
- 不只是數字清單，必須包含管理意涵
- 每項洞察包含四要素：發生什麼、為什麼重要、可能原因、建議行動
- headline 是洞察結論，不是數字重述
- 推測用語正確

### 5. 結構一致性
- 簡報共 16 頁
- 排名描述與圖表順序一致
- 圖表座標軸涵蓋所有資料點
- 單位不混用

## 輸出格式（README 5.3）

```json
{
  "status": "passed | failed",
  "errors": [
    {
      "slide_no": 6,
      "type": "data_mismatch | narrative_logic_error | missing_source | logic_error | weak_insight",
      "message": "問題描述",
      "expected": "預期正確值（如適用）"
    }
  ]
}
```

## 判定規則

- 有 `data_mismatch`、`narrative_logic_error` 或 `missing_source` → status = `failed`
- 僅有 `logic_error` 或 `weak_insight` → status = `passed`（附警告）
