"""LineageTracker — 血缘追踪（BFF listLineage 优先 + MCP DFS DAG 构建 + 环检测）。"""

from __future__ import annotations

import logging
import time

from dataworks_agent.schemas import LineageGraph, LineageNode

logger = logging.getLogger(__name__)

LINEAGE_CACHE_TTL = 86400  # 24 小时


class LineageTracker:
    """表血缘关系追踪器。"""

    def __init__(self) -> None:
        self._cache: dict[str, list[LineageNode]] = {}
        self._cache_times: dict[str, float] = {}

    def _cache_key(self, table_name: str, mc_project: str | None) -> str:
        return f"{table_name}|{mc_project or ''}"

    async def trace_upstream(
        self, table_name: str, mc_project: str | None = None
    ) -> list[LineageNode]:
        """追踪上游依赖 — 优先 BFF，再 MCP，最后读本地缓存。"""
        key = self._cache_key(table_name, mc_project)
        if key in self._cache and (time.time() - self._cache_times.get(key, 0)) < LINEAGE_CACHE_TTL:
            return self._cache[key]

        from dataworks_agent.governance.table_guid_resolver import resolve_table_guid
        from dataworks_agent.mcp.operations import get_upstream_tasks
        from dataworks_agent.state import app_state

        nodes: list[LineageNode] = []
        bff = getattr(app_state, "_bff_client", None)

        if bff is not None:
            try:
                guid, _ = await resolve_table_guid(table_name, mc_project, bff=bff)
                data = await bff.list_lineage(guid)
                if data:
                    up_data = data.get("up", {})
                    if isinstance(up_data, dict):
                        for entity in up_data.get("entityList", []):
                            if not isinstance(entity, dict):
                                continue
                            upstream_table = (
                                entity.get("tableName")
                                or str(entity.get("entityGuid", "")).split(".")[-1]
                            )
                            if upstream_table:
                                nodes.append(
                                    LineageNode(
                                        table=table_name,
                                        upstream_table=upstream_table,
                                        task_id=str(entity.get("taskId", entity.get("nodeId", ""))),
                                        task_name=entity.get(
                                            "taskName", entity.get("nodeName", "")
                                        ),
                                    )
                                )
                if not nodes:
                    tasks = await bff.get_upstream_tasks(guid)
                    for task in tasks or []:
                        if not isinstance(task, dict):
                            continue
                        upstream_table = (
                            task.get("output_table")
                            or task.get("table_name")
                            or task.get("tableName")
                            or ""
                        )
                        nodes.append(
                            LineageNode(
                                table=table_name,
                                upstream_table=str(upstream_table),
                                task_id=str(task.get("task_id", task.get("taskId", ""))),
                                task_name=task.get("task_name", task.get("taskName", "")),
                            )
                        )
            except Exception as exc:
                logger.warning("BFF 上游追溯失败: %s", exc)

        if not nodes:
            try:
                guid, _ = await resolve_table_guid(table_name, mc_project, bff=bff)
                result = await get_upstream_tasks(guid)
                tasks = result.get("tasks", []) if isinstance(result, dict) else result
                for task in tasks or []:
                    if isinstance(task, str):
                        continue
                    nodes.append(
                        LineageNode(
                            table=table_name,
                            upstream_table=task.get("output_table", task.get("table_name", "")),
                            task_id=str(task.get("task_id", "")),
                            task_name=task.get("task_name", ""),
                        )
                    )
            except Exception as exc:
                logger.warning("MCP 上游追溯失败: %s", exc)

        self._cache[key] = nodes
        self._cache_times[key] = time.time()
        return nodes

    async def build_lineage_graph(
        self,
        root_table: str,
        max_depth: int = 3,
        max_nodes: int = 200,
        mc_project: str | None = None,
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

            upstream = await self.trace_upstream(table, mc_project)
            for node in upstream:
                if not node.upstream_table:
                    continue
                graph.nodes.append(node)
                graph.edges.append({"from": node.upstream_table, "to": table})
                await dfs(node.upstream_table, depth + 1)

            path_stack.pop()

        await dfs(root_table, 1)
        return graph
