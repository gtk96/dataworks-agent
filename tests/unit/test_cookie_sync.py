"""Cookie 更新仅刷新 BFF 内存态。"""

from __future__ import annotations

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
async def test_apply_cookie_update_only_invalidates_bff():
    bff = DataWorksClient()
    bff._cookie = "stale"
    app_state._bff_client = bff

    await apply_cookie_update("new_cookie=value")

    assert bff._cookie == ""
    assert not hasattr(app_state, "mcp_pool")
