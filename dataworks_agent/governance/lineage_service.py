"""Lineage code export service — BFS upstream trace + ZIP export."""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from dataworks_agent.governance.lineage_export import (
    MAX_DEPTH,
    MAX_NODES,
    build_archive,
    build_preview,
    extract_parent_table_name,
    make_lineage_node,
    make_root_node,
    prune_excluded,
)
from dataworks_agent.governance.lineage_models import (
    CollectedNode,
    DependencyEdge,
    ExportMeta,
    LineageNode,
    RootNode,
    TraversalResult,
)
from dataworks_agent.governance.sql_lineage import is_temp_table
from dataworks_agent.governance.table_name_parser import (
    build_table_guid,
    extract_code_text,
    extract_node_id,
    identify_layer_ext,
)

logger = logging.getLogger(__name__)


async def resolve_root_node(bff: Any, table_name: str, mc_project: str | None) -> RootNode:
    """Resolve root node via MCP → BFF upstream → BFF node search."""
    from dataworks_agent.mcp.operations import get_upstream_tasks as mcp_get_upstream

    # MCP 优先
    try:
        tasks = await mcp_get_upstream(table_name)
        if tasks:
            node_id = extract_node_id(tasks[0])
            if node_id:
                return make_root_node(node_id, table_name)
    except Exception as exc:
        logger.debug("MCP get_upstream_tasks 失败: %s", exc)

    # BFF get_upstream_tasks 回退
    guid = build_table_guid(table_name, mc_project)
    try:
        tasks = await bff.get_upstream_tasks(guid)
        if tasks:
            node_id = extract_node_id(tasks[0])
            if node_id:
                return make_root_node(node_id, table_name)
    except Exception as exc:
        logger.debug("BFF get_upstream_tasks 失败: %s", exc)

    # BFF 节点搜索回退（支持 Holo 节点）
    # Holo 节点命名格式: ods_hl_dataworks_holo__<表名>_<粒度>
    search_names = [table_name]
    if table_name.lower().startswith("ods_hl_"):
        # 尝试不同的 Holo 节点命名格式
        parts = table_name.split("__", 1)
        if len(parts) == 2:
            schema_table = parts[1]  # e.g., "s_order_hour"
            search_names.extend(
                [
                    f"ods_hl_dataworks_holo__{schema_table}",
                    f"ods_holo_cda__hl_sv_{schema_table}",
                ]
            )

    for search_name in search_names:
        try:
            nodes = await bff.get_node_list(search=search_name, force_refresh=True)
            for node in nodes:
                node_name = (node.get("nodeName") or node.get("name", "")).lower()
                if search_name.lower() in node_name or table_name.lower() in node_name:
                    node_id = extract_node_id(node)
                    if node_id:
                        return make_root_node(node_id, table_name)
        except Exception as exc:
            logger.debug("BFF get_node_list 搜索 '%s' 失败: %s", search_name, exc)

    raise HTTPException(status_code=404, detail=f"未找到表 {table_name} 的产出节点")


async def traverse_upstream(
    bff: Any,
    root: RootNode,
    env: str,
    excluded_node_ids: set[str] | None = None,
) -> TraversalResult:
    excluded = excluded_node_ids or set()
    nodes: dict[str, LineageNode] = {}
    edges: list[DependencyEdge] = []
    visited: set[str] = set()
    reached_limit = False

    root_node = make_lineage_node(root.node_id, root.table_name, 0)
    nodes[root.node_id] = root_node
    queue: deque[tuple[str, int]] = deque([(root.node_id, 0)])

    while queue:
        current_id, current_depth = queue.popleft()
        if current_id in visited:
            continue
        visited.add(current_id)

        current_node = nodes.get(current_id)
        if current_node is None:
            continue
        if current_node.layer == "ODS":
            continue
        if len(nodes) >= MAX_NODES or current_depth >= MAX_DEPTH:
            reached_limit = True
            continue

        parents = await bff.get_node_parents_by_depth(node_id=int(current_id), env=env)
        if parents is None:
            current_node.status = "error"
            current_node.error = "父依赖获取失败"
            continue

        for parent_record in parents:
            parent_id = extract_node_id(parent_record)
            if parent_id is None:
                continue
            parent_table = extract_parent_table_name(parent_record)

            if is_temp_table(parent_table or ""):
                current_node.is_truncation_point = True
                continue
            if parent_id in excluded:
                current_node.is_truncation_point = True
                continue
            if parent_id == current_id or parent_id in visited:
                continue

            edges.append(DependencyEdge(parent_node_id=parent_id, child_node_id=current_id))

            if parent_id not in nodes:
                if len(nodes) >= MAX_NODES:
                    reached_limit = True
                    current_node.is_truncation_point = True
                    continue
                nodes[parent_id] = LineageNode(
                    node_id=parent_id,
                    table_name=parent_table,
                    layer=identify_layer_ext(parent_table or ""),
                    depth=current_depth + 1,
                )
                queue.append((parent_id, current_depth + 1))

    return TraversalResult(nodes=nodes, edges=edges, reached_limit=reached_limit)


