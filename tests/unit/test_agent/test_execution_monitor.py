import pytest

from dataworks_agent.agent.monitor.execution_monitor import ExecutionMonitor


@pytest.fixture
def monitor():
    return ExecutionMonitor()


def test_record_step_start(monitor):
    """测试记录步骤开始"""
    monitor.record_step_start("task_1", "step_0", "create_table")
    status = monitor.get_status("task_1")
    assert status is not None
    assert status.current_step == "step_0"
    assert "step_0" in status.steps
    assert status.steps["step_0"].status == "running"


def test_record_step_complete(monitor):
    """测试记录步骤完成"""
    monitor.record_step_start("task_1", "step_0", "create_table")
    monitor.record_step_complete("task_1", "step_0", success=True)
    status = monitor.get_status("task_1")
    assert status.completed_steps == 1
    assert status.steps["step_0"].status == "completed"


def test_record_step_failure(monitor):
    """测试记录步骤失败"""
    monitor.record_step_start("task_1", "step_0", "create_table")
    monitor.record_step_complete("task_1", "step_0", success=False, error="连接超时")
    status = monitor.get_status("task_1")
    assert status.failed_steps == 1
    assert status.steps["step_0"].status == "failed"
    assert status.steps["step_0"].error == "连接超时"


def test_complete_task(monitor):
    """测试标记任务完成"""
    monitor.record_step_start("task_1", "step_0", "create_table")
    monitor.record_step_complete("task_1", "step_0", success=True)
    monitor.complete_task("task_1")
    status = monitor.get_status("task_1")
    assert status.end_time is not None
    assert status.current_step is None


def test_multiple_steps(monitor):
    """测试多个步骤"""
    monitor.record_step_start("task_1", "step_0", "create_holo_table")
    monitor.record_step_complete("task_1", "step_0", success=True)

    monitor.record_step_start("task_1", "step_1", "create_mc_table")
    monitor.record_step_complete("task_1", "step_1", success=True)

    status = monitor.get_status("task_1")
    assert status.completed_steps == 2
    assert len(status.steps) == 2
