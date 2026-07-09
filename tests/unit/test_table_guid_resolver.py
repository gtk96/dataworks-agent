"""table_guid_resolver 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from dataworks_agent.governance.table_guid_resolver import resolve_table_guid


class TestResolveTableGuid:
    @pytest.mark.asyncio
    async def test_explicit_project(self):
        guid, project = await resolve_table_guid("dwd_a", "dataworks")
        assert guid == "odps.dataworks.dwd_a"
        assert project == "dataworks"

    @pytest.mark.asyncio
    async def test_search_prefers_prod_schema(self, monkeypatch):
        monkeypatch.setattr(
            "dataworks_agent.governance.table_guid_resolver.settings.dataworks_prod_schema",
            "giikin",
        )
        bff = AsyncMock()
        bff.search_tables = AsyncMock(
            return_value=[
                {
                    "table_name": "dwd_a",
                    "project": "dataworks",
                    "entity_guid": "odps.dataworks.dwd_a",
                },
                {"table_name": "dwd_a", "project": "giikin", "entity_guid": "odps.giikin.dwd_a"},
            ]
        )
        guid, project = await resolve_table_guid("dwd_a", bff=bff)
        assert guid == "odps.giikin.dwd_a"
        assert project == "giikin"

    @pytest.mark.asyncio
    async def test_fallback_default_project(self, monkeypatch):
        monkeypatch.setattr(
            "dataworks_agent.governance.table_guid_resolver.settings.dataworks_prod_schema",
            "giikin",
        )
        bff = AsyncMock()
        bff.search_tables = AsyncMock(return_value=[])
        guid, project = await resolve_table_guid("dwd_a", bff=bff)
        assert guid == "odps.giikin.dwd_a"
        assert project == "giikin"
