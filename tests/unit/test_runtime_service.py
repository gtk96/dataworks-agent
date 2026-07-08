"""RuntimeService 单元测试 — Agent Runtime 生命周期。"""

import pytest

from dataworks_agent.runtime.service import RuntimeService
from dataworks_agent.runtime.session import (
    Event,
    EventType,
    RunStatus,
)


@pytest.fixture
def service():
    """创建 RuntimeService 实例。"""
    return RuntimeService()


@pytest.mark.asyncio
async def test_create_session(service):
    """创建会话。"""
    session = service.create_session(task_id="task_001", task_type="modeling")
    assert session.session_id.startswith("sess_")
    assert session.task_id == "task_001"
    assert session.task_type == "modeling"


@pytest.mark.asyncio
async def test_start_run(service):
    """启动运行。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={"action": "create_table", "table_name": "dwd_test"},
        actor="test_user",
    )

    assert run.run_id.startswith("run_")
    assert run.session_id == session.session_id
    assert run.status == RunStatus.RUNNING


@pytest.mark.asyncio
async def test_get_run(service):
    """获取运行状态。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={},
    )

    retrieved = await service.get_run(run.run_id)
    assert retrieved is not None
    assert retrieved.run_id == run.run_id


@pytest.mark.asyncio
async def test_cancel_run(service):
    """取消运行。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={},
    )

    result = await service.cancel_run(run.run_id)
    assert result is True

    retrieved = await service.get_run(run.run_id)
    assert retrieved.status == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_interrupt_run(service):
    """中断运行。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={},
    )

    result = await service.interrupt_run(run.run_id, {"reason": "needs_approval"})
    assert result is True

    retrieved = await service.get_run(run.run_id)
    assert retrieved.status == RunStatus.SUSPENDED


@pytest.mark.asyncio
async def test_resume_run(service):
    """恢复运行。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={},
    )

    # 先中断
    await service.interrupt_run(run.run_id, {"reason": "needs_approval"})

    # 恢复
    result = await service.resume_run(run.run_id, {"approved": True})
    assert result is True

    retrieved = await service.get_run(run.run_id)
    assert retrieved.status == RunStatus.RUNNING


@pytest.mark.asyncio
async def test_retry_run(service):
    """重试运行。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={},
    )

    # 先失败
    await service.fail_run(run.run_id, "test error")

    # 重试
    result = await service.retry_run(run.run_id)
    assert result is True

    retrieved = await service.get_run(run.run_id)
    assert retrieved.status == RunStatus.RUNNING


@pytest.mark.asyncio
async def test_complete_run(service):
    """完成运行。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={},
    )

    result = await service.complete_run(run.run_id, {"status": "success"})
    assert result is True

    retrieved = await service.get_run(run.run_id)
    assert retrieved.status == RunStatus.COMPLETED
    assert retrieved.result == {"status": "success"}


@pytest.mark.asyncio
async def test_fail_run(service):
    """失败运行。"""
    session = service.create_session(task_id="task_001")
    run = await service.start_run(
        session_id=session.session_id,
        request={},
    )

    result = await service.fail_run(run.run_id, "connection timeout")
    assert result is True

    retrieved = await service.get_run(run.run_id)
    assert retrieved.status == RunStatus.FAILED
    assert retrieved.error == "connection timeout"


def test_session_post_init():
    """Session 初始化。"""
    from dataworks_agent.runtime.session import Session

    session = Session(session_id="test", task_id="task_001", task_type="modeling")
    assert session.created_at != ""
    assert session.updated_at != ""


def test_run_post_init():
    """Run 初始化。"""
    from dataworks_agent.runtime.session import Run

    run = Run(run_id="", session_id="sess_001")
    assert run.run_id.startswith("run_")
    assert run.started_at != ""


def test_step_post_init():
    """Step 初始化。"""
    from dataworks_agent.runtime.session import Step

    step = Step(step_id="", run_id="run_001", step_name="test_step")
    assert step.step_id.startswith("step_")
    assert step.span_id.startswith("span_")


def test_event_post_init():
    """Event 初始化。"""

    event = Event(event_id="", run_id="run_001", event_type=EventType.STEP_START)
    assert event.event_id.startswith("evt_")
    assert event.timestamp != ""


def test_artifact_post_init():
    """Artifact 初始化。"""
    from dataworks_agent.runtime.session import Artifact

    artifact = Artifact(artifact_id="", run_id="run_001", artifact_type="ddl", name="test")
    assert artifact.artifact_id.startswith("art_")
    assert artifact.created_at != ""


def test_checkpoint_post_init():
    """Checkpoint 初始化。"""
    from dataworks_agent.runtime.session import Checkpoint

    checkpoint = Checkpoint(checkpoint_id="", run_id="run_001", step_index=0)
    assert checkpoint.checkpoint_id.startswith("ckpt_")
    assert checkpoint.created_at != ""
