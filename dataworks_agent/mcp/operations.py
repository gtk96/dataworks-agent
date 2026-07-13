"""原生 DataWorks 操作兼容门面。

模块路径为兼容现有建模调用保留；实现只使用 AK/SK MaxCompute、DataWorks
OpenAPI 与 Cookie BFF，不连接外部 data-mcp 服务。
"""

from __future__ import annotations

import json
from typing import Any

from dataworks_agent.api_clients.destructive_guard import guard_sql
from dataworks_agent.state import app_state


def _require_client(name: str, client: Any) -> Any:
    if client is None:
        raise RuntimeError(f"{name} 客户端未初始化")
    return client


def _table_parts(table_ref: str) -> tuple[str | None, str]:
    value = str(table_ref or "").strip()
    if value.lower().startswith("odps."):
        value = value[5:]
    parts = value.split(".")
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, value


def _to_map(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    method = getattr(value, "to_map", None)
    if callable(method):
        mapped = method()
        return mapped if isinstance(mapped, dict) else {"result": mapped}
    return {"result": value}


async def execute_ddl(ddl: str, guarded: bool = True) -> dict:
    """通过 AK/SK MaxCompute 执行 DDL。"""
    if guarded:
        guard_sql(ddl)
    mc = _require_client("MaxCompute", getattr(app_state, "_maxcompute_client", None))
    result = await mc.execute_ddl(ddl)
    return {
        "success": bool(getattr(result, "success", False)),
        "instance_id": str(getattr(result, "instance_id", "") or ""),
        "error": getattr(result, "error", None),
    }


async def check_column_roots(column_names: str) -> list[dict]:
    """使用本地同步词根缓存校验字段，保持旧调用返回结构。"""
    from dataworks_agent.standards.loader import valid_root_tokens, validate_field_roots

    roots = valid_root_tokens()
    results = []
    for name in (part.strip() for part in column_names.split(",")):
        if not name:
            continue
        invalid = validate_field_roots(name, roots)
        results.append(
            {
                "column_name": name,
                "is_valid": not invalid,
                "invalid_parts": invalid,
                "suggested_name": None,
            }
        )
    return results


async def get_table_ddl(table_guid: str) -> str:
    """优先通过 MaxCompute 元数据读取 DDL，Cookie BFF 兜底。"""
    project, table = _table_parts(table_guid)
    mc = getattr(app_state, "_maxcompute_client", None)
    if mc is not None and table:
        ddl = await mc.get_table_ddl(table, project=project)
        if ddl:
            return ddl
    bff = getattr(app_state, "_bff_client", None)
    if bff is not None:
        ddl = await bff.get_creation_ddl(table_guid)
        if ddl:
            return ddl
    return ""


async def list_tables(project: str, keyword: str = "") -> list[dict]:
    """通过 Cookie BFF 自由搜索表，并按项目过滤。"""
    bff = _require_client("DataWorks BFF", getattr(app_state, "_bff_client", None))
    rows = await bff.search_tables(keyword)
    return [
        row
        for row in rows or []
        if not project or str(row.get("project") or row.get("schema") or "") == project
    ]


async def submit_query(sql: str) -> list[dict]:
    """通过 AK/SK MaxCompute 执行查询并返回字典行。"""
    guard_sql(sql)
    mc = _require_client("MaxCompute", getattr(app_state, "_maxcompute_client", None))
    instance = await mc.submit_query(sql)
    result = await mc.wait_and_fetch(instance)
    columns = list(getattr(result, "columns", []) or [])
    rows = list(getattr(result, "rows", []) or [])
    if columns:
        return [dict(zip(columns, row, strict=False)) for row in rows]
    return [{str(index): value for index, value in enumerate(row)} for row in rows]


async def get_query_result(query_id: str) -> dict:
    """兼容旧 BFF 查询任务结果读取。"""
    bff = _require_client("DataWorks BFF", getattr(app_state, "_bff_client", None))
    return await bff.get_query_result(query_id)


async def get_upstream_tasks(table_name: str) -> list[dict]:
    """通过 Cookie BFF 获取表上游任务。"""
    bff = _require_client("DataWorks BFF", getattr(app_state, "_bff_client", None))
    return await bff.get_upstream_tasks(table_name)


async def get_node_detail(node_id: str) -> dict:
    """通过 DataWorks OpenAPI 获取节点详情。"""
    client = _require_client("DataWorks OpenAPI", getattr(app_state, "_openapi_client", None))
    return _to_map(await client.get_node(node_id))


async def get_node_script(node_id: str) -> str:
    """优先从 OpenAPI FlowSpec 解析节点脚本，Cookie BFF 兜底。"""
    client = getattr(app_state, "_openapi_client", None)
    if client is not None:
        payload = _to_map(await client.get_node(node_id))
        node = payload.get("body", {}).get("Node") or payload.get("Body", {}).get("Node")
        if not node:
            node = payload.get("Node") or payload.get("node") or {}
        spec = node.get("Spec") or node.get("spec") if isinstance(node, dict) else ""
        if isinstance(spec, str) and spec:
            try:
                spec = json.loads(spec)
            except json.JSONDecodeError:
                spec = {}
        if isinstance(spec, dict):
            nodes = spec.get("spec", {}).get("nodes") or []
            if nodes:
                content = nodes[0].get("script", {}).get("content")
                if isinstance(content, str):
                    return content
    bff = _require_client("DataWorks BFF", getattr(app_state, "_bff_client", None))
    raw = await bff.get_node_code(int(node_id))
    if isinstance(raw, dict):
        return str(raw.get("content") or raw.get("code") or "")
    return str(raw or "")


async def get_current_user() -> dict:
    """验证当前 Cookie BFF 会话；外部 MCP 用户接口已移除。"""
    bff = _require_client("DataWorks BFF", getattr(app_state, "_bff_client", None))
    await bff._refresh_csrf()
    return {"authenticated": True, "provider": "cookie-bff"}


async def count_table(table_full_name: str) -> int:
    """统计表的行数。"""
    from dataworks_agent.schemas import assert_safe_table_name

    for part in table_full_name.split("."):
        assert_safe_table_name(part)
    result = await submit_query(f"SELECT COUNT(*) AS cnt FROM {table_full_name}")
    return int(result[0].get("cnt", 0)) if result else 0
