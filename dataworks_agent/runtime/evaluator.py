"""Evaluator — 可评测与反馈闭环。

实现 Requirement 31：
- 记录 agent 产出的质量指标
- Badcase 沉淀 + 归因
- 反馈驱动 prompt/工具/规范迭代
- 评测只用 schema/元数据
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QualityMetric:
    """质量指标。"""

    metric_name: str
    value: float
    unit: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class Badcase:
    """Badcase 记录。"""

    badcase_id: str
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    failure_reason: str = ""
    run_id: str = ""
    task_id: str = ""
    category: str = ""  # ddl_validation / root_check / caliber_mismatch / etc.
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()


@dataclass
class EvaluationResult:
    """评测结果。"""

    evaluation_id: str
    metrics: list[QualityMetric] = field(default_factory=list)
    badcases: list[Badcase] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


class Evaluator:
    """评测器 — 可评测与反馈闭环。

    记录 agent 产出的质量指标，沉淀 badcase 并形成反馈闭环。
    """

    def __init__(self) -> None:
        self._metrics: list[QualityMetric] = []
        self._badcases: list[Badcase] = []

    def record_metric(self, metric_name: str, value: float, unit: str = "") -> QualityMetric:
        """记录质量指标。"""
        metric = QualityMetric(
            metric_name=metric_name,
            value=value,
            unit=unit,
        )
        self._metrics.append(metric)
        logger.info("记录质量指标: %s = %.2f %s", metric_name, value, unit)
        return metric

    def record_badcase(
        self,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        failure_reason: str,
        run_id: str = "",
        task_id: str = "",
        category: str = "",
    ) -> Badcase:
        """记录 Badcase。"""
        import uuid

        badcase = Badcase(
            badcase_id=f"bc_{uuid.uuid4().hex[:8]}",
            input_data=input_data,
            output_data=output_data,
            failure_reason=failure_reason,
            run_id=run_id,
            task_id=task_id,
            category=category,
        )
        self._badcases.append(badcase)
        logger.info("记录 Badcase: %s (category=%s)", badcase.badcase_id, category)
        return badcase

    def evaluate(
        self,
        run_id: str,
        task_id: str,
        outputs: list[dict[str, Any]],
    ) -> EvaluationResult:
        """评测 agent 产出。"""
        import uuid

        evaluation_id = f"eval_{uuid.uuid4().hex[:8]}"

        # 计算质量指标
        metrics = self._calculate_metrics(outputs)

        # 识别 badcases
        badcases = self._identify_badcases(run_id, task_id, outputs)

        # 生成建议
        recommendations = self._generate_recommendations(metrics, badcases)

        return EvaluationResult(
            evaluation_id=evaluation_id,
            metrics=metrics,
            badcases=badcases,
            summary={
                "total_outputs": len(outputs),
                "total_badcases": len(badcases),
                "pass_rate": self._calculate_pass_rate(outputs),
            },
            recommendations=recommendations,
        )

    def _calculate_metrics(self, outputs: list[dict[str, Any]]) -> list[QualityMetric]:
        """计算质量指标。"""
        metrics = []

        # DDL 一次过校验率
        ddl_outputs = [o for o in outputs if o.get("type") == "ddl"]
        if ddl_outputs:
            passed = sum(1 for o in ddl_outputs if o.get("validation_passed", False))
            pass_rate = passed / len(ddl_outputs) if ddl_outputs else 0
            metrics.append(
                QualityMetric(
                    metric_name="ddl_first_pass_rate",
                    value=pass_rate,
                    unit="ratio",
                )
            )

        # 语义采纳率
        semantic_outputs = [o for o in outputs if o.get("type") == "semantic"]
        if semantic_outputs:
            adopted = sum(1 for o in semantic_outputs if o.get("adopted", False))
            adoption_rate = adopted / len(semantic_outputs) if semantic_outputs else 0
            metrics.append(
                QualityMetric(
                    metric_name="semantic_adoption_rate",
                    value=adoption_rate,
                    unit="ratio",
                )
            )

        # 查询口径命中率
        query_outputs = [o for o in outputs if o.get("type") == "query"]
        if query_outputs:
            hit = sum(1 for o in query_outputs if o.get("caliber_hit", False))
            hit_rate = hit / len(query_outputs) if query_outputs else 0
            metrics.append(
                QualityMetric(
                    metric_name="query_caliber_hit_rate",
                    value=hit_rate,
                    unit="ratio",
                )
            )

        return metrics

    def _identify_badcases(
        self,
        run_id: str,
        task_id: str,
        outputs: list[dict[str, Any]],
    ) -> list[Badcase]:
        """识别 Badcase。"""
        badcases = []

        for output in outputs:
            if output.get("validation_failed") or output.get("rejected"):
                badcase = self.record_badcase(
                    input_data=output.get("input", {}),
                    output_data=output,
                    failure_reason=output.get("failure_reason", "未知原因"),
                    run_id=run_id,
                    task_id=task_id,
                    category=output.get("category", "unknown"),
                )
                badcases.append(badcase)

        return badcases

    def _calculate_pass_rate(self, outputs: list[dict[str, Any]]) -> float:
        """计算通过率。"""
        if not outputs:
            return 0.0

        passed = sum(1 for o in outputs if o.get("passed", False))
        return passed / len(outputs)

    def _generate_recommendations(
        self,
        metrics: list[QualityMetric],
        badcases: list[Badcase],
    ) -> list[str]:
        """生成改进建议。"""
        recommendations = []

        # 基于指标生成建议
        for metric in metrics:
            if metric.metric_name == "ddl_first_pass_rate" and metric.value < 0.8:
                recommendations.append("DDL 一次过校验率较低，建议优化 DDL 生成规则")
            elif metric.metric_name == "semantic_adoption_rate" and metric.value < 0.5:
                recommendations.append("语义采纳率较低，建议优化语义候选生成")
            elif metric.metric_name == "query_caliber_hit_rate" and metric.value < 0.7:
                recommendations.append("查询口径命中率较低，建议完善语义层定义")

        # 基于 badcases 生成建议
        category_counts = {}
        for badcase in badcases:
            category_counts[badcase.category] = category_counts.get(badcase.category, 0) + 1

        for category, count in category_counts.items():
            if count >= 3:
                recommendations.append(f"Badcase 类别 '{category}' 出现 {count} 次，建议系统性改进")

        return recommendations

    def get_metrics_summary(self) -> dict[str, Any]:
        """获取指标摘要。"""
        if not self._metrics:
            return {"total_metrics": 0}

        metric_values = {}
        for metric in self._metrics:
            if metric.metric_name not in metric_values:
                metric_values[metric.metric_name] = []
            metric_values[metric.metric_name].append(metric.value)

        summary = {"total_metrics": len(self._metrics)}
        for name, values in metric_values.items():
            summary[name] = {
                "count": len(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
            }

        return summary

    def get_badcases_summary(self) -> dict[str, Any]:
        """获取 Badcase 摘要。"""
        if not self._badcases:
            return {"total_badcases": 0}

        category_counts = {}
        for badcase in self._badcases:
            category_counts[badcase.category] = category_counts.get(badcase.category, 0) + 1

        return {
            "total_badcases": len(self._badcases),
            "by_category": category_counts,
        }
