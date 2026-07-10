import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dataworks_agent.agent.core import ChatAgent, ChatResponse


def test_chat_response_initialization():
    """测试 ChatResponse 初始化"""
    response = ChatResponse(message="test")
    assert response.message == "test"
    assert response.success is True
    assert response.data == {}
    assert response.error is None


def test_chat_response_with_error():
    """测试 ChatResponse 错误状态"""
    response = ChatResponse(message="error", success=False, error="something wrong")
    assert response.success is False
    assert response.error == "something wrong"


@pytest.mark.asyncio
async def test_chat_agent_empty_message():
    """测试 ChatAgent 空消息处理"""
    agent = ChatAgent()
    response = await agent.chat("")
    assert response.success is False
    assert "请输入您的需求" in response.message


@pytest.mark.asyncio
async def test_chat_agent_whitespace_message():
    """测试 ChatAgent 纯空格消息"""
    agent = ChatAgent()
    response = await agent.chat("   ")
    assert response.success is False
    assert "请输入您的需求" in response.message


@pytest.mark.asyncio
async def test_chat_agent_delegates_to_agent():
    """测试 ChatAgent 委托给 runtime.agent.Agent"""
    from dataworks_agent.runtime.agent import AgentRequest, AgentResponse

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value=AgentResponse(
        success=True,
        response_type="result",
        content="查询结果",
        data={"table": "ods_user"},
    ))

    agent = ChatAgent()
    agent._agent = mock_agent

    response = await agent.chat("查询 ods_user")

    assert response.success is True
    assert response.message == "查询结果"
    assert response.data == {"table": "ods_user"}

    # 验证调用参数
    call_args = mock_agent.process.call_args[0][0]
    assert isinstance(call_args, AgentRequest)
    assert call_args.request_type == "query"
    assert call_args.content == "查询 ods_user"


@pytest.mark.asyncio
async def test_chat_agent_request_type_passed():
    """测试请求类型正确传递"""
    from dataworks_agent.runtime.agent import AgentResponse

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value=AgentResponse(
        success=True,
        response_type="result",
        content="建模结果",
    ))

    agent = ChatAgent()
    agent._agent = mock_agent

    response = await agent.chat("建表", request_type="modeling")

    call_args = mock_agent.process.call_args[0][0]
    assert call_args.request_type == "modeling"
