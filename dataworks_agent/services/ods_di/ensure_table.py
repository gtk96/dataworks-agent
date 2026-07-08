"""Phase 2: ensure ODS table exists (DDL registry + compatibility check)."""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.config import settings
from dataworks_agent.services.ods_di.di_config import (
    compare_ddl_structures,
    inject_schema_prefix_in_ddl,
    sql_literal,
    strip_leading_drop_table,
)
from dataworks_agent.services.ods_di.sql_runner import run_ida_query

logger = logging.getLogger(__name__)


async def _fetch_registry_ddl(
    bff: Any,
    datasource_name: str,
    source_table_name: str,
    granularity: str,
    *,
    mc: Any = None,
    ddl_registry_project: str | None = None,
) -> str | None:
    ddl_column = "ods_ddl_hour" if granularity in {"hour", "hourly"} else "ods_ddl_day"
    registry = ddl_registry_project or settings.dataworks_prod_schema
    ddl_table_ref = f"{registry}.dwd_pub_ods_ddl_all"
    query_sql = (
        f"SELECT {ddl_column}\n"
        f"FROM {ddl_table_ref}\n"
        f"WHERE dt = max_pt({sql_literal(ddl_table_ref)})\n"
        f"  AND source_schema_name = {sql_literal(datasource_name)}\n"
        f"  AND source_table_name = {sql_literal(source_table_name)}"
    )
    if mc is not None:
        # AK/SK MaxCompute 查询（优先）
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
    bff: Any, mcp: Any, mc_project: str, ods_table_name: str, *, mc: Any = None
) -> str | None:
    if mc is not None:
        # MaxCompute 为权威源：返回现有 DDL 或 None(不存在)
        return await mc.get_table_ddl(ods_table_name, project=mc_project)

    table_guid = f"odps.{mc_project}.{ods_table_name}"
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


async def ensure_table(
    bff: Any,
    mcp: Any,
    *,
    datasource_name: str,
    source_table_name: str,
    target_table: str,
    granularity: str,
    mc_project: str | None = None,
    ddl_registry_project: str | None = None,
    mc: Any = None,
) -> dict[str, Any]:
    """Ensure ODS table exists and matches registry DDL when already present.

    mc(MaxComputeClient) 存在时 registry 查询/现有 DDL/建表均走 AK/SK；否则降级 bff。
    """
    project = mc_project or settings.dataworks_dev_schema
    registry_ddl = await _fetch_registry_ddl(
        bff,
        datasource_name,
        source_table_name,
        granularity,
        mc=mc,
        ddl_registry_project=ddl_registry_project,
    )
    if not registry_ddl:
        return {
            "status": "failed",
            "error": f"DDL 模板未找到: {datasource_name}.{source_table_name}",
            "table": target_table,
        }

    existing_ddl = await _get_existing_ddl(bff, mcp, project, target_table, mc=mc)
    if existing_ddl:
        comparison = compare_ddl_structures(registry_ddl, existing_ddl)
        return {
            "status": "exists" if comparison["compatible"] else "incompatible",
            "table": target_table,
            "standard_ddl": registry_ddl,
            "comparison": comparison,
            "error": None
            if comparison["compatible"]
            else "Existing ODS table incompatible with registry DDL",
        }

    create_ddl = strip_leading_drop_table(inject_schema_prefix_in_ddl(registry_ddl, project))
    if mc is not None:
        res = await mc.execute_ddl(create_ddl)
        ok, err = res.success, res.error
    else:
        job_code = await bff.execute_sql_ida(create_ddl)
        ok = bool(job_code and await bff.wait_ida_job(job_code))
        err = getattr(bff, "last_error", "建表失败")
    if not ok:
        return {
            "status": "failed",
            "error": err or "建表失败",
            "table": target_table,
            "standard_ddl": registry_ddl,
        }

    return {
        "status": "created",
        "table": target_table,
        "standard_ddl": registry_ddl,
    }
