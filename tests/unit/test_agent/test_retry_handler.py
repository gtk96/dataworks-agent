import pytest

from dataworks_agent.agent.executor.retry_handler import RetryHandler


@pytest.fixture
def handler():
    return RetryHandler(max_retries=3)


def test_should_retry_on_transient_error(handler):
    """测试瞬时错误应该重试"""
    strategy = handler.get_strategy("connection_timeout")
    assert strategy.should_retry is True
    assert strategy.delay_seconds > 0


def test_should_not_retry_on_permanent_error(handler):
    """测试永久错误不应重试"""
    strategy = handler.get_strategy("invalid_table_name")
    assert strategy.should_retry is False


def test_retry_count_exceeded(handler):
    """测试重试次数超限"""
    for _ in range(3):
        handler.record_attempt("connection_timeout")

    strategy = handler.get_strategy("connection_timeout")
    assert strategy.should_retry is False


def test_exponential_backoff(handler):
    """测试指数退避"""
    handler.record_attempt("connection_timeout")
    strategy1 = handler.get_strategy("connection_timeout")

    handler.record_attempt("connection_timeout")
    strategy2 = handler.get_strategy("connection_timeout")

    assert strategy2.delay_seconds > strategy1.delay_seconds


def test_reset_attempts(handler):
    """测试重置尝试次数"""
    handler.record_attempt("connection_timeout")
    handler.record_attempt("connection_timeout")

    handler.reset("connection_timeout")
    strategy = handler.get_strategy("connection_timeout")
    assert strategy.should_retry is True


def test_unknown_error_defaults_to_retry(handler):
    """测试未知错误默认重试"""
    strategy = handler.get_strategy("some_unknown_error")
    assert strategy.should_retry is True
    assert strategy.delay_seconds == 1.0
