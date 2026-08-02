"""
LLM 規劃器（TASK1.md Stage 2 步驟 1~4）：把自然語言 Prompt 翻譯成積木配方。

**這是整個系統裡 LLM 唯一出現的位置。** 它的職責只有語意判斷——
「整年度市占率」的分母該用官方總計欄還是自行加總明細、期間取哪一年、
哪個欄位對應使用者說的「日本」。這些是業務判斷，規則式程式做不好。

它**不做**的事（鐵律 2、4、12）：
  不做算術            —— LLM 是預測不是計算，加總會給出合理但錯誤的數字
  不讀原始 Excel      —— 只讀精簡 Catalog，11 份塞進 context 會爆且必然失真
  不生成 pandas 程式碼 —— 語法會對、業務定義會錯，而且錯得很有自信
  不填 value/source/validation_status —— 只要有一個由 LLM 生成，
                        「LLM 不碰數字」這道防線就整個破功

輸出的配方裡沒有任何計算結果，只有積木名、欄位名與期間。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from .blocks import BLOCK_REGISTRY
from .dataset import Dataset
from .executor import MetricRecipe

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
DEFAULT_REGION = "us-west-2"

MAX_CATALOG_FIELDS = 220
"""餵進 LLM 的欄位卡上限。

實測 11 份共 193 個欄位、壓縮後約 15 KB，完全在 context 預算內。
留一點餘裕給決賽可能更多的欄位；真的超過就依量級截斷，
並在 prompt 裡明說「已截斷」，不要讓 LLM 以為看到的是全部。"""

SAMPLE_VALUES_PER_FIELD = 2
"""每個欄位給幾個樣本值。

