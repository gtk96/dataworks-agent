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
    app.include_router(router)

    # Mock ChatAgent
    mock_agent = MagicMock(spec=ChatAgent)
    mock_agent.chat = AsyncMock(return_value=ChatResponse(
        message="已成功创建表 ods_user",
        success=True,
        data={"task_id": "test-123"},
    ))

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
    """测试空消息处理"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)

    mock_agent = MagicMock(spec=ChatAgent)
    mock_agent.chat = AsyncMock(return_value=ChatResponse(
        message="请输入您的需求",
        success=False,
        error="empty message",
    ))

    import dataworks_agent.routers.agent as agent_module
    original_agent = agent_module._agent
    agent_module._agent = mock_agent

    try:
        client = TestClient(app)
        response = client.post(
            "/agent/chat",
            json={"message": ""},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "empty message"
    finally:
        agent_module._agent = original_agent


@pytest.mark.asyncio
async def test_chat_router_missing_message():
    """测试缺少 message 字段"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)

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
