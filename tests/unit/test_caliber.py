"""CaliberClarifier 单元测试 — 口径澄清。"""

import pytest

from dataworks_agent.runtime.caliber import (
    CaliberClarificationRequest,
    CaliberClarificationResult,
    CaliberClarifier,
)


@pytest.fixture
def clarifier():
    """创建 CaliberClarifier 实例。"""
    return CaliberClarifier()


@pytest.mark.asyncio
async def test_clarify_metric_not_found(clarifier):
    """口径澄清 — 未找到指标。"""
    request = CaliberClarificationRequest(
        metric_id="nonexistent_metric",
        expected_caliber="订单数量",
    )
    result = await clarifier.clarify(request)

    assert result.resolved is False
    assert result.root_cause == "metric_not_found"
    assert result.needs_drill_down is True


def test_compare_calibers_match(clarifier):
    """比对口径 — 一致。"""
    match = clarifier._compare_calibers("订单数量", "订单数量")
    assert match is True


def test_compare_calibers_mismatch(clarifier):
    """比对口径 — 不一致。"""
    match = clarifier._compare_calibers("订单数量", "销售数量")
    assert match is False


def test_compare_calibers_empty(clarifier):
    """比对口径 — 空值。"""
    match = clarifier._compare_calibers("", "订单数量")
    assert match is True


@pytest.mark.asyncio
async def test_clarify_batch(clarifier):
    """批量口径澄清。"""
    requests = [
        CaliberClarificationRequest(
            metric_id="metric_1",
            expected_caliber="口径1",
        ),
        CaliberClarificationRequest(
            metric_id="metric_2",
            expected_caliber="口径2",
        ),
    ]
    results = await clarifier.clarify_batch(requests)
    assert len(results) == 2


def test_caliber_clarification_result_post_init():
    """CaliberClarificationResult 初始化。"""
    result = CaliberClarificationResult(
        metric_id="test_metric",
        resolved=True,
        caliber_match=True,
    )
    assert result.metric_id == "test_metric"
    assert result.evidence == []
