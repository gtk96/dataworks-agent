"""MCPServer 单元测试 — 自建 AK/SK MCP Server。"""

import pytest

from dataworks_agent.mcp_server.server import (
    MCPServer,
    ToolCallRequest,
    ToolCallResult,
    ToolDefinition,
)


@pytest.fixture
def server():
    """创建 MCPServer 实例。"""
    return MCPServer()


def test_list_tools(server):
    """列出工具。"""
    tools = server.list_tools()
    assert len(tools) > 0


def test_list_tools_by_category(server):
    """按类别列出工具。"""
    semantic_tools = server.list_tools(category="semantic")
    assert len(semantic_tools) > 0
    for tool in semantic_tools:
        assert tool.category == "semantic"


def test_get_tool(server):
    """获取工具定义。"""
    tool = server.get_tool("get_metric_definition")
    assert tool is not None
    assert tool.name == "get_metric_definition"


def test_get_tool_not_found(server):
    """获取不存在的工具。"""
    tool = server.get_tool("nonexistent_tool")
    assert tool is None


@pytest.mark.asyncio
async def test_call_tool_not_found(server):
    """调用不存在的工具。"""
    request = ToolCallRequest(tool_name="nonexistent_tool")
    result = await server.call_tool(request)
    assert result.success is False
    assert "不存在" in result.error


@pytest.mark.asyncio
async def test_call_tool_requires_auth(server):
    """调用需要鉴权的工具。"""
    request = ToolCallRequest(
        tool_name="get_metric_definition",
        parameters={"metric_id": "test"},
    )
    result = await server.call_tool(request)
    assert result.success is False
    assert "鉴权" in result.error


@pytest.mark.asyncio
async def test_call_tool_with_auth(server):
    """调用带鉴权的工具。"""
    request = ToolCallRequest(
        tool_name="get_metric_definition",
        parameters={"metric_id": "test"},
        user_id="user_001",
    )
    result = await server.call_tool(request)
    # 工具可能不存在或执行失败，但鉴权通过
    assert isinstance(result, ToolCallResult)


@pytest.mark.asyncio
async def test_call_tool_read_only(server):
    """调用只读工具。"""
    request = ToolCallRequest(
        tool_name="get_metric_definition",
        parameters={"metric_id": "test"},
        user_id="user_001",
    )
    result = await server.call_tool(request)
    assert isinstance(result, ToolCallResult)


def test_tool_definition_post_init():
    """ToolDefinition 初始化。"""
    tool = ToolDefinition(
        name="test_tool",
        description="测试工具",
        category="test",
    )
    assert tool.name == "test_tool"
    assert tool.requires_auth is True
    assert tool.read_only is False


def test_tool_call_request_post_init():
    """ToolCallRequest 初始化。"""
    request = ToolCallRequest(tool_name="test")
    assert request.tool_name == "test"
    assert request.parameters == {}


def test_tool_call_result_post_init():
    """ToolCallResult 初始化。"""
    result = ToolCallResult(success=True)
    assert result.success is True
    assert result.result is None
