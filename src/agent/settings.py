from __future__ import annotations

# 读取环境变量
import os
# 轻量不可变配置对象
from dataclasses import dataclass


# 读取必填环境变量，缺失时抛出明确异常
def _required_env(name: str) -> str:
    # 按变量名读取值
    value = os.getenv(name)
    # 空字符串或 None 都视为未配置
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    # 返回有效值
    return value


# 运行时配置：从环境变量一次性装配
@dataclass(frozen=True)
class Settings:
    # Bedrock 模型 ID
    model_id: str
    # DynamoDB 表名
    table_name: str
    # S3 Bucket 名
    bucket_name: str
    # PDF 预签名 URL 过期时间（秒）
    pdf_url_expires: int = 600

    # 工厂方法：从环境变量构建 Settings 实例
    @classmethod
    def from_env(cls) -> "Settings":
        # 可选变量：未提供时默认 600 秒
        expires = int(os.getenv("PDF_URL_EXPIRES", "600"))
        # 必填变量通过 _required_env 校验
        return cls(
            model_id=_required_env("MODEL_ID"),
            table_name=_required_env("TABLE_NAME"),
            bucket_name=_required_env("BUCKET_NAME"),
            pdf_url_expires=expires,
        )
