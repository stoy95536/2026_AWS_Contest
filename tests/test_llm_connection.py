"""
LLM 連線測試腳本

用途：驗證 Bedrock Claude 是否能正常運作。
前置條件：
  1. 已安裝 boto3: pip install boto3
  2. 已設定 AWS 憑證（環境變數 或 ~/.aws/credentials）
  3. 有 Bedrock Claude 的存取權限

使用方式：
  python tests/test_llm_connection.py

成功時會看到：
  [PASS] Bedrock 連線成功
  [PASS] Planner Agent (LLM) 成功
  [PASS] Analyst Agent (LLM) 成功

失敗時會看到具體錯誤訊息，幫助你排查。
"""

import sys
import os
import json

# 自動載入 .env 檔案中的環境變數
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 載入測試資料
test_file = os.path.join(os.path.dirname(__file__), "test_llm_input.json")
with open(test_file, "r", encoding="utf-8") as f:
    test_data = json.load(f)

data_summary = test_data["data_summary"]
mock_metrics = test_data["mock_metric_data"]
test_slide = test_data["test_slide_spec"]


def test_bedrock_connection():
    """測試 1: Bedrock 基本連線"""
    print("\n[Test 1] Bedrock 基本連線...")
    try:
        import boto3
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        client = boto3.client("bedrock-runtime", region_name=region)

        response = client.converse(
            modelId=os.environ.get("MODEL_ID", "anthropic.claude-sonnet-4-20250514"),
            messages=[{"role": "user", "content": [{"text": "回覆 OK"}]}],
            inferenceConfig={"maxTokens": 10, "temperature": 0},
        )

        reply = response["output"]["message"]["content"][0]["text"]
        print(f"  Claude 回覆: {reply}")
        print("  [PASS] Bedrock 連線成功")
        return True

    except ImportError:
        print("  [FAIL] boto3 未安裝，請執行: pip install boto3")
        return False
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False


def test_planner_llm():
    """測試 2: Planner Agent LLM 模式"""
    print("\n[Test 2] Planner Agent (LLM 模式)...")
    try:
        from src.agents import PlannerAgent

        planner = PlannerAgent()

        # 先測試規則模式（不需要 LLM）
        slides_rule = planner.plan_structure(data_summary, use_llm=False, total_pages=16)
        print(f"  規則模式: {len(slides_rule)} 頁 OK")

        # 測試分類
        classification = planner.classify_data(data_summary)
        print(f"  資料分類: domain={classification['domain']}")

        # 測試 LLM 模式
        slides_llm = planner.plan_structure(data_summary, use_llm=True, total_pages=16)
        print(f"  LLM 模式: {len(slides_llm)} 頁")

        # 驗證格式
        for s in slides_llm:
            assert "slide_no" in s, "缺少 slide_no"
            assert "layout" in s, "缺少 layout"
            assert "title" in s, "缺少 title"

        print("  [PASS] Planner Agent (LLM) 成功")
        return True

    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False


def test_analyst_llm():
    """測試 3: Analyst Agent LLM 模式"""
    print("\n[Test 3] Analyst Agent (LLM 模式)...")
    try:
        from src.agents import AnalystAgent

        analyst = AnalystAgent()

        # 規則模式
        enriched_rule = analyst.generate_insights(test_slide, mock_metrics, use_llm=False)
        print(f"  規則模式: {len(enriched_rule.get('insights', []))} 洞察 OK")

        # LLM 模式
        enriched_llm = analyst.generate_insights(test_slide, mock_metrics, use_llm=True)
        insights = enriched_llm.get("insights", [])
        print(f"  LLM 模式: {len(insights)} 洞察")

        if insights:
            print(f"  洞察範例: {insights[0].get('text', '')[:60]}...")
            assert "evidence_metric_ids" in insights[0], "洞察缺少 evidence_metric_ids"

        print("  [PASS] Analyst Agent (LLM) 成功")
        return True

    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False


def test_full_pipeline_llm():
    """測試 4: 完整 Pipeline (LLM)"""
    print("\n[Test 4] 完整 Pipeline (LLM)...")
    try:
        from src.agents import PlannerAgent, AnalystAgent, ReviewerAgent

        # Step 1: Plan
        planner = PlannerAgent()
        slides = planner.plan_structure(data_summary, use_llm=True, total_pages=16)
        print(f"  Planner: {len(slides)} 頁")

        # Step 2: Analyze (只測第5頁)
        analyst = AnalystAgent()
        enriched = analyst.generate_insights(slides[4], mock_metrics, use_llm=True)
        print(f"  Analyst: headline='{enriched.get('headline', '')[:40]}...'")

        # Step 3: Review
        reviewer = ReviewerAgent()
        # 建立 verified_metrics
        verified = {m["metric_id"]: m["value"] for m in mock_metrics}
        qa = reviewer.review([enriched], verified, use_llm=False)
        print(f"  Reviewer: status={qa['status']}, errors={len(qa['errors'])}")

        print("  [PASS] 完整 Pipeline 成功")
        return True

    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("  LLM Agent 連線測試")
    print("  測試 Bedrock Claude 是否正常運作")
    print("=" * 60)

    results = []

    # Test 1: 基本連線
    results.append(test_bedrock_connection())

    if results[0]:
        # 連線成功才測後面的
        results.append(test_planner_llm())
        results.append(test_analyst_llm())
        results.append(test_full_pipeline_llm())
    else:
        print("\n  Bedrock 連線失敗，跳過後續測試。")
        print("  請確認：")
        print("    1. AWS 憑證已設定（aws configure 或環境變數）")
        print("    2. 有 Bedrock Claude 存取權限")
        print("    3. Region 設定正確（預設 us-east-1）")

    # 總結
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"  結果: {passed}/{total} 通過")

    if all(results):
        print("  LLM Agent 系統準備就緒！")
    print("=" * 60)
