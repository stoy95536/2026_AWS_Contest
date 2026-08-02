# Task 1 交付範例檔 — 給成員 B / C / D

這三份是 **Task 1 實際跑 11 份旅遊 Excel 產出的真實輸出**，不是手寫的假資料。
決賽當天檔案換掉後，內容會變、**格式不會變**，現在就能對著它寫串接程式。

> 正式執行時檔案位於 `outputs/`（開發期暫時寫在 `outputs/v2/`，避免蓋掉現有
> demo 素材）。這裡的副本只是讓你們不必自己跑就能開始接。

| 檔案 | 給誰 | 內容 |
|---|---|---|
| `analysis_result.json` | **B** + **C** | 180 個指標 + 11 張圖表 |
| `data_lineage.json` | **D** | 177 筆血緣，含積木鏈與真實 A1 座標 |
| `data_catalog.json` | **B** | 193 個欄位卡，供 Planner 規劃章節 |

重新產生：`python Task1/run_task1.py`

---

## 成員 B — 不用改任何程式碼

`data_summary` 的鍵名完全照你現有的 `plan_structure(data_summary)` 簽名，
已實測直接呼叫可產出 16 頁。

```python
import json
payload = json.load(open("Task1/samples/analysis_result.json", encoding="utf-8"))

specs = PlannerAgent().plan_structure(payload["data_summary"], use_llm=True, total_pages=16)
```

```
data_summary = {
  "metrics":      ["觀光外匯收入", "來臺旅客", "出國", "出國人次", "郵輪來臺遊客人次"],
  "institutions": ["日本", "韓國", "30至39歲", ...],   # 106 個維度值
  "periods":      ["1956", ..., "2025"],
  "record_count": 11130,
}
```

要引用實際數字時，用 `metric_id` 去 `payload["metrics"]` 查：

```python
from src.export import load_metrics
metrics = load_metrics("Task1/samples/analysis_result.json")   # {metric_id: metric}
metrics["來臺旅客_亞洲地區_日本_2024"]["value"]        # 1318372.0
metrics["來臺旅客_亞洲地區_日本_2024"]["display_value"] # "1,318,372"
```

**KPI 卡片請只引用 `metric_id`，不要自己抄數字進 slide_spec。**
成員 D 的回溯校驗就是靠比對 `metric_id` 是否存在於血緣紀錄。

---

## 成員 C — 加一行 import

`chart_data` 已經整理成你 `create_bar_chart(categories, series_data)` 的參數形狀。

```python
from src.export import load_chart_series

for chart_id, chart in load_chart_series("Task1/samples/analysis_result.json").items():
    factory.create_bar_chart(
        slide, x, y, cx, cy,
        categories=chart["categories"],     # list[str]
        series_data=chart["series_data"],   # {系列名: [float | None]}
        title=chart["title"],
    )
```

實際內容長這樣：

```
categories  = ["2020", "2021", "2022", "2023", "2024", "2025"]
series_data = {"來臺旅客_亞洲地區_日本": [269659.0, 10056.0, 87616.0, 928235.0, 1319592.0, 1479392.0]}
```

注意事項：

- **值可能是 `None`**（該年度無資料）。請讓圖表留空，**不要補 0**——
  補 0 會畫出一條假的下探曲線，而 2021 年那種疫情斷點是真實資訊。
- `chart["unit"]` 是該圖的單位（人次／美元／%／夜），座標軸請照它標，
  不同量級的系列不要混在同一張圖。
- `chart["metric_ids"]` 與 values 同序等長，需要回溯時可用。

---

## 成員 D — 加一行 import

你的 `PPTReconciler.__init__` 吃的是 `DataLineageTracker` **物件**，
而 `DataLineageTracker` 只有 `export_json()`、沒有讀檔方法，
所以原本載不進這份 JSON。已補一個 loader（放在 `src/export/`，
**沒有改到你的 `data_lineage.py`**）：

```python
from src.export import load_lineage_tracker

tracker = load_lineage_tracker("Task1/samples/data_lineage.json")   # 177 筆
reconciler = PPTReconciler(tracker)
result = reconciler.reconcile(slide_specs)
```

`get_record(metric_id)` 現在拿得到**真實儲存格座標**，可以打開 Excel 逐格核對：

```python
tracker.get_record("來臺旅客_亞洲地區_日本_2024").sources
# [{"file": "表1-3-歷年來臺旅客按國籍分.xlsx",
#   "sheet": "歷年來臺旅客-按國籍",
#   "range": "C65"}]
```

舊版的 `sources` 是 `{metric, institution, value}`，沒有任何座標，
無法回原檔核對——這是這次改版的重點。

JSON 裡另有 `block_chain`（積木調用鏈）與 `assumption_statement`（計算假設聲明）
兩欄可供查閱，沒有塞進 `LineageRecord` dataclass，以免改動你的型別定義。

### ⚠️ 有一個 bug 需要你和 B 對齊

`ppt_reconciler._check_chart_data` 讀的是：

```python
chart["series"][i]["metric_ids"]
```

但目前 `slide_spec.json` 的 chart 只有 `{"type", "series_metric_ids"}` 兩個鍵。
鍵名對不上 → `chart.get("series", [])` 永遠回傳空陣列 → **圖表校驗一直在空轉**，
驗收標準「chart_data 三方一致」在 QA 報告裡會永遠是綠燈，但其實沒檢查過。

Task 1 輸出的 `chart_data` 用的正是你程式碼期待的 `series[i].metric_ids` 格式，
所以只要 B 的 slide_spec 也改成這個鍵名，兩邊就通了。

---

## 共同注意事項

**`value` 可能是 `null`。** 全部 180 個指標中目前有 3 個是 `null`，
每個都在 `validation_note` 附了原因（缺基期、基期為負、該年度無資料）。
這是刻意的：**缺資料時寧可輸出 N/A 也不估算**，請不要在下游補 0 或沿用前期值。

**`display_value` 只能拿來顯示。** 需要再計算時請用 `value` 的原始精度，
拿四捨五入後的顯示值回頭運算會讓誤差層層累積。

**`validation_status` 有四種**：`passed` / `na` / `failed` / `needs_manual_review`。
非 `passed` 的指標建議不要放進簡報結論，或至少加註。
`analysis_result.xlsx` 的 `NeedsReview` 分頁列出了所有這類指標。