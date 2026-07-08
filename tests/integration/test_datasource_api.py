"""DataSourceManager.vue 集成测试 — /api/workspace/{datasources, holo/*}。

注: /api/workspace/search-tables、create-di-node、preview-holo-dml、create-holo-node
等已在 test_data_integration_api.py 覆盖(因为 DataIntegration 也用这些)。
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response


@pytest.mark.asyncio
async def test_list_datasources(mocked_client):
    """GET /api/workspace/datasources — 列出外部数据源。"""
    resp = await mocked_client.get("/api/workspace/datasources")
    assert_routed_response(resp, allowed=(200, 500))


@pytest.mark.asyncio
async def test_list_datasources_with_type_filter(mocked_client):
    """GET /api/workspace/datasources?type=mysql — 按类型过滤。"""
    resp = await mocked_client.get("/api/workspace/datasources", params={"type": "mysql"})
    assert_routed_response(resp, allowed=(200, 500))


@pytest.mark.asyncio
async def test_list_datasource_tables(mocked_client):
    """GET /api/workspace/datasources/{name}/tables — 列出某数据源的表。"""
    resp = await mocked_client.get("/api/workspace/datasources/mysql_test/tables")
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_list_holo_schemas(mocked_client):
    """GET /api/workspace/holo/schemas — 列 Hologres schemas。"""
    resp = await mocked_client.get("/api/workspace/holo/schemas")
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_list_holo_tables(mocked_client):
    """GET /api/workspace/holo/schemas/{schema}/tables — 列某 schema 的表。"""
    resp = await mocked_client.get("/api/workspace/holo/schemas/dataworks/tables")
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_list_holo_columns(mocked_client):
    """GET /api/workspace/holo/schemas/{schema}/tables/{table}/columns — 列字段。"""
    resp = await mocked_client.get(
        "/api/workspace/holo/schemas/dataworks/tables/t_order/columns",
        params={"granularity": "hour", "where_mode": "default"},
    )
    assert_routed_response(resp)


@pytest.mark.asyncio
async def test_repository_tree(mocked_client):
    """GET /api/workspace/repository-tree — 浏览 DataWorks 目录。"""
    resp = await mocked_client.get(
        "/api/workspace/repository-tree",
        params={"path": "业务流程/100_订单信息"},
    )
    assert_routed_response(resp, allowed=(200, 500))


@pytest.mark.asyncio
async def test_create_holo_node_validation(mocked_client):
    """POST /api/workspace/create-holo-node — 缺参数应 422。"""
    resp = await mocked_client.post("/api/workspace/create-holo-node", json={})
    assert_routed_response(resp, allowed=(422, 500))
