"""Check AWS permissions - show actual error details."""
import os
from dotenv import load_dotenv
load_dotenv(override=True)
import boto3
import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

region = "us-east-1"
session = boto3.Session(region_name=region)

checks = [
    ("STS", lambda: session.client("sts", verify=False).get_caller_identity()),
    ("S3", lambda: session.client("s3", verify=False).list_buckets()),
    ("EC2", lambda: session.client("ec2", verify=False).describe_instances(MaxResults=5)),
    ("Lambda", lambda: session.client("lambda", verify=False).list_functions(MaxItems=1)),
    ("ECR", lambda: session.client("ecr", verify=False).describe_repositories(maxResults=1)),
    ("App Runner", lambda: session.client("apprunner", verify=False).list_services()),
    ("ECS", lambda: session.client("ecs", verify=False).list_clusters(maxResults=1)),
    ("Bedrock", lambda: session.client("bedrock", verify=False).list_foundation_models(byProvider="Anthropic")),
    ("S3 create bucket", lambda: session.client("s3", verify=False).head_bucket(Bucket="test-permission-check-xxxxx")),
    ("Lightsail", lambda: session.client("lightsail", verify=False).get_instances()),
]

print("AWS Workshop 權限檢查 (詳細)")
print("=" * 60)
for name, fn in checks:
    try:
        result = fn()
        print(f"  ✓ {name} — 成功")
    except Exception as e:
        err_code = ""
        err_msg = str(e)
        if hasattr(e, "response"):
            err_code = e.response.get("Error", {}).get("Code", "")
            err_msg = e.response.get("Error", {}).get("Message", str(e))

        if err_code in ("AccessDenied", "UnauthorizedOperation", "AccessDeniedException"):
            print(f"  ✗ {name} — 無權限 ({err_code})")
        elif err_code in ("NoSuchBucket", "RepositoryNotFoundException", "ResourceNotFoundException"):
            print(f"  ✓ {name} — 有權限（資源不存在而已）")
        elif err_code == "ExpiredTokenException":
            print(f"  ✗ {name} — Token 過期！需要重新取得 credentials")
            break
        else:
            print(f"  ? {name} — {err_code}: {err_msg[:80]}")
print("=" * 60)
