"""Bounded conversational Agent run integration coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.agent.context.metadata_provider import MetadataQueryResult
from dataworks_agent.agent.conversation_graph import ConversationGraph
from dataworks_agent.agent.core import ChatAgent
from dataworks_agent.agent.interaction import InteractionAnswer
from dataworks_agent.agent.run_coordinator import AgentRunCoordinator
from dataworks_agent.agent.run_models import AgentRunRequest, RunEvent
from dataworks_agent.agent.tools.registry import ToolRegistry
from dataworks_agent.agent.tools.table_discovery import TableDiscoveryTool


@pytest.fixture
async def runtime(tmp_path):
    provider = AsyncMock()
    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    coordinator = AgentRunCoordinator(
        conversation_graph=graph,
        tools=ToolRegistry([TableDiscoveryTool(provider)]),
    )
    try:
        yield coordinator, provider, graph
    finally:
        await graph.aclose()


def _answer(response, option_id: str) -> InteractionAnswer:
    interaction = response.data["interaction"]
    return InteractionAnswer(
        interaction_id=interaction["interaction_id"],
        option_id=option_id,
        state_version=interaction["state_version"],
    )


@pytest.mark.asyncio
async def test_greeting_find_table_and_explain_survive_read_failure(runtime) -> None:
    coordinator, provider, graph = runtime
    provider.search_table.return_value = None

    greeting = await coordinator.run(AgentRunRequest("conv", "你好"))
    find = await coordinator.run(
        AgentRunRequest(
            "conv",
            "查找数据表",
            interaction_answer=_answer(greeting, "find_table"),
        )
    )
    explain = await coordinator.run(AgentRunRequest("conv", "什么意思"))
    context = await graph.context("conv")

    assert greeting.data["interaction"]["purpose"] == "choose_entry"
    assert find.data["agent_mode"] == "waiting_user"
    assert find.data["conversation"]["status"] != "execution_unknown"
    assert explain.error != "execution_unknown"
    assert explain.data["interaction"]["purpose"] == "refine_table_search"
    assert context["action"] == "find_table"
    assert context["pending_interaction"]["purpose"] == "refine_table_search"
    provider.search_table.assert_not_awaited()


@pytest.mark.asyncio
async def test_broken_llm_does_not_block_deterministic_find_table(runtime) -> None:
    coordinator, provider, _graph = runtime
    coordinator.decisions.llm = AsyncMock(side_effect=RuntimeError("model_not_found"))
    provider.search_table.return_value = MetadataQueryResult(
        keyword="订单",
        candidates=[
            {
                "full_name": "dw.dwd_orders",
                "layer": "dwd",
                "comment": "订单明细",
            }
        ],
    )

    response = await coordinator.run(AgentRunRequest("conv", "找订单表"))

    assert response.success is True
    assert response.data["interaction"]["purpose"] == "select_table"
    assert response.data["interaction"]["options"][0]["payload"]["params"]["table_name"] == (
        "dw.dwd_orders"
    )
    coordinator.decisions.llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_table_selection_returns_next_action_without_requery(runtime) -> None:
    coordinator, provider, graph = runtime
    provider.search_table.return_value = MetadataQueryResult(
        keyword="订单",
        candidates=[
            {
                "full_name": "dw.dwd_orders",
                "layer": "dwd",
                "comment": "订单明细",
            }
        ],
    )
    candidates = await coordinator.run(AgentRunRequest("conv", "找订单表"))

    selected = await coordinator.run(
        AgentRunRequest(
            "conv",
            "订单明细",
            interaction_answer=_answer(candidates, "table_1"),
        )
    )
    context = await graph.context("conv")

    assert selected.success is True
    assert selected.data["agent_mode"] == "table_selected"
    assert selected.data["interaction"]["purpose"] == "table_next_action"
    assert context["selected_resources"]["table"] == "dw.dwd_orders"
    assert provider.search_table.await_count == 1


@pytest.mark.asyncio
async def test_run_is_bounded_and_emits_one_completed_response(runtime) -> None:
    coordinator, provider, _graph = runtime
    provider.search_table.return_value = None
    events: list[RunEvent] = []

    response = await coordinator.run(
        AgentRunRequest("conv", "找订单表"),
        emit=events.append,
    )

    assert response.success is True
    assert response.error is None
    assert response.data["agent_mode"] == "waiting_user"
    assert len([event for event in events if event.type == "response.completed"]) == 1
    assert len([event for event in events if event.type == "decision.started"]) <= 6
    assert [event.type for event in events] == [
        "run.started",
        "decision.started",
        "decision.completed",
        "tool.started",
        "tool.completed",
        "state.persisted",
        "response.completed",
    ]


@pytest.mark.asyncio
async def test_chat_agent_public_api_uses_bounded_table_discovery(runtime) -> None:
    coordinator, provider, graph = runtime
    provider.search_table.return_value = MetadataQueryResult(
        keyword="订单",
        candidates=[{"full_name": "dw.dwd_orders", "layer": "dwd"}],
    )
    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._run_coordinator = coordinator
    agent._save_conversation_message = MagicMock()

    response = await agent.chat("找订单表", conversation_id="conv-public")

    assert response.data["interaction"]["purpose"] == "select_table"
    assert response.data["conversation"]["conversation_id"] == "conv-public"
    provider.search_table.assert_awaited_once()
