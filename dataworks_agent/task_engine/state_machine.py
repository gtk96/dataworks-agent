"""异步有限状态机 — 建模任务生命周期管理。

状态转换:
  PENDING → RUNNING → DDL_GEN → TABLE_CRE → ROOT_CHECK
  → DML_WRITE → SCHED_CFG → TESTING → COMPLETED

异常路径:
  任意步骤 → FAILED (不可重试) / RETRY (可重试 max 3 次)
  Cookie 过期 → SUSPENDED → 恢复后从当前步骤续跑
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from dataworks_agent.schemas import TaskStatus

logger = logging.getLogger(__name__)


# 步骤执行顺序
STEP_ORDER = [
    TaskStatus.DDL_GEN,
    TaskStatus.TABLE_CRE,
    TaskStatus.ROOT_CHECK,
    TaskStatus.DML_WRITE,
    TaskStatus.SCHED_CFG,
    TaskStatus.TESTING,
]

# 步骤显示名称
STEP_LABELS = {
    TaskStatus.DDL_GEN: "DDL 生成",
    TaskStatus.TABLE_CRE: "建表执行",
    TaskStatus.ROOT_CHECK: "词根校验",
    TaskStatus.DML_WRITE: "DML 写入",
    TaskStatus.SCHED_CFG: "调度配置",
    TaskStatus.TESTING: "测试验证",
}

# 不可重试的错误
NON_RETRYABLE = [
    "root_check_failed",
    "permission_denied",
    "sql_syntax_error",
    "table_already_exists",
]


class StepHandler:
    """步骤处理器 — 封装步骤的执行、验证、回滚逻辑。"""

    def __init__(
        self,
        step: TaskStatus,
        execute: Callable,
        validate: Callable | None = None,
        rollback: Callable | None = None,
    ) -> None:
        self.step = step
        self.label = STEP_LABELS.get(step, step.value)
        self.execute = execute
        self.validate = validate
        self.rollback = rollback


class TaskStateMachine:
    """建模任务异步状态机。"""

    MAX_RETRIES = 3
    BASE_DELAY = 2  # 秒

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.status: TaskStatus = TaskStatus.PENDING
        self.current_step_index: int = 0
        self.retry_count: int = 0
        self.steps: list[StepHandler] = []
        self.error_message: str = ""
        self._cancelled: bool = False
        self._suspended: bool = False
        self._event_queue: asyncio.Queue = asyncio.Queue()

    def add_step(self, handler: StepHandler) -> None:
        self.steps.append(handler)

    def cancel(self) -> None:
        self._cancelled = True

    def suspend(self) -> None:
        self._suspended = True

    def resume(self) -> None:
        self._suspended = False

    async def emit_event(self, event: str, data: dict | None = None) -> None:
        """发布事件到 SSE 队列 + EventBus（dashboard WS 推送源）。"""
        await self._event_queue.put(
            {
                "event": event,
                "task_id": self.task_id,
                "step": self.status.value,
                "status": self.status.value,
                "message": STEP_LABELS.get(self.status, ""),
                "data": data or {},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        # 异步 publish 给 EventBus（dashboard WS 订阅源）。try/except 防止
        # 监控推送故障拖垮状态机；create_task 把发布动作 task 化，避免阻塞
        # emit_event 主链路（监控 handler 若是 async 不会拖慢状态机推进）。
        # 注意：失败时记录 debug 级别（不污染告警日志），事件总线 handler
        # 内部已有异常隔离（cache/events.py:57-61）。
        try:
            from dataworks_agent.cache.events import Event, EventType, get_event_bus

            event = Event(
                event_type=EventType.TASK_STATUS_CHANGED,
                source=self.task_id,
                data={
                    "task_id": self.task_id,
                    "status": self.status.value,
                    "event": event,
                    "data": data or {},
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            async def _publish() -> None:
                try:
                    await get_event_bus().publish_async(event)
                except Exception as e:
                    logger.debug("TASK_STATUS_CHANGED 异步发布失败: %s", e)

            asyncio.create_task(_publish())  # noqa: RUF006 — fire-and-forget 是设计意图（事件总线不应阻塞状态机）
        except Exception as e:
            logger.debug("TASK_STATUS_CHANGED 调度失败（不影响状态机）: %s", e)

    async def run(self) -> bool:
        """执行状态机 — 从 PENDING 开始逐个步骤推进到 COMPLETED。"""
        if not self.steps:
            logger.error("状态机 %s 没有注册步骤", self.task_id)
            return False

        self.status = TaskStatus.RUNNING
        await self.emit_event("start", {"total_steps": len(self.steps)})

        for i, handler in enumerate(self.steps):
            if self._cancelled:
                self.status = TaskStatus.CANCELLED
                await self.emit_event("done", {"status": "cancelled"})
                return False

            if self._suspended:
                self.status = TaskStatus.SUSPENDED
                await self.emit_event("done", {"status": "suspended"})
                return False

            self.status = handler.step
            self.current_step_index = i
            await self.emit_event("step", {"step_label": handler.label, "step_index": i + 1})

            try:
                # 执行步骤
                await handler.execute()
            except Exception as e:
                error_type = _classify_error(e)
                logger.error("步骤 %s 失败: %s (%s)", handler.label, e, error_type)

                if error_type in NON_RETRYABLE:
                    self.status = TaskStatus.FAILED
                    self.error_message = str(e)
                    await self.emit_event("error", {"error": str(e), "retryable": False})
                    return False

                # 可重试 — 指数退避
                if self.retry_count >= self.MAX_RETRIES:
                    self.status = TaskStatus.FAILED
                    self.error_message = f"重试 {self.MAX_RETRIES} 次后仍失败: {e}"
                    await self.emit_event(
                        "error", {"error": self.error_message, "retryable": False}
                    )
                    return False

                self.retry_count += 1
                delay = self.BASE_DELAY * (2 ** (self.retry_count - 1))
                logger.info(
                    "步骤 %s 第 %d 次重试 (延迟 %.1fs)", handler.label, self.retry_count, delay
                )
                await self.emit_event(
                    "progress", {"message": f"重试中 ({self.retry_count}/{self.MAX_RETRIES})"}
                )
                await asyncio.sleep(delay)

                try:
                    await handler.execute()
                except Exception as e2:
                    self.status = TaskStatus.FAILED
                    self.error_message = str(e2)
                    await self.emit_event("error", {"error": str(e2)})
                    return False

            # 步骤成功
            if handler.validate:
                try:
                    await handler.validate()
                except Exception as e:
                    self.status = TaskStatus.FAILED
                    self.error_message = f"验证失败: {e}"
                    await self.emit_event("error", {"error": self.error_message})
                    return False

            await self.emit_event(
                "progress",
                {
                    "step_label": handler.label,
                    "completed": True,
                    "progress_pct": int((i + 1) / len(self.steps) * 100),
                },
            )

        self.status = TaskStatus.COMPLETED
        await self.emit_event("done", {"status": "completed"})
        return True

    def get_event_queue(self) -> asyncio.Queue:
        return self._event_queue


def _classify_error(e: Exception) -> str:
    """将异常归类为可重试/不可重试类型。"""
    msg = str(e).lower()
    if "csrf_token" in msg or "token" in msg:
        return "csrf_token_expired"
    if "timeout" in msg or "timed out" in msg:
        return "network_timeout"
    if "unavailable" in msg or "503" in msg or "502" in msg:
        return "bff_service_unavailable"
    if "connection" in msg or "refused" in msg:
        return "mcp_connection_lost"
    if "locked" in msg:
        return "sqlite_locked"
    if "permission" in msg or "denied" in msg or "forbidden" in msg:
        return "permission_denied"
    if "syntax" in msg:
        return "sql_syntax_error"
    if "already exists" in msg:
        return "table_already_exists"
    if "root" in msg:
        return "root_check_failed"
    return "unknown"
