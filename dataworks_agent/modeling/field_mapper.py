"""字段映射自动推断 — 从源表结构推断目标表字段。"""

from __future__ import annotations

import re
from typing import Any

# 字段类型推断规则（来自数仓规范）
_AMOUNT_SUFFIXES = re.compile(
    r"(amt|cost|price|fee|spend|budget|revenue|income|profit|loss|payment|refund)$", re.IGNORECASE
)
_COUNT_SUFFIXES = re.compile(
    r"(cnt|count|num|total|sales|clicks|impressions|views|pv|uv|orders|qty|quantity)$",
    re.IGNORECASE,
)
_RATIO_SUFFIXES = re.compile(r"(ratio|rate|cnv|ctr|roi|cpm|cpc|cpa|cvr|arpu|arppu)$", re.IGNORECASE)

PARTITION_NAMES = {"dt", "ht", "hh", "mt", "update_ht"}


def infer_column_type(col_name: str, source_type: str = "") -> str:
    """根据字段名后缀推断 MC 类型（遵循数仓规范字段类型规则）。"""
    lower = col_name.lower()

    # id 结尾 → string（规范：id 结尾字段不是数字类型）
    if lower.endswith("id"):
        return "string"

    # 金额类 → decimal(24,6)
    if _AMOUNT_SUFFIXES.search(lower):
        return "decimal(24,6)"

    # 计数类 → bigint
    if _COUNT_SUFFIXES.search(lower):
        return "bigint"

    # 比率类 → decimal(24,6)
    if _RATIO_SUFFIXES.search(lower):
        return "decimal(24,6)"

    # 源表类型映射
    if source_type:
        src = source_type.lower()
        if "int" in src and "bigint" not in src:
            return "bigint"
        if "bigint" in src:
            return "bigint"
        if "decimal" in src or "numeric" in src:
            return "decimal(24,6)"
        if "timestamp" in src or "datetime" in src:
            return "string"

    return "string"


def infer_field_mappings(
    source_columns: list[dict[str, Any]],
    target_layer: str = "DWD",
) -> list[dict[str, Any]]:
    """从源表字段自动推断目标表字段映射。

    Args:
        source_columns: 源表字段列表 [{"column_name": str, "data_type": str, "comment": str}]
        target_layer: 目标层 (DWD/DWS/DMR/DIM)

    Returns:
        目标表字段列表 [{"name": str, "type": str, "comment": str, "source_expr": str}]
    """
    mappings = []

    for col in source_columns:
        name = col.get("column_name", "")
        if not name or name.lower() in PARTITION_NAMES:
            continue

        source_type = col.get("data_type", "string")
        comment = col.get("comment", "")

        # 推断目标类型
        target_type = infer_column_type(name, source_type)

        # 生成映射
        mapping = {
            "name": name,
            "type": target_type,
            "comment": comment,
            "source_expr": f"t1.{name}",
        }
        mappings.append(mapping)

    return mappings


def infer_dwd_field_mappings(
    source_columns: list[dict[str, Any]],
    source_table: str,
) -> dict[str, Any]:
    """为 DWD 推断完整的字段映射元数据。

    Returns:
        StructuredMetadata 格式的字典
    """
    mappings = infer_field_mappings(source_columns, "DWD")

    # 构建 sources
    alias = "t1"
    sources = [{"table_name": source_table, "alias": alias, "is_master": True}]

    # 构建 field_mappings
    field_mappings = []
    for m in mappings:
        field_mappings.append(
            {
                "source_alias": alias,
                "source_field_name": m["name"],
                "target_field_name": m["name"],
                "field_category": _get_field_category(m["name"]),
                "apply_coalesce": m["type"] == "string",
            }
        )

    return {
        "sources": sources,
        "field_mappings": field_mappings,
        "joins": [],
        "logical_primary_keys": [],
    }


def _get_field_category(field_name: str) -> str:
    """推断字段类别。"""
    lower = field_name.lower()
    if _AMOUNT_SUFFIXES.search(lower):
        return "amount"
    if _COUNT_SUFFIXES.search(lower):
        return "quantity"
    if _RATIO_SUFFIXES.search(lower):
        return "ratio"
    return "normal"
