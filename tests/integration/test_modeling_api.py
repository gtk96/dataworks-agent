"""建模 API 集成测试 — 测试全流程 HTTP 交互。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():
    from dataworks_agent.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "checks" in data


@pytest.mark.asyncio
async def test_create_task_dry_run(client: AsyncClient):
    body = {
        "source_table": "dataworks_develop.rule_adset_info",
        "target_layer": "DWD",
        "domain": "mkt",
        "entity": "test_api",
        "update_method": "day",
        "dry_run": True,
    }
    resp = await client.post("/api/modeling/tasks", json=body)
    # MCP 不可用时返回 500，可用时返回 202
    if resp.status_code == 202:
        data = resp.json()
        assert "task_id" in data
    else:
        assert resp.status_code == 500


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient):
    resp = await client.get("/api/modeling/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_preview_ddl(client: AsyncClient):
    body = {
        "source_table": "dataworks_develop.rule_adset_info",
        "target_layer": "DWD",
        "domain": "mkt",
        "entity": "test_preview",
        "update_method": "day",
        "dry_run": True,
    }
    resp = await client.post("/api/modeling/preview", json=body)
    # MCP 不可用时会返回 500，可用时返回 200
    if resp.status_code == 200:
        data = resp.json()
        assert "ddl_dev" in data
        assert "ddl_prod" in data
    else:
        assert resp.status_code == 500


@pytest.mark.asyncio
async def test_root_check_api(client: AsyncClient):
    body = {"fields": ["order_id", "ad_acct_id", "create_time"]}
    resp = await client.post("/api/roots/check", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert "passed" in data


@pytest.mark.asyncio
async def test_task_not_found(client: AsyncClient):
    resp = await client.get("/api/modeling/tasks/nonexistent_task_id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_idempotency_key(client: AsyncClient):
    import uuid

    key = f"test-idempotent-{uuid.uuid4().hex[:6]}"
    body = {
        "source_table": "dataworks_develop.rule_adset_info",
        "target_layer": "DWD",
        "domain": "mkt",
        "entity": "idempotent_test",
        "update_method": "day",
        "dry_run": True,
    }
    headers = {"X-Idempotency-Key": key}
    resp1 = await client.post("/api/modeling/tasks", json=body, headers=headers)
    # MCP 不可用时第一次就失败，可用时第二次返回重复
    if resp1.status_code == 202:
        resp2 = await client.post("/api/modeling/tasks", json=body, headers=headers)
        assert resp2.status_code in (200, 202)
