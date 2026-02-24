from __future__ import annotations

# 获取 UTC 时间，用于按年月分目录
from datetime import UTC, datetime
# 类型标注
from typing import Any

# AWS SDK
import boto3


# 根据 record_id 生成 S3 key：pdf/YYYY/MM/<record_id>.pdf
def build_pdf_s3_key(record_id: str, now: datetime | None = None) -> str:
    # 支持注入 now（便于测试）；不传就用当前 UTC 时间
    ts = now or datetime.now(UTC)
    return f"pdf/{ts:%Y/%m}/{record_id}.pdf"


# 上传 PDF 字节到 S3
def upload_pdf(
    pdf_bytes: bytes,
    bucket_name: str,
    key: str,
    client: Any | None = None,
) -> None:
    # 支持注入 mock client；不传则创建真实 S3 client
    s3 = client or boto3.client("s3")
    s3.put_object(Bucket=bucket_name, Key=key, Body=pdf_bytes, ContentType="application/pdf")


# 为 PDF 生成限时下载链接
def generate_presigned_pdf_url(
    bucket_name: str,
    key: str,
    expires_in: int = 600,
    client: Any | None = None,
) -> str:
    # 支持注入 mock client；不传则创建真实 S3 client
    s3 = client or boto3.client("s3")
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": key},
        ExpiresIn=expires_in,
    )
