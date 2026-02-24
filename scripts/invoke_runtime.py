from __future__ import annotations

# 解析命令行参数
import argparse

# 处理 JSON 负载与响应
import json

# 用于默认 session_id（时间戳）
import time

# 类型标注
from typing import Any

# AWS SDK
import boto3


# 定义命令行参数
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Invoke Bedrock AgentCore runtime endpoint."
    )
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--stack-name", default="InfraStack")
    parser.add_argument("--runtime-arn", default=None)
    parser.add_argument("--qualifier", default=None)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--session-id", default=f"local-{int(time.time())}")
    parser.add_argument("--locale", default="zh-CN")
    return parser.parse_args()


# 解析调用目标（优先用命令行传入，否则读 CloudFormation 输出）
def resolve_runtime_target(
    region: str,
    stack_name: str,
    runtime_arn: str | None,
    qualifier: str | None,
) -> tuple[str, str]:
    # 如果两个关键参数都已提供，直接使用
    if runtime_arn and qualifier:
        return runtime_arn, qualifier

    cfn = boto3.client("cloudformation", region_name=region)
    stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
    outputs = stacks[0].get("Outputs", [])
    output_map = {o["OutputKey"]: o["OutputValue"] for o in outputs}

    resolved_runtime_arn = runtime_arn or output_map.get("AgentRuntimeArn")
    resolved_qualifier = qualifier or output_map.get("AgentRuntimeEndpointName")

    if not resolved_runtime_arn or not resolved_qualifier:
        raise RuntimeError(
            "Cannot resolve runtime target. Pass --runtime-arn and --qualifier, "
            "or ensure stack outputs include AgentRuntimeArn/AgentRuntimeEndpointName."
        )
    return resolved_runtime_arn, resolved_qualifier


# 兼容 Bedrock 可能返回的多种 response 结构
def decode_response_blob(blob: Any) -> dict[str, Any]:
    if isinstance(blob, (bytes, bytearray)):
        return json.loads(bytes(blob).decode("utf-8"))
    if hasattr(blob, "read"):
        return json.loads(blob.read().decode("utf-8"))
    if isinstance(blob, str):
        return json.loads(blob)
    if hasattr(blob, "__iter__"):
        chunks: list[bytes] = []
        for event in blob:
            chunk = event.get("chunk") if isinstance(event, dict) else None
            if isinstance(chunk, dict) and "bytes" in chunk:
                chunks.append(chunk["bytes"])
        if chunks:
            return json.loads(b"".join(chunks).decode("utf-8"))
    raise TypeError(f"Unsupported response payload type: {type(blob)!r}")


# 脚本主流程：调用 runtime 并打印返回
def main() -> int:
    args = parse_args()

    runtime_arn, qualifier = resolve_runtime_target(
        region=args.region,
        stack_name=args.stack_name,
        runtime_arn=args.runtime_arn,
        qualifier=args.qualifier,
    )

    payload = {
        "prompt": args.prompt,
        "user_id": args.user_id,
        "session_id": args.session_id,
        "locale": args.locale,
    }

    client = boto3.client("bedrock-agentcore", region_name=args.region)
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier=qualifier,
        payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        contentType="application/json",
    )
    response_json = decode_response_blob(resp.get("response"))

    print("Runtime ARN:", runtime_arn)
    print("Qualifier:", qualifier)
    print(json.dumps(response_json, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