給樣本是為了讓 LLM 判斷語意（看到 22733、40424 就知道是人次不是比率），
但**不能給多**——Catalog 是「一欄一張卡」不是「一格一張卡」，
給整欄資料等於讓 LLM 有機會直接抄數字，那就破功了。"""

TEMPERATURE = 0.0
"""驗收標準要求「同一 Prompt 重跑結果一致」，故一律 0。"""

MAX_TOKENS = 8192

TOOL_NAME = "emit_metric_plan"


class LLMPlannerError(Exception):
    """LLM 規劃失敗。訊息會被上層轉成規則式後備的理由。"""


# --------------------------------------------------------------------------
# Catalog 壓縮
# --------------------------------------------------------------------------

def compact_catalog(dataset: Dataset, limit: int = MAX_CATALOG_FIELDS) -> str:
    """
    把 Catalog 壓成一行一欄的純文字，餵給 LLM。

    完整的 data_catalog.json 有 118 KB，塞進每次提問既慢又貴，而且大部分
    內容（信心分數、表頭列號、指紋）對「決定要算什麼」毫無幫助。

    保留的四項都有明確用途：
      unit              讓 LLM 不會把人次欄和百分比欄拿去相除
      aggregation_role  讓它知道哪些是小計，避免叫積木把明細與彙總混算
      file              同名欄位橫跨多檔時，它必須指定是哪一份
      樣本值            判斷語意用（看到 22733 就知道是人次不是比率）
    """
    rows = []
    for canonical, meta in list(dataset.fields.items())[:limit]:
        samples = (
            dataset.frame.loc[
                dataset.frame["canonical"] == canonical, "value"
            ]
            .dropna()
            .head(SAMPLE_VALUES_PER_FIELD)
            .tolist()
        )
        sample_text = ", ".join(f"{v:,.6g}" for v in samples) or "無"
        rows.append(
            f"{canonical} | {meta.unit} | {meta.aggregation_role} | "
            f"{meta.file_name} | 樣本 {sample_text}"
        )

    header = (
        "欄位清單（canonical_name | 單位 | 角色 | 來源檔案 | 樣本值）\n"
        "角色說明：detail=明細、subtotal=小計、total=總計、residual=其他/未列明\n"
    )
    if len(dataset.fields) > limit:
        header += f"（欄位過多，已截斷為前 {limit} 個，共 {len(dataset.fields)} 個）\n"
    return header + "\n".join(rows)


def describe_periods(dataset: Dataset) -> str:
    periods = dataset.periods()
    if not periods:
        return "無可用期間"
    return f"可用年度：{periods[0]}～{periods[-1]}（共 {len(periods)} 個）"


# --------------------------------------------------------------------------
# Tool schema：結構上就讓 LLM 點不到白名單以外的東西
# --------------------------------------------------------------------------

def build_tool_config() -> dict[str, Any]:
    """
    Bedrock Converse API 的 toolConfig。

    `block` 欄位用 enum 鎖死 10 個積木名——這是鐵律 12 要求的
    「LLM 端用 structured output 約束只能點白名單積木」。
    欄位名無法用 enum（近 200 個會讓 schema 爆掉），改由執行引擎驗證，
    失敗時透過重試把錯誤訊息回饋給 LLM。
    """
    step_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "此步驟的識別碼，供後續步驟引用"},
            "block": {
                "type": "string",
                "enum": sorted(BLOCK_REGISTRY),
                "description": "白名單積木名稱，只能是列舉中的值",
            },
            "input": {
                "type": "string",
                "description": "上一步的 id，或 'dataset' 表示原始長表。"
                               "ratio 與 growth_rate 不需要此欄位",
            },
            "params": {
                "type": "object",
                "description": "積木參數。引用前一步的結果用 {\"$ref\": \"步驟id\"}",
            },
        },
        "required": ["id", "block"],
    }

    recipe_schema = {
        "type": "object",
        "properties": {
            "metric_id": {"type": "string", "description": "英數與底線，全份唯一"},
            "metric_name": {"type": "string", "description": "給人看的中文指標名"},
            "unit": {"type": "string", "description": "人次／美元／%／夜等"},
            "period": {"type": "string", "description": "期間，如 '2024'"},
            "is_share": {
                "type": "boolean",
                "description": "是否為占比類（占比才套用 0～100% 的上界檢查）",
            },
            "assumption_statement": {
                "type": "string",
                "description": "一句話說明你對業務定義的理解，例如分母怎麼界定、"
                               "期間怎麼取。這會存進資料血緣供人事後核對，必填",
            },
            "steps": {"type": "array", "items": step_schema},
            "output": {"type": "string", "description": "取哪一步的結果作為最終值"},
        },
        "required": [
            "metric_id", "metric_name", "unit", "period",
            "assumption_statement", "steps", "output",
        ],
    }

    chart_schema = {
        "type": "object",
        "properties": {
            "chart_id": {"type": "string"},
            "chart_type": {"type": "string", "enum": ["line", "bar", "pie", "scatter"]},
            "title": {"type": "string"},
            "unit": {"type": "string"},
            "categories": {
                "type": "array", "items": {"type": "string"},
                "description": "x 軸標籤，長度須與每個系列的 metric_ids 相同",
            },
            "series": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "metric_ids": {
                            "type": "array", "items": {"type": "string"},
                            "description": "引用上面定義過的 metric_id，"
                                           "順序須與 categories 對應",
                        },
                    },
                    "required": ["name", "metric_ids"],
                },
            },
        },
        "required": ["chart_id", "chart_type", "title", "categories", "series"],
    }

    return {
        "tools": [{
            "toolSpec": {
                "name": TOOL_NAME,
                "description": "輸出計算計畫。只描述要呼叫哪些積木、用哪些欄位，"
                               "不要填入任何計算結果——數值由程式執行積木後產生。",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "metrics": {"type": "array", "items": recipe_schema},
                            "charts": {"type": "array", "items": chart_schema},
                        },
                        "required": ["metrics"],
                    }
                },
            }
        }],
        "toolChoice": {"tool": {"name": TOOL_NAME}},
    }


SYSTEM_PROMPT = """你是資料分析規劃器。你的職責是把使用者的問題翻譯成「積木調用計畫」。

## 絕對禁止
- 不要自己計算任何數字。你輸出的計畫裡不能出現任何計算結果。
- 不要使用欄位清單以外的 canonical_name。捏造欄位會讓整個計畫被拒絕。
- 不要憑印象填數值。所有數字都由程式執行積木後從原始 Excel 讀取。

