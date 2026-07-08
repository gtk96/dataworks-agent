"""MCPClientPool — data-mcp Streamable HTTP 连接池。

MCP Streamable HTTP 协议要求:
1. Accept 头必须包含 application/json 和 text/event-stream
2. 服务端返回 mcp-session-id 头，后续请求必须携带
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MCPClientPool:
    """MCP (Model Context Protocol) Streamable HTTP 客户端。"""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._mcp_url: str = ""
        self._session_id: str = ""
        self._headers: dict[str, str] = {}

    async def connect(self) -> None:
        """从 mcp.json 加载配置并建立 MCP 会话。"""
        import json as _json
        from pathlib import Path

        mcp_config_path = Path(__file__).parent.parent.parent / "mcp.json"
        if not mcp_config_path.exists():
            logger.warning("mcp.json 不存在，MCP 连接池未配置")
            return

        with open(mcp_config_path, encoding="utf-8") as f:
            config = _json.load(f)

        servers = config.get("mcpServers", {})
        data_mcp = servers.get("data-mcp", {})

        self._mcp_url = data_mcp.get("url", "").rstrip("/")

        # MCP Streamable HTTP 要求的 Accept 头
        self._headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **{k: v for k, v in data_mcp.get("headers", {}).items()},
        }

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            follow_redirects=False,
        )

        # 发送初始化请求获取 session ID
        try:
            init_payload = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "dataworks-agent", "version": "0.1.0"},
                },
                "id": 1,
            }
            resp = await self._client.post(
                self._mcp_url,
                json=init_payload,
                headers=self._headers,
            )

            # 捕获 session ID
            sid = resp.headers.get("mcp-session-id", "")
            if sid:
                self._session_id = sid
                self._headers["Mcp-Session-Id"] = sid

            if resp.status_code >= 400:
                logger.warning("MCP initialize 返回 %d: %s", resp.status_code, resp.text[:200])
            else:
                data = self._parse_sse_response(resp.text)
                if data and "result" in data:
                    logger.info(
                        "MCP 会话已建立: %s (session: %s...)",
                        data["result"].get("serverInfo", {}).get("name", "unknown"),
                        sid[:16] if sid else "none",
                    )

        except Exception as e:
            logger.warning("MCP 初始化请求失败: %s", e)

        logger.info("MCP 连接池已连接到 %s", self._mcp_url)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """调用 MCP 工具 (JSON-RPC)。"""
        if not self._client:
            raise RuntimeError("MCP 客户端未初始化，请先调用 connect()")

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": 1,
        }

        resp = await self._client.post(
            self._mcp_url,
            json=payload,
            headers=self._headers,
        )

        if resp.status_code >= 400:
            raise RuntimeError(
                f"MCP 调用 {tool_name} 失败: HTTP {resp.status_code} — {resp.text[:300]}"
            )

        # MCP Streamable HTTP 返回 SSE 格式: "event: message\ndata: {...}\n\n"
        raw = resp.text
        data = self._parse_sse_response(raw)

        if not data:
            raise RuntimeError(f"MCP 调用 {tool_name} 返回空响应: {raw[:200]}")

        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"MCP 调用失败 {tool_name}: {err.get('message', err)}")

        result = data.get("result", {})
        content = result.get("content", [])

        # 提取文本内容
        if content and isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text
        return result

    @staticmethod
    def _parse_sse_response(raw: str) -> dict | None:
        """解析 MCP Streamable HTTP SSE 响应。

        格式: "event: message\\ndata: {...}\\n\\n"
        """
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data_str = line[5:].strip()
                try:
                    return json.loads(data_str)
                except json.JSONDecodeError:
                    continue
        # 可能是纯 JSON
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
