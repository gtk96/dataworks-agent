"""中间件单元测试 — rate_limit / idempotency。"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from dataworks_agent.middleware.idempotency import IdempotencyMiddleware
from dataworks_agent.middleware.rate_limit import (
    RateLimitMiddleware,
    rate_limiter,
)


def _make_request(
    method: str = "POST", headers: dict | None = None, client_ip: str = "127.0.0.1"
) -> Request:
    # Starlette Headers 对 raw tuples 大小写敏感(只在从 scope 构造时 normalize),这里强制 lowercase
    raw_headers = []
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode(), v.encode()))
    scope = {
        "type": "http",
        "method": method,
        "path": "/",
        "headers": raw_headers,
        "client": (client_ip, 50000),
        "query_string": b"",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_rate_limit_passes_under_burst():
    mw = RateLimitMiddleware(app=None)
    req = _make_request()
    called = False

    async def call_next(_):
        nonlocal called
        called = True
        return "ok"

    result = await mw.dispatch(req, call_next)
    assert result == "ok"
    assert called


@pytest.mark.asyncio
async def test_rate_limit_returns_429_on_exhaustion(monkeypatch):
    """强制 acquire 返回 False,验证 429 响应。"""
    mw = RateLimitMiddleware(app=None)
    req = _make_request()

    async def fake_acquire(key: str) -> bool:
        return False

    monkeypatch.setattr(rate_limiter, "acquire", fake_acquire)

    async def call_next(_):
        return "should-not-reach"

    result = await mw.dispatch(req, call_next)
    assert result.status_code == 429
    assert "频繁" in result.body.decode()


@pytest.mark.asyncio
async def test_idempotency_skips_non_post():
    mw = IdempotencyMiddleware(app=None)
    req = _make_request(method="GET")
    called = False

    async def call_next(_):
        nonlocal called
        called = True
        return "ok"

    result = await mw.dispatch(req, call_next)
    assert result == "ok"
    assert called


@pytest.mark.asyncio
async def test_idempotency_skips_without_key():
    mw = IdempotencyMiddleware(app=None)
    req = _make_request(method="POST", headers={})
    called = False

    async def call_next(_):
        nonlocal called
        called = True
        return "ok"

    result = await mw.dispatch(req, call_next)
    assert result == "ok"
    assert called


@pytest.mark.asyncio
async def test_idempotency_register_and_lookup():
    mw = IdempotencyMiddleware(app=None)
    mw.register("abc-123", "127.0.0.1", "task-xyz")

    # 已注册的 key 命中
    assert mw.get_existing("abc-123", "127.0.0.1") == "task-xyz"
    # 另一 IP 不命中
    assert mw.get_existing("abc-123", "10.0.0.1") is None
    # 未注册的 key 不命中
    assert mw.get_existing("nonexistent", "127.0.0.1") is None


@pytest.mark.asyncio
async def test_idempotency_dispatch_returns_cached_on_replay():
    """同一 IP+key 重复请求,第二次直接返回缓存的 task_id。

    模拟真实场景: 第一次调用时,业务代码在处理完后通过 register() 写入 task_id;
    第二次调用同 key 时, dispatch 在 call_next 之前就命中缓存并返回。
    """
    mw = IdempotencyMiddleware(app=None)
    req = _make_request(method="POST", headers={"X-Idempotency-Key": "replay-key"})

    # 第一次: 走 call_next,业务代码在内部调用 register
    async def call_next(_):
        mw.register("replay-key", "127.0.0.1", "task-42")
        return "first-response"

    r1 = await mw.dispatch(req, call_next)
    assert r1 == "first-response"

    # 第二次: 直接返回缓存,不再调 call_next
    called_again = False

    async def call_next_again(_):
        nonlocal called_again
        called_again = True
        return "should-not-reach"

    r2 = await mw.dispatch(req, call_next_again)
    assert r2.status_code == 200
    body = r2.body.decode()
    assert "task-42" in body and "重复请求" in body
    assert not called_again


@pytest.mark.asyncio
async def test_idempotency_auto_registers_from_json_response():
    """响应是 JSON 且含 task_id 字段时,中间件自动 register。

    覆盖场景: 路由不显式调 register,只要返回 {task_id: "..."} + 客户端带
    X-Idempotency-Key 头,中间件自动防重复。
    """
    from starlette.responses import JSONResponse

    mw = IdempotencyMiddleware(app=None)
    req = _make_request(method="POST", headers={"X-Idempotency-Key": "auto-key"})

    async def call_next(_):
        return JSONResponse({"task_id": "auto-task-99", "status": "pending"})

    r1 = await mw.dispatch(req, call_next)
    assert r1.status_code == 200

    # 中间件已自动 register,直接查
    assert mw.get_existing("auto-key", "127.0.0.1") == "auto-task-99"

    # 第二次发同 key,应返回缓存
    async def call_next_again(_):
        raise AssertionError("call_next 不应被调用,应该命中缓存")

    r2 = await mw.dispatch(req, call_next_again)
    body = r2.body.decode()
    assert "auto-task-99" in body


@pytest.mark.asyncio
async def test_idempotency_ignores_non_json_response():
    """非 JSON 响应不会 register(避免误判)。"""
    mw = IdempotencyMiddleware(app=None)
    req = _make_request(method="POST", headers={"X-Idempotency-Key": "html-key"})

    async def call_next(_):
        from starlette.responses import HTMLResponse

        return HTMLResponse("<html>ok</html>")

    await mw.dispatch(req, call_next)
    assert mw.get_existing("html-key", "127.0.0.1") is None


@pytest.mark.asyncio
async def test_idempotency_ignores_json_without_task_id():
    """JSON 响应但不含 task_id 字段,不会 register。"""
    from starlette.responses import JSONResponse

    mw = IdempotencyMiddleware(app=None)
    req = _make_request(method="POST", headers={"X-Idempotency-Key": "no-task-key"})

    async def call_next(_):
        return JSONResponse({"status": "ok", "data": "value"})

    await mw.dispatch(req, call_next)
    assert mw.get_existing("no-task-key", "127.0.0.1") is None


@pytest.mark.asyncio
async def test_ip_isolation_sets_state_attributes():
    """IPIsolationMiddleware 给 request.state 注入 client_ip + user_context + user_id。"""
    from dataworks_agent.middleware.ip_isolation import IPIsolationMiddleware

    mw = IPIsolationMiddleware(app=None)
    req = _make_request(method="GET", client_ip="192.168.1.42")

    async def call_next(r):
        # 在 call_next 里检查 state 已被注入
        assert r.state.client_ip == "192.168.1.42"
        assert r.state.user_id == "ip_192_168_1_42"
        assert r.state.user_context.ip == "192.168.1.42"
        return "ok"

    result = await mw.dispatch(req, call_next)
    assert result == "ok"


@pytest.mark.asyncio
async def test_ip_isolation_cleanup_expired_contexts():
    """30 分钟无活动 + 空队列的 IP 上下文被清理。"""
    from dataworks_agent.middleware.ip_isolation import IPIsolationMiddleware

    mw = IPIsolationMiddleware(app=None)
    req = _make_request(method="GET", client_ip="10.0.0.1")

    async def call_next(_):
        return "ok"

    await mw.dispatch(req, call_next)
    assert "10.0.0.1" in mw._contexts

    # 模拟 30+ 分钟前的活动 + 空队列
    import time

    mw._contexts["10.0.0.1"].last_activity = time.time() - 2000
    # task_queue 默认就是空 Queue
    assert mw._contexts["10.0.0.1"].task_queue.empty()

    # 直接调 cleanup(模拟 dispatch 后的清理)
    mw._cleanup_expired()
    assert "10.0.0.1" not in mw._contexts, "过期上下文应被清理"


@pytest.mark.asyncio
async def test_ip_isolation_keeps_active_context():
    """最近活动的 IP 上下文不被清理。"""
    from dataworks_agent.middleware.ip_isolation import IPIsolationMiddleware

    mw = IPIsolationMiddleware(app=None)
    req = _make_request(method="GET", client_ip="10.0.0.2")

    async def call_next(_):
        return "ok"

    await mw.dispatch(req, call_next)
    mw._cleanup_expired()
    assert "10.0.0.2" in mw._contexts, "刚活动的 IP 不应被清理"


@pytest.mark.asyncio
async def test_ip_isolation_ignores_xff_without_trusted_proxy(monkeypatch):
    """loopback peer 时忽略 X-Forwarded-For，避免伪造本机 IP（v10 §2.2）。"""
    from dataworks_agent.config import settings
    from dataworks_agent.middleware.ip_isolation import IPIsolationMiddleware

    monkeypatch.setattr(settings, "trusted_proxies", [])
    mw = IPIsolationMiddleware(app=None)
    req = _make_request(
        method="GET",
        client_ip="127.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.99"},
    )

    async def call_next(r):
        assert r.state.client_ip == "127.0.0.1"
        return "ok"

    result = await mw.dispatch(req, call_next)
    assert result == "ok"
