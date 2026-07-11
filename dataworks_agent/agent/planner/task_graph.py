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
        # 确保两个节点都存在
        if from_node not in self._nodes:
            self.add_node(from_node)
        if to_node not in self._nodes:
            self.add_node(to_node)

        self._edges[from_node].append(to_node)

    def validate(self) -> bool:
        """验证图是否有效（无循环）"""
        try:
            self.topological_sort()
            return True
        except ValueError:
            return False

    def topological_sort(self) -> list[str]:
        """拓扑排序（检测循环）"""
        visited: set[str] = set()
        result: list[str] = []
        in_progress: set[str] = set()

        def dfs(node: str) -> None:
            if node in in_progress:
                raise ValueError(f"检测到循环依赖: {node}")
            if node in visited:
                return

            in_progress.add(node)
            visited.add(node)

            for next_node in self._edges.get(node, []):
                dfs(next_node)

            in_progress.remove(node)
            result.insert(0, node)  # 插入到开头，确保依赖在前

        for node in self._nodes:
            if node not in visited:
                dfs(node)

        return result
