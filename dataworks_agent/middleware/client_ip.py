"""客户端 IP 解析 — 区分 TCP 对端与经受信代理解析后的客户端 IP。"""

from __future__ import annotations

from starlette.requests import Request


def peer_ip(request: Request) -> str:
    """直连 TCP 对端地址（不可被 X-Forwarded-For 伪造）。"""
    return request.client.host if request.client else "127.0.0.1"


def is_loopback(ip: str) -> bool:
    return ip in ("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1")


def resolve_client_ip(request: Request, trusted_proxies: frozenset[str]) -> str:
    """解析用于隔离/限流的客户端 IP。

    仅当 TCP 对端在 trusted_proxies 内时才读取 X-Forwarded-For 最左值；
    否则使用对端 IP，避免远程攻击者伪造 XFF 绕过本机校验（v9 §2.2）。
    """
    peer = peer_ip(request)
    if peer in trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer
