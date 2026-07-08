"""日志 API — 任务日志查询。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from dataworks_agent.db.database import SessionLocal
from dataworks_agent.db.models import TaskStepLogModel

router = APIRouter()


@router.get("")
async def query_logs(
    task_id: str = Query(None),
    level: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """查询任务日志（按 task_id/level 筛选）。"""
    from sqlalchemy import select

    with SessionLocal() as db:
        stmt = select(TaskStepLogModel).order_by(TaskStepLogModel.created_at.desc()).limit(limit)

        if task_id:
            stmt = stmt.where(TaskStepLogModel.task_id == task_id)
        if level:
            stmt = stmt.where(TaskStepLogModel.error.like(f"%{level}%"))

        logs = db.execute(stmt).scalars().all()

        return {
            "logs": [
                {
                    "id": entry.id,
                    "task_id": entry.task_id,
                    "step_name": entry.step_name,
                    "status": entry.status,
                    "operation": entry.intent_operation,
                    "target": entry.intent_target,
                    "error": entry.error,
                    "duration_ms": entry.duration_ms,
                    "created_at": entry.created_at,
                }
                for entry in logs
            ]
        }
