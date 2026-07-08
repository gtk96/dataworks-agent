"""Evaluator 单元测试 — 可评测与反馈闭环。"""

import pytest

from dataworks_agent.runtime.evaluator import (
    Badcase,
    EvaluationResult,
    Evaluator,
    QualityMetric,
)


@pytest.fixture
def evaluator():
    """创建 Evaluator 实例。"""
    return Evaluator()


def test_record_metric(evaluator):
    """记录质量指标。"""
    metric = evaluator.record_metric("ddl_first_pass_rate", 0.85, "ratio")
    assert metric.metric_name == "ddl_first_pass_rate"
    assert metric.value == 0.85
    assert metric.timestamp != ""


def test_record_badcase(evaluator):
    """记录 Badcase。"""
    badcase = evaluator.record_badcase(
        input_data={"ddl": "CREATE TABLE..."},
        output_data={"validation_passed": False},
        failure_reason="命名不规范",
        run_id="run_001",
        task_id="task_001",
        category="ddl_validation",
    )
    assert badcase.badcase_id.startswith("bc_")
    assert badcase.category == "ddl_validation"


def test_evaluate(evaluator):
    """评测 agent 产出。"""
    outputs = [
        {"type": "ddl", "validation_passed": True, "passed": True},
        {"type": "ddl", "validation_passed": False, "passed": False, "failure_reason": "命名错误"},
        {"type": "semantic", "adopted": True, "passed": True},
    ]

    result = evaluator.evaluate("run_001", "task_001", outputs)

    assert isinstance(result, EvaluationResult)
    assert len(result.metrics) > 0
    assert result.summary["total_outputs"] == 3


def test_evaluate_empty_outputs(evaluator):
    """评测空产出。"""
    result = evaluator.evaluate("run_001", "task_001", [])
    assert result.summary["total_outputs"] == 0


def test_get_metrics_summary(evaluator):
    """获取指标摘要。"""
    evaluator.record_metric("ddl_first_pass_rate", 0.85)
    evaluator.record_metric("ddl_first_pass_rate", 0.90)

    summary = evaluator.get_metrics_summary()
    assert summary["total_metrics"] == 2
    assert "ddl_first_pass_rate" in summary
    assert summary["ddl_first_pass_rate"]["avg"] == 0.875


def test_get_badcases_summary(evaluator):
    """获取 Badcase 摘要。"""
    evaluator.record_badcase(
        input_data={},
        output_data={},
        failure_reason="test",
        category="ddl_validation",
    )
    evaluator.record_badcase(
        input_data={},
        output_data={},
        failure_reason="test",
        category="root_check",
    )

    summary = evaluator.get_badcases_summary()
    assert summary["total_badcases"] == 2
    assert summary["by_category"]["ddl_validation"] == 1
    assert summary["by_category"]["root_check"] == 1


def test_quality_metric_post_init():
    """QualityMetric 初始化。"""
    metric = QualityMetric(metric_name="test", value=0.5)
    assert metric.timestamp != ""


def test_badcase_post_init():
    """Badcase 初始化。"""
    badcase = Badcase(badcase_id="bc_001")
    assert badcase.created_at != ""
