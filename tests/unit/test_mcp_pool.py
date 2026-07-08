"""MCP 连接池 — 单元测试。

仅测纯函数 _parse_sse_response + 未连接时 call_tool 抛错,不连真实 MCP server。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from dataworks_agent.mcp.pool import MCPClientPool


def test_parse_sse_standard_format():
    """标准 SSE: event: message\\ndata: {...}\\n\\n。"""
    raw = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"value":42}}\n\n'
    parsed = MCPClientPool._parse_sse_response(raw)
    assert parsed == {"jsonrpc": "2.0", "id": 1, "result": {"value": 42}}


def test_parse_sse_data_only():
    """只有 data 行,无 event 行。"""
    raw = 'data: {"foo": "bar"}\n\n'
    parsed = MCPClientPool._parse_sse_response(raw)
    assert parsed == {"foo": "bar"}


def test_parse_sse_multiple_data_lines_takes_first_valid():
    raw = 'data: not-valid-json\ndata: {"valid": true}\ndata: {"ignored": true}\n'
    parsed = MCPClientPool._parse_sse_response(raw)
    assert parsed == {"valid": True}


def test_parse_sse_falls_back_to_plain_json():
    """SSE 解析失败时,尝试整体 JSON。"""
    raw = json.dumps({"jsonrpc": "2.0", "result": "ok"})
    parsed = MCPClientPool._parse_sse_response(raw)
    assert parsed == {"jsonrpc": "2.0", "result": "ok"}


def test_parse_sse_empty_returns_none():
    assert MCPClientPool._parse_sse_response("") is None
    assert MCPClientPool._parse_sse_response("\n\n") is None
    assert MCPClientPool._parse_sse_response("not json at all") is None


def test_parse_sse_handles_indented_data():
    raw = 'data:    {"a": 1}\n'
    parsed = MCPClientPool._parse_sse_response(raw)
    assert parsed == {"a": 1}


def test_call_tool_raises_when_not_connected():
    """未调用 connect() 就 call_tool 应抛 RuntimeError。"""
    pool = MCPClientPool()
    with pytest.raises(RuntimeError, match="MCP 客户端未初始化"):
        asyncio.run(pool.call_tool("foo", {}))
