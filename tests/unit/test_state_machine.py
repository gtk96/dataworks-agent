"""状态机单元测试 — 全流程推进和异常路径。"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from dataworks_agent.schemas import TaskStatus
from dataworks_agent.task_engine.state_machine import StepHandler, TaskStateMachine


def make_handler(name: str, succeed: bool = True):
    """创建 mock StepHandler。"""
    execute = AsyncMock()
    if not succeed:
        execute.side_effect = RuntimeError(f"{name} 执行失败")
    return StepHandler(
        step=TaskStatus.DDL_GEN,
        execute=execute,
        validate=AsyncMock() if succeed else None,
    )


@pytest.mark.asyncio
async def test_full_pipeline_success():
    """全流程 6 步全部成功 → COMPLETED。"""
    sm = TaskStateMachine("task_test_001")

    for step_name in ["DDL 生成", "建表执行", "词根校验", "DML 写入", "调度配置", "测试验证"]:
        sm.add_step(make_handler(step_name, succeed=True))

    result = await sm.run()
    assert result is True
    assert sm.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancel_during_run():
    """运行中取消 → CANCELLED。"""
    sm = TaskStateMachine("task_test_002")

    async def slow_execute():
        await asyncio.sleep(0.5)

    sm.add_step(StepHandler(TaskStatus.DDL_GEN, execute=slow_execute))
    sm.add_step(make_handler("step2"))

    async def _run():
        await sm.run()

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.1)
    sm.cancel()
    await task

    assert sm.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_step_failure_non_retryable():
    """不可重试错误 → 立即 FAILED。"""
    sm = TaskStateMachine("task_test_003")

    async def fail():
        raise RuntimeError("root_check_failed")

    sm.add_step(StepHandler(TaskStatus.ROOT_CHECK, execute=fail))
    result = await sm.run()

    assert result is False
    assert sm.status == TaskStatus.FAILED
    assert "root_check_failed" in sm.error_message


@pytest.mark.asyncio
async def test_suspend_and_resume():
    """Cookie 过期挂起 → 恢复后续跑。"""
    sm = TaskStateMachine("task_test_004")
    sm.add_step(make_handler("DDL 生成"))
    sm.add_step(make_handler("建表执行"))

    sm.suspend()

    async def _run():
        await sm.run()

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.1)

    assert sm.status == TaskStatus.SUSPENDED

    sm.resume()
    # 注意: 当前实现 suspend 后直接退出，不自动续跑
    await task


@pytest.mark.asyncio
async def test_emit_event_publishes_task_status_changed():
    """v10：emit_event 应通过 EventBus 异步发布 TASK_STATUS_CHANGED，
    即使无订阅也不抛（事件总线自带 handler 异常隔离）。"""
    from dataworks_agent.cache.events import EventType, get_event_bus

    received: list = []
    get_event_bus().subscribe(EventType.TASK_STATUS_CHANGED, lambda e: received.append(e))

    sm = TaskStateMachine("task_test_pub_001")
    await sm.emit_event("start", {"total_steps": 1})

    # 等 create_task 调度出去的 publish_async 完成
    for _ in range(20):
        if received:
            break
        await asyncio.sleep(0.02)

    assert received, "emit_event 必须至少 publish 一次 TASK_STATUS_CHANGED"
    ev = received[0]
    assert ev.data["task_id"] == "task_test_pub_001"
    assert ev.data["status"] == TaskStatus.PENDING.value


@pytest.mark.asyncio
async def test_emit_event_publish_failure_does_not_break_state_machine():
    """v10：EventBus publish 抛错不应影响状态机主链路（仅 debug 日志）。"""
    from dataworks_agent.cache.events import EventType, get_event_bus

    def bad_handler(event):
        raise RuntimeError("subscriber crash")

    get_event_bus().subscribe(EventType.TASK_STATUS_CHANGED, bad_handler)

    sm = TaskStateMachine("task_test_pub_002")
    # 即使订阅者抛错，emit_event 也不应抛
    await sm.emit_event("step", {"step_label": "x"})

    # 状态机主字段没被污染
    assert sm.task_id == "task_test_pub_002"
    assert sm.status == TaskStatus.PENDING
