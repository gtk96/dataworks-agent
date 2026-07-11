"""Agent 路由单元测试 — 验证路由逻辑。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.agent.core import ChatAgent, ChatResponse
from dataworks_agent.routers.agent import ChatRequest, router


@pytest.mark.asyncio
async def test_chat_router_logic():
    """测试路由处理逻辑"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/agent")

    # Mock ChatAgent
    mock_agent = MagicMock(spec=ChatAgent)
    mock_agent.chat = AsyncMock(
        return_value=ChatResponse(
            message="已成功创建表 ods_user",
            success=True,
            data={"task_id": "test-123"},
        )
    )

    # Patch the module-level agent
    import dataworks_agent.routers.agent as agent_module

    original_agent = agent_module._agent
    agent_module._agent = mock_agent

    try:
        client = TestClient(app)
        response = client.post(
            "/agent/chat",
            json={"message": "创建ods_user表"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "ods_user" in data["message"]
        mock_agent.chat.assert_called_once_with("创建ods_user表")
    finally:
        agent_module._agent = original_agent


@pytest.mark.asyncio
async def test_chat_router_empty_message():
    """测试空消息返回 422 验证错误"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/agent")

    client = TestClient(app)
    response = client.post(
        "/agent/chat",
        json={"message": ""},
    )
    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_chat_router_missing_message():
    """测试缺少 message 字段"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/agent")

    client = TestClient(app)
    response = client.post(
        "/agent/chat",
        json={},
    )
    assert response.status_code == 422  # Pydantic validation error


def test_chat_request_model():
    """测试 ChatRequest 模型"""
    req = ChatRequest(message="test")
    assert req.message == "test"


def test_chat_response_model():
    """测试 ChatResponse 模型"""
    from dataworks_agent.routers.agent import ChatResponse as RouterChatResponse

    resp = RouterChatResponse(
        message="test",
        success=True,
        data={"key": "value"},
        error=None,
    )
    assert resp.message == "test"
    assert resp.success is True
    assert resp.data == {"key": "value"}
    assert resp.error is None


@pytest.mark.asyncio
async def test_websocket_message_processing():
    """测试 WebSocket 收到消息后调用 Agent 并返回响应"""
    from fastapi import WebSocketDisconnect

    from dataworks_agent.routers.agent import manager

    # Mock ChatAgent
    mock_agent = MagicMock(spec=ChatAgent)
    mock_agent.chat = AsyncMock(
        return_value=ChatResponse(
            message="已成功创建表 ods_user",
            success=True,
            data={"task_id": "test-123"},
        )
    )

    import dataworks_agent.routers.agent as agent_module

    original_agent = agent_module._agent
    agent_module._agent = mock_agent

    try:
        # 第一次 receive_json 返回消息，第二次抛出 WebSocketDisconnect 退出循环
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.receive_json = AsyncMock(
            side_effect=[{"message": "创建ods_user表"}, WebSocketDisconnect()]
        )
        ws.send_json = AsyncMock()

        from dataworks_agent.routers.agent import websocket_endpoint

        await websocket_endpoint(ws)

        # 验证连接管理
        ws.accept.assert_awaited_once()
        assert ws not in manager._connections

        # 验证 Agent 被调用
        mock_agent.chat.assert_called_once_with("创建ods_user表")

        # 验证响应格式
        ws.send_json.assert_awaited_once()
        call_args = ws.send_json.await_args.args[0]
        assert call_args["type"] == "response"
        assert call_args["data"]["success"] is True
        assert "ods_user" in call_args["data"]["message"]
    finally:
        agent_module._agent = original_agent
        manager._connections.clear()


@pytest.mark.asyncio
async def test_websocket_disconnect_cleans_up():
    """测试 WebSocket 断开连接后从池中移除"""
    from fastapi import WebSocketDisconnect

    from dataworks_agent.routers.agent import manager

    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.receive_json = AsyncMock(side_effect=WebSocketDisconnect())

    from dataworks_agent.routers.agent import websocket_endpoint

    await websocket_endpoint(ws)

    assert ws not in manager._connections


@pytest.mark.asyncio
async def test_websocket_exception_cleans_up():
    """测试 WebSocket 异常断开后从池中移除"""
    from dataworks_agent.routers.agent import manager

    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.receive_json = AsyncMock(side_effect=RuntimeError("connection reset"))

    from dataworks_agent.routers.agent import websocket_endpoint

    await websocket_endpoint(ws)

    assert ws not in manager._connections
