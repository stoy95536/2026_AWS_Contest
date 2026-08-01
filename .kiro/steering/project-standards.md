---
inclusion: always
---

# 專案開發規範 — LLM Excel-to-PPT Automation

## 專案概述
本專案為 2026 AWS Contest 競賽作品，使用 Kiro AI IDE 進行開發。
目標：讀取信用卡業務 Excel 資料，透過 LLM Agent 分析，自動產出 16 頁策略簡報。

## 技術棧
- Python 3.11+
- pandas / openpyxl — Excel 資料處理
- python-pptx — PowerPoint 原生物件生成
- boto3 — AWS Bedrock LLM 呼叫
- FastAPI — Web Demo API
- Docker — 部署容器化

## 核心設計原則
1. **LLM 不直接負責精確計算** — 所有數值由 Python 確定性計算
2. **優先讀取 Excel 原生結構** — 不將 Excel 轉圖片再 OCR
3. **PowerPoint 必須保留原生物件** — 圖表可編輯，不貼圖片
4. **每個數值都必須可追溯** — 資料血緣 (Data Lineage)

## 程式碼規範
- 函式與類別須有 docstring
- 中文註解描述商業邏輯
- 所有計算須經過 DataLineageTracker 記錄
- 不得由 LLM 自行產生未經驗證的數值

## 目錄結構
```
src/
├── data_loader/          # Task 1: Excel 解析
├── calculation_engine/   # Task 1: 指標計算與血緣
├── validation/           # Task 1+4: 資料驗證與回溯
├── agents/               # Task 2: LLM Agent
├── presentation/         # Task 3: PPT 生成
└── pipeline.py           # Task 4: 端到端整合
```

## 分支規則
- main: 穩定可展示版本
- develop: 日常整合
- feature/*: 各成員開發分支