## 可用積木
- filter(column, operator, value)：篩選。column 只能是 'file'、'canonical'、'period'、'aggregation_role'
- filter_by_period(start, end)：依年度區間篩選，含頭含尾
- group_sum(group_col, value_col, detail_only)：分組加總
- group_mean(group_col, value_col, detail_only)：分組平均
- rank_top_n(value_col, n, ascending)：取前 N 名
- pivot(index, columns, values)：長表轉寬表
- join(data_a, data_b, on, how)：跨檔關聯
- cumulative_sum(value_col, order_by)：累計加總
- ratio(numerator, denominator, as_percent)：比率。分母為 0 會回傳 N/A
- growth_rate(current, previous)：成長率。缺基期會回傳 N/A

## 必須遵守的規則

1. **一定要先用 filter 指定 file**。同一個 canonical 欄位常同時存在於多份檔案
   （例如「日本」同時出現在按居住地與按國籍兩份），不指定會把同一批對象重複
   計算，而且在比率中分子分母會同時加倍互相抵銷，看起來完全正常但絕對值是錯的。

2. **每個配方最終必須收斂成「1 列 1 值」才能當指標**。資料是長表結構：每列
   有 (file, canonical, period, value)。如果你要 2024 年某欄位的值，正確的
   步驟順序是：
     filter(file) → filter(canonical) → filter_by_period(2024, 2024)
   如此會剩下剛好 1 列。若你漏了 filter(canonical)，就會剩下該檔案所有欄位
   × 1 年 = 幾十列，積木會報錯「產生 N 列，無法當成單一數值使用」。

3. **要做趨勢指標（多年值做一張折線圖）時**，為每一年做一個獨立的 metric，
   而不是試圖讓一個 metric 回傳整條趨勢。例如「2020~2024 歷年旅客人次」
   應該拆成 5 個配方（visitors_2020, visitors_2021, ..., visitors_2024），
   然後在 charts 的 series.metric_ids 引用這 5 個 id。

4. **收斂成單一數值才能餵給 ratio 或 growth_rate**。用 filter(file) →
   filter(canonical) → filter_by_period(year, year) 這個順序，最後會得到
   一列。如果仍需加總（例如合併多個明細欄），再加一步
   group_sum(group_col='period', detail_only=false)。

5. **注意 aggregation_role**。要加總明細時不要把 subtotal 或 total 欄一起算進去。
   若你已經用 canonical 鎖定單一欄位，請設 detail_only=false，否則該欄若本身是
   總計欄會被濾光。

6. **比率的分母優先用報表既有的 total 欄**，而不是自行加總明細——這樣數字能與
   報表原文對得起來，評審可以直接核對。並在 assumption_statement 說明你的選擇。

7. **assumption_statement 必填**，用一句話寫清楚分子分母怎麼界定、期間怎麼取。
   遇到語意模糊時不要停下來問，直接寫下你的假設繼續——這會存進資料血緣供人事後
   核對。

8. **步驟間引用**用 {"$ref": "步驟id"}，例如
   ratio 的 params: {"numerator": {"$ref": "num_s"}, "denominator": {"$ref": "den_s"}}

9. **每個配方產出一個數字**。不要試圖在一個配方裡產出多筆資料。如果提問要求
   「前 5 名國家的市占率」，就做 5 個配方，每個配方只算一個國家。

## 配方範例

### 範例 1：2024 年日本旅客占比（單一值）

steps:
  {"id":"f1","block":"filter","input":"dataset","params":{"column":"file","operator":"==","value":"歷年來臺旅客按目的分.xlsx"}}
  {"id":"f2","block":"filter","input":"f1","params":{"column":"canonical","operator":"==","value":"來臺旅客_亞洲地區_日本"}}
  {"id":"f3","block":"filter_by_period","input":"f2","params":{"start":2024,"end":2024}}
  {"id":"den_f","block":"filter","input":"dataset","params":{"column":"file","operator":"==","value":"歷年來臺旅客按目的分.xlsx"}}
  {"id":"den_c","block":"filter","input":"den_f","params":{"column":"canonical","operator":"==","value":"來臺旅客_合計"}}
  {"id":"den_y","block":"filter_by_period","input":"den_c","params":{"start":2024,"end":2024}}
  {"id":"r","block":"ratio","params":{"numerator":{"$ref":"f3"},"denominator":{"$ref":"den_y"},"as_percent":true}}
output: "r"

### 範例 2：趨勢圖（多年值拆成多個 metric）

