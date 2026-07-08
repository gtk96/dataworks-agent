"""ReverseModelingFlow 单元测试 — 逆向建模流程。"""

import pytest

from dataworks_agent.runtime.reverse_flow import (
    ReverseModelingFlow,
    ReverseModelingRequest,
    ReverseModelingResult,
)


@pytest.fixture
def flow():
    """创建 ReverseModelingFlow 实例。"""
    return ReverseModelingFlow()


@pytest.mark.asyncio
async def test_reverse_from_table(flow):
    """从表逆向抽取。"""
    request = ReverseModelingRequest(
        source_type="table",
        source_value="dwd_ord_order_day",
        project="dataworks",
    )
    result = await flow.execute(request)

    assert result.success is True
    assert result.table_name == "dwd_ord_order_day"
    assert result.layer == "DWD"
    assert len(result.steps) > 0


@pytest.mark.asyncio
async def test_reverse_from_sql(flow):
    """从 SQL 逆向抽取。"""
    request = ReverseModelingRequest(
        source_type="sql",
        source_value="SELECT id FROM ods_ord_order_hour WHERE dt = '${bizdate}'",
    )
    result = await flow.execute(request)

    assert result.success is True
    assert len(result.steps) > 0


@pytest.mark.asyncio
async def test_reverse_from_node(flow):
    """从节点逆向抽取。"""
    request = ReverseModelingRequest(
        source_type="node",
        source_value="node_12345",
    )
    result = await flow.execute(request)

    assert result.success is True
    assert len(result.steps) > 0


@pytest.mark.asyncio
async def test_reverse_with_lineage(flow):
    """逆向抽取包含血缘。"""
    request = ReverseModelingRequest(
        source_type="table",
        source_value="dwd_ord_order_day",
        include_lineage=True,
    )
    result = await flow.execute(request)

    assert result.success is True
    assert "get_lineage" in [s["step"] for s in result.steps]


@pytest.mark.asyncio
async def test_reverse_with_semantics(flow):
    """逆向抽取包含语义候选。"""
    request = ReverseModelingRequest(
        source_type="table",
        source_value="dwd_ord_order_day",
        include_semantics=True,
    )
    result = await flow.execute(request)

    assert result.success is True
    assert len(result.semantic_candidates) > 0


def test_reverse_result_post_init():
    """ReverseModelingResult 初始化。"""
    result = ReverseModelingResult(success=True, source_type="table")
    assert result.source_type == "table"
    assert result.errors == []
