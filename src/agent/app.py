"""AgentCore 调用入口模块。

本模块负责：
1) 解析并校验调用请求。
2) 通过 LLM 路由器选择工具并执行。
3) 执行业务主链路（回答 -> PDF -> S3 -> DynamoDB）。
4) 返回兼容 AgentCore/Lambda 的 HTTP 风格响应。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any
from uuid import uuid4

from agent.llm.bedrock import generate_answer
from agent.pdf.render import render_pdf
from agent.settings import Settings
from agent.storage.dynamo import put_record
from agent.storage.s3 import build_pdf_s3_key, generate_presigned_pdf_url, upload_pdf

# 结构化日志记录器，用于观测时延与异常。
LOGGER = logging.getLogger(__name__)

# 请求体必填字段。
REQUIRED_FIELDS = ("prompt", "user_id", "session_id", "locale")

# 路由最大步数上限，防止无限循环和额外成本。
MAX_ROUTER_STEPS = 3

# 工具函数统一签名。
ToolHandler = Callable[[dict[str, Any], Settings], str]


# 工具：基于原始 prompt 直接生成回答。
def _tool_direct_answer(tool_input: dict[str, Any], settings: Settings) -> str:
    return generate_answer(prompt=str(tool_input.get("prompt", "")), model_id=settings.model_id)


# 工具：将原始 prompt 生成精简要点总结。
def _tool_bullet_summary(tool_input: dict[str, Any], settings: Settings) -> str:
    prompt = str(tool_input.get("prompt", ""))
    summary_prompt = (
        "Summarize the user request in concise bullet points.\n"
        "Keep it factual and short.\n\n"
        f"User request:\n{prompt}"
    )
    return generate_answer(prompt=summary_prompt, model_id=settings.model_id)


# 工具注册表：统一维护可用工具、输入约束和处理函数。
TOOLS: dict[str, dict[str, Any]] = {
    "direct_answer": {
        "description": "Return a direct answer to the user prompt.",
        "required": {"prompt": str},
        "handler": _tool_direct_answer,
    },
    "bullet_summary": {
        "description": "Return concise bullet summary for the user prompt.",
        "required": {"prompt": str},
        "handler": _tool_bullet_summary,
    },
}


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """将调用事件统一归一化为 dict。"""
    body = event.get("body")
    if body is None:
        return event if isinstance(event, dict) else {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return {}


def _validate_payload(payload: dict[str, Any]) -> list[str]:
    """返回缺失的必填字段；空字符串和 None 都视为缺失。"""
    return [field for field in REQUIRED_FIELDS if payload.get(field) in (None, "")]


def _validate_tool_input(tool_name: str, tool_input: Any) -> list[str]:
    """按工具注册表定义的 schema 校验输入，返回错误列表。"""
    if tool_name not in TOOLS:
        return [f"unknown tool: {tool_name}"]
    if not isinstance(tool_input, dict):
        return ["tool_input must be an object"]

    errors: list[str] = []
    required = TOOLS[tool_name]["required"]
    for field, expected_type in required.items():
        if field not in tool_input:
            errors.append(f"missing field: {field}")
            continue
        if not isinstance(tool_input[field], expected_type):
            errors.append(f"field {field} must be {expected_type.__name__}")
    return errors


def _build_router_prompt(user_prompt: str, scratchpad: list[dict[str, Any]]) -> str:
    """构造严格路由提示词，要求模型仅返回 JSON。"""
    tools_desc = [
        {
            "tool": name,
            "description": spec["description"],
            "required": list(spec["required"].keys()),
        }
        for name, spec in TOOLS.items()
    ]
    return (
        "You are a strict tool router.\n"
        "Decide the next action for this request.\n"
        "Return JSON only, no markdown.\n"
        "Allowed JSON formats:\n"
        "1) {\"action\":\"call_tool\",\"tool\":\"<name>\",\"tool_input\":{...}}\n"
        "2) {\"action\":\"final\",\"answer\":\"...\"}\n"
        "Prefer using at most one tool call unless a follow-up tool is necessary.\n\n"
        f"Available tools:\n{json.dumps(tools_desc, ensure_ascii=False)}\n\n"
        f"Scratchpad (previous tool outputs):\n{json.dumps(scratchpad, ensure_ascii=False)}\n\n"
        f"User prompt:\n{user_prompt}"
    )


def _route_once(
    user_prompt: str,
    settings: Settings,
    scratchpad: list[dict[str, Any]],
) -> dict[str, Any]:
    """执行一次 LLM 路由并归一化输出。"""
    router_prompt = _build_router_prompt(user_prompt=user_prompt, scratchpad=scratchpad)
    router_raw = generate_answer(prompt=router_prompt, model_id=settings.model_id)
    try:
        decision = json.loads(router_raw)
    except json.JSONDecodeError:
        return {
            "action": "call_tool",
            "tool": "direct_answer",
            "tool_input": {"prompt": user_prompt},
            "fallback_reason": "router_output_not_json",
        }

    action = str(decision.get("action", "")).strip()
    if action == "final" and isinstance(decision.get("answer"), str):
        return {"action": "final", "answer": decision["answer"]}

    tool = str(decision.get("tool", "")).strip()
    tool_input = decision.get("tool_input", {})
    if isinstance(tool_input, dict) and "prompt" not in tool_input:
        tool_input["prompt"] = user_prompt

    return {"action": "call_tool", "tool": tool, "tool_input": tool_input}


def _run_tool_routing(
    user_prompt: str,
    settings: Settings,
) -> tuple[str, str, list[dict[str, Any]]]:
    """执行“路由-工具”循环，返回 (tool_name, answer, trace)。"""
    trace: list[dict[str, Any]] = []
    scratchpad: list[dict[str, Any]] = []
    last_tool = "direct_answer"
    last_output = ""

    for step in range(1, MAX_ROUTER_STEPS + 1):
        decision = _route_once(user_prompt=user_prompt, settings=settings, scratchpad=scratchpad)
        action = str(decision.get("action", ""))

        if action == "final":
            answer = str(decision.get("answer", ""))
            trace.append({"step": step, "action": "final"})
            if answer:
                return last_tool, answer, trace
            break

        tool_name = str(decision.get("tool", "")).strip()
        tool_input = decision.get("tool_input")
        errors = _validate_tool_input(tool_name=tool_name, tool_input=tool_input)

        if errors:
            trace.append(
                {
                    "step": step,
                    "action": "call_tool",
                    "tool": tool_name,
                    "valid": False,
                    "errors": errors,
                }
            )
            # 不因路由器格式错误让请求直接失败。
            tool_name = "direct_answer"
            tool_input = {"prompt": user_prompt}

        handler = TOOLS[tool_name]["handler"]
        tool_output = handler(tool_input, settings)
        last_tool = tool_name
        last_output = tool_output

        trace.append(
            {
                "step": step,
                "action": "call_tool",
                "tool": tool_name,
                "valid": True,
            }
        )
        scratchpad.append(
            {
                "tool": tool_name,
                # 控制 trace 大小，避免响应和日志过大。
                "output_preview": tool_output[:500],
            }
        )

    if last_output:
        trace.append({"step": MAX_ROUTER_STEPS, "action": "max_steps_reached"})
        return last_tool, last_output, trace

    fallback_answer = TOOLS["direct_answer"]["handler"]({"prompt": user_prompt}, settings)
    trace.append({"step": MAX_ROUTER_STEPS, "action": "fallback", "tool": "direct_answer"})
    return "direct_answer", fallback_answer, trace


def handle_invocation(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """单次调用的业务主流程。"""
    start = perf_counter()
    record_id = str(uuid4())
    status_code = 500

    try:
        missing_fields = _validate_payload(payload)
        if missing_fields:
            status_code = 400
            return status_code, {"error": "missing required fields", "missing": missing_fields}

        settings = Settings.from_env()
        tool_name, answer, route_trace = _run_tool_routing(
            user_prompt=payload["prompt"],
            settings=settings,
        )

        pdf_bytes = render_pdf(
            record_id=record_id,
            prompt=payload["prompt"],
            answer=answer,
            user_id=payload["user_id"],
            session_id=payload["session_id"],
            locale=payload["locale"],
        )

        pdf_key = build_pdf_s3_key(record_id)
        upload_pdf(
            pdf_bytes=pdf_bytes,
            bucket_name=settings.bucket_name,
            key=pdf_key,
        )
        pdf_url = generate_presigned_pdf_url(
            bucket_name=settings.bucket_name,
            key=pdf_key,
            expires_in=settings.pdf_url_expires,
        )

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
                "tool": tool_name,
                "route_trace": route_trace,
            },
        )

        status_code = 200
        return status_code, {
            "record_id": record_id,
            "answer": answer,
            "tool": tool_name,
            "route_trace": route_trace,
            "pdf": {"s3_key": pdf_key, "url": pdf_url},
        }
    except Exception:
        LOGGER.exception("failed to process invocation")
        status_code = 500
        return status_code, {"error": "internal_server_error"}
    finally:
        latency_ms = int((perf_counter() - start) * 1000)
        LOGGER.info(
            json.dumps(
                {"record_id": record_id, "latency_ms": latency_ms, "status_code": status_code},
                ensure_ascii=False,
            )
        )


def invocations(event: dict[str, Any], context: Any | None = None) -> dict[str, Any]:
    """AgentCore/Lambda 兼容入口，统一返回 HTTP 风格响应。"""
    del context
    payload = _parse_body(event)
    status_code, body = handle_invocation(payload)
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def lambda_handler(event: dict[str, Any], context: Any | None = None) -> dict[str, Any]:
    """Lambda 常见入口别名，内部复用 invocations()."""
    return invocations(event, context)
