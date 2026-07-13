"""CookieHealthMonitor — BFF 主动探活与心跳保活。"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from dataworks_agent.config import settings
from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)
KEEPALIVE_INTERVAL = 300


class CookieHealthMonitor:
    """通过 BFF 探测 Cookie 可用性；不再依赖外部 data-mcp 的过期时间。"""

    def __init__(self) -> None:
        self._keepalive_task: asyncio.Task | None = None

    async def check(self, bff_client) -> dict:
        """通过 BFF CSRF 端点主动探测 Cookie。"""
        if bff_client is None:
            app_state.cookie_health = "unknown"
            return {"status": "unknown", "expires_in": None}
        try:
            await asyncio.wait_for(bff_client._refresh_csrf(), timeout=10)
            app_state.cookie_health = "healthy"
            return {"status": "healthy", "expires_in": None}
        except Exception:
            app_state.cookie_health = "expired"
            return {"status": "expired", "expires_in": 0}

    async def _suspend_waiting_tasks(self, client_ip: str | None = None) -> None:
        """仅允许清理明确客户端的排队任务，避免跨用户影响。"""
        if client_ip is None:
            logger.warning("Cookie 全局健康度异常，暂不清理任何客户端队列")
            return
        queue = app_state.task_queues.get(client_ip)
        if queue is None:
            return
        while not queue.empty():
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def start_keepalive(self, bff_client=None) -> None:
        """通过轻量 BFF /csrf 请求维持会话。"""
        if not settings.cookie_keepalive_enabled:
            logger.info("Cookie keepalive 已禁用 (COOKIE_KEEPALIVE_ENABLED=false)")
            return

        async def _loop() -> None:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                try:
                    if bff_client:
                        await bff_client._refresh_csrf()
                        logger.debug("Cookie keepalive OK")
                except Exception:
                    logger.debug("Cookie keepalive 失败")

        self._keepalive_task = asyncio.create_task(_loop())
        logger.info("Cookie keepalive 已启用 (间隔 %ds, 仅 BFF 心跳)", KEEPALIVE_INTERVAL)

    async def stop_keepalive(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task


cookie_health_monitor = CookieHealthMonitor()
