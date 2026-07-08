"""MetricAttributor 单元测试 — 指标归因诊断。"""

import pytest

from dataworks_agent.runtime.attribution import (
    AnomalyReport,
    AttributionResult,
    MetricAttributor,
    RootCause,
)


@pytest.fixture
def attributor():
    """创建 MetricAttributor 实例。"""
    return MetricAttributor()


@pytest.mark.asyncio
async def test_diagnose_caliber_mismatch(attributor):
    """诊断口径不一致 — 指标不存在时需要下钻。"""
    report = AnomalyReport(
        report_id="report_001",
        metric_id="nonexistent_metric",
        expected_value=100,
        actual_value=200,
        context={"expected_caliber": "订单数量"},
    )
    result = await attributor.diagnose(report)

    # 指标不存在时，会执行 drill down，最终返回根因
    assert result.resolved is True
    assert result.root_cause is not None


@pytest.mark.asyncio
async def test_diagnose_metric_not_found(attributor):
    """诊断指标不存在。"""
    report = AnomalyReport(
        report_id="report_002",
        metric_id="nonexistent_metric",
        expected_value=100,
        actual_value=200,
    )
    result = await attributor.diagnose(report)

    # 可能是口径不匹配或需要下钻
    assert result.resolved is True
    assert result.root_cause is not None


def test_classify_root_cause_no_mismatch(attributor):
    """分类根因 — 无不匹配。"""
    drill_down_results = [
        {"layer": "DMR", "match": True},
        {"layer": "DWS", "match": True},
        {"layer": "DWD", "match": True},
    ]
    root_cause = attributor._classify_root_cause(drill_down_results)
    assert root_cause == RootCause.BUSINESS_FLUCTUATION


def test_classify_root_cause_multiple_mismatch(attributor):
    """分类根因 — 多个不匹配。"""
    drill_down_results = [
        {"layer": "DMR", "match": False},
        {"layer": "DWS", "match": False},
        {"layer": "DWD", "match": True},
    ]
    root_cause = attributor._classify_root_cause(drill_down_results)
    assert root_cause == RootCause.DATA_BUG


def test_classify_root_cause_single_mismatch(attributor):
    """分类根因 — 单个不匹配。"""
    drill_down_results = [
        {"layer": "DMR", "match": True},
        {"layer": "DWS", "match": True},
        {"layer": "DWD", "match": False},
    ]
    root_cause = attributor._classify_root_cause(drill_down_results)
    assert root_cause == RootCause.UPSTREAM_DELAY


def test_generate_repair_suggestion(attributor):
    """生成修复提议。"""
    report = AnomalyReport(
        report_id="report_001",
        metric_id="order_count",
    )
    drill_down_results = [
        {"layer": "DWD", "match": False},
    ]
    suggestion = attributor._generate_repair_suggestion(report, drill_down_results)

    assert suggestion["type"] == "data_fix"
    assert suggestion["requires_approval"] is True


def test_anomaly_report_post_init():
    """AnomalyReport 初始化。"""
    report = AnomalyReport(report_id="report_001", metric_id="test")
    assert report.report_id == "report_001"
    assert report.metric_id == "test"


def test_attribution_result_post_init():
    """AttributionResult 初始化。"""
    result = AttributionResult(report_id="report_001", metric_id="test")
    assert result.timestamp != ""
    assert result.evidence == []
