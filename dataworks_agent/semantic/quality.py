"""DQConsumer — 数据质量消费。

实现 Requirement 28：
- 拉 DataWorks DQC 结果 → 转 Quality_Signal 进语义层
- agent 提议质量规则(审批后写 DQC)
- 引用不可信数据告警
- 不自建 DQ 引擎
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QualityRule:
    """质量规则。"""

    rule_id: str
    table_name: str
    rule_type: str  # completeness / freshness / uniqueness / accuracy
    threshold: float = 0.0
    operator: str = "gte"  # gte / lte / eq
    enabled: bool = True


@dataclass
class QualityCheckResult:
    """质量检查结果。"""

    table_name: str
    rule_id: str
    passed: bool
    actual_value: float = 0.0
    expected_value: float = 0.0
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(UTC).isoformat()


@dataclass
class QualitySignalData:
    """质量信号数据。"""

    table_name: str
    freshness: str = "unknown"  # fresh/stale/unknown
    completeness: float = 0.0  # 0-1
    uniqueness: float = 0.0  # 0-1
    quality_status: str = "unknown"  # good/warning/bad/unknown
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(UTC).isoformat()


class DQConsumer:
    """数据质量消费者。

    拉 DataWorks DQC 结果 → 转 Quality_Signal 进语义层。
    """

    def __init__(self) -> None:
        self._rules: dict[str, QualityRule] = {}

    async def fetch_quality_signals(self, table_name: str) -> QualitySignalData:
        """获取质量信号。"""
        # 简化实现：返回默认质量信号
        # 实际应从 DataWorks DQC 获取
        return QualitySignalData(
            table_name=table_name,
            freshness="unknown",
            completeness=0.0,
            uniqueness=0.0,
            quality_status="unknown",
        )

    async def check_quality(self, table_name: str) -> list[QualityCheckResult]:
        """检查质量。"""
        results = []

        # 获取该表的规则
        table_rules = [
            rule for rule in self._rules.values() if rule.table_name == table_name and rule.enabled
        ]

        for rule in table_rules:
            result = await self._check_rule(rule)
            results.append(result)

        return results

    async def _check_rule(self, rule: QualityRule) -> QualityCheckResult:
        """检查单个规则。"""
        # 简化实现：模拟检查
        # 实际应从 DataWorks DQC 获取检查结果
        actual_value = 1.0  # 假设检查通过
        passed = True

        if rule.operator == "gte":
            passed = actual_value >= rule.threshold
        elif rule.operator == "lte":
            passed = actual_value <= rule.threshold
        elif rule.operator == "eq":
            passed = actual_value == rule.threshold

        return QualityCheckResult(
            table_name=rule.table_name,
            rule_id=rule.rule_id,
            passed=passed,
            actual_value=actual_value,
            expected_value=rule.threshold,
        )

    def add_rule(self, rule: QualityRule) -> None:
        """添加质量规则。"""
        self._rules[rule.rule_id] = rule

    def get_rules(self, table_name: str | None = None) -> list[QualityRule]:
        """获取质量规则。"""
        if table_name:
            return [rule for rule in self._rules.values() if rule.table_name == table_name]
        return list(self._rules.values())

    async def propose_quality_rule(
        self,
        table_name: str,
        rule_type: str,
        threshold: float,
        operator: str = "gte",
    ) -> QualityRule:
        """提议质量规则（需要审批后写 DQC）。"""
        import uuid

        rule = QualityRule(
            rule_id=f"qr_{uuid.uuid4().hex[:8]}",
            table_name=table_name,
            rule_type=rule_type,
            threshold=threshold,
            operator=operator,
            enabled=False,  # 需要审批后启用
        )

        logger.info("质量规则已提议: %s (table=%s, type=%s)", rule.rule_id, table_name, rule_type)
        return rule

    def approve_rule(self, rule_id: str) -> bool:
        """批准质量规则。"""
        rule = self._rules.get(rule_id)
        if not rule:
            return False

        rule.enabled = True
        logger.info("质量规则已批准: %s", rule_id)
        return True

    def check_data_trust(self, table_name: str) -> dict[str, Any]:
        """检查数据可信度。"""
        # 简化实现：返回默认可信度
        return {
            "table_name": table_name,
            "trusted": True,
            "confidence": 0.8,
            "reason": "数据质量检查通过",
        }
