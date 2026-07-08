"""Error-as-Data — 错误分类与边界。

实现 Requirement 30：错误分类、可恢复错误回传 LLM、系统级错误中断执行。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorClass(StrEnum):
    """错误分类。"""

    RECOVERABLE = "recoverable"  # 可恢复：超时、限流、可修正语法错误
    SYSTEM = "system"  # 系统级：DB 错误、服务不可用
    SECURITY = "security"  # 安全级：权限拒绝、凭证缺失


class ErrorSeverity(StrEnum):
    """错误严重程度。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ClassifiedError:
    """分类后的错误。"""

    error_class: ErrorClass
    severity: ErrorSeverity
    message: str
    original_error: Exception | None = None
    context: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = False
    retry_suggestion: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


# 可恢复错误模式
RECOVERABLE_PATTERNS = [
    "timeout",
    "connection refused",
    "connection reset",
    "rate limit",
    "too many requests",
    "temporary failure",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "sql syntax error",
    "invalid syntax",
    "column not found",
    "table not found",
]

# 系统级错误模式
SYSTEM_PATTERNS = [
    "database error",
    "internal server error",
    "out of memory",
    "disk full",
    "process crashed",
    "segmentation fault",
]

# 安全级错误模式
SECURITY_PATTERNS = [
    "permission denied",
    "access denied",
    "unauthorized",
    "forbidden",
    "credential",
    "token expired",
    "invalid token",
    "authentication failed",
    "authorization failed",
]


def classify_error(error: Exception | str) -> ClassifiedError:
    """分类错误。

    根据错误消息判断错误类型：
    - RECOVERABLE: 可恢复错误，回传 LLM 供其决策
    - SYSTEM: 系统级错误，中断执行
    - SECURITY: 安全级错误，中断执行并交由人工处理
    """
    error_msg = str(error).lower()

    # 检查安全级错误（优先级最高）
    for pattern in SECURITY_PATTERNS:
        if pattern in error_msg:
            return ClassifiedError(
                error_class=ErrorClass.SECURITY,
                severity=ErrorSeverity.CRITICAL,
                message=str(error),
                original_error=error if isinstance(error, Exception) else None,
                recoverable=False,
                retry_suggestion="需要人工审批或权限调整",
            )

    # 检查系统级错误
    for pattern in SYSTEM_PATTERNS:
        if pattern in error_msg:
            return ClassifiedError(
                error_class=ErrorClass.SYSTEM,
                severity=ErrorSeverity.HIGH,
                message=str(error),
                original_error=error if isinstance(error, Exception) else None,
                recoverable=False,
                retry_suggestion="系统故障，需要人工介入",
            )

    # 检查可恢复错误
    for pattern in RECOVERABLE_PATTERNS:
        if pattern in error_msg:
            return ClassifiedError(
                error_class=ErrorClass.RECOVERABLE,
                severity=ErrorSeverity.LOW,
                message=str(error),
                original_error=error if isinstance(error, Exception) else None,
                recoverable=True,
                retry_suggestion="可以重试或修改后重试",
            )

    # 未知错误默认为系统级
    return ClassifiedError(
        error_class=ErrorClass.SYSTEM,
        severity=ErrorSeverity.MEDIUM,
        message=str(error),
        original_error=error if isinstance(error, Exception) else None,
        recoverable=False,
        retry_suggestion="未知错误，需要人工排查",
    )


def format_error_for_llm(error: ClassifiedError) -> dict[str, Any]:
    """将错误格式化为 LLM 可消费的结构化数据。

    用于 Requirement 30.1：可恢复错误作为数据返回给 LLM。
    """
    return {
        "error_class": error.error_class.value,
        "severity": error.severity.value,
        "message": error.message,
        "recoverable": error.recoverable,
        "retry_suggestion": error.retry_suggestion,
        "context": error.context,
        "timestamp": error.timestamp,
    }


def should_interrupt(error: ClassifiedError) -> bool:
    """判断是否应该中断执行。

    用于 Requirement 30.2：系统级/安全级错误中断执行。
    """
    return error.error_class in (ErrorClass.SYSTEM, ErrorClass.SECURITY)


def should_retry(error: ClassifiedError) -> bool:
    """判断是否应该重试。"""
    return error.recoverable and error.error_class == ErrorClass.RECOVERABLE
