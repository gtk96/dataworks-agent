"""SemanticGraph 单元测试 — 语义知识图谱。"""

import pytest

from dataworks_agent.semantic.graph import GraphEdge, SemanticGraph, TableContext


@pytest.fixture
def graph():
    """创建 SemanticGraph 实例。"""
    return SemanticGraph()


def test_get_table_context_not_found(graph):
    """获取表上下文 — 不存在的表。"""
    # 由于没有真实数据，返回 None 或空上下文
    context = graph.get_table_context("nonexistent_table")
    # 可能返回 None 或空上下文
    assert context is None or isinstance(context, TableContext)


def test_add_edge(graph):
    """添加边。"""
    edge = GraphEdge(
        source="ods_ord_order_hour",
        target="dwd_ord_order_day",
        edge_type="lineage",
    )
    graph.add_edge(edge)
    assert len(graph._edges) == 1


def test_get_upstream(graph):
    """获取上游表。"""
    # 添加边
    graph.add_edge(
        GraphEdge(source="ods_ord_order_hour", target="dwd_ord_order_day", edge_type="lineage")
    )
    graph.add_edge(
        GraphEdge(source="ods_ord_customer", target="dwd_ord_order_day", edge_type="lineage")
    )

    upstream = graph.get_upstream("dwd_ord_order_day")
    assert "ods_ord_order_hour" in upstream
    assert "ods_ord_customer" in upstream


def test_get_downstream(graph):
    """获取下游表。"""
    # 添加边
    graph.add_edge(
        GraphEdge(source="dwd_ord_order_day", target="dws_ord_order_summary", edge_type="lineage")
    )

    downstream = graph.get_downstream("dwd_ord_order_day")
    assert "dws_ord_order_summary" in downstream


def test_bootstrap_from_reverse_modeling(graph):
    """从逆向建模结果 bootstrap。"""
    results = [
        {
            "table_name": "dwd_ord_order_day",
            "upstream_tables": ["ods_ord_order_hour", "ods_ord_customer"],
            "downstream_tables": ["dws_ord_order_summary"],
        }
    ]

    count = graph.bootstrap_from_reverse_modeling(results)
    assert count == 3  # 2 upstream + 1 downstream


def test_table_context_post_init():
    """TableContext 初始化。"""
    context = TableContext(table_name="test_table")
    assert context.table_name == "test_table"
    assert context.upstream_tables == []
    assert context.downstream_tables == []


def test_graph_edge_post_init():
    """GraphEdge 初始化。"""
    edge = GraphEdge(source="a", target="b", edge_type="lineage")
    assert edge.source == "a"
    assert edge.target == "b"
    assert edge.metadata == {}
