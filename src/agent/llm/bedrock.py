from __future__ import annotations

# 类型标注
from typing import Any

# AWS SDK
import boto3


# 从 Bedrock Converse 响应中提取第一段文本
def _extract_text(response: dict[str, Any]) -> str:
    # 标准路径是 output.message.content（拿不到时回退为空列表）
    contents = response.get("output", {}).get("message", {}).get("content", [])
    # 遍历内容块，找到第一个 text 字段
    for item in contents:
        text = item.get("text")
        if text:
            return text
    # 没拿到文本时抛错，交给上层统一处理
    raise RuntimeError("bedrock response does not contain text")


# 调用 Bedrock Runtime 生成回答
def generate_answer(prompt: str, model_id: str, client: Any | None = None) -> str:
    # 支持注入 client（便于测试）；未传时创建真实 client
    runtime = client or boto3.client("bedrock-runtime")
    # 使用 Converse API 发起一次单轮对话
    response = runtime.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )
    return _extract_text(response)
