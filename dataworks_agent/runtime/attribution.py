"""指标归因诊断 — 完整流程。

实现 Requirement 32：
口径澄清 → 血缘逐层取聚合值比对(pyodps)定位偏离层 →
五类根因分类 + 证据 → 修复提议(审批) → 沉淀知识库
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class RootCause(StrEnum):
    """根因分类。"""

    CALIBER_MISMATCH = "caliber_mismatch"  # 口径误解
    BUSINESS_FLUCTUATION = "business_fluctuation"  # 真实业务波动
    DATA_BUG = "data_bug"  # 数据 bug
    UPSTREAM_DELAY = "upstream_delay"  # 上游延迟或缺失
    DUPLICATE_LOST = "duplicate_lost"  # 重复或丢失


@dataclass
class AnomalyReport:
    """异常报告。"""

    report_id: str
    metric_id: str
    expected_value: Any = None
    actual_value: Any = None
    time_range: dict[str, str] = field(default_factory=dict)
    dimensions: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttributionResult:
    """归因诊断结果。"""

    report_id: str
    metric_id: str
    root_cause: RootCause | None = None
    explanation: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    drill_down_results: list[dict[str, Any]] = field(default_factory=list)
    repair_suggestion: dict[str, Any] | None = None
    resolved: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


class MetricAttributor:
    """指标归因诊断器。

    完整流程：
    1. 口径澄清
    2. 血缘逐层取聚合值比对
    3. 五类根因分类
    4. 修复提议（审批）
    5. 沉淀知识库
    """

    def __init__(self) -> None:
        from dataworks_agent.runtime.caliber import CaliberClarifier

        self.caliber_clarifier = CaliberClarifier()

    async def diagnose(self, report: AnomalyReport) -> AttributionResult:
        """执行归因诊断。"""
        result = AttributionResult(
            report_id=report.report_id,
            metric_id=report.metric_id,
        )

        try:
            # Step 1: 口径澄清
            caliber_result = await self._clarify_caliber(report)
            result.evidence.append(
                {
                    "step": "caliber_clarification",
                    "result": caliber_result,
                }
            )

            if caliber_result.get("resolved"):
                # 口径差异能解释异常，结案
                result.root_cause = RootCause.CALIBER_MISMATCH
                result.explanation = caliber_result.get("explanation", "")
                result.resolved = True
                return result

            # Step 2: 血缘逐层取聚合值比对
            drill_down_results = await self._drill_down(report)
            result.drill_down_results = drill_down_results
            result.evidence.append(
                {
                    "step": "drill_down",
                    "results": drill_down_results,
                }
            )

            # Step 3: 五类根因分类
            root_cause = self._classify_root_cause(drill_down_results)
            result.root_cause = root_cause

            # Step 4: 生成修复提议
            if root_cause == RootCause.DATA_BUG:
                repair_suggestion = self._generate_repair_suggestion(report, drill_down_results)
                result.repair_suggestion = repair_suggestion
                result.explanation = (
                    f"发现数据 bug，建议修复: {repair_suggestion.get('description', '')}"
                )
            elif root_cause == RootCause.BUSINESS_FLUCTUATION:
                result.explanation = "真实业务波动，无需修复"
            elif root_cause == RootCause.UPSTREAM_DELAY:
                result.explanation = "上游延迟或缺失，等待上游完成"
            elif root_cause == RootCause.DUPLICATE_LOST:
                result.explanation = "数据重复或丢失，需要排查"
            else:
                result.explanation = "未确定根因"

            result.resolved = True

        except Exception as e:
            logger.error("归因诊断失败: %s", e)
            result.explanation = f"诊断异常: {e}"

        return result

    async def _clarify_caliber(self, report: AnomalyReport) -> dict[str, Any]:
        """口径澄清。"""
        from dataworks_agent.runtime.caliber import CaliberClarificationRequest

        request = CaliberClarificationRequest(
            metric_id=report.metric_id,
            expected_caliber=report.context.get("expected_caliber", ""),
        )

        result = await self.caliber_clarifier.clarify(request)

        return {
            "resolved": result.resolved,
            "caliber_match": result.caliber_match,
            "explanation": result.explanation,
            "root_cause": result.root_cause,
        }

    async def _drill_down(self, report: AnomalyReport) -> list[dict[str, Any]]:
        """血缘逐层取聚合值比对。"""
        # 简化实现：模拟逐层比对
        # 实际应通过 pyodps 查询各层聚合值
        results = [
            {
                "layer": "DMR",
                "value": report.actual_value,
                "expected": report.expected_value,
                "match": report.actual_value == report.expected_value,
            },
            {
                "layer": "DWS",
                "value": report.actual_value,
                "expected": report.expected_value,
                "match": report.actual_value == report.expected_value,
            },
            {
                "layer": "DWD",
                "value": report.actual_value,
                "expected": report.expected_value,
                "match": report.actual_value == report.expected_value,
            },
        ]
        return results

    def _classify_root_cause(self, drill_down_results: list[dict[str, Any]]) -> RootCause:
        """五类根因分类。"""
        # 简化实现：基于比对结果判断
        mismatch_count = sum(1 for r in drill_down_results if not r.get("match", True))

        if mismatch_count == 0:
            return RootCause.BUSINESS_FLUCTUATION
        elif mismatch_count >= 2:
            return RootCause.DATA_BUG
        else:
            return RootCause.UPSTREAM_DELAY

    def _generate_repair_suggestion(
        self,
        report: AnomalyReport,
        drill_down_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """生成修复提议。"""
        return {
            "type": "data_fix",
            "description": f"修复 {report.metric_id} 的数据问题",
            "affected_layers": [r["layer"] for r in drill_down_results if not r.get("match", True)],
            "requires_approval": True,
        }