如果要做 2020~2024 年歷年旅客人次趨勢圖，定義 5 個 metric：
  metric_id: "visitors_2020", steps: [filter(file), filter(canonical="合計"), filter_by_period(2020,2020)], output 最後的 filter 步驟
  metric_id: "visitors_2021", ...（同上改年份）
  ...
然後 charts: [{"chart_id":"trend_visitors","chart_type":"line","title":"歷年來臺旅客","categories":["2020","2021","2022","2023","2024"],"series":[{"name":"旅客人次","metric_ids":["visitors_2020","visitors_2021","visitors_2022","visitors_2023","visitors_2024"]}]}]

## 圖表
若使用者的問題適合用圖呈現，在 charts 裡定義，series 的 metric_ids 必須引用你在
metrics 裡定義過的 metric_id，且順序與 categories 對應。圖表資料由程式從 metric
查表產生，你不需要（也不可以）填數值。
"""


@dataclass
class PlanResult:
    """LLM 規劃的產出。"""

    recipes: list[MetricRecipe] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMPlanner:
    """透過 Bedrock Converse + Function Calling 產生積木配方。"""

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
    ):
        # 與組員的 Agent 走同一組環境變數，決賽當天換發憑證只需改 .env 一處
        self.model_id = model_id or os.getenv("MODEL_ID") or DEFAULT_MODEL_ID
        self.region = (
            region
            or os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or DEFAULT_REGION
        )
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def plan(
        self,
        prompt: str,
        dataset: Dataset,
        feedback: str | None = None,
    ) -> PlanResult:
        """
        依使用者 Prompt 產生配方。

        Args:
            feedback: 上一輪的失敗原因。非 None 時附在訊息裡，讓 LLM 知道
                      哪裡出錯——這是 Sanity Check 重試機制的 LLM 端。
        """
        user_message = self._build_message(prompt, dataset, feedback)

        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": user_message}]}],
                toolConfig=build_tool_config(),
                inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE},
            )
        except Exception as e:
            raise LLMPlannerError(f"Bedrock 呼叫失敗：{type(e).__name__}: {e}") from e

        return self._parse(response)

    @staticmethod
    def _build_message(prompt: str, dataset: Dataset, feedback: str | None) -> str:
        parts = [
            f"## 使用者問題\n{prompt}",
            f"\n## 資料概況\n{describe_periods(dataset)}\n"
            f"共 {len(dataset.fields)} 個欄位、{len(dataset.frame):,} 筆記錄",
            f"\n## 可用欄位\n{compact_catalog(dataset)}",
        ]
        if feedback:
            parts.append(
                f"\n## 上一次的計畫執行失敗\n{feedback}\n"
                "請針對這個錯誤修正後重新輸出完整計畫。"
            )
        return "\n".join(parts)

    @staticmethod
    def _parse(response: dict[str, Any]) -> PlanResult:
        """從 Converse 回應取出 tool use 的內容。"""
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        payload = next(
            (b["toolUse"]["input"] for b in blocks if "toolUse" in b), None
        )
        if payload is None:
            text = " ".join(b.get("text", "") for b in blocks)[:300]
            raise LLMPlannerError(
                f"LLM 未呼叫工具，無法取得計畫。回應片段：{text}"
            )

        metrics = payload.get("metrics") or []
        if not metrics:
            raise LLMPlannerError("LLM 回傳的計畫沒有任何指標")

        recipes = []
        for item in metrics:
            # LLM 偶爾會回傳非 dict 的元素（例如字串），直接跳過
            if not isinstance(item, dict):
                continue
            try:
                recipes.append(MetricRecipe.from_dict(item))
            except Exception as e:
                # 單一配方格式錯誤不該讓整批作廢，記錄後繼續
                mid = item.get("metric_id", "?") if isinstance(item, dict) else "?"
                print(f"    [skip] 配方 '{mid}' 格式錯誤：{e}")
                continue

        return PlanResult(
            recipes=recipes,
            charts=payload.get("charts") or [],
            raw=payload,
        )


def plan_with_llm(
    prompt: str,
    dataset: Dataset,
    model_id: str | None = None,
    region: str | None = None,
) -> PlanResult:
    """便利函式：一次性規劃。失敗時拋 LLMPlannerError，由呼叫方決定是否走後備。"""
    return LLMPlanner(model_id=model_id, region=region).plan(prompt, dataset)