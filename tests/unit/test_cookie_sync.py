"""Cookie 同步 — 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.api_clients.bff_client import DataWorksClient
from dataworks_agent.cookie.sync import apply_cookie_update, invalidate_bff_session
from dataworks_agent.state import app_state


def test_invalidate_bff_session_clears_cookie_cache():
    bff = DataWorksClient()
    bff._cookie = "stale"
    bff._datasource_cache = [{"name": "x"}]
    invalidate_bff_session(bff)
    assert bff._cookie == ""
    assert bff._datasource_cache is None


@pytest.mark.asyncio
async def test_apply_cookie_update_syncs_mcp(monkeypatch):
    bff = DataWorksClient()
    app_state._bff_client = bff

    mcp = MagicMock()
    mcp.set_cookie_header = MagicMock()
    mcp.call_tool = AsyncMock(return_value={"success": True})
    app_state._mcp_pool = mcp

    await apply_cookie_update("new_cookie=value")
    assert bff._cookie == ""
    mcp.set_cookie_header.assert_called_once_with("new_cookie=value")
    mcp.call_tool.assert_awaited_once()
