"""重试处理器 - 处理执行失败和重试策略"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class RetryStrategy:
    """重试策略"""
    should_retry: bool
    delay_seconds: float
    reason: str


@dataclass
class ErrorPattern:
    """错误模式"""
    keyword: str
    is_transient: bool
    base_delay: float = 1.0


class RetryHandler:
    """重试处理器"""

    # 错误模式定义
    ERROR_PATTERNS: ClassVar[list[ErrorPattern]] = [
        ErrorPattern("connection_timeout", is_transient=True, base_delay=2.0),
        ErrorPattern("throttling", is_transient=True, base_delay=5.0),
        ErrorPattern("rate_limit", is_transient=True, base_delay=10.0),
        ErrorPattern("invalid_table_name", is_transient=False),
        ErrorPattern("permission_denied", is_transient=False),
        ErrorPattern("not_found", is_transient=False),
    ]

    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries
        self._attempt_counts: dict[str, int] = {}

    def record_attempt(self, error_type: str) -> None:
        """记录尝试次数"""
        self._attempt_counts[error_type] = self._attempt_counts.get(error_type, 0) + 1

    def get_strategy(self, error_type: str) -> RetryStrategy:
        """获取重试策略"""
        # 检查重试次数
        attempts = self._attempt_counts.get(error_type, 0)
        if attempts >= self._max_retries:
            return RetryStrategy(
                should_retry=False,
                delay_seconds=0,
                reason=f"重试次数已超限 ({attempts}/{self._max_retries})",
            )

        # 查找错误模式
        for pattern in self.ERROR_PATTERNS:
            if pattern.keyword in error_type.lower():
                if pattern.is_transient:
                    # 指数退避
                    delay = pattern.base_delay * (2 ** attempts)
                    return RetryStrategy(
                        should_retry=True,
                        delay_seconds=delay,
                        reason=f"瞬时错误，{delay:.1f}秒后重试",
                    )
                else:
                    return RetryStrategy(
                        should_retry=False,
                        delay_seconds=0,
                        reason="永久错误，不重试",
                    )

        # 未知错误，默认重试
        return RetryStrategy(
            should_retry=True,
            delay_seconds=1.0,
            reason="未知错误，尝试重试",
        )

    def reset(self, error_type: str | None = None) -> None:
        """重置尝试次数"""
        if error_type:
            self._attempt_counts.pop(error_type, None)
        else:
            self._attempt_counts.clear()
