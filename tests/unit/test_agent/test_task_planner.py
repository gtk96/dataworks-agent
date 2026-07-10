import pytest

from dataworks_agent.agent.nlu.intent_parser import Intent
from dataworks_agent.agent.planner.task_planner import TaskPlanner, TaskPlan, TaskStep


@pytest.fixture
def planner():
    return TaskPlanner()


def test_plan_create_table(planner):
    """测试规划创建表任务"""
    intent = Intent(
        action="create_table",
        params={"table_name": "ods_user", "layer": "ods"},
        confidence=0.9,
    )
    plan = planner.plan(intent)

    assert isinstance(plan, TaskPlan)
    assert len(plan.steps) > 0
    assert any(s.tool == "create_holo_table" for s in plan.steps)


def test_plan_query_lineage(planner):
    """测试规划查询血缘任务"""
    intent = Intent(
        action="query_lineage",
        params={"table_name": "ods_user"},
        confidence=0.9,
    )
    plan = planner.plan(intent)

    assert isinstance(plan, TaskPlan)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "query_lineage"
