"""Agent 单元测试 — 端到端建模与对话查询。"""

import pytest

from dataworks_agent.runtime.agent import Agent, AgentRequest, AgentResponse


@pytest.fixture
def agent():
    """创建 Agent 实例。"""
    return Agent()


@pytest.mark.asyncio
async def test_process_modeling(agent):
    """处理建模请求。"""
    request = AgentRequest(
        request_type="modeling",
        content="创建一个 DWD 表",
        context={
            "source_table": "ods_ord_order_hour",
            "target_layer": "DWD",
            "domain": "ord",
            "entity": "order_detail",
            "update_method": "day",
        },
    )
    result = await agent.process(request)

    assert result.success is True
    assert result.response_type == "proposal"
    assert result.needs_approval is True


@pytest.mark.asyncio
async def test_process_query(agent):
    """处理查询请求。"""
    request = AgentRequest(
        request_type="query",
        content="查询订单数量",
        context={"metric_id": "order_count"},
    )
    result = await agent.process(request)

    assert result.success is True
    assert result.response_type == "result"


@pytest.mark.asyncio
async def test_process_clarification(agent):
    """处理口径澄清请求。"""
    request = AgentRequest(
        request_type="clarification",
        content="澄清订单数量口径",
        context={
            "metric_id": "nonexistent_metric",
            "expected_caliber": "订单数量",
        },
    )
    result = await agent.process(request)

    assert result.success is True
    assert result.response_type == "clarification"


@pytest.mark.asyncio
async def test_process_unknown_type(agent):
    """处理未知请求类型。"""
    request = AgentRequest(
        request_type="unknown",
        content="测试",
    )
    result = await agent.process(request)

    assert result.success is False
    assert result.response_type == "error"


def test_agent_request_post_init():
    """AgentRequest 初始化。"""
    request = AgentRequest(request_type="modeling", content="test")
    assert request.request_type == "modeling"
    assert request.context == {}


def test_agent_response_post_init():
    """AgentResponse 初始化。"""
    response = AgentResponse(success=True, response_type="result")
    assert response.success is True
    assert response.errors == []
