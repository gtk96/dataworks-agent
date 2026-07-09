"""CDP Cookie 提取并发控制与失败退避。"""

from __future__ import annotations

import asyncio
import time


class CookieExtractState:
    """防止后台刷新与手动提取并发；连续失败时指数退避。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.is_running = False
        self.consecutive_failures = 0
        self.last_failure_ts: float = 0.0
        self.backoff_seconds: int = 0

    def should_skip_due_to_backoff(self) -> bool:
        if self.backoff_seconds <= 0:
            return False
        elapsed = time.time() - self.last_failure_ts
        if elapsed >= self.backoff_seconds:
            self.backoff_seconds = 0
            return False
        return True

    def record_start(self) -> None:
        self.is_running = True

    def record_success(self) -> None:
        self.is_running = False
        self.consecutive_failures = 0
        self.backoff_seconds = 0

    def record_failure(self) -> None:
        self.is_running = False
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()
        # 60s → 120s → 240s … 上限 15min
        self.backoff_seconds = min(60 * (2 ** min(self.consecutive_failures - 1, 4)), 900)


extract_state = CookieExtractState()
