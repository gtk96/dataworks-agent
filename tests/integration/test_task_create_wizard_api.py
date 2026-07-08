"""TaskCreateWizard.vue 集成测试 — 5 步简化版向导。

注: 大部分端点与 ModelingWorkbench 共享,本文件重点测两者的差异点。
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_wizard_search_tables(mocked_client):
    """GET /api/workspace/search-tables — 第 1 步搜源表(与 ModelingWorkbench 相同)。"""
    resp = await mocked_client.get("/api/workspace/search-tables", params={"keyword": "ods_"})
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_wizard_preview(mocked_client):
    """POST /api/modeling/preview — 第 3 步预览 DDL(简化版)。"""
    resp = await mocked_client.post(
        "/api/modeling/preview",
        json={
            "source_table": "ods_hl_dataworks_holo__s_order_hour",
            "target_layer": "DWD",
            "domain": "ord",
            "entity": "ofc_s_order_simple",
            "update_method": "hour",
        },
    )
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_wizard_create_task_with_idempotency(mocked_client):
    """POST /api/modeling/tasks + X-Idempotency-Key 头 — 向导版特有。

    TaskCreateWizard 总是带 idempotencyKey(防止重复提交),
    IdempotencyMiddleware 应自动 register 响应里的 task_id。
    """
    headers = {"X-Idempotency-Key": "wizard-test-idem-" + str(__import__("time").time())}
    body = {
        "source_table": "ods_test",
        "target_layer": "DIM",
        "domain": "ord",
        "entity": "ofc_simple",
        "update_method": "day",
        "dry_run": True,
    }
    # 第一次
    r1 = await mocked_client.post("/api/modeling/tasks", json=body, headers=headers)
    assert_routed_response(r1)
    # 第二次: 命中 idempotency 中间件(路由不再调)
    r2 = await mocked_client.post("/api/modeling/tasks", json=body, headers=headers)
    # 两次都至少应能进路由(middleware 不抛 500)
    assert_routed_response(r2)