async def collect_node(bff: Any, node: LineageNode, env: str) -> CollectedNode:
    try:
        response = await bff.get_node_code(int(node.node_id), env=env)
        code_text = extract_code_text(response)
        if code_text is None or not code_text.strip():
            node.status = "missing_code"
            return CollectedNode(node=node, code_text=None)
        return CollectedNode(node=node, code_text=code_text)
    except Exception as exc:
        node.status = "error"
        node.error = str(exc)
        return CollectedNode(node=node, code_text=None)


async def collect_nodes_concurrent(
    bff: Any,
    nodes: dict[str, LineageNode],
    env: str,
    *,
    concurrency: int = 8,
) -> list[CollectedNode]:
    """v16 F6-7：并发拉所有节点代码，信号量限流避免一次打爆 BFF。

    MAX_NODES=500 全并发会爆 BFF；用 asyncio.Semaphore 限到默认 8 路。
    行为兼容 collect_node：每个节点仍是独立 try/except，失败只标自己 error。
    """
    import asyncio

    sem = asyncio.Semaphore(concurrency)

    async def _one(node: LineageNode) -> CollectedNode:
        async with sem:
            return await collect_node(bff, node, env)

    return await asyncio.gather(*(_one(n) for n in nodes.values()))


async def preview_lineage(
    bff: Any,
    *,
    table_name: str,
    mc_project: str | None = None,
    env: str = "prod",
) -> dict[str, Any]:
    root = await resolve_root_node(bff, table_name, mc_project)
    result = await traverse_upstream(bff, root, env)
    return build_preview(root, result)


async def export_lineage(
    bff: Any,
    *,
    table_name: str,
    mc_project: str | None = None,
    env: str = "prod",
    excluded_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    excluded = set(excluded_node_ids or [])
    root = await resolve_root_node(bff, table_name, mc_project)
    result = await traverse_upstream(bff, root, env, excluded_node_ids=excluded)
    before_count = len(result.nodes)
    if excluded:
        result = prune_excluded(result, root.node_id, excluded)
    excluded_count = before_count - len(result.nodes)

    # v16 F6-7: collect 阶段由串行 await list 改并发 gather（信号量限流）
    collected = await collect_nodes_concurrent(bff, result.nodes, env)
    meta = ExportMeta(
        root_table=root.table_name,
        root_node_id=root.node_id,
        generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        node_total=len(result.nodes),
        truncation_count=sum(1 for n in result.nodes.values() if n.is_truncation_point),
        reached_limit=result.reached_limit,
    )
    zip_path = build_archive(collected, result.edges, meta)

    return {
        "root_table": root.table_name,
        "root_node_id": root.node_id,
        "file_path": str(zip_path),
        "summary": {
            "node_total": len(result.nodes),
            "truncation_count": meta.truncation_count,
            "failed_count": sum(1 for c in collected if c.node.status == "error"),
            "missing_code_count": sum(1 for c in collected if c.node.status == "missing_code"),
            "excluded_count": excluded_count,
            "reached_limit": result.reached_limit,
        },
    }
