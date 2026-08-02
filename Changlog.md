# 異動紀錄：資料領域變更（信用卡 → 決賽當天 11 份旅遊 Excel）

> 背景：主辦方確認決賽現場將提供 11 份旅遊業務相關 Excel（欄位/指標事先未知），並要求系統可吃通用 Prompt 直接生成，盡量不寫死業務指標。本次異動即為因應此變更所做的架構調整。

## 新增檔案
- **`task1.md`**（全新）：成員 A 完整架構規格書。內容涵蓋資料目錄建置（三層欄位比對）、白名單運算積木庫、LLM Function Calling 流程、計算假設聲明、Sanity Check、資料血緣、Kiro 規格拆解、兩天時程建議。
- **`CLAUDE.md`**（全新／取代舊版）：Claude Code 協作規則文件，鐵律由 7 條擴充為 11 條，任務清單改為 Stage 1（資料目錄）／Stage 2（Prompt 處理）兩階段，新增「LLM 生成程式碼語法正確但業務定義理解錯誤」風險提醒。

## `README.md` 異動摘要
（完整逐行 diff 見 `README_diff.patch`；`git diff --stat` 結果：1 file changed, 108 insertions(+), 77 deletions(-)）

| 章節 | 異動狀態 | 內容 |
|---|---|---|
| 標題／開頭引言 | 修改 | 新增「資料領域變更說明」區塊，明講信用卡→旅遊資料 |
| 1. 專案目標（系統輸入輸出） | 修改 | 輸入從「信用卡業務統計 Excel」改為「多份 Excel 業務資料（11份）」；輸出從固定 16 頁改為「依 Prompt 動態規劃章節」 |
| 2. 核心設計原則 | 新增 | 新增 2.2a（資料目錄）、2.2b（白名單積木）兩小節 |
| 3. 建議系統流程圖 | 修改 | Mermaid 流程圖加入「欄位語意比對」「Data Catalog」「白名單積木」「計算假設聲明」節點 |
| 第一大項（成員 A） | **整段改寫** | 從信用卡指標函式庫列表，改為精簡摘要 + 指向 `task1.md` |
| 第二大項（成員 B） | 小幅修改 | 工具定義移除「取得銀行排名」改為通用「取得排名」；Planner Agent 補註「依 Data Catalog 動態規劃章節」 |
| 第三大項（成員 C） | 中幅修改 | 原生圖表清單移除信用卡專屬命名（如「有效卡率比較圖」→「佔比／滲透率比較圖」）；16 頁固定章節表格改標示為「信用卡情境範例，非寫死」，並新增旅遊情境章節範例 |
| **第四大項（成員 D）** | **未修改** | QA 回溯、Pipeline、Web Demo、AWS 部署段落維持原樣 |
| 5.1 資料引擎輸出格式 | 修改 | 新增 `assumption_statement`、`block_chain` 兩個新欄位；補充旅遊情境 JSON 範例對照 |
| 5.2 / 5.3 | 未修改 | Slide Spec 格式、QA 報告格式維持原樣 |
| 6. GitHub 目錄規劃 | 修改 | 新增 `task1.md`、`src/catalog_builder/`、`src/calculation_engine/blocks/`、`executor.py`、`outputs/data_catalog.json`、`schemas/data_catalog.schema.json` |
| 7. 分支規則 | 未修改 | |
| 8. 開發時程 | 未修改 | |
| 9. Definition of Done | 未修改 | |
| 10. 評分對應 | 修改 1 行 | 「主題切合度」說明從「聚焦金融信用卡業務報表自動化」改為「聚焦金融業管報自動化痛點，並以領域無關架構因應…」 |

## 建議 commit message
```
refactor(architecture): 因應決賽當天11份旅遊Excel，資料層架構改為領域無關設計

- 新增 task1.md：資料目錄 + 白名單積木 + LLM Function Calling 完整規格
- 更新 CLAUDE.md：同步新架構鐵律與任務清單
- 更新 README.md：
  - 標註資料來源由信用卡範例改為決賽當天旅遊資料
  - 第一大項改寫指向 task1.md
  - 第二、三大項移除信用卡專屬寫死內容，改為通用/動態表述
  - 新增資料目錄相關的目錄結構與輸出 schema 欄位
  - 第四大項、分支規則、時程、DoD 未變動
```