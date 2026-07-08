"""Error-as-Data 单元测试 — 错误分类与边界。"""

from dataworks_agent.runtime.errors import (
    ClassifiedError,
    ErrorClass,
    ErrorSeverity,
    classify_error,
    format_error_for_llm,
    should_interrupt,
    should_retry,
)


def test_classify_timeout_error():
    """分类超时错误 — 可恢复。"""
    error = classify_error("connection timeout")
    assert error.error_class == ErrorClass.RECOVERABLE
    assert error.recoverable is True
    assert error.severity == ErrorSeverity.LOW


def test_classify_rate_limit_error():
    """分类限流错误 — 可恢复。"""
    error = classify_error("rate limit exceeded")
    assert error.error_class == ErrorClass.RECOVERABLE
    assert error.recoverable is True


def test_classify_permission_error():
    """分类权限错误 — 安全级。"""
    error = classify_error("permission denied")
    assert error.error_class == ErrorClass.SECURITY
    assert error.recoverable is False
    assert error.severity == ErrorSeverity.CRITICAL


def test_classify_database_error():
    """分类数据库错误 — 系统级。"""
    error = classify_error("database error occurred")
    assert error.error_class == ErrorClass.SYSTEM
    assert error.recoverable is False
    assert error.severity == ErrorSeverity.HIGH


def test_classify_sql_syntax_error():
    """分类 SQL 语法错误 — 可恢复。"""
    error = classify_error("sql syntax error near SELECT")
    assert error.error_class == ErrorClass.RECOVERABLE
    assert error.recoverable is True


def test_classify_unknown_error():
    """分类未知错误 — 系统级。"""
    error = classify_error("something went wrong")
    assert error.error_class == ErrorClass.SYSTEM
    assert error.recoverable is False


def test_classify_exception():
    """分类异常对象。"""
    error = classify_error(Exception("connection refused"))
    assert error.error_class == ErrorClass.RECOVERABLE
    assert error.recoverable is True


def test_format_error_for_llm():
    """格式化错误为 LLM 可消费数据。"""
    error = classify_error("timeout")
    formatted = format_error_for_llm(error)

    assert formatted["error_class"] == "recoverable"
    assert formatted["recoverable"] is True
    assert "message" in formatted
    assert "timestamp" in formatted


def test_should_interrupt_system_error():
    """系统级错误应该中断。"""
    error = classify_error("database error")
    assert should_interrupt(error) is True


def test_should_interrupt_security_error():
    """安全级错误应该中断。"""
    error = classify_error("permission denied")
    assert should_interrupt(error) is True


def test_should_not_interrupt_recoverable_error():
    """可恢复错误不应该中断。"""
    error = classify_error("timeout")
    assert should_interrupt(error) is False


def test_should_retry_recoverable_error():
    """可恢复错误应该重试。"""
    error = classify_error("timeout")
    assert should_retry(error) is True


def test_should_not_retry_system_error():
    """系统级错误不应该重试。"""
    error = classify_error("database error")
    assert should_retry(error) is False


def test_should_not_retry_security_error():
    """安全级错误不应该重试。"""
    error = classify_error("permission denied")
    assert should_retry(error) is False


def test_classified_error_post_init():
    """ClassifiedError 初始化。"""
    error = ClassifiedError(
        error_class=ErrorClass.RECOVERABLE,
        severity=ErrorSeverity.LOW,
        message="test error",
    )
    assert error.timestamp != ""
