import pytest

from dataworks_agent.agent.planner.task_decomposer import TaskDecomposer


@pytest.fixture
def decomposer():
    return TaskDecomposer()


def test_decompose_simple_task(decomposer):
    """测试简单任务拆解"""
    result = decomposer.decompose("创建ods_user表")
    assert len(result.steps) == 1
    assert result.steps[0].tool == "unknown"
    assert result.original_task == "创建ods_user表"


def test_decompose_complex_task(decomposer):
    """测试复杂任务拆解"""
    result = decomposer.decompose("创建ods_user表并配置调度")
    assert len(result.steps) == 2
    assert result.steps[0].tool == "create_table"
    assert result.steps[1].tool == "configure_schedule"
    assert result.steps[1].depends_on == ["step_0"]


def test_decompose_complex_task_with_dependency(decomposer):
    """测试带依赖的复杂任务拆解"""
    result = decomposer.decompose("创建ods_user表并设置依赖")
    assert len(result.steps) == 2
    assert result.steps[0].tool == "create_table"
    assert result.steps[1].tool == "add_dependency"


def test_decompose_update_and_deploy(decomposer):
    """测试更新并部署任务"""
    result = decomposer.decompose("更新dwd_order表并重新部署")
    assert len(result.steps) == 2
    assert result.steps[0].tool == "update_table"
    assert result.steps[1].tool == "deploy_node"