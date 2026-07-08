"""Coordinator 单元测试 — 多专业 agent 协调器。"""

import pytest

from dataworks_agent.runtime.coordinator import (
    AgentType,
    CoordinationResult,
    Coordinator,
    SubTask,
    TaskStatus,
)


@pytest.fixture
def coordinator():
    """创建 Coordinator 实例。"""
    return Coordinator()


@pytest.mark.asyncio
async def test_coordinate_modeling(coordinator):
    """协调建模任务。"""
    result = await coordinator.coordinate(
        goal="创建一个 DWD 表",
        context={
            "source_table": "ods_ord_order_hour",
            "target_layer": "DWD",
        },
    )

    assert isinstance(result, CoordinationResult)
    assert result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
    assert len(result.sub_tasks) > 0


@pytest.mark.asyncio
async def test_coordinate_diagnosis(coordinator):
    """协调诊断任务。"""
    result = await coordinator.coordinate(
        goal="诊断订单数量异常",
        context={"metric_id": "order_count"},
    )

    assert isinstance(result, CoordinationResult)
    assert len(result.sub_tasks) > 0


@pytest.mark.asyncio
async def test_coordinate_query(coordinator):
    """协调查询任务。"""
    result = await coordinator.coordinate(
        goal="查询订单数量",
        context={"sql": "SELECT COUNT(*) FROM orders"},
    )

    assert isinstance(result, CoordinationResult)
    assert len(result.sub_tasks) > 0


def test_decompose_task_modeling(coordinator):
    """分解建模任务。"""
    sub_tasks = coordinator._decompose_task("创建一个 DWD 表", {})
    assert len(sub_tasks) >= 2
    assert sub_tasks[0].agent_type == AgentType.REQUIREMENT
    assert sub_tasks[1].agent_type == AgentType.MODELING


def test_decompose_task_diagnosis(coordinator):
    """分解诊断任务。"""
    sub_tasks = coordinator._decompose_task("诊断异常", {})
    assert len(sub_tasks) == 1
    assert sub_tasks[0].agent_type == AgentType.DIAGNOSIS


def test_sub_task_post_init():
    """SubTask 初始化。"""
    task = SubTask(
        task_id="task_001",
        agent_type=AgentType.MODELING,
        description="test",
    )
    assert task.created_at != ""
    assert task.status == TaskStatus.PENDING


def test_coordination_result_post_init():
    """CoordinationResult 初始化。"""
    result = CoordinationResult(
        task_id="coord_001",
        status=TaskStatus.RUNNING,
    )
    assert result.task_id == "coord_001"
    assert result.sub_tasks == []
