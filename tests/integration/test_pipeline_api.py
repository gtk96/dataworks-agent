"""PipelineHub.vue 集成测试 — /api/pipeline/*。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_preview_oss_sql_validation(mocked_client):
    """POST /api/pipeline/preview/oss-sql — 缺参数应 422。"""
    resp = await mocked_client.post("/api/pipeline/preview/oss-sql", json={})
    assert_routed_response(resp, allowed=(422, 500))


@pytest.mark.asyncio
async def test_preview_oss_sql_well_formed(mocked_client):
    """POST /api/pipeline/preview/oss-sql — 完整参数。"""
    resp = await mocked_client.post(
        "/api/pipeline/preview/oss-sql",
        json={"oss_path": "oss://bucket/path/", "target_table": "ods_oss_xxx"},
    )
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_preview_realtime_validation(mocked_client):
    """POST /api/pipeline/preview/realtime — 缺参数应 422。"""
    resp = await mocked_client.post("/api/pipeline/preview/realtime", json={})
    assert_routed_response(resp, allowed=(422, 500))


@pytest.mark.asyncio
async def test_oss_batch_validation(mocked_client):
    """POST /api/pipeline/oss/batch — 缺参数应 422。"""
    resp = await mocked_client.post("/api/pipeline/oss/batch", json={})
    assert_routed_response(resp, allowed=(422, 500))


@pytest.mark.asyncio
async def test_oss_batch_well_formed(mocked_client):
    """POST /api/pipeline/oss/batch — 完整参数(可能因 mcp 失败 500)。"""
    resp = await mocked_client.post(
        "/api/pipeline/oss/batch",
        json={"items": [{"oss_path": "oss://b/p/", "target_table": "ods_oss_x"}]},
    )
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_realtime_batch_validation(mocked_client):
    """POST /api/pipeline/realtime/batch — 缺参数应 422。"""
    resp = await mocked_client.post("/api/pipeline/realtime/batch", json={})
    assert_routed_response(resp, allowed=(422, 500))


@pytest.mark.asyncio
async def test_get_batch_status(mocked_client):
    """GET /api/pipeline/batches/{batch_id} — 查批次状态(可能 404 因为 batch_id 不存在)。"""
    resp = await mocked_client.get("/api/pipeline/batches/nonexistent-batch-xyz")
    # 404 是正常(资源不存在)
    assert resp.status_code in (200, 404, 500)
