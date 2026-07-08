"""MCP Server — 自建 AK/SK 版 MCP Server。

实现 Requirement 18：暴露六类工具，每次调用鉴权 + 审计 + 数据边界。
"""

from dataworks_agent.mcp_server.server import MCPServer

__all__ = ["MCPServer"]
