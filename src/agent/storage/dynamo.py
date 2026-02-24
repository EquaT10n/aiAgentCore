from __future__ import annotations

# DynamoDB 数值类型推荐使用 Decimal
from decimal import Decimal

# 类型标注
from typing import Any

# AWS SDK
import boto3


# 将 Python 值递归转换为 DynamoDB AttributeValue
def _to_attr_value(value: Any) -> dict[str, Any]:
    # 字符串 -> S
    if isinstance(value, str):
        return {"S": value}
    # 布尔值 -> BOOL
    if isinstance(value, bool):
        return {"BOOL": value}
    # 数字 -> N（字符串格式）
    if isinstance(value, (int, float, Decimal)):
        return {"N": str(value)}
    # None -> NULL
    if value is None:
        return {"NULL": True}
    # 列表 -> L（递归转换每个元素）
    if isinstance(value, list):
        return {"L": [_to_attr_value(item) for item in value]}
    # 字典 -> M（递归转换每个键值）
    if isinstance(value, dict):
        return {"M": {key: _to_attr_value(item) for key, item in value.items()}}
    # 其他类型显式报错，避免静默写入异常结构
    raise TypeError(f"unsupported value type for DynamoDB serialization: {type(value)}")


# 向指定 DynamoDB 表写入一条记录
def put_record(table_name: str, record: dict[str, Any], client: Any | None = None) -> None:
    # 支持注入 mock client；不传则创建真实 DynamoDB client
    dynamodb = client or boto3.client("dynamodb")
    # 整条记录转换成 DynamoDB Item 结构
    item = {key: _to_attr_value(value) for key, value in record.items()}
    dynamodb.put_item(TableName=table_name, Item=item)
