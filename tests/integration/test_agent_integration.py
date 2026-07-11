"""Agent 集成测试 — 测试完整对话流程。

使用真实 ChatAgent（NLU→Planner→Executor 链路），ToolExecutor 为 stub 实现。
验证从 API 请求到 Agent 处理再到响应的完整链路。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dataworks_agent.agent.core import ChatAgent
from dataworks_agent.routers.agent import router


@pytest.fixture
def client():
    """创建带真实 ChatAgent 的测试客户端。"""
    app = FastAPI()
    app.include_router(router, prefix="/agent")

    import dataworks_agent.routers.agent as agent_module

    original_agent = agent_module._agent
    agent_module._agent = ChatAgent()

    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        agent_module._agent = original_agent


def test_full_chat_flow(client):
    """测试完整对话流程：创建表 → 查询血缘。"""
    # 1. 创建表
    response = client.post(
        "/agent/chat",
        json={"message": "创建ods_user表"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "task_id" in data["data"]

    # 2. 查询血缘
    response = client.post(
        "/agent/chat",
        json={"message": "查询ods_user的血缘"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "task_id" in data["data"]


def test_unknown_intent(client):
    """测试未知意图"""
    response = client.post(
        "/agent/chat",
        json={"message": "今天天气怎么样"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_empty_message_rejected(client):
    """测试空消息被拒绝"""
    response = client.post(
        "/agent/chat",
        json={"message": ""},
    )
    assert response.status_code == 422


def test_create_table_returns_task_id(client):
    """测试建表请求返回 task_id 和步骤数。"""
    response = client.post(
        "/agent/chat",
        json={"message": "创建ods_order表"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "task_id" in data["data"]
    assert "steps_completed" in data["data"]
    assert data["data"]["steps_completed"] > 0


def test_lineage_query_returns_task_id(client):
    """测试血缘查询返回 task_id。"""
    response = client.post(
        "/agent/chat",
        json={"message": "查询dwd_order_detail的血缘"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "task_id" in data["data"]


def test_complex_task_decomposition(client):
    """测试复杂任务拆解"""
    response = client.post(
        "/agent/chat",
        json={"message": "创建ods_user表并配置调度"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # 复杂任务应该有多个步骤
    assert data["data"]["steps_completed"] >= 2
