"""依赖解析器 — 验证任务依赖关系，检测循环依赖。"""

from __future__ import annotations


class CycleDetectedError(Exception):
    """循环依赖检测到。"""

    pass


class DependencyResolver:
    """任务依赖关系解析器 — 祖先校验 + 环检测。"""

    def __init__(self):
        self._graph: dict[str, set[str]] = {}
        self._reverse: dict[str, set[str]] = {}

    def add_dependency(self, upstream: str, downstream: str) -> None:
        """添加依赖: downstream 依赖 upstream。"""
        if upstream not in self._graph:
            self._graph[upstream] = set()
        self._graph[upstream].add(downstream)

        if downstream not in self._reverse:
            self._reverse[downstream] = set()
        self._reverse[downstream].add(upstream)

        # 检查新增边是否引入环
        if self._has_cycle_from(downstream):
            # 回滚
            self._graph[upstream].discard(downstream)
            self._reverse[downstream].discard(upstream)
            raise CycleDetectedError(f"添加 {upstream} → {downstream} 会引入循环依赖")

    def _has_cycle_from(self, start: str) -> bool:
        """DFS 检测从 start 出发是否存在环。"""
        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(node: str) -> bool:
            if node in stack:
                return True
            if node in visited:
                return False
            visited.add(node)
            stack.add(node)
            for neighbor in self._graph.get(node, set()):
                if dfs(neighbor):
                    return True
            stack.discard(node)
            return False

        return dfs(start)

    def get_upstream_chain(self, node: str, max_depth: int = 10) -> list[str]:
        """获取节点的上游依赖链（拓扑排序）。"""
        result: list[str] = []
        visited: set[str] = set()

        def traverse(n: str, depth: int) -> None:
            if depth > max_depth or n in visited:
                return
            visited.add(n)
            for upstream in self._reverse.get(n, set()):
                traverse(upstream, depth + 1)
            result.append(n)

        traverse(node, 0)
        return list(reversed(result))
