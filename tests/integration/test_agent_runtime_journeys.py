"""Product-level deterministic journeys for the bounded Agent runtime."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.agent.conversation_graph import ConversationGraph
from dataworks_agent.agent.interaction import InteractionAnswer
from dataworks_agent.agent.run_coordinator import AgentRunCoordinator
from dataworks_agent.agent.run_models import AgentRunRequest, RunEvent
from dataworks_agent.agent.tools.registry import ToolRegistry
from dataworks_agent.agent.tools.table_discovery import TableDiscoveryTool
from dataworks_agent.agent.tools.table_inspection import TableInspectionTool
from tests.support.agent_runtime import DeterministicNoWriteProvider


def _runtime(graph: ConversationGraph, provider: DeterministicNoWriteProvider):
    return AgentRunCoordinator(
        conversation_graph=graph,
        tools=ToolRegistry(
            [TableDiscoveryTool(provider), TableInspectionTool(provider)]
        ),
    )


def _answer(response, *, option_id: str | None = None, custom_text: str | None = None):
    interaction = response.data["interaction"]
    return InteractionAnswer(
        interaction_id=interaction["interaction_id"],
        option_id=option_id,
        custom_text=custom_text,
        state_version=interaction["state_version"],
    )


async def _run(runtime, conversation_id: str, message: str, answer=None, events=None):
    return await runtime.run(
        AgentRunRequest(conversation_id, message, interaction_answer=answer),
        emit=events.append if events is not None else None,
    )


@pytest.mark.asyncio
async def test_journey_1_greeting_find_explain_select_and_view_columns(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    runtime = _runtime(graph, provider)
    try:
        greeting = await _run(runtime, "journey-1", "你好")
        refine = await _run(
            runtime,
            "journey-1",
            "查找数据表",
            _answer(greeting, option_id="find_table"),
        )
        candidates = await _run(
            runtime,
            "journey-1",
            "订单",
            _answer(refine, custom_text="订单"),
        )
        explained = await _run(runtime, "journey-1", "什么意思")
        selected = await _run(
            runtime,
            "journey-1",
            "第二个",
        )
        columns = await _run(
            runtime,
            "journey-1",
            "查看字段",
        )

        assert candidates.data["interaction"]["purpose"] == "select_table"
        assert explained.data["interaction"]["interaction_id"] == candidates.data["interaction"]["interaction_id"]
        assert selected.data["conversation"]["selected_resources"]["table"] == "dw.dws_orders_summary"
        assert [column["name"] for column in columns.data["columns"]] == ["order_id", "pay_amount"]
        provider.assert_no_writes()
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_journey_2_layer_and_custom_refinement(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    runtime = _runtime(graph, provider)
    try:
        layers = await _run(runtime, "journey-2", "找宽订单表")
        dwd = await _run(
            runtime,
            "journey-2",
            "DWD",
        )
        refunds = await _run(
            runtime,
            "journey-2",
            "退款",
        )
        selected = await _run(
            runtime,
            "journey-2",
            "明细表",
            _answer(refunds, option_id="table_1"),
        )

        assert layers.data["interaction"]["purpose"] == "select_layer"
        assert len(dwd.data["interaction"]["options"]) == 5
        assert selected.data["conversation"]["selected_resources"]["table"] == "dw.dwd_refund_detail"
        provider.assert_no_writes()
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_journey_3_read_failure_is_recoverable_and_new_goal_works(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    provider.fail_search = True
    runtime = _runtime(graph, provider)
    try:
        failed = await _run(runtime, "journey-3", "找订单表")
        explained = await _run(runtime, "journey-3", "什么意思")
        provider.fail_search = False
        recovered = await _run(runtime, "journey-3", "找退款表")

        assert failed.data["agent_mode"] == "recoverable_error"
        assert failed.data["conversation"]["status"] != "execution_unknown"
        assert explained.error != "execution_unknown"
        assert recovered.data["interaction"]["purpose"] == "select_table"
        assert recovered.data["conversation"]["active_goal"] == "找退款表"
        provider.assert_no_writes()
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_journey_4_broken_llm_does_not_block_known_tool(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    runtime = _runtime(graph, provider)
    runtime.decisions.llm = AsyncMock(side_effect=RuntimeError("model_not_found"))
    try:
        response = await _run(runtime, "journey-4", "找订单表")
        assert response.data["interaction"]["purpose"] == "select_table"
        runtime.decisions.llm.assert_not_awaited()
        provider.assert_no_writes()
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_journey_5_refresh_restores_active_interaction(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    runtime = _runtime(graph, provider)
    try:
        response = await _run(runtime, "journey-5", "找订单表")
        restored = await graph.context("journey-5")
        assert restored["pending_interaction"] == response.data["interaction"]
        provider.assert_no_writes()
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_journey_6_new_coordinator_instance_restores_and_continues(tmp_path) -> None:
    path = tmp_path / "journeys.db"
    provider = DeterministicNoWriteProvider()
    first_graph = ConversationGraph(str(path))
    first = _runtime(first_graph, provider)
    response = await _run(first, "journey-6", "找订单表")
    await first_graph.aclose()

    second_graph = ConversationGraph(str(path))
    second = _runtime(second_graph, provider)
    try:
        selected = await _run(
            second,
            "journey-6",
            "明细表",
            _answer(response, option_id="table_1"),
        )
        assert selected.data["agent_mode"] == "table_selected"
        provider.assert_no_writes()
    finally:
        await second_graph.aclose()


@pytest.mark.asyncio
async def test_journey_7_two_clients_reject_one_stale_answer(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    first = _runtime(graph, provider)
    second = _runtime(graph, provider)
    try:
        response = await _run(first, "journey-7", "找订单表")
        answer = _answer(response, option_id="table_1")
        results = await asyncio.gather(
            _run(first, "journey-7", "明细表", answer),
            _run(second, "journey-7", "明细表", answer),
        )
        assert sorted(result.error or "" for result in results) == ["", "interaction_expired"]
        provider.assert_no_writes()
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_journey_8_task_switch_does_not_leak_table_params(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    runtime = _runtime(graph, provider)
    try:
        orders = await _run(runtime, "journey-8", "找订单表")
        await _run(
            runtime,
            "journey-8",
            "明细表",
            _answer(orders, option_id="table_1"),
        )
        refunds = await _run(runtime, "journey-8", "找退款表")
        context = await graph.context("journey-8")

        assert refunds.data["conversation"]["active_goal"] == "找退款表"
        assert context["params"] == {}
        assert context["selected_resources"] == {}
        provider.assert_no_writes()
    finally:
        await graph.aclose()


@pytest.mark.asyncio
async def test_fifty_turns_keep_state_bounded_monotonic_and_read_only(tmp_path) -> None:
    graph = ConversationGraph(str(tmp_path / "journeys.db"))
    provider = DeterministicNoWriteProvider()
    runtime = _runtime(graph, provider)
    versions: list[int] = []
    all_events: list[RunEvent] = []
    try:
        for cycle in range(10):
            candidates = await _run(runtime, "journey-50", f"找订单表", events=all_events)
            versions.append(candidates.data["conversation"]["state_version"])
            explained = await _run(runtime, "journey-50", "什么意思", events=all_events)
            versions.append(explained.data["conversation"]["state_version"])
            selected = await _run(
                runtime,
                "journey-50",
                "明细表",
                _answer(explained, option_id="table_1"),
                all_events,
            )
            versions.append(selected.data["conversation"]["state_version"])
            inspected = await _run(
                runtime,
                "journey-50",
                "查看字段",
                _answer(selected, option_id="inspect_columns"),
                all_events,
            )
            versions.append(inspected.data["conversation"]["state_version"])
            greeting = await _run(runtime, "journey-50", "你好", events=all_events)
            versions.append(greeting.data["conversation"]["state_version"])

        context = await graph.context("journey-50")
        assert len(versions) == 50
        assert versions == sorted(versions)
        assert len(set(versions)) == 50
        assert len(context["conversation_summary"]) <= 1000
        assert sum(call["tool"] == "find_table" for call in provider.calls) == 10
        assert sum(call["tool"] == "inspect_table" for call in provider.calls) == 10
        assert sum(event.type == "response.completed" for event in all_events) == 50
        decisions_by_run: dict[str, int] = {}
        for event in all_events:
            if event.type == "decision.started":
                decisions_by_run[event.run_id] = decisions_by_run.get(event.run_id, 0) + 1
        assert max(decisions_by_run.values()) <= 6
        provider.assert_no_writes()
    finally:
        await graph.aclose()
