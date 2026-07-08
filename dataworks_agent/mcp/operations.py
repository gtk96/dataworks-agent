"""建模专用 MCP 操作 — 封装 data-mcp 所有建模相关工具调用。"""

from __future__ import annotations

import logging
from typing import Any

from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)


async def _mcp() -> Any:
    pool = app_state.mcp_pool
    if pool is None:
        raise RuntimeError("MCP 连接池未初始化")
    return pool


async def execute_ddl(ddl: str) -> dict:
    """直接在 MC 执行 CREATE TABLE / ALTER TABLE。"""
    pool = await _mcp()
    result = await pool.call_tool("execute_ddl", {"ddl_sql": ddl})
    # MCP 可能返回纯文本结果
    if isinstance(result, str):
        return {"success": "error" not in result.lower(), "message": result}
    return result


async def check_column_roots(column_names: str) -> list[dict]:
    """字段词根校验 + 修正建议。"""
    pool = await _mcp()
    return await pool.call_tool("check_column_roots", {"column_names": column_names})


async def get_table_ddl(table_guid: str) -> str:
    """获取表 DDL 结构。"""
    pool = await _mcp()
    return await pool.call_tool("get_table_ddl", {"table_guid": table_guid})


async def list_tables(project: str, keyword: str = "") -> list[dict]:
    """按关键词搜索表（含中文注释匹配）。"""
    pool = await _mcp()
    return await pool.call_tool("list_tables", {"project": project, "keyword": keyword})


async def submit_query(sql: str) -> list[dict]:
    """ODPS SELECT 查询（IDA 接口，全账号有权限）。"""
    pool = await _mcp()
    return await pool.call_tool("submit_query", {"sql": sql})


async def get_query_result(query_id: str) -> dict:
    """获取 ODPS 查询结果。"""
    pool = await _mcp()
    return await pool.call_tool("get_query_result", {"query_id": query_id})


async def get_upstream_tasks(table_name: str) -> list[dict]:
    """查询产出表的调度任务（血缘）。"""
    pool = await _mcp()
    return await pool.call_tool("get_upstream_tasks", {"entity_guid": table_name})


async def get_node_detail(node_id: str) -> dict:
    """获取节点详情。"""
    pool = await _mcp()
    return await pool.call_tool("get_node_detail", {"node_id": node_id})


async def get_node_script(node_id: str) -> str:
    """获取节点脚本内容。"""
    pool = await _mcp()
    return await pool.call_tool("get_node_script", {"node_id": node_id})


async def get_current_user() -> dict:
    """获取当前 DataWorks 用户信息（含 Cookie 有效期）。"""
    pool = await _mcp()
    return await pool.call_tool("get_current_user", {})


async def count_table(table_full_name: str) -> int:
    """统计表的行数。"""
    sql = f"SELECT COUNT(*) AS cnt FROM {table_full_name}"
    result = await submit_query(sql)
    if result and isinstance(result, list):
        return int(result[0].get("cnt", 0))
    return 0
