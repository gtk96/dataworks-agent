"""重试策略单元测试。"""

from dataworks_agent.task_engine.retry_policy import get_delay, should_retry


def test_retryable_error():
    assert should_retry("network_timeout", 0) is True
    assert should_retry("network_timeout", 2) is True


def test_non_retryable_error():
    assert should_retry("root_check_failed", 0) is False
    assert should_retry("permission_denied", 0) is False
    assert should_retry("sql_syntax_error", 1) is False


def test_max_retries_exceeded():
    assert should_retry("network_timeout", 3) is False
    assert should_retry("bff_service_unavailable", 3) is False


def test_delay_calculation():
    assert get_delay(0) == 2
    assert get_delay(1) == 4
    assert get_delay(2) == 8
    assert get_delay(0, "sqlite_locked") == 0.5
