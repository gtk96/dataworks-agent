"""任务队列 — 每 IP 独立队列，先进先出调度。"""

from __future__ import annotations

import logging

from dataworks_agent.state import app_state

logger = logging.getLogger(__name__)


class TaskQueueManager:
    """多用户任务队列管理器。"""

    @staticmethod
    async def enqueue(ip: str, task_id: str) -> None:
        """将任务放入用户专属队列。"""
        queue = app_state.get_task_queue(ip)
        await queue.put(task_id)
        logger.debug("任务 %s 加入队列 (IP: %s), 队列长度 %d", task_id, ip, queue.qsize())

    @staticmethod
    async def dequeue(ip: str) -> str:
        """从用户队列取出下一个任务（阻塞等待）。"""
        queue = app_state.get_task_queue(ip)
        task_id = await queue.get()
        logger.debug("任务 %s 出队 (IP: %s)", task_id, ip)
        return task_id

    @staticmethod
    def queue_size(ip: str) -> int:
        queue = app_state.get_task_queue(ip)
        return queue.qsize()

    @staticmethod
    def all_queue_sizes() -> dict[str, int]:
        return {ip: q.qsize() for ip, q in app_state.task_queues.items()}
