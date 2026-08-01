"""Check AWS Bedrock connectivity and available models."""
import os
import sys

# Fix SSL certificate issue on this machine
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["AWS_CA_BUNDLE"] = certifi.where()

from dotenv import load_dotenv
load_dotenv(override=True)

import boto3
from botocore.config import Config

region = os.getenv("AWS_REGION", "us-east-1")
key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
token = os.getenv("AWS_SESSION_TOKEN", "")

print(f"Region: {region}")
print(f"AWS_ACCESS_KEY_ID: {key_id[:12]}... ({len(key_id)} chars)")
print(f"AWS_SECRET_ACCESS_KEY: {'set' if secret else 'NOT SET'} ({len(secret)} chars)")
print(f"AWS_SESSION_TOKEN: {'set' if token else 'NOT SET'} ({len(token)} chars)")

config = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 0})

# Build session explicitly
session = boto3.Session(
    aws_access_key_id=key_id,
    aws_secret_access_key=secret,
    aws_session_token=token if token else None,
    region_name=region,
)

# Use certifi CA bundle for all clients
ca_bundle = certifi.where()
print(f"\nUsing CA bundle: {ca_bundle}")

# Monkey-patch SSL to use certifi
import ssl
ssl_context = ssl.create_default_context(cafile=ca_bundle)

try:
    print("\n[1] Testing STS identity (verify=False for debug)...")
    sts = session.client("sts", config=config, verify=False)
    identity = sts.get_caller_identity()
    print(f"  Account: {identity['Account']}")
    print(f"  ARN: {identity['Arn']}")
    print("  ✓ AWS credentials valid!")
except Exception as e:
    print(f"  ✗ STS Error: {type(e).__name__}: {e}")
    print("  Continuing anyway to test Bedrock...")

try:
    print("\n[2] Listing Bedrock models...")
    client = session.client("bedrock", config=config, verify=False)
    response = client.list_foundation_models(byProvider="Anthropic")
    models = response["modelSummaries"]
    print(f"  Available Anthropic models: {len(models)}")
    for m in models[:10]:
        print(f"    {m['modelId']}")
except Exception as e:
    print(f"  ✗ Bedrock list Error: {type(e).__name__}: {e}")

try:
    print("\n[3] Testing inference (Claude 3 Haiku)...")
    runtime = session.client("bedrock-runtime", config=config, verify=False)
    response = runtime.converse(
        modelId="anthropic.claude-3-haiku-20240307-v1:0",
        messages=[{"role": "user", "content": [{"text": "Say hello in 5 words."}]}],
        inferenceConfig={"maxTokens": 50},
    )
    text = response["output"]["message"]["content"][0]["text"]
    print(f"  Response: {text}")
    print("  ✓ LLM inference works!")
except Exception as e:
    print(f"  ✗ Haiku Error: {type(e).__name__}: {e}")
    try:
        print("\n[4] Trying us-west-2 region...")
        runtime2 = boto3.client("bedrock-runtime", region_name="us-west-2",
                                aws_access_key_id=key_id, aws_secret_access_key=secret,
                                aws_session_token=token if token else None, config=config,
                                verify=False)
        response = runtime2.converse(
            modelId="anthropic.claude-3-haiku-20240307-v1:0",
            messages=[{"role": "user", "content": [{"text": "Say hi"}]}],
            inferenceConfig={"maxTokens": 20},
        )
        text = response["output"]["message"]["content"][0]["text"]
        print(f"  Response: {text}")
        print("  ✓ Works in us-west-2!")
    except Exception as e2:
        print(f"  ✗ us-west-2 Error: {type(e2).__name__}: {e2}")
