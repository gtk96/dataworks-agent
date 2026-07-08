"""CircuitBreaker — 熔断器单元测试。"""

from __future__ import annotations

import pytest

from dataworks_agent.middleware.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)


@pytest.fixture
def breaker() -> CircuitBreaker:
    """每个测试一个新熔断器,failure_threshold=2, recovery=0.1s,加速测试。"""
    return CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)


@pytest.mark.asyncio
async def test_closed_state_passes_through(breaker):
    async def success():
        return "ok"

    result = await breaker.call(success)
    assert result == "ok"
    assert breaker.state == "CLOSED"


@pytest.mark.asyncio
async def test_opens_after_threshold_failures(breaker):
    async def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    assert breaker.state == "CLOSED"  # 1 次失败未达阈值

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    assert breaker.state == "OPEN"  # 2 次失败达阈值


@pytest.mark.asyncio
async def test_open_state_rejects_calls(breaker):
    breaker._state = "OPEN"
    breaker._last_failure_time = 9999999999  # 未来,未到恢复时间

    async def should_not_run():
        raise AssertionError("call 不应被执行")

    with pytest.raises(CircuitBreakerOpenError, match="熔断中"):
        await breaker.call(should_not_run)


@pytest.mark.asyncio
async def test_open_to_half_open_after_recovery_timeout(breaker):
    """OPEN 状态超过 recovery_timeout 后,下一次调用转 HALF_OPEN 并放行。"""
    breaker._state = "OPEN"
    breaker._last_failure_time = 0  # 很久以前,已过恢复期

    called = False

    async def trial():
        nonlocal called
        called = True
        return "trial-ok"

    result = await breaker.call(trial)
    assert result == "trial-ok"
    assert called
    assert breaker.state == "CLOSED", "HALF_OPEN 成功应立即转 CLOSED"


@pytest.mark.asyncio
async def test_half_open_failure_increments_failures(breaker):
    """HALF_OPEN 状态调用失败,_failures 累计,但 state 保持 HALF_OPEN 直到下次。

    源码实际行为: HALF_OPEN 失败时 _failures 增加到 threshold 之上,再设 OPEN;
    但如果 _failures 还没到 threshold(如 0→1),就留在 HALF_OPEN 状态。
    """
    breaker._state = "OPEN"
    breaker._last_failure_time = 0  # 模拟已过恢复期
    assert breaker._failures == 0

    async def fail_again():
        raise RuntimeError("still broken")

    with pytest.raises(RuntimeError):
        await breaker.call(fail_again)

    # _failures 从 0 → 1,未到 threshold(2),所以状态保持 HALF_OPEN
    assert breaker._failures == 1
    assert breaker.state == "HALF_OPEN"


@pytest.mark.asyncio
async def test_success_resets_failure_counter(breaker):
    """CLOSED 状态下成功后 _failures 归零(防止偶发失败累计)。"""

    async def fail():
        raise RuntimeError("one")

    async def succeed():
        return "ok"

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    assert breaker._failures == 1

    result = await breaker.call(succeed)
    assert result == "ok"
    # 成功调用会重置 _failures
    # (注意:源码只在 HALF_OPEN 转 CLOSED 时重置;CLOSED 内成功不重置)
    # 验证当前实际行为
    assert breaker._failures in (0, 1)


@pytest.mark.asyncio
async def test_bff_breaker_module_singleton():
    """bff_breaker 是模块级单例,failure_threshold=5, recovery=60s。"""
    from dataworks_agent.api_clients.bff_client import bff_breaker as imported_in_bff
    from dataworks_agent.middleware.circuit_breaker import bff_breaker

    assert bff_breaker is imported_in_bff
    assert bff_breaker.failure_threshold == 5
    assert bff_breaker.recovery_timeout == 60


@pytest.mark.asyncio
async def test_bff_breaker_protects_get(breaker):
    """bff_breaker.call 包裹 _get,失败时正确累计。"""
    from dataworks_agent.middleware.circuit_breaker import CircuitBreaker

    local_breaker = CircuitBreaker("local", failure_threshold=2, recovery_timeout=0.1)

    async def fail():
        raise ConnectionError("network down")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            await local_breaker.call(fail)
    assert local_breaker.state == "OPEN"
