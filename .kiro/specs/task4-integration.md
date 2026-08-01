# Task 4: 數值回溯 QA、系統整合、部署與 Live Demo

## 需求
將前三模組整合為端到端系統，建立校驗、操作介面與部署環境。

## 規格

### Pipeline 流程
```
上傳檔案 → 解析 → 計算 → LLM 規劃 → PPT 生成 → 數值回溯 → 輸出
```

### 校驗規則
- 百分比大小關係與文案一致（不得出現「10.6% 高於 11.1%」）
- 排名文字與圖表順序一致
- 無基期時不得出現 YoY
- 所有 KPI 的 metric_id 須存在於 data_lineage

### Web Demo
- FastAPI + 靜態 HTML
- 上傳 Excel → 處理 → 下載 PPT/Excel/QA報告

### 部署
- Docker (Dockerfile + docker-compose.yml)
- AWS compatible

### 交付成果
- [x] src/pipeline.py
- [x] src/validation/ppt_reconciler.py
- [x] app/api/server.py
- [x] app/web/index.html
- [x] deployment/Dockerfile
- [x] deployment/docker-compose.yml
- [x] demo_run.py

### 驗收標準
- [x] 從 Excel 到 PPT 可一鍵完成
- [x] 數值回溯校驗可攔截邏輯錯誤
- [x] Web Demo 架構已建立
- [x] Docker 部署設定完成
