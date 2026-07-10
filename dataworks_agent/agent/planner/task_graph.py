"""任务依赖图"""
from __future__ import annotations

from typing import Any


class TaskGraph:
    """任务依赖图"""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[str, list[str]] = {}

    def add_node(self, node_id: str, **kwargs: Any) -> None:
        """添加节点"""
        self._nodes[node_id] = kwargs
        if node_id not in self._edges:
            self._edges[node_id] = []

    def add_edge(self, from_node: str, to_node: str) -> None:
        """添加边"""
        if from_node not in self._edges:
            self._edges[from_node] = []
        self._edges[from_node].append(to_node)

    def topological_sort(self) -> list[str]:
        """拓扑排序"""
        visited: set[str] = set()
        result: list[str] = []

        def dfs(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for next_node in self._edges.get(node, []):
                dfs(next_node)
            result.append(node)

        for node in self._nodes:
            dfs(node)

        return result
