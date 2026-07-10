import pytest

from dataworks_agent.agent.core import ChatAgent, ChatResponse


@pytest.fixture
def agent():
    return ChatAgent()


def test_agent_initialization(agent):
    """测试 Agent 初始化"""
    assert agent is not None
    assert hasattr(agent, 'chat')


@pytest.mark.asyncio
async def test_agent_chat_returns_response(agent):
    """测试 Agent chat 方法返回响应"""
    response = await agent.chat("你好")
    assert isinstance(response, ChatResponse)
    assert response.message is not None
    assert response.success is True


@pytest.mark.asyncio
async def test_agent_chat_empty_message(agent):
    """测试空消息处理"""
    response = await agent.chat("")
    assert response.success is False
    assert "请输入您的需求" in response.message
