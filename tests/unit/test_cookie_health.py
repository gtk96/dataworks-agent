"""Cookie 健康监测 — BFF 探活。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from dataworks_agent.cookie.health import CookieHealthMonitor
from dataworks_agent.state import app_state


@pytest.fixture(autouse=True)
def reset_state():
    app_state.cookie_health = "unknown"
    yield
    app_state.cookie_health = "unknown"


def _make_bff(*, error: Exception | None = None):
    bff = MagicMock()
    bff._refresh_csrf = AsyncMock(side_effect=error)
    return bff


@pytest.mark.asyncio
async def test_check_healthy_when_bff_works():
    monitor = CookieHealthMonitor()
    result = await monitor.check(_make_bff())
    assert result == {"status": "healthy", "expires_in": None}
    assert app_state.cookie_health == "healthy"


@pytest.mark.asyncio
async def test_check_expired_when_bff_fails():
    monitor = CookieHealthMonitor()
    result = await monitor.check(_make_bff(error=RuntimeError("401")))
    assert result == {"status": "expired", "expires_in": 0}
    assert app_state.cookie_health == "expired"


@pytest.mark.asyncio
async def test_check_unknown_without_bff():
    monitor = CookieHealthMonitor()
    result = await monitor.check(None)
    assert result == {"status": "unknown", "expires_in": None}
    assert app_state.cookie_health == "unknown"


@pytest.mark.asyncio
async def test_global_signal_does_not_clear_queues():
    import asyncio

    q = asyncio.Queue()
    await q.put("job")
    app_state.task_queues["127.0.0.1"] = q
    await CookieHealthMonitor()._suspend_waiting_tasks()
    assert not q.empty()
    app_state.task_queues.pop("127.0.0.1", None)
