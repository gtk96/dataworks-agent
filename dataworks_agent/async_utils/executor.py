"""AsyncTaskExecutor — 异步任务执行器。

实现异步处理功能：
1. 任务队列
2. 并发控制
3. 任务状态追踪
4. 重试机制
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class TaskState(StrEnum):
    """任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AsyncTask:
    """异步任务。"""

    task_id: str
    func: Callable[..., Coroutine[Any, Any, Any]]
    args: tuple = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: str = ""
    retries: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    started_at: float = 0
    completed_at: float = 0


class AsyncTaskExecutor:
    """异步任务执行器。

    实现任务队列、并发控制、任务状态追踪、重试机制。
    """

    def __init__(self, max_concurrent: int = 10):
        """
        初始化异步任务执行器。

        Args:
            max_concurrent: 最大并发数
        """
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, AsyncTask] = {}
        self._running: set[str] = set()

    async def submit(
        self,
        task_id: str,
        func: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> AsyncTask:
        """提交任务。"""
        task = AsyncTask(
            task_id=task_id,
            func=func,
            args=args,
            kwargs=kwargs or {},
            max_retries=max_retries,
        )
        self._tasks[task_id] = task
        logger.info("任务已提交: %s", task_id)
        return task

    async def execute(self, task: AsyncTask) -> Any:
        """执行单个任务。"""
        async with self._semaphore:
            task.state = TaskState.RUNNING
            task.started_at = time.time()
            self._running.add(task.task_id)

            try:
                result = await task.func(*task.args, **task.kwargs)
                task.result = result
                task.state = TaskState.COMPLETED
                task.completed_at = time.time()
                logger.info(
                    "任务完成: %s (%.2fs)", task.task_id, task.completed_at - task.started_at
                )
                return result
            except Exception as e:
                task.error = str(e)
                task.retries += 1

                if task.retries < task.max_retries:
                    logger.warning(
                        "任务失败，重试: %s (retry=%d/%d)",
                        task.task_id,
                        task.retries,
                        task.max_retries,
                    )
                    task.state = TaskState.PENDING
                else:
                    task.state = TaskState.FAILED
                    task.completed_at = time.time()
                    logger.error("任务最终失败: %s: %s", task.task_id, e)

                raise
            finally:
                self._running.discard(task.task_id)

    async def execute_all(self) -> list[Any]:
        """执行所有待处理任务。"""
        results = []
        pending_tasks = [task for task in self._tasks.values() if task.state == TaskState.PENDING]

        for task in pending_tasks:
            try:
                result = await self.execute(task)
                results.append(result)
            except Exception:
                results.append(None)

        return results

    def get_task(self, task_id: str) -> AsyncTask | None:
        """获取任务。"""
        return self._tasks.get(task_id)

    def get_pending_tasks(self) -> list[AsyncTask]:
        """获取待处理任务。"""
        return [task for task in self._tasks.values() if task.state == TaskState.PENDING]

    def get_running_tasks(self) -> list[AsyncTask]:
        """获取运行中任务。"""
        return [task for task in self._tasks.values() if task.state == TaskState.RUNNING]

    def get_completed_tasks(self) -> list[AsyncTask]:
        """获取已完成任务。"""
        return [task for task in self._tasks.values() if task.state == TaskState.COMPLETED]

    def get_failed_tasks(self) -> list[AsyncTask]:
        """获取失败任务。"""
        return [task for task in self._tasks.values() if task.state == TaskState.FAILED]

    def cancel_task(self, task_id: str) -> bool:
        """取消任务。"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.state == TaskState.RUNNING:
            task.state = TaskState.CANCELLED
            logger.info("任务已取消: %s", task_id)
            return True

        return False

    def clear(self) -> None:
        """清空任务队列。"""
        self._tasks.clear()
        self._running.clear()

    @property
    def stats(self) -> dict[str, int]:
        """获取统计信息。"""
        return {
            "total": len(self._tasks),
            "pending": len(self.get_pending_tasks()),
            "running": len(self.get_running_tasks()),
            "completed": len(self.get_completed_tasks()),
            "failed": len(self.get_failed_tasks()),
        }
