"""FineReport_Adapter — 帆软报表接入。

实现 Requirement 35：
- 从报表上下文发起诊断，口径以语义层为准
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FineReportContext:
    """帆软报表上下文。"""

    report_id: str
    report_name: str = ""
    metric_id: str = ""
    dimensions: dict[str, str] = field(default_factory=dict)
    time_range: dict[str, str] = field(default_factory=dict)
    user_id: str = ""


@dataclass
class FineReportResponse:
    """帆软报表响应。"""

    report_id: str
    diagnosis_result: dict[str, Any] = field(default_factory=dict)
    caliber_info: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class FineReportAdapter:
    """帆软报表接入适配器。

    从报表上下文发起诊断，口径以语义层为准。
    """

    async def handle_report_context(self, context: FineReportContext) -> FineReportResponse:
        """处理报表上下文。"""
        try:
            # 1. 获取指标口径
            caliber_info = await self._get_caliber_info(context.metric_id)

            # 2. 执行归因诊断
            diagnosis_result = await self._diagnose(context)

            return FineReportResponse(
                report_id=context.report_id,
                diagnosis_result=diagnosis_result,
                caliber_info=caliber_info,
            )
        except Exception as e:
            logger.error("帆软报表处理失败: %s", e)
            return FineReportResponse(
                report_id=context.report_id,
                error=str(e),
            )

    async def _get_caliber_info(self, metric_id: str) -> dict[str, Any]:
        """获取口径信息。"""
        from dataworks_agent.semantic.layer import SemanticLayer

        layer = SemanticLayer()
        definition = layer.get_metric_definition(metric_id)

        if definition:
            return {
                "metric_id": definition.key,
                "caliber": definition.body.get("caliber", ""),
                "version": definition.version,
            }
        return {"metric_id": metric_id, "caliber": "", "version": 0}

    async def _diagnose(self, context: FineReportContext) -> dict[str, Any]:
        """执行归因诊断。"""
        from dataworks_agent.runtime.attribution import AnomalyReport, MetricAttributor

        report = AnomalyReport(
            report_id=f"fr_{context.report_id}",
            metric_id=context.metric_id,
            context={
                "user_id": context.user_id,
                "dimensions": context.dimensions,
                "time_range": context.time_range,
            },
        )

        attributor = MetricAttributor()
        result = await attributor.diagnose(report)

        return {
            "root_cause": result.root_cause.value if result.root_cause else None,
            "explanation": result.explanation,
            "resolved": result.resolved,
        }
