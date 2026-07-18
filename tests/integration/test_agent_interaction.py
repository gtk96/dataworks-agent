"""Structured Agent interaction integration coverage."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
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
from dataworks_agent.agent.response_policy import ConversationMeta, ResponsePolicy

ENTRY_OPTION_IDS = ["ask_data", "find_table", "modeling", "diagnose"]


def test_conversation_meta_selected_resources_defaults_are_independent() -> None:
    first = ConversationMeta()
    second = ConversationMeta()

    first.selected_resources["table"] = "dw.orders"

    assert second.selected_resources == {}


def test_greeting_returns_entry_cards() -> None:
    data = ResponsePolicy().greeting({}, state_version=1)

    assert [item["id"] for item in data["interaction"]["options"]] == ENTRY_OPTION_IDS
    assert data["interaction"]["allow_custom_input"] is True


def test_greeting_preserves_active_interaction() -> None:
    pending = {
        "interaction_id": "int_orders",
        "type": "single_select",
        "purpose": "select_table",
        "prompt": "请选择候选表",
        "options": [],
        "allow_custom_input": True,
        "custom_input_placeholder": "",
        "state_version": 2,
        "status": "pending",
    }

    data = ResponsePolicy().greeting({"pending_interaction": pending}, state_version=3)

    assert data["interaction"] == pending


def test_explanation_preserves_active_interaction() -> None:
    context = {
        "pending_interaction": {
            "interaction_id": "int_orders",
            "type": "single_select",
            "purpose": "select_table",
            "prompt": "请选择候选表",
            "options": [
                {
                    "id": "detail",
                    "label": "订单明细表",
                    "value": "dw.detail",
                    "description": "一单一行",
                    "payload": {},
                }
            ],
            "allow_custom_input": True,
            "custom_input_placeholder": "",
            "state_version": 2,
            "status": "pending",
        }
    }

    message, data = ResponsePolicy().explain(context)

    assert "一单一行" in message
    assert data["interaction"]["interaction_id"] == "int_orders"


def test_explanation_without_pending_or_previous_content_requests_clarification() -> None:
    message, data = ResponsePolicy().explain({})

    assert message
    assert message != "上一条的意思是："
    assert "补充" in message or "说明" in message
    assert data["interaction"] is None


def test_clarify_returns_stable_entry_cards() -> None:
    data = ResponsePolicy().clarify(state_version=4)

    assert data["interaction"]["purpose"] == "clarify_request"
    assert [item["id"] for item in data["interaction"]["options"]] == ENTRY_OPTION_IDS


def test_string_next_actions_become_structured_options_without_mutating_input() -> None:
    original = {"next_actions": ["查看字段", "查询数据"]}
    snapshot = {"next_actions": list(original["next_actions"])}

    data = ResponsePolicy().normalize_workflow_data(
        original,
        purpose="next_step",
        state_version=5,
    )

    assert original == snapshot
    assert [item["label"] for item in data["interaction"]["options"]] == [
        "查看字段",
        "查询数据",
    ]
    assert [item["id"] for item in data["interaction"]["options"]] == [
        "action_0",
        "action_1",
    ]
    assert all(item["payload"]["value"] == item["value"] for item in data["interaction"]["options"])


def test_normalize_workflow_data_without_useful_options_has_no_interaction() -> None:
    original = {"next_actions": ["", "   ", None]}
    snapshot = {"next_actions": list(original["next_actions"])}

    data = ResponsePolicy().normalize_workflow_data(
        original,
        purpose="next_step",
        state_version=5,
    )

    assert original == snapshot
    assert data["option_chips"] == []
    assert data["interaction"] is None


def test_legacy_string_options_are_preserved() -> None:
    pending = build_interaction(
        {"next_actions": ["查看字段", "查询数据"]},
        purpose="next_step",
        state_version=5,
    )

    assert pending is not None
    assert [item.label for item in pending.options] == ["查看字段", "查询数据"]
    assert [item.id for item in pending.options] == ["action_0", "action_1"]


def test_action_option_payload_is_structured() -> None:
    pending = build_interaction(
        {
            "next_actions": [
                {
                    "id": "inspect",
                    "type": "action",
                    "label": "查看字段",
                    "value": "查看字段",
                }
            ]
        },
        purpose="next_step",
        state_version=5,
    )

    assert pending is not None
    assert pending.options[0].payload == {
        "value": "查看字段",
        "params": {"follow_up_action": "查看字段"},
    }


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
async def test_rich_context_survives_new_graph_instance(tmp_path) -> None:
    from dataworks_agent.agent.conversation_graph import ConversationGraph

    db_path = str(tmp_path / "conversation.db")
    first = ConversationGraph(db_path)
    current = await first.remember(
        "conv-rich",
        "查找订单相关表",
        needs_clarification=False,
        action="ask_data",
        params={"layer": "dwd"},
        selected_resources={"table": "dw.dwd_order_detail"},
        last_assistant_turn={"content": "已选择订单明细表"},
        conversation_summary="目标：查订单；分层：DWD",
        query_frame={"metric": "order_count"},
        task_status="active",
    )

    restored = await ConversationGraph(db_path).context("conv-rich")
    empty = await first.context("conv-empty")

    assert current["state_version"] == 1
    assert restored["last_assistant_turn"] == {"content": "已选择订单明细表"}
    assert restored["conversation_summary"] == "目标：查订单；分层：DWD"
    assert restored["query_frame"] == {"metric": "order_count"}
    assert restored["task_status"] == "active"
    assert empty["last_assistant_turn"] == {}
    assert empty["conversation_summary"] == ""
    assert empty["query_frame"] == {}
    assert empty["task_status"] == ""


@pytest.mark.asyncio
async def test_remember_rejects_stale_expected_version(tmp_path) -> None:
    from dataworks_agent.agent.conversation_graph import (
        ConversationGraph,
        ConversationStateConflictError,
    )

    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    current = await graph.remember(
        "conv-cas",
        "查订单",
        needs_clarification=False,
    )

    with pytest.raises(ConversationStateConflictError) as exc_info:
        await graph.remember(
            "conv-cas",
            "查订单",
            needs_clarification=False,
            expected_version=current["state_version"] - 1,
        )

    assert exc_info.value.current == current
    assert (await graph.context("conv-cas"))["state_version"] == current["state_version"]


@pytest.mark.asyncio
async def test_single_process_lock_serializes_cas_across_graph_instances(
    tmp_path, monkeypatch
) -> None:
    from dataworks_agent.agent.conversation_graph import (
        ConversationGraph,
        ConversationStateConflictError,
    )

    db_path = tmp_path / "conversation.db"
    first = ConversationGraph(str(db_path))
    second = ConversationGraph(os.path.relpath(db_path, start=Path.cwd()))
    first_write_entered = asyncio.Event()
    release_first_write = asyncio.Event()
    second_read_entered = asyncio.Event()
    tasks = []

    try:
        current = await first.remember(
            "conv-shared-lock",
            "query orders",
            needs_clarification=False,
        )
        await second.context("conv-shared-lock")
        first_update = first._graph.aupdate_state
        second_context = second._context_unlocked

        async def delayed_first_update(*args, **kwargs):
            first_write_entered.set()
            await release_first_write.wait()
            return await first_update(*args, **kwargs)

        async def observed_second_context(*args, **kwargs):
            second_read_entered.set()
            return await second_context(*args, **kwargs)

        monkeypatch.setattr(first._graph, "aupdate_state", delayed_first_update)
        monkeypatch.setattr(second, "_context_unlocked", observed_second_context)
        tasks.append(
            asyncio.create_task(
                first.remember(
                    "conv-shared-lock",
                    "query orders",
                    needs_clarification=False,
                    params={"writer": "first"},
                    expected_version=current["state_version"],
                )
            )
        )
        await first_write_entered.wait()
        tasks.append(
            asyncio.create_task(
                second.remember(
                    "conv-shared-lock",
                    "query orders",
                    needs_clarification=False,
                    params={"writer": "second"},
                    expected_version=current["state_version"],
                )
            )
        )
        await asyncio.sleep(0)
        if second_read_entered.is_set():
            await tasks[1]
        release_first_write.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        final = await first.context("conv-shared-lock")

        assert sum(isinstance(result, dict) for result in results) == 1
        assert sum(isinstance(result, ConversationStateConflictError) for result in results) == 1
        assert final["state_version"] == current["state_version"] + 1
    finally:
        release_first_write.set()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_aclose_closes_connection_idempotently(tmp_path) -> None:
    from dataworks_agent.agent.conversation_graph import ConversationGraph

    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    try:
        await graph.context("conv-close")
        connection = graph._connection
        assert connection is not None

        await graph.aclose()
        await graph.aclose()

        with pytest.raises(ValueError, match="connection"):
            await connection.execute("SELECT 1")
    finally:
        await graph.aclose()


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
    assert resolved["state_version"] == 2
    assert state["selected_resources"]["table"] == "giikin_aliyun.tb_dwd_order"
    assert state["params"]["table_name"] == "giikin_aliyun.tb_dwd_order"
    assert state["pending_interaction"] == {}
    assert state["pending_objective"] == ""
    assert state["state_version"] == 2


@pytest.mark.asyncio
async def test_legacy_resolve_cancel_serializes_with_answer(tmp_path, monkeypatch) -> None:
    from dataworks_agent.agent.conversation_graph import ConversationGraph

    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    pending = build_interaction(
        {
            "option_chips": [
                {
                    "type": "pick_table",
                    "id": "table_1",
                    "label": "query orders",
                    "value": "giikin_aliyun.tb_dwd_order",
                }
            ]
        },
        purpose="select_table",
        state_version=1,
    )
    assert pending is not None
    answer_write_entered = asyncio.Event()
    release_answer_write = asyncio.Event()
    resolve_entered = asyncio.Event()
    tasks = []

    try:
        current = await graph.remember(
            "conv-resolve-race",
            "find orders",
            needs_clarification=True,
            pending_interaction=pending.model_dump(),
        )
        update_state = graph._graph.aupdate_state
        resolve_unlocked = graph._resolve_unlocked

        async def delayed_answer_update(*args, **kwargs):
            answer_write_entered.set()
            await release_answer_write.wait()
            return await update_state(*args, **kwargs)

        async def observed_resolve(*args, **kwargs):
            resolve_entered.set()
            return await resolve_unlocked(*args, **kwargs)

        monkeypatch.setattr(graph._graph, "aupdate_state", delayed_answer_update)
        monkeypatch.setattr(graph, "_resolve_unlocked", observed_resolve)
        tasks.append(
            asyncio.create_task(
                graph.answer(
                    "conv-resolve-race",
                    InteractionAnswer(
                        interaction_id=pending.interaction_id,
                        option_id="table_1",
                        state_version=current["state_version"],
                    ),
                )
            )
        )
        await answer_write_entered.wait()
        tasks.append(asyncio.create_task(graph.resolve("取消", "conv-resolve-race")))
        await asyncio.sleep(0)
        if resolve_entered.is_set():
            await tasks[1]
        release_answer_write.set()
        answer_result, resolve_result = await asyncio.gather(*tasks, return_exceptions=True)
        final = await graph.context("conv-resolve-race")

        assert resolve_result == "取消"
        assert final["pending_interaction"] == {}
        if isinstance(answer_result, InteractionExpiredError):
            assert final["state_version"] == current["state_version"] + 1
        else:
            assert answer_result["state_version"] == current["state_version"] + 1
            assert final["state_version"] == current["state_version"] + 2
    finally:
        release_answer_write.set()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await graph.aclose()


@pytest.mark.asyncio
async def test_cancel_atomically_clears_pending_and_increments_version(tmp_path) -> None:
    from dataworks_agent.agent.conversation_graph import ConversationGraph

    graph = ConversationGraph(str(tmp_path / "conversation.db"))
    pending = PendingInteraction(
        interaction_id="int-cancel",
        type="free_text",
        purpose="select_table",
        prompt="请选择表",
        state_version=1,
    )
    remembered = await graph.remember(
        "conv-cancel",
        "找订单表",
        needs_clarification=True,
        pending_interaction=pending.model_dump(),
        selected_resources={"table": "giikin_aliyun.tb_dwd_order"},
        task_status="waiting_user",
    )

    cancelled = await graph.cancel("conv-cancel")
    restored = await graph.context("conv-cancel")

    assert remembered["state_version"] == 1
    assert cancelled["state_version"] == 2
    assert cancelled["pending_interaction"] == {}
    assert cancelled["pending_objective"] == ""
    assert cancelled["task_status"] == "cancelled"
    assert cancelled["selected_resources"] == {"table": "giikin_aliyun.tb_dwd_order"}
    assert restored == cancelled


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
    assert execute["params"]["interaction_purpose"] == "select_table"


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


def test_table_clarification_groups_large_candidate_sets_by_layer() -> None:
    from dataworks_agent.agent.workflow_service import (
        AgentWorkflowService,
        QueryNeedsClarificationError,
    )

    chips = [
        {
            "type": "pick_table",
            "id": f"opt-{index}",
            "label": f"project.tb_{layer}_orders_{index}",
            "value": f"project.tb_{layer}_orders_{index}",
            "layer": layer,
        }
        for index, layer in enumerate(
            ["ods", "ods", "dwd", "dwd", "dwd", "dws", "dws", "dmr", "dmr"]
        )
    ]
    result = AgentWorkflowService()._query_clarification_result(
        QueryNeedsClarificationError("orders", [], option_chips=chips),
        "dev_execute",
    )

    interaction = result.data["interaction"]
    assert interaction["purpose"] == "select_layer"
    assert {option["value"] for option in interaction["options"]} == {
        "ods",
        "dwd",
        "dws",
        "dmr",
    }
    assert result.data["option_chips"][-1]["type"] == "free_text"


def test_table_clarification_keeps_full_identifiers_for_small_sets() -> None:
    from dataworks_agent.agent.workflow_service import (
        AgentWorkflowService,
        QueryNeedsClarificationError,
    )

    full_name = "giikin_aliyun.tb_dwd_order"
    result = AgentWorkflowService()._query_clarification_result(
        QueryNeedsClarificationError(
            "orders",
            [],
            option_chips=[
                {
                    "type": "pick_table",
                    "id": "table-1",
                    "label": full_name,
                    "value": full_name,
                    "layer": "dwd",
                }
            ],
        ),
        "dev_execute",
    )

    interaction = result.data["interaction"]
    assert interaction["purpose"] == "select_table"
    assert interaction["options"][0]["value"] == full_name
    assert interaction["options"][0]["payload"] == {
        "params": {"table_name": full_name},
        "selected_resources": {"table": full_name},
    }


def test_selected_table_returns_follow_up_actions_with_same_identifier() -> None:
    from dataworks_agent.agent.workflow_service import AgentWorkflowService

    full_name = "giikin_aliyun.tb_dwd_order"
    result = AgentWorkflowService()._selected_table_action_result(full_name, "dev_execute")

    assert result.data["selected_table"] == full_name
    assert result.data["interaction"]["purpose"] == "select_action"
    actions = {
        option["payload"]["params"]["table_action"]: option
        for option in result.data["interaction"]["options"]
    }
    assert set(actions) == {
        "view_columns",
        "preview_data",
        "view_partitions",
        "view_lineage",
        "generate_ods_node",
        "generate_dwd_node",
    }
    assert all(
        option["payload"]["params"]["table_name"] == full_name for option in actions.values()
    )


@pytest.mark.asyncio
async def test_generate_node_action_returns_confirmation_without_writing(monkeypatch) -> None:
    from dataworks_agent.agent.workflow_service import AgentWorkflowService
    from dataworks_agent.services.ods_oss.directory_guard import ExistingDirectoryEvidence
    from dataworks_agent.state import app_state

    parent = "业务流程/106_广告报告/MaxCompute/数据开发/02_DWD"
    bff = MagicMock()
    bff.check_existing_directory = AsyncMock(
        return_value=ExistingDirectoryEvidence.from_check(parent, "datastudio_directory_tree", True)
    )
    nodes = MagicMock()
    nodes.get_node_uuid_by_path = AsyncMock(return_value=None)
    nodes.create_node = AsyncMock()
    nodes.update_node = AsyncMock()
    monkeypatch.setattr(app_state, "_bff_client", bff)
    monkeypatch.setattr(app_state, "_node_client", nodes)

    result = await AgentWorkflowService()._prepare_node_write_confirmation(
        "giikin_aliyun.tb_dwd_order",
        "DWD",
        {"environment": "test"},
        "dev_execute",
    )

    assert result.success is True
    assert result.data["interaction"]["purpose"] == "confirm_node_write"
    plan = next(
        option["payload"]["params"]["node_write_plan"]
        for option in result.data["interaction"]["options"]
        if option["id"] == "confirm_node_write"
    )
    assert plan["parent_path"] == parent
    assert plan["node_path"].startswith(parent + "/")
    assert plan["operation"] == "create"
    assert plan["publish"] is False
    nodes.create_node.assert_not_awaited()
    nodes.update_node.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_node_write_rechecks_and_updates_existing_uuid(monkeypatch) -> None:
    from dataworks_agent.agent.workflow_service import AgentWorkflowService
    from dataworks_agent.services.ods_oss.directory_guard import ExistingDirectoryEvidence
    from dataworks_agent.state import app_state

    parent = "业务流程/106_广告报告/MaxCompute/数据开发/02_DWD"
    node_name = "tb_dwd_order"
    node_path = f"{parent}/{node_name}"
    script = "-- Agent draft\nSELECT * FROM giikin_aliyun.tb_dwd_order;"
    plan = {
        "decision_id": "placement-1",
        "environment": "test",
        "layer": "DWD",
        "source_table": "giikin_aliyun.tb_dwd_order",
        "node_name": node_name,
        "parent_path": parent,
        "node_path": node_path,
        "language": "odps-sql",
        "script_content": script,
        "operation": "update",
        "existing_uuid": "node-existing",
        "publish": False,
    }
    bff = MagicMock()
    bff.check_existing_directory = AsyncMock(
        return_value=ExistingDirectoryEvidence.from_check(parent, "datastudio_directory_tree", True)
    )
    nodes = MagicMock()
    nodes.get_node_uuid_by_path = AsyncMock(return_value="node-existing")
    nodes.create_node = AsyncMock()
    nodes.update_node = AsyncMock(return_value=True)
    api = MagicMock()
    api.get_node = AsyncMock(
        return_value={
            "Node": {
                "Id": "node-existing",
                "Name": node_name,
                "Spec": json.dumps(
                    {
                        "spec": {
                            "nodes": [
                                {
                                    "name": node_name,
                                    "script": {
                                        "path": node_path,
                                        "language": "odps-sql",
                                        "content": script,
                                    },
                                }
                            ]
                        }
                    }
                ),
            }
        }
    )
    monkeypatch.setattr(app_state, "_bff_client", bff)
    monkeypatch.setattr(app_state, "_node_client", nodes)
    monkeypatch.setattr(app_state, "_openapi_client", api)

    result = await AgentWorkflowService()._execute_confirmed_node_write(plan, "dev_execute")

    assert result.success is True
    assert result.data["node_uuid"] == "node-existing"
    assert result.data["operation"] == "update"
    assert result.data["published"] is False
    nodes.create_node.assert_not_awaited()
    nodes.update_node.assert_awaited_once_with("node-existing", script)


@pytest.mark.asyncio
async def test_confirmed_node_write_creates_draft_with_fresh_evidence(monkeypatch) -> None:
    from dataworks_agent.agent.workflow_service import AgentWorkflowService
    from dataworks_agent.services.ods_oss.directory_guard import ExistingDirectoryEvidence
    from dataworks_agent.state import app_state

    parent = "业务流程/106_广告报告/MaxCompute/数据开发/00_ODS"
    node_name = "tb_ods_order"
    node_path = f"{parent}/{node_name}"
    script = "-- Agent draft\nSELECT * FROM giikin_aliyun.tb_dwd_order;"
    plan = {
        "decision_id": "placement-1",
        "environment": "test",
        "layer": "ODS",
        "source_table": "giikin_aliyun.tb_dwd_order",
        "node_name": node_name,
        "parent_path": parent,
        "node_path": node_path,
        "language": "odps-sql",
        "script_content": script,
        "operation": "create",
        "existing_uuid": "",
        "publish": False,
    }
    evidence = ExistingDirectoryEvidence.from_check(parent, "datastudio_directory_tree", True)
    bff = MagicMock()
    bff.check_existing_directory = AsyncMock(return_value=evidence)
    nodes = MagicMock()
    nodes.get_node_uuid_by_path = AsyncMock(return_value=None)
    nodes.create_node = AsyncMock(return_value="node-new")
    nodes.update_node = AsyncMock(return_value=True)
    api = MagicMock()
    api.get_node = AsyncMock(
        return_value={
            "Node": {
                "Id": "node-new",
                "Name": node_name,
                "Spec": json.dumps(
                    {
                        "spec": {
                            "nodes": [
                                {
                                    "name": node_name,
                                    "script": {
                                        "path": node_path,
                                        "language": "odps-sql",
                                        "content": script,
                                    },
                                }
                            ]
                        }
                    }
                ),
            }
        }
    )
    monkeypatch.setattr(app_state, "_bff_client", bff)
    monkeypatch.setattr(app_state, "_node_client", nodes)
    monkeypatch.setattr(app_state, "_openapi_client", api)

    result = await AgentWorkflowService()._execute_confirmed_node_write(plan, "dev_execute")

    assert result.success is True
    nodes.create_node.assert_awaited_once()
    assert nodes.create_node.await_args.kwargs["directory_evidence"] == evidence
    nodes.update_node.assert_awaited_once_with("node-new", script)
    assert result.data["published"] is False


@pytest.mark.asyncio
async def test_confirmed_node_write_blocks_when_directory_recheck_fails(monkeypatch) -> None:
    from dataworks_agent.agent.workflow_service import AgentWorkflowService
    from dataworks_agent.services.ods_oss.directory_guard import ExistingDirectoryEvidence
    from dataworks_agent.state import app_state

    parent = "业务流程/106_广告报告/MaxCompute/数据开发/02_DWD"
    bff = MagicMock()
    bff.check_existing_directory = AsyncMock(
        return_value=ExistingDirectoryEvidence.from_check(parent, "no_positive_evidence", False)
    )
    nodes = MagicMock()
    nodes.get_node_uuid_by_path = AsyncMock()
    nodes.create_node = AsyncMock()
    nodes.update_node = AsyncMock()
    monkeypatch.setattr(app_state, "_bff_client", bff)
    monkeypatch.setattr(app_state, "_node_client", nodes)

    result = await AgentWorkflowService()._execute_confirmed_node_write(
        {
            "decision_id": "placement-1",
            "environment": "test",
            "layer": "DWD",
            "source_table": "giikin_aliyun.tb_dwd_order",
            "node_name": "tb_dwd_order",
            "parent_path": parent,
            "node_path": f"{parent}/tb_dwd_order",
            "language": "odps-sql",
            "script_content": "SELECT 1;",
            "publish": False,
        },
        "dev_execute",
    )

    assert result.success is False
    assert result.data["directory_creation_attempted"] is False
    nodes.get_node_uuid_by_path.assert_not_awaited()
    nodes.create_node.assert_not_awaited()
    nodes.update_node.assert_not_awaited()


@pytest.mark.asyncio
async def test_layer_option_refines_previous_objective_text() -> None:
    from dataworks_agent.agent.core import ChatAgent
    from dataworks_agent.agent.nlu.intent_parser import Intent
    from dataworks_agent.agent.workflow_service import WorkflowResult

    graph = MagicMock()
    graph.context = AsyncMock(
        return_value={
            "objective": "找订单表",
            "pending_objective": "找订单表",
            "action": "ask_data",
            "params": {},
            "pending_interaction": {
                "interaction_id": "int-layer",
                "type": "single_select",
                "purpose": "select_layer",
                "prompt": "请选择分层",
                "options": [],
                "allow_custom_input": True,
                "custom_input_placeholder": "",
                "status": "pending",
                "state_version": 1,
            },
        }
    )
    graph.answer = AsyncMock(return_value={"params": {"layer": "dwd"}})
    graph.resolve = AsyncMock(side_effect=lambda message, *_args, **_kwargs: message)
    graph.remember = AsyncMock()
    agent = ChatAgent()
    agent._conversation_graph = graph
    agent._intent_parser = MagicMock()
    agent._intent_parser.parse.return_value = Intent(action="unknown", confidence=0.1)
    agent._workflow_service = MagicMock()
    agent._workflow_service.understand_business_query.return_value = None
    agent._workflow_service.execute = AsyncMock(
        return_value=WorkflowResult(True, "ok", "ask_data", "dev_execute")
    )
    agent._save_conversation_message = MagicMock()

    await agent.chat(
        "DWD",
        conversation_id="conv-layer",
        interaction_answer=InteractionAnswer(
            interaction_id="int-layer",
            option_id="layer_dwd",
            state_version=1,
        ),
    )

    parsed_message = agent._intent_parser.parse.call_args.args[0]
    assert "找订单表" in parsed_message
    assert "只要 dwd" in parsed_message
    assert agent._workflow_service.execute.await_args.kwargs["params"]["layer"] == "dwd"


@pytest.mark.parametrize("message", ["取消", "重新开始", "新任务", "cancel", "reset"])
def test_conversation_reset_recognizes_supported_commands(message: str) -> None:
    from dataworks_agent.agent.core import ChatAgent

    assert ChatAgent._is_conversation_reset(message) is True
