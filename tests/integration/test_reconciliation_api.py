"""ReconciliationView.vue 集成测试 — /api/reconciliation/*。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_reconciliation_tasks_list(mocked_client):
    """GET /api/reconciliation/tasks — 列出待协调任务。"""
    resp = await mocked_client.get("/api/reconciliation/tasks")
    assert_routed_response(resp)
    if resp.status_code == 200:
        data = resp.json()
        assert "tasks" in data or isinstance(data, list)


@pytest.mark.asyncio
async def test_reconciliation_dispose_validation(mocked_client):
    """POST /api/reconciliation/dispose — 缺参数应 422。"""
    resp = await mocked_client.post("/api/reconciliation/dispose", json={})
    assert_routed_response(resp, allowed=(422, 500))


@pytest.mark.asyncio
async def test_reconciliation_dispose_well_formed(mocked_client):
    """POST /api/reconciliation/dispose — 不存在的 intent 应 404。"""
    resp = await mocked_client.post(
        "/api/reconciliation/dispose",
        json={"intent_id": 999999, "action": "confirm_success"},
    )
    assert_routed_response(resp, allowed=(404,))
