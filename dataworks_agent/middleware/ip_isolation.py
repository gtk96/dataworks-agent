"""IP 隔离中间件 — 基于客户端 IP 的多用户隔离。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


@dataclass
class UserContext:
    ip: str
    session_start: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    active_tasks: set[str] = field(default_factory=set)
    cookie: str | None = None
    task_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=5))

    def is_expired(self, ttl: float = 1800) -> bool:
        return time.time() - self.last_activity > ttl


class IPIsolationMiddleware(BaseHTTPMiddleware):
    """基于 IP 的用户隔离 — 每个 IP 拥有独立的 UserContext 和任务队列。"""

    def __init__(self, app):
        super().__init__(app)
        self._contexts: dict[str, UserContext] = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "127.0.0.1"

        # T4: 反向代理(nginx 等)后取真实客户端 IP。
        # 仅当直连客户端是受信代理(本机/网关)时才信任 X-Forwarded-For，
        # 否则该头可被伪造。取最前一个 IP 即真实客户端。
        if client_ip in ("127.0.0.1", "::1", "0:0:0:0:0:0:0:1"):
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()

        # 获取或创建用户上下文
        if client_ip not in self._contexts:
            self._contexts[client_ip] = UserContext(ip=client_ip)

        ctx = self._contexts[client_ip]
        ctx.last_activity = time.time()

        # 注入到请求状态
        request.state.user_context = ctx
        request.state.user_id = f"ip_{client_ip.replace('.', '_')}"
        request.state.client_ip = client_ip

        response = await call_next(request)

        # 清理过期上下文
        self._cleanup_expired()

        return response

    def _cleanup_expired(self) -> None:
        expired = [
            ip for ip, ctx in self._contexts.items() if ctx.is_expired() and ctx.task_queue.empty()
        ]
        for ip in expired:
            del self._contexts[ip]

    def get_context(self, ip: str) -> UserContext | None:
        return self._contexts.get(ip)
