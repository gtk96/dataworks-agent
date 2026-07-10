"""Agent API 集成测试 — 测试 /agent/chat 端点。

注意: 由于 Python 3.14 与 cryptography 的兼容性问题,
这些测试使用独立的 FastAPI app 而非完整的 main.py app。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dataworks_agent.agent.core import ChatAgent, ChatResponse
from dataworks_agent.routers.agent import router


@pytest.fixture
def client():
    """创建带 mock ChatAgent 的测试客户端。"""
    app = FastAPI()
    app.include_router(router)

    mock_agent = MagicMock(spec=ChatAgent)
    mock_agent.chat = AsyncMock(return_value=ChatResponse(
        message="已成功创建表 ods_user",
        success=True,
        data={"task_id": "test-123"},
    ))

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
    """测试空消息"""
    test_client, mock_agent = client
    mock_agent.chat = AsyncMock(return_value=ChatResponse(
        message="请输入您的需求",
        success=False,
        error="empty message",
    ))

    response = test_client.post(
        "/agent/chat",
        json={"message": ""},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["error"] == "empty message"


def test_chat_endpoint_agent_error(client):
    """测试 Agent 处理失败"""
    test_client, mock_agent = client
    mock_agent.chat = AsyncMock(return_value=ChatResponse(
        message="处理失败: 连接超时",
        success=False,
        error="连接超时",
    ))

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
    mock_agent.chat.assert_called_once_with("测试消息")
