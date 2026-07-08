"""client_ip 与 Cookie 本机校验单元测试（v10 §2.2/§2.3）。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from dataworks_agent.middleware.client_ip import is_loopback, peer_ip, resolve_client_ip


def _make_request(client_ip: str, headers: dict | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (client_ip, 50000),
        "query_string": b"",
    }
    return Request(scope)


def test_peer_ip_uses_tcp_client():
    req = _make_request("203.0.113.9")
    assert peer_ip(req) == "203.0.113.9"


def test_resolve_client_ip_ignores_xff_when_peer_not_trusted():
    """loopback peer + 伪造 XFF 127.0.0.1 不应被信任（v9 §2.2）。"""
    req = _make_request(
        "127.0.0.1",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert resolve_client_ip(req, frozenset()) == "127.0.0.1"


def test_resolve_client_ip_trusts_xff_only_from_trusted_proxy():
    req = _make_request(
        "10.0.0.1",
        headers={"X-Forwarded-For": "203.0.113.42, 10.0.0.1"},
    )
    assert resolve_client_ip(req, frozenset()) == "10.0.0.1"
    assert resolve_client_ip(req, frozenset({"10.0.0.1"})) == "203.0.113.42"


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "::1", "0:0:0:0:0:0:0:1", "localhost"],
)
def test_is_loopback(ip: str):
    assert is_loopback(ip)


@pytest.mark.asyncio
async def test_cookie_copy_rejects_remote_peer():
    from dataworks_agent.routers.cookie import copy_cookie

    req = _make_request("203.0.113.9")
    with pytest.raises(HTTPException) as exc:
        await copy_cookie(req)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_cookie_copy_rejects_xff_spoof_on_loopback_peer():
    """伪造 XFF 不能绕过 _require_local（检查 peer 而非 resolve_client_ip）。"""
    from dataworks_agent.routers.cookie import copy_cookie

    req = _make_request(
        "203.0.113.9",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    with pytest.raises(HTTPException) as exc:
        await copy_cookie(req)
    assert exc.value.status_code == 403
