from __future__ import annotations

# 解析 JSON 响应体
import json

# 构造固定 UUID，保证测试可重复
import uuid

# 固定时间输入（UTC）
from datetime import UTC, datetime

# 被测业务入口
from agent import app

# 被测 PDF 渲染函数
from agent.pdf.render import render_pdf

# 被测 S3 key 生成函数
from agent.storage.s3 import build_pdf_s3_key


# 验证 PDF 渲染至少能产出合法 PDF 字节
def test_render_pdf_generates_bytes() -> None:
    pdf_bytes = render_pdf(
        record_id="rid-1",
        prompt="hello prompt",
        answer="hello answer",
        user_id="u-1",
        session_id="s-1",
        locale="ko-KR",
    )
    # PDF 文件头应该以 %PDF 开头
    assert pdf_bytes.startswith(b"%PDF")
    # 至少有一定长度，避免空文件
    assert len(pdf_bytes) > 100


# 验证 S3 key 规则：pdf/YYYY/MM/<record_id>.pdf
def test_build_pdf_s3_key_rule() -> None:
    key = build_pdf_s3_key(
        record_id="abc123",
        now=datetime(2026, 2, 9, 1, 2, 3, tzinfo=UTC),
    )
    assert key == "pdf/2026/02/abc123.pdf"


# happy path：mock 掉外部依赖，验证主流程可走通
def test_invocations_happy_path_with_mocked_aws(monkeypatch) -> None:
    # 设置运行时环境变量
    monkeypatch.setenv("MODEL_ID", "m-1")
    monkeypatch.setenv("TABLE_NAME", "table-1")
    monkeypatch.setenv("BUCKET_NAME", "bucket-1")
    monkeypatch.setenv("PDF_URL_EXPIRES", "900")

    # 固定 UUID，便于断言
    fixed_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(app, "uuid4", lambda: fixed_id)
    # mock 掉真实模型调用
    monkeypatch.setattr(app, "generate_answer", lambda prompt, model_id: "mock-answer")

    # 捕获 mock 调用参数，供断言使用
    captured = {}

    def fake_upload_pdf(pdf_bytes, bucket_name, key):
        captured["bucket"] = bucket_name
        captured["key"] = key
        captured["pdf_size"] = len(pdf_bytes)

    monkeypatch.setattr(app, "upload_pdf", fake_upload_pdf)
    monkeypatch.setattr(
        app,
        "generate_presigned_pdf_url",
        lambda bucket_name, key, expires_in: f"https://example.test/{bucket_name}/{key}?exp={expires_in}",
    )
    monkeypatch.setattr(
        app,
        "put_record",
        lambda table_name, record: captured.update(record=record),
    )

    # 构造标准调用（body 为 JSON 字符串）
    response = app.invocations(
        {"body": json.dumps({"prompt": "p", "user_id": "u", "session_id": "s", "locale": "en-US"})}
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["record_id"] == str(fixed_id)
    assert body["answer"] == "mock-answer"
    # 这里使用当前 UTC 的年/月
    assert body["pdf"]["s3_key"] == f"pdf/{datetime.now(UTC):%Y/%m}/{fixed_id}.pdf"
    assert body["pdf"]["url"].endswith("?exp=900")
    assert captured["bucket"] == "bucket-1"
    assert captured["key"] == body["pdf"]["s3_key"]
    assert captured["pdf_size"] > 100
    assert captured["record"]["record_id"] == str(fixed_id)


# 缺少必填字段时应返回 400
def test_invocations_missing_fields_returns_400(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_ID", "m-1")
    monkeypatch.setenv("TABLE_NAME", "table-1")
    monkeypatch.setenv("BUCKET_NAME", "bucket-1")

    response = app.invocations({"body": json.dumps({"prompt": "p"})})

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"] == "missing required fields"
    assert set(body["missing"]) == {"user_id", "session_id", "locale"}
