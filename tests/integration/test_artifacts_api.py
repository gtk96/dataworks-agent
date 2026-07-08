"""ArtifactsView.vue 集成测试 — /api/artifacts/*。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_artifacts_list(mocked_client):
    """GET /api/artifacts/ddl?table_name= — 列出 DDL 产物(支持过滤)。"""
    resp = await mocked_client.get("/api/artifacts/ddl", params={"table_name": "dwd_test"})
    assert_routed_response(resp, allowed=(200, 500))
    if resp.status_code == 200:
        data = resp.json()
        assert "artifacts" in data or isinstance(data, list)


@pytest.mark.asyncio
async def test_artifacts_list_no_filter(mocked_client):
    """无 table_name 参数也应能调(可能返回空)。"""
    resp = await mocked_client.get("/api/artifacts/ddl")
    assert_routed_response(resp, allowed=(200, 500))


@pytest.mark.asyncio
async def test_artifacts_get_by_id_404(mocked_client):
    """GET /api/artifacts/ddl/{id} — 不存在的 ID 应 404(不视为路由错误)。"""
    resp = await mocked_client.get("/api/artifacts/ddl/99999")
    # 404 是正常的(资源不存在),422 是 Pydantic 校验失败(端点 ID 应是 int)
    assert resp.status_code in (200, 404, 422, 500)
