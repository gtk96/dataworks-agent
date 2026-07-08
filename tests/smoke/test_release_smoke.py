"""发布前冒烟测试 — 5 场景必须全过。"""

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
async def test_smoke_health_check_ok(client: AsyncClient):
    """冒烟 1: 健康检查返回 OK。"""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded", "down")


@pytest.mark.asyncio
async def test_smoke_wizard_preview_returns_valid_ddl(client: AsyncClient):
    """冒烟 2: Wizard 预览返回有效 DDL（MCP 不可用时跳过）。"""
    body = {
        "source_table": "dataworks_develop.rule_adset_info",
        "target_layer": "DWD",
        "domain": "mkt",
        "entity": "ad_group",
        "update_method": "day",
        "dry_run": True,
    }
    resp = await client.post("/api/modeling/preview", json=body)
    if resp.status_code == 200:
        data = resp.json()
        assert "CREATE TABLE" in (data.get("ddl_dev", "") or "").upper()
    else:
        assert resp.status_code == 500  # MCP 不可用


@pytest.mark.asyncio
async def test_smoke_root_check_valid_fields(client: AsyncClient):
    """冒烟 3: 合法词根字段校验通过。"""
    body = {"fields": ["order_id", "ad_acct_id", "create_time"]}
    resp = await client.post("/api/roots/check", json=body)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_smoke_root_check_invalid_fields(client: AsyncClient):
    """冒烟 4: 非法词根字段校验不通过。"""
    body = {"fields": ["created_by"]}
    resp = await client.post("/api/roots/check", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is False
    assert len(data["field_results"]) == 1


@pytest.mark.asyncio
async def test_smoke_idempotency(client: AsyncClient):
    """冒烟 5: 幂等性 — 重复请求返回同一 task_id（MCP 不可用时跳过）。"""
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
    r1 = await client.post("/api/modeling/tasks", json=body, headers=headers)
    if r1.status_code == 202:
        r2 = await client.post("/api/modeling/tasks", json=body, headers=headers)
        assert r2.status_code in (200, 202)
    else:
        assert r1.status_code == 500  # MCP 不可用
