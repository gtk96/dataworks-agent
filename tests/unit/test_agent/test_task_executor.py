import pytest
from dataworks_agent.agent.planner.task_planner import TaskPlan, TaskStep
from dataworks_agent.agent.executor.task_executor import TaskExecutor, ExecutionResult

@pytest.fixture
def executor():
    return TaskExecutor()

def test_execute_simple_plan(executor):
    """测试执行简单计划"""
    plan = TaskPlan(
        task_id="test_task",
        steps=[
            TaskStep(step_id="step_0", tool="query_lineage", params={"table_name": "ods_user"}),
        ],
    )
    result = executor.execute(plan)
    
    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert len(result.step_results) == 1

def test_execute_plan_with_dependency(executor):
    """测试执行有依赖的计划"""
    plan = TaskPlan(
        task_id="test_task",
        steps=[
            TaskStep(step_id="step_0", tool="create_holo_table", params={"table_name": "test"}),
            TaskStep(step_id="step_1", tool="push_dml", params={"table_name": "test"}, depends_on=["step_0"]),
        ],
    )
    result = executor.execute(plan)
    
    assert isinstance(result, ExecutionResult)
    assert result.success is True