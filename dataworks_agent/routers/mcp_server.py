"""MCP Server API — 自建 AK/SK 版 MCP Server。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class ToolCallRequest(BaseModel):
    """工具调用请求。"""

    tool_name: str = Field(..., description="工具名称")
    parameters: dict[str, Any] = Field(default_factory=dict, description="参数")
    user_id: str = Field(default="", description="用户 ID")
    session_id: str = Field(default="", description="会话 ID")


@router.get("/tools")
async def list_tools(category: str | None = None):
    """列出可用工具。"""
    from dataworks_agent.mcp_server.server import MCPServer

    server = MCPServer()
    tools = server.list_tools(category=category)

    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "parameters": t.parameters,
                "requires_auth": t.requires_auth,
                "read_only": t.read_only,
            }
            for t in tools
        ],
        "total": len(tools),
    }


@router.get("/tools/{tool_name}")
async def get_tool(tool_name: str):
    """获取工具定义。"""
    from dataworks_agent.mcp_server.server import MCPServer

    server = MCPServer()
    tool = server.get_tool(tool_name)

    if not tool:
        raise HTTPException(status_code=404, detail=f"工具 {tool_name} 不存在")

    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "parameters": tool.parameters,
        "requires_auth": tool.requires_auth,
        "read_only": tool.read_only,
    }


@router.post("/call")
async def call_tool(body: ToolCallRequest):
    """调用工具。"""
    from dataworks_agent.mcp_server.server import MCPServer
    from dataworks_agent.mcp_server.server import ToolCallRequest as ToolCallRequestObj

    server = MCPServer()
    request = ToolCallRequestObj(
        tool_name=body.tool_name,
        parameters=body.parameters,
        user_id=body.user_id,
        session_id=body.session_id,
    )
    result = await server.call_tool(request)

    return {
        "success": result.success,
        "result": result.result,
        "error": result.error,
    }


@router.get("/categories")
async def list_categories():
    """列出工具类别。"""
    from dataworks_agent.mcp_server.server import MCPServer

    server = MCPServer()
    tools = server.list_tools()

    categories = {}
    for tool in tools:
        if tool.category not in categories:
            categories[tool.category] = 0
        categories[tool.category] += 1

    return {"categories": categories}
