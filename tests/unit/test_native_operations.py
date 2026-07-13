"""原生客户端兼容门面不依赖外部 data-mcp。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.mcp import operations
from dataworks_agent.state import app_state


@pytest.fixture(autouse=True)
def restore_clients():
    old_mc = app_state._maxcompute_client
    old_bff = getattr(app_state, "_bff_client", None)
    old_openapi = app_state._openapi_client
    yield
    app_state._maxcompute_client = old_mc
    app_state._bff_client = old_bff
    app_state._openapi_client = old_openapi


@pytest.mark.asyncio
async def test_execute_ddl_uses_maxcompute():
    mc = MagicMock()
    mc.execute_ddl = AsyncMock(
        return_value=SimpleNamespace(success=True, instance_id="i-1", error=None)
    )
    app_state._maxcompute_client = mc

    result = await operations.execute_ddl("CREATE TABLE t (id BIGINT)")

    assert result["success"] is True
    mc.execute_ddl.assert_awaited_once_with("CREATE TABLE t (id BIGINT)")


@pytest.mark.asyncio
async def test_get_table_ddl_uses_project_and_table():
    mc = MagicMock()
    mc.get_table_ddl = AsyncMock(return_value="CREATE TABLE t (id BIGINT)")
    app_state._maxcompute_client = mc

    ddl = await operations.get_table_ddl("odps.dev_project.t")

    assert ddl.startswith("CREATE TABLE")
    mc.get_table_ddl.assert_awaited_once_with("t", project="dev_project")


@pytest.mark.asyncio
async def test_submit_query_returns_dict_rows():
    mc = MagicMock()
    mc.submit_query = AsyncMock(return_value="instance")
    mc.wait_and_fetch = AsyncMock(return_value=SimpleNamespace(columns=["cnt"], rows=[[3]]))
    app_state._maxcompute_client = mc

    assert await operations.submit_query("SELECT 3 AS cnt") == [{"cnt": 3}]


@pytest.mark.asyncio
async def test_list_tables_uses_bff_and_filters_project():
    bff = MagicMock()
    bff.search_tables = AsyncMock(
        return_value=[
            {"project": "prod", "table_name": "dwd_order"},
            {"project": "other", "table_name": "dwd_order"},
        ]
    )
    app_state._bff_client = bff

    rows = await operations.list_tables("prod", "dwd_order")

    assert rows == [{"project": "prod", "table_name": "dwd_order"}]
    bff.search_tables.assert_awaited_once_with("dwd_order")
