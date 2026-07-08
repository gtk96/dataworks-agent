"""Orchestrator 单元测试 — Loop Engineering 总指挥。"""

import pytest

from dataworks_agent.runtime.orchestrator import (
    Orchestrator,
    OrchestratorResult,
    OrchestratorStatus,
    SubTask,
    TaskStatus,
)


@pytest.fixture
def orchestrator():
    """创建 Orchestrator 实例。"""
    return Orchestrator()


@pytest.mark.asyncio
async def test_orchestrator_idle(orchestrator):
    """Orchestrator 初始状态。"""
    assert orchestrator.status == OrchestratorStatus.IDLE


@pytest.mark.asyncio
async def test_orchestrator_run_simple(orchestrator):
    """Orchestrator 简单执行。"""

    # 注册 mock 执行器
    async def mock_executor(task: SubTask) -> dict:
        return {"success": True}

    orchestrator.register_executor("ods_node_create", mock_executor)
    orchestrator.register_executor("ods_dml_push", mock_executor)

    result = await orchestrator.run(
        goal="创建 ODS 节点",
        context={"task_type": "ODS"},
    )

    assert result.status == OrchestratorStatus.COMPLETED
    assert len(result.sub_tasks) > 0
    assert len(result.decisions) > 0


@pytest.mark.asyncio
async def test_orchestrator_run_with_failure(orchestrator):
    """Orchestrator 执行有失败。"""

    # 注册 mock 执行器（一个成功，一个失败）
    async def success_executor(task: SubTask) -> dict:
        return {"success": True}

    async def fail_executor(task: SubTask) -> dict:
        raise RuntimeError("执行失败")

    orchestrator.register_executor("ods_node_create", success_executor)
    orchestrator.register_executor("ods_dml_push", fail_executor)

    result = await orchestrator.run(
        goal="创建 ODS 节点",
        context={"task_type": "ODS"},
    )

    assert result.status == OrchestratorStatus.FAILED
    assert "失败" in result.summary


@pytest.mark.asyncio
async def test_orchestrator_decompose_goal_ods(orchestrator):
    """分解 ODS 目标。"""
    sub_tasks = orchestrator._decompose_goal("创建 ODS 节点", {"task_type": "ODS"})

    assert len(sub_tasks) >= 2
    task_types = [t.task_type for t in sub_tasks]
    assert "ods_node_create" in task_types
    assert "ods_dml_push" in task_types


@pytest.mark.asyncio
async def test_orchestrator_decompose_goal_dwd(orchestrator):
    """分解 DWD 目标。"""
    sub_tasks = orchestrator._decompose_goal("创建 DWD 节点", {"task_type": "DWD"})

    assert len(sub_tasks) >= 3
    task_types = [t.task_type for t in sub_tasks]
    assert "dwd_node_create" in task_types
    assert "dwd_dml_push" in task_types
    assert "dwd_dependency_config" in task_types


@pytest.mark.asyncio
async def test_orchestrator_decompose_goal_dim(orchestrator):
    """分解 DIM 目标。"""
    sub_tasks = orchestrator._decompose_goal("创建 DIM 节点", {"task_type": "DIM"})

    assert len(sub_tasks) >= 2
    task_types = [t.task_type for t in sub_tasks]
    assert "dim_node_create" in task_types
    assert "dim_dml_push" in task_types


def test_has_dependency(orchestrator):
    """检查任务依赖。"""
    all_tasks = [
        SubTask(task_id="t1", task_type="ods_node_create", description="创建节点"),
        SubTask(task_id="t2", task_type="ods_dml_push", description="推送 DML"),
    ]

    # DML 依赖节点创建
    assert orchestrator._has_dependency(all_tasks[1], all_tasks) is True

    # 节点创建无依赖
    assert orchestrator._has_dependency(all_tasks[0], all_tasks) is False


def test_generate_next_steps(orchestrator):
    """生成下一步建议。"""
    completed_tasks = [
        SubTask(
            task_id="t1",
            task_type="ods_node_create",
            description="创建节点",
            status=TaskStatus.COMPLETED,
        ),
        SubTask(
            task_id="t2",
            task_type="ods_dml_push",
            description="推送 DML",
            status=TaskStatus.COMPLETED,
        ),
    ]

    next_steps = orchestrator._generate_next_steps("创建 ODS 节点", completed_tasks)

    assert len(next_steps) > 0
    step_types = [s.step_type for s in next_steps]
    assert "verification" in step_types


def test_orchestrator_result_summary():
    """OrchestratorResult 摘要。"""
    result = OrchestratorResult(
        goal="测试目标",
        status=OrchestratorStatus.COMPLETED,
        summary="目标完成",
    )

    assert result.goal == "测试目标"
    assert result.status == OrchestratorStatus.COMPLETED
    assert result.summary == "目标完成"
