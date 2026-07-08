"""DQConsumer 单元测试 — 数据质量消费。"""

import pytest

from dataworks_agent.semantic.quality import (
    DQConsumer,
    QualityCheckResult,
    QualityRule,
    QualitySignalData,
)


@pytest.fixture
def consumer():
    """创建 DQConsumer 实例。"""
    return DQConsumer()


@pytest.mark.asyncio
async def test_fetch_quality_signals(consumer):
    """获取质量信号。"""
    signal = await consumer.fetch_quality_signals("test_table")
    assert isinstance(signal, QualitySignalData)
    assert signal.table_name == "test_table"


@pytest.mark.asyncio
async def test_check_quality(consumer):
    """检查质量。"""
    # 添加规则
    rule = QualityRule(
        rule_id="rule_001",
        table_name="test_table",
        rule_type="completeness",
        threshold=0.9,
    )
    consumer.add_rule(rule)

    # 检查质量
    results = await consumer.check_quality("test_table")
    assert len(results) == 1
    assert results[0].passed is True


def test_add_rule(consumer):
    """添加质量规则。"""
    rule = QualityRule(
        rule_id="rule_001",
        table_name="test_table",
        rule_type="completeness",
        threshold=0.9,
    )
    consumer.add_rule(rule)

    rules = consumer.get_rules("test_table")
    assert len(rules) == 1


def test_get_rules_by_table(consumer):
    """按表获取质量规则。"""
    consumer.add_rule(
        QualityRule(rule_id="rule_001", table_name="table_a", rule_type="completeness")
    )
    consumer.add_rule(QualityRule(rule_id="rule_002", table_name="table_b", rule_type="freshness"))

    rules_a = consumer.get_rules("table_a")
    assert len(rules_a) == 1

    rules_b = consumer.get_rules("table_b")
    assert len(rules_b) == 1


@pytest.mark.asyncio
async def test_propose_quality_rule(consumer):
    """提议质量规则。"""
    rule = await consumer.propose_quality_rule(
        table_name="test_table",
        rule_type="completeness",
        threshold=0.95,
    )

    assert rule.rule_id.startswith("qr_")
    assert rule.enabled is False  # 需要审批


def test_approve_rule(consumer):
    """批准质量规则。"""
    rule = QualityRule(
        rule_id="rule_001",
        table_name="test_table",
        rule_type="completeness",
        threshold=0.9,
        enabled=False,
    )
    consumer.add_rule(rule)

    result = consumer.approve_rule("rule_001")
    assert result is True

    # 验证已启用
    rules = consumer.get_rules("test_table")
    assert rules[0].enabled is True


def test_check_data_trust(consumer):
    """检查数据可信度。"""
    result = consumer.check_data_trust("test_table")
    assert result["trusted"] is True
    assert result["confidence"] == 0.8


def test_quality_rule_post_init():
    """QualityRule 初始化。"""
    rule = QualityRule(
        rule_id="rule_001",
        table_name="test_table",
        rule_type="completeness",
    )
    assert rule.enabled is True


def test_quality_signal_data_post_init():
    """QualitySignalData 初始化。"""
    signal = QualitySignalData(table_name="test_table")
    assert signal.checked_at != ""


def test_quality_check_result_post_init():
    """QualityCheckResult 初始化。"""
    result = QualityCheckResult(
        table_name="test_table",
        rule_id="rule_001",
        passed=True,
    )
    assert result.checked_at != ""
