"""LineageTracker — 血缘追踪（MCP get_upstream_tasks + DFS DAG 构建 + 环检测）。"""

from __future__ import annotations

import logging

from dataworks_agent.schemas import LineageGraph, LineageNode

logger = logging.getLogger(__name__)

LINEAGE_CACHE_TTL = 86400  # 24 小时


class LineageTracker:
    """表血缘关系追踪器。"""

    def __init__(self) -> None:
        self._cache: dict[str, list[LineageNode]] = {}
        self._cache_times: dict[str, float] = {}

    async def trace_upstream(self, table_name: str) -> list[LineageNode]:
        """追踪上游依赖 — 优先本地缓存。"""
        # 检查缓存
        import time

        if (
            table_name in self._cache
            and (time.time() - self._cache_times.get(table_name, 0)) < LINEAGE_CACHE_TTL
        ):
            return self._cache[table_name]

        from dataworks_agent.governance.table_name_parser import build_table_guid
        from dataworks_agent.mcp.operations import get_upstream_tasks

        # 构建正确的表 GUID
        try:
            guid = build_table_guid(table_name)
        except Exception:
            guid = table_name

        try:
            result = await get_upstream_tasks(guid)
        except Exception as e:
            logger.warning("获取上游任务失败: %s", e)
            return []

        # MCP 返回格式: {"tasks": [...], "next_action": "..."}
        tasks = []
        if isinstance(result, dict):
            tasks = result.get("tasks", [])
        elif isinstance(result, list):
            tasks = result

        nodes = []
        for task in tasks or []:
            if isinstance(task, str):
                # 如果是字符串，跳过
                continue
            nodes.append(
                LineageNode(
                    table=table_name,
                    upstream_table=task.get("output_table", task.get("table_name", "")),
                    task_id=str(task.get("task_id", "")),
                    task_name=task.get("task_name", ""),
                )
            )

        self._cache[table_name] = nodes
        self._cache_times[table_name] = time.time()
        return nodes

    async def build_lineage_graph(
        self, root_table: str, max_depth: int = 3, max_nodes: int = 200
    ) -> LineageGraph:
        """构建血缘 DAG 图 — DFS 深度优先 + 环检测。"""
        graph = LineageGraph()
        visited: set[str] = set()
        path_stack: list[str] = []

        async def dfs(table: str, depth: int) -> None:
            if depth > max_depth or len(visited) >= max_nodes:
                return
            if table in path_stack:
                graph.cycles.append(path_stack.copy())
                return
            if table in visited:
                return

            visited.add(table)
            path_stack.append(table)

            upstream = await self.trace_upstream(table)
            for node in upstream:
                graph.nodes.append(node)
                graph.edges.append({"from": node.upstream_table, "to": table})
                await dfs(node.upstream_table, depth + 1)

            path_stack.pop()

        await dfs(root_table, 1)
        return graph
