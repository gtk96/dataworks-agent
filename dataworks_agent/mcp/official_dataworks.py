"""阿里云官方 DataWorks MCP stdio 客户端。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dataworks_agent.config import settings

logger = logging.getLogger(__name__)


DEFAULT_TOOL_NAMES = (
    "ListProjects,GetProject,ListNodes,GetNode,ListNodeDependencies,"
    "ListTables,GetTable,ListDataSources,GetDataSource,ListLineages,"
    "GetLineageRelationship,ListTaskInstances,GetTaskInstance,GetTaskInstanceLog,"
    "ListWorkflows,GetWorkflow,CreateNode,UpdateNode"
)


@dataclass
class OfficialMCPStatus:
    enabled: bool
    connected: bool = False
    server: str = "alibabacloud-dataworks-mcp-server"
    version: str = ""
    tool_count: int = 0
    tools: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "server": self.server,
            "version": self.version,
            "tool_count": self.tool_count,
            "tools": list(self.tools),
            "error": self.error,
        }


class OfficialDataWorksMCPClient:
    """管理官方 npm stdio MCP 子进程，并提供 tools/list 与 tools/call。"""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = asyncio.Lock()
        self._status = OfficialMCPStatus(enabled=settings.official_dataworks_mcp_enabled)

    @property
    def status(self) -> OfficialMCPStatus:
        return self._status

    def _server_parameters(self) -> StdioServerParameters:
        command = settings.official_dataworks_mcp_command
        if command.lower() == "npx" and shutil.which("npx.cmd"):
            command = "npx.cmd"
        package = settings.official_dataworks_mcp_package
        env = os.environ.copy()
        env.update(
            {
                "REGION": settings.dataworks_region,
                "ALIBABA_CLOUD_ACCESS_KEY_ID": settings.aliyun_access_key_id,
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET": settings.aliyun_access_key_secret,
                "TOOL_NAMES": settings.official_dataworks_mcp_tool_names or DEFAULT_TOOL_NAMES,
            }
        )
        if settings.official_dataworks_mcp_tool_categories:
            env["TOOL_CATEGORIES"] = settings.official_dataworks_mcp_tool_categories
        return StdioServerParameters(command=command, args=["-y", package], env=env)

    async def connect(self) -> OfficialMCPStatus:
        if not self._status.enabled:
            return self._status
        if not settings.aliyun_access_key_id or not settings.aliyun_access_key_secret:
            self._status.error = "缺少 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET"
            return self._status
        async with self._lock:
            if self._session is not None:
                return self._status
            stack = AsyncExitStack()
            stdio_logger = logging.getLogger("mcp.client.stdio")
            previous_stdio_level = stdio_logger.level
            try:
                # 官方 npm server 会把启动提示写到 stdout；MCP SDK 能跳过，但会输出大量解析堆栈。
                # 初始化期间只屏蔽这类已知噪声，连接结果仍由 initialize/tools/list 严格校验。
                stdio_logger.setLevel(logging.CRITICAL)
                streams = await stack.enter_async_context(stdio_client(self._server_parameters()))
                session = await stack.enter_async_context(ClientSession(*streams))
                init = await asyncio.wait_for(session.initialize(), timeout=30)
                tools_result = await asyncio.wait_for(session.list_tools(), timeout=30)
                self._stack = stack
                self._session = session
                self._status.connected = True
                self._status.version = getattr(init.serverInfo, "version", "") or ""
                self._status.tools = [tool.name for tool in tools_result.tools]
                self._status.tool_count = len(self._status.tools)
                self._status.error = ""
                logger.info("阿里云官方 DataWorks MCP 已连接，工具数: %d", self._status.tool_count)
            except Exception as exc:
                await stack.aclose()
                self._status.connected = False
                self._status.error = str(exc)[:300]
                logger.warning("阿里云官方 DataWorks MCP 初始化失败（降级运行）: %s", exc)
            finally:
                stdio_logger.setLevel(previous_stdio_level)
            return self._status

    async def list_tools(self) -> list[str]:
        if self._session is None:
            await self.connect()
        return list(self._status.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            await self.connect()
        if self._session is None:
            raise RuntimeError(self._status.error or "官方 DataWorks MCP 未连接")
        if self._status.tools and name not in self._status.tools:
            raise ValueError(f"官方 MCP 工具未启用: {name}")
        async with self._lock:
            result = await self._session.call_tool(name, arguments)
        content: list[Any] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text is None:
                content.append(item.model_dump() if hasattr(item, "model_dump") else str(item))
                continue
            try:
                content.append(json.loads(text))
            except json.JSONDecodeError:
                content.append(text)
        if len(content) == 1:
            return content[0]
        return {"content": content, "is_error": bool(getattr(result, "isError", False))}

    async def close(self) -> None:
        async with self._lock:
            stack, self._stack = self._stack, None
            self._session = None
            self._status.connected = False
            if stack is not None:
                with contextlib.suppress(Exception):
                    await stack.aclose()
