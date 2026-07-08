"""Ensure Holo ODS target table exists (MC DDL + Holo IMPORT FOREIGN SCHEMA)."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.services.ods_di.di_config import (
    inject_schema_prefix_in_ddl,
    sql_literal,
    strip_leading_drop_table,
)
from dataworks_agent.services.ods_di.sql_runner import run_ida_query

logger = logging.getLogger(__name__)

HOLO_TO_MC_TYPE: dict[str, str] = {
    "character varying": "STRING",
    "varchar": "STRING",
    "text": "STRING",
    "char": "STRING",
    "integer": "BIGINT",
    "int": "BIGINT",
    "int4": "BIGINT",
    "bigint": "BIGINT",
    "int8": "BIGINT",
    "smallint": "BIGINT",
    "int2": "BIGINT",
    "boolean": "BOOLEAN",
    "bool": "BOOLEAN",
    "numeric": "DECIMAL(24,6)",
    "decimal": "DECIMAL(24,6)",
    "real": "DOUBLE",
    "float4": "DOUBLE",
    "double precision": "DOUBLE",
    "float8": "DOUBLE",
    "float": "DOUBLE",
    "timestamp": "TIMESTAMP",
    "timestamptz": "TIMESTAMP",
    "timestamp without time zone": "TIMESTAMP",
    "timestamp with time zone": "TIMESTAMP",
    "date": "STRING",
    "json": "STRING",
    "jsonb": "STRING",
    "uuid": "STRING",
    "bytea": "STRING",
}

PARTITION_NAMES = frozenset({"dt", "ht", "mt", "update_ht"})


def _holo_type_to_mc(holo_type: str) -> str:
    normalized = holo_type.strip().lower()
    base = normalized.split("(")[0].strip()
    if base in HOLO_TO_MC_TYPE:
        return HOLO_TO_MC_TYPE[base]
    if "varchar" in base or "text" in base or "char" in base:
        return "STRING"
    if "int" in base:
        return "BIGINT"
    if "numeric" in base or "decimal" in base:
        return "DECIMAL(24,6)"
    if "float" in base or "double" in base or "real" in base:
        return "DOUBLE"
    if "timestamp" in base or "date" in base or "time" in base:
        return "TIMESTAMP"
    if "bool" in base:
        return "BOOLEAN"
    return "STRING"


def _generate_mc_ddl(
    target_table: str,
    columns: list[dict[str, Any]],
    granularity: str,
    mc_project: str = "cda",
) -> str:
    col_lines: list[str] = []
    for col in columns:
        name = col.get("column_name", "")
        if not name or name.lower() in PARTITION_NAMES:
            continue
        holo_type = col.get("data_type", "string")
        mc_type = _holo_type_to_mc(holo_type)
        col_lines.append(f"    {name} {mc_type}")

    if not col_lines:
        raise ValueError("No non-partition columns found for DDL generation")

    gran = granularity.lower()
    if gran in {"hour", "hourly", "min"}:
        partition_clause = "PARTITIONED BY (dt STRING, ht STRING)"
    else:
        partition_clause = "PARTITIONED BY (dt STRING)"

    body = ",\n".join(col_lines)
    full_table = f"{mc_project}.{target_table}" if mc_project else target_table
    return (
        f"CREATE TABLE IF NOT EXISTS {full_table}\n(\n{body}\n)\n{partition_clause}\nLIFECYCLE 365;"
    )


async def _fetch_registry_ddl(
    bff: Any,
    holo_schema: str,
    source_table: str,
    granularity: str,
    *,
    mc: Any = None,
) -> str | None:
    ddl_column = "ods_ddl_hour" if granularity in {"hour", "hourly"} else "ods_ddl_day"
    registry = settings.ddl_registry_project or settings.dataworks_prod_schema
    ddl_table_ref = f"{registry}.dwd_pub_ods_ddl_all"
    query_sql = (
        f"SELECT {ddl_column}\n"
        f"FROM {ddl_table_ref}\n"
        f"WHERE dt = max_pt({sql_literal(ddl_table_ref)})\n"
        f"  AND source_schema_name = {sql_literal(holo_schema)}\n"
        f"  AND source_table_name = {sql_literal(source_table)}"
    )
    if mc is not None:
        try:
            inst = await mc.submit_query(query_sql)
            rows = (await mc.wait_and_fetch(inst)).rows
        except Exception as exc:
            logger.warning("registry DDL 查询失败(MaxCompute): %s", exc)
            rows = None
    else:
        rows = await run_ida_query(bff, query_sql)
    if not rows or len(rows) != 1 or not rows[0] or not rows[0][0]:
        return None
    ddl = str(rows[0][0]).strip()
    return ddl or None


async def _get_existing_ddl(
    bff: Any, mcp: Any, mc_project: str, table_name: str, *, mc: Any = None
) -> str | None:
    if mc is not None:
        return await mc.get_table_ddl(table_name, project=mc_project)

    table_guid = f"odps.{mc_project}.{table_name}"
    try:
        ddl = await bff.get_creation_ddl(table_guid)
        if ddl:
            return ddl
    except Exception as exc:
        logger.debug("BFF geneCreationDdl 失败: %s", exc)

    if mcp is not None:
        try:
            ddl = await mcp.call_tool("get_table_ddl", {"table_guid": table_guid})
            if ddl and "CREATE TABLE" in str(ddl).upper():
                return str(ddl)
        except Exception as exc:
            logger.debug("MCP get_table_ddl 失败: %s", exc)
    return None


async def _execute_sql_with_fallback(
    bff: Any, sql: str, label: str = "SQL", *, mc: Any = None
) -> bool:
    """Execute DDL via AK/SK MaxCompute (剥离 DROP)，缺则降级 bff IDA → 资源组。"""
    if mc is not None:
        res = await mc.execute_ddl(strip_leading_drop_table(sql))
        if not res.success:
            logger.warning("%s MaxCompute 执行失败: %s", label, res.error or "")
        return res.success

    logger.info("执行 %s:\n%s", label, sql[:500])
    job_code = await bff.execute_sql_ida(sql)
    if job_code:
        ok = await bff.wait_ida_job(job_code)
        if not ok:
            logger.warning("%s IDA 执行失败: %s", label, getattr(bff, "last_error", None) or "")
        return ok

    logger.info("IDA 失败，尝试资源组: %s", getattr(bff, "last_error", None) or "")
    job_code = await bff.execute_sql(sql)
    if not job_code:
        logger.warning(
            "%s 提交失败 (IDA + 资源组): %s", label, getattr(bff, "last_error", None) or ""
        )
        return False
    ok = await bff.wait_job(job_code)
    if not ok:
        logger.warning("%s 资源组执行失败: %s", label, getattr(bff, "last_error", None) or "")
    return ok


async def ensure_holo_table(
    bff: Any,
    mcp: Any,
    *,
    holo_schema: str,
    source_table: str,
    target_table: str,
    granularity: str,
    mc_project: str | None = None,
    holo_cda_schema: str = "cda",
    source_columns: list[dict[str, Any]] | None = None,
    mc: Any = None,
) -> dict[str, Any]:
    """Ensure MC target table exists in both dev and prod, and Holo foreign schema mapping is synced.

    Args:
        mc_project: MaxCompute project for CREATE TABLE (defaults to prod schema).
        holo_cda_schema: Hologres CDA schema for IMPORT FOREIGN SCHEMA.
    """
    mc_prod = mc_project or settings.dataworks_prod_schema
    mc_dev = settings.dataworks_dev_schema
    logger.info(
        "ensure_holo_table 开始: holo_schema=%s, source_table=%s, target_table=%s, mc_dev=%s, mc_prod=%s",
        holo_schema,
        source_table,
        target_table,
        mc_dev,
        mc_prod,
    )
    registry_ddl = await _fetch_registry_ddl(bff, holo_schema, source_table, granularity, mc=mc)

    if registry_ddl:
        logger.info("Holo DDL registry 命中: %s.%s", holo_schema, source_table)
        ddl_source = "registry"
    elif source_columns:
        logger.info("Holo DDL registry 未命中，动态生成: %s.%s", holo_schema, source_table)
        ddl_source = "generated"
    else:
        return {
            "status": "failed",
            "error": f"DDL 模板未找到且无字段元数据: {holo_schema}.{source_table}",
            "table": target_table,
        }

    results: dict[str, Any] = {
        "status": "created",
        "table": target_table,
        "ddl_source": ddl_source,
        "environments": {},
    }

    for env_name, proj in [("dev", mc_dev), ("prod", mc_prod)]:
        if registry_ddl:
            mc_ddl = inject_schema_prefix_in_ddl(registry_ddl, proj)
        else:
            mc_ddl = _generate_mc_ddl(target_table, source_columns, granularity, proj)

        existing_ddl = await _get_existing_ddl(bff, mcp, proj, target_table, mc=mc)
        if existing_ddl:
            logger.info("MC 表已存在: %s.%s，跳过建表", proj, target_table)
            results["environments"][env_name] = {"status": "exists", "project": proj}
            continue

        logger.info("创建 MC 表: %s.%s (来源: %s)", proj, target_table, ddl_source)
        created = await _execute_sql_with_fallback(
            bff, mc_ddl, f"MC DDL({proj}.{target_table})", mc=mc
        )
        if not created:
            results["environments"][env_name] = {
                "status": "failed",
                "project": proj,
                "error": getattr(bff, "last_error", None) or "MC 建表失败",
            }
            results["status"] = "failed"
            results["error"] = (
                f"{env_name} 建表失败: {getattr(bff, 'last_error', None) or '请检查日志'}"
            )
        else:
            results["environments"][env_name] = {"status": "created", "project": proj}

    if results["status"] != "failed":
        logger.info("MC 建表完成（dev + prod）: %s", target_table)

    return results
