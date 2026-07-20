"""多 Agent 协调核心集成测试。"""

import pytest

from dataworks_agent.agent.multi_agent.coordinator import AgentCoordinator
from dataworks_agent.agent.multi_agent.diagnosis_agent import DiagnosisAgent
from dataworks_agent.agent.multi_agent.governance_agent import GovernanceAgent
from dataworks_agent.agent.multi_agent.modeling_agent import ModelingAgent
from dataworks_agent.agent.multi_agent.query_agent import QueryAgent


@pytest.mark.asyncio
async def test_modeling_agent_can_handle():
    agent = ModelingAgent()
    assert await agent.can_handle("帮我建一张 DWD 订单明细表", {}) is True
    assert await agent.can_handle("查询昨天 GMV", {}) is False


@pytest.mark.asyncio
async def test_diagnosis_agent_can_handle():
    agent = DiagnosisAgent()
    assert await agent.can_handle("任务为什么失败了", {}) is True
    assert await agent.can_handle("帮我建表", {}) is False


@pytest.mark.asyncio
async def test_query_agent_can_handle():
    agent = QueryAgent()
    assert await agent.can_handle("查询昨天 GMV", {}) is True
    assert await agent.can_handle("建表", {}) is False


@pytest.mark.asyncio
async def test_governance_agent_can_handle():
    agent = GovernanceAgent()
    assert await agent.can_handle("检查词根", {}) is True
    assert await agent.can_handle("建表", {}) is False


@pytest.mark.asyncio
async def test_coordinator_route_to_correct_agent():
    coordinator = AgentCoordinator(
        [ModelingAgent(), DiagnosisAgent(), QueryAgent(), GovernanceAgent()]
    )
    agent = await coordinator.route_task("帮我建表", {}, None)
    assert agent is not None
    assert agent.agent_type == "modeling"

    agent = await coordinator.route_task("任务为什么失败了", {}, None)
    assert agent is not None
    assert agent.agent_type == "diagnosis"


@pytest.mark.asyncio
async def test_coordinator_no_matching_agent():
    coordinator = AgentCoordinator([ModelingAgent(), DiagnosisAgent()])
    agent = await coordinator.route_task("未知意图", {}, None)
    assert agent is None


@pytest.mark.asyncio
async def test_list_available_agents():
    coordinator = AgentCoordinator(
        [ModelingAgent(), DiagnosisAgent(), QueryAgent(), GovernanceAgent()]
    )
    agents = coordinator.list_available_agents()
    assert len(agents) == 4
    types = {a["type"] for a in agents}
    assert types == {"modeling", "diagnosis", "query", "governance"}


@pytest.mark.asyncio
async def test_execute_with_agents_modeling():
    coordinator = AgentCoordinator(
        [ModelingAgent(), DiagnosisAgent(), QueryAgent(), GovernanceAgent()]
    )
    task = await coordinator.execute_with_agents("帮我建一张 DWD 订单明细表", {}, None)
    assert task is not None
    assert "DWD" in task.description
