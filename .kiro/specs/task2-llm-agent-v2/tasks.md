# Task 2 LLM Agent 系統 — Tasks（開發歷程）

> 使用 Kiro IDE 開發，以下為實際執行的任務與進度。全程於 Kiro 中規劃、實作、測試、除錯。

## 階段一：通用化重構

- [x] 1. 重寫 system_prompt.md — 移除信用卡專屬內容，改為金融業為核心的通用策略顧問
- [x] 2. 重寫 slide_planner.md — 動態結構規劃，依資料特性而非固定模板
- [x] 3. 重寫 insight_reviewer.md — 六維度品質審核框架，對齊 README 5.3
- [x] 4. 重寫 planner_agent.py — 新增 classify_data() 智慧分類，結構由資料驅動
- [x] 5. 重寫 analyst_agent.py — WIRA 四要素洞察，layout 導向分析方法
- [x] 6. 重寫 reviewer_agent.py — QA 輸出格式對齊 README 5.3
- [x] 7. 新增 schemas/metric.schema.json 與 slide_spec.schema.json

## 階段二：移除所有硬編碼

- [x] 8. 徹底移除 Agent 中所有信用卡硬編碼內容（DEFAULT_16_PAGE_STRUCTURE 等）
- [x] 9. 驗證：輸入信用卡/旅遊/零售資料，各自產出對應簡報，原始碼無產業字串
- [x] 10. 頁數改為使用者可指定（total_pages 參數），未指定預設 16 頁

## 階段三：LLM 連線

- [x] 11. Agent 改為從 .env 讀取 MODEL_ID / AWS_REGION
- [x] 12. 安裝 boto3 + python-dotenv，設定 .env
- [x] 13. 新增 tests/test_llm_connection.py 連線測試
- [x] 14. 除錯：AWS 憑證/region/inference profile
      - 發現須用 inference profile ID（us.anthropic.claude-sonnet-4-20250514-v1:0）
      - 而非直接 model ID
- [x] 15. LLM 連線測試 4/4 通過

## 階段四：與 Task1 串接

- [x] 16. 讀取 Task1 分支的 sample 檔，分析 analysis_result.json 格式
- [x] 17. planner_agent.py 接受 metrics=[] 與 chart_data=[]
- [x] 18. analyst_agent.py 從 chart.series[].metric_ids 收集真實 ID
- [x] 19. 圖表格式加入 series[] 陣列（與成員 D 的 ppt_reconciler 相容）
- [x] 20. reviewer_agent.py 接受 metrics_list=[]（Task1 格式）
- [x] 21. 新增 run_task2_from_task1() 串接入口
- [x] 22. 測試：Task1 真實旅遊資料（180 指標、11 圖表）跑通

## 階段五：防幻覺與品質修正

- [x] 23. 發現 LLM 規劃器編造不存在的 metric_id → 有 chart_data 時強制規則引擎規劃
- [x] 24. 新增 _sanitize_insights() 過濾 LLM 幻覺的 metric_id
- [x] 25. 修正 Reviewer 語意：空 evidence 為 weak_insight（警告）而非 missing_source（阻斷）
- [x] 26. 策略頁餵入全簡報關鍵指標，產出有數據支撐的建議
- [x] 27. 最終驗證：LLM 模式 QA PASSED，0 errors，39 條洞察

## 最終成果

| 指標 | 結果 |
|------|------|
| 測試資料 | Task1 真實旅遊資料（180 指標、11 圖表）|
| 產出頁數 | 16 頁 |
| 洞察數 | 39 條 |
| 策略建議 | 6 條 |
| QA 狀態 | PASSED（0 錯誤）|
| 洞察品質 | 引用真實數字、標注推測、連結金融業務機會 |

## 洞察範例（LLM 實際產出）

> 「2024年來台旅客達786萬人次，年增21.13%，顯示台灣觀光市場正從疫情衝擊中強勁復甦。這個雙位數成長率對台灣服務業復甦具關鍵意義，可能反映邊境開放政策效果...金融機構應積極布局觀光相關授信與支付服務」

此洞察展現：引用真實數字（786萬、21.13%）、標注推測（可能）、連結金融業務（授信、支付）——完全符合「金融業與百工百業相連」的設計目標。
