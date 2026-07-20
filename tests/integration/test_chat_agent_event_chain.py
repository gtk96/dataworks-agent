from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.agent.context.metadata_provider import MetadataQueryResult
from dataworks_agent.agent.conversation_events import TurnTrace
from dataworks_agent.agent.conversation_graph import ConversationGraph
from dataworks_agent.agent.core import ChatAgent
from dataworks_agent.agent.nlu.intent_parser import Intent
from dataworks_agent.agent.tools.registry import ToolRegistry
from dataworks_agent.agent.tools.table_discovery import TableDiscoveryTool
from dataworks_agent.agent.workflow_service import WorkflowResult


class FakeConversationEventRecorder:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []

    def start_turn(
        self, conversation_id: str, *, request_id: str | None = None, input_text: str = ""
    ) -> TurnTrace:
        trace = TurnTrace(
            conversation_id=conversation_id,
            request_id=request_id or "req-test",
            turn_id="turn-test",
            started_at=0.0,
        )
        self.records.append(("turn_received", {"input_length": len(input_text)}))
        return trace

    def emit(self, trace: TurnTrace, event: str, **payload: object) -> None:
        assert trace.turn_id == "turn-test"
        self.records.append((event, payload))

    def finish(self, trace: TurnTrace, *, success: bool, **payload: object) -> None:
        self.emit(
            trace,
            "response_sent",
            outcome="success" if success else "failed",
            **payload,
        )


@pytest.mark.asyncio
async def test_chat_agent_emits_ordered_greeting_trace_and_response_ids(tmp_path):
    recorder = FakeConversationEventRecorder()
    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._conversation_events = recorder

    response = await agent.chat("hello", conversation_id="conv-trace")

    assert [event for event, _payload in recorder.records] == [
        "turn_received",
        "context_loaded",
        "turn_classified",
        "run.started",
        "state.persisted",
        "response.completed",
        "interaction_emitted",
        "state_persisted",
        "response_sent",
    ]
    assert response.data["conversation"]["request_id"] == "req-test"
    assert response.data["conversation"]["turn_id"] == "turn-test"
    await graph.aclose()


@pytest.mark.asyncio
async def test_chat_agent_emits_failure_stage_before_failed_response(tmp_path):
    recorder = FakeConversationEventRecorder()
    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._conversation_events = recorder
    agent._context_resolver.resolve = AsyncMock(side_effect=RuntimeError("classifier failed"))

    response = await agent.chat("continue", conversation_id="conv-failure")

    assert response.success is False
    assert [event for event, _payload in recorder.records] == [
        "turn_received",
        "context_loaded",
        "turn_failed",
        "response_sent",
    ]
    failure = recorder.records[2][1]
    assert failure["failure_stage"] == "turn_classification"
    assert failure["error_type"] == "RuntimeError"
    assert failure["write_workflow_started"] is False
    assert response.data["conversation"]["request_id"] == "req-test"
    await graph.aclose()


@pytest.mark.asyncio
async def test_chat_agent_emits_complete_workflow_trace(tmp_path):
    recorder = FakeConversationEventRecorder()
    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._conversation_events = recorder
    agent._intent_parser = MagicMock()
    agent._intent_parser.parse.return_value = Intent(action="diagnose_issue", confidence=0.95)
    agent._workflow_service = MagicMock()
    agent._workflow_service.understand_business_query.return_value = None
    agent._workflow_service.execute = AsyncMock(
        return_value=WorkflowResult(
            success=True,
            message="diagnosis complete",
            workflow_type="diagnose_issue",
            mode="plan",
        )
    )

    response = await agent.chat(
        "诊断这个任务",
        conversation_id="conv-workflow-trace",
        execution_mode="plan",
    )

    assert response.success is True
    assert [event for event, _payload in recorder.records] == [
        "turn_received",
        "context_loaded",
        "turn_classified",
        "reference_resolved",
        "nlu_parsed",
        "workflow_started",
        "workflow_finished",
        "state_persisted",
        "response_sent",
    ]
    await graph.aclose()


@pytest.mark.asyncio
async def test_bounded_tool_events_are_persisted_without_arguments(tmp_path):
    recorder = FakeConversationEventRecorder()
    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    provider = AsyncMock()
    provider.search_table.return_value = MetadataQueryResult(
        keyword="订单",
        candidates=[{"full_name": "dw.dwd_orders", "layer": "dwd"}],
    )
    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._run_coordinator.conversation_graph = graph
    agent._run_coordinator.tools = ToolRegistry([TableDiscoveryTool(provider)])
    agent._conversation_events = recorder
    try:
        response = await agent.chat("找订单表", conversation_id="conv-tool-trace")

        assert response.success is True
        events = [event for event, _payload in recorder.records]
        assert "tool.started" in events
        assert "tool.completed" in events
        started = next(payload for event, payload in recorder.records if event == "tool.started")
        completed = next(payload for event, payload in recorder.records if event == "tool.completed")
        assert started == {"tool": "find_table", "side_effect": "read"}
        assert "arguments" not in started
        assert completed["tool"] == "find_table"
        assert completed["success"] is True
    finally:
        await graph.aclose()
