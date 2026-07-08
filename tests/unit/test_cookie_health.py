"""Cookie 健康监测 — 单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.cookie.health import (
    CRITICAL_THRESHOLD,
    WARN_THRESHOLD,
    CookieHealthMonitor,
)
from dataworks_agent.state import app_state


@pytest.fixture(autouse=True)
def reset_state():
    app_state.cookie_health = "unknown"
    yield
    app_state.cookie_health = "unknown"


def _make_mcp(user_payload: dict | str):
    """Mock mcp_pool.call_tool 返回值。"""
    mcp = MagicMock()
    mcp.call_tool = AsyncMock(return_value=user_payload)
    return mcp


@pytest.mark.asyncio
async def test_check_healthy_when_expires_in_large():
    mcp = _make_mcp({"expires_in": 7200})
    monitor = CookieHealthMonitor()
    result = await monitor.check(mcp)
    assert result["status"] == "healthy"
    assert result["expires_in"] == 7200
    assert app_state.cookie_health == "healthy"


@pytest.mark.asyncio
async def test_check_warning_when_expires_in_moderate():
    mcp = _make_mcp({"expires_in": WARN_THRESHOLD - 100})  # 1h 之内
    monitor = CookieHealthMonitor()
    result = await monitor.check(mcp)
    assert result["status"] == "warning"
    assert app_state.cookie_health == "warning"


@pytest.mark.asyncio
async def test_check_critical_when_expires_in_low():
    mcp = _make_mcp({"expires_in": CRITICAL_THRESHOLD - 10})  # 10min 之内
    monitor = CookieHealthMonitor()
    result = await monitor.check(mcp)
    assert result["status"] == "critical"
    assert app_state.cookie_health == "critical"


@pytest.mark.asyncio
async def test_check_critical_does_not_cross_tenant_clear_queues():
    """critical 状态下不应跨用户清理队列（全局信号）。

    历史行为：_suspend_waiting_tasks(client_ip=None) 会清空 app_state.task_queues
    全部条目。这意味着一旦某用户 cookie 过期会 kill 其他用户的 pending 任务。
    修正后：全局 critical 信号只记 WARN，由人工或 Publish_Gate 处置，不自动清队列。
    """
    mcp = _make_mcp({"expires_in": 60})
    monitor = CookieHealthMonitor()

    # 填一个别人（非触发方）的 fake task queue
    import asyncio

    q = asyncio.Queue()
    await q.put("job-1")
    await q.put("job-2")
    app_state.task_queues["127.0.0.1"] = q

    await monitor.check(mcp)
    # 检查触发方 IP 未知，所以别人的 queue 不该被清
    assert not q.empty(), "critical 信号不应自动清空队列（跨租户数据风险 —— 由人工或审批流程处置）"
    assert app_state.cookie_health == "critical"

    # cleanup
    app_state.task_queues.pop("127.0.0.1", None)


@pytest.mark.asyncio
async def test_check_expired_when_call_raises():
    mcp = MagicMock()
    mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection refused"))
    monitor = CookieHealthMonitor()
    result = await monitor.check(mcp)
    assert result["status"] == "expired"
    assert result["expires_in"] == 0
    assert app_state.cookie_health == "expired"


@pytest.mark.asyncio
async def test_check_string_response_treated_as_expired():
    """源码对 user 调 .get() 后再 isinstance str;传字符串会 AttributeError → except → expired。

    这个测试记录真实行为,防止有人误以为它返回 healthy。
    """
    mcp = _make_mcp("plain text response")
    monitor = CookieHealthMonitor()
    result = await monitor.check(mcp)
    assert result["status"] == "expired"
    assert app_state.cookie_health == "expired"


@pytest.mark.asyncio
async def test_check_handles_missing_expires_in():
    """响应里没有 expires_in 字段时,默认 24h。"""
    mcp = _make_mcp({})
    monitor = CookieHealthMonitor()
    result = await monitor.check(mcp)
    assert result["status"] == "healthy"
    assert result["expires_in"] == 86400


@pytest.mark.asyncio
async def test_check_zero_expires_in_treated_as_unknown(monkeypatch):
    """expires_in=0 时视为未知,默认 24h healthy。"""
    mcp = _make_mcp({"expires_in": 0})
    monitor = CookieHealthMonitor()
    result = await monitor.check(mcp)
    assert result["status"] == "healthy"
