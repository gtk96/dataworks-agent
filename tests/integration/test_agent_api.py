"""Agent API 集成测试 — 测试 /agent/chat 端点。

注意: 由于 Python 3.14 与 cryptography 的兼容性问题,
这些测试使用独立的 FastAPI app 而非完整的 main.py app。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dataworks_agent.agent.core import ChatAgent, ChatResponse
from dataworks_agent.agent.run_models import RunEvent
from dataworks_agent.routers.agent import router


@pytest.fixture
def client():
    """创建带 mock ChatAgent 的测试客户端。"""
    app = FastAPI()
    app.include_router(router, prefix="/agent")

    mock_agent = MagicMock(spec=ChatAgent)
    mock_agent.chat = AsyncMock(
        return_value=ChatResponse(
            message="已成功创建表 ods_user",
            success=True,
            data={"task_id": "test-123"},
        )
    )
    mock_agent.get_conversation_history.return_value = []
    mock_agent.get_conversation_context = AsyncMock(return_value={})

    import dataworks_agent.routers.agent as agent_module

    original_agent = agent_module._agent
    agent_module._agent = mock_agent

    test_client = TestClient(app)
    yield test_client, mock_agent

    agent_module._agent = original_agent


def test_chat_endpoint(client):
    """测试聊天端点"""
    test_client, _mock_agent = client
    response = test_client.post(
        "/agent/chat",
        json={"message": "创建ods_user表"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "ods_user" in data["message"]


def test_chat_endpoint_empty_message(client):
    """测试空消息返回 422 验证错误"""
    test_client, _mock_agent = client

    response = test_client.post(
        "/agent/chat",
        json={"message": ""},
    )
    assert response.status_code == 422  # Pydantic validation error


def test_chat_endpoint_agent_error(client):
    """测试 Agent 处理失败"""
    test_client, mock_agent = client
    mock_agent.chat = AsyncMock(
        return_value=ChatResponse(
            message="处理失败: 连接超时",
            success=False,
            error="连接超时",
        )
    )

    response = test_client.post(
        "/agent/chat",
        json={"message": "查询表结构"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "error" in data


def test_chat_endpoint_message_forwarded(client):
    """测试消息正确转发给 Agent"""
    test_client, mock_agent = client
    response = test_client.post(
        "/agent/chat",
        json={"message": "测试消息"},
    )
    assert response.status_code == 200
    mock_agent.chat.assert_called_once_with("测试消息", execution_mode="plan", conversation_id=None)


def test_structured_interaction_answer_forwarded(client):
    test_client, mock_agent = client
    answer = {
        "interaction_id": "int-1",
        "option_id": "table-1",
        "state_version": 2,
    }

    response = test_client.post(
        "/agent/chat",
        json={
            "message": "订单表",
            "conversation_id": "conv-1",
            "interaction_answer": answer,
        },
    )

    assert response.status_code == 200
    call = mock_agent.chat.await_args
    assert call.args == ("订单表",)
    assert call.kwargs["execution_mode"] == "plan"
    assert call.kwargs["conversation_id"] == "conv-1"
    assert call.kwargs["interaction_answer"].model_dump(exclude_none=True) == answer


def test_websocket_structured_interaction_answer_forwarded(client):
    test_client, mock_agent = client
    answer = {
        "interaction_id": "int-1",
        "custom_text": "只看退款金额表",
        "state_version": 2,
    }

    with test_client.websocket_connect("/agent/ws") as websocket:
        websocket.send_json(
            {
                "message": "只看退款金额表",
                "conversation_id": "conv-1",
                "interaction_answer": answer,
            }
        )
        payload = websocket.receive_json()

    assert payload["type"] == "response"
    call = mock_agent.chat.await_args
    assert call.args == ("只看退款金额表",)
    assert call.kwargs["conversation_id"] == "conv-1"
    assert call.kwargs["interaction_answer"].model_dump(exclude_none=True) == answer


def test_messages_returns_active_interaction_and_state_version(client):
    test_client, mock_agent = client
    interaction = {
        "interaction_id": "int-1",
        "type": "single_select",
        "purpose": "select_table",
        "prompt": "请选择表",
        "options": [],
        "allow_custom_input": True,
        "custom_input_placeholder": "",
        "status": "pending",
        "state_version": 3,
    }
    mock_agent.get_conversation_history.return_value = [
        {
            "role": "assistant",
            "content": "请选择表",
            "timestamp": "2026-07-17T00:00:00+00:00",
            "payload": {"interaction": interaction},
        }
    ]
    mock_agent.get_conversation_context.return_value = {
        "objective": "查订单",
        "action": "ask_data",
        "task_status": "waiting_user",
        "selected_resources": {"table": "dw.orders"},
        "pending_interaction": interaction,
        "state_version": 3,
    }

    response = test_client.get("/agent/messages", params={"conversation_id": "conv-1"})

    assert response.status_code == 200
    assert response.json() == {
        "messages": mock_agent.get_conversation_history.return_value,
        "active_interaction": interaction,
        "state_version": 3,
        "conversation": {
            "conversation_id": "conv-1",
            "active_goal": "查订单",
            "action": "ask_data",
            "status": "waiting_user",
            "state_version": 3,
            "selected_resources": {"table": "dw.orders"},
        },
    }
    mock_agent.get_conversation_context.assert_awaited_once_with("conv-1")


def test_expired_answer_preserves_agent_snapshot_without_second_read(client):
    test_client, mock_agent = client
    latest_interaction = {
        "interaction_id": "int_latest",
        "type": "single_select",
        "purpose": "select_table",
        "prompt": "请选择最新候选",
        "options": [],
        "allow_custom_input": True,
        "custom_input_placeholder": "",
        "status": "pending",
        "state_version": 9,
    }
    conversation = {
        "conversation_id": "conv-1",
        "active_goal": "查订单",
        "action": "ask_data",
        "status": "waiting_user",
        "state_version": 9,
        "selected_resources": {"table": "dw.orders"},
    }
    mock_agent.chat = AsyncMock(
        return_value=ChatResponse(
            message="当前候选已经更新，请根据最新选项继续。",
            success=False,
            data={
                "interaction": latest_interaction,
                "conversation": conversation,
            },
            error="interaction_expired",
        )
    )
    mock_agent.get_conversation_context.side_effect = AssertionError(
        "complete agent snapshot must not be reread"
    )

    response = test_client.post(
        "/agent/chat",
        json={"message": "第二个", "conversation_id": "conv-1"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["error"] == "interaction_expired"
    assert payload["data"]["interaction"] == latest_interaction
    assert payload["data"]["conversation"] == conversation
    mock_agent.get_conversation_context.assert_not_awaited()


def test_websocket_preserves_same_complete_agent_payload(client):
    test_client, mock_agent = client
    conversation = {
        "conversation_id": "conv-ws",
        "active_goal": "查订单",
        "action": "ask_data",
        "status": "active",
        "state_version": 4,
        "selected_resources": {},
    }
    agent_data = {
        "task_id": "task-ws",
        "status": {"state": "running"},
        "interaction": None,
        "conversation": conversation,
    }
    mock_agent.chat = AsyncMock(
        return_value=ChatResponse(
            message="继续处理",
            success=True,
            data=agent_data,
        )
    )
    mock_agent.get_conversation_context.side_effect = AssertionError(
        "complete agent snapshot must not be reread"
    )

    with test_client.websocket_connect("/agent/ws") as websocket:
        websocket.send_json({"message": "继续", "conversation_id": "conv-ws"})
        payload = websocket.receive_json()

    assert payload["type"] == "response"
    assert payload["data"] == {
        "message": "继续处理",
        "success": True,
        "data": agent_data,
        "error": None,
    }
    mock_agent.get_conversation_context.assert_not_awaited()


def test_run_stream_emits_real_ordered_events_and_one_final_response(client):
    test_client, mock_agent = client

    async def run_with_events(_message, **kwargs):
        sink = kwargs["run_event_sink"]
        await sink(RunEvent("run.started", "run-1", 1, {"conversation_id": "conv-1"}))
        await sink(RunEvent("tool.started", "run-1", 2, {"tool": "find_table"}))
        await sink(
            RunEvent(
                "tool.completed",
                "run-1",
                3,
                {"tool": "find_table", "success": True},
            )
        )
        await sink(RunEvent("state.persisted", "run-1", 4, {"state_version": 2}))
        response = ChatResponse(
            message="请选择订单表",
            success=True,
            data={"agent_mode": "tool_result"},
        )
        await sink(
            RunEvent(
                "response.completed",
                "run-1",
                5,
                {
                    "response": {
                        "message": response.message,
                        "success": response.success,
                        "data": response.data,
                        "error": response.error,
                    }
                },
            )
        )
        return response

    mock_agent.chat.side_effect = run_with_events

    response = test_client.post(
        "/agent/runs/stream",
        json={"message": "找订单表", "conversation_id": "conv-1"},
    )
    events = [line for line in response.text.splitlines() if line.strip()]
    payloads = [__import__("json").loads(line) for line in events]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [item["type"] for item in payloads] == [
        "run.started",
        "tool.started",
        "tool.completed",
        "state.persisted",
        "response.completed",
    ]
    assert sum(item["type"] == "response.completed" for item in payloads) == 1
