"""调度配置服务 — 自动生成 Cron 表达式 + 节点依赖链。

调度规则：
1. ODS (day) → DWD (day, depends on ODS) → DIM (day, depends on ODS)
   → DWS (day, depends on DWD + DIM) → ADS (day, depends on DWS)
2. 天级调度：按任务数量自动分配分钟槽位（避免并发冲突）
3. 小时级调度：同上
4. 分钟级调度：用户自定义
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dataworks_agent.naming.schedule import generate_cron, get_cycle_type

logger = logging.getLogger(__name__)


@dataclass
class ScheduleNode:
    """单个节点的调度配置。"""

    node_name: str
    table_name: str
    cron: str
    cycle_type: str
    depends_on: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    resource_group: str = ""
    retry_times: int = 0
    retry_interval: int = 0


@dataclass
class DependencyChain:
    """依赖链 — 节点间的调度依赖关系。"""

    nodes: list[ScheduleNode] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (child, parent)

    def add_node(self, node: ScheduleNode) -> None:
        self.nodes.append(node)

    def add_edge(self, child: str, parent: str) -> None:
        self.edges.append((child, parent))

    def get_dependencies(self, node_name: str) -> list[str]:
        """获取指定节点的依赖列表。"""
        return [parent for child, parent in self.edges if child == node_name]

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "nodes": [
                {
                    "node_name": n.node_name,
                    "table_name": n.table_name,
                    "cron": n.cron,
                    "cycle_type": n.cycle_type,
                    "depends_on": n.depends_on,
                    "parameters": n.parameters,
                }
                for n in self.nodes
            ],
            "edges": [{"child": c, "parent": p} for c, p in self.edges],
        }


class SchedulePlanner:
    """
    自动生成调度配置。

    工作流程：
    1. 根据分层信息生成调度计划
    2. 自动分配 Cron 分钟槽位
    3. 构建节点依赖链
    """

    # 分层顺序（决定依赖方向）
    LAYER_ORDER = ["ods", "dwd", "dim", "dws", "ads"]

    def __init__(self, default_minute_slot: int | None = None) -> None:
        self._default_minute_slot = default_minute_slot

    def plan_full_pipeline(
        self,
        layers: list[str],
        tables: dict[str, str],  # {layer: table_name}
        granularity: str = "day",
        minute_slots: dict[str, int] | None = None,
    ) -> DependencyChain:
        """
        为全链路建模生成完整的调度计划。

        Args:
            layers: 分层列表，如 ["ods", "dwd", "dim", "dws"]
            tables: 层→表名映射
            granularity: 调度粒度 (day | hour)
            minute_slots: 自定义分钟槽位 {layer: minute}

        Returns:
            依赖链
        """
        chain = DependencyChain()

        # 按分层顺序排序
        sorted_layers = [
            l for l in self.LAYER_ORDER if l in layers
        ]

        # 生成 Cron
        cron = generate_cron(granularity, minute=self._default_minute_slot)
        cycle_type = get_cycle_type(granularity)

        # 记录已创建的节点名
        created_tables: list[str] = []

        for layer in sorted_layers:
            table_name = tables.get(layer, "")
            if not table_name:
                continue

            # 确定依赖
            depends_on: list[str] = []
            for prev_layer in reversed(sorted_layers[:sorted_layers.index(layer)]):
                prev_table = tables.get(prev_layer)
                if prev_table and prev_table in created_tables:
                    depends_on.append(prev_table)

            # 生成 Cron（每个层可以有独立的分钟槽位）
            layer_minute = (minute_slots or {}).get(layer)
            if layer_minute is not None:
                layer_cron = generate_cron(granularity, minute=layer_minute)
            else:
                layer_cron = cron

            node = ScheduleNode(
                node_name=table_name,
                table_name=table_name,
                cron=layer_cron,
                cycle_type=cycle_type,
                depends_on=depends_on,
            )
            chain.add_node(node)
            created_tables.append(table_name)

            # 添加依赖边
            for parent in depends_on:
                chain.add_edge(table_name, parent)

        return chain

    def plan_simple_dependency(
        self,
        source_table: str,
        target_table: str,
        granularity: str = "day",
        source_minute: int | None = None,
        target_minute: int | None = None,
    ) -> DependencyChain:
        """
        简化的两节点依赖链（ODS→DWD 常见场景）。

        Args:
            source_table: 源表名
            target_table: 目标表名
            granularity: 调度粒度
            source_minute: 源表调度分钟
            target_minute: 目标表调度分钟

        Returns:
            依赖链
        """
        chain = DependencyChain()

        # 源节点
        source_cron = generate_cron(granularity, minute=source_minute or 0)
        source_node = ScheduleNode(
            node_name=source_table,
            table_name=source_table,
            cron=source_cron,
            cycle_type=get_cycle_type(granularity),
        )
        chain.add_node(source_node)

        # 目标节点（依赖源节点）
        target_cron = generate_cron(granularity, minute=target_minute or 30)
        target_node = ScheduleNode(
            node_name=target_table,
            table_name=target_table,
            cron=target_cron,
            cycle_type=get_cycle_type(granularity),
            depends_on=[source_table],
        )
        chain.add_node(target_node)
        chain.add_edge(target_table, source_table)

        return chain

    def auto_distribute_minutes(
        self,
        layer: str,
        task_count: int,
        granularity: str = "day",
    ) -> dict[int, int]:
        """
        为同层多个任务自动分配分钟槽位。

        Args:
            layer: 分层名称
            task_count: 任务数量
            granularity: 调度粒度

        Returns:
            {task_index: minute_slot}
        """
        from dataworks_agent.naming.schedule import auto_distribute

        slots: dict[int, int] = {}
        for i in range(task_count):
            slot = auto_distribute(i, task_count, granularity)
            slots[i] = slot["minute"]
        return slots


# ── 单例 ──────────────────────────────────────────────────────────

_planner_instance: SchedulePlanner | None = None


def get_schedule_planner() -> SchedulePlanner:
    """获取调度规划器单例。"""
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = SchedulePlanner()
    return _planner_instance
