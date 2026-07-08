"""Semantic_Graph — 语义知识图谱。

实现 Requirement 15：融合血缘 + 语义 + 元数据 + 质量信号。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TableContext:
    """表上下文 — 包含血缘、语义、元数据和质量信号。"""

    table_name: str
    layer: str = ""
    domain: str = ""
    update_mode: str = ""

    # 血缘
    upstream_tables: list[str] = field(default_factory=list)
    downstream_tables: list[str] = field(default_factory=list)

    # 语义
    semantic_definition: dict[str, Any] | None = None
    caliber: str = ""

    # 元数据
    columns: list[dict[str, Any]] = field(default_factory=list)
    comment: str = ""

    # 质量信号
    quality_signal: dict[str, Any] | None = None


@dataclass
class GraphEdge:
    """图谱边 — 表示表间关系。"""

    source: str
    target: str
    edge_type: str  # lineage / semantic / dependency
    metadata: dict[str, Any] = field(default_factory=dict)


class SemanticGraph:
    """语义知识图谱。

    融合 Lineage_Service 血缘 + Semantic_Layer 业务含义 + DataWorks 元数据 + Quality_Signal。
    """

    def __init__(self) -> None:
        self._edges: list[GraphEdge] = []
        self._table_contexts: dict[str, TableContext] = {}

    def get_table_context(self, table_name: str) -> TableContext | None:
        """获取表上下文。"""
        # 先从缓存查找
        if table_name in self._table_contexts:
            return self._table_contexts[table_name]

        # 构建上下文
        context = self._build_table_context(table_name)
        if context:
            self._table_contexts[table_name] = context

        return context

    def _build_table_context(self, table_name: str) -> TableContext | None:
        """构建表上下文。"""
        # 从语义层获取语义定义
        semantic_def = self._get_semantic_definition(table_name)

        # 从血缘获取上下游
        upstream, downstream = self._get_lineage(table_name)

        # 获取质量信号
        quality_signal = self._get_quality_signal(table_name)

        # 反推分层和域名
        layer = self._infer_layer(table_name)
        domain = self._infer_domain(table_name)

        return TableContext(
            table_name=table_name,
            layer=layer,
            domain=domain,
            upstream_tables=upstream,
            downstream_tables=downstream,
            semantic_definition=semantic_def,
            caliber=semantic_def.get("caliber", "") if semantic_def else "",
            quality_signal=quality_signal,
        )

    def _get_semantic_definition(self, table_name: str) -> dict[str, Any] | None:
        """获取语义定义。"""
        from dataworks_agent.semantic.layer import SemanticLayer

        layer = SemanticLayer()
        definition = layer.get_metric_definition(table_name)
        if definition:
            return definition.body
        return None

    def _get_lineage(self, table_name: str) -> tuple[list[str], list[str]]:
        """获取血缘关系。"""
        upstream = []
        downstream = []

        for edge in self._edges:
            if edge.target == table_name and edge.edge_type == "lineage":
                upstream.append(edge.source)
            elif edge.source == table_name and edge.edge_type == "lineage":
                downstream.append(edge.target)

        return upstream, downstream

    def _get_quality_signal(self, table_name: str) -> dict[str, Any] | None:
        """获取质量信号。"""
        from dataworks_agent.semantic.layer import SemanticLayer

        layer = SemanticLayer()
        signal = layer.get_quality_signal(table_name)
        return {
            "freshness": signal.freshness,
            "completeness": signal.completeness,
            "uniqueness": signal.uniqueness,
            "quality_status": signal.quality_status,
        }

    def _infer_layer(self, table_name: str) -> str:
        """反推分层。"""
        from dataworks_agent.governance.table_name_parser import identify_layer

        return identify_layer(table_name)

    def _infer_domain(self, table_name: str) -> str:
        """反推域名。"""
        # 简化实现：从表名提取域名
        parts = table_name.split("_")
        if len(parts) >= 3:
            return parts[1]  # 第二个部分通常是域名
        return ""

    def add_edge(self, edge: GraphEdge) -> None:
        """添加边。"""
        self._edges.append(edge)

    def get_upstream(self, table_name: str) -> list[str]:
        """获取上游表。"""
        upstream, _ = self._get_lineage(table_name)
        return upstream

    def get_downstream(self, table_name: str) -> list[str]:
        """获取下游表。"""
        _, downstream = self._get_lineage(table_name)
        return downstream

    def bootstrap_from_reverse_modeling(self, results: list[dict[str, Any]]) -> int:
        """从逆向建模结果 bootstrap。"""
        count = 0

        for result in results:
            table_name = result.get("table_name", "")
            upstream = result.get("upstream_tables", [])
            downstream = result.get("downstream_tables", [])

            # 添加血缘边
            for upstream_table in upstream:
                edge = GraphEdge(
                    source=upstream_table,
                    target=table_name,
                    edge_type="lineage",
                )
                self.add_edge(edge)
                count += 1

            for downstream_table in downstream:
                edge = GraphEdge(
                    source=table_name,
                    target=downstream_table,
                    edge_type="lineage",
                )
                self.add_edge(edge)
                count += 1

        logger.info("从逆向建模结果 bootstrap %d 条边", count)
        return count
