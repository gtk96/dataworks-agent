"""情景记忆 — 持久化存储历史任务执行记录。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"access_key_id", "access_key_secret", "cookie", "token", "password", "secret"}


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """过滤敏感字段，避免将凭证写入持久层。"""
    return {k: ("***REDACTED***" if k.lower() in _SENSITIVE_KEYS else v) for k, v in params.items()}


@dataclass
class ExecutionEpisode:
    """一次自主任务执行的完整记录。"""

    episode_id: str
    task_type: str
    intent: str
    params: dict[str, Any]
    plan_steps: list[dict[str, Any]]
    execution_log: list[dict[str, Any]]
    final_status: str
    verification_result: dict[str, Any] | None
    error_message: str | None
    duration_seconds: float
    created_at: datetime
    lessons_learned: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "task_type": self.task_type,
            "intent": self.intent,
            "params": _sanitize_params(self.params),
            "plan_steps": self.plan_steps,
            "execution_log": self.execution_log,
            "final_status": self.final_status,
            "verification_result": self.verification_result or {},
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat(),
            "lessons_learned": self.lessons_learned,
        }


class EpisodicMemory:
    """基于 SQLite 的情景记忆存储。

    Args:
        session_factory: 返回 SQLAlchemy Session 的可调用对象。
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat()

    async def store_episode(self, episode: ExecutionEpisode) -> None:
        """将 episode 写入 SQLite。若已存在则更新。"""
        from dataworks_agent.db.models import ExecutionEpisodeModel

        session = self._session_factory()
        try:
            payload = episode.to_dict()
            row = session.get(ExecutionEpisodeModel, episode.episode_id)
            if row is None:
                row = ExecutionEpisodeModel(episode_id=episode.episode_id)

            row.task_type = episode.task_type
            row.intent = payload["intent"]
            row.params_json = json.dumps(payload["params"], ensure_ascii=False)
            row.plan_steps_json = json.dumps(payload["plan_steps"], ensure_ascii=False)
            row.execution_log_json = json.dumps(payload["execution_log"], ensure_ascii=False)
            row.final_status = episode.final_status
            row.verification_result_json = json.dumps(
                payload["verification_result"], ensure_ascii=False
            )
            row.error_message = episode.error_message or ""
            row.duration_seconds = episode.duration_seconds
            row.lessons_learned_json = json.dumps(payload["lessons_learned"], ensure_ascii=False)
            if row.created_at == "":
                row.created_at = self._now_iso()

            session.add(row)
            session.commit()
            logger.info(
                "Episode stored: %s (task_type=%s, status=%s)",
                episode.episode_id,
                episode.task_type,
                episode.final_status,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def get_episode(self, episode_id: str) -> ExecutionEpisode | None:
        """按 ID 获取单个 episode。"""
        from dataworks_agent.db.models import ExecutionEpisodeModel

        session = self._session_factory()
        try:
            row = session.get(ExecutionEpisodeModel, episode_id)
            if row is None:
                return None
            return self._row_to_episode(row)
        finally:
            session.close()

    async def get_episodes(
        self, task_type: str | None = None, status: str | None = None
    ) -> list[ExecutionEpisode]:
        """按条件查询 episodes。"""
        from dataworks_agent.db.models import ExecutionEpisodeModel

        session = self._session_factory()
        try:
            stmt = select(ExecutionEpisodeModel)
            if task_type:
                stmt = stmt.where(ExecutionEpisodeModel.task_type == task_type)
            if status:
                stmt = stmt.where(ExecutionEpisodeModel.final_status == status)
            stmt = stmt.order_by(ExecutionEpisodeModel.created_at.desc())
            rows = session.execute(stmt).scalars().all()
            return [self._row_to_episode(row) for row in rows]
        finally:
            session.close()

    async def get_success_patterns(self, task_type: str) -> list[ExecutionEpisode]:
        """获取指定任务类型的成功案例。"""
        return await self.get_episodes(task_type=task_type, status="verified")

    async def get_failure_patterns(self, task_type: str) -> list[ExecutionEpisode]:
        """获取指定任务类型的失败案例。"""
        return await self.get_episodes(task_type=task_type, status="failed")

    def _row_to_episode(self, row: Any) -> ExecutionEpisode:
        return ExecutionEpisode(
            episode_id=row.episode_id,
            task_type=row.task_type,
            intent=row.intent,
            params=json.loads(row.params_json or "{}"),
            plan_steps=json.loads(row.plan_steps_json or "[]"),
            execution_log=json.loads(row.execution_log_json or "[]"),
            final_status=row.final_status,
            verification_result=json.loads(row.verification_result_json or "{}")
            if row.verification_result_json
            else None,
            error_message=row.error_message or None,
            duration_seconds=row.duration_seconds or 0.0,
            created_at=datetime.fromisoformat(row.created_at)
            if row.created_at
            else datetime.now(UTC),
            lessons_learned=json.loads(row.lessons_learned_json or "[]"),
        )
