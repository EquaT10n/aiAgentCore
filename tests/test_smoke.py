from __future__ import annotations

# JSON 读写
import json
# 用于构造固定 UUID，保证测试可重复
import uuid
# 固定时间输入和 UTC 时区
from datetime import datetime, timezone

# 被测应用入口
from agent import app
# 被测 PDF 渲染函数
from agent.pdf.render import render_pdf
# 被测 S3 key 规则函数
from agent.storage.s3 import build_pdf_s3_key


# 验证 PDF 渲染函数至少能产出有效 PDF 字节
def test_render_pdf_generates_bytes() -> None:
    # 调用渲染函数构造一个最小可用 PDF
    pdf_bytes = render_pdf(
        record_id="rid-1",
        prompt="hello prompt",
        answer="hello answer",
        user_id="u-1",
        session_id="s-1",
        locale="ko-KR",
    )
    # PDF 文件头应以 %PDF 开头
    assert pdf_bytes.startswith(b"%PDF")
    # 大小应大于最小阈值，避免空文件
    assert len(pdf_bytes) > 100


# 验证 S3 key 生成规则是否符合预期路径模板
def test_build_pdf_s3_key_rule() -> None:
    # 传入固定时间，避免依赖系统当前时间
    key = build_pdf_s3_key(
        record_id="abc123",
        now=datetime(2026, 2, 9, 1, 2, 3, tzinfo=timezone.utc),
    )
    # 断言 key 格式为 pdf/YYYY/MM/<id>.pdf
    assert key == "pdf/2026/02/abc123.pdf"


# 端到端 happy path：通过 monkeypatch mock 掉外部 AWS 依赖
def test_invocations_happy_path_with_mocked_aws(monkeypatch) -> None:
    # 设置运行时必需环境变量
    monkeypatch.setenv("MODEL_ID", "m-1")
    monkeypatch.setenv("TABLE_NAME", "table-1")
    monkeypatch.setenv("BUCKET_NAME", "bucket-1")
    monkeypatch.setenv("PDF_URL_EXPIRES", "900")

    # 固定 UUID，确保断言稳定
    fixed_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    # 替换 uuid4 生成器
    monkeypatch.setattr(app, "uuid4", lambda: fixed_id)
    # 替换真实模型调用，避免外部网络依赖
    monkeypatch.setattr(app, "generate_answer", lambda prompt, model_id: "mock-answer")

    # 用字典捕获 mock 调用参数，供后续断言
    captured = {}

    # mock 上传函数：只记录输入，不真正上传
    def fake_upload_pdf(pdf_bytes, bucket_name, key):
        captured["bucket"] = bucket_name
        captured["key"] = key
        captured["pdf_size"] = len(pdf_bytes)

    # 打补丁替换上传函数
    monkeypatch.setattr(app, "upload_pdf", fake_upload_pdf)
    # 打补丁替换预签名 URL 生成函数
    monkeypatch.setattr(
        app,
        "generate_presigned_pdf_url",
        lambda bucket_name, key, expires_in: f"https://example.test/{bucket_name}/{key}?exp={expires_in}",
    )
    # 打补丁替换落库函数，并捕获 record
    monkeypatch.setattr(app, "put_record", lambda table_name, record: captured.update(record=record))

    # 构造一次标准调用（body 为 JSON 字符串）
    response = app.invocations(
        {"body": json.dumps({"prompt": "p", "user_id": "u", "session_id": "s", "locale": "en-US"})}
    )

    # 断言响应状态码
    assert response["statusCode"] == 200
    # 解析响应体 JSON
    body = json.loads(response["body"])
    # 断言记录 ID 使用了固定 UUID
    assert body["record_id"] == str(fixed_id)
    # 断言回答来自 mock
    assert body["answer"] == "mock-answer"
    # 断言 S3 key 路径规则正确（年月基于当前 UTC 时间）
    assert body["pdf"]["s3_key"] == f"pdf/{datetime.now(timezone.utc):%Y/%m}/{fixed_id}.pdf"
    # 断言 URL 过期参数来自环境变量配置
    assert body["pdf"]["url"].endswith("?exp=900")
    # 断言上传时 bucket 正确
    assert captured["bucket"] == "bucket-1"
    # 断言上传 key 与响应一致
    assert captured["key"] == body["pdf"]["s3_key"]
    # 断言上传内容不是空 PDF
    assert captured["pdf_size"] > 100
    # 断言落库记录 ID 正确
    assert captured["record"]["record_id"] == str(fixed_id)


# 参数缺失路径：应返回 400 和缺失字段列表
def test_invocations_missing_fields_returns_400(monkeypatch) -> None:
    # 设置最小环境变量集合（本测试不会真正调用外部服务）
    monkeypatch.setenv("MODEL_ID", "m-1")
    monkeypatch.setenv("TABLE_NAME", "table-1")
    monkeypatch.setenv("BUCKET_NAME", "bucket-1")

    # 只传 prompt，故应缺 user_id/session_id/locale
    response = app.invocations({"body": json.dumps({"prompt": "p"})})

    # 断言返回 400
    assert response["statusCode"] == 400
    # 解析错误体
    body = json.loads(response["body"])
    # 断言错误码语义
    assert body["error"] == "missing required fields"
    # 断言缺失字段集合准确
    assert set(body["missing"]) == {"user_id", "session_id", "locale"}
