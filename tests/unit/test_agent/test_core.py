import pytest

from dataworks_agent.agent.core import Agent, AgentResponse


@pytest.fixture
def agent():
    return Agent()


def test_agent_initialization(agent):
    """测试 Agent 初始化"""
    assert agent is not None
    assert hasattr(agent, 'chat')


def test_agent_chat_returns_response(agent):
    """测试 Agent chat 方法返回响应"""
    response = agent.chat("你好")
    assert isinstance(response, AgentResponse)
    assert response.message is not None
    assert response.success is True
