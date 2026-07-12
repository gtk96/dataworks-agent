import pytest

from dataworks_agent.agent.nlu.intent_parser import Intent
from dataworks_agent.agent.planner.task_graph import TaskGraph
from dataworks_agent.agent.planner.task_planner import TaskPlan, TaskPlanner


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
    assert len(plan.steps) == 4
    assert plan.steps[0].tool == "create_holo_table"
    assert plan.steps[1].tool == "create_mc_table"
    assert plan.steps[2].tool == "create_node"
    assert plan.steps[3].tool == "push_dml"


def test_plan_query_lineage(planner):
    """测试规划查询血缘任务"""
    intent = Intent(
        action="query_lineage",
        params={"table_name": "ods_user"},
        confidence=0.9,
    )
    plan = planner.plan(intent)

    assert isinstance(plan, TaskPlan)
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "query_lineage"
    assert plan.steps[1].tool == "summarize_lineage_impact"


def test_plan_unknown_intent(planner):
    """测试未知意图返回空计划"""
    intent = Intent(
        action="unknown",
        params={},
        confidence=0.0,
        raw_text="今天天气怎么样",
    )
    plan = planner.plan(intent)

    assert isinstance(plan, TaskPlan)
    assert len(plan.steps) == 0


def test_task_graph_basic():
    """测试 TaskGraph 基本功能"""
    graph = TaskGraph()
    graph.add_node("a")
    graph.add_node("b")
    graph.add_node("c")
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")

    result = graph.topological_sort()
    # 拓扑排序：a 在 b 之前，b 在 c 之前
    assert "a" in result
    assert "b" in result
    assert "c" in result
    assert result.index("a") < result.index("b")
    assert result.index("b") < result.index("c")


def test_task_graph_cycle_detection():
    """测试 TaskGraph 循环检测"""
    graph = TaskGraph()
    graph.add_node("a")
    graph.add_node("b")
    graph.add_edge("a", "b")
    graph.add_edge("b", "a")

    assert graph.validate() is False
    with pytest.raises(ValueError, match="循环依赖"):
        graph.topological_sort()


def test_task_graph_add_edge_auto_create():
    """测试 add_edge 自动创建节点"""
    graph = TaskGraph()
    graph.add_edge("a", "b")  # b 未预先添加

    assert "a" in graph._nodes
    assert "b" in graph._nodes


def test_plan_create_table_dependencies(planner):
    """测试创建表任务的依赖关系"""
    intent = Intent(
        action="create_table",
        params={"table_name": "ods_user", "layer": "ods"},
        confidence=0.9,
    )
    plan = planner.plan(intent)

    # 第一个步骤没有依赖
    assert plan.steps[0].depends_on == []
    # 后续步骤依赖前一个
    assert plan.steps[1].depends_on == ["step_0"]
    assert plan.steps[2].depends_on == ["step_1"]
    assert plan.steps[3].depends_on == ["step_2"]


def test_plan_with_llm_fallback(planner):
    """DataWorks-shaped unknown goals use a deterministic safe fallback plan."""
    intent = Intent(
        action="unknown",
        params={},
        confidence=0.0,
        raw_text="\u5e2e\u6211\u521b\u5efa\u4e00\u4e2a\u7528\u6237\u8868\u5e76\u914d\u7f6e\u6bcf\u5929\u8c03\u5ea6",
    )
    plan = planner.plan(intent)
    assert isinstance(plan, TaskPlan)
    assert len(plan.steps) == 6
    assert plan.summary == "Fallback DataWorks Agent plan"
    assert plan.needs_confirmation is True
    assert plan.steps[0].tool == "analyze_requirement"
