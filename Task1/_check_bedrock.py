"""
Task1 前置檢查：驗證 AWS Bedrock 連線、可用模型與 reasoning 設定。

決賽當天憑證換發後，重跑此腳本即可確認環境是否就緒。

檢查項目：
  1. .env 載入與 region fallback (AWS_REGION -> AWS_DEFAULT_REGION -> us-west-2)
  2. STS 憑證有效性（臨時憑證是否過期）
  3. .env 指定的 MODEL_ID 是否可呼叫
  4. reasoning 設定 (effort 或 thinking budget_tokens) 是否生效
  5. 失敗時列出本帳號實際可用的 Anthropic 模型

執行：
    .venv\\Scripts\\python.exe Task1\\_check_bedrock.py
    .venv\\Scripts\\python.exe Task1\\_check_bedrock.py --list-all   # 完整掃描所有模型
"""

import os
import sys
from pathlib import Path

import certifi

# 修正本機 SSL 憑證路徑（使用正規 CA bundle，不停用憑證驗證）
_CA = certifi.where()
os.environ.setdefault("SSL_CERT_FILE", _CA)
os.environ.setdefault("REQUESTS_CA_BUNDLE", _CA)
os.environ.setdefault("AWS_CA_BUNDLE", _CA)

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
load_dotenv(ENV_PATH, override=True)

import boto3
from botocore.config import Config

SEP = "=" * 70


def resolve_region() -> str:
    """Region fallback：AWS_REGION -> AWS_DEFAULT_REGION -> us-west-2。"""
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"


def mask(value: str) -> str:
    """僅顯示長度與前綴，不外洩憑證內容。"""
    if not value:
        return "NOT SET"
    return f"set ({len(value)} chars, prefix={value[:4]}...)"


def build_reasoning_fields() -> tuple[dict | None, str]:
    """
    依 .env 組出 additionalModelRequestFields。

    Returns:
        (additional_fields 或 None, 說明文字)
    """
    mode = os.getenv("REASONING_MODE", "").strip().lower()

    if mode == "thinking_budget":
        budget = int(os.getenv("THINKING_BUDGET_TOKENS", "4096"))
        return (
            {"thinking": {"type": "enabled", "budget_tokens": budget}},
            f"thinking budget_tokens={budget}",
        )

    effort = os.getenv("REASONING_EFFORT", "").strip().lower()
    if effort:
        return {"effort": effort}, f"effort={effort}"

    return None, "未啟用 reasoning"


def probe_available_models(session, cfg) -> list[str]:
    """實測本帳號真正可呼叫的 Anthropic 模型（清單有不代表有權限）。"""
    runtime = session.client("bedrock-runtime", config=cfg)
    ids: list[str] = []
    try:
        bedrock = session.client("bedrock", config=cfg)
        for p in bedrock.list_inference_profiles(maxResults=100).get(
            "inferenceProfileSummaries", []
        ):
            pid = p.get("inferenceProfileId", "")
            if "anthropic" in pid.lower():
                ids.append(pid)
    except Exception as e:
        print(f"  無法列出 inference profiles: {type(e).__name__}")
        return []

    usable = []
    for mid in ids:
        try:
            runtime.converse(
                modelId=mid,
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                inferenceConfig={"maxTokens": 8},
            )
            usable.append(mid)
            print(f"  OK   {mid}")
        except Exception as e:
            code = type(e).__name__
            short = "AccessDenied" if "AccessDenied" in code else code
            print(f"  --   {mid}  [{short}]")
    return usable


