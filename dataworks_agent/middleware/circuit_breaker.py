"""熔断器 — BFF/CDP 通道在连续失败达到阈值时进入 OPEN 状态。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """熔断打开时拒绝执行。"""

    pass


class CircuitBreaker:
    """三态熔断器: CLOSED → OPEN → HALF_OPEN → CLOSED。"""

    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: float = 30) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures: int = 0
        self._state: str = "CLOSED"
        self._last_failure_time: float = 0

    @property
    def state(self) -> str:
        return self._state

    async def call(self, fn: Callable, *args, **kwargs):
        """受熔断保护的函数调用。"""
        if self._state == "OPEN":
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = "HALF_OPEN"
                logger.info("熔断器 %s → HALF_OPEN (尝试恢复)", self.name)
            else:
                raise CircuitBreakerOpenError(f"{self.name} 熔断中，请稍后重试")

        try:
            result = await fn(*args, **kwargs)
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
                self._failures = 0
                logger.info("熔断器 %s → CLOSED (已恢复)", self.name)
            return result
        except Exception:
            self._failures += 1
            self._last_failure_time = time.time()
            if self._failures >= self.failure_threshold:
                self._state = "OPEN"
                logger.critical("熔断器 %s → OPEN (%d 次连续失败)", self.name, self._failures)
            raise


# 全局熔断器实例
bff_breaker = CircuitBreaker("BFF", failure_threshold=5, recovery_timeout=60)
cdp_breaker = CircuitBreaker("CDP", failure_threshold=3, recovery_timeout=30)
