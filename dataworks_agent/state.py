"""全局 AppState — 单例持有 MCP 连接池、配置、健康状态等共享资源。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from dataworks_agent.config import Settings, settings


class AppState:
    """应用级全局状态。在 lifespan 启动阶段初始化。"""

    def __init__(self) -> None:
        self.settings: Settings = settings
        self.cookie_health: str = "unknown"  # healthy | warning | critical | expired | degraded
        self.smoke_ok: bool = False
        self.smoke_failures: list[tuple[str, bool, str]] = []
        self.smoke_results: dict[str, dict] = {}
        self.task_queues: dict[str, asyncio.Queue] = {}
        self.startup_time: datetime = datetime.now(UTC)

        # 延迟导入避免循环依赖
        self._mcp_pool: MCPClientPool | None = None  # noqa: F821
        # 执行底座客户端（lifespan 注入；迁移期与 _bff_client 并存）
        self._openapi_client = None  # DataWorksOpenAPIClient | None
        self._maxcompute_client = None  # MaxComputeClient | None
        self._node_client = None  # OpenAPINodeAdapter | None（节点操作 AK/SK，drop-in 替 bff）

    @property
    def mcp_pool(self):
        return self._mcp_pool

    @mcp_pool.setter
    def mcp_pool(self, pool):
        self._mcp_pool = pool

    def get_task_queue(self, ip: str) -> asyncio.Queue:
        """获取或创建用户专属任务队列。"""
        if ip not in self.task_queues:
            self.task_queues[ip] = asyncio.Queue(maxsize=5)
        return self.task_queues[ip]

    def cleanup_expired_contexts(self, ttl: float = 1800) -> None:
        """清理过期用户上下文。"""
        now = datetime.now(UTC).timestamp()
        expired = []
        for ip, q in self.task_queues.items():
            if q.empty() and now - self.startup_time.timestamp() > ttl:
                expired.append(ip)
        for ip in expired:
            del self.task_queues[ip]


# 全局单例
app_state = AppState()
