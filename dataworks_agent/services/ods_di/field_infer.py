"""Phase 1: field inference from schema snapshot / DDL registry."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.services.ods_di.ddl_parser import DDLParseError, DDLParser
from dataworks_agent.services.ods_di.di_config import infer_split_pk, sql_literal
from dataworks_agent.services.ods_di.sql_runner import run_odps_query
from dataworks_agent.services.ods_di.where_infer import infer_where_field

logger = logging.getLogger(__name__)


def _registry_ddl_column(granularity: str) -> str:
    if granularity.lower() in {"hour", "hourly", "min"}:
        return "ods_ddl_hour"
    return "ods_ddl_day"


def _normalize_columns(rows: list[list[Any]]) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for row in rows:
        if row and len(row) >= 2:
            columns.append(
                {
                    "column_name": (row[0] or "").strip(),
                    "data_type": (row[1] or "").strip().lower(),
                    "column_key": (row[2] or "").strip() if len(row) > 2 else "",
                    "column_position": row[3] if len(row) > 3 else 0,
                }
            )
    return columns


async def query_columns(
    bff: Any,
    mcp: Any,
    datasource_name: str,
    source_table_name: str,
    *,
    metadata_project: str | None = None,
) -> list[dict[str, Any]] | None:
    """Query column metadata from dwd_gds_schema_column_snapshot_all."""
    mc_project = metadata_project or settings.dataworks_prod_schema
    table_ref = f"{mc_project}.dwd_gds_schema_column_snapshot_all"
    schema_expr = f"REGEXP_REPLACE(table_schema, '-', '_') = {sql_literal(datasource_name)}"
    table_expr = f"table_name = {sql_literal(source_table_name)}"
    query_sql = (
        f"SELECT column_name, data_type, column_key, column_position\n"
        f"FROM {table_ref}\n"
        f"WHERE dt = max_pt({sql_literal(table_ref)})\n"
        f"  AND {schema_expr}\n"
        f"  AND {table_expr}\n"
        f"ORDER BY column_position"
    )

    body_list = await run_odps_query(bff, mcp, query_sql)
    if body_list:
        columns = _normalize_columns(body_list)
        if columns:
            logger.info(
                "查询到 %d 个字段 (%s.%s)",
                len(columns),
                datasource_name,
                source_table_name,
            )
            return columns

    return None


async def query_columns_from_ddl_registry(
    bff: Any,
    mcp: Any,
    datasource_name: str,
    source_table_name: str,
    granularity: str,
    *,
    ddl_registry_project: str | None = None,
) -> list[dict[str, Any]] | None:
    """Fallback: parse registered ODS DDL template for column list."""
    ddl_column = _registry_ddl_column(granularity)
    registry = ddl_registry_project or settings.dataworks_prod_schema
    ddl_table_ref = f"{registry}.dwd_pub_ods_ddl_all"
    schema_key = datasource_name.strip().lower()
    table_key = source_table_name.strip()
    query_sql = (
        f"SELECT {ddl_column}\n"
        f"FROM {ddl_table_ref}\n"
        f"WHERE dt = max_pt({sql_literal(ddl_table_ref)})\n"
        f"  AND lower(source_schema_name) = {sql_literal(schema_key)}\n"
        f"  AND lower(source_table_name) = {sql_literal(table_key.lower())}\n"
        f"LIMIT 1"
    )

    body_list = await run_odps_query(bff, mcp, query_sql)
    if not body_list or not body_list[0] or not body_list[0][0]:
        return None

    ddl_text = str(body_list[0][0]).strip()
    if not ddl_text:
        return None

    try:
        structure = DDLParser().parse(ddl_text)
    except DDLParseError as exc:
        logger.warning(
            "DDL registry fallback parse failed for %s.%s: %s",
            datasource_name,
            source_table_name,
            exc,
        )
        return None

    partition_names = {"dt", "ht", "mt"}
    return [
        {
            "column_name": field.name,
            "data_type": field.type.lower(),
            "column_key": "PRI" if field.name == "id" else "",
            "column_position": index,
        }
        for index, field in enumerate(structure.fields, start=1)
        if field.name.lower() not in partition_names
    ] or None


async def resolve_source_step_type(bff: Any, datasource_name: str) -> str:
    """Resolve DI reader stepType from datasource list."""
    from dataworks_agent.services.ods_di.di_config import resolve_source_step_type as _map

    try:
        for source in await bff.list_datasources():
            name = source.get("name") or source.get("datasourceName", "")
            if name == datasource_name:
                raw_type = source.get("type") or source.get("datasourceType") or "mysql"
                return _map(str(raw_type))
    except Exception as exc:
        logger.warning("解析数据源 %s 类型失败: %s", datasource_name, exc)
    return "mysql"


async def infer_fields(
    bff: Any,
    mcp: Any,
    datasource_name: str,
    source_table_name: str,
    granularity: str,
) -> dict[str, Any]:
    """Run phase-1 field inference."""
    columns_raw = await query_columns(bff, mcp, datasource_name, source_table_name)
    if columns_raw is None:
        columns_raw = await query_columns_from_ddl_registry(
            bff,
            mcp,
            datasource_name,
            source_table_name,
            granularity,
        )

    if not columns_raw:
        return {
            "status": "failed",
            "error": f"字段查询失败: {datasource_name}.{source_table_name}",
        }

    split_pk = infer_split_pk(columns_raw, source_table_name)
    where_result = infer_where_field(columns_raw)
    source_step_type = await resolve_source_step_type(bff, datasource_name)

    return {
        "status": "ok",
        "split_pk": split_pk,
        "where_field": where_result["where_field"],
        "where_type": where_result["where_type"],
        "columns": [c["column_name"] for c in columns_raw],
        "source_step_type": source_step_type,
    }
