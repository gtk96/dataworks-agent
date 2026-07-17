"""全局 AppState — 单例持有执行客户端、配置、健康状态等共享资源。"""

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
        self.cookie_bg_poll: dict = {}
        self.word_root_sync: dict = {}
        self.task_queues: dict[str, asyncio.Queue] = {}
        self.startup_time: datetime = datetime.now(UTC)

        # 执行底座客户端（lifespan 注入；与 Cookie BFF 长期并存）
        self._openapi_client = None  # DataWorksOpenAPIClient | None
        self._maxcompute_client = None  # MaxComputeClient | None
        self._node_client = None  # OpenAPINodeAdapter | None（节点操作 AK/SK，drop-in 替 bff）
        self._official_mcp_client = None  # OfficialDataWorksMCPClient | None
        self._bff_client = None  # DataWorksClient | None（Cookie BFF 兜底）
        self._cdp_client = None  # CDPClient | None
        self._publish_gate = None  # Runtime PublishGate | None

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
