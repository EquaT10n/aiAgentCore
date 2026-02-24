from __future__ import annotations

# 处理 JSON 编解码
import json
# 记录结构化日志
import logging
# 统计函数耗时（高精度计时器）
from time import perf_counter
# 类型标注
from typing import Any
# 生成唯一记录 ID
from uuid import uuid4

# 调用 Bedrock 生成回答
from agent.llm.bedrock import generate_answer
# 把问答内容渲染为 PDF
from agent.pdf.render import render_pdf
# 从环境变量读取运行配置
from agent.settings import Settings
# 写入 DynamoDB 记录
from agent.storage.dynamo import put_record
# 处理 S3 key、上传 PDF、生成预签名 URL
from agent.storage.s3 import build_pdf_s3_key, generate_presigned_pdf_url, upload_pdf

# 当前模块的日志器
LOGGER = logging.getLogger(__name__)
# 请求体里必须出现的字段
REQUIRED_FIELDS = ("prompt", "user_id", "session_id", "locale")


# 将事件里的 body 统一解析成字典
def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    # 读取 body 字段（有些调用可能没有这个字段）
    body = event.get("body")
    # 兼容“直接把 payload 放在顶层”的调用方式
    if body is None:
        return event if isinstance(event, dict) else {}
    # 上游已经是字典时，直接返回
    if isinstance(body, dict):
        return body
    # 字符串时按 JSON 解析
    if isinstance(body, str):
        try:
            return json.loads(body)
        # 非法 JSON 统一返回空字典，交给后续参数校验处理
        except json.JSONDecodeError:
            return {}
    # 其他未知类型按空字典处理
    return {}


# 校验缺失字段，返回缺失字段名列表
def _validate_payload(payload: dict[str, Any]) -> list[str]:
    # 字段不存在、为 None、或为空字符串时都视为缺失
    return [field for field in REQUIRED_FIELDS if payload.get(field) in (None, "")]


# 核心业务流程：生成回答、落库、上传 PDF
def handle_invocation(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    # 记录开始时间用于统计耗时
    start = perf_counter()
    # 每次调用分配唯一记录 ID
    record_id = str(uuid4())
    # 默认状态码先设为 500，成功后再覆盖
    status_code = 500

    try:
        # 先检查必填字段
        missing_fields = _validate_payload(payload)
        if missing_fields:
            # 参数问题返回 400
            status_code = 400
            return status_code, {"error": "missing required fields", "missing": missing_fields}

        # 读取运行配置
        settings = Settings.from_env()
        # 生成 AI 回答
        answer = generate_answer(prompt=payload["prompt"], model_id=settings.model_id)
        # 将问题和回答渲染为 PDF 字节
        pdf_bytes = render_pdf(
            record_id=record_id,
            prompt=payload["prompt"],
            answer=answer,
            user_id=payload["user_id"],
            session_id=payload["session_id"],
            locale=payload["locale"],
        )
        # 生成按年月分层的 S3 对象 key
        pdf_key = build_pdf_s3_key(record_id)
        # 上传 PDF 到 S3
        upload_pdf(
            pdf_bytes=pdf_bytes,
            bucket_name=settings.bucket_name,
            key=pdf_key,
        )
        # 生成临时下载链接给调用方
        pdf_url = generate_presigned_pdf_url(
            bucket_name=settings.bucket_name,
            key=pdf_key,
            expires_in=settings.pdf_url_expires,
        )
        # 将问答结果和 PDF key 写入 DynamoDB
        put_record(
            table_name=settings.table_name,
            record={
                "record_id": record_id,
                "prompt": payload["prompt"],
                "user_id": payload["user_id"],
                "session_id": payload["session_id"],
                "locale": payload["locale"],
                "answer": answer,
                "pdf_s3_key": pdf_key,
            },
        )

        # 业务成功，返回 200 和结果
        status_code = 200
        return status_code, {
            "record_id": record_id,
            "answer": answer,
            "pdf": {"s3_key": pdf_key, "url": pdf_url},
        }
    # 兜底异常：防止内部错误细节泄露给调用方
    except Exception:
        # 记录完整异常堆栈到日志
        LOGGER.exception("failed to process invocation")
        status_code = 500
        # 对外仅返回通用错误信息
        return status_code, {"error": "internal_server_error"}
    # 无论成功失败都记录耗时日志
    finally:
        # 计算毫秒级延迟
        latency_ms = int((perf_counter() - start) * 1000)
        # 输出结构化日志，便于检索和监控
        LOGGER.info(
            json.dumps(
                {"record_id": record_id, "latency_ms": latency_ms, "status_code": status_code},
                # 保留中文字符，避免转义为 \uXXXX
                ensure_ascii=False,
            )
        )


# AgentCore / Lambda 调用入口
def invocations(event: dict[str, Any], context: Any | None = None) -> dict[str, Any]:
    # 当前实现不需要 context，显式删除避免 lint 警告
    del context
    # 解析请求体
    payload = _parse_body(event)
    # 执行核心业务
    status_code, body = handle_invocation(payload)
    # 返回标准 HTTP 风格响应结构
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        # 返回 JSON 字符串，同时保留非 ASCII 字符
        "body": json.dumps(body, ensure_ascii=False),
    }


# 兼容 Lambda 常见入口名
def lambda_handler(event: dict[str, Any], context: Any | None = None) -> dict[str, Any]:
    return invocations(event, context)
