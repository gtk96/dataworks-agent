"""ReplayManager 单元测试 — 无状态重放续跑。"""

import pytest

from dataworks_agent.runtime.replay import ReplayManager, ReplayState


@pytest.fixture
def manager():
    """创建 ReplayManager 实例。"""
    return ReplayManager()


@pytest.mark.asyncio
async def test_create_replay_state(manager):
    """创建重放状态。"""
    state = await manager.create_replay_state(
        run_id="run_001",
        session_id="sess_001",
        total_steps=5,
    )

    assert state.run_id == "run_001"
    assert state.session_id == "sess_001"
    assert len(state.pending_steps) == 5
    assert state.completed_steps == []


@pytest.mark.asyncio
async def test_get_replay_state(manager):
    """获取重放状态。"""
    await manager.create_replay_state(
        run_id="run_001",
        session_id="sess_001",
        total_steps=5,
    )

    state = await manager.get_replay_state("run_001")
    assert state is not None
    assert state.run_id == "run_001"


@pytest.mark.asyncio
async def test_get_steps_to_replay(manager):
    """获取需要重放的步骤。"""
    state = await manager.create_replay_state(
        run_id="run_001",
        session_id="sess_001",
        total_steps=5,
    )

    # 模拟完成前 2 个步骤
    state.completed_steps = [0, 1]
    state.last_completed_step = 1

    steps = manager._get_steps_to_replay(state)
    assert steps == [2, 3, 4]


@pytest.mark.asyncio
async def test_replay(manager):
    """重放执行。"""
    await manager.create_replay_state(
        run_id="run_001",
        session_id="sess_001",
        total_steps=3,
    )

    # 执行重放
    run = await manager.replay("run_001")
    assert run is not None
    assert run.run_id == "run_001"


@pytest.mark.asyncio
async def test_replay_with_executor(manager):
    """带执行器重放。"""
    state = await manager.create_replay_state(
        run_id="run_001",
        session_id="sess_001",
        total_steps=2,
    )
    # 确保 pending_steps 包含所有步骤
    state.pending_steps = [0, 1]
    state.last_completed_step = -1  # 从 -1 开始，这样 0 也会被包含

    executed_steps = []

    async def executor(run_id: str, step_index: int) -> None:
        executed_steps.append(step_index)

    run = await manager.replay("run_001", executor=executor)
    assert run is not None
    assert len(executed_steps) == 2


@pytest.mark.asyncio
async def test_replay_idempotent(manager):
    """幂等重放 — 已完成步骤跳过。"""
    state = await manager.create_replay_state(
        run_id="run_001",
        session_id="sess_001",
        total_steps=3,
    )

    # 标记前 2 个步骤已完成
    state.completed_steps = [0, 1]

    executed_steps = []

    async def executor(run_id: str, step_index: int) -> None:
        executed_steps.append(step_index)

    run = await manager.replay("run_001", executor=executor)
    assert run is not None
    assert len(executed_steps) == 1  # 只执行步骤 2
    assert executed_steps[0] == 2


@pytest.mark.asyncio
async def test_get_replay_summary(manager):
    """获取重放摘要。"""
    await manager.create_replay_state(
        run_id="run_001",
        session_id="sess_001",
        total_steps=5,
    )

    summary = await manager.get_replay_summary("run_001")
    assert summary["run_id"] == "run_001"
    assert summary["total_steps"] == 5
    assert summary["completed_steps"] == 0
    assert summary["pending_steps"] == 5


def test_replay_state_post_init():
    """ReplayState 初始化。"""
    state = ReplayState(run_id="run_001", session_id="sess_001")
    assert state.run_id == "run_001"
    assert state.last_completed_step == 0
    assert state.pending_steps == []
