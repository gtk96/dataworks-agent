"""口径澄清 — 指标归因第一步。

实现 Requirement 32：口径澄清，业务预期 vs 实际口径比对。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CaliberClarificationRequest:
    """口径澄清请求。"""

    metric_id: str
    expected_caliber: str  # 业务预期口径
    actual_value: Any = None
    expected_value: Any = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaliberClarificationResult:
    """口径澄清结果。"""

    metric_id: str
    resolved: bool
    caliber_match: bool  # 口径是否一致
    expected_caliber: str = ""
    actual_caliber: str = ""
    explanation: str = ""
    root_cause: str = (
        ""  # caliber_mismatch / data_bug / business_fluctuation / upstream_delay / duplicate_lost
    )
    evidence: list[dict[str, Any]] = field(default_factory=list)
    needs_drill_down: bool = False


class CaliberClarifier:
    """口径澄清器。

    指标归因诊断的第一步：业务预期 vs 实际口径比对。
    如果口径差异能解释异常，则结案；否则进入数据下钻。
    """

    def __init__(self) -> None:
        from dataworks_agent.semantic.layer import SemanticLayer

        self._semantic_layer = SemanticLayer()

    async def clarify(
        self,
        request: CaliberClarificationRequest,
    ) -> CaliberClarificationResult:
        """执行口径澄清。"""
        result = CaliberClarificationResult(
            metric_id=request.metric_id,
            resolved=False,
            caliber_match=False,
        )

        try:
            # 1. 从语义层获取实际口径
            definition = self._semantic_layer.get_metric_definition(request.metric_id)
            if definition:
                actual_caliber = definition.body.get("caliber", "")
                result.actual_caliber = actual_caliber
                result.expected_caliber = request.expected_caliber

                # 2. 比对口径
                caliber_match = self._compare_calibers(
                    request.expected_caliber,
                    actual_caliber,
                )
                result.caliber_match = caliber_match

                if caliber_match:
                    # 口径一致，需要数据下钻
                    result.root_cause = "caliber_match_needs_drill_down"
                    result.explanation = "业务预期口径与实际口径一致，需要进一步数据下钻"
                    result.needs_drill_down = True
                else:
                    # 口径不一致，可能是口径误解
                    result.root_cause = "caliber_mismatch"
                    result.explanation = f"业务预期口径与实际口径不一致。预期: {request.expected_caliber}, 实际: {actual_caliber}"
                    result.resolved = True
            else:
                # 未找到指标定义
                result.root_cause = "metric_not_found"
                result.explanation = f"未找到指标 {request.metric_id} 的定义"
                result.needs_drill_down = True

            # 3. 记录证据
            result.evidence.append(
                {
                    "type": "caliber_comparison",
                    "metric_id": request.metric_id,
                    "expected": request.expected_caliber,
                    "actual": result.actual_caliber,
                    "match": result.caliber_match,
                }
            )

        except Exception as e:
            logger.error("口径澄清失败: %s", e)
            result.root_cause = "error"
            result.explanation = str(e)

        return result

    def _compare_calibers(self, expected: str, actual: str) -> bool:
        """比对口径。

        简化实现：直接字符串比较。
        实际应该进行语义比对。
        """
        if not expected or not actual:
            return True  # 未提供口径时默认一致

        # 标准化后比较
        expected_normalized = expected.strip().lower()
        actual_normalized = actual.strip().lower()

        return expected_normalized == actual_normalized

    async def clarify_batch(
        self,
        requests: list[CaliberClarificationRequest],
    ) -> list[CaliberClarificationResult]:
        """批量口径澄清。"""
        results = []
        for request in requests:
            result = await self.clarify(request)
            results.append(result)
        return results