def main() -> int:
    list_all = "--list-all" in sys.argv

    region = resolve_region()
    model_id = os.getenv("MODEL_ID", "global.anthropic.claude-opus-4-6-v1")
    fallback_id = os.getenv("FALLBACK_MODEL_ID", "")
    reasoning_fields, reasoning_desc = build_reasoning_fields()

    print(SEP)
    print("[0] 環境設定")
    print(SEP)
    print(f"  .env 路徑          : {ENV_PATH}")
    print(f"  .env 存在          : {ENV_PATH.exists()}")
    print(f"  AWS_REGION         : {os.getenv('AWS_REGION') or '(未設)'}")
    print(f"  AWS_DEFAULT_REGION : {os.getenv('AWS_DEFAULT_REGION') or '(未設)'}")
    print(f"  -> 解析後 region   : {region}")
    print(f"  MODEL_ID           : {model_id}")
    print(f"  FALLBACK_MODEL_ID  : {fallback_id or '(未設)'}")
    print(f"  reasoning          : {reasoning_desc}")
    print(f"  ACCESS_KEY_ID      : {mask(os.getenv('AWS_ACCESS_KEY_ID', ''))}")
    print(f"  SECRET_ACCESS_KEY  : {mask(os.getenv('AWS_SECRET_ACCESS_KEY', ''))}")
    print(f"  SESSION_TOKEN      : {mask(os.getenv('AWS_SESSION_TOKEN', ''))}")

    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN") or None,
        region_name=region,
    )
    # retries=2 以吸收偶發的 ConnectionClosedError
    cfg = Config(connect_timeout=10, read_timeout=120, retries={"max_attempts": 3})

    # --- 1. STS 憑證 ---
    print()
    print(SEP)
    print("[1] STS 憑證有效性")
    print(SEP)
    try:
        ident = session.client("sts", config=cfg).get_caller_identity()
        print(f"  OK   Account : {ident['Account']}")
        print(f"  OK   ARN     : {ident['Arn']}")
    except Exception as e:
        print(f"  FAIL {type(e).__name__}: {str(e)[:180]}")
        print("  -> STS 臨時憑證可能已過期，需重新換發後再試。")
        return 1

    runtime = session.client("bedrock-runtime", config=cfg)
    # Bedrock 要求 maxTokens > thinking.budget_tokens，故預留 1024 tokens 輸出空間
    budget = int(os.getenv("THINKING_BUDGET_TOKENS", "4096"))
    max_tokens = budget + 1024 if reasoning_fields else 256
    probe = {
        "messages": [{"role": "user", "content": [{"text": "12345 乘以 6789 等於多少？只回答數字。"}]}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }

    # --- 2. MODEL_ID 基本推論 ---
    print()
    print(SEP)
    print(f"[2] 基本推論：{model_id}")
    print(SEP)
    basic_ok = False
    try:
        r = runtime.converse(modelId=model_id, **probe)
        text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
        usage = r.get("usage", {})
        print(f"  OK   回答  : {text.strip()[:60]}")
        print(f"  OK   tokens: in={usage.get('inputTokens')} out={usage.get('outputTokens')}")
        basic_ok = True
    except Exception as e:
        print(f"  FAIL {type(e).__name__}: {str(e)[:180]}")

    # --- 3. reasoning 設定 ---
    print()
    print(SEP)
    print(f"[3] reasoning 設定：{reasoning_desc}")
    print(SEP)
    reasoning_ok = False
    if not basic_ok:
        print("  SKIP 基本推論未通過。")
    elif reasoning_fields is None:
        print("  SKIP 未啟用 reasoning。")
    else:
        try:
            r = runtime.converse(
                modelId=model_id, **probe, additionalModelRequestFields=reasoning_fields
            )
            blocks = r["output"]["message"]["content"]
            kinds = [list(b.keys())[0] for b in blocks]
            text = "".join(b.get("text", "") for b in blocks)
            usage = r.get("usage", {})
            print(f"  OK   content 區塊 : {kinds}")
            print(f"  OK   回答         : {text.strip()[:60]}")
            print(f"  OK   tokens       : in={usage.get('inputTokens')} out={usage.get('outputTokens')}")
            if any("reasoning" in k.lower() for k in kinds):
                print("  OK   reasoning 已生效（回傳 reasoningContent 區塊）")
            else:
                print("  WARN 無 reasoningContent 區塊，reasoning 可能未實際啟用")
            reasoning_ok = True
        except Exception as e:
            print(f"  FAIL {type(e).__name__}: {str(e)[:180]}")

    # --- 4. 可用模型掃描 ---
    if not basic_ok or list_all:
        print()
        print(SEP)
        print("[4] 本帳號實際可用的 Anthropic 模型（實測 converse）")
        print(SEP)
        usable = probe_available_models(session, cfg)
        print()
        print(f"  共 {len(usable)} 個可用")

    print()
    print(SEP)
    print("結論")
    print(SEP)
    print(f"  憑證       : OK")
    print(f"  模型       : {'OK' if basic_ok else 'FAIL'}  {model_id} @ {region}")
    print(f"  reasoning  : {'OK' if reasoning_ok else 'FAIL/SKIP'}  {reasoning_desc}")
    return 0 if (basic_ok and reasoning_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
