"""Runtime 服务 — 生命周期操作。

实现 Requirement 16 和 29：无状态 agent 与重放续跑、Runtime 协议对象与生命周期操作。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from dataworks_agent.runtime.session import (
    Artifact,
    Checkpoint,
    Event,
    EventType,
    Run,
    RunStatus,
    Session,
)

logger = logging.getLogger(__name__)


class RuntimeService:
    """Runtime 服务 — 生命周期操作。

    实现 Requirement 16：无状态 agent 与重放续跑。
    实现 Requirement 29：Runtime 协议对象与生命周期操作。
    """

    def __init__(self) -> None:
        self._active_runs: dict[str, Run] = {}

    def create_session(self, task_id: str, task_type: str = "modeling") -> Session:
        """创建会话。"""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = Session(
            session_id=session_id,
            task_id=task_id,
            task_type=task_type,
        )
        logger.info("创建会话: %s (task=%s)", session_id, task_id)
        return session

    async def start_run(
        self,
        session_id: str,
        request: dict[str, Any],
        actor: str = "",
    ) -> Run:
        """启动运行。"""
        run = Run(
            run_id="",
            session_id=session_id,
            request=request,
            actor=actor,
        )
        run.status = RunStatus.RUNNING
        self._active_runs[run.run_id] = run

        # 记录事件
        event = Event(
            event_id="",
            run_id=run.run_id,
            event_type=EventType.STEP_START,
            payload={"action": "start_run", "request": request},
        )
        await self._log_event(event)

        logger.info("启动运行: %s (session=%s)", run.run_id, session_id)
        return run

    async def get_run(self, run_id: str) -> Run | None:
        """获取运行状态。"""
        # 先从内存缓存查找
        if run_id in self._active_runs:
            return self._active_runs[run_id]

        # 从 Event_Log 重建
        return await self._rebuild_run(run_id)

    async def cancel_run(self, run_id: str) -> bool:
        """取消运行。"""
        run = self._active_runs.get(run_id)
        if not run:
            return False

        run.status = RunStatus.CANCELLED
        run.completed_at = datetime.now(UTC).isoformat()

        # 记录事件
        event = Event(
            event_id="",
            run_id=run_id,
            event_type=EventType.INTERRUPT,
            payload={"action": "cancel"},
        )
        await self._log_event(event)

        logger.info("运行已取消: %s", run_id)
        return True

    async def interrupt_run(self, run_id: str, payload: dict[str, Any]) -> bool:
        """中断运行（等待审批）。"""
        run = self._active_runs.get(run_id)
        if not run:
            return False

        run.status = RunStatus.SUSPENDED

        # 记录事件
        event = Event(
            event_id="",
            run_id=run_id,
            event_type=EventType.INTERRUPT,
            payload={"action": "interrupt", "data": payload},
        )
        await self._log_event(event)

        logger.info("运行已中断: %s", run_id)
        return True

    async def resume_run(self, run_id: str, decision: dict[str, Any]) -> bool:
        """恢复运行。"""
        run = self._active_runs.get(run_id)
        if not run or run.status != RunStatus.SUSPENDED:
            return False

        run.status = RunStatus.RUNNING

        # 记录事件
        event = Event(
            event_id="",
            run_id=run_id,
            event_type=EventType.RESUME,
            payload={"action": "resume", "decision": decision},
        )
        await self._log_event(event)

        logger.info("运行已恢复: %s", run_id)
        return True

    async def retry_run(self, run_id: str) -> bool:
        """重试运行。"""
        run = self._active_runs.get(run_id)
        if not run or run.status != RunStatus.FAILED:
            return False

        run.status = RunStatus.RUNNING
        run.error = ""
        run.started_at = datetime.now(UTC).isoformat()

        # 记录事件
        event = Event(
            event_id="",
            run_id=run_id,
            event_type=EventType.RESUME,
            payload={"action": "retry"},
        )
        await self._log_event(event)

        logger.info("运行已重试: %s", run_id)
        return True

    async def complete_run(
        self,
        run_id: str,
        result: dict[str, Any],
        artifacts: list[Artifact] | None = None,
    ) -> bool:
        """完成运行。"""
        run = self._active_runs.get(run_id)
        if not run:
            return False

        run.status = RunStatus.COMPLETED
        run.result = result
        run.completed_at = datetime.now(UTC).isoformat()

        # 记录事件
        event = Event(
            event_id="",
            run_id=run_id,
            event_type=EventType.STEP_COMPLETE,
            payload={"action": "complete_run", "result": result},
        )
        await self._log_event(event)

        # 记录产物
        if artifacts:
            for artifact in artifacts:
                await self._log_artifact(artifact)

        logger.info("运行已完成: %s", run_id)
        return True

    async def fail_run(self, run_id: str, error: str) -> bool:
        """标记运行失败。"""
        run = self._active_runs.get(run_id)
        if not run:
            return False

        run.status = RunStatus.FAILED
        run.error = error
        run.completed_at = datetime.now(UTC).isoformat()

        # 记录事件
        event = Event(
            event_id="",
            run_id=run_id,
            event_type=EventType.ERROR,
            payload={"action": "fail_run", "error": error},
        )
        await self._log_event(event)

        logger.info("运行已失败: %s: %s", run_id, error)
        return True

    async def stream_events(
        self,
        run_id: str,
        after_seq: int = 0,
    ) -> AsyncIterator[Event]:
        """流式返回事件（SSE）。"""
        # 简化实现：返回内存中的事件
        # 实际应从 Event_Log 读取
        events = await self._get_events(run_id, after_seq)
        for event in events:
            yield event

    async def create_checkpoint(
        self,
        run_id: str,
        step_index: int,
        state: dict[str, Any],
    ) -> Checkpoint:
        """创建检查点。"""
        checkpoint = Checkpoint(
            checkpoint_id="",
            run_id=run_id,
            step_index=step_index,
            state=state,
        )

        # 记录到 Event_Log
        event = Event(
            event_id="",
            run_id=run_id,
            event_type=EventType.STEP_COMPLETE,
            payload={
                "action": "create_checkpoint",
                "checkpoint_id": checkpoint.checkpoint_id,
                "step_index": step_index,
            },
        )
        await self._log_event(event)

        logger.info(
            "检查点已创建: %s (run=%s, step=%d)", checkpoint.checkpoint_id, run_id, step_index
        )
        return checkpoint

    async def replay_from_checkpoint(self, run_id: str) -> Run | None:
        """从检查点重放。"""
        # 查找最近的检查点
        checkpoint = await self._get_latest_checkpoint(run_id)
        if not checkpoint:
            logger.warning("未找到检查点: %s", run_id)
            return None

        # 重建运行状态
        run = await self._rebuild_run(run_id)
        if not run:
            return None

        # 从检查点恢复
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(UTC).isoformat()

        logger.info("从检查点重放: %s (step=%d)", run_id, checkpoint.step_index)
        return run

    # ── 内部方法 ──

    async def _log_event(self, event: Event) -> None:
        """记录事件到 Event_Log。"""
        # 简化实现：打印日志
        # 实际应写入 Event_Log 表
        logger.debug(
            "Event: %s (run=%s, type=%s)", event.event_id, event.run_id, event.event_type.value
        )

    async def _log_artifact(self, artifact: Artifact) -> None:
        """记录产物。"""
        # 简化实现：打印日志
        # 实际应写入 artifacts 表
        logger.debug(
            "Artifact: %s (run=%s, type=%s)",
            artifact.artifact_id,
            artifact.run_id,
            artifact.artifact_type,
        )

    async def _get_events(self, run_id: str, after_seq: int) -> list[Event]:
        """获取事件列表。"""
        # 简化实现：返回空列表
        return []

    async def _get_latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        """获取最近的检查点。"""
        # 简化实现：返回 None
        return None

    async def _rebuild_run(self, run_id: str) -> Run | None:
        """从 Event_Log 重建运行状态。"""
        # 简化实现：返回 None
        return None
