"""Structured Agent interaction integration coverage."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from dataworks_agent.agent.interaction import (
    InteractionAnswer,
    InteractionExpiredError,
    PendingInteraction,
    build_interaction,
    resolve_interaction_answer,
)


def test_build_interaction_from_table_option_chips() -> None:
    pending = build_interaction(
        {
            "option_chips": [
                {
                    "type": "pick_table",
                    "id": "opt_0",
                    "label": "giikin_aliyun.tb_dwd_order",
                    "value": "giikin_aliyun.tb_dwd_order",
                    "layer": "dwd",
                },
                {
                    "type": "free_text",
                    "id": "opt_custom",
                    "label": "输入其它",
                    "placeholder": "project.table",
                },
            ],
            "clarifying_questions": ["请选择目标表"],
        },
        purpose="select_table",
        state_version=1,
    )

    assert pending is not None
    assert pending.prompt == "请选择目标表"
    assert pending.allow_custom_input is True
    assert pending.custom_input_placeholder == "project.table"
    assert pending.options[0].value == "giikin_aliyun.tb_dwd_order"
    assert pending.options[0].payload == {
        "params": {"table_name": "giikin_aliyun.tb_dwd_order"},
        "selected_resources": {"table": "giikin_aliyun.tb_dwd_order"},
    }


def test_build_interaction_from_next_actions() -> None:
    pending = build_interaction(
        {
            "next_actions": [
                {
                    "id": "dwd",
                    "label": "DWD",
                    "value": "dwd",
                    "payload": {"params": {"layer": "dwd"}},
                }
            ],
            "allow_custom_input": True,
            "custom_input_hint": "继续描述筛选条件",
        },
        purpose="select_layer",
        state_version=2,
    )

    assert pending is not None
    assert pending.options[0].id == "dwd"
    assert pending.options[0].payload == {"params": {"layer": "dwd"}}


def test_resolve_answer_uses_server_option_payload() -> None:
    pending = build_interaction(
        {
            "next_actions": [
                {
                    "id": "dwd",
                    "label": "DWD",
                    "payload": {"params": {"layer": "dwd"}},
                }
            ]
        },
        purpose="select_layer",
        state_version=2,
    )
    assert pending is not None

    result = resolve_interaction_answer(
        pending,
        InteractionAnswer(
            interaction_id=pending.interaction_id,
            option_id="dwd",
            state_version=2,
        ),
    )

    assert result == {"params": {"layer": "dwd"}}


def test_resolve_custom_answer() -> None:
    pending = PendingInteraction(
        interaction_id="int_1",
        type="free_text",
        purpose="select_table",
        prompt="请继续描述",
        allow_custom_input=True,
        state_version=4,
    )

    result = resolve_interaction_answer(
        pending,
        InteractionAnswer(
            interaction_id="int_1",
            custom_text="只要包含退款金额字段的 DWD 表",
            state_version=4,
        ),
    )

    assert result == {"custom_text": "只要包含退款金额字段的 DWD 表"}


def test_expired_interaction_is_rejected() -> None:
    pending = PendingInteraction(
        interaction_id="int_current",
        type="single_select",
        purpose="select_layer",
        prompt="请选择层级",
        state_version=5,
    )

    with pytest.raises(InteractionExpiredError):
        resolve_interaction_answer(
            pending,
            InteractionAnswer(
                interaction_id="int_old",
                custom_text="DWD",
                state_version=4,
            ),
        )


def test_answer_requires_exactly_one_answer_mode() -> None:
    with pytest.raises(ValidationError):
        InteractionAnswer(interaction_id="int_1", state_version=1)

    with pytest.raises(ValidationError):
        InteractionAnswer(
            interaction_id="int_1",
            option_id="opt_1",
            custom_text="other",
            state_version=1,
        )


@pytest.mark.asyncio
async def test_pending_interaction_survives_new_graph_instance(tmp_path) -> None:
    from dataworks_agent.agent.conversation_graph import ConversationGraph

    db_path = str(tmp_path / "conversation.db")
    first = ConversationGraph(db_path)
    pending = build_interaction(
        {"next_actions": [{"id": "dwd", "label": "DWD", "value": "dwd"}]},
        purpose="select_layer",
        state_version=1,
    )
    assert pending is not None
    await first.remember(
        "conv-1",
        "找订单表",
        needs_clarification=True,
        action="ask_data",
        pending_interaction=pending.model_dump(),
    )

    second = ConversationGraph(db_path)
    state = await second.context("conv-1")

    assert state["pending_interaction"]["interaction_id"] == pending.interaction_id
    assert state["state_version"] == 1
    assert state["objective"] == "找订单表"


@pytest.mark.asyncio
async def test_answer_updates_selected_resources_and_clears_pending(tmp_path) -> None:
    from dataworks_agent.agent.conversation_graph import ConversationGraph

    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    pending = build_interaction(
        {
            "option_chips": [
                {
                    "type": "pick_table",
                    "id": "table_1",
                    "label": "订单表",
                    "value": "giikin_aliyun.tb_dwd_order",
                }
            ]
        },
        purpose="select_table",
        state_version=1,
    )
    assert pending is not None
    await graph.remember(
        "conv-1",
        "找订单表",
        needs_clarification=True,
        pending_interaction=pending.model_dump(),
    )

    resolved = await graph.answer(
        "conv-1",
        InteractionAnswer(
            interaction_id=pending.interaction_id,
            option_id="table_1",
            state_version=1,
        ),
    )
    state = await graph.context("conv-1")

    assert resolved["params"]["table_name"] == "giikin_aliyun.tb_dwd_order"
    assert state["selected_resources"]["table"] == "giikin_aliyun.tb_dwd_order"
    assert state["params"]["table_name"] == "giikin_aliyun.tb_dwd_order"
    assert state["pending_interaction"] == {}
    assert state["state_version"] == 2


@pytest.mark.asyncio
async def test_cancel_clears_interaction_and_selected_resources(tmp_path) -> None:
    from dataworks_agent.agent.conversation_graph import ConversationGraph

    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    pending = PendingInteraction(
        interaction_id="int_1",
        type="free_text",
        purpose="select_table",
        prompt="请选择表",
        state_version=1,
    )
    await graph.remember(
        "conv-1",
        "找订单表",
        needs_clarification=True,
        pending_interaction=pending.model_dump(),
        selected_resources={"table": "giikin_aliyun.tb_dwd_order"},
    )

    resolved = await graph.resolve("取消", "conv-1")
    state = await graph.context("conv-1")

    assert resolved == "取消"
    assert state["pending_interaction"] == {}
    assert state["selected_resources"] == {}
    assert state["state_version"] == 2


@pytest.mark.asyncio
async def test_chat_resolves_structured_answer_before_nlu() -> None:
    from dataworks_agent.agent.core import ChatAgent
    from dataworks_agent.agent.nlu.intent_parser import Intent
    from dataworks_agent.agent.workflow_service import WorkflowResult

    pending = PendingInteraction(
        interaction_id="int-1",
        purpose="select_table",
        prompt="请选择表",
        state_version=1,
        options=[],
    )
    previous_context = {
        "objective": "找订单表",
        "pending_objective": "找订单表",
        "action": "ask_data",
        "params": {"keyword": "order"},
        "pending_interaction": pending.model_dump(),
        "state_version": 1,
    }
    graph = MagicMock()
    graph.context = AsyncMock(return_value=previous_context)
    graph.answer = AsyncMock(
        return_value={
            "params": {"table_name": "giikin_aliyun.tb_dwd_order"},
            "selected_resources": {"table": "giikin_aliyun.tb_dwd_order"},
        }
    )
    graph.resolve = AsyncMock(side_effect=lambda message, *_args, **_kwargs: message)
    graph.remember = AsyncMock()

    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._intent_parser = MagicMock()
    agent._intent_parser.parse.return_value = Intent(action="unknown", confidence=0.1)
    agent._workflow_service = MagicMock()
    agent._workflow_service.execute = AsyncMock(
        return_value=WorkflowResult(
            success=True,
            message="ok",
            workflow_type="ask_data",
            mode="dev_execute",
        )
    )
    agent._workflow_service.understand_business_query.return_value = None
    agent._save_conversation_message = MagicMock()

    response = await agent.chat(
        "订单表",
        conversation_id="conv-1",
        interaction_answer=InteractionAnswer(
            interaction_id="int-1",
            option_id="table-1",
            state_version=1,
        ),
    )

    assert response.success is True
    graph.answer.assert_awaited_once()
    execute = agent._workflow_service.execute.await_args.kwargs
    assert execute["action"] == "ask_data"
    assert execute["params"]["table_name"] == "giikin_aliyun.tb_dwd_order"
    assert execute["params"]["keyword"] == "order"


@pytest.mark.asyncio
async def test_chat_returns_current_interaction_when_answer_expired() -> None:
    from dataworks_agent.agent.core import ChatAgent

    pending = PendingInteraction(
        interaction_id="int-current",
        purpose="select_table",
        prompt="请选择表",
        state_version=3,
    )
    graph = MagicMock()
    graph.context = AsyncMock(
        return_value={
            "pending_interaction": pending.model_dump(),
            "state_version": 3,
        }
    )
    graph.answer = AsyncMock(side_effect=InteractionExpiredError("expired", current=pending))

    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._save_conversation_message = MagicMock()

    response = await agent.chat(
        "old",
        conversation_id="conv-1",
        interaction_answer=InteractionAnswer(
            interaction_id="int-old",
            option_id="table-1",
            state_version=2,
        ),
    )

    assert response.success is False
    assert response.error == "interaction_expired"
    assert response.data["interaction"]["interaction_id"] == "int-current"


def test_history_persists_readable_content_and_structured_payload(monkeypatch) -> None:
    import dataworks_agent.agent.core as core_module
    from dataworks_agent.agent.core import ChatAgent

    session = MagicMock()
    monkeypatch.setattr(core_module, "SessionLocal", lambda: session)
    agent = ChatAgent()
    payload = {"interaction": {"interaction_id": "int-1"}}

    agent._save_conversation_message(
        "conv-1",
        "assistant",
        "请选择表",
        payload=payload,
    )

    saved = session.add.call_args.args[0]
    assert saved.content == "请选择表"
    assert json.loads(saved.payload_json) == payload
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_history_loading_parses_payload_json(monkeypatch) -> None:
    import dataworks_agent.agent.core as core_module
    from dataworks_agent.agent.core import ChatAgent

    message = SimpleNamespace(
        role="assistant",
        content="请选择表",
        created_at="2026-07-17T00:00:00+00:00",
        payload_json='{"interaction":{"interaction_id":"int-1"}}',
    )
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [message]
    monkeypatch.setattr(core_module, "SessionLocal", lambda: session)

    history = ChatAgent().get_conversation_history("conv-1")

    assert history == [
        {
            "role": "assistant",
            "content": "请选择表",
            "timestamp": "2026-07-17T00:00:00+00:00",
            "payload": {"interaction": {"interaction_id": "int-1"}},
        }
    ]
