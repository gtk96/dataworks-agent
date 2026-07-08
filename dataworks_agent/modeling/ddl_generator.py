"""DDLGenerator — 生成符合数仓规范的 DDL 语句。

规范来源: standards/steering/data-warehouse-standards.md
- DDL 前加 drop table if exists，不加 if not exists
- ODS/DWD/DWS/DMR 不设 LIFECYCLE（永久保存）
- 字段类型按后缀推断：id→string, amt→decimal(24,6), cnt→bigint
"""

from __future__ import annotations

import json
import logging
import re

from dataworks_agent.schemas import ColumnDef, CreateTaskRequest

logger = logging.getLogger(__name__)

# 金额类后缀
_AMOUNT_SUFFIXES = re.compile(
    r"(amt|cost|price|fee|spend|budget|revenue|income|profit|loss|payment|refund)$", re.IGNORECASE
)
# 计数类后缀
_COUNT_SUFFIXES = re.compile(
    r"(cnt|count|num|total|sales|clicks|impressions|views|pv|uv|orders|qty|quantity)$",
    re.IGNORECASE,
)
# 比率类后缀
_RATIO_SUFFIXES = re.compile(r"(ratio|rate|cnv|ctr|roi|cpm|cpc|cpa|cvr|arpu|arppu)$", re.IGNORECASE)


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


def _get_partitions(update_method: str) -> list[str]:
    """根据更新方式返回分区字段列表（规范：hour/hourly→dt,ht；day/all→dt）。"""
    if update_method in ("hour", "hourly"):
        return ["dt", "ht"]
    return ["dt"]


class DDLGenerator:
    """DDL 生成器 — 遵循数仓分层规范。"""

    async def generate(
        self,
        request: CreateTaskRequest,
        target_table: str,
        task_id: str = "",
        preview_result: dict | None = None,
    ) -> None:
        """生成 dev + prod 双表 DDL 并持久化。preview_result 不为空时跳过 DB 写入。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel
        from dataworks_agent.modeling.table_discovery import TableDiscovery

        # 1. 获取源表结构
        columns = request.columns_override
        if not columns:
            discovery = TableDiscovery()
            source_structure = await discovery.get_table_structure(request.source_table)
            columns = source_structure.columns
            if not columns:
                raise ValueError(f"无法获取源表 {request.source_table} 的字段结构")

        # 2. 推断字段类型（如果源表类型不标准）
        normalized = []
        for col in columns:
            inferred = infer_column_type(col.name, col.type)
            normalized.append(
                ColumnDef(
                    name=col.name,
                    type=inferred,
                    comment=col.comment,
                )
            )

        partitions = request.partition_keys or _get_partitions(request.update_method.value)

        # 3. 生成 DDL（不带 schema 前缀，MCP/BFF 自动添加）
        comment = f"{request.target_layer.value}层-{request.domain}域-{request.entity}-{request.update_method.value}"
        dev_ddl = self._build_ddl(
            table=target_table, columns=normalized, partitions=partitions, comment=comment
        )
        prod_ddl = dev_ddl  # dev 和 prod DDL 结构一致

        if preview_result is not None:
            preview_result["ddl_dev"] = dev_ddl
            preview_result["ddl_prod"] = prod_ddl
            return

        # 4. 持久化
        with SessionLocal() as db:
            task = db.get(ModelingTaskModel, task_id)
            if task:
                task.ddl_dev = dev_ddl
                task.ddl_prod = prod_ddl
                task.columns_json = json.dumps(
                    [c.model_dump() for c in normalized], ensure_ascii=False
                )
                db.commit()

        logger.info("DDL 生成完成: %s", target_table)

    def _build_ddl(
        self,
        table: str,
        columns: list,
        partitions: list[str],
        comment: str,
    ) -> str:
        """构建 ODPS DDL — 遵循规范：drop + create，无 if not exists，无 LIFECYCLE。"""
        part_set = set(partitions)

        col_lines = []
        for col in columns:
            if col.name in part_set:
                continue
            dtype = col.type or "string"
            cmt = f" comment '{col.comment}'" if col.comment else ""
            col_lines.append(f"    {col.name} {dtype}{cmt}")

        part_lines = []
        for pn in partitions:
            dtype = "string"
            for col in columns:
                if col.name == pn:
                    dtype = col.type or "string"
                    break
            part_lines.append(f"{pn} {dtype}")

        lines = [
            f"drop table if exists {table};",
            f"create table {table} (",
            ",\n".join(col_lines),
            ")",
        ]

        if comment:
            lines.append(f"comment '{comment}'")

        if part_lines:
            lines.append(f"partitioned by ({', '.join(part_lines)})")

        lines.append(";")
        return "\n".join(lines)


ddl_generator = DDLGenerator()
