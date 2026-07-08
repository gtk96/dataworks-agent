"""指数退避重试策略 — 区分可重试/不可重试错误。"""

from __future__ import annotations

RETRYABLE_ERRORS = [
    "csrf_token_expired",
    "network_timeout",
    "bff_service_unavailable",
    "mcp_connection_lost",
    "sqlite_locked",
]

NON_RETRYABLE_ERRORS = [
    "root_check_failed",
    "permission_denied",
    "sql_syntax_error",
    "table_already_exists",
]

MAX_RETRIES = 3
BASE_DELAY = 2  # 秒


def should_retry(error_type: str, attempt: int) -> bool:
    """判断是否应该重试。"""
    if error_type in NON_RETRYABLE_ERRORS:
        return False
    if attempt >= MAX_RETRIES:
        return False
    return error_type in RETRYABLE_ERRORS


def get_delay(attempt: int, error_type: str = "") -> float:
    """计算重试延迟（秒）。"""
    if error_type == "sqlite_locked":
        return 0.5  # SQLite 写锁冲突极短延迟
    return BASE_DELAY * (2**attempt)  # 网络类: 2, 4, 8 秒
