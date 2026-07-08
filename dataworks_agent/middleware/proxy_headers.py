"""受信反向代理 X-Forwarded-* 解析（Starlette ProxyHeadersMiddleware 兼容子集）。

Starlette <0.28 无内置模块；行为对齐官方实现：仅当 TCP 对端在 trusted_hosts
内时才改写 scope["client"] 与 scheme。
"""

from __future__ import annotations


class ProxyHeadersMiddleware:
    """解析 X-Forwarded-For / X-Forwarded-Proto（v11 §3.3）。"""

    def __init__(self, app, trusted_hosts: list[str] | str | None = None) -> None:
        self.app = app
        if trusted_hosts is None:
            self.trusted_hosts: list[str] = []
        elif isinstance(trusted_hosts, str):
            self.trusted_hosts = [trusted_hosts]
        else:
            self.trusted_hosts = list(trusted_hosts)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.trusted_hosts:
            client = scope.get("client")
            if client is not None:
                client_host = client[0]
                if client_host in self.trusted_hosts:
                    headers = dict(scope.get("headers") or [])
                    forwarded_for = headers.get(b"x-forwarded-for", b"").decode("latin1")
                    if forwarded_for:
                        client_host = forwarded_for.split(",")[0].strip()
                    forwarded_proto = headers.get(b"x-forwarded-proto", b"").decode("latin1")
                    if forwarded_proto in ("http", "https", "ws", "wss"):
                        scope["scheme"] = forwarded_proto
                    scope["client"] = (client_host, client[1])
        await self.app(scope, receive, send)
