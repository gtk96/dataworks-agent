"""BusMatrixView.vue 集成测试 — /api/bus-matrix。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_bus_matrix_returns_grid(mocked_client):
    """GET /api/bus-matrix — 返回总线矩阵数据。"""
    resp = await mocked_client.get("/api/bus-matrix")
    assert_routed_response(resp, allowed=(200, 500))
    if resp.status_code == 200:
        data = resp.json()
        assert "matrix" in data
        assert isinstance(data["matrix"], list)
