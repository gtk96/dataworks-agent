"""AsyncTaskExecutor 单元测试 — 异步任务执行器。"""

import asyncio

import pytest

from dataworks_agent.async_utils.executor import AsyncTask, AsyncTaskExecutor, TaskState


@pytest.fixture
def executor():
    """创建 AsyncTaskExecutor 实例。"""
    return AsyncTaskExecutor(max_concurrent=5)


@pytest.mark.asyncio
async def test_submit(executor):
    """提交任务。"""

    async def dummy_func():
        return "result"

    task = await executor.submit("task_001", dummy_func)
    assert task.task_id == "task_001"
    assert task.state == TaskState.PENDING


@pytest.mark.asyncio
async def test_execute(executor):
    """执行任务。"""

    async def dummy_func():
        return "result"

    task = await executor.submit("task_001", dummy_func)
    result = await executor.execute(task)

    assert result == "result"
    assert task.state == TaskState.COMPLETED


@pytest.mark.asyncio
async def test_execute_with_args(executor):
    """执行带参数的任务。"""

    async def add(a: int, b: int) -> int:
        return a + b

    task = await executor.submit("task_001", add, args=(1, 2))
    result = await executor.execute(task)

    assert result == 3


@pytest.mark.asyncio
async def test_execute_with_kwargs(executor):
    """执行带关键字参数的任务。"""

    async def greet(name: str, greeting: str = "Hello") -> str:
        return f"{greeting}, {name}!"

    task = await executor.submit("task_001", greet, kwargs={"name": "World"})
    result = await executor.execute(task)

    assert result == "Hello, World!"


@pytest.mark.asyncio
async def test_execute_all(executor):
    """执行所有任务。"""

    async def dummy_func():
        return "result"

    await executor.submit("task_001", dummy_func)
    await executor.submit("task_002", dummy_func)

    results = await executor.execute_all()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_get_task(executor):
    """获取任务。"""

    async def dummy_func():
        return "result"

    await executor.submit("task_001", dummy_func)
    task = executor.get_task("task_001")

    assert task is not None
    assert task.task_id == "task_001"


@pytest.mark.asyncio
async def test_cancel_task(executor):
    """取消任务。"""

    async def slow_func():
        await asyncio.sleep(10)
        return "result"

    task = await executor.submit("task_001", slow_func)

    # 启动任务但不等待完成（明确 fire-and-forget，仅用于测试）
    asyncio.create_task(executor.execute(task))  # noqa: RUF006 - 测试无需保留 reference
    await asyncio.sleep(0.1)

    # 取消任务
    result = executor.cancel_task("task_001")
    assert result is True


@pytest.mark.asyncio
async def test_stats(executor):
    """获取统计信息。"""

    async def dummy_func():
        return "result"

    await executor.submit("task_001", dummy_func)
    await executor.submit("task_002", dummy_func)

    stats = executor.stats
    assert stats["total"] == 2
    assert stats["pending"] == 2


def test_clear(executor):
    """清空任务队列。"""
    executor._tasks["task_001"] = AsyncTask(task_id="task_001", func=lambda: None)
    executor.clear()
    assert len(executor._tasks) == 0


def test_task_state():
    """TaskState 枚举。"""
    assert TaskState.PENDING == "pending"
    assert TaskState.RUNNING == "running"
    assert TaskState.COMPLETED == "completed"
    assert TaskState.FAILED == "failed"
    assert TaskState.CANCELLED == "cancelled"
