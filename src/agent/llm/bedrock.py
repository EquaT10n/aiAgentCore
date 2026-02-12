from __future__ import annotations

# 类型提示
from typing import Any

# AWS SDK
import boto3


# 从 Bedrock converse 响应中提取第一段文本内容
def _extract_text(response: dict[str, Any]) -> str:
    # 取出标准路径 output.message.content（缺失则回落为空列表）
    contents = response.get("output", {}).get("message", {}).get("content", [])
    # 遍历 content 项，找到首个 text 字段
    for item in contents:
        text = item.get("text")
        if text:
            return text
    # 没有可用文本则抛错，交由上层统一处理
    raise RuntimeError("bedrock response does not contain text")


# 使用 Bedrock Runtime 生成回答
def generate_answer(prompt: str, model_id: str, client: Any | None = None) -> str:
    # 支持注入 client（便于测试），未传则创建默认 boto3 client
    runtime = client or boto3.client("bedrock-runtime")
    # 使用 Converse API 发起一次对话请求
    response = runtime.converse(
        # 指定模型
        modelId=model_id,
        # 按消息格式传入用户 prompt
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )
    # 提取并返回模型文本
    return _extract_text(response)
