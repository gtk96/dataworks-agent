"""Intent Log — 写操作前的意图记录，防止进程崩溃后丢失操作证据。

关键流程:
  1. BFF/CDP 写操作发出前 → INSERT intent 日志
  2. 操作返回成功 → UPDATE intent → completed
  3. 进程崩溃恢复 → 扫描 dangling intent → 查询 BFF 确认 → 标记/重试
"""

from __future__ import annotations

import json
import logging
from datetime import UTC

from sqlalchemy import select

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import TaskStepLogModel

logger = logging.getLogger(__name__)


async def log_intent(
    task_id: str,
    step_name: str,
    operation: str,
    target: str,
    payload: dict | None = None,
) -> int:
    """在调用 BFF/CDP 前记录意图，返回步骤日志 ID。"""
    with SessionLocal() as db:
        log = TaskStepLogModel(
            task_id=task_id,
            step_name=step_name,
            status="intent",
            intent_operation=operation,
            intent_target=target,
            intent_payload_json=json.dumps(payload or {}, ensure_ascii=False),
            created_at=_now(),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        log_id = log.id
    logger.debug(
        "Intent 记录: task=%s step=%s op=%s target=%s id=%d",
        task_id,
        step_name,
        operation,
        target,
        log_id,
    )
    return log_id


async def confirm_intent(log_id: int, result: dict | None = None) -> None:
    """BFF 返回成功 → 将 intent 更新为 completed。"""
    with SessionLocal() as db:
        log = db.get(TaskStepLogModel, log_id)
        if log:
            log.status = "completed"
            log.result_json = json.dumps(result or {}, ensure_ascii=False)
            db.commit()
    logger.debug("Intent 确认: id=%d", log_id)


async def fail_intent(log_id: int, error: str) -> None:
    """BFF 返回失败 → 标记 intent 为 failed。"""
    with SessionLocal() as db:
        log = db.get(TaskStepLogModel, log_id)
        if log:
            log.status = "failed"
            log.error = error
            db.commit()
    logger.debug("Intent 失败: id=%d error=%s", log_id, error)


async def dispose_intent(intent_id: int, action: str) -> dict | None:
    """人工协调处置 dangling intent。"""
    with SessionLocal() as db:
        log = db.get(TaskStepLogModel, intent_id)
        if not log or log.status != "intent":
            return None

        if action == "confirm_success":
            log.status = "completed"
            log.result_json = json.dumps(
                {"disposition": "manual_confirm_success"},
                ensure_ascii=False,
            )
            log.error = ""
        elif action == "confirm_failed":
            log.status = "failed"
            log.error = "人工确认失败"
        elif action == "retry":
            log.status = "failed"
            log.error = "人工标记重试（请在建模任务页对该任务执行重试）"
        else:
            return None

        db.commit()
        return {
            "intent_id": log.id,
            "task_id": log.task_id,
            "step_name": log.step_name,
            "action": action,
        }


async def detect_dangling_intents() -> list[dict]:
    """启动恢复: 扫描未确认的 intent 记录。"""
    with SessionLocal() as db:
        stmt = select(TaskStepLogModel).where(TaskStepLogModel.status == "intent")
        dangling = db.execute(stmt).scalars().all()
        return [
            {
                "id": d.id,
                "task_id": d.task_id,
                "step_name": d.step_name,
                "operation": d.intent_operation,
                "target": d.intent_target,
                "payload": json.loads(d.intent_payload_json),
                "created_at": d.created_at,
            }
            for d in dangling
        ]


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()
