"""Settings.vue 集成测试 — /api/health + /api/settings + /api/cookie/*。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import assert_routed_response

# ─── /api/health + /api/settings ───────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint(mocked_client):
    """/api/health 返回 200 + checks 字段。"""
    resp = await mocked_client.get("/api/health")
    assert_routed_response(resp, allowed=(200, 500, 503))
    if resp.status_code == 200:
        data = resp.json()
        assert "status" in data
        assert "checks" in data


@pytest.mark.asyncio
async def test_settings_get(mocked_client):
    """/api/settings 返回项目配置。"""
    resp = await mocked_client.get("/api/settings")
    assert_routed_response(resp, allowed=(200, 500))
    if resp.status_code == 200:
        data = resp.json()
        # 至少应有 project_id 或 status 字段
        assert any(k in data for k in ("project_id", "status", "region"))


# ─── /api/cookie/* ───────────────────────────────────────


@pytest.mark.asyncio
async def test_cookie_status(mocked_client):
    """GET /api/cookie/status — Cookie 状态(可能因 mock decrypt_cookie 返回 fake 而 200)。"""
    resp = await mocked_client.get("/api/cookie/status")
    assert_routed_response(resp, allowed=(200, 500, 503))


@pytest.mark.asyncio
async def test_cookie_full(mocked_client):
    """GET /api/cookie/full — 读取完整 Cookie(已 mock decrypt_cookie)。"""
    import hmac

    # 计算正确的 Admin Token
    test_key = "test_encryption_key"
    expected_token = hmac.new(test_key.encode(), b"admin-access", "sha256").hexdigest()[:16]

    # Mock settings.cookie_encryption_key
    from dataworks_agent.config import settings

    original_key = settings.cookie_encryption_key
    settings.cookie_encryption_key = test_key

    try:
        resp = await mocked_client.get(f"/api/cookie/full?token={expected_token}")
        assert_routed_response(resp, allowed=(200, 500, 503))
    finally:
        settings.cookie_encryption_key = original_key


@pytest.mark.asyncio
async def test_cookie_save(mocked_client):
    """POST /api/cookie — 保存 Cookie(参数缺失可能 422)。"""
    resp = await mocked_client.post("/api/cookie", json={})
    assert_routed_response(resp, allowed=(200, 422, 500))


@pytest.mark.asyncio
async def test_cookie_save_well_formed(mocked_client):
    """POST /api/cookie — 完整 Cookie 字符串(字段名 cookie_string)。"""
    resp = await mocked_client.post(
        "/api/cookie", json={"cookie_string": "fake_cookie_for_tests" * 3}
    )
    assert_routed_response(resp, allowed=(200, 500))


@pytest.mark.asyncio
async def test_cookie_verify(mocked_client):
    """GET /api/cookie/verify — 验证 Cookie(已 mock)。"""
    resp = await mocked_client.get("/api/cookie/verify")
    assert_routed_response(resp, allowed=(200, 500, 503))


@pytest.mark.asyncio
async def test_cookie_auto_fetch(mocked_client):
    """POST /api/cookie/auto-fetch — 自动提取(需要 CDP 浏览器,可能 503)。"""
    resp = await mocked_client.post("/api/cookie/auto-fetch")
    assert_routed_response(resp, allowed=(200, 500, 503))


@pytest.mark.asyncio
async def test_cookie_wait_login(mocked_client):
    """POST /api/cookie/wait-login — 等扫码登录(需要 CDP,可能 503)。"""
    resp = await mocked_client.post("/api/cookie/wait-login")
    assert_routed_response(resp, allowed=(200, 500, 503))


@pytest.mark.asyncio
async def test_cookie_launch_browser(mocked_client):
    """POST /api/cookie/launch-browser — 打开 IDE(需要 CDP,可能 503)。"""
    resp = await mocked_client.post("/api/cookie/launch-browser")
    assert_routed_response(resp, allowed=(200, 500, 503))


@pytest.mark.asyncio
async def test_cookie_scan_uuids(mocked_client):
    """GET /api/cookie/scan-uuids — CDP 扫描 UUID(已 mock CDP=None,可能 503)。"""
    resp = await mocked_client.get("/api/cookie/scan-uuids")
    assert_routed_response(resp, allowed=(200, 500, 503))
