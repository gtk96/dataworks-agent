"""Cookie 后台刷新 — 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dataworks_agent.cookie.background_refresh import (
    run_cookie_background_refresh_once,
    touch_cookie_poll,
)
from dataworks_agent.state import app_state


@pytest.fixture(autouse=True)
def reset_poll():
    previous_mcp_pool = app_state.mcp_pool
    previous_cookie_health = app_state.cookie_health
    app_state.cookie_bg_poll = {}
    yield
    app_state.cookie_bg_poll = {}
    app_state.mcp_pool = previous_mcp_pool
    app_state.cookie_health = previous_cookie_health


@pytest.mark.asyncio
async def test_touch_cookie_poll_sets_next_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.settings.auto_login_enabled",
        True,
    )
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.settings.cdp_url",
        "http://localhost:9222",
    )
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.settings.cookie_refresh_poll_seconds",
        600,
    )
    touch_cookie_poll(action="valid", detail="ok")
    assert app_state.cookie_bg_poll["last_action"] == "valid"
    assert app_state.cookie_bg_poll["next_poll_ts"] > 0


@pytest.mark.asyncio
async def test_run_once_skips_when_cookie_valid(monkeypatch):
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.settings.cdp_url",
        "http://localhost:9222",
    )
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.decrypt_cookie",
        lambda: "session=abc",
    )
    with (
        patch(
            "dataworks_agent.cookie.background_refresh.verify_cookie_access",
            new=AsyncMock(return_value=(True, "", "testuser")),
        ),
        patch(
            "dataworks_agent.cookie.background_refresh.cdp_extract_and_apply",
            new=AsyncMock(),
        ) as mock_extract,
    ):
        outcome = await run_cookie_background_refresh_once()
    assert outcome["status"] == "valid"
    mock_extract.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_extracts_when_invalid(monkeypatch):
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.settings.cdp_url",
        "http://localhost:9222",
    )
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.decrypt_cookie",
        lambda: "bad=1",
    )
    with (
        patch(
            "dataworks_agent.cookie.background_refresh.verify_cookie_access",
            new=AsyncMock(side_effect=[(False, "expired", ""), (True, "", "user1")]),
        ),
        patch(
            "dataworks_agent.cookie.background_refresh.cdp_extract_and_apply",
            new=AsyncMock(return_value={"status": "success", "detail": "100 字符"}),
        ),
        patch(
            "dataworks_agent.cookie.health.cookie_health_monitor.check",
            new=AsyncMock(),
        ),
    ):
        outcome = await run_cookie_background_refresh_once()
    assert outcome["status"] == "refreshed"
    assert app_state.cookie_bg_poll["last_action"] == "refreshed"


@pytest.mark.asyncio
async def test_valid_bff_cookie_with_mcp_error_is_degraded_not_expired(monkeypatch):
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.settings.cdp_url",
        "http://localhost:9222",
    )
    monkeypatch.setattr(
        "dataworks_agent.cookie.background_refresh.decrypt_cookie",
        lambda: "session=abc",
    )
    monkeypatch.setattr(app_state, "mcp_pool", object())
    app_state.cookie_health = "expired"
    with (
        patch(
            "dataworks_agent.cookie.background_refresh.verify_cookie_access",
            new=AsyncMock(return_value=(True, "MCP 401 Unauthorized", "testuser")),
        ),
        patch(
            "dataworks_agent.cookie.health.cookie_health_monitor.check",
            new=AsyncMock(),
        ) as health_check,
        patch(
            "dataworks_agent.cookie.background_refresh.cdp_extract_and_apply",
            new=AsyncMock(),
        ) as mock_extract,
    ):
        outcome = await run_cookie_background_refresh_once()

    assert outcome["status"] == "valid"
    assert app_state.cookie_health == "degraded"
    health_check.assert_not_awaited()
    mock_extract.assert_not_awaited()
