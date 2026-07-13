"""MaxCompute / BFF ODPS SQL helpers for ODS metadata queries."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_ida_query(bff: Any, sql: str) -> list[list[Any]] | None:
    """Execute SQL via BFF IDA interface and return bodyList rows."""
    if bff is None:
        return None
    job_code = await bff.execute_sql_ida(sql)
    if not job_code:
        logger.error("IDA 任务创建失败: %s", getattr(bff, "last_error", ""))
        return None
    if not await bff.wait_ida_job(job_code):
        logger.error("IDA 任务执行失败: %s", getattr(bff, "last_error", ""))
        return None
    result = await bff.get_query_result(job_code)
    body_list = (result or {}).get("bodyList") or []
    return body_list if body_list else None


async def run_maxcompute_query(sql: str) -> list[list[Any]] | None:
    """Run ODPS SELECT via MaxCompute pyodps. Return None if absent or failed."""
    from dataworks_agent.state import app_state

    mc = getattr(app_state, "_maxcompute_client", None)
    if mc is None:
        return None
    try:
        instance = await mc.submit_query(sql)
        result = await mc.wait_and_fetch(instance)
        return result.rows or None
    except Exception as exc:
        logger.warning("MaxCompute 查询失败，回退 BFF IDA: %s", exc)
        return None


async def run_odps_query(bff: Any, sql: str) -> list[list[Any]] | None:
    """Run ODPS SELECT through native clients: MaxCompute first, then BFF IDA."""
    body_list = await run_maxcompute_query(sql)
    if body_list:
        return body_list
    return await run_ida_query(bff, sql)
