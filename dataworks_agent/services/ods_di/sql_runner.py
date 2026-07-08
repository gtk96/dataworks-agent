"""IDA / MCP ODPS SQL execution helpers for ODS metadata queries."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


def _parse_tool_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"result": data}
    except json.JSONDecodeError:
        return {"raw": text}


def _coerce_tool_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = _parse_tool_json(raw)
        return parsed if parsed else {"raw": raw}
    return {}


def _parse_job_code(submit_raw: Any) -> str:
    data = _coerce_tool_payload(submit_raw)
    for key in ("job_code", "jobCode", "job_id"):
        val = data.get(key)
        if val:
            return str(val)
    text = str(submit_raw or "")
    match = re.search(r"job_code['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_-]+)", text, re.I)
    return match.group(1) if match else ""


def _parse_status(result_raw: Any) -> str:
    data = _coerce_tool_payload(result_raw)
    for key in ("status", "state"):
        val = data.get(key)
        if val:
            status = str(val).upper()
            return "FAILED" if status == "FAIL" else status
    upper = str(result_raw or "").upper()
    for status in ("SUCCESS", "FAILED", "RUNNING", "SUBMITTED"):
        if status in upper:
            return status
    return "UNKNOWN"


def _dict_rows_to_body_list(rows: list[dict[str, Any]]) -> list[list[Any]]:
    if not rows:
        return []
    keys = list(rows[0].keys())
    return [[row.get(key) for key in keys] for row in rows]


def _parse_mcp_body_list(result_raw: Any) -> list[list[Any]] | None:
    data = _coerce_tool_payload(result_raw)
    body_list = data.get("bodyList")
    if isinstance(body_list, list) and body_list:
        return body_list

    rows = data.get("rows")
    if isinstance(rows, list) and rows:
        if rows and isinstance(rows[0], dict):
            return _dict_rows_to_body_list(rows)
        if rows and isinstance(rows[0], list):
            return rows

    text = ""
    for key in ("result", "content"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            text = val.strip()
            break
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            if parsed and isinstance(parsed[0], dict):
                return _dict_rows_to_body_list(parsed)
            if parsed and isinstance(parsed[0], list):
                return parsed
    except json.JSONDecodeError:
        pass

    parsed_rows = list(csv.reader(io.StringIO(text)))
    if not parsed_rows:
        return None
    if len(parsed_rows) == 1:
        return [parsed_rows[0]]
    # CSV header + data rows (IDA 常见格式)
    return parsed_rows[1:]


async def _poll_mcp_query(mcp: Any, job_code: str, *, timeout_s: float = 180.0) -> Any:
    deadline = time.monotonic() + timeout_s
    delay = 0.8
    last: Any = ""
    while time.monotonic() < deadline:
        last = await mcp.call_tool(
            "get_query_result",
            {"job_code": job_code, "include_content": True},
        )
        status = _parse_status(last)
        if status in ("SUCCESS", "FAILED"):
            return last
        await asyncio.sleep(delay)
        delay = min(delay * 1.6, 8.0)
    return last or f"查询超时（job_code={job_code}）"


async def run_mcp_query(mcp: Any, sql: str) -> list[list[Any]] | None:
    """Execute SELECT via MCP submit_query + get_query_result polling."""
    if mcp is None:
        return None
    try:
        submit_raw = await mcp.call_tool("submit_query", {"sql": sql})
        job_code = _parse_job_code(submit_raw)
        if not job_code:
            logger.warning("MCP submit_query 未返回 job_code: %s", str(submit_raw)[:300])
            return None
        result_raw = await _poll_mcp_query(mcp, job_code)
        if _parse_status(result_raw) != "SUCCESS":
            logger.warning("MCP 查询失败: %s", str(result_raw)[:400])
            return None
        body_list = _parse_mcp_body_list(result_raw)
        if body_list:
            logger.info("MCP 查询成功，返回 %d 行", len(body_list))
        return body_list
    except Exception as exc:
        logger.warning("MCP submit_query 失败: %s", exc)
        return None


async def run_ida_query(bff: Any, sql: str) -> list[list[Any]] | None:
    """Execute SQL via BFF IDA interface and return bodyList rows."""
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
    """Run ODPS SELECT via MaxCompute pyodps (新底座). None if client absent/fails."""
    from dataworks_agent.state import app_state

    mc = getattr(app_state, "_maxcompute_client", None)
    if mc is None:
        return None
    try:
        instance = await mc.submit_query(sql)
        result = await mc.wait_and_fetch(instance)
        return result.rows or None
    except Exception as exc:
        logger.warning("MaxCompute 查询失败，回退 IDA/MCP: %s", exc)
        return None


async def run_odps_query(bff: Any, mcp: Any, sql: str) -> list[list[Any]] | None:
    """Run ODPS SELECT: MaxCompute pyodps 优先, 回退 BFF IDA, 再回退 MCP.

    迁移期三级链路: 新底座(pyodps) → 旧 IDA(bff) → MCP。
    MaxCompute client 从 app_state 取（迁移期注入），与 bff/mcp 入参并存。
    """
    body_list = await run_maxcompute_query(sql)
    if body_list:
        return body_list
    body_list = await run_ida_query(bff, sql)
    if body_list:
        return body_list
    return await run_mcp_query(mcp, sql)
