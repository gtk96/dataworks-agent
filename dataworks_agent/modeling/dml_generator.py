"""DMLGenerator — 生成符合数仓规范的 DML 语句。

规范来源: standards/steering/sql-development-rules.md
- SQL 关键字全小写
- 表别名用 t1/t2/t3
- DML SELECT 列数必须与 DDL 非分区字段数严格一致
- JSON ODS 的 DWD 必须保留 json_data 放 SELECT 最后一列
- 分区用 partition (dt='${bizdate}')
- 禁止 select *
"""

from __future__ import annotations

import json
import logging

from dataworks_agent.config import settings

logger = logging.getLogger(__name__)


def _build_dml_structured(
    dev_schema: str,
    prod_schema: str,
    target_table: str,
    source_table: str,
    columns: list[dict],
    granularity: str = "day",
) -> str:
    """构建结构化 ODS → DWD 的 DML。"""
    partition_names = {"dt", "ht", "hh"}
    col_lines = []
    for col in columns:
        name = col.get("name", "")
        if name.lower() in partition_names:
            continue
        expr = col.get("source_expr") or f"t1.{name}"
        alias = f" as {name}" if expr != f"t1.{name}" else ""
        comment = col.get("comment", "")
        line = f"    {expr}{alias}"
        if comment:
            line += f"  -- {comment}"
        col_lines.append(line)

    cols = ",\n".join(col_lines)

    # 小时级分区需要 dt + ht
    if granularity in ("hour", "hourly"):
        partition = "partition (dt='${bizdate}', ht='${hour}')"
        where = "where t1.dt = '${bizdate}' and t1.ht = '${hour}'"
    else:
        partition = "partition (dt='${bizdate}')"
        where = "where t1.dt = '${bizdate}'"

    return (
        f"insert overwrite table {dev_schema}.{target_table} "
        f"{partition}\n"
        f"select\n"
        f"{cols}\n"
        f"from {prod_schema}.{source_table} t1\n"
        f"{where};\n"
    )


def _build_dml_json(
    dev_schema: str,
    prod_schema: str,
    target_table: str,
    source_table: str,
    columns: list[dict],
    granularity: str = "day",
) -> str:
    """构建 JSON ODS → DWD 的 DML。

    规范：json_data 固定放 SELECT 最后一列。
    """
    partition_names = {"dt", "ht", "hh"}
    col_lines = []
    for col in columns:
        name = col.get("name", "")
        if name.lower() in partition_names:
            continue
        expr = col.get("source_expr", "")
        comment = col.get("comment", "")
        if not expr:
            source_path = col.get("source_path", name)
            expr = f"get_json_object(t1.json_data, '$.{source_path}')"
        alias = f" as {name}" if name else ""
        line = f"    {expr}{alias}"
        if comment:
            line += f"  -- {comment}"
        col_lines.append(line)

    # json_data 固定放最后一列（规范要求）
    col_lines.append("    t1.json_data")

    cols = ",\n".join(col_lines)

    # 小时级分区需要 dt + ht
    if granularity in ("hour", "hourly"):
        partition = "partition (dt='${bizdate}', ht='${hour}')"
        where = "where t1.dt = '${bizdate}' and t1.ht = '${hour}'"
    else:
        partition = "partition (dt='${bizdate}')"
        where = "where t1.dt = '${bizdate}'"

    return (
        f"insert overwrite table {dev_schema}.{target_table} "
        f"{partition}\n"
        f"select\n"
        f"{cols}\n"
        f"from {prod_schema}.{source_table} t1\n"
        f"{where};\n"
    )


class DMLGenerator:
    """DML 生成器。"""

    async def generate_and_write(self, task_id: str) -> None:
        """生成 DML 并通过 BFF updateNode 写入 IDE 节点。"""
        from dataworks_agent.db.database import SessionLocal
        from dataworks_agent.db.models import ModelingTaskModel

        with SessionLocal() as db:
            task = db.get(ModelingTaskModel, task_id)
            if not task:
                raise RuntimeError(f"任务 {task_id} 不存在")

            columns = json.loads(task.columns_json) if task.columns_json else []
            source_format = "json" if "json_data" in (task.ddl_dev or "").lower() else "structured"
            granularity = task.update_method or "day"

            if source_format == "json":
                dml = _build_dml_json(
                    dev_schema=settings.dataworks_dev_schema,
                    prod_schema=settings.dataworks_prod_schema,
                    target_table=task.target_table,
                    source_table=task.source_table,
                    columns=columns,
                    granularity=granularity,
                )
            else:
                dml = _build_dml_structured(
                    dev_schema=settings.dataworks_dev_schema,
                    prod_schema=settings.dataworks_prod_schema,
                    target_table=task.target_table,
                    source_table=task.source_table,
                    columns=columns,
                    granularity=granularity,
                )

            if task.node_uuid:
                from dataworks_agent.state import app_state
                from dataworks_agent.task_engine.intent_logger import confirm_intent, log_intent

                bff = getattr(app_state, "_bff_client", None)
                cdp = getattr(app_state, "_cdp_client", None)

                if bff and cdp:
                    intent_id = await log_intent(
                        task_id, "dml_write", "updateNode", str(task.node_uuid)
                    )
                    await bff.update_node(task.node_uuid, dml)
                    await cdp.format_and_save()
                    await confirm_intent(intent_id)

            task.dml = dml
            db.commit()

        self._archive_dml(task_id, task.target_table, dml)

    def _archive_dml(self, task_id: str, table_name: str, dml: str) -> None:
        """本地归档 DML 文件。"""
        from datetime import datetime
        from pathlib import Path

        archive_dir = Path(settings.archive_dir) / datetime.now().strftime("%Y-%m")
        archive_dir.mkdir(parents=True, exist_ok=True)
        filepath = archive_dir / f"{table_name}_dml.sql"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"-- Task: {task_id}\n-- Generated: {datetime.now().isoformat()}\n\n{dml}")
