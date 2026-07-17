"""CookieHealthMonitor — 主动探活 + 心跳保活，防止会话超时。"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from giikin_dw_agent.config import settings
from giikin_dw_agent.state import app_state

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 3600  # 剩余 < 1h → 前端 banner
CRITICAL_THRESHOLD = 600  # 剩余 < 10min → 暂停新任务
KEEPALIVE_INTERVAL = 300  # 5 分钟心跳


class CookieHealthMonitor:
    """Cookie 剩余有效期监控 + 心跳保活。"""

    def __init__(self) -> None:
        self._keepalive_task: asyncio.Task | None = None

    async def check(self, mcp_pool) -> dict:
        """主动探测 Cookie 剩余有效期。"""
        try:
            user = await asyncio.wait_for(
                mcp_pool.call_tool("get_current_user", {}),
                timeout=10,
            )
            # expires_in 可能不存在（MCP 不返回），默认为足够大的值
            expires_in = user.get("expires_in", 0)
            if isinstance(user, str):
                # MCP 返回纯文本结果
                expires_in = 86400  # assume 24h

            if expires_in <= 0:
                expires_in = 86400  # 无有效期信息时假设 24h

            if expires_in < CRITICAL_THRESHOLD:
                app_state.cookie_health = "critical"
                await self._suspend_waiting_tasks()
                return {"status": "critical", "expires_in": expires_in}

            if expires_in < WARN_THRESHOLD:
                app_state.cookie_health = "warning"
                return {"status": "warning", "expires_in": expires_in}

            app_state.cookie_health = "healthy"
            return {"status": "healthy", "expires_in": expires_in}

        except Exception:
            app_state.cookie_health = "expired"
            return {"status": "expired", "expires_in": 0}

    async def _suspend_waiting_tasks(self, client_ip: str | None = None) -> None:
        """暂停排队中的任务。

        Args:
            client_ip: 指定客户端 IP，仅暂停该用户的任务。
                       **None 表示此次调用源自全局信号（如 cookie 全局过期监测），
                       不应跨用户清理队列——只记日志由人工处置。**
        """
        if client_ip is None:
            # 全局信号 —— 不自动清队列（避免一个用户 cookie 过期 kill 全部
            # pending 任务的副作用）。仅记 WARN，由人工或 Publish_Gate 后续处置。
            logger.warning(
                "Cookie 全局健康度异常，暂停清理队列（需人工处置 %d 个客户端队列）",
                len(app_state.task_queues),
            )
            return

        logger.warning("Cookie 即将过期，暂停客户端 %s 的排队任务", client_ip)

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
        """Cookie 心跳保活 — 通过轻量 BFF /csrf 请求维持会话，不刷新浏览器。"""
        if not settings.cookie_keepalive_enabled:
            logger.info("Cookie keepalive 已禁用 (COOKIE_KEEPALIVE_ENABLED=false)")
            return

        async def _loop() -> None:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                try:
                    if bff_client:
                        await bff_client._refresh_csrf()  # 轻量 GET /csrf，不刷新页面
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


# 全局单例
cookie_health_monitor = CookieHealthMonitor()
