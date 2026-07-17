"""LazyMCPClient — MCP 懒加载客户端。

启动时不连接 MCP（避免 5-30s 阻塞），首次调用时才连接。
同时支持后台预热（启动后 5 秒在后台尝试连接）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LazyMCPClient:
    """懒加载 MCP 客户端 — 启动不阻塞，首次调用才连接。

    使用模式:
        lazy = LazyMCPClient()
        # 启动时注册后台预热
        asyncio.create_task(lazy.warmup(delay=5))
        # 业务代码中调用
        result = await lazy.call_tool("ListProjects", {"projectId": 123})
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._connecting = False
        self._connect_error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def connect_error(self) -> str | None:
        """兼容旧代码读取 connect_error。"""
        return self._connect_error

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def status(self):
        """兼容 app_state._official_mcp_client.status 的只读属性。"""
        if self._client:
            return self._client.status

        # 未连接时返回一个临时 status 对象
        class _Status:
            connected = False
            error = "lazy-init: not yet connected"
            tool_count = 0
            tools = []

            def to_dict(self) -> dict:
                return {
                    "enabled": True,
                    "connected": False,
                    "server": "alibabacloud-dataworks-mcp-server",
                    "version": "",
                    "tool_count": 0,
                    "tools": [],
                    "error": "lazy-init: not yet connected",
                }

        return _Status()

    async def connect(self) -> bool:
        """连接 MCP（线程安全，只连一次）。"""
        if self._client:
            return True
        async with self._lock:
            if self._client:
                return True
            if self._connecting:
                return False
            self._connecting = True

        try:
            from dataworks_agent.mcp.official_dataworks import OfficialDataWorksMCPClient

            client = OfficialDataWorksMCPClient()
            status = await client.connect()
            if status.connected:
                self._client = client
                logger.info("LazyMCP 连接成功 (tools=%d)", status.tool_count)
                return True
            else:
                self._connect_error = status.error or "MCP 连接失败"
                logger.warning("LazyMCP 连接失败: %s", self._connect_error)
                return False
        except Exception as e:
            self._connect_error = str(e)[:300]
            logger.warning("LazyMCP 连接异常: %s", e)
            return False
        finally:
            self._connecting = False

    async def warmup(self, delay: float = 5.0) -> None:
        """后台预热 — 启动后 delay 秒尝试连接，不阻塞主流程。"""
        await asyncio.sleep(delay)
        logger.info("LazyMCP 后台预热开始...")
        success = await self.connect()
        if success:
            logger.info("LazyMCP 后台预热成功")
        else:
            logger.info("LazyMCP 后台预热失败（将在首次调用时重试）")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """调用 MCP 工具 — 自动连接（如果尚未连接）。"""
        if not await self.connect():
            raise RuntimeError(f"MCP 未连接: {self._connect_error}")
        assert self._client is not None
        return await self._client.call_tool(name, arguments)

    async def list_tools(self) -> list[str]:
        """列出 MCP 工具。"""
        if not await self.connect():
            return []
        assert self._client is not None
        return await self._client.list_tools()

    async def close(self) -> None:
        """关闭 MCP 连接。"""
        if self._client:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("LazyMCP 关闭异常: %s", e)
            self._client = None
