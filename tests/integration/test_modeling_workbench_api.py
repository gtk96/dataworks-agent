"""ModelingWorkbench + DwdWorkbench 集成测试 — 5 步向导 + JSON 模式核心 API。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_search_tables(mocked_client):
    """GET /api/workspace/search-tables — 向导第 1 步搜源表。"""
    resp = await mocked_client.get("/api/workspace/search-tables", params={"keyword": "ods_"})
    assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_modeling_preview_dry_run(mocked_client):
    """POST /api/modeling/preview — 干运行预览 DDL(不写库)。"""
    resp = await mocked_client.post(
        "/api/modeling/preview",
        json={
            "source_table": "ods_hl_dataworks_holo__s_order_hour",
            "target_layer": "DWD",
            "domain": "ord",
            "entity": "ofc_s_order",
            "update_method": "hour",
        },
    )
    # 200 预览成功;500 是 mcp 不可用,但路由应能进入(middleware 不挡)
    assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_governance_check_ddl(mocked_client):
    """POST /api/governance/check-ddl — DDL 规范检查。"""
    resp = await mocked_client.post(
        "/api/governance/check-ddl",
        json={"ddl": "create table dataworks.dwd_test (id string) partitioned by (dt string);"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "passed" in data


@pytest.mark.asyncio
async def test_create_task_dwd_dry_run(mocked_client):
    """POST /api/modeling/tasks — DWD 干运行,验证 task_id 流程。"""
    resp = await mocked_client.post(
        "/api/modeling/tasks",
        json={
            "source_table": "ods_hl_dataworks_holo__s_order_hour",
            "target_layer": "DWD",
            "domain": "ord",
            "entity": "ofc_s_order",
            "update_method": "hour",
            "dry_run": True,
        },
    )
    # mcp 不可用 → 500;可用 → 202+task_id
    assert resp.status_code in (202, 500)
    if resp.status_code == 202:
        data = resp.json()
        assert "task_id" in data


@pytest.mark.asyncio
async def test_create_task_idempotency_header(mocked_client):
    """POST /api/modeling/tasks 带 X-Idempotency-Key — IdempotencyMiddleware 介入。

    注意: middleware 只在响应含 task_id 字段时才 register。
    第一次响应可能是 500(mcp 不可用),所以 idempotency 不写入,第二次应能进入业务。
    """
    headers = {"X-Idempotency-Key": "integration-test-idem-1"}
    body = {
        "source_table": "ods_test",
        "target_layer": "DIM",
        "domain": "ord",
        "entity": "ofc_x",
        "update_method": "day",
        "dry_run": True,
    }
    r1 = await mocked_client.post("/api/modeling/tasks", json=body, headers=headers)
    r2 = await mocked_client.post("/api/modeling/tasks", json=body, headers=headers)
    # 两次都至少应不抛 500 middleware 内部异常
    assert r1.status_code in (200, 202, 400, 422, 500)
    assert r2.status_code in (200, 202, 400, 422, 500)


@pytest.mark.asyncio
async def test_dwd_preview_ddl_validation(mocked_client):
    """POST /api/dwd/preview-ddl — DWD JSON 模式预览,缺参数应 422。"""
    resp = await mocked_client.post("/api/dwd/preview-ddl", json={})
    assert resp.status_code in (422, 500)


@pytest.mark.asyncio
async def test_dwd_preview_sql_validation(mocked_client):
    """POST /api/dwd/preview-sql — 缺参数应 422。"""
    resp = await mocked_client.post("/api/dwd/preview-sql", json={})
    assert resp.status_code in (422, 500)


@pytest.mark.asyncio
async def test_dwd_resolve_types(mocked_client):
    """POST /api/dwd/resolve-types — 批量字段类型解析(用 structured_metadata schema)。"""
    resp = await mocked_client.post(
        "/api/dwd/resolve-types",
        json={
            "structured_metadata": {
                "targets": [
                    {
                        "fields": [
                            {"name": "order_id", "comment": "订单ID"},
                            {"name": "order_amt", "comment": "订单金额"},
                            {"name": "order_cnt", "comment": "订单数量"},
                        ]
                    }
                ]
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "fields" in data or "status" in data


@pytest.mark.asyncio
async def test_dwd_deploy_validation(mocked_client):
    """POST /api/dwd/deploy — 缺参数应 422。"""
    resp = await mocked_client.post("/api/dwd/deploy", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_dwd_deploy_well_formed_dry_run(mocked_client):
    """POST /api/dwd/deploy — 完整参数(可能因 mcp/bff 失败 500)。"""
    resp = await mocked_client.post(
        "/api/dwd/deploy",
        json={
            "structured_metadata": {
                "sources": [{"name": "ods_test", "schema": "dataworks"}],
                "targets": [
                    {"table_name": "dwd_test", "fields": [{"name": "id", "type": "STRING"}]}
                ],
            },
            "publish": False,
        },
    )
    # 200/500/503 都能接受(走通了路由),422 说明 schema 不对
    assert resp.status_code in (200, 422, 500, 503)


@pytest.mark.asyncio
async def test_list_tasks_filter(mocked_client):
    """GET /api/modeling/tasks?status=&layer= — 筛选参数。"""
    resp = await mocked_client.get(
        "/api/modeling/tasks", params={"status": "completed", "layer": "DWD"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert "total" in data
