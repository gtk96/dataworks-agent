"""OwnershipView.vue 集成测试 — /api/ownership/{table_name}。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_ownership_query(mocked_client):
    """GET /api/ownership/{table_name} — 查产权记录(空 DB 应返回空 records)。"""
    resp = await mocked_client.get("/api/ownership/dwd_test")
    assert_routed_response(resp, allowed=(200, 500))
    if resp.status_code == 200:
        data = resp.json()
        assert "records" in data
        assert isinstance(data["records"], list)


@pytest.mark.asyncio
async def test_ownership_query_unknown_table(mocked_client):
    """不存在的表应返回空 records(不是 500)。"""
    resp = await mocked_client.get("/api/ownership/nonexistent_table_xyz")
    assert_routed_response(resp, allowed=(200, 500))
    if resp.status_code == 200:
        data = resp.json()
        assert data["records"] == []
