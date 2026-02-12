from __future__ import annotations

# 时间戳用于按年月分区对象路径
from datetime import datetime, timezone
# 类型提示
from typing import Any

# AWS SDK
import boto3


# 根据记录 ID 生成 PDF 对象键：pdf/YYYY/MM/<record_id>.pdf
def build_pdf_s3_key(record_id: str, now: datetime | None = None) -> str:
    # 支持注入 now（便于测试），未传则取当前 UTC 时间
    ts = now or datetime.now(timezone.utc)
    # 按年月分层目录，便于管理与生命周期策略
    return f"pdf/{ts:%Y/%m}/{record_id}.pdf"


# 上传 PDF 字节到 S3
def upload_pdf(
    pdf_bytes: bytes,
    bucket_name: str,
    key: str,
    client: Any | None = None,
) -> None:
    # 支持传入 mock client；未传则创建真实 client
    s3 = client or boto3.client("s3")
    # 写入对象并显式标注内容类型为 PDF
    s3.put_object(Bucket=bucket_name, Key=key, Body=pdf_bytes, ContentType="application/pdf")


# 生成 PDF 下载预签名 URL
def generate_presigned_pdf_url(
    bucket_name: str,
    key: str,
    expires_in: int = 600,
    client: Any | None = None,
) -> str:
    # 支持传入 mock client；未传则创建真实 client
    s3 = client or boto3.client("s3")
    # 为 get_object 生成限时 URL
    return s3.generate_presigned_url(
        "get_object",
        # 目标对象定位参数
        Params={"Bucket": bucket_name, "Key": key},
        # 过期时间（秒）
        ExpiresIn=expires_in,
    )
